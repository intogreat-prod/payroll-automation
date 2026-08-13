"""
features/payroll
-----------------
All feature modules that belong to the Payroll app within the Finance Suite:

    payroll.py             — PayrollFeature: file picker, validation, upload prep
    checker.py              — CheckerFeature: variance checker file picker/validation
    dbx_to_sprout.py         — DarwinToSproutTool: DarwinBox → Sprout conversion tool
    attendance_summary.py   — AttendanceSummaryTool: attendance summary generator
    settings.py              — Payroll settings helpers (users, deminimis)

Grouped here (rather than flat under features/) so each suite app owns its
own feature namespace as more apps (Billing, ...) are added.
"""
