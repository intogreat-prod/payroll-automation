"""
slicer.py
---------
Slices one attendance row into payroll headers.

Scenarios (routing in payroll_premiums._compute_breakdown, in this order)
    0. Detailed Status "Request Pending" -> breakdown_not_computed()       (Pending Request)
    1. Present + Weekly Off / Holiday   -> breakdown_premium()
           paid <= 8h -> breakdown_premium_no_ot()   paid > 8h -> breakdown_premium_ot()
    2. Holiday, not Present / Weekly Off -> breakdown_holiday_unworked()   (Ord 8)
    3. Unpaid Leave (not Present)        -> breakdown_not_computed()       (SKIPPED)
    4. Overtime but not Present          -> breakdown_not_computed()       (CHECK)
    5. Ord day                           -> breakdown_ordinary_no_ot() / breakdown_ordinary_ot()

Both follow the same steps:
    1. Start      : Clock In or Shift start (policy decides)
    2. Work pieces: ordinary / base -> first 4 paid hours | 1h unpaid BREAK | remaining paid hours
                    OT              -> computed as is: no break, no deduction (any length)
    3. Each piece : cut at midnight, tag with day code, split regular / NSD

Day code: Ord, LH, SH, LH-SH, RD, RD-LH, RD-SH, RD-LH-SH
    holiday  = calendar day the piece ACTUALLY happens on
    rest day = the whole SHIFT ("Weekly Off" in the row's own Status Final)
               -> a night shift into tomorrow's weekly off stays Ord after midnight
               -> EXCEPT OT: OT landing on the employee's weekly off date is RD

Hours (Final Work Duration) already has the break deducted. It decides HOW MANY
hours are paid; the start + break decide WHERE they land. The break is never
paid and never NSD. On OT days, Hours INCLUDES the OT.

Checks
    is_missing_clock_in() -> clock policy + no Clock In -> "MISSING CLOCK IN", not computed
    check_logs()          -> "CHECK: No Clock Out." / "CHECK: Clock In-Out over 16h" (remark only)
    snap_early_start()    -> early Clock In BEFORE NSD on a shift that runs into NSD -> Shift start
    snap_late_start()     -> late Clock In -> end lined up with Clock Out (seconds only)
    finish_result()       -> blank Policy with paid hours -> Breakdown Valid False, "Blank policy."
    check_attendance()    -> "CHECK: ..." flags in Detailed Remarks (row still sliced)
    remove_overlap()      -> OT window part inside ordinary hours is cut out,
                             the cut OT moves after the last work ("OVERLAP" remark)

allocate() is the shared loop. OT reuses it with suffix "-OT" (allocate_ot).
Debug IDs live in debug_ids.py.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd

from features.payroll.premiums.debug_ids import (
    DEBUG_ORD_NO_OT,
    DEBUG_ORD_OT,
    DEBUG_PREMIUM_NO_OT,
    DEBUG_PREMIUM_OT,
    is_debug,
)
from features.payroll.premiums.helpers import (
    BREAK_AFTER_HOURS,
    BREAK_HOURS,
    MAX_ORDINARY_HOURS,
    ZERO_DURATION,
    build_work_pieces,
    duration_to_hm,
    duration_to_seconds,
    format_duration,
    get_clock_window,
    get_shift_window,
    is_missing,
    normalize_text,
    parse_clock_time,
    parse_duration,
    parse_work_date,
    seconds_to_duration,
)
from features.payroll.premiums.holiday import (
    ND_SUFFIX,
    OT_SUFFIX,
    build_day_segments,
    build_headers,
    ORDINARY_CODE,
    SCENARIO_RD,
    SCENARIO_RD_HOL,
    get_day_code,
    is_late,
    is_rest_day,
)
from features.payroll.premiums.nsd import calculate_nsd_duration, split_nsd
from features.payroll.premiums.policy import PolicyRule, get_policy_rule, get_work_start

# Ord, Ord-ND, Ord-OT, Ord-ND-OT, LH, ..., RD, RD-ND, RD-OT, RD-ND-OT, RD-LH, ...
ALL_HEADERS = build_headers(("", ND_SUFFIX, OT_SUFFIX, f"{ND_SUFFIX}{OT_SUFFIX}"))

# Attendance checks
MAX_CLOCK_SHIFT_GAP = timedelta(hours=4)    # Clock In this far from the shift start -> flag
CLOCK_TOLERANCE = timedelta(minutes=15)     # Hours may exceed Clock In-Out by this much

# Break (ordinary / base hours only — OT never has a break)
ORD_BREAK_AFTER = timedelta(hours=BREAK_AFTER_HOURS)    # after 4 paid hours
BREAK_LENGTH = timedelta(hours=BREAK_HOURS)

# Clock seconds can make pieces touch by a few seconds -> not worth a remark
MIN_REMARK = timedelta(minutes=1)

# Clock In -> Clock Out longer than this -> possible missing clock out (remark only)
MAX_CLOCK_SPAN = timedelta(hours=16)

# Late snap: the most the start may move to line the end up with Clock Out
MAX_LATE_SNAP = timedelta(minutes=1)

Window = tuple[datetime, datetime]


# ============================================================
# SHARED LOOP
# ============================================================
def allocate(
    start: datetime,
    end: datetime,
    compute_nsd: bool,
    holiday_lookup: dict[date, str],
    values: dict[str, timedelta],
    suffix: str = "",
    rest_day: bool = False,
    rest_dates: Optional[set[date]] = None,
) -> list[str]:
    """
    Add every second of start-end to the right header in `values`.
    Returns a short trace per segment for Detailed Remarks.
    An unknown code raises KeyError on purpose — a silent zero is worse.

    Example (Sep 1 is Legal, NSD on):
        Aug 31 21:00 - Sep 1 01:00 ->
            Ord += 1h, Ord-ND += 2h, LH-ND += 1h
            trace: ["21:00-00:00 Ord 1:00 ND 2:00", "00:00-01:00 LH 0:00 ND 1:00"]
    Example (weekly off row, suffix "-OT"):
        06:00 - 10:00 -> RD-OT += 4h
    """
    trace = []

    # takes care of day transition (midnight) + day code (Ord / holiday / rest day)
    for seg_start, seg_end, code in build_day_segments(start, end, holiday_lookup, rest_day, rest_dates):
        regular, nsd = split_nsd(seg_start, seg_end, compute_nsd)
        values[f"{code}{suffix}"] += regular
        values[f"{code}{ND_SUFFIX}{suffix}"] += nsd
        trace.append(
            f"{seg_start:%H:%M}-{seg_end:%H:%M} {code}{suffix} "
            f"{duration_to_hm(regular)} ND {duration_to_hm(nsd)}"
        )

    return trace


def allocate_with_break(
    start: datetime,
    paid: timedelta,
    rule: PolicyRule,
    holiday_lookup: dict[date, str],
    values: dict[str, timedelta],
    suffix: str = "",
    rest_day: bool = False,
    break_after: timedelta = ORD_BREAK_AFTER,
    rest_dates: Optional[set[date]] = None,
) -> tuple[list[str], list[Window]]:
    """
    Lay paid hours around the 1h unpaid break, then allocate each piece.
    Returns (trace, work pieces). The last piece's end = where the work stops.
    Ordinary / base hours only (break after 4h). OT uses allocate_ot() instead.

    Example (start 22:00, paid 8h):
        22:00-02:00 Ord 4:00 | 02:00-03:00 BREAK | 03:00-07:00 Ord 4:00
    Example (start 22:00, paid 4h):
        22:00-02:00 Ord 4:00   (stopped before the break)
    """
    # Separate work hours segment from break
    work_pieces, break_window = build_work_pieces(
        start, paid, rule.has_break, break_after=break_after, break_length=BREAK_LENGTH,
    )

    trace = []
    for piece_start, piece_end in work_pieces:

        # Break work segment more (nsd, transition)
        trace += allocate(piece_start, piece_end, rule.compute_nsd, holiday_lookup, values, suffix, rest_day, rest_dates)

        # Break window
        if break_window and piece_end == break_window[0]:
            trace.append(f"{break_window[0]:%H:%M}-{break_window[1]:%H:%M} BREAK")

    return trace, work_pieces


def allocate_ot(
    start: datetime,
    paid: timedelta,
    rule: PolicyRule,
    holiday_lookup: dict[date, str],
    values: dict[str, timedelta],
    rest_day: bool = False,
    rest_dates: Optional[set[date]] = None,
) -> tuple[list[str], Window]:
    """
    OT hours, computed as is: one straight block, no break, no deduction.
    Still cut at midnight, tagged with the day code and split regular / NSD.
    rest_dates: the employee's weekly off dates -> OT on those dates is RD-OT.
    Returns (trace, (start, end)).

    Example (start 06:00, paid 12h, weekly off):
        06:00-18:00 RD-OT 12:00
    """
    end = start + paid
    trace = allocate(start, end, rule.compute_nsd, holiday_lookup, values, OT_SUFFIX, rest_day, rest_dates)
    return trace, (start, end)


def count_breaks(pieces: list[Window]) -> timedelta:
    """One unpaid break between every two work pieces. Example: 2 pieces -> 1:00"""
    return BREAK_LENGTH * max(len(pieces) - 1, 0)


# ============================================================
# CHECKS
# ============================================================
def snap_late_start(
    row: pd.Series,
    rule: PolicyRule,
    start: datetime,
    paid: timedelta,
) -> tuple[datetime, list[str]]:
    """
    Late rows only: line the end of the work up with Clock Out.
    Hours is stored in whole minutes, so the dropped seconds would come off the
    END of the shift. For a late arrival they belong to the START instead.

    Applies only when ALL are true:
        Is Late = Yes, clock-based policy, Clock Out present,
        and the gap (Clock Out - planned end) is > 0 and < 1 minute.
    Capped rows (gap of hours) and on-time rows are never touched.
    The caller only uses this on no-OT paths (post-shift OT ends at Clock Out).

    Planned end = start + paid + break (1h if paid > 4h and the policy has a break).

    Example (IE0-1138 Oct 31: Clock In 16:23:29, Clock Out 01:00:20, paid 7:36):
        planned end 00:59:29, Clock Out 01:00 -> gap 0:31
        -> start 16:24:00, "Late: start shifted 0:31 to match Clock Out."
        -> SH-ND 1:00 after midnight (was 0:59:29)
    """
    if not is_late(row) or rule.time_source != "clock":
        return start, []

    _, clock_end = get_clock_window(row.get("Date"), row.get("Clock In"), row.get("Clock Out"))
    if clock_end is None:
        return start, []

    has_break = rule.has_break and paid > ORD_BREAK_AFTER
    planned_end = start + paid + (BREAK_LENGTH if has_break else ZERO_DURATION)
    target_end = clock_end.replace(second=0, microsecond=0)
    while target_end < planned_end - timedelta(hours=12):   # clock window on the wrong day
        target_end += timedelta(days=1)

    gap = target_end - planned_end
    if not ZERO_DURATION < gap < MAX_LATE_SNAP:
        return start, []

    return start + gap, [f"Late: start shifted 0:{int(gap.total_seconds()):02d} to match Clock Out."]


def is_missing_clock_in(row: pd.Series, rule: PolicyRule) -> bool:
    """
    Clock-based policy with no usable Clock In -> the hours cannot be placed.
    Shift-based policies never need the clock.

    Example:
        "Requires Time In / Out", Clock In "N.A." -> True
        "No Time In / Out",       Clock In "N.A." -> False
    """
    if rule.time_source != "clock":
        return False
    clock_in = row.get("Clock In")
    return is_missing(clock_in) or parse_clock_time(clock_in) is None


def check_logs(row: pd.Series) -> list[str]:
    """
    Log flags for every policy (remark only, the row is still computed).
        Clock In but no Clock Out           -> "CHECK: No Clock Out."
        Clock In -> Clock Out over 16 hours -> possible missing clock out
    Example (IE0-2216 Nov 5: 05:52 - 22:20):
        -> ["CHECK: Clock In-Out 16:28 over 16h. Possible missing clock out."]
    """
    clock_start, clock_end = get_clock_window(row.get("Date"), row.get("Clock In"), row.get("Clock Out"))
    if clock_start is None:
        return []
    if clock_end is None:
        return ["CHECK: No Clock Out."]
    span = clock_end - clock_start
    if span > MAX_CLOCK_SPAN:
        return [f"CHECK: Clock In-Out {duration_to_hm(span)} over 16h. Possible missing clock out."]
    return []


def snap_early_start(
    row: pd.Series,
    rule: PolicyRule,
    start: datetime,
    paid: timedelta,
) -> tuple[datetime, list[str]]:
    """
    Special case (IE0-1727 type): early clock-in BEFORE the NSD window on a shift
    that runs into NSD -> ordinary hours start at Shift start.
    The early minutes are regular time and are what the 8h cap removes; counting
    them pushes the end of the shift back and loses NSD at the end.

    Applies only when ALL are true:
        clock-based policy with NSD and a break (Same Day Split Shift excluded),
        start is before Shift start,
        the shift overlaps 10 PM - 6 AM,
        the early minutes (Clock In -> Shift start) have NO NSD
            (11PM / 12AM / 4AM / 5AM shifts are skipped: their early minutes are
             already NSD, moving them would LOWER NSD),
        Shift start + paid + break still ends by Clock Out (+15 min tolerance).

    Example (IE0-1727 Oct 26: shift 9PM-6AM, Clock In 20:53:03, paid 8h):
        start -> 21:00 -> 21:00-01:00 | BREAK | 02:00-06:00 -> Ord 1:00 + Ord-ND 7:00
    Example (IE0-063 Oct 21: shift 4:30AM, Clock In 04:07) -> kept at Clock In
    """
    if rule.time_source != "clock" or not rule.compute_nsd or not rule.has_break:
        return start, []

    shift_start, shift_end = get_shift_window(row.get("Date"), row.get("Shift"))
    if shift_start is None or start >= shift_start:
        return start, []
    if calculate_nsd_duration(shift_start, shift_end) <= ZERO_DURATION:
        return start, []
    if calculate_nsd_duration(start, shift_start) > ZERO_DURATION:
        return start, []

    _, clock_end = get_clock_window(row.get("Date"), row.get("Clock In"), row.get("Clock Out"))
    if clock_end is None:
        return start, []
    while clock_end < start:
        clock_end += timedelta(days=1)

    has_break = paid > ORD_BREAK_AFTER
    planned_end = shift_start + paid + (BREAK_LENGTH if has_break else ZERO_DURATION)
    if planned_end > clock_end + CLOCK_TOLERANCE:
        return start, []

    return shift_start, [f"Early clock-in: start moved to Shift start {shift_start:%H:%M}."]


def check_attendance(
    row: pd.Series,
    rule: PolicyRule,
    paid: timedelta,
    ot_windows: Optional[list[Window]] = None,
    breaks: Optional[timedelta] = None,
) -> list[str]:
    """
    Flag attendance rows that look wrong. The row is still sliced;
    the flags only go to Detailed Remarks so they can be reviewed.
    Only for clock-based policies (shift-based rows don't use the clock).

    Flags (Clock Out missing / long span -> check_logs, all policies):
        Clock In far from Shift   (> 4h and not explained by an OT window)
        Hours longer than Clock In-Out (paid + breaks > clock span + 15 min)

    breaks: total unpaid break inside the span. None -> ordinary rule (1h if paid > 4h).

    Example (IE0-1970, shift 6:00AM, Clock In 18:01):
        -> ["CHECK: Clock In 18:01 is 11:59 from Shift start 06:00."]
    """
    if rule.time_source != "clock":
        return []

    flags = []
    clock_start, clock_end = get_clock_window(row.get("Date"), row.get("Clock In"), row.get("Clock Out"))
    if clock_start is None:
        return flags

    # Clock In far from the shift start, unless an OT window starts around it
    work_start, _ = get_work_start(row, rule.time_source)
    shift_start, _ = get_shift_window(row.get("Date"), row.get("Shift"))
    if work_start is not None and shift_start is not None:
        gap = abs(work_start - shift_start)
        near_ot = any(
            ot_start - timedelta(hours=1) <= work_start < ot_end
            for ot_start, ot_end in (ot_windows or [])
        )
        if gap > MAX_CLOCK_SHIFT_GAP and not near_ot:
            flags.append(
                f"CHECK: Clock In {work_start:%H:%M} is {duration_to_hm(gap)} "
                f"from Shift start {shift_start:%H:%M}."
            )

    # Paid hours (+ breaks) cannot be longer than the time clocked
    if clock_end is not None:
        if breaks is None:
            has_break = rule.has_break and paid > ORD_BREAK_AFTER
            breaks = BREAK_LENGTH if has_break else ZERO_DURATION
        needed = paid + breaks
        span = clock_end - clock_start
        if needed > span + CLOCK_TOLERANCE:
            flags.append(
                f"CHECK: Hours {duration_to_hm(paid)} (+ breaks) longer than "
                f"Clock In-Out {duration_to_hm(span)}."
            )

    return flags


def remove_overlap(
    ot_windows: list[Window],
    ordinary_pieces: list[Window],
) -> tuple[list[Window], list[str]]:
    """
    Cut the ordinary hours out of the OT windows (same time is never paid twice).
    HOW MUCH OT is paid does not change (attendance Overtime). The cut part is no
    longer a place for OT, so take_ot_windows() leaves it as leftover and it is
    placed right after the last work.
    Returns (clean windows, one OVERLAP remark per cut of 1 minute or more).

    Example:
        OT [(06:00, 08:00)], ordinary [(22:00, 02:00), (03:00, 07:00)]
        -> [(07:00, 08:00)],
           ["OVERLAP: OT 06:00-08:00 inside ordinary 03:00-07:00 (1:00). Moved after last work."]
    """
    clean: list[Window] = []
    remarks: list[str] = []

    for ot_start, ot_end in sorted(ot_windows):
        parts = [(ot_start, ot_end)]

        for ord_start, ord_end in ordinary_pieces:
            overlap = min(ot_end, ord_end) - max(ot_start, ord_start)
            if overlap >= MIN_REMARK:
                remarks.append(
                    f"OVERLAP: OT {ot_start:%H:%M}-{ot_end:%H:%M} inside ordinary "
                    f"{ord_start:%H:%M}-{ord_end:%H:%M} ({duration_to_hm(overlap)}). "
                    f"Moved after last work."
                )

            # Keep only the parts of the OT window outside this ordinary piece
            next_parts = []
            for part_start, part_end in parts:
                if part_end <= ord_start or part_start >= ord_end:
                    next_parts.append((part_start, part_end))
                    continue
                if part_start < ord_start:
                    next_parts.append((part_start, ord_start))
                if part_end > ord_end:
                    next_parts.append((ord_end, part_end))
            parts = next_parts

        clean += parts

    return sorted(clean), remarks


# ============================================================
# RESULT BUILDERS
# ============================================================
def build_result(row: pd.Series, values: dict) -> pd.Series:
    """
    Add the breakdown values to a copy of the row.
    Header durations become Excel time values here (format_duration
    default "hhmm"), after the checks are done.
    Example:
        08:00:00 -> 0.3333
    """
    converted = {
        key: format_duration(value) if key in ALL_HEADERS else value
        for key, value in values.items()
    }
    return pd.Series({**row.to_dict(), **converted})


def finish_result(row: pd.Series, values: dict, valid: bool, *notes: Any) -> pd.Series:
    """
    Close a row: set validity, append remarks, build the result.
    Example:
        Existing: "Ordinary Capped"
        Notes:    "NSD calculated using Clock In.", "21:00-00:00 Ord 1:00 ND 2:00"
        Result:   "Ordinary Capped | NSD calculated using Clock In. | 21:00-00:00 Ord 1:00 ND 2:00"
    """
    # Blank Policy with paid hours -> cannot trust NSD / start -> not valid
    if not normalize_text(row.get("Policy")) and any(values.get(h, ZERO_DURATION) > ZERO_DURATION for h in ALL_HEADERS):
        valid = False
        notes = (*notes, "Blank policy.")

    parts = (str(part).strip() for part in (row.get("Detailed Remarks"), *notes) if part is not None)
    values["Breakdown Valid"] = valid
    values["Detailed Remarks"] = " | ".join(p for p in parts if p and p.lower() != "nan")
    return build_result(row, values)


def empty_values() -> dict[str, timedelta]:
    """Every header at zero. Example: {"Ord": 0:00, "Ord-ND": 0:00, ...}"""
    return {header: ZERO_DURATION for header in ALL_HEADERS}


# ============================================================
# SCENARIO 1: ORDINARY / REST DAY, NO OT
# ============================================================
def breakdown_ordinary_no_ot(row: pd.Series, holiday_lookup: Optional[dict] = None) -> pd.Series:
    """
    Break a no-OT row into day-code headers (Ord / RD / holiday, + ND).
    Hours is in seconds, already capped, already break-deducted,
    so every second is assigned.

    Example (row Aug 30, Clock In 23:00, Hours 8h, Aug 31 Legal, NSD on):
        23:00-00:00 Ord ND 1:00
        00:00-03:00 LH  ND 3:00
        03:00-04:00 BREAK
        04:00-06:00 LH  ND 2:00
        06:00-08:00 LH     2:00
        -> Ord-ND=1, LH-ND=5, LH=2
    Example (normal row 22:00-06:00, next day is the employee's weekly off):
        -> Ord / Ord-ND only (the weekly off belongs to the next shift)
    Example (weekly off, Clock In 13:00, Hours 8h):
        -> RD=8
    Example (Requires Time In / Out, Clock In missing):
        -> all 0, Breakdown Valid False, "MISSING CLOCK IN. Ordinary not computed."
    """
    total = seconds_to_duration(row.get("Hours"))
    values = empty_values()
    lookup = holiday_lookup or {}

    # Step 1: nothing worked - skip
    if total <= ZERO_DURATION:
        return finish_result(row, values, True, "No Final Work Hours.", *check_logs(row))

    # Step 2: Get policy, clockin and rest day (Weekly Off in the row's Status Final)
    rule = get_policy_rule(row.get("Policy"))
    start, source = get_work_start(row, rule.time_source)
    rest_day = is_rest_day(row)

    # DEBUG -> IDs in debug_ids.py
    if is_debug(row, DEBUG_ORD_NO_OT):
        pass  # set breakpoint here

    # Step 3: Clock policy without Clock In -> tag only, not computed
    if is_missing_clock_in(row, rule):
        return finish_result(row, values, False, rule.description, "MISSING CLOCK IN. Ordinary not computed.")

    # Step 4: Attendance checks -> flags only, the row is still sliced
    flags = check_logs(row) + check_attendance(row, rule, total)

    # Step 5: no start time (shift unreadable / unknown policy) -> all to the row's day code
    if start is None:
        day_code = get_day_code(parse_work_date(row.get("Date")), lookup, rest_day)
        values[day_code] = total
        return finish_result(
            row, values, True,
            rule.description, *flags,
            f"{source} unavailable. All hours assigned to {day_code}.",
        )

    # Step 6: Early (before NSD) -> Shift start | Late -> end lined up with Clock Out
    start, early_notes = snap_early_start(row, rule, start, total)
    start, late_notes = snap_late_start(row, rule, start, total)
    flags += early_notes + late_notes

    # Step 7: Work pieces (4hrs - 1hr break - 4 hrs) -> midnight, day code, NSD
    trace, _ = allocate_with_break(start, total, rule, lookup, values, rest_day=rest_day)

    # Step 8: Go through validations -> validation = total work hours
    assigned = sum(values.values(), ZERO_DURATION)
    return finish_result(row, values, assigned == total, rule.description, *flags, *trace)


# ============================================================
# SCENARIO 2: ORDINARY / REST DAY, WITH OT
# ============================================================
def get_ordinary_start(row: pd.Series, work_start: datetime, ot_windows: list[Window]) -> datetime:
    """
    Ordinary hours start after any OT that comes first:
        - PRE-shift OT   : an OT window that ends at or before the shift start
        - OT covering it : an OT window the start falls inside
                           (weekly off where the whole shift is filed as OT)

    Example (shift 9PM, Clock In 17:47, OT 19:00-21:00):
        17:47 -> 21:00   (the early clock-in is not ordinary time)
    Example (shift 2PM, Clock In 10:07, OT 10:00-14:00):
        10:07 -> 14:00
    Example (weekly off, Clock In 06:00, OT 06:00-15:00, Hours 8:07, Overtime 8:00):
        06:00 -> 15:00   (the extra 0:07 RD comes after the OT window, not on top of it)
    """
    shift_start, _ = get_shift_window(row.get("Date"), row.get("Shift"))
    start = work_start
    for ot_start, ot_end in sorted(ot_windows):
        is_pre_shift = ot_end <= shift_start if shift_start else ot_start <= work_start
        covers_start = ot_start <= start < ot_end
        if is_pre_shift or covers_start:
            start = max(start, ot_end)
    return start


def take_ot_windows(
    ot_windows: list[Window],
    ot_total: timedelta,
) -> tuple[list[tuple[datetime, timedelta]], timedelta]:
    """
    Take OT windows in time order until the paid OT (attendance Overtime) is used up.
    OT is taken as is: the whole window length is room for OT (no break inside).
    Returns ([(window start, paid OT in it)], OT left with no window).

    Example (Overtime 3:00, windows 20:00-22:00 and 07:00-08:00):
        -> [(20:00, 2:00), (07:00, 1:00)], 0
    Example (Overtime 2:56, window 17:00-18:00 only):
        -> [(17:00, 1:00)], 1:56 left
    Example (Overtime 12:00, window 06:00-19:00):
        -> [(06:00, 12:00)], 0   (06:00-18:00 straight, no break)
    """
    taken = []
    remaining = ot_total
    for ot_start, ot_end in ot_windows:
        if remaining <= ZERO_DURATION:
            break

        paid = min(remaining, ot_end - ot_start)
        if paid > ZERO_DURATION:
            taken.append((ot_start, paid))
            remaining -= paid

    return taken, max(remaining, ZERO_DURATION)


def breakdown_ordinary_ot(
    row: pd.Series,
    holiday_lookup: Optional[dict] = None,
    ot_windows: Optional[list[Window]] = None,
    rest_day_lookup: Optional[dict[str, set[date]]] = None,
) -> pd.Series:
    """
    Break a row WITH OT into day-code headers and "-OT" headers.

        OT (how much)  = attendance "Overtime"
        Ordinary       = Hours - OT, capped at 8h   (Hours includes OT)
        OT (where)     = approved OT windows (ot.py); day code = day the OT happens
        No OT window   = OT placed right after the last work piece (flagged)
        OT break       = none — OT is computed as is (any length)
        Early clock-in = before NSD on an NSD shift -> ordinary starts at Shift start
        OT rest day    = OT on the employee's weekly off date -> RD-OT (rest_day_lookup)
        Overlap        = OT window part inside ordinary hours is cut out,
                         that OT moves after the last work ("OVERLAP" remark)
        Missing Clock In (clock policy) = tagged, not computed

    Example (shift 10PM-7AM, Clock In 19:52, Hours 11:08, Overtime 3:00,
             OT 20:00-22:00 and 07:00-08:00, NSD on):
        20:00-22:00 Ord-OT 2:00
        22:00-02:00 Ord-ND 4:00 | 02:00-03:00 BREAK | 03:00-06:00 Ord-ND 3:00 | 06:00-07:00 Ord 1:00
        07:00-08:00 Ord-OT 1:00
        -> Ord-ND=7, Ord=1, Ord-OT=3   (ordinary capped 8:08 -> 8:00)

    Example (weekly off, Hours 8:00, Overtime 8:00, OT 06:00-15:00):
        06:00-14:00 RD-OT 8:00
        -> RD-OT=8
    """
    hours = seconds_to_duration(row.get("Hours"))
    values = empty_values()
    lookup = holiday_lookup or {}
    notes = []

    # Step 1: Split hours -> OT (attendance Overtime) and ordinary (rest, max 8h)
    ot_total = min(parse_duration(row.get("Overtime")), hours)
    ordinary = min(hours - ot_total, timedelta(hours=MAX_ORDINARY_HOURS))
    expected = ordinary + ot_total
    if hours - ot_total > ordinary:
        notes.append(f"Ordinary capped {duration_to_hm(hours - ot_total)} -> {duration_to_hm(ordinary)}.")

    # Step 2: Get policy, clockin and rest day (Weekly Off in the row's Status Final)
    rule = get_policy_rule(row.get("Policy"))
    work_start, source = get_work_start(row, rule.time_source)
    rest_day = is_rest_day(row)
    rest_dates = (rest_day_lookup or {}).get(str(row.get("Employee ID", "")).strip(), set())
    windows = sorted(ot_windows or [])

    # DEBUG -> IDs in debug_ids.py
    if is_debug(row, DEBUG_ORD_OT):
        pass  # set breakpoint here

    # Step 3: Clock policy without Clock In -> tag only, not computed
    if is_missing_clock_in(row, rule):
        return finish_result(row, values, False, rule.description, *notes, "MISSING CLOCK IN. Not computed.")

    # Step 4: no start time (shift unreadable / unknown policy) -> all to the row's day code
    if work_start is None:
        day_code = get_day_code(parse_work_date(row.get("Date")), lookup, rest_day)
        values[day_code] += ordinary
        values[f"{day_code}{OT_SUFFIX}"] += ot_total
        return finish_result(
            row, values, True, rule.description, *notes,
            *check_attendance(row, rule, expected, windows),
            f"{source} unavailable. Hours to {day_code} / {day_code}{OT_SUFFIX}.",
        )

    # Step 5: Ordinary starts after any OT that comes first (pre-shift / covers the start)
    start = get_ordinary_start(row, work_start, windows)

    # Step 5b: Early clock-in before NSD (no pre-shift OT in the way) -> Shift start
    start, early_notes = snap_early_start(row, rule, start, ordinary)
    notes += early_notes

    # Step 6: Ordinary segments (4hrs - 1hr break - 4 hrs)
    trace = []
    ordinary_pieces: list[Window] = []
    last_end = start
    if ordinary > ZERO_DURATION:
        trace, ordinary_pieces = allocate_with_break(start, ordinary, rule, lookup, values, rest_day=rest_day)
        last_end = ordinary_pieces[-1][1]

    # Step 7: Overlap -> cut the ordinary hours out of the OT windows
    clean_windows, overlaps = remove_overlap(windows, ordinary_pieces)
    notes += overlaps

    # Step 8: OT segments -> clean OT windows, trimmed to the attendance Overtime
    taken, leftover = take_ot_windows(clean_windows, ot_total)
    for ot_start, ot_paid in taken:
        # OT as is (nsd, transition) -> "-OT" headers, no break
        ot_trace, (_, ot_end) = allocate_ot(ot_start, ot_paid, rule, lookup, values, rest_day, rest_dates)
        trace += ot_trace
        last_end = max(last_end, ot_end)

    # Step 9: OT with no (clean) window -> right after the last work (ordinary or OT)
    if leftover > ZERO_DURATION:
        if leftover >= MIN_REMARK:
            notes.append(f"No OT window for {duration_to_hm(leftover)}. Placed after last work.")
        ot_trace, _ = allocate_ot(last_end, leftover, rule, lookup, values, rest_day, rest_dates)
        trace += ot_trace

    # Step 10: Attendance checks -> flags only (only the ordinary break counts; OT has none)
    notes = check_logs(row) + check_attendance(row, rule, expected, windows, count_breaks(ordinary_pieces)) + notes

    # Step 11: Go through validations -> validation = ordinary + OT
    assigned = sum(values.values(), ZERO_DURATION)
    return finish_result(row, values, assigned == expected, rule.description, *notes, *trace)


# ============================================================
# SCENARIO 3: RD / HOLIDAY / RD + HOLIDAY  (Present + Weekly Off and/or Holiday)
# ============================================================
# Hook (Status Final): Present + Weekly Off  -> RD
#                      Present + Holiday     -> LH / SH / LH-SH (type from the SharePoint holiday list)
#                      Present + both        -> RD-LH / RD-SH / RD-LH-SH
#
# HOW MUCH is paid = attendance "Overtime" (actual OT filed).
# WHERE it lands   = approved OT window (OT file start/end), Clock In/Out as backup:
#     OT fits the OT window (full length, break included) -> OT window used, start at OT start
#     OT does not fit the window, fits Clock In/Out       -> logs used, start from policy
#                                                            "Wrong OT window filing" remark
#     No OT window                                        -> logs used (remark)
# Then: 4h | BREAK | 4h base, midnight, NSD, day code. The excess over 8h is -OT, as is.
#
# No approved Overtime:
#   Holiday (not weekly off) -> Ord 8 (holiday pay, same as unworked holiday)
#   RD / RD + Holiday        -> SKIPPED
# With approved Overtime the holiday header (e.g. LH 8) covers the holiday pay -> no extra Ord 8.

SCENARIO_LABELS = {SCENARIO_RD: "RD", "HOL": "Holiday", SCENARIO_RD_HOL: "RD Holiday"}
PREMIUM_BASE = timedelta(hours=MAX_ORDINARY_HOURS)   # first 8h -> RD / LH; also holiday pay


def whole_minutes(value: timedelta) -> timedelta:
    """Drop leftover seconds. Example: 9:03:42 -> 9:03"""
    return timedelta(seconds=duration_to_seconds(value))


def get_premium_hours(
    row: pd.Series,
    rule: PolicyRule,
    ot_windows: Optional[list[Window]] = None,
) -> tuple[timedelta, Optional[datetime], str, list[str]]:
    """
    Paid hours AND start for an RD / Holiday row.
    Returns (paid, start, source, notes).

        OT window span = total length of the approved OT windows (break included)
        Logs           = Clock Out - Clock In (backup)

        1. OT <= window span (and <= logs, if logs exist) -> paid OT, start = first OT start
        2. OT <= window span, OT > logs                   -> paid logs, start = first OT start
        3. OT >  window span, OT <= logs                  -> paid OT, start = policy start
                                                             "Wrong OT window filing"
        4. No OT window, OT <= logs                       -> paid OT, start = policy start
        5. OT > window span and > logs                    -> paid logs, start = policy start
        6. No logs, OT > window span                      -> paid window span, start = OT start
        7. No OT window and no logs                       -> paid OT, start = policy start (CHECK)

    Example (IE0-033 Aug 21: OT 8:00, window 06:08-15:08 (9:00), logs 06:07-15:57):
        -> 8:00 from 06:08   (06:08-10:08 | BREAK 10:08-11:08 | 11:08-15:08)
    Example (IE0-1306 Aug 31: OT 11:48, window 09:11-14:00 (4:49), logs 10:11-23:00 (12:48)):
        -> 11:48 from Clock In 10:11, "Wrong OT window filing ..."
    Example (IE0-1358 Aug 31: OT 12:00, windows 02:00-06:00 + 06:00-15:00 (13:00)):
        -> 12:00 from 02:00
    """
    overtime = whole_minutes(parse_duration(row.get("Overtime")))
    windows = sorted(ot_windows or [])
    span = whole_minutes(sum((end - start for start, end in windows), ZERO_DURATION))
    window_start = windows[0][0] if windows else None

    clock_start, clock_end = get_clock_window(row.get("Date"), row.get("Clock In"), row.get("Clock Out"))
    logs = whole_minutes(clock_end - clock_start) if clock_start and clock_end else None
    policy_start, policy_source = get_work_start(row, rule.time_source)

    fits_window = bool(windows) and overtime <= span
    fits_logs = logs is not None and overtime <= logs
    ot_hm, span_hm = duration_to_hm(overtime), duration_to_hm(span)
    logs_hm = duration_to_hm(logs) if logs is not None else ""

    # 1 / 2: OT fits the OT window -> OT window used
    if fits_window:
        if logs is not None and not fits_logs:
            return logs, window_start, "OT start", [f"Overtime {ot_hm} > logs {logs_hm}. Logs used, from OT start."]
        return overtime, window_start, "OT start", ["OT window used."]

    # 3 / 4: OT fits the logs -> logs used
    if fits_logs:
        if windows:
            note = f"Wrong OT window filing: Overtime {ot_hm} > OT window {span_hm}. Clock In/Out used."
        else:
            note = "No OT window. Clock In/Out used."
        return overtime, policy_start, policy_source, [note]

    # 5: OT longer than both -> raw logs
    if logs is not None:
        window_note = f" and OT window {span_hm}" if windows else ""
        return logs, policy_start, policy_source, [f"Overtime {ot_hm} > logs {logs_hm}{window_note}. Logs used."]

    # 6: no logs, OT longer than the OT window -> OT window
    if windows:
        return span, window_start, "OT start", [
            f"CHECK: No complete logs. Overtime {ot_hm} > OT window {span_hm}. OT window used."
        ]

    # 7: nothing to verify against
    return overtime, policy_start, policy_source, ["CHECK: No OT window and no complete logs. Overtime used."]


def cap_by_total_work(row: pd.Series, paid: timedelta) -> tuple[timedelta, list[str]]:
    """
    Premium paid hours can never be more than Total Work Duration
    (Total, not Final: Total still includes the break, like the Overtime filing).
    Example:
        Overtime 8:00, Total 9:00 -> 8:00
        Overtime 9:00, Total 8:30 -> 8:30 "Overtime 9:00 > Total Work 8:30. Total used."
    """
    total = whole_minutes(parse_duration(row.get("Total Work Hours")))
    if total <= ZERO_DURATION or paid <= total:
        return paid, []
    return total, [f"Overtime {duration_to_hm(paid)} > Total Work {duration_to_hm(total)}. Total used."]


def breakdown_premium(
    row: pd.Series,
    scenario: str,
    holiday_lookup: Optional[dict] = None,
    rest_day_lookup: Optional[dict[str, set[date]]] = None,
    ot_windows: Optional[list[Window]] = None,
) -> pd.Series:
    """
    Entry point for RD / Holiday / RD + Holiday rows.
        1. Holiday status, date not in the holiday list -> not computed (CHECK)
        2. No Overtime value -> Holiday: Ord 8 | RD / RD + Holiday: SKIPPED
        3. Clock policy, no Clock In  -> MISSING CLOCK IN, not computed
        4. Paid + start -> get_premium_hours (OT window first, Clock In/Out backup)
        5. Paid <= 8h -> breakdown_premium_no_ot, else breakdown_premium_ot
    Example:
        "Present,Weekly Off", Overtime 0, worked 8:35 -> SKIPPED: RD without approved OT.
        "Present,Holiday" Aug 31, Overtime 0          -> Ord 8 "Worked holiday (LH) without approved OT."
        "Present,Holiday" Aug 31, Overtime 8:00       -> LH 8 (no extra Ord 8)
    """
    values = empty_values()
    lookup = holiday_lookup or {}
    label = SCENARIO_LABELS[scenario]
    rule = get_policy_rule(row.get("Policy"))
    holiday_code = lookup.get(parse_work_date(row.get("Date")))

    # Step 1: Holiday status must match the SharePoint holiday list
    if scenario != SCENARIO_RD and not holiday_code:
        return finish_result(
            row, values, False, "CHECK: Status says Holiday but date is not in the holiday list. Not computed.",
        )

    # Step 2: no approved Overtime
    if parse_duration(row.get("Overtime")) <= ZERO_DURATION:
        if scenario == "HOL":
            values[ORDINARY_CODE] = PREMIUM_BASE
            return finish_result(
                row, values, True,
                f"Worked holiday ({holiday_code}) without approved OT. Ord {duration_to_hm(PREMIUM_BASE)}.",
            )
        return finish_result(row, values, True, f"SKIPPED: {label} without approved OT.")

    # Step 3: Clock policy without Clock In -> tag only, not computed
    if is_missing_clock_in(row, rule):
        return finish_result(row, values, False, rule.description, "MISSING CLOCK IN. Not computed.")

    # Step 4: Paid hours + start -> OT window first, Clock In/Out as backup
    paid, start, source, notes = get_premium_hours(row, rule, ot_windows)
    paid, total_notes = cap_by_total_work(row, paid)
    notes = [*check_logs(row), *notes, *total_notes]
    if paid <= ZERO_DURATION:
        return finish_result(row, values, True, rule.description, *notes, "No paid hours.")

    rest_dates = (rest_day_lookup or {}).get(str(row.get("Employee ID", "")).strip(), set())

    # Step 5: route by paid hours
    if paid <= PREMIUM_BASE:
        return breakdown_premium_no_ot(row, paid, start, source, notes, rule, lookup, values)
    return breakdown_premium_ot(row, paid, start, source, notes, rule, lookup, values, rest_dates)


def breakdown_premium_no_ot(
    row: pd.Series,
    paid: timedelta,
    start: Optional[datetime],
    source: str,
    notes: list[str],
    rule: PolicyRule,
    lookup: dict,
    values: dict[str, timedelta],
) -> pd.Series:
    """
    Paid <= 8h. Same as Ord no-OT, header = RD / LH / SH / RD-LH ...
    start comes from get_premium_hours (OT start, or policy start as backup).
    Example (IE0-033 Aug 21 SH, OT 8:00, window 06:08-15:08):
        06:08-10:08 SH 4:00 | 10:08-11:08 BREAK | 11:08-15:08 SH 4:00 -> SH=8
    Example (Present,Holiday Aug 21 SH, start 21:05, OT 8:00):
        21:05-00:00 SH (ND) | 00:00-... Ord (ND)   (holiday follows the calendar day)
    """
    rest_day = is_rest_day(row)

    # DEBUG -> IDs in debug_ids.py
    if is_debug(row, DEBUG_PREMIUM_NO_OT):
        pass  # set breakpoint here

    # No start time -> all to the row's day code
    if start is None:
        day_code = get_day_code(parse_work_date(row.get("Date")), lookup, rest_day)
        values[day_code] += paid
        return finish_result(
            row, values, True, rule.description, *notes,
            f"{source} unavailable. All hours assigned to {day_code}.",
        )

    # Late -> line the end up with Clock Out (only when the start came from Clock In,
    #         not from an OT window)
    if source == "Clock In":
        start, late_notes = snap_late_start(row, rule, start, paid)
        notes = [*notes, *late_notes]

    # Work pieces (4h | BREAK | 4h) -> midnight, day code, NSD
    trace, _ = allocate_with_break(start, paid, rule, lookup, values, rest_day=rest_day)

    assigned = sum(values.values(), ZERO_DURATION)
    return finish_result(row, values, assigned == paid, rule.description, *notes, *trace)


def breakdown_premium_ot(
    row: pd.Series,
    paid: timedelta,
    start: Optional[datetime],
    source: str,
    notes: list[str],
    rule: PolicyRule,
    lookup: dict,
    values: dict[str, timedelta],
    rest_dates: Optional[set[date]] = None,
) -> pd.Series:
    """
    Paid > 8h. First 8h -> RD / LH (4h | BREAK | 4h), the excess -> RD-OT / LH-OT
    right after, computed as is (no break, no deduction, any length).
    start comes from get_premium_hours (OT start, or policy start as backup).
    Example (IE0-1358 Aug 31 RD-LH, OT 12:00, windows 02:00-06:00 + 06:00-15:00):
        02:00-06:00 RD-LH 4 | 06:00-07:00 BREAK | 07:00-11:00 RD-LH 4 | 11:00-15:00 RD-LH-OT 4
    Example (weekly off, start 06:00, OT 17:00):
        RD 4 | BREAK | RD 4 | 15:00-00:00 RD-OT 9   (no deduction)
    """
    rest_day = is_rest_day(row)

    # Step 1: split -> first 8h base, the rest is OT (as is)
    ot_paid = paid - PREMIUM_BASE

    # DEBUG -> IDs in debug_ids.py
    if is_debug(row, DEBUG_PREMIUM_OT):
        pass  # set breakpoint here

    # Step 2: no start time -> all to the row's day code
    if start is None:
        day_code = get_day_code(parse_work_date(row.get("Date")), lookup, rest_day)
        values[day_code] += PREMIUM_BASE
        values[f"{day_code}{OT_SUFFIX}"] += ot_paid
        return finish_result(
            row, values, True, rule.description, *notes,
            f"{source} unavailable. Hours to {day_code} / {day_code}{OT_SUFFIX}.",
        )

    # Step 3: base 8h (4h | BREAK | 4h)
    trace, pieces = allocate_with_break(start, PREMIUM_BASE, rule, lookup, values, rest_day=rest_day)

    # Step 4: OT right after the base, one straight block
    ot_trace, _ = allocate_ot(pieces[-1][1], ot_paid, rule, lookup, values, rest_day, rest_dates)
    trace += ot_trace

    # Step 5: validation = paid (base + OT)
    assigned = sum(values.values(), ZERO_DURATION)
    return finish_result(row, values, assigned == paid, rule.description, *notes, *trace)


# ============================================================
# SCENARIO 4: UNWORKED HOLIDAY (Holiday, not Present, not Weekly Off)
# ============================================================
def breakdown_holiday_unworked(row: pd.Series, holiday_lookup: Optional[dict] = None) -> pd.Series:
    """
    Holiday the employee did not work and is not their weekly off -> Ord 8h.
    LH or SH comes from the SharePoint holiday list (shown in the remark).
    No logs, so no segmenting, break, NSD or transition.
    Example:
        "Holiday", Aug 31 (LH) -> Ord=8   "Unworked holiday (LH). Ord 8:00."
        "Weekly Off,Holiday"   -> not routed here (no pay)
    """
    values = empty_values()
    holiday_code = (holiday_lookup or {}).get(parse_work_date(row.get("Date")))

    if not holiday_code:
        return finish_result(
            row, values, False, "CHECK: Status says Holiday but date is not in the holiday list. Not computed.",
        )

    values[ORDINARY_CODE] = PREMIUM_BASE
    return finish_result(row, values, True, f"Unworked holiday ({holiday_code}). Ord {duration_to_hm(PREMIUM_BASE)}.")


# ============================================================
# SCENARIO 5: NOT COMPUTED (all headers 0, remark only)
# ============================================================
PENDING_REQUEST_REMARK = "Pending Request"
UNPAID_LEAVE_REMARK = "SKIPPED: Unpaid Leave."
PRESENT_LEAVE_REMARK = "Leave."
HALF_LEAVE_REMARK = "Half Day Leave + Half Day Unpaid Leave."
OT_WITHOUT_PRESENT_REMARK = "CHECK: Overtime without Present status. Not computed."


def breakdown_not_computed(row: pd.Series, remark: str, valid: bool = True) -> pd.Series:
    """
    All headers 0 with a remark.
    Example:
        "Unpaid Leave", 2:16 logged          -> SKIPPED: Unpaid Leave.            (valid)
        "Weekly Off,Request", Overtime 8:00  -> CHECK: Overtime without Present... (not valid)
    """
    return finish_result(row, empty_values(), valid, remark)


# ============================================================
# SCENARIO 6: FLAT ORD (status decides the hours, no slicing)
# ============================================================
def breakdown_flat_ord(row: pd.Series, hours: timedelta, remark: str) -> pd.Series:
    """
    Fixed Ord hours from the status. No segments, break, NSD or transition.
    Example:
        "Present,Leave"                          -> Ord 8 "Leave. Ord 8:00."
        "Half Day Leave, Half Day Unpaid Leave"  -> Ord 4 "Half Day Leave + Half Day Unpaid Leave. Ord 4:00."
    """
    values = empty_values()
    values[ORDINARY_CODE] = hours
    return finish_result(row, values, True, f"{remark} Ord {duration_to_hm(hours)}.")
