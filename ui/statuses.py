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
BILLING_STATUSES  — codes emitted by the Billing upload + Unmand flow
CHECKER_STATUSES  — codes emitted by the Checker file-validation flow
SETTINGS_STATUSES — codes emitted by the Settings (users + deminimis) flow
EXCEL_LOCKER_STATUSES — codes emitted by the Toolbox Excel Locker flow
DBX_TO_SPROUT_STATUSES — codes emitted by the DarwinBox to Sprout conversion flow
ATTENDANCE_SUMMARY — codes emitted by the Attendance Summary flow
ATT_ADJ_STATUSES  — codes emitted by the Billing Attendance Adjustment flow
INSIGHTFUL_STATUSES — codes emitted by the Billing Insightful tracker flow
"""


# ---------------------------------------------------------------------------
# PARSER
# ---------------------------------------------------------------------------

import orchestrator


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
#              orchestrator._save_deminimis,
# ---------------------------------------------------------------------------

PAYROLL_STATUSES = {

    # ── Success ───────────────────────────────────────────────────────
    "file_success":            "Files uploaded successfully.",
    "unmand_init_success":     "Unmand initiated successfully. {file_name}",
    "unmand_status_success":   "Unmand automation completed successfully. "
                               "Please verify the generated output.",
    "deminimis_save_success": "Deminimis values saved successfully.",


    # ── File errors ───────────────────────────────────────────────────
    "no_file_error":           "No files selected — aborting upload.",
    "file_exceed_error":       "Number of files exceeds the expected limit. "
                               "Please verify your upload.",
    "headers_sensitivity_error":       "Payroll Headers and Premium.xlsx sensitivity "
                               "or password protection issue detected.",
    "sensitivity_error":       "{file_name} sensitivity "
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

    # ── Save Deminimis/ operation errors ───────────────────────────────────────
    "deminimis_save_error":   "Failed to save deminimis. "
                              "Please contact the Automation Team.",
    "error_value":            "Invalid input value. "
                              "Please check your entry and try again.",
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
    "sensitivity_error":      "File sensitivity or password protection issue detected in {file_name}. If the issue\n"
                              "persists, please create a new file with the same content and try again.",

    # ── Configuration / reference file errors ────────────────────────
    "premium_download_error": "Payroll Headers and Premium.xlsx download error. "
                              "Please check the SharePoint location.",
}


# ---------------------------------------------------------------------------
# BILLING STATUSES
# Emitted by: features/billing/billing.py [BillingFeature], the Billing
#             SharePoint upload + Unmand flow in billing_orchestrator.py
# Mirrors PAYROLL_STATUSES minus the payroll-only checks (attendance date
# format, Total row, deduction column) that don't apply to Billing files.
# ---------------------------------------------------------------------------

BILLING_STATUSES = {

    # ── Success ───────────────────────────────────────────────────────
    "file_success":            "Files uploaded successfully.",
    "unmand_init_success":     "Unmand initiated successfully. {file_name}",
    "unmand_status_success":   "Unmand automation completed successfully. "
                               "Please verify the generated output.",

    # ── File errors ───────────────────────────────────────────────────
    "no_file_error":           "No files selected — aborting upload.",
    "file_exceed_error":       "Number of files exceeds the expected limit. "
                               "Please verify your upload.",
    "sensitivity_error":       "{file_name} sensitivity "
                               "or password protection issue detected.",
    "not_found_error":         "{file_name} — file not found in the upload.",
    "upload_sp_error":         "Error uploading files to SharePoint. "
                               "Please contact the Automation Team.",

    # ── Unmand errors ─────────────────────────────────────────────────
    "unmand_init_error":          "Failed to start Unmand. "
                                  "Please contact the Automation Team.",
    "unmand_status_error":        "Unmand encountered an error. "
                                  "Please check your inbox for details.",
    "unmand_status_pending_error": "Unmand is still processing. "
                                   "Please check again shortly.",
}


# ---------------------------------------------------------------------------
# BILLING CHECKER STATUSES
# Emitted by: features/billing/checker.py [BillingCheckerFeature],
#             orchestrators/billing_orchestrator.py
# ---------------------------------------------------------------------------

BILLING_CHECKER_STATUSES = {

    # ── Success ───────────────────────────────────────────────────────
    "file_success":           "Files added successfully.",
    "validated_success":      "Checker validation completed successfully.",

    # ── File count / identity errors ──────────────────────────────────
    "no_file_error":          "No files selected — aborting upload.",
    "file_exceed_error":      "Number of files exceeds the expected limit "
                              "of 2. Please verify your upload.",
    "currency_error":          "{file_name} — Non-AUD currency found.",
    "missing_column_error":    "{file_name}",
    "manual_error":           "Manual Checker file not found.",
    "unmand_error":           "Unmand Checker file not found.",

    # ── Structural errors ─────────────────────────────────────────────
    "missing_header_error":   "{file_name} — Missing Row 1 Header.",
    "sensitivity_error":      "File sensitivity or password protection issue detected in {file_name}. If the issue\n"
                              "persists, please create a new file with the same content and try again.",

    # ── Processing errors ─────────────────────────────────────────────
    "processing_error":       "The checker encountered an error. "
                              "Please contact support.",
}


# ---------------------------------------------------------------------------
# SETTINGS STATUSES
# Emitted by: orchestrator._add_user
# ---------------------------------------------------------------------------

APP_SETTINGS_STATUSES = {
    # ── Success ───────────────────────────────────────────────────────
    "add_user_success":       "User added successfully.",
    "upload_success":          "{file_name} log/s shared successfully.",
    "upload_partial_success": "Logs partially shared. Some logs could not be uploaded.",
    "uploading":              "Sharing logs...",


    # ── Save / operation errors ───────────────────────────────────────
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
    "upload_error":           "Unable to share logs. Please try again or contact the Automation Team.",
    "no_logs_found":          "No logs were found for the selected date range.",
    "no_token_error":         "Authentication token is missing. Please try again.",
    "invalid_range_error":    "Invalid date range. Please select a valid start and cutoff date.",
    "missing_dates_error":    "Please select both a start date and a cutoff date.",
    "empty_selection_error":  "Please select app version to install.",
}

# ---------------------------------------------------------------------------
# EXCEL LOCKER STATUSES
# Emitted by: features/tools_feature.py [_lock_excel, _ExcelLockWorker],
#             orchestrator._lock_excel
#
# The {file_name} slot is reused for whatever value the error is really
# about — a file name most of the time, but a metadata-file line number
# for the TXT-parsing errors, and the exception text for the read error.
# Same overload already used elsewhere (see PAYROLL_STATUSES
# "unmand_init_success").
# ---------------------------------------------------------------------------

EXCEL_LOCKER_STATUSES = {

    # ── Success ───────────────────────────────────────────────────────
    "locked_success":          "{file_name} locked successfully.",

    # ── Selection / metadata errors ──────────────────────────────────
    "no_excel_error":          "No Excel files detected in your selection.",
    "multiple_txt_error":      "Multiple TXT files selected — choose only one.",
    "invalid_format_error":    "Invalid format on line {file_name} of the metadata file.",
    "empty_entry_error":       "Empty filename or password on line {file_name} of the metadata file.",
    "invalid_filename_error":  "{file_name} — invalid filename in the metadata file (must end in .xlsx).",
    "duplicate_entry_error":   "{file_name} — duplicate entry in the metadata file.",
    "metadata_read_error":     "Unable to read the metadata file: {file_name}",

    # ── Matching errors ───────────────────────────────────────────────
    "not_listed_error":        "{file_name} — not listed in the metadata file.",
    "not_uploaded_error":      "{file_name} — listed in the metadata file but not uploaded.",

    # ── Locking errors ────────────────────────────────────────────────
    "already_protected_error": "{file_name} is already password-protected or check the sensitivity.",
    "no_password_error":       "{file_name} — no password provided.",
    "save_cancelled_error":    "{file_name} — save location was not chosen.",
    "failed_to_lock_error":    "{file_name} — failed to lock - please check sensitivity.",
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
    "sensitivity_error":      "File sensitivity or password protection issue detected in {file_name}. If the issue\n"
                              "persists, please create a new file with the same content and try again.",

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
    "sensitivity_error":      "File sensitivity or password protection issue detected in {file_name}. If the issue\n"
                              "persists, please create a new file with the same content and try again.",

    # ── Processing Error ────────────────────────
    "processing_error": "The tool ecountered an error. Please contact support.",
}

# ---------------------------------------------------------------------------
# ATTENDANCE ADJUSTMENT STATUSES
# Emitted by: features/billing/attendance_adjustment.py [AttendanceAdjustmentTool],
#             orchestrator._generate_att_adj
# ---------------------------------------------------------------------------

ATT_ADJ_STATUSES = {

    # ── Success ───────────────────────────────────────────────────────
    "file_success":           "File added successfully.",
    "generated_success":      "Attendance Adjustment generated successfully.",

    # ── File count / identity errors ──────────────────────────────────
    "no_file_error":          "No file selected — aborting upload.",
    "file_count_error":      "Number file error. Expected count is "
                              "3. Please verify your upload.",

    # ── Structural errors ─────────────────────────────────────────────
    "missing_header_error":   "{file_name} — Missing Row 1 Header.",
    "missing_total_error":    "{file_name} — Missing Total row in "
                              "the Employee ID column.",
    "sensitivity_error":      "File sensitivity or password protection issue detected in {file_name}. If the issue\n"
                              "persists, please create a new file with the same content and try again.",

    "not_found_error":        "{file_name} — file not found in the upload.",
    "emp_id_not_found_error": "Employee ID(s) not found in Employee List: {file_name}",
    "currency_format_error":  "Exchange rate has an invalid format.",
    "empty_currency_error":   "Exchange rate is missing.",
    "new_headers_error":      "Please add them to the Payroll Headers. New headers: {file_name}",
    "processing_error":        "An unknown error occured. Please contact Automation Team",

    # ── SharePoint / Unmand errors ──────────────────────────────────────
    "headers_sensitivity_error":    "Please check the sensivity of the Payroll Premium Headers.xlsx Source: {file_name} ",
    "premium_download_error":       "Payroll Premium Headers.xlsx (Payroll Headers and Rates) cannot be downloaded. \n"
                                    "Please Contact the Automation Team.",
    "premium_header_error":         "Header [Payroll Headers and Rates] in Row 13 cannot be find in\n"
                                    "Payroll Premium Headers.xlsx (Payroll Headers and Rates)",

}

# ---------------------------------------------------------------------------
# INSIGHTFUL STATUSES
# Emitted by: features/billing/insightful.py [InsightfulTool],
#             orchestrator._generate_insightful
# ---------------------------------------------------------------------------

INSIGHTFUL_STATUSES = {

    # ── Success ───────────────────────────────────────────────────────
    "file_success":           "File added successfully.",
    "generated_success":      "Insightful tracker updated and generated successfully.",

    # ── New user found — tracker updated, run stopped for review ──────
    "new_user_found":         "New user(s) found and added to the tracker: {file_name}.\n"
                              "Please complete their details — especially the Employee ID — "
                              "before continuing.",
    "new_user_error":         "An error occurred while checking the tracker for new users. "
                              "Please contact the Automation Team.",

    # ── File count / identity errors ──────────────────────────────────
    "no_file_error":          "No file selected — aborting upload.",
    "file_count_error":      "Number file error. Expected count is "
                              "2. Please verify your upload.",

    # ── Structural errors ─────────────────────────────────────────────
    "missing_header_error":   "{file_name} — Missing Row 1 Header.",
    "sensitivity_error":      "File sensitivity or password protection issue detected in {file_name}. If the issue\n"
                              "persists, please create a new file with the same content and try again.",
    "not_found_error":        "{file_name} — file not found in the upload.",
    "emp_id_not_found_error": "Employee ID(s) not found in Employee List: {file_name}",

    "processing_error":        "An unknown error occured. Please contact Automation Team",


    # ── SharePoint / Unmand errors ──────────────────────────────────────
    "premium_download_error":       "Insightful.xlsx (Tracker) cannot be downloaded. \n"
                                    "Please Contact the Automation Team.",
    "tracker_upload_error":         "The updated Insightful tracker could not be uploaded back "
                                    "to SharePoint. Please Contact the Automation Team.",
    "tracker_locked_error":         "The Insightful tracker is currently locked (open in Excel or a "
                                   "co-authoring session elsewhere). Please close it on SharePoint "
                                   "and try again.",
   "tracker_client_error":         "The Insightful tracker request was rejected by SharePoint "
                                   "(HTTP {file_name}). Please contact the Automation Team.",
    "tracker_incomplete_error":     "The following tracker column(s) have blank value(s) that must "
                                   "be completed before the output can be generated: {file_name}.",
}