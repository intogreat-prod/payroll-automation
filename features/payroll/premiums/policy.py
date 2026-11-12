"""
policy.py
---------
Policy rules. Read ONCE per row by slicer.py.
nsd.py and holiday.py never see the policy.

To support a new behaviour later (e.g. ot_eligible), add a flag to
PolicyRule — do not pass the rule into other modules.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Optional

from features.payroll.premiums.helpers import (
    align_to_shift,
    get_clock_window,
    get_shift_window,
    normalize_text,
)

TimeSource = Literal["clock", "shift", "none"]


@dataclass(frozen=True)
class PolicyRule:
    """
    compute_nsd : does NSD apply?
    time_source : where the work window starts ("clock", "shift", "none")
    description : note written to Detailed Remarks
    has_break   : insert the 1-hour unpaid break after the first 4 paid hours?
                  False for Same Day Split Shift (the gap between parts is the break).
    """
    compute_nsd: bool
    time_source: TimeSource
    description: str
    has_break: bool = True


_NO_NSD = "No NSD. All hours assigned to day code."
_NSD_SHIFT = "NSD calculated using Shift."
_NSD_CLOCK = "NSD calculated using Clock In."

POLICY_RULES: dict[str, PolicyRule] = {
    "Flexi Shift with Grace Period (No NSD)":          PolicyRule(False, "shift", _NO_NSD),
    "Flexi Shift with Grace Period + NSD":             PolicyRule(True,  "shift", _NSD_SHIFT),
    "Flexi Shift with No Default Schedule (with NSD)": PolicyRule(True,  "clock", _NSD_CLOCK),
    "Flexi Shift - Morning (No NSD)":                  PolicyRule(False, "shift", _NO_NSD),
    "Flexible Schedule (No NSD)":                      PolicyRule(False, "shift", _NO_NSD),
    "No Time In / Out":                                PolicyRule(True,  "shift", _NSD_SHIFT),
    "No Time In / Out - AU":                           PolicyRule(True,  "shift", _NSD_SHIFT),
    "Requires Time In / Out":                          PolicyRule(True,  "clock", _NSD_CLOCK),
    "Requires Time In / Out (No NSD)":                 PolicyRule(False, "shift", _NO_NSD),
    "Requires Time In / Out (with Buffer for 12MN)":   PolicyRule(True,  "clock", _NSD_CLOCK),
    "Same Day Split Shift":                            PolicyRule(True,  "clock", _NSD_CLOCK, has_break=False),
}

DEFAULT_POLICY_RULE = PolicyRule(
    compute_nsd=False,
    time_source="none",
    description="Unknown policy.",
)

# Case-insensitive lookup, built once
_RULES_BY_KEY = {name.casefold(): rule for name, rule in POLICY_RULES.items()}


def get_policy_rule(policy: Any) -> PolicyRule:
    """
    Return the rule assigned to a policy.
    Example:
        "Requires Time In / Out" -> NSD=True, source="clock"
        "Something new"          -> DEFAULT_POLICY_RULE
    """
    return _RULES_BY_KEY.get(normalize_text(policy).casefold(), DEFAULT_POLICY_RULE)


def get_work_start(row: Any, time_source: TimeSource) -> tuple[Optional[datetime], str]:
    """
    Return the work start and the name of the source used.
    Example:
        "clock" -> Clock In, moved to the day nearest the shift start, "Clock In"
        "shift" -> Shift start on the work date, "Shift"
        "none"  -> None, "Time source"

    Clock example (row date Aug 30, shift 12:00AM - 9:00AM, Clock In 23:49):
        Aug 29 23:49 (early clock-in), not Aug 30 23:49.
    """
    if time_source == "clock":
        start, _ = get_clock_window(row.get("Date"), row.get("Clock In"), row.get("Clock Out"))
        if start is None:
            return None, "Clock In"
        shift_start, _ = get_shift_window(row.get("Date"), row.get("Shift"))
        return align_to_shift(start, shift_start), "Clock In"
    if time_source == "shift":
        start, _ = get_shift_window(row.get("Date"), row.get("Shift"))
        return start, "Shift"
    return None, "Time source"
