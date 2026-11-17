"""
statuses.py
-----------
Single source of truth for every user-facing status in the Finance Suite
(tools AND automations).

Concepts
--------
Status      One message definition: text, level, the aux buttons it reveals,
            and how many extra "lines" of window height it needs.
STATUSES    Registry: tool name -> {status key -> Status}.
resolve()   The ONE way to turn an emitted code into something displayable.

Status codes
------------
Features/orchestrators keep emitting plain strings.  When a value is attached
(a file name, a line number, an HTTP code, ...) it is encoded as

    "<value>|<status_key>"        e.g. "Payroll Register.xlsx|sensitivity_error"

parse_status_code() splits it back.  The value is available to templates as
{file_name} (when it really is a file) or {detail} (anything else) -- both
names point at the same value, so emitters do not need to change.

Levels
------
success | error | warning | info.  The level -- never a substring of the key --
decides colour, log result and whether a run is "final".

Adding a status
---------------
1. Put it in the right base dict (_COMMON for everything, or a flow base).
2. Override it in a tool only if the wording genuinely differs.
3. Run `python -m ui.statuses` (or call validate()) -- it checks every
   template placeholder and aux-button reference.

Tools
-----
payroll, payroll_checker, payroll_settings, dbx_to_sprout, attendance_summary,
billing, billing_checker, att_adj, insightful, app_settings, excel_locker
"""

from __future__ import annotations

import logging
import re
import string
from dataclasses import dataclass

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LEVELS
# ---------------------------------------------------------------------------

SUCCESS = "success"
ERROR   = "error"
WARNING = "warning"
INFO    = "info"

# level -> (css colour for UIFactory.label, hex colour for setStyleSheet)
_COLORS = {
    SUCCESS: ("green",   "#16A34A"),
    ERROR:   ("red",     "#DC2626"),
    WARNING: ("orange",  "#F59E0B"),
    INFO:    ("#D3D0D0", "#D3D0D0"),
}


# ---------------------------------------------------------------------------
# MODEL
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Status:
    """One message definition."""
    text:        str
    level:       str   = ERROR
    aux:         tuple = ()   # aux-button keys revealed by this status
    extra_lines: int   = 0    # extra window height (in 10px lines) it needs


def _ok(text, aux=(), lines=0):   return Status(text, SUCCESS, tuple(aux), lines)
def _err(text, aux=(), lines=0):  return Status(text, ERROR,   tuple(aux), lines)
def _warn(text, aux=(), lines=0): return Status(text, WARNING, tuple(aux), lines)
def _info(text):                  return Status(text, INFO)


@dataclass(frozen=True)
class Resolved:
    """A status code turned into everything a screen / logger needs."""
    tool:        str
    key:         str
    value:       str     # the "<value>|" part ("" if none)
    message:     str     # final, formatted text
    level:       str
    aux:         tuple
    extra_lines: int
    known:       bool = True

    @property
    def color(self) -> str:        # for UIFactory.label(color=...)
        return _COLORS[self.level][0]

    @property
    def hex(self) -> str:          # for setStyleSheet(f"color: ...")
        return _COLORS[self.level][1]

    @property
    def is_error(self) -> bool:
        return self.level == ERROR

    @property
    def ok(self) -> bool:          # used for log success= flags
        return self.level in (SUCCESS, INFO)

    @property
    def is_final(self) -> bool:    # run finished (as opposed to "in progress")
        return self.level != INFO


# ---------------------------------------------------------------------------
# PARSER / RESOLVER
# ---------------------------------------------------------------------------

def parse_status_code(code: str) -> tuple[str, str]:
    """
    Split a status code into (value, status_key).

    "file_success"                    -> ("", "file_success")
    "Report.xlsx|sensitivity_error"   -> ("Report.xlsx", "sensitivity_error")
    """
    if "|" in code:
        value, key = code.split("|", maxsplit=1)
    else:
        value, key = "", code
    return value, key


class _Fmt(dict):
    """format_map helper: unknown {names} stay visible instead of raising."""
    def __missing__(self, name):
        return "{" + name + "}"


def _format(text: str, value: str, ctx: dict) -> str:
    fields = _Fmt(file_name=value, detail=value, **ctx)
    return text.format_map(fields)


def resolve(tool: str, code: str, *, value: str | None = None, **ctx) -> Resolved:
    """
    Resolve an emitted status code for `tool`.

    `code` is either a bare key or "<value>|<key>".  Pass `value=` explicitly
    when the value may itself contain a "|" (e.g. exception text) -- `code`
    is then treated as a bare key and is not parsed.

    Unknown keys never crash the UI: they are shown as-is, as errors, and a
    warning is logged so the missing definition is easy to find.
    """
    if value is None:
        value, key = parse_status_code(code)
    else:
        key = code
    status = STATUSES[tool].get(key)
    known = status is not None
    if not known:
        _log.warning("Unknown status key %r for tool %r", key, tool)
        status = Status(key, ERROR)

    return Resolved(
        tool=tool, key=key, value=value,
        message=_format(status.text, value, ctx),
        level=status.level, aux=status.aux,
        extra_lines=status.extra_lines, known=known,
    )


def aux_codes(tool: str, button_key: str) -> list[str]:
    """Status keys that should reveal `button_key` (feeds _register_aux_button)."""
    return [k for k, s in STATUSES[tool].items() if button_key in s.aux]


# ---------------------------------------------------------------------------
# SHARED BASES
# ---------------------------------------------------------------------------

# Used by every file-processing tool.
_COMMON = {
    "missing_header_error": _err("{file_name} — Missing Row 1 Header."),
    "missing_total_error":  _err("{file_name} — Missing Total row in the Employee ID column."),
    "not_found_error":      _err("{file_name} — file not found in the upload."),
    "sensitivity_error":    _err("File sensitivity or password protection issue detected in {file_name}. If the issue\n"
                                 "persists, please create a new file with the same content and try again."),
    "processing_error":     _err("An unknown error occurred. Please contact the Automation Team."),
    "premium_download_error": _err("Payroll Headers and Premium.xlsx download error. "
                                   "Please check the SharePoint location."),
}

_INPUT = {
    "error_value": _err("Invalid input value. Please check your entry and try again."),
}

# Tools that take one or more files: wording differs only by plurality / limit.
_FILES   = {"file_success": _ok("Files added successfully."),
            "no_file_error": _err("No files selected — aborting upload.")}
_ONE_FILE = {"file_success": _ok("File added successfully."),
             "no_file_error": _err("No file selected — aborting upload.")}


def _exceed(limit: int) -> dict:
    noun = "files" if limit != 1 else "file"
    return {"file_exceed_error": _err(
        f"Number of {noun} exceeds the expected limit of {limit}. Please verify your upload.")}


def _count(n: int) -> dict:
    return {"file_count_error": _err(
        f"Number file error. Expected count is {n}. Please verify your upload.")}


# Payroll + Billing: upload to SharePoint, then run an Unmand automation.
def _upload_flow(unmand_btn: str) -> dict:
    return {
        "file_success":
            _ok("Files uploaded successfully.", aux=(unmand_btn,), lines=2),
        "unmand_init_success":
            _ok("Unmand initiated successfully. {detail}", aux=("check_unmand_btn",), lines=2),
        "unmand_status_success":
            _ok("Unmand automation completed successfully. "
                "Please verify the generated output.", aux=("open_output_btn",), lines=2),
        # Not a failure: Unmand just hasn't finished yet.
        "unmand_status_pending_error":
            _warn("Unmand is still processing. Please check again shortly.",
                  aux=("check_unmand_btn",), lines=2),

        "no_file_error":
            _err("No files selected — aborting upload."),
        "file_exceed_error":
            _err("Number of files exceeds the expected limit. Please verify your upload."),
        "sensitivity_error":
            _err("{file_name} sensitivity or password protection issue detected."),
        "upload_sp_error":
            _err("Error uploading files to SharePoint. Please contact the Automation Team."),
        "unmand_init_error":
            _err("Failed to start Unmand. Please contact the Automation Team."),
        "unmand_status_error":
            _err("Unmand encountered an error. Please check your inbox for details."),
    }


# ---------------------------------------------------------------------------
# REGISTRY
# ---------------------------------------------------------------------------

STATUSES: dict[str, dict[str, Status]] = {

    # ── Payroll automation (upload + Unmand) ─────────────────────────
    # Emitted by: features/payroll/payroll.py, payroll_orchestrator
    "payroll": {
        **_COMMON, **_upload_flow("payroll_unmand"),

        # Payroll-specific wording
        "missing_total_error":
            _err("Current Payroll has a missing Total row in the Employee ID column."),
        "headers_sensitivity_error":
            _err("Payroll Headers and Premium.xlsx sensitivity or password protection issue detected."),

        "date_format_error":     _err("Date format error detected in {file_name}."),
        "category_column_error": _err("Column 'Charge Type/Category' in Deduction is missing"),

        # ID / version validation
        "id_error":              _err("ID number not found in previous records."),
        "version_duplicate_error": _err("This version number already exists."),
        "id_missing_error":      _err("Version number provided but ID number is missing."),
        "version_missing_error": _err("ID number provided but version number is missing."),
        "version_input_error":   _err("Invalid version format. Please use v1, v2, etc."),

        # Reference files
        "new_headers_error":
            _err("New headers detected. Please update Payroll Headers "
                 "in Settings before proceeding.", aux=("open_new_btn",), lines=2),
    },

    # ── Payroll settings (de minimis) ────────────────────────────────
    # Emitted by: payroll_orchestrator._save_deminimis
    "payroll_settings": {
        **_INPUT,
        "deminimis_save_success": _ok("Deminimis values saved successfully."),
        "deminimis_save_error":   _err("Failed to save deminimis. Please contact the Automation Team."),
    },

    # ── Payroll checker ──────────────────────────────────────────────
    # Emitted by: features/payroll/checker.py
    "payroll_checker": {
        **_COMMON, **_FILES, **_exceed(2),
        "validated_success": _ok("Checker validation completed successfully.",
                                 aux=("open_output_btn",), lines=2),
        "manual_error":      _err("Manual Checker file not found."),
        "unmand_error":      _err("Unmand Checker file not found."),
    },

    # ── DarwinBox -> Sprout ──────────────────────────────────────────
    # Emitted by: features/payroll/dbx_to_sprout.py
    "dbx_to_sprout": {
        **_COMMON, **_ONE_FILE, **_exceed(1),
        "converted_success": _ok("DarwinBox Payroll converted completed successfully.",
                                 aux=("open_output_btn",), lines=2),
    },

    # ── Attendance summary ───────────────────────────────────────────
    # Emitted by: features/payroll/attendance_summary.py
    "attendance_summary": {
        **_COMMON, **_ONE_FILE, **_exceed(1),
        "summarized_success":
            _ok("DarwinBox attendance report summarized successfully.",
                aux=("open_output_btn",), lines=2),
        "missing_columns_error": _err("Missing {detail} column."),

        "date_same_error":   _err("Start Date and Cut-off Date cannot be the same."),
        "date_range_error":  _err("The Cut-off Date cannot be earlier than the Start Date."),
        # Was a duplicate "date_range_error" key (silently overwrote the line
        # above); attendance_summary.py emits this code for bad date input.
        "date_format_error": _err("Date format error. Please contact support."),
    },

    # ── Payroll Premiums ───────────────────────────────────────────
    # Emitted by: features/payroll/payroll_premiums.py
    "payroll_premiums": {
        **_COMMON, **_ONE_FILE, **_exceed(1),
        "premiums_success":
            _ok("Attendance Premiums generated successfully .",
                aux=("open_output_btn",), lines=2),

        # File identity (by file name)
        "ot_error":         _err("Overtime file is missing. The file name must contain \"OT\" or \"Overtime\"."),
        "attendance_error": _err("Attendance Summary file is missing. The file name must contain \"Attendance Summary\"."),

        "missing_columns_error": _err("{detail}"),
        "date_format_error":     _err("Date format error detected in {file_name}."),
        "holiday_list_error": _err("Holiday list could not be read from SharePoint."),
    },

    # ── Billing automation (upload + Unmand) ─────────────────────────
    # Emitted by: features/billing/billing.py, billing_orchestrator
    "billing": {
        **_COMMON, **_upload_flow("billing_unmand"),
    },

    # ── Billing checker (variance) ───────────────────────────────────
    # Emitted by: features/billing/checker.py
    "billing_checker": {
        **_COMMON, **_FILES, **_exceed(2),
        "validated_success": _ok("Checker validation completed successfully.",
                                 aux=("open_output_btn",), lines=2),
        "manual_error":      _err("Manual Checker file not found."),
        "unmand_error":      _err("Unmand Checker file not found."),
        "currency_error":       _err("{file_name} — Non-AUD currency found."),
        "missing_column_error": _err("{detail}"),
    },

    # ── Billing: attendance adjustment ───────────────────────────────
    # Emitted by: features/billing/attendance_adjustment.py
    "att_adj": {
        **_COMMON, **_ONE_FILE, **_count(3),
        "generated_success": _ok("Attendance Adjustment generated successfully.",
                                 aux=("open_output_btn",)),

        "emp_id_not_found_error": _err("Employee ID(s) not found in Employee List: {detail}"),
        "currency_format_error":  _err("Exchange rate has an invalid format."),
        "empty_currency_error":   _err("Exchange rate is missing."),
        "new_headers_error":      _err("Please add them to the Payroll Headers. New headers: {detail}"),

        "headers_sensitivity_error":
            _err("Please check the sensitivity of the Payroll Premium Headers.xlsx Source: {file_name} "),
        "premium_download_error":
            _err("Payroll Premium Headers.xlsx (Payroll Headers and Rates) cannot be downloaded. \n"
                 "Please Contact the Automation Team."),
        "premium_header_error":
            _err("Header [Payroll Headers and Rates] in Row 13 cannot be find in\n"
                 "Payroll Premium Headers.xlsx (Payroll Headers and Rates)"),
    },

    # ── Billing: Insightful tracker ──────────────────────────────────
    # Emitted by: features/billing/insightful.py
    "insightful": {
        **_COMMON, **_ONE_FILE, **_count(2),
        "generated_success": _ok("Insightful tracker updated and generated successfully.",
                                 aux=("open_output_btn",)),

        # Tracker updated but the run stops for review -> warning, not success.
        "new_user_found":
            _warn("New user(s) found and added to the tracker: {detail}.\n"
                  "Please complete their details — especially the Employee ID — "
                  "before continuing."),
        # Emitted as "<n>|tracker_updated" when Employee-List changes were
        # written to the tracker and the run stops for review.  (Previously
        # undefined, so the raw key was shown on screen.)
        "tracker_updated":
            _warn("{detail} tracker cell(s) were updated from the Employee List.\n"
                  "Please review them before continuing."),
        "new_user_error":
            _err("An error occurred while checking the tracker for new users. "
                 "Please contact the Automation Team."),

        "emp_id_not_found_error": _err("Employee ID(s) not found in Employee List: {detail}"),

        "premium_download_error":
            _err("Insightful.xlsx (Tracker) cannot be downloaded. \n"
                 "Please Contact the Automation Team."),
        "tracker_upload_error":
            _err("The updated Insightful tracker could not be uploaded back "
                 "to SharePoint. Please Contact the Automation Team."),
        "tracker_locked_error":
            _err("The Insightful tracker is currently locked (open in Excel or a "
                 "co-authoring session elsewhere). Please close it on SharePoint "
                 "and try again."),
        "tracker_client_error":
            _err("The Insightful tracker request was rejected by SharePoint "
                 "(HTTP {detail}). Please contact the Automation Team."),
        "tracker_incomplete_error":
            _err("The following tracker column(s) have blank value(s) that must "
                 "be completed before the output can be generated: {detail}."),
    },

    # ── Suite settings (users, log sharing, app version) ─────────────
    # Emitted by: features/settings_feature.py, orchestrator.py
    "app_settings": {
        **_INPUT,
        "add_user_success":       _ok("User added successfully."),
        "upload_success":         _ok("{file_name} shared successfully."),
        "upload_partial_success": _warn("Logs partially shared. Some logs could not be uploaded."),
        "uploading":              _info("Sharing logs..."),

        "add_user_error":         _err("Failed to add user. Please contact the Automation Team."),
        "add_user_email_error":   _warn("User added, but the welcome email could not be sent. "
                                        "Please contact the Automation Team."),

        "empty_error":            _err("Email address field is empty. Please enter an email."),
        "error_email":            _err("Invalid email domain. "
                                       "Please use an @intogreatsolutions.com address."),
        "duplicate_user":         _err("This user already has access. "
                                       "Please check the user list above."),
        "upload_error":           _err("Unable to share logs. Please try again or contact the Automation Team."),
        "no_logs_found":          _warn("No logs were found for the selected date range."),
        "no_token_error":         _err("Authentication token is missing. Please try again."),
        "invalid_range_error":    _err("Invalid date range. Please select a valid start and cutoff date."),
        "missing_dates_error":    _err("Please select both a start date and a cutoff date."),
        "empty_selection_error":  _err("Please select app version to install."),
    },

    # ── Toolbox: Excel locker ────────────────────────────────────────
    # Emitted by: features/tools_feature.py -> Body.show_excel_locker_result
    # {file_name}/{detail} carry a file name, a metadata line number, or an
    # exception text depending on the code.
    "excel_locker": {
        "locked_success":          _ok("{file_name} locked successfully."),

        "no_excel_error":          _err("No Excel files detected in your selection."),
        "multiple_txt_error":      _err("Multiple TXT files selected — choose only one."),
        "invalid_format_error":    _err("Invalid format on line {detail} of the metadata file."),
        "empty_entry_error":       _err("Empty filename or password on line {detail} of the metadata file."),
        "invalid_filename_error":  _err("{file_name} — invalid filename in the metadata file (must end in .xlsx)."),
        "duplicate_entry_error":   _err("{file_name} — duplicate entry in the metadata file."),
        "metadata_read_error":     _err("Unable to read the metadata file: {detail}"),

        "not_listed_error":        _err("{file_name} — not listed in the metadata file."),
        "not_uploaded_error":      _err("{file_name} — listed in the metadata file but not uploaded."),

        "already_protected_error": _err("{file_name} is already password-protected or check the sensitivity."),
        "no_password_error":       _err("{file_name} — no password provided."),
        "save_cancelled_error":    _err("{file_name} — save location was not chosen."),
        "failed_to_lock_error":    _err("{file_name} — failed to lock - please check sensitivity."),
    },
}


# ---------------------------------------------------------------------------
# SELF-CHECK  (python -m ui.statuses  /  call validate() from a test)
# ---------------------------------------------------------------------------

_KNOWN_FIELDS = {"file_name", "detail"}
_LEVELS = set(_COLORS)


def validate() -> list[str]:
    """Return a list of problems (empty list == registry is healthy)."""
    problems = []
    for tool, table in STATUSES.items():
        for key, st in table.items():
            where = f"{tool}.{key}"
            if st.level not in _LEVELS:
                problems.append(f"{where}: bad level {st.level!r}")
            for _, field, _, _ in string.Formatter().parse(st.text):
                if field and field not in _KNOWN_FIELDS:
                    problems.append(f"{where}: unknown placeholder {{{field}}}")
            if key.endswith("_success") and st.level == ERROR:
                problems.append(f"{where}: *_success key with level error")
            if key.endswith("_error") and st.level == SUCCESS:
                problems.append(f"{where}: *_error key with level success")
            if re.search(r"  +\.|of \.", st.text):
                problems.append(f"{where}: suspicious empty slot in text")
    return problems


if __name__ == "__main__":
    issues = validate()
    total = sum(len(t) for t in STATUSES.values())
    print(f"{len(STATUSES)} tools, {total} statuses, {len(issues)} problem(s)")
    for i in issues:
        print("  -", i)
    raise SystemExit(1 if issues else 0)
