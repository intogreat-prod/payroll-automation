"""
holiday.py
----------
Day codes. Decides WHAT KIND OF DAY each piece of work falls on.

    get_day_code()       -> "Ord", "LH", "SH", "LH-SH", "RD", "RD-LH", ... (the only place that decides)
    is_rest_day()        -> True if the row's Status Final says Weekly Off
    build_rest_day_lookup() -> {Employee ID: {weekly off dates}} (for OT only)
    get_status_scenario()   -> "RD", "HOL", "RD-HOL" or None (from Status Final)
    is_unworked_holiday()   -> Holiday, not Present, not Weekly Off (paid Ord 8h)
    is_present()            -> Status Final says Present
    is_unpaid_leave()       -> Status Final says Unpaid Leave (whole day, not Half Day)
    is_request_pending()    -> Detailed Status says "Request Pending" (not computed)
    is_late()               -> attendance "Is Late" = Yes
    is_present_leave()      -> Present + Leave (not half day / unpaid, not RD / Holiday) -> Ord 8
    is_half_leave_half_unpaid() -> Half Day Leave + Half Day Unpaid Leave, not Present -> Ord 4
    build_day_segments() -> cut a window at midnight and tag each piece
    build_headers()      -> payroll headers generated from DAY_CODES

Holidays come from the SharePoint holiday list (per calendar).
Holiday Type is strictly LH, SH or both. Anything else stops the run.
Rest day follows the SHIFT (the row), holidays follow the CALENDAR day:
    - Weekly off row  -> every piece of that shift is RD, even after midnight
    - Normal row whose next day is a weekly off -> stays Ord after midnight
      (the next day's weekly off belongs to the next day's shift)
    - OT is the exception: OT that lands on the employee's weekly off date -> RD
      (e.g. post-shift OT after midnight when the next day is the weekly off)
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Iterable, Optional

import pandas as pd

from features.payroll.premiums.helpers import (
    normalize_text,
    parse_work_date,
    split_at_midnights,
)

# ============================================================
# CONSTANTS
# ============================================================
ORDINARY_CODE = "Ord"
ND_SUFFIX = "-ND"
OT_SUFFIX = "-OT"
REST_DAY_CODE = "RD"

# Word in the Holiday Type -> flag
# Accepts the codes ("LH", "SH", "LH-SH") and the long names ("Legal Holiday", "Special ...")
HOLIDAY_FLAGS = {
    "lh": "LH",
    "sh": "SH",
    "legal": "LH",
    "regular": "LH",
    "special": "SH",
}

# Join order when a date is both (Legal first)
HOLIDAY_FLAG_ORDER = ("LH", "SH")

# Every code a holiday date can have
HOLIDAY_CODES = ("LH", "SH", "LH-SH")

# Text in Status Final (Status_Unmand) that marks a weekly off
REST_DAY_STATUS = "weekly off"

# Status Final words for the routing hooks
PRESENT_STATUS = "present"
HOLIDAY_STATUS = "holiday"
UNPAID_LEAVE_STATUS = "unpaid leave"
REQUEST_PENDING_STATUS = "request pending"   # read from Detailed Status, not Status Final
HALF_DAY_STATUS = "half day"

# Status scenarios (Status Final must also say Present)
SCENARIO_RD = "RD"          # Present + Weekly Off
SCENARIO_HOL = "HOL"        # Present + Holiday
SCENARIO_RD_HOL = "RD-HOL"  # Present + Weekly Off + Holiday

# Rest day alone or with a holiday: RD, RD-LH, RD-SH, RD-LH-SH
REST_DAY_CODES = (REST_DAY_CODE, *(f"{REST_DAY_CODE}-{code}" for code in HOLIDAY_CODES))

# Every code a day can have
DAY_CODES = (ORDINARY_CODE, *HOLIDAY_CODES, *REST_DAY_CODES)


def build_headers(suffixes: Iterable[str] = ("", ND_SUFFIX)) -> list[str]:
    """
    Generate payroll headers so no combination can go missing.
    Example:
        ("", "-ND") -> ["Ord", "Ord-ND", "LH", "LH-ND", ..., "RD", "RD-ND", ...]
    With OT:
        ("", "-ND", "-OT", "-ND-OT") -> ["Ord", "Ord-ND", "Ord-OT", "Ord-ND-OT", ...]
    """
    return [f"{code}{suffix}" for code in DAY_CODES for suffix in suffixes]


# ============================================================
# HOLIDAY LOOKUP
# ============================================================
def get_holiday_flags(holiday_type) -> set[str]:
    """
    Read LH / SH flags from one Holiday Type value.
    Example:
        "LH"             -> {"LH"}
        "LH-SH"          -> {"LH", "SH"}
        "Legal Holiday"  -> {"LH"}
        "National"       -> set()   (unknown)
    """
    words = re.findall(r"[a-z]+", normalize_text(holiday_type).casefold())
    return {HOLIDAY_FLAGS[word] for word in words if word in HOLIDAY_FLAGS}


def build_holiday_lookup(holidays: Optional[pd.DataFrame]) -> dict[date, str]:
    """
    Turn the holiday list into a date lookup.
    Example:
        Date 2026-09-01, ["LH"]       -> {date(2026, 9, 1): "LH"}
        Date 2026-09-01, ["LH", "SH"] -> {date(2026, 9, 1): "LH-SH"}

    An unknown Holiday Type raises UserWarning instead of being skipped,
    because a skipped holiday is silently paid as Ord.
    """
    lookup: dict[date, str] = {}
    unknown: list[str] = []
    if holidays is None or len(holidays) == 0:
        return lookup

    for _, holiday in holidays.iterrows():
        holiday_date = parse_work_date(holiday["Date"])
        if holiday_date is None:
            continue

        holiday_types = holiday["Holiday Type"]
        if not isinstance(holiday_types, (list, tuple, set)):
            holiday_types = [holiday_types]

        flags = set(lookup.get(holiday_date, "").split("-")) - {""}
        for holiday_type in holiday_types:
            found = get_holiday_flags(holiday_type)
            if not found:
                unknown.append(f"{holiday_date} '{holiday_type}'")
            flags |= found

        code = "-".join(flag for flag in HOLIDAY_FLAG_ORDER if flag in flags)
        if code:
            lookup[holiday_date] = code

    if unknown:
        raise UserWarning(f"Unknown Holiday Type (expected LH / SH): {', '.join(unknown)}")

    return lookup


# ============================================================
# REST DAY
# ============================================================
def is_rest_day(row) -> bool:
    """
    True if the row's Status Final says Weekly Off. Only the row itself is read,
    so the next day's weekly off never leaks into tonight's shift.
    Example:
        "Present,Weekly Off" -> True
        "Present"            -> False
    """
    return REST_DAY_STATUS in normalize_text(row.get("Status Final")).casefold()


def build_rest_day_lookup(att_df: Optional[pd.DataFrame]) -> dict[str, set[date]]:
    """
    Weekly off dates per employee, read from every attendance row.
    Used only for OT pieces (OT that lands on a weekly off date -> RD).
    Example:
        IE0-1590 Aug 26 "Weekly Off" -> {"IE0-1590": {date(2026, 8, 26)}}
    """
    lookup: dict[str, set[date]] = {}
    if att_df is None or att_df.empty:
        return lookup
    for _, row in att_df.iterrows():
        work_date = parse_work_date(row.get("Date"))
        if work_date is not None and is_rest_day(row):
            lookup.setdefault(normalize_text(row.get("Employee ID")), set()).add(work_date)
    return lookup


def _status(row) -> str:
    return normalize_text(row.get("Status Final")).casefold()


def is_present(row) -> bool:
    """Example: "Present,Request" -> True, "Weekly Off,Request" -> False"""
    return PRESENT_STATUS in _status(row)


def is_unpaid_leave(row) -> bool:
    """
    Whole-day Unpaid Leave (no Present). Half Day Unpaid Leave is capped elsewhere.
    Example:
        "Unpaid Leave" / "Request,Unpaid Leave" -> True
        "Present,Half Day Unpaid Leave"         -> False
    """
    status = _status(row)
    return UNPAID_LEAVE_STATUS in status and HALF_DAY_STATUS not in status and PRESENT_STATUS not in status


def is_request_pending(row) -> bool:
    """
    Detailed Status has a pending request (attendance adjustment, shift change, clock-in...).
    The row is not computed until the request is resolved.
    Example:
        "Present,Request Pending (Shift Change)"                          -> True
        "Request Pending (Attendance Adjustment)Leave (Leave without Pay)" -> True
        "Present,Shift Change"                                            -> False
    """
    return REQUEST_PENDING_STATUS in normalize_text(row.get("Detailed Status")).casefold()


def is_late(row) -> bool:
    """
    Attendance "Is Late" column (source header "Is Late " with a trailing space).
    Example: "Yes" -> True, "No" / blank -> False
    """
    return normalize_text(row.get("Is Late")).casefold() == "yes"


LEAVE_STATUS = "leave"
HALF_DAY_LEAVE_STATUS = "half day leave"
HALF_DAY_UNPAID_STATUS = "half day unpaid leave"


def is_present_leave(row) -> bool:
    """
    Present and on (paid) Leave the same day -> Ord 8, remark "Leave".
    Example:
        "Present,Leave" / "Present,Request,Leave" -> True
        "Present,Half Day Leave"                  -> False (half day, normal Ord path)
        "Present,Half Day Unpaid Leave"           -> False (capped to 4h)
    """
    status = _status(row)
    return (
        PRESENT_STATUS in status
        and LEAVE_STATUS in status
        and HALF_DAY_STATUS not in status
        and UNPAID_LEAVE_STATUS not in status
        and REST_DAY_STATUS not in status
        and HOLIDAY_STATUS not in status
    )


def is_half_leave_half_unpaid(row) -> bool:
    """
    Half day paid leave + half day unpaid leave, not Present -> Ord 4 (the paid half).
    Example:
        "Half Day Leave, Half Day Unpaid Leave"          -> True
        "Present,Half Day Unpaid Leave"                  -> False
    """
    status = _status(row)
    return (
        PRESENT_STATUS not in status
        and HALF_DAY_UNPAID_STATUS in status
        and status.replace(HALF_DAY_UNPAID_STATUS, "").find(HALF_DAY_LEAVE_STATUS) >= 0
    )


def get_status_scenario(row) -> Optional[str]:
    """
    Pick the RD / Holiday scenario from Status Final. Checked most specific first.
    "Request" in the status is ignored. Not Present -> None (other routes).
    Example:
        "Present,Weekly Off,Holiday,Request" -> "RD-HOL"
        "Present,Holiday"                    -> "HOL"
        "Present,Weekly Off,Request"         -> "RD"
        "Present" / "Weekly Off"             -> None
    """
    status = _status(row)
    if PRESENT_STATUS not in status:
        return None
    rest_day = REST_DAY_STATUS in status
    holiday = HOLIDAY_STATUS in status
    if rest_day and holiday:
        return SCENARIO_RD_HOL
    if holiday:
        return SCENARIO_HOL
    if rest_day:
        return SCENARIO_RD
    return None


def is_unworked_holiday(row) -> bool:
    """
    Holiday the employee did not work and is not their weekly off -> Ord 8h.
    Example:
        "Holiday" / "Holiday,Request" -> True
        "Weekly Off,Holiday"          -> False  (holiday on a rest day, no pay)
        "Present,Holiday"             -> False  (worked -> breakdown_premium)
    """
    status = _status(row)
    return HOLIDAY_STATUS in status and PRESENT_STATUS not in status and REST_DAY_STATUS not in status


# ============================================================
# DAY CODE
# ============================================================
def get_day_code(
    day: Optional[date],
    holiday_lookup: dict[date, str],
    rest_day: bool = False,
) -> str:
    """
    Return the day code. The ONLY function that decides it.
    day      -> calendar day the piece happens on (holiday lookup)
    rest_day -> the SHIFT is a weekly off (from the row, not the calendar day)
    Example:
        date(2026, 8, 31) (Legal)              -> "LH"
        date(2026, 9, 2)                       -> "Ord"
        date(2026, 9, 2), rest_day             -> "RD"
        date(2026, 8, 31) (Legal), rest_day    -> "RD-LH"
        None                                   -> "Ord"
    """
    holiday_code = holiday_lookup.get(day) if day is not None else None
    if rest_day and holiday_code:
        return f"{REST_DAY_CODE}-{holiday_code}"   # RD-LH
    if rest_day:
        return REST_DAY_CODE                       # RD
    return holiday_code or ORDINARY_CODE           # LH / Ord


def build_day_segments(
    start: datetime,
    end: datetime,
    holiday_lookup: dict[date, str],
    rest_day: bool = False,
    rest_dates: Optional[set[date]] = None,
) -> list[tuple[datetime, datetime, str]]:
    """
    Cut a work window at every midnight and tag each piece.
    Holiday = calendar day of the piece. Rest day = the whole shift.
    rest_dates (OT only): the employee's weekly off dates -> RD by calendar day.
    Example (Aug 31 is Legal, normal row):
        Aug 30 10 PM - Aug 31 6 AM -> [(10 PM, 12 AM, "Ord"), (12 AM, 6 AM, "LH")]
    Example (Aug 30 is a normal row, Aug 31 is that employee's weekly off):
        Aug 30 10 PM - Aug 31 6 AM -> [(10 PM, 12 AM, "Ord"), (12 AM, 6 AM, "Ord")]
    Example (OT, Aug 30 normal row, Aug 31 weekly off, rest_dates={Aug 31}):
        Aug 31 06:00 - 08:00 -> [(06:00, 08:00, "RD-LH")]   (Aug 31 is also Legal)
    Example (Aug 30 row is the weekly off):
        Aug 30 10 PM - Aug 31 6 AM -> [(10 PM, 12 AM, "RD"), (12 AM, 6 AM, "RD-LH")]
    """
    return [
        (
            seg_start,
            seg_end,
            get_day_code(
                seg_start.date(),
                holiday_lookup,
                rest_day or seg_start.date() in (rest_dates or set()),
            ),
        )
        for seg_start, seg_end in split_at_midnights(start, end)
    ]
