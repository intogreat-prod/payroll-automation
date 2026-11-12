"""
ot.py
-----
WHERE approved OT happens. Pure lookup: no policy, NSD or holiday logic.

    build_ot_lookup() -> {(employee_id, shift_date): [(start, end), ...]}
    get_ot_windows()  -> OT windows for one attendance row

HOW MUCH OT is paid always comes from the attendance "Overtime" column.
This lookup only tells the slicer where on the clock those hours sit.

Key = Employee ID + "Date" (OT Shift Date, renamed in _OT_COLUMNS = attendance Date), so post-shift OT
after midnight (OT Start Date = next day) still matches its shift.
One shift can have several windows (pre-shift + post-shift) -> sorted list.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd

from features.payroll.premiums.helpers import (
    combine_date_and_time,
    normalize_text,
    parse_work_date,
)

OtKey = tuple[str, date]
OtWindow = tuple[datetime, datetime]


def build_ot_lookup(ot_df: Optional[pd.DataFrame]) -> dict[OtKey, list[OtWindow]]:
    """
    Group approved OT windows by (Employee ID, OT Shift Date).
    Duplicate windows (same request listed twice) are kept once.
    Example:
        IE0-1590, shift 2026-08-30, 20:00-22:00 and 07:00-08:00 (next day) ->
        {("IE0-1590", date(2026, 8, 30)): [(Aug 30 20:00, 22:00), (Aug 31 07:00, 08:00)]}
    """
    lookup: dict[OtKey, set[OtWindow]] = defaultdict(set)
    if ot_df is None or ot_df.empty:
        return {}

    for _, row in ot_df.iterrows():
        employee_id = normalize_text(row.get("Employee ID"))
        shift_date = parse_work_date(row.get("Date"))
        start = combine_date_and_time(row.get("OT Start Date"), row.get("OT Start Time"))
        end = combine_date_and_time(row.get("OT End Date") or row.get("OT Start Date"), row.get("OT End Time"))

        if not employee_id or shift_date is None or start is None or end is None:
            continue
        while end <= start:  # end date missing / same as start, e.g. 22:00-00:00
            end += timedelta(days=1)

        lookup[(employee_id, shift_date)].add((start, end))

    return {key: sorted(windows) for key, windows in lookup.items()}


def get_ot_windows(row: Any, ot_lookup: dict[OtKey, list[OtWindow]]) -> list[OtWindow]:
    """
    OT windows for one attendance row (Employee ID + Date).
    Example:
        IE0-1590 / 2026-08-30 -> [(20:00, 22:00), (07:00, 08:00)]
        no approved OT        -> []
    """
    key = (normalize_text(row.get("Employee ID")), parse_work_date(row.get("Date")))
    return ot_lookup.get(key, [])
