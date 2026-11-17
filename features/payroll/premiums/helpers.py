"""
helpers.py
----------
Generic building blocks shared by payroll_premiums.py and slicer.py.

This module imports NOTHING from the other premiums modules.

Sections
--------
    Constants
    Missing value / text
    Date
    Duration
    Seconds  (the "Hours" column is always whole seconds)
    Overtime
    Clock
    Shift
    Time windows (break + midnight split)
    Excel format (used only at export)
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable, Literal, Optional

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter


# ============================================================
# CONSTANTS
# ============================================================
ZERO_DURATION = timedelta(0)

# Most hours an ordinary no-OT day can pay. Anything above is capped.
MAX_ORDINARY_HOURS = 8

# Most hours a Half Day Unpaid Leave day can pay.
MAX_HALF_DAY_HOURS = 4

# Unpaid break: taken after the first BREAK_AFTER_HOURS of paid work.
# Final Work Duration already has it deducted — it only affects WHERE hours land.
BREAK_AFTER_HOURS = 4
BREAK_HOURS = 1

# The break applies to ordinary / base hours only.
# OT is always computed as is: no break, no deduction (any length).

SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

CLOCK_COLUMNS = ("Clock In", "Clock Out")


# ============================================================
# MISSING VALUE AND TEXT HELPERS
# ============================================================
def is_missing(value: Any) -> bool:
    """
    Check whether a value is blank.
    Example:
        "N.A."     -> True
        "08:00:00" -> False
    """
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().casefold() in {
        "", "nan", "nat", "none", "n.a", "n.a.", "na", "-",
    }


def normalize_text(value: Any) -> str:
    """
    Remove unnecessary spaces.
    Example:
        "  Requires   Time In  " -> "Requires Time In"
    """
    if is_missing(value):
        return ""
    return " ".join(str(value).strip().split())


# ============================================================
# DATE HELPER
# ============================================================
def parse_work_date(value: Any) -> Optional[date]:
    """
    Convert a value into a date.
    Example:
        "2026-08-21" -> date(2026, 8, 21)
    """
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


# ============================================================
# DURATION HELPERS
# ============================================================
def parse_duration(value: Any) -> timedelta:
    """
    Convert a duration into timedelta.
    Example:
        "09:58:00" -> timedelta(hours=9, minutes=58)
    """
    if is_missing(value):
        return ZERO_DURATION
    if isinstance(value, pd.Timedelta):
        return max(value.to_pytimedelta(), ZERO_DURATION)
    if isinstance(value, timedelta):
        return max(value, ZERO_DURATION)
    if isinstance(value, time):
        return timedelta(hours=value.hour, minutes=value.minute, seconds=value.second)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value <= 0:
            return ZERO_DURATION
        return timedelta(days=float(value))

    match = re.fullmatch(
        r"(?P<hours>\d+):(?P<minutes>\d{1,2})(?::(?P<seconds>\d{1,2}))?",
        normalize_text(value),
    )
    if not match:
        return ZERO_DURATION

    hours = int(match.group("hours"))
    minutes = int(match.group("minutes"))
    seconds = int(match.group("seconds") or 0)
    if minutes > 59 or seconds > 59:
        return ZERO_DURATION
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


def duration_to_hours(value: timedelta) -> float:
    """
    Convert a duration into decimal hours.
    Example:
        09:58:00 -> 9.9667
    """
    return value.total_seconds() / SECONDS_PER_HOUR


def duration_to_hhmmss(value: timedelta) -> str:
    """
    Convert a duration into HH:MM:SS.
    Example:
        9.5 hours -> "09:30:00"
    """
    total_seconds = max(0, round(value.total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def duration_to_hm(value: timedelta) -> str:
    """
    Short H:MM text for remarks / traces.
    Example:
        timedelta(hours=2, minutes=30) -> "2:30"
    """
    total_minutes = max(0, round(value.total_seconds() / 60))
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}:{minutes:02d}"


# ============================================================
# SECONDS HELPERS
# The "Hours" column is always stored in whole seconds.
# ============================================================
def duration_to_seconds(value: timedelta) -> int:
    """
    Convert a duration into seconds, dropping leftover seconds.
    Example:
        08:30:45 -> 30600
    """
    return (int(value.total_seconds()) // 60) * 60


def seconds_to_duration(seconds: Any) -> timedelta:
    """
    Convert whole seconds into a duration.
    Blank, negative or non-numeric values become zero.
    Example:
        30600 -> 08:30:00
    """
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return ZERO_DURATION
    if pd.isna(value) or value <= 0:
        return ZERO_DURATION
    return timedelta(seconds=round(value))


def cap_seconds(seconds: Any, max_hours: float = MAX_ORDINARY_HOURS) -> int:
    """
    Cap a seconds value at a maximum number of hours.
    Example:
        32400 seconds (9 hours), max 8 hours -> 28800
    """
    return min(
        duration_to_seconds(seconds_to_duration(seconds)),
        round(max_hours * SECONDS_PER_HOUR),
    )


# ============================================================
# OVERTIME HELPER
# ============================================================
def has_overtime(value: Any) -> bool:
    """
    Check whether Overtime is greater than zero.
    Example:
        "01:00:00" -> True
        "00:00:00" -> False
    """
    return parse_duration(value) > ZERO_DURATION


# ============================================================
# CLOCK HELPERS
# ============================================================
def parse_clock_time(value: Any) -> Optional[time]:
    """
    Convert a clock boundary into time at payroll minute precision.

    Clock In / Clock Out timestamps are truncated to the minute before any
    payroll slicing. Seconds are dropped, never rounded. Duration fields are
    handled separately by parse_duration() and retain their second precision.

    Examples:
        "00:00:02"            -> time(0, 0)
        "20:53:59"            -> time(20, 53)
        "10:30:45 PM"         -> time(22, 30)
        0.9375                -> time(22, 30)
        "2026-08-21 22:30:45" -> time(22, 30)
    """
    if is_missing(value):
        return None

    def minute_precision(parsed: time) -> time:
        return parsed.replace(second=0, microsecond=0)

    if isinstance(value, time):
        return minute_precision(value)

    if isinstance(value, (datetime, pd.Timestamp)):
        return minute_precision(value.time())

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 0 <= float(value) < 1:
            total_seconds = round(float(value) * SECONDS_PER_DAY) % SECONDS_PER_DAY
            hours, remainder = divmod(total_seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            return time(hours, minutes)
        return None

    text = re.sub(r"\s+", "", normalize_text(value).upper())

    for clock_format in ("%H:%M:%S", "%H:%M", "%I:%M:%S%p", "%I:%M%p", "%I%p"):
        try:
            return minute_precision(datetime.strptime(text, clock_format).time())
        except ValueError:
            continue

    # Fallback: full date-time text such as "2026-08-21 22:00:45"
    parsed = pd.to_datetime(str(value), errors="coerce")
    if pd.isna(parsed):
        return None
    return minute_precision(parsed.time())

def combine_date_and_time(work_date: Any, time_value: Any) -> Optional[datetime]:
    """
    Combine a date and clock time.
    Example:
        "2026-08-21", "22:00:00" -> 2026-08-21 22:00
    """
    parsed_date = parse_work_date(work_date)
    parsed_time = parse_clock_time(time_value)
    if parsed_date is None or parsed_time is None:
        return None
    return datetime.combine(parsed_date, parsed_time)


def get_clock_window(
    work_date: Any,
    clock_in: Any,
    clock_out: Any,
) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Build the Clock In and Clock Out window.
    Example:
        "21:00:00", "06:00:00" -> 9 PM to next-day 6 AM
    """
    start = combine_date_and_time(work_date, clock_in)
    end = combine_date_and_time(work_date, clock_out)
    if start is None:
        return None, None
    if end is not None and end <= start:
        end += timedelta(days=1)
    return start, end


def align_to_shift(clock_start: datetime, shift_start: Optional[datetime]) -> datetime:
    """
    Move a clock-in to the day closest to the shift start.
    The row date is the SHIFT date, so an early clock-in before midnight
    belongs to the previous calendar day.
    Example (row date Aug 30, shift 12:00AM):
        Aug 30 23:49 -> Aug 29 23:49   (11 min early, not 24 h late)
        Aug 30 00:06 -> Aug 30 00:06   (unchanged)
    """
    if shift_start is None:
        return clock_start
    half_day = timedelta(hours=12)
    if clock_start - shift_start > half_day:
        return clock_start - timedelta(days=1)
    if shift_start - clock_start > half_day:
        return clock_start + timedelta(days=1)
    return clock_start


# ============================================================
# SHIFT HELPERS
# ============================================================
def clean_shift_text(shift: Any) -> str:
    """
    Remove the shift location suffix and normalise noon / midnight.
    Example:
        "6:00AM - 3:00PM (PH)" -> "6:00AM - 3:00PM"
        "12:00NN - 9:00PM"     -> "12:00PM - 9:00PM"
    """
    text = normalize_text(shift)
    if not text:
        return ""
    text = re.sub(r"\s*\((?:PH|AU)\)\s*$", "", text, flags=re.IGNORECASE).strip()
    # "12:00NN" = noon, "12:00MN" = midnight
    text = re.sub(r"(?<=\d)\s*NN\b", "PM", text, flags=re.IGNORECASE)
    return re.sub(r"(?<=\d)\s*MN\b", "AM", text, flags=re.IGNORECASE)


def extract_time_values(text: str) -> list[str]:
    """
    Extract clock values from text.
    Example:
        "Shift 7 (6AM - 3PM)" -> ["6AM", "3PM"]
    """
    time_pattern = (
        r"\b(?:"
        r"(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?"
        r"|"
        r"(?:1[0-2]|0?[1-9])(?::[0-5]\d(?::[0-5]\d)?)?\s*(?:AM|PM)"
        r")\b"
    )
    return re.findall(time_pattern, text, flags=re.IGNORECASE)


_HOURS_END = re.compile(r"(\d+)H-(\d{1,4})(AM|PM)", re.IGNORECASE)


def parse_hours_end_shift(shift: Any) -> tuple[Optional[time], Optional[time]]:
    """
    Read shifts written as "<hours>H-<end time>".
    Example:
        "9H-430AM" -> time(19, 30), time(4, 30)
    """
    match = _HOURS_END.fullmatch(clean_shift_text(shift).replace(" ", ""))
    if not match:
        return None, None

    digits = match.group(2)
    if len(digits) <= 2:
        hour, minute = int(digits), 0
    else:
        hour, minute = int(digits[:-2]), int(digits[-2:])

    end = parse_clock_time(f"{hour}:{minute:02d}{match.group(3)}")
    if end is None:
        return None, None

    start = (
        datetime.combine(date(2000, 1, 1), end) - timedelta(hours=int(match.group(1)))
    ).time()
    return start, end


def parse_shift_times(shift: Any) -> tuple[Optional[time], Optional[time]]:
    """
    Extract the shift start and end.
    Example:
        "7:00PM - 4:00AM" -> time(19, 0), time(4, 0)
    """
    text = clean_shift_text(shift)
    if not text:
        return None, None
    time_values = extract_time_values(text)
    if len(time_values) < 2:
        return parse_hours_end_shift(shift)
    return parse_clock_time(time_values[0]), parse_clock_time(time_values[1])


def get_shift_window(
    work_date: Any,
    shift: Any,
) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Build the scheduled shift window.
    Example:
        "2026-08-21", "7PM - 4AM" -> Aug 21 7 PM to Aug 22 4 AM
    """
    parsed_date = parse_work_date(work_date)
    shift_start, shift_end = parse_shift_times(shift)
    if parsed_date is None or shift_start is None or shift_end is None:
        return None, None
    start = datetime.combine(parsed_date, shift_start)
    end = datetime.combine(parsed_date, shift_end)
    if end <= start:
        end += timedelta(days=1)
    return start, end


# ============================================================
# TIME WINDOW HELPERS
# ============================================================
def build_work_pieces(
    start: datetime,
    paid: timedelta,
    has_break: bool = True,
    break_after: timedelta = timedelta(hours=BREAK_AFTER_HOURS),
    break_length: timedelta = timedelta(hours=BREAK_HOURS),
) -> tuple[list[tuple[datetime, datetime]], Optional[tuple[datetime, datetime]]]:
    """
    Lay the paid hours on the clock with the unpaid break as a gap.
    Returns (work_pieces, break_window). The break is never paid or NSD.

    The break only exists if paid work goes past break_after.
    If paid <= 4h (half day, undertime) the person stopped before the break.

    Example (start 23:00, paid 8h):
        work  [(23:00, 03:00), (04:00, 08:00)]
        break (03:00, 04:00)
    Example (start 22:00, paid 4h):
        work  [(22:00, 02:00)], break None
    """
    if not has_break or paid <= break_after:
        return [(start, start + paid)], None

    break_start = start + break_after
    break_end = break_start + break_length
    remaining = paid - break_after
    return [(start, break_start), (break_end, break_end + remaining)], (break_start, break_end)


def split_at_midnights(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """
    Cut a window at EVERY midnight it crosses (loop, not a single split).
    Example:
        10 PM-6 AM -> [(10 PM, 12 AM), (12 AM, 6 AM)]
        6 AM-3 PM  -> [(6 AM, 3 PM)]
    """
    pieces = []
    current = start
    while current < end:
        next_midnight = datetime.combine(current.date() + timedelta(days=1), time.min)
        piece_end = min(next_midnight, end)
        pieces.append((current, piece_end))
        current = piece_end
    return pieces


# ============================================================
# EXCEL FORMAT HELPERS (export only)
# Keep durations as timedelta until here.
# ============================================================
def duration_to_excel_time(value: Any) -> float:
    """
    Convert a duration/time into an Excel time value (fraction of a day).
    Examples:
        timedelta(hours=9, minutes=58) -> 0.41527778
        "09:58:00"                     -> 0.41527778
        time(9, 58)                    -> 0.41527778
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return 0.0 if pd.isna(value) else float(value)
    if isinstance(value, timedelta):
        return value.total_seconds() / SECONDS_PER_DAY
    if isinstance(value, time):
        return (value.hour * 3600 + value.minute * 60 + value.second) / SECONDS_PER_DAY
    return parse_duration(value).total_seconds() / SECONDS_PER_DAY


def format_duration(
    value: timedelta,
    output_format: Literal["duration", "hhmm", "decimal"] = "hhmm",
) -> str | float:
    """
    Examples:
        09:58:00 -> 0.41527778  ("hhmm", Excel time — default)
        09:58:00 -> 9.9667      ("decimal")
        09:58:00 -> "09:58:00"  ("duration")
    """
    if output_format == "hhmm":
        return duration_to_excel_time(value)
    if output_format == "decimal":
        return round(duration_to_hours(value), 4)
    if output_format == "duration":
        return duration_to_hhmmss(value)
    raise ValueError("output_format must be 'duration', 'hhmm', or 'decimal'.")


def clock_to_excel_time(value: Any) -> Any:
    """
    Clock value -> Excel time so the time format applies.
    Unparseable values are returned unchanged.
    NOTE: never leave datetime.time objects — pandas writes them as text.
    Example:
        "22:30:00" -> 0.9375
    """
    parsed = parse_clock_time(value)
    if parsed is None:
        return value
    return (parsed.hour * 3600 + parsed.minute * 60 + parsed.second) / SECONDS_PER_DAY


def prepare_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    Get the DataFrame ready for writing. All value conversion happens here,
    so format_workbook() only applies cell formats.

        Date        -> date (no time part)
        Day         -> inserted right after Date (day of month)
        Clock In/Out-> Excel time
        Hours       -> seconds converted to Excel time
        Detailed Remarks moved to the last column
    """
    df = df.copy()

    if "Detailed Remarks" in df.columns:
        df = df[[*df.columns.drop("Detailed Remarks"), "Detailed Remarks"]]

    if "Date" in df.columns:
        dates = pd.to_datetime(df["Date"], errors="coerce")
        df["Date"] = dates.dt.date
        if "Day" not in df.columns:
            df.insert(df.columns.get_loc("Date") + 1, "Day", dates.dt.day)

    for col in CLOCK_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(clock_to_excel_time)

    if "Hours" in df.columns:
        df["Hours"] = pd.to_numeric(df["Hours"], errors="coerce") / SECONDS_PER_DAY

    return df


def format_workbook(
    output_path: str | Path,
    sheet_name: str,
    time_columns: Iterable[str],
    freeze_at: str = "K2",
) -> None:
    """
    Apply cell formats to an already-written sheet. No value changes.

        freeze panes, header filter, auto width, bold header,
        time_columns -> "hh:mm", Clock In/Out -> "hh:mm:ss AM/PM" (12-hour)

    time_columns is passed in so this module never imports the header lists.
    """
    time_columns = set(time_columns)

    wb = load_workbook(output_path)
    ws = wb[sheet_name]

    ws.freeze_panes = freeze_at
    ws.auto_filter.ref = ws.dimensions

    for column in ws.columns:
        longest = max((len(str(c.value)) for c in column if c.value is not None), default=0)
        ws.column_dimensions[get_column_letter(column[0].column)].width = min(longest + 2, 50)

    for header in ws[1]:
        header.font = Font(bold=True)

        if header.value in time_columns:
            number_format, width = "hh:mm", 10
        elif header.value in CLOCK_COLUMNS:
            number_format, width = "hh:mm:ss AM/PM", 14
        else:
            continue

        for (cell,) in ws.iter_rows(min_row=2, min_col=header.column, max_col=header.column):
            cell.number_format = number_format
        ws.column_dimensions[get_column_letter(header.column)].width = width

    wb.save(output_path)
