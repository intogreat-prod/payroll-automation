"""
nsd.py
------
Pure time math for Night Shift Differential (10 PM - 6 AM).
No policy, no holiday, no break, no DataFrame. Testable on its own:

    split_nsd(10 PM, 6 AM, True) -> (0h regular, 8h NSD)
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from features.payroll.premiums.helpers import ZERO_DURATION

NSD_START = time(22, 0)
NSD_END = time(6, 0)


def calculate_overlap(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
) -> timedelta:
    """
    Overlap of two periods.
    Example:
        9 PM-5 AM versus 10 PM-6 AM -> 7 hours
    """
    overlap_start = max(first_start, second_start)
    overlap_end = min(first_end, second_end)
    if overlap_end <= overlap_start:
        return ZERO_DURATION
    return overlap_end - overlap_start


def calculate_nsd_duration(work_start: datetime, work_end: datetime) -> timedelta:
    """
    Work time inside every 10 PM-6 AM period the window touches.
    Example:
        9 PM-5 AM -> 7 hours
    """
    if work_end <= work_start:
        return ZERO_DURATION

    total_nsd = ZERO_DURATION
    current_date = work_start.date() - timedelta(days=1)
    while current_date <= work_end.date():
        nsd_start = datetime.combine(current_date, NSD_START)
        nsd_end = datetime.combine(current_date + timedelta(days=1), NSD_END)
        total_nsd += calculate_overlap(work_start, work_end, nsd_start, nsd_end)
        current_date += timedelta(days=1)
    return total_nsd


def split_nsd(start: datetime, end: datetime, compute_nsd: bool) -> tuple[timedelta, timedelta]:
    """
    Split a window into (regular, nsd). regular + nsd always equals end - start.
    Example:
        10 PM-12 AM, True  -> (0h, 2h)
        10 PM-12 AM, False -> (2h, 0h)
    """
    total = max(end - start, ZERO_DURATION)
    nsd = calculate_nsd_duration(start, end) if compute_nsd else ZERO_DURATION
    nsd = min(nsd, total)
    return total - nsd, nsd
