"""
attendance_adjustment.py
-------------------------
AttendanceAdjustmentFeature — file collection and validation for the
Billing "Attendance Adjustment" tool.

Mirrors features/payroll/payroll.py (PayrollFeature) structurally — same
file-picker -> read/decrypt -> validate -> upload hand-off pipeline —
adapted for this tool:

    - Exactly 3 FIXED files are required (not config-driven, per the
      list shown on the tool's screen):
          "Employee List"
          "Payroll Register 1st Half"
          "Payroll Register 2nd Half"

    - Pre-checks come straight from the Notes panel on that screen
      (ui/components/body_apps/billing_app.py -> show_attendance_adjustment_tool):
          - "Headers in Row 1; use Sheet 1"          -> _check_headers()
          - "File type must be .xlsx"                -> _read_files()
          - "The file should not be password-        -> _read_files() decrypt
             protected. If required, use                fallback (same
             INTOGREAT[YYYY]."                           INTOGREAT{YYYY}
                                                          convention as
                                                          Payroll/Billing)
      "Sensitivity should be set to Public" is a SharePoint-side setting
      on the source export and can't be verified from a local file, so
      it isn't enforced here. No Total-row check — unlike Payroll, this
      flow doesn't require one.

Responsibilities
----------------
1. Open a native file-picker dialog for the user to select the 3 fixed
   Excel files (deferred via QTimer so the UI settles first).
2. Read each selected file, decrypting it with msoffcrypto when needed.
3. Run the pre-checks above (required files / Row 1 headers).
4. Emit the result back to the Orchestrator via callbacks:
       on_result(codes)        — list of status-code strings for the UI
       uploaded_files(dfs)     — dict of validated DataFrames, ready to
                                  upload to SharePoint + hand off to Unmand

This class performs NO direct UI calls other than the file-picker dialog,
and does NOT touch SharePoint or Unmand itself — that's the Orchestrator's
job (see orchestrators/billing_orchestrator.py), the same separation of
concerns PayrollFeature/BillingFeature use.
"""

import io
from datetime import datetime, timedelta
from difflib import get_close_matches
from pathlib import Path
import msoffcrypto
import pandas as pd

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Side, Border, Alignment
from openpyxl.utils import get_column_letter

from PyQt6.QtCore import QDate, QTimer
from PyQt6.QtWidgets import QFileDialog, QApplication

from services.sharepoint_service import SharePointService
from utils.app_config_user import get
from utils.file_utils import create_path, billing_app_path

# The 3 fixed files this tool always expects — shown as-is on the
# Attendance Adjustment screen, so they're hardcoded here rather than
# pulled from the remote config the way Payroll/Billing's required_files are.
_REQUIRED_FILES = [
    "Employee List",
    "Payroll Register 15",
    "Payroll Register 30",
]

# Fallback Employee ID column-name variants, used only if the caller
# doesn't supply its own list from config.
_DEFAULT_ID_NAMES = ["Employee ID", "EmployeeID", "Emp ID", "Emp. ID", "ID"]

# Password format used for encrypted files (same convention as Payroll/Billing)
_PASSWORD_PREFIX = get("PASSWORD_PREFIX", "")

RATES = {
  "Ord-OT": 1.25,
  "Ord-ND": 0.1,
  "Ord-ND-OT": 1.375,
  "RD": 1.3,
  "RD-OT": 1.69,
  "RD-ND": 1.43,
  "RD-ND-OT": 1.859,
  "SH": 0.3,
  "SH-OT": 1.69,
  "SH-ND": 0.43,
  "SH-ND-OT": 1.859,
  "LH": 1,
  "LH-OT": 2.6,
  "LH-ND": 1.2,
  "LH-ND-OT": 2.86,
  "SH-RD": 1.5,
  "SH-RD-OT": 1.95,
  "SH-RD-ND": 1.65,
  "SH-RD-ND-OT": 2.145,
  "LH-RD": 2.6,
  "LH-RD-OT": 3.38,
  "LH-RD-ND": 2.86,
  "LH-RD-ND-OT": 3.718,
  "Absence Adjustment": 1,
  "Late/Undertime Adjustment": 1,
  "Ord-ND Adj": 0.1,
  "Total Absent Deduction": 1,
  "Deminimis Deduction": 1,
  "Total Late Deduction": 1,
  "Deminimis Adjustment": 1,
  "Complexity Pay": 1,
  "LH-RD-ND Adj": 2.86,
  "Ord-ND OT Adj": 1.375,
  "Ord-OT Adj": 1.25,
  "RD Adj": 1.3,
  "Absence Adjustment (LESS)": 1,
  "Deminimis Adjustment (LESS)": 1,
  "Late/Undertime Adjustment (LESS)": 1,
  "Ord-OT Adj (LESS)": 1.25,
  "Ord-ND OT Adj (LESS)": 1.375,
  "Ord-ND Adj (LESS)": 0.1,
  "PTO Conversion": 1,
  "LH Adj": 1,
  "LH-ND Adj": 1.2,
  "LH-RD Adj": 2.6,
  "LH ND-OT Adj": 2.86,
  "LH-OT Adj": 2.6,
  "RD Adj (LESS)": 1.3,
  "RD ND Adj": 1.43,
  "RD ND Adj (LESS)": 1.43,
  "RD OT Adj (LESS)": 1.69,
  "RD ND OT Adj": 1.859,
  "Service Incentive Leave": 1,
  "SH Adj": 0.3,
  "SH ND Adj": 0.43,
  "SH ND Adj (LESS)": 0.43,
  "SH ND-OT Adj": 0.43,
  "SH RD Adj": 1.5,
  "SH RD Adj (LESS)": 1.5,
  "SH RD ND Adj": 1.65,
  "SH RD ND Adj (LESS)": 1.65,
  "RD OT Adj": 1.69,
  "SH Adj (LESS)": 0.3,
  "LH Adj (LESS)": 1,
  "LH-RD Adj (LESS)": 2.6,
  "LH-OT Adj (LESS)": 2.6,
  "SH OT Adj": 1.69
}

class AttendanceAdjustmentFeature:
    """
    Parameters
    ----------
    log         : Logger
        Shared Logger instance from the Orchestrator.
    main_window : MainWindow
        Used only to obtain a screen-centre reference for the dialog.
        The dialog's Qt parent is set to None so it is independent of
        the main window and cannot cause it to flash.
    """

    def __init__(self, log, main_window):
        self.log         = log
        self.main_window = main_window

        # Callbacks wired by the Orchestrator after construction
        self.on_result      = None   # fn(codes: list[str])
        self.uploaded_files = None   # fn(files: dict[str, pd.DataFrame])
        self.on_progress    = None   # fn(percent: int, message: str)

    # ===================================================================

    def prepare_attendance_adjustment_files(self, expected_id_names: list = None, required_files: list = None, exchange_rate: str = None):
        """
        Start the Attendance Adjustment file preparation flow.

        Defers opening the file dialog to the next Qt event loop tick so
        the UI can fully settle after the button click before the dialog
        appears.

        Parameters
        ----------
        expected_id_names : list[str], optional
            Employee ID column header variants from config, used for
            fuzzy matching. Falls back to _DEFAULT_ID_NAMES if not
            supplied (e.g. config has no attendance_adjustment section yet).
        """
        self.log.section("ATTENDANCE ADJUSTMENT FILE PREPARATION")
        self.log.info("AttendanceAdjustmentFeature: Deferring file dialog to next event loop tick")
        QTimer.singleShot(
            0,
            lambda: self._open_and_process(expected_id_names or _DEFAULT_ID_NAMES, required_files or _REQUIRED_FILES, exchange_rate),
        )

    # ===================================================================
    # STEP 1 — OPEN FILE DIALOG + PROCESS
    # ===================================================================

    def _open_and_process(self, expected_id_names: list, required_files: list, exchange_rate: str):
        """
        Open the native file-picker and, if files are selected, run the
        validation pipeline.

        Called by QTimer.singleShot() so it executes after the button
        click has been fully processed by the event loop — this prevents
        the main window from flashing when the dialog appears.
        """
        self.log.info("AttendanceAdjustmentFeature: Opening file dialog")
        self._emit_progress(2, "Selecting files…")

        # Parent=None keeps the dialog independent of the main window.
        file_paths, _ = QFileDialog.getOpenFileNames(
            self.main_window,
            "Select Attendance Adjustment Excel Files",
            "",
            "Excel Files (*.xlsx)",
        )

        self.log.info(
            f"AttendanceAdjustmentFeature: File dialog closed | "
            f"selected={len(file_paths)} expected_max={len(required_files)}"
        )

        # ── Guard: nothing selected ───────────────────────────────────
        if not file_paths:
            self.log.info("AttendanceAdjustmentFeature: No files selected — aborting")
            self._emit_result("no_file_error")
            return

        # ── Guard: Incorrect number files ─────────────────────────────────────
        if len(file_paths) != len(required_files):
            self.log.warning(
                f"AttendanceAdjustmentFeature: Incorrect number files | "
                f"got={len(file_paths)} max={len(required_files)}"
            )
            self._emit_result("file_exceed_error")
            return

        # ── no currency exchange rate  ─────────────────────────────────────
        if not exchange_rate:
            self.log.warning(
                f"AttendanceAdjustmentFeature: No currency conversion provided"
            )
            self._emit_result("empty_currency_error")
            return
        else:
            try: 
                float(exchange_rate)
            except:
                self.log.warning(
                    f"AttendanceAdjustmentFeature: Currency provided not float"
                )
                self._emit_result("currency_format_error")
                return

        self.log.info("AttendanceAdjustmentFeature: File count validated — starting processing")
        self._process_files(file_paths, expected_id_names, required_files)

    # ===================================================================
    # STEP 2 — VALIDATION PIPELINE
    # ===================================================================

    def _process_files(self, file_paths: list, expected_id_names: list, required_files: list):
        """
        Run the pre-check pipeline described in the tool's Notes panel.

        Checks performed (in order)
        ----------------------------
        1. Read / decrypt each file (.xlsx-only is enforced here too).
        2. Check all 3 fixed files are present.
        3. Check Row 1 headers via the Employee ID column.

        On success, delegates to uploaded_files() so the Orchestrator can
        upload to SharePoint and hand off to Unmand.
        On any failure, emits the error codes via on_result().
        """
        self._emit_progress(10, "Reading files…")
        QApplication.processEvents()
        dataframes = self._read_files(file_paths)

        self._emit_progress(25, "Checking required files…")
        self._check_required_files(dataframes, required_files)

        self._emit_progress(30, "Checking Row 1 headers…")
        self._check_headers(dataframes, expected_id_names)

        self._emit_progress(40, "Validating Employee ID with Employee List…")
        emp_id_error = self._check_employee_ids(dataframes)

        if emp_id_error:
            self._emit_result(emp_id_error)
            return

        # ── Final error sweep ─────────────────────────────────────────
        self._emit_progress(45, "Final error sweep…")
        self.log.info("AttendanceAdjustmentFeature: Final error check across all files")
        error_codes = [
            f"{file}|{status}"
            for file, status in dataframes.items()
            if not isinstance(status, pd.DataFrame)
        ]

        if error_codes:
            self.log.warning(f"AttendanceAdjustmentFeature: Validation failed | errors={error_codes}")
            self._emit_result(error_codes)
        else:
            self.log.info("AttendanceAdjustmentFeature: All files validated — handing off to Orchestrator")
            self._emit_files(dataframes)

    # ===================================================================
    # VALIDATION HELPERS
    # ===================================================================

    def _read_files(self, file_paths: list) -> dict:
        """
        Read each selected file into a DataFrame, decrypting if needed.

        Also enforces the "File type must be .xlsx" note — non-.xlsx
        files are marked "sensitivity_error" without attempting a read,
        the same error code the read/decrypt failure path uses, so it
        still shows up cleanly in the final error sweep.

        Encrypted files are opened with msoffcrypto using the standard
        INTOGREAT{YYYY} password. Files that cannot be read at all are
        also stored as "sensitivity_error".

        Returns
        -------
        dict[str, pd.DataFrame | str]
            Keys are file names (stem only, no directory).
            Values are DataFrames on success, or an error-code string.
        """
        self.log.info(f"AttendanceAdjustmentFeature: Reading {len(file_paths)} file(s)")
        dataframes = {}
        year      = datetime.now().year
        progress  = 10
        increment = progress / len(file_paths)

        for file_path in file_paths:
            filename = Path(file_path).name
            progress += increment

            # ── Note: "File type must be .xlsx" ───────────────────────
            if Path(file_path).suffix.lower() != ".xlsx":
                self.log.warning(f"AttendanceAdjustmentFeature: Invalid file type | file={filename}")
                dataframes[filename] = "sensitivity_error"
                self._emit_progress(int(progress), f"Invalid file type | {filename}")
                continue

            # ── Attempt unencrypted read ──────────────────────────────
            try:
                df = pd.read_excel(file_path, dtype=str)
                dataframes[filename] = df

                self._emit_progress(int(progress), f"Read OK | {filename}")
                QApplication.processEvents()
                continue

            except Exception:
                pass   # Fall through to decryption attempt

            # ── Attempt decrypted read ────────────────────────────────
            try:
                password  = f"{_PASSWORD_PREFIX}{year}"
                decrypted = io.BytesIO()

                with open(file_path, "rb") as f:
                    office_file = msoffcrypto.OfficeFile(f)
                    office_file.load_key(password=password)
                    office_file.decrypt(decrypted)

                decrypted.seek(0)
                df = pd.read_excel(decrypted, dtype=str)
                dataframes[filename] = df

                self._emit_progress(int(progress), f"Decrypted and read OK | {filename}")
                QApplication.processEvents()

            except Exception as e:
                self.log.warning(f"AttendanceAdjustmentFeature: Failed to read or decrypt | file={filename} error={e}")
                dataframes[filename] = "sensitivity_error"

        return dataframes

    def _check_required_files(self, dataframes: dict, required_files: list):
        """
        Verify all required files are present.

        Employee List uses fuzzy matching.
        Payroll Register 15 and Payroll Register 30 must explicitly contain
        the corresponding 15 or 30 identifier in the filename.
        """
        self.log.info(
            "AttendanceAdjustmentFeature: Checking all required files are present"
        )

        updated_dataframes = {}
        uploaded_files = list(dataframes.keys())

        for expected in required_files:

            # Strict matching for payroll registers
            if expected == "Payroll Register 15":
                match = next(
                    (
                        filename for filename in uploaded_files
                        if "payroll register" in filename.lower()
                        and "15" in filename
                    ),
                    None
                )

            elif expected == "Payroll Register 30":
                match = next(
                    (
                        filename for filename in uploaded_files
                        if "payroll register" in filename.lower()
                        and any(day in filename for day in ("28", "29", "30", "31"))
                    ),
                    None
                )

            # Fuzzy matching for other required files
            else:
                matches = get_close_matches(
                    expected,
                    uploaded_files,
                    n=1,
                    cutoff=0.3
                )
                match = matches[0] if matches else None

            if not match:
                self.log.warning(
                    f"AttendanceAdjustmentFeature: Required file missing | "
                    f"expected='{expected}'"
                )
                updated_dataframes[expected] = "not_found_error"
            else:
                updated_dataframes[expected] = dataframes[match]

        dataframes.clear()
        dataframes.update(updated_dataframes)

    def _check_headers(self, dataframes: dict, expected_id_names: list):
        """
        Verify Row 4 is a real header row by fuzzy-matching an Employee
        ID column on each file, normalising it to "Employee ID".

        This is the note's "Headers in Row 1; use Sheet 1" requirement —
        if Row 4 isn't a real header row, no ID column will be found.
        Files with no match are marked "missing_header_error".
        """
        self.log.info("AttendanceAdjustmentFeature: Checking Row 1 headers / Employee ID column")

        for file_, content in dataframes.items():
            if not isinstance(content, pd.DataFrame):
                continue

            found = False
            for id_name in expected_id_names:
                match = get_close_matches(
                    str(id_name),
                    list(map(str, content.columns)),
                    n=1,
                    cutoff=0.6,
                )
                if match:
                    content.rename(columns={match[0]: "Employee ID"}, inplace=True)
                    self.log.info(f"AttendanceAdjustmentFeature: Renamed column | file={file_} from='{match[0]}' to='Employee ID'")
                    found = True
                    break

            if not found:
                self.log.warning(f"AttendanceAdjustmentFeature: No Employee ID header found | file={file_}")
                dataframes[file_] = "missing_header_error"

    def _check_employee_ids(self, dataframes: dict) -> str | None:
        """
        Verify every Employee ID referenced in Payroll Register 15 and
        Payroll Register 30 exists in the Employee List.
        """
        self.log.info("AttendanceAdjustmentFeature: Checking Employee IDs against Employee List")

        emp_list  = dataframes.get("Employee List")
        payroll15 = dataframes.get("Payroll Register 15")
        payroll30 = dataframes.get("Payroll Register 30")

        if not isinstance(emp_list, pd.DataFrame) or "Employee ID" not in emp_list.columns:
            self.log.warning("AttendanceAdjustmentFeature: Employee List missing/invalid — skipping ID check")
            return None
        
        emp_ids_in_list = set(emp_list["Employee ID"].dropna().astype(str))
        missing_ids = set()

        for df in (payroll15, payroll30):
            if not isinstance(df, pd.DataFrame) or "Employee ID" not in df.columns:
                continue

            ids = set(df["Employee ID"].dropna().astype(str))
            ids = {i for i in ids if i.startswith("IE0")}
            missing_ids |= (ids - emp_ids_in_list)

        if not missing_ids:
            return None
        
        missing_str = ", ".join(sorted(missing_ids))
        self.log.warning(
            f"AttendanceAdjustmentFeature: Employee ID(s) not found in Employee List | ids={missing_str}"
        )

        return f"{missing_str}|emp_id_not_found_error"
    # ===================================================================
    # GENERATION (called by _AttendanceAdjustmentWorker)
    # Ported directly from the Unmand Python-block script.
    # ===================================================================

    def generate(self, files: dict, token: str, rates_loc: str, source: str, date: tuple, aud_php: float):
        """
        Compute the Attendance Adjustment summary and write it to a
        local Excel workbook. Same logic as the original Unmand script,
        translated to read from already-validated in-memory DataFrames
        instead of SharePoint-downloaded blobs.

        Parameters
        ----------
        files   : dict[str, pd.DataFrame]
            Keyed by the canonical _REQUIRED_FILES labels:
            "Attendance Adjustment 1", "Attendance Adjustment 2",
            "Client Billing", "Payroll".
        rates   : dict[str, float]
            Category -> premium multiplier. Passed in by the caller at
            generation time (e.g. from billing_config), not stored here.
        aud_php : float
            AUD -> PHP exchange rate for this run.
        month   : str
            Billing month name (e.g. "August").
        year    : int
            Billing year (e.g. 2026).

        Returns
        -------
        Path
            Local paPayroll Register 30he generated Attendance Summary Excel file.
        """
        self.log.section("PAYROLL FILE PREPARATION")
        self.log.info("AttendanceAdjustmentFeature: Initialising SharePointService")
        self._sharepoint = SharePointService(token)

        self._emit_progress(50, "Fetching rates and client details…")

        rates= self._fetch_rates_gst(rates_loc, source)

        if not rates:
            self.log.warning(f"AttendanceAdjustmentFeature: Error fetching rates utlizing local rates...")
            rates = RATES

        payroll15   = files.get("Payroll Register 15")
        payroll30   = files.get("Payroll Register 30")
        emp_list = files.get("Employee List")

        for label, df in (
            ("Employee List", emp_list),
            ("Payroll Register 15", payroll15),
            ("Payroll Register 30", payroll30),
       
        ):
            if not isinstance(df, pd.DataFrame):
                self.log.warning(f"AttendanceAdjustmentFeature: generate() missing source | {label}")
                return None

        self._emit_progress(60, "Building lookups…")

        emp_list_record = emp_list.to_dict("records")
        client_billing_records = emp_list.to_dict("records")

        emp_list_lookup = {
            row["Employee ID"]: row for row in emp_list_record if row.get("Employee ID")
        }
        client_billing_lookup = {
            row["*ContactName"]: row for row in client_billing_records if row.get("*ContactName")
        }

        self._emit_progress(70, "Resolving billing period…")

        year, month_num, day = date
        month = datetime(year, month_num, day).strftime("%B")

        first_of_month = datetime(year, month_num, 1)

        prev_month_date = first_of_month - timedelta(days=1)
        prev_month = prev_month_date.strftime("%B")

        prev_prev_month = (first_of_month - timedelta(days=32)).strftime("%B")

        self._emit_progress(80, "Computing adjustments…")

        attendance_adjustment_php = []
        rate_keys = list(rates.keys())

        for period_index, att_df in enumerate((payroll15, payroll30)):
            att_records = att_df.to_dict("records")

            for row in att_records:
                emp_id = row.get("Employee ID", "")
                team = row.get("Cost Center", "")

                if not str(emp_id).startswith("IE"):
                    continue
                if not str(emp_id).startswith("IE0"):
                    continue

                sum_row = {
                    "Emp Id": row["Employee ID"],
                    "Name": f"{row['Fullname'].split(',')[1].strip()} {row['Fullname'].split(',')[0].strip()}",
                    "Position": row.get("Position"),
                    "Department": row.get("Department"),
                    "Team": team,
                    "Month": prev_month,
                    "Attendance Date": "",
                    "Category": "",
                    "Unit of Measure": "Hours",
                    "Duration": None,
                    "Hours": None,
                    "Hourly Rate(PHP)": None,
                    "Premium": None,
                    "Amount(PHP)": 0,
                    "Attendance Adjustment(AUD)": 0,
                    "GST": None,
                    "*ContactName": team,
                    "Reference": "",
                    "Billing Name": "Attendance Adjustment",
                    "Description": "Revenue",
                }

                for key, value in row.items():
                    if key not in rate_keys or value in ["", None, 0]:
                        continue

                    employee_details = emp_list_lookup.get(emp_id, {})
                    monthly_gross = employee_details.get("Monthly Gross", 0)
                    cost_center = employee_details.get("Cost Center", "")

                    if cost_center == "Intogreat":
                        gst_percent = 0
                    else:
                        gst_percent = client_billing_lookup.get(cost_center, {}).get("%", 0)
                        gst_percent = float(gst_percent) if gst_percent else 0

                    if period_index == 0:
                        sum_row["Attendance Date"] = f"{prev_prev_month} 21 - {prev_month} 5, {year}"
                    else:
                        sum_row["Attendance Date"] = f"{prev_month} 6 - {prev_month} 20, {year}"

                    sum_row["Category"] = key
                    sum_row["Hourly Rate(PHP)"] = round(float(monthly_gross) / 21.75 / 8, 2)
                    sum_row["Premium"] = rates[key]

                    value_str = str(value).strip()
                    if not value_str or not value_str.replace(".", "", 1).replace("-", "", 1).isdigit():
                        self.log.warning(
                            f"AttendanceAdjustmentFeature: Non-numeric/empty value skipped | "
                            f"emp_id={emp_id} key={key} value={value!r}"
                        )
                        continue
                    
                    if "less" in key.lower() or "deduction" in key.lower():
                        sum_row["Amount(PHP)"] = -round(float(value_str), 7)
                    else:
                        sum_row["Amount(PHP)"] = round(float(value_str), 7)

                    if sum_row["Amount(PHP)"] == 0:
                        continue

                    if sum_row["Hourly Rate(PHP)"] not in [0, "", None]:
                        sum_row["Hours"] = round(
                            sum_row["Amount(PHP)"] / sum_row["Hourly Rate(PHP)"] / sum_row["Premium"], 2
                        )
                        sum_row["Attendance Adjustment(AUD)"] = round(sum_row["Amount(PHP)"] / aud_php, 2)
                        sum_row["GST"] = round(sum_row["Attendance Adjustment(AUD)"] * gst_percent, 2)
                        sum_row["*ContactName"] = employee_details.get("*ContactName", "")
                        sum_row["Reference"] = employee_details.get("Reference", "")
                    else:
                        attendance_adjustment_php.append(sum_row.copy())
                        self.log.warning(
                            f"AttendanceAdjustmentFeature: {emp_id} Monthly Gross not found in Payroll — "
                            f"FOR MANUAL review. Skipping."
                        )
                        continue

                    attendance_adjustment_php.append(sum_row.copy())

        self._emit_progress(90, "Writing output…")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = create_path(billing_app_path() / "Tools" / "Attendance Summary") / f"Attendance_Summary_{month}_{year}_{stamp}.xlsx"

        self._write_workbook(attendance_adjustment_php, out_path, month, year)
        self.log.info(f"AttendanceAdjustmentFeature: Output written | path={out_path} rows={len(attendance_adjustment_php)}")

        self._emit_progress(100, "Done.")
        return out_path

    # ===================================================================
    # STEP 1 — DOWNLOAD HEADERS REFERENCE
    # ===================================================================
    def _fetch_rates_gst(self, rates_loc: str, source: str):

        """
        Fetch the Payroll Headers Excel from SharePoint and return the
        list of expected column headers for the current source.

        Returns
        -------
        list[str] or None
            The header list on success, or None on any failure (result
            already emitted before returning None).
        """
        base_url = get("SP_BASE_URL", "")
        url = f"{base_url}{rates_loc}"

        self.log.info(
            "AttendanceAdjustmentFeature: Downloading headers from SharePoint"
        )

        response = self._sharepoint.get(url)

        if not str(response.status_code).startswith("2"):
            self.log.warning(
                f"AttendanceAdjustmentFeature: Headers download failed | "
                f"HTTP={response.status_code}"
            )
            return None

        sheet_name = (
            "Sprout Payroll Headers"
            if source == "Sprout"
            else "DarwinBox Payroll Headers"
        )

        self.log.info(
            f"AttendanceAdjustmentFeature: Parsing headers sheet | "
            f"sheet={sheet_name}"
        )

        try:
            excel_file = io.BytesIO(response.content)

            df = pd.read_excel(
                excel_file,
                sheet_name=sheet_name,
                header=12,
                engine="openpyxl"
            )

            rates = dict(zip(df["Payroll Headers"], df["Rate"]))

            self.log.info(
                f"AttendanceAdjustmentFeature: Loaded {len(rates)} payroll header(s)"
            )

            return rates

        except Exception as e:
            self.log.warning(
                f"AttendanceAdjustmentFeature: Failed to parse headers sheet — {e}",
                error=e
            )
            return None

    # ===================================================================
    # EXCEL WORKBOOK WRITER
    # ===================================================================

    def _write_workbook(self, rows: list, out_path: Path, month: str, year: int) -> None:
        """Write the Attendance Summary as a single styled sheet."""
        if not rows:
            columns = [
                "Emp Id", "Name", "Position", "Department", "Team", "Month",
                "Attendance Date", "Category", "Unit of Measure", "Duration",
                "Hours", "Hourly Rate(PHP)", "Premium", "Amount(PHP)",
                "Attendance Adjustment(AUD)", "GST", "*ContactName",
                "Reference", "Billing Name", "Description",
            ]
            df = pd.DataFrame(columns=columns)
        else:
            df = pd.DataFrame(rows)

        wb = Workbook()
        ws = wb.active
        ws.title = f"{month} {year}"

        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="203864")
        thin = Side(style="thin", color="B8B8B8")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        left = Alignment(horizontal="left", vertical="center")

        for col_idx, col_name in enumerate(df.columns, start=1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center
            cell.border = border

        for row_idx, row in enumerate(df.itertuples(index=False), start=2):
            for col_idx, value in enumerate(row, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.border = border
                cell.alignment = left

        last_col_letter = get_column_letter(len(df.columns)) if len(df.columns) else "A"
        ws.auto_filter.ref = f"A1:{last_col_letter}1"
        ws.freeze_panes = "A2"

        for col_cells in ws.columns:
            length = max((len(str(c.value)) if c.value is not None else 0) for c in col_cells)
            ws.column_dimensions[get_column_letter(col_cells[0].column)].width = min(max(length + 2, 8), 40)

        wb.save(out_path)

    # ===================================================================
    # EMIT HELPERS
    # ===================================================================

    def _emit_result(self, codes):
        if not self.on_result:
            self.log.warning("AttendanceAdjustmentFeature: on_result callback not wired — result dropped")
            return
        normalized = list(codes) if isinstance(codes, (list, tuple)) else [codes]
        self.log.info(f"AttendanceAdjustmentFeature: Emitting result codes | codes={normalized}")
        self.on_result(normalized)

    def _emit_files(self, files: dict):
        if not self.uploaded_files:
            self.log.warning("AttendanceAdjustmentFeature: uploaded_files callback not wired — files dropped")
            return
        self.log.info(f"AttendanceAdjustmentFeature: Handing {len(files)} file(s) to Orchestrator")
        self.uploaded_files(files)

    def _emit_progress(self, percent: int, message: str):
        if not self.on_progress:
            return
        self.log.info(f"AttendanceAdjustmentFeature: Progress | {percent}% — {message}")
        self.on_progress(percent, message)
