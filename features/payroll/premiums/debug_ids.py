"""
debug_ids.py
------------
Employee IDs to stop on while debugging the slicer.

Usage (in slicer.py):
    if is_debug(row, DEBUG_ORD_NO_OT):
        pass  # <- set breakpoint here

Comment out an ID to skip it. Empty list = no debug stops.
Dates assume Aug 21 = Special holiday, Aug 31 = Legal holiday.
RD = "Weekly Off" in Status Final. Both scenarios handle Ord and RD rows.
RD follows the SHIFT (whole row, also after midnight); holidays follow the calendar day.
Exception: OT landing on the employee's weekly off date -> RD-OT.
"""
from typing import Any

# ============================================================
# ORDINARY / REST DAY, NO OT
# ============================================================
DEBUG_ORD_NO_OT = [
    "IE0-1174",  # Aug 30 – night shift into Legal holiday
    "IE0-063",   # Aug 25 – early clock-in NSD + capped
    "IE0-1609",  # Sep 1  – shift-based start (Flexi + NSD)
    "IE0-1535",  # Aug 25 – No-NSD policy, shift start
    "IE0-1275",  # Aug 23 – 12:00NN shift
    "IE0-1226",  # Sep 4  – Half Day Unpaid cap
    "IE0-1168",  # Aug 23/24/29/30 – 12MN buffer (Aug 30 = early clock-in before midnight)
    "IE0-1281",  # Aug 22 – break starts before 10 PM and ends after it
    "IE0-1487",  # Sep 5  – break starts before 6 AM and ends after it
    "IE0-1777",  # Aug 30 – break fully inside NSD
    "IE0-706",   # Aug 26 – break ends before 10 PM, work after it moves into NSD
    "IE0-1966",  # Aug 27 – break starts after 6 AM
    "IE0-437",   # Sep 1  – work touches NSD by a few minutes
    "IE0-1243",  # Sep 5  – weekly off, no OT -> RD (not Ord)
    "IE0-1970",  # Sep 4  – bad attendance: Clock In 18:01 on a 6AM shift -> CHECK flag
]

# ============================================================
# ORDINARY / REST DAY, WITH OT
# ============================================================
DEBUG_ORD_OT = [
    "IE0-1590",  # Aug 30 – pre + post shift OT, post-shift OT lands on Legal holiday
    "IE0-433",   # Aug 23 – pre-shift OT moves ordinary start (clock in 17:47 -> 21:00)
    "IE0-1306",  # Aug 24 – 4h pre-shift OT window, OT 3:52 trimmed, ordinary starts 14:00
    "IE0-2041",  # Aug 25 – OT split across two windows (pre 06:03 + post 17:00)
    "IE0-1962",  # Sep 2  – pre-shift OT fully inside NSD (22:00-00:00)
    "IE0-2038",  # Sep 2  – early clock-in, gap between ordinary end and OT window
    "IE0-1157",  # Aug 24 – no approved OT window, OT placed after shift end
    "IE0-1086",  # Sep 3  – weekly off, 8h OT -> RD-OT 8 (as is)
    "IE0-1219",  # Aug 29 – weekly off, Hours 8:07 > OT 8:00 -> extra 0:07 RD after the OT
    "IE0-1303",  # Aug 29 – weekly off night OT, after midnight stays RD-ND-OT (shift rule)
                 # Aug 28 – OVERLAP: ordinary runs into OT window 05:00-09:00, 0:13 moved after
    "IE0-2103",  # Sep 2  – weekly off, OT 00:00-08:00 on next calendar day -> RD-OT (shift rule)
    "IE0-1562",  # Aug 23 – 12h OT -> OT 12h straight (as is, no break)
]


# ============================================================
# RD / HOLIDAY / RD + HOLIDAY  (hours from Overtime, capped by raw logs)
# ============================================================
DEBUG_PREMIUM_NO_OT = [
    # --- Where the hours land: OT window first, Clock In/Out as backup ---
    "IE0-033",   # Aug 21 – OT 8:00 fits window 06:08-15:08 -> 06:08-10:08 | BREAK | 11:08-15:08
    "IE0-1002",  # Aug 21 – Clock In 06:05 but window 08:30-17:30 -> starts 08:30 (OT start)
    "IE0-1306",  # Aug 31 – OT 11:48 > window 4:49, fits logs -> Clock In used, "Wrong OT window filing"
    "IE0-1157",  # Aug 31 – no OT window -> Clock In/Out used
    "IE0-1086",  # Sep 3  – Present,Weekly Off, OT 8:00 -> RD 4 | BREAK | RD 4
    "IE0-1149",  # Aug 26 – Present,Weekly Off, OT 8:00 vs logs 7:58
    "IE0-033",   # Aug 21 SH / Aug 31 LH – Present,Holiday, OT 8:00 -> SH 8 / LH 8
    "IE0-001",   # Aug 21 – Present,Holiday, no OT -> Ord 8 (worked holiday, no approved OT)
    "IE0-1243",  # Sep 5  – Present,Weekly Off, no OT -> SKIPPED: RD without approved OT
]

DEBUG_PREMIUM_OT = [
    "IE0-1303",  # Aug 22 – Present,Weekly Off night, OT 8:02 -> RD 8 + RD-OT 0:02
    "IE0-1137",  # Aug 21 – Present,Holiday SH night: SH before midnight, Ord after, OT on weekly off -> RD-OT
    "IE0-1128",  # Aug 31 – Present,Holiday LH, OT 8:51 -> LH 8 + LH-OT 0:51
]

# ============================================================
# NOT COMPUTED / SKIPPED
# ============================================================
DEBUG_OTHER = [
    "IE0-1727",  # Oct 26 – early 20:53 on 9PM-6AM + 4h post-shift OT -> start 21:00 -> Ord 1 + Ord-ND 7 + RD-OT 4
    "IE0-063",   # Oct 21 – early 04:07 on 4:30AM shift (early minutes are NSD) -> Clock In kept
    "IE0-2182",  # Oct 23 – Present, blank Policy -> Breakdown Valid False, "Blank policy."
    "IE0-2216",  # Nov 5  – Clock 05:52-22:20 (16:28) -> CHECK: possible missing clock out
    "IE0-1138",  # Oct 31 – late 0:23, no OT -> start snapped 0:31 to Clock Out -> SH-ND 1:00 after midnight
    "IE0-2115",  # Aug 29 – Weekly Off,Request + Overtime 8:00 -> CHECK: Overtime without Present
    "IE0-1313",  # Aug 26 – Unpaid Leave with 2:16 logged -> SKIPPED: Unpaid Leave
]


def is_debug(row: Any, ids: list[str]) -> bool:
    """
    True if this row's Employee ID is in the debug list.
    Example:
        row IE0-1590, DEBUG_ORD_OT -> True
    """
    return str(row.get("Employee ID", "")).strip() in ids
