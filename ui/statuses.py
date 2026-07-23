"""
statuses.py
-----------
All user-facing status message dictionaries and the status-code parser.

Structure
---------
Status codes are plain strings used as keys in these dicts.  When a
file name is associated with the status, the code is encoded as:

    "<file_name>|<status_code>"   e.g. "Payroll Register.xlsx|sensitivity_error"

parse_status_code() splits this back into (file_name, status_code) so
Body can format the final display string with the file name interpolated.

Message templates may contain a {file_name} slot which is filled at
render time in Body._show_status().

Dictionaries
------------
PAYROLL_STATUSES  — codes emitted by the Payroll upload + Unmand flow
CHECKER_STATUSES  — codes emitted by the Checker file-validation flow
SETTINGS_STATUSES — codes emitted by the Settings (users + deminimis) flow
DBX_TO_SPROUT_STATUSES — codes emitted by the DarwinBox to Sprout conversion flow
ATTENDANCE_SUMMARY — codes emitted by the Attendance Summary flow
"""


# ---------------------------------------------------------------------------
# PARSER
# ---------------------------------------------------------------------------

def parse_status_code(code: str) -> tuple[str, str]:
    """
    Split a status code into its (file_name, status_key) parts.

    Parameters
    ----------
    code : str
        Either a bare status key  ("file_success")
        or a pipe-separated pair  ("Report.xlsx|sensitivity_error").

    Returns
    -------
    tuple[str, str]
        (file_name, status_key).
        file_name is an empty string when no pipe separator is present.
    """
    if "|" in code:
        file_name, status_key = code.split("|", maxsplit=1)
    else:
        file_name  = ""
        status_key = code

    return file_name, status_key


# ---------------------------------------------------------------------------
# PAYROLL STATUSES
# Emitted by: features/payroll.py, orchestrator._upload_sp_files,
#             orchestrator._start_unmand, orchestrator._check_unmand
# ---------------------------------------------------------------------------

PAYROLL_STATUSES = {

    # ── Success ───────────────────────────────────────────────────────
    "file_success":            "Files uploaded successfully.",
    "unmand_init_success":     "Unmand initiated successfully. {file_name}",
    "unmand_status_success":   "Unmand automation completed successfully. "
                               "Please verify the generated output.",

    # ── File errors ───────────────────────────────────────────────────
    "no_file_error":           "No files selected — aborting upload.",
    "file_exceed_error":       "Number of files exceeds the expected limit. "
                               "Please verify your upload.",
    "sensitivity_error":       "Payroll Headers and Premium.xlsx sensitivity "
                               "or password protection issue detected.",
    "date_format_error":       "Date format error detected in {file_name}.",
    "not_found_error":         "{file_name} — file not found in the upload.",
    "missing_header_error":    "{file_name} — Missing row 1 header.",
    "missing_total_error":     "Current Payroll has a missing Total row "
                               "in the Employee ID column.",
    "upload_sp_error":         "Error uploading files to SharePoint. "
                               "Please contact the Automation Team.",
    "category_column_error":   "Column 'Charge Type/Category' in Deduction is missing",

    # ── ID / version validation errors ───────────────────────────────
    "id_error":                "ID number not found in previous records.",
    "version_duplicate_error": "This version number already exists.",
    "id_missing_error":        "Version number provided but ID number is missing.",
    "version_missing_error":   "ID number provided but version number is missing.",
    "version_input_error":     "Invalid version format. Please use v1, v2, etc.",

    # ── Configuration / reference file errors ────────────────────────
    "premium_download_error":  "Payroll Headers and Premium.xlsx download error. "
                               "Please check the SharePoint location.",
    "new_headers_error":       "New headers detected. Please update Payroll Headers "
                               "in Settings before proceeding.",

    # ── Unmand errors ─────────────────────────────────────────────────
    "unmand_init_error":          "Failed to start Unmand. "
                                  "Please contact the Automation Team.",
    "unmand_status_error":        "Unmand encountered an error. "
                                  "Please check your inbox for details.",
    "unmand_status_pending_error": "Unmand is still processing. "
                                   "Please check again shortly.",
}


# ---------------------------------------------------------------------------
# CHECKER STATUSES
# Emitted by: features/checker.py, orchestrator._generate_validation
# ---------------------------------------------------------------------------

CHECKER_STATUSES = {

    # ── Success ───────────────────────────────────────────────────────
    "file_success":           "Files added successfully.",
    "validated_success":      "Checker validation completed successfully.",

    # ── File count / identity errors ──────────────────────────────────
    "no_file_error":          "No files selected — aborting upload.",
    "file_exceed_error":      "Number of files exceeds the expected limit "
                              "of 2. Please verify your upload.",
    "manual_error":           "Manual Checker file not found.",
    "unmand_error":           "Unmand Checker file not found.",

    # ── Structural errors ─────────────────────────────────────────────
    "missing_header_error":   "{file_name} — Missing Row 1 Header.",
    "missing_total_error":    "{file_name} — Missing Total row in "
                              "the Employee ID column.",
    "sensitivity_error":      "File sensitivity or password protection "
                              "issue detected in {file_name}.",

    # ── Configuration / reference file errors ────────────────────────
    "premium_download_error": "Payroll Headers and Premium.xlsx download error. "
                              "Please check the SharePoint location.",
}


# ---------------------------------------------------------------------------
# SETTINGS STATUSES
# Emitted by: orchestrator._save_deminimis, orchestrator._add_user
# ---------------------------------------------------------------------------

SETTINGS_STATUSES = {

    # ── Success ───────────────────────────────────────────────────────
    "deminimis_save_success": "Deminimis values saved successfully.",
    "add_user_success":       "User added successfully.",

    # ── Save / operation errors ───────────────────────────────────────
    "deminimis_save_error":   "Failed to save deminimis. "
                              "Please contact the Automation Team.",
    "add_user_error":         "Failed to add user. "
                              "Please contact the Automation Team.",
    "add_user_email_error":   "User added, but the welcome email could not be sent. "
                              "Please contact the Automation Team.",

    # ── Input validation errors ───────────────────────────────────────
    "empty_error":            "Email address field is empty. Please enter an email.",
    "error_email":            "Invalid email domain. "
                              "Please use an @intogreatsolutions.com address.",
    "duplicate_user":         "This user already has access. "
                              "Please check the user list above.",
    "error_value":            "Invalid input value. "
                              "Please check your entry and try again.",
}


# ---------------------------------------------------------------------------
# DARWINBOX TO SPROUT STATUSES
# Emitted by: features/dbx_sprout.py [DarwinToSproutTool], 
#             orchestrator._generate_conversion
# ---------------------------------------------------------------------------

DBX_TO_SPROUT_STATUSES = {

    # ── Success ───────────────────────────────────────────────────────
    "file_success":           "File added successfully.",
    "converted_success":      "DarwinBox Payroll converted completed successfully.",

    # ── File count / identity errors ──────────────────────────────────
    "no_file_error":          "No file selected — aborting upload.",
    "file_exceed_error":      "Number of file exceeds the expected limit "
                              "of 1. Please verify your upload.",

    # ── Structural errors ─────────────────────────────────────────────
    "missing_header_error":   "{file_name} — Missing Row 1 Header.",
    "missing_total_error":    "{file_name} — Missing Total row in "
                              "the Employee ID column.",
    "sensitivity_error":      "File sensitivity or password protection "
                              "issue detected in {file_name}.",

    # ── Configuration / reference file errors ────────────────────────
    "premium_download_error": "Payroll Headers and Premium.xlsx download error. "
                              "Please check the SharePoint location.",
}

# ---------------------------------------------------------------------------
# ATTENDANCE SUMMARY
# Emitted by: features/attendance_summary.py [AttendanceSummaryTool], 
#             orchestrator._generate_summary
# ---------------------------------------------------------------------------

ATTENDANCE_SUMMARY = {

    # ── Success ───────────────────────────────────────────────────────
    "file_success":           "File added successfully.",
    "summarized_success":      "DarwinBox attendance report summarized successfully.",


    # ── File count / identity errors ──────────────────────────────────
    "no_file_error":          "No file selected — aborting upload.",
    "file_exceed_error":      "Number of file exceeds the expected limit "
                              "of . Please verify your upload.",

    # ── Date Inputs Errors ──────────────────────────────────────────────
    "date_same_error":         "Start Date and Cut-off Date cannot be the same.",
    "date_range_error":        "The Cut-off Date cannot be earlier than the Start Date.",
    "date_range_error":        "Date format error. Please contact support.",

    # ── Structural errors ─────────────────────────────────────────────
    "missing_header_error":   "{file_name} — Missing Row 1 Header.",
    "missing_columns_error":  "Missing {file_name} column.",
    "sensitivity_error":      "File sensitivity or password protection "
                              "issue detected in {file_name}.",

    # ── Processing Error ────────────────────────
    "processing_error": "The tool ecountered an error. Please contact support.",
}