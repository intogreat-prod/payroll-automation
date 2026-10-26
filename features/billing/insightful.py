"""
insightful.py
-------------------------
InsightfulFeature — file collection, validation, and tracker
generation for the Billing "Insightful" tool.

    - Exactly 2 FIXED files are required (not config-driven, per the
      list shown on the tool's screen) see the billing config to change:
          "Employee List"
          "IT File Insightful"

    - Pre-checks come straight from the Notes panel on that screen
      (ui/components/body_apps/billing_app.py -> show_insightful_tool):
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
1. Open a native file-picker dialog for the user to select the 2 fixed
   Excel files (deferred via QTimer so the UI settles first).
2. Read each selected file, decrypting it with msoffcrypto when needed.
3. Run the pre-checks above (required files / Row 1 headers).
4. Emit the result back to the Orchestrator via callbacks:
       on_result(codes)        — list of status-code strings for the UI
       uploaded_files(dfs)     — dict of validated DataFrames, handed to
                                  the Orchestrator to kick off generate()

5. generate() is the "running tracker" step: it downloads the current
   Insightful tracker from SharePoint, compares its Identifiers against
   the freshly uploaded IT File, and either:
       - finds new user(s): appends a blank row per new Identifier to
         the tracker, uploads that tracker back to SharePoint
         immediately, and STOPS — no report is produced this run. The
         admin has to fill in that row's details (especially Employee
         ID) on the tracker before the next run can proceed.
       - finds no new users: refreshes every tracker column that
         shares a header with the Employee List (matched by Employee
         ID), writes the result to a local Excel file as this run's
         output, and uploads that same file back to SharePoint as the
         new running tracker.

This class performs NO direct UI calls other than the file-picker dialog.
File collection/validation does not touch SharePoint or Unmand itself —
that's the Orchestrator's job (see orchestrators/billing_orchestrator.py,
the same separation of concerns PayrollFeature/BillingFeature use) — but
generate() does talk to SharePoint directly to read and write the tracker,
since the tracker is this tool's own state rather than a hand-off file.
"""

import io
from datetime import datetime
from difflib import get_close_matches
from pathlib import Path
import msoffcrypto
import pandas as pd

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Side, Border, Alignment
from openpyxl.utils import get_column_letter

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QFileDialog, QApplication

from services.sharepoint_service import SharePointService
from utils.app_config_user import get
from utils.file_utils import create_path, billing_app_path

# The 3 fixed files this tool always expects — shown as-is on the
# Insightful screen, so they're hardcoded here rather than
# pulled from the remote config the way Payroll/Billing's required_files are.
_REQUIRED_FILES = [
    "Employee List",
    "IT File Insightful",
]

# Fallback Employee ID column-name variants, used only if the caller
# doesn't supply its own list from config.
_DEFAULT_ID_NAMES = ["Employee ID", "EmployeeID", "Emp ID", "Emp. ID", "ID"]

# Password format used for encrypted files (same convention as Payroll/Billing)
_PASSWORD_PREFIX = get("PASSWORD_PREFIX", "")

# Tracker columns refreshed from the Employee List, hooked on Employee ID.
# "Employee Name" isn't a literal Employee List column — it's built from
# these name-part columns instead.
_DIRECT_UPDATE_COLUMNS = ["*ContactName", "Reference", "Separation Date"]
_NAME_PART_COLUMNS     = ["First Name", "Middle Name", "Last Name"]

# 1-indexed column positions that must be filled on every row before
# the tracker can be written out: Identifiers, Employee ID, and Col G.
_REQUIRED_FILLED_COLUMNS = (1, 2, 7)

class InsightfulTool:
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

    def prepare_insightful_files(self, expected_id_names: list = None, required_files: list = None, exchange_rate: str = None):
        """
        Start the Insightful file preparation flow.

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
        self.log.section("INSIGHTFUL FILE PREPARATION")
        self.log.info("InsightfulFeature: Deferring file dialog to next event loop tick")
        QTimer.singleShot(
            0,
            lambda: self._open_and_process(expected_id_names or _DEFAULT_ID_NAMES, required_files or _REQUIRED_FILES),
        )

    # ===================================================================
    # STEP 1 — OPEN FILE DIALOG + PROCESS
    # ===================================================================

    def _open_and_process(self, expected_id_names: list, required_files: list):
        """
        Open the native file-picker and, if files are selected, run the
        validation pipeline.

        Called by QTimer.singleShot() so it executes after the button
        click has been fully processed by the event loop — this prevents
        the main window from flashing when the dialog appears.
        """
        self.log.info("InsightfulFeature: Opening file dialog")
        self._emit_progress(2, "Selecting files…")

        # Parent=None keeps the dialog independent of the main window.
        file_paths, _ = QFileDialog.getOpenFileNames(
            self.main_window,
            "Select Insightful Excel Files",
            "",
            "Excel Files (*.xlsx)",
        )

        self.log.info(
            f"InsightfulFeature: File dialog closed | "
            f"selected={len(file_paths)} expected_max={len(required_files)}"
        )

        # ── Guard: nothing selected ───────────────────────────────────
        if not file_paths:
            self.log.info("InsightfulFeature: No files selected — aborting")
            self._emit_result("no_file_error")
            return

        # ── Guard: Incorrect number files ─────────────────────────────────────
        if len(file_paths) != len(required_files):
            self.log.warning(
                f"InsightfulFeature: Incorrect number files | "
                f"got={len(file_paths)} max={len(required_files)}"
            )
            self._emit_result("file_count_error")
            return

        self.log.info("InsightfulFeature: File count validated — starting processing")
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

        # ── Final error sweep ─────────────────────────────────────────
        self._emit_progress(45, "Final error sweep…")
        self.log.info("InsightfulFeature: Final error check across all files")
        error_codes = [
            f"{file}|{status}"
            for file, status in dataframes.items()
            if not isinstance(status, pd.DataFrame)
        ]

        if error_codes:
            self.log.warning(f"InsightfulFeature: Validation failed | errors={error_codes}")
            self._emit_result(error_codes)
        else:
            self.log.info("InsightfulFeature: All files validated — handing off to Orchestrator")
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
        self.log.info(f"InsightfulFeature: Reading {len(file_paths)} file(s)")
        dataframes = {}
        year      = datetime.now().year
        progress  = 10
        increment = progress / len(file_paths)

        for file_path in file_paths:
            filename = Path(file_path).name
            progress += increment

            # ── Note: "File type must be .xlsx" ───────────────────────
            if Path(file_path).suffix.lower() != ".xlsx":
                self.log.warning(f"InsightfulFeature: Invalid file type | file={filename}")
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
                self.log.warning(f"InsightfulFeature: Failed to read or decrypt | file={filename} error={e}")
                dataframes[filename] = "sensitivity_error"

        return dataframes

    def _check_required_files(self, dataframes: dict, required_files: list):
        """
        Verify all required files are present.

        Employee List uses fuzzy matching.
        Insightful must explicitly contain
        the corresponding insightful in the filename.
        """
        self.log.info(
            "InsightfulFeature: Checking all required files are present"
        )

        updated_dataframes = {}
        uploaded_files = list(dataframes.keys())

        for expected in required_files:

            # Strict matching for payroll registers
            if expected == "IT File Insightful":
                match = next(
                    (
                        filename for filename in uploaded_files
                        if "insightful" in filename.lower()
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
                    f"InsightfulFeature: Required file missing | "
                    f"expected='{expected}'"
                )
                updated_dataframes[expected] = "not_found_error"
            else:
                updated_dataframes[expected] = dataframes[match]

        dataframes.clear()
        dataframes.update(updated_dataframes)

    def _check_headers(self, dataframes: dict, expected_id_names: list):
        """
        Verify Row 1 is a real header row by fuzzy-matching an Employee
        ID column on each file, normalising it to "Employee ID".

        This is the note's "Headers in Row 1; use Sheet 1" requirement —
        if Row 1 isn't a real header row, no ID column will be found.
        Files with no match are marked "missing_header_error".
        """
        self.log.info("InsightfulFeature: Checking Row 1 headers / Employee ID column")

        for file_, content in dataframes.items():
            if not isinstance(content, pd.DataFrame):
                continue

            found = False

            if "insightful" in file_.lower():
                columns_lower = list(map(str.lower, map(str, content.columns)))
                if "identifiers" in columns_lower or "identifier" in columns_lower:
                    match_idx      = columns_lower.index("identifiers") if "identifiers" in columns_lower else columns_lower.index("identifier")
                    original_name  = content.columns[match_idx]
                    content.rename(columns={original_name: "Identifiers"}, inplace=True)
                    self.log.info(f"InsightfulFeature: Renamed column | file={file_} from='{original_name}' to='Identifiers'")
                    found = True
                    continue

            for id_name in expected_id_names:
                match = get_close_matches(
                    str(id_name),
                    list(map(str, content.columns)),
                    n=1,
                    cutoff=0.6,
                )
                if match:
                    content.rename(columns={match[0]: "Employee ID"}, inplace=True)
                    self.log.info(f"InsightfulFeature: Renamed column | file={file_} from='{match[0]}' to='Employee ID'")
                    found = True
                    break

            if not found:
                self.log.warning(f"InsightfulFeature: No Employee ID header found | file={file_}")
                dataframes[file_] = "missing_header_error"

    # ===================================================================
    # GENERATION (called by _InsightfulWorker)
    # Ported directly from the Unmand Python-block script.
    # ===================================================================

    def generate(self, files: dict, token: str, tracker_loc: str):
        """
        Returns
        -------
        Path | None
            Local path to the generated tracker Excel file — only when
            this run found no new users AND no Employee-List-driven
            changes. Otherwise the tracker is appended/refreshed and
            reuploaded with flags for review, and this returns None;
            the tool must be run again once flagged rows are reviewed
            before an output file is produced.
        """

        self.log.info("InsightfulFeature: Initialising SharePointService")
        self._sharepoint = SharePointService(token)

        self._emit_progress(50, "Fetching Insightful tracker…")
        tracker = self._fetch_tracker(tracker_loc)
        if tracker is None or tracker.empty:
            return None
        
        IT_file  = files.get("IT File Insightful")
        emp_list = files.get("Employee List")

        self._emit_progress(60, "Looking for new users…")
        new_users = self._check_new_user(tracker, IT_file) or []

        if new_users:
            self._emit_progress(65, "New user(s) found — appending to tracker…")
            tracker = self._append_new_users(tracker, new_users)
            self.log.info(f"InsightfulFeature: New user row(s) appended | ids={', '.join(new_users)}")

        self._emit_progress(75, "Updating tracker against Employee List…")
        tracker, unmatched_columns, separation_changed_rows, updated_cells = self._update_tracker_from_emp_list(tracker, emp_list)

        # ── New user(s) and/or Employee-List change(s) — flag, reupload, stop ──
        if new_users or updated_cells:
            if not self._upload_tracker(tracker, tracker_loc, unmatched_columns, separation_changed_rows, updated_cells):
                return None
            
            codes = []
            if new_users:
                self.log.info(f"InsightfulFeature: Stopping run — new user(s) pending manual completion | ids={', '.join(new_users)}")
                codes.append(f"{', '.join(new_users)}|new_user_found")
            if updated_cells:
                self.log.info(f"InsightfulFeature: Stopping run — {len(updated_cells)} cell(s) updated from Employee List, pending review")
                codes.append(f"{len(updated_cells)}|tracker_updated")

            self._emit_result(codes)
            self._emit_progress(100, "Done.")
            return None
        
        # ── No new users, no changes — safe to finalize ──────────────────
        blank_columns = self._check_required_columns_filled(tracker)
        if blank_columns:
            self.log.warning(f"InsightfulFeature: Required tracker column(s) incomplete | columns={blank_columns}")
            self._emit_result(f"{', '.join(blank_columns)}|tracker_incomplete_error")
            return None
        
        tracker = self._apply_billable_rule(tracker)
        self._emit_progress(90, "Writing output…")
        stamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = create_path(billing_app_path() / "Tools" / "Insightful") / f"Insightful_Tracker_{stamp}.xlsx"
        self._write_tracker_workbook(tracker, out_path, unmatched_columns, separation_changed_rows)
        self.log.info(f"InsightfulFeature: Output written | path={out_path} rows={len(tracker)}")

        self._emit_progress(95, "Uploading updated tracker…")
        if not self._upload_tracker(tracker, tracker_loc, unmatched_columns, separation_changed_rows):
            return None
        
        self._emit_progress(100, "Done.")
        return out_path

    # ===================================================================
    # GENERATION HELPERS
    # ===================================================================
    def _fetch_tracker(self, tracker_loc: str):

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
        url = f"{base_url}{tracker_loc}"

        self.log.info(
            "InsightfulFeature: Downloading tracker from SharePoint"
        )

        response = self._sharepoint.get(url)
        status   = response.status_code

        if 400 <= status < 500:
            self.log.warning(f"InsightfulFeature: Tracker download rejected | HTTP={status}")
            self._emit_result(f"{status}|tracker_client_error")
            return None

        if not str(status).startswith("2"):
            self.log.warning(
                f"InsightfulFeature: Headers download failed | "
                f"HTTP={status}"
            )
            self._emit_result("premium_download_error")
            return None


        try:
            excel_file = io.BytesIO(response.content)

            df = pd.read_excel(
                excel_file,
                engine="openpyxl"
            )
            return df

        except Exception as e:
            self.log.warning(
                f"InsightfulFeature: Failed to parse tracker sheet — {e}",
                error=e
            )
            self._emit_result("processing_error")
            return None

    def _check_new_user(self, tracker: pd.DataFrame, IT_file: pd.DataFrame) -> list | None:
        """
        Find new users in the IT file whose Identifiers are not yet in the tracker.
        """
        self.log.info("InsightfulFeature: Checking for new users")
        try:
            tracker_ids = set(tracker["Identifiers"].dropna().astype(str))
            IT_file_ids = set(IT_file["Identifiers"].dropna().astype(str))
            new_users = sorted(IT_file_ids - tracker_ids)

            if not new_users:
                return None

            self.log.info(f"InsightfulFeature: New user(s) found | ids={', '.join(new_users)}")
            return new_users

        except Exception as e:
            self.log.exception(f"InsightfulFeature: Error checking for new users | error={e}")
            self._emit_result("new_user_error")
            return None

    def _append_new_users(self, tracker: pd.DataFrame, new_users: list) -> pd.DataFrame:
        """
        Append one blank row per newly found Identifier to the tracker.

        Every other tracker column is left blank so the new row is
        obvious on the tracker itself — the admin fills in the rest
        (especially Employee ID) by hand before the next run.
        """
        self.log.info(f"InsightfulFeature: Appending {len(new_users)} new user row(s) to tracker")
        new_rows = pd.DataFrame(
            [{**{col: "" for col in tracker.columns}, "Identifiers": identifier,
            "Created": datetime.today().strftime("%Y-%m-%d"),
            "Billable Yes/No": "No" if "i2g" in identifier.lower() else ""}
            for identifier in new_users]
        )
        return pd.concat([tracker, new_rows], ignore_index=True)

    def _update_tracker_from_emp_list(self, tracker: pd.DataFrame, emp_list: pd.DataFrame):
        """
        Refresh the tracker's data from the Employee List, hooked on
        Employee ID.
        Columns updated
        ----------------
        - "Employee Name"   — built as "First Name Middle Name Last Name"
                                from the Employee List's separate name
                                columns (there's no single "Employee Name"
                                column on the Employee List itself).
        - "*ContactName"    — direct column match.
        - "Reference"       — direct column match.
        - "Separation Date" — direct column match. If it changes for a
                                row this run, "Billable Yes/No" on that
                                row is flagged for manual review, since a
                                new separation date should prompt a
                                billable status check.
        Rows whose Employee ID has no match in the Employee List (e.g. a
        new user still pending manual completion) keep their existing
        values untouched.

        Returns
        -------
        tuple[pd.DataFrame, set[str], set]
            (updated tracker,
                names of the columns above that aren't actually available on
                    the Employee List this run — flagged on the header,
                index labels of rows whose Separation Date changed —
                    flagged on Billable Yes/No)
        """
        if "Employee ID" not in tracker.columns or "Employee ID" not in emp_list.columns:
            self.log.warning(
                "InsightfulFeature: 'Employee ID' column missing from tracker or Employee List — skipping update"
            )
            return tracker, set(), set(), set()
        
        tracker    = tracker.copy()
        emp_lookup = emp_list.drop_duplicates(subset="Employee ID", keep="last").set_index("Employee ID")
        unmatched_columns       = set()
        separation_changed_rows = set()
        updated_cells           = set()   # {(row_index, col_name)} — old value != refreshed value

        # ── "Employee Name" = First Name + Middle Name + Last Name ─────────
        if "Employee Name" in tracker.columns:
            available_name_parts = [c for c in _NAME_PART_COLUMNS if c in emp_lookup.columns]
            if not available_name_parts:
                unmatched_columns.add("Employee Name")
            else:
                def _full_name(emp_id):
                    if emp_id not in emp_lookup.index:
                        return None
                    parts = [
                        str(emp_lookup.loc[emp_id, c]).strip()
                        for c in available_name_parts
                        if pd.notna(emp_lookup.loc[emp_id, c]) and str(emp_lookup.loc[emp_id, c]).strip()
                    ]
                    return " ".join(parts) if parts else None
                
                refreshed = tracker["Employee ID"].map(_full_name)
                changed_mask = (
                    refreshed.notna()
                    & (refreshed.astype(str).str.strip() != tracker["Employee Name"].astype(str).str.strip())
                )
                updated_cells.update((idx, "Employee Name") for idx in tracker.index[changed_mask])
                tracker["Employee Name"] = refreshed.combine_first(tracker["Employee Name"])

        # ── Direct-match columns ("*ContactName", "Reference", "Separation Date") ──
        for col in _DIRECT_UPDATE_COLUMNS:
            if col not in tracker.columns:
                continue

            if col not in emp_lookup.columns:
                unmatched_columns.add(col)
                continue

            refreshed = tracker["Employee ID"].map(emp_lookup[col])
            changed_mask = (
                refreshed.notna()
                & (refreshed.astype(str).str.strip() != tracker[col].astype(str).str.strip())
            )

            if col == "Separation Date":
                separation_changed_rows.update(tracker.index[changed_mask])

            updated_cells.update((idx, col) for idx in tracker.index[changed_mask])
            tracker[col] = refreshed.combine_first(tracker[col])

        if unmatched_columns:
            self.log.warning(
                f"InsightfulFeature: Column(s) not available in Employee List | columns={sorted(unmatched_columns)}"
            )
        if separation_changed_rows:
            self.log.info(f"InsightfulFeature: Separation Date changed | rows={sorted(separation_changed_rows)}")
        if updated_cells:
            self.log.info(f"InsightfulFeature: {len(updated_cells)} cell(s) updated from Employee List")
        return tracker, unmatched_columns, separation_changed_rows, updated_cells

    def _upload_tracker(self, tracker: pd.DataFrame, tracker_loc: str, unmatched_columns: set = None, separation_changed_rows: set = None, updated_cells: set = None) -> bool:
        """
        Upload the tracker DataFrame back to SharePoint, at the same
        location it was downloaded from, so it stays the single running
        source of truth.
        """

        base_url = get("SP_BASE_URL", "")
        url      = f"{base_url}{tracker_loc}"

        self.log.info("InsightfulFeature: Uploading updated tracker to SharePoint")

        buffer = io.BytesIO()
        wb = self._build_tracker_workbook(tracker, unmatched_columns, separation_changed_rows, updated_cells)
        wb.save(buffer)
        buffer.seek(0)

        response = self._sharepoint.put_file(
            url,
            data=buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            bypass_lock=True,
        )
        status = response.status_code
        if status == 423:
            self.log.warning("InsightfulFeature: Tracker upload blocked — resource locked (HTTP 423)")
            self._emit_result("tracker_locked_error")
            return False
        
        if 400 <= status < 500:
            self.log.warning(f"InsightfulFeature: Tracker upload rejected | HTTP={status}")
            self._emit_result(f"{status}|tracker_client_error")
            return False
        
        if not str(status).startswith("2"):
            self.log.warning(f"InsightfulFeature: Tracker upload failed | HTTP={status}")
            self._emit_result("tracker_upload_error")
            return False
        
        self.log.info("InsightfulFeature: Tracker uploaded successfully")

        return True

    def _check_required_columns_filled(self, tracker: pd.DataFrame) -> list:
        blank_columns = []
        for pos in _REQUIRED_FILLED_COLUMNS:
            idx = pos - 1
            if idx >= len(tracker.columns):
                continue

            col_name   = tracker.columns[idx]
            col_series = tracker.iloc[:, idx]

            is_blank   = col_series.isna() | (col_series.astype(str).str.strip() == "")
            if is_blank.any():
                blank_columns.append(col_name)

        return blank_columns
    
    def _apply_billable_rule(self, tracker: pd.DataFrame) -> pd.DataFrame:
        """
        Enforce the Billable Yes/No business rule: any row whose
        Separation Date isn't "Not yet" gets Billable Yes/No set to "No".
        """
        if "Separation Date" not in tracker.columns or "Billable Yes/No" not in tracker.columns:
            self.log.warning(
                "InsightfulFeature: 'Separation Date' or 'Billable Yes/No' column missing — skipping billable rule"
            )
            return tracker
        
        tracker = tracker.copy()
        separated_mask = ((tracker["Separation Date"].astype(str).str.strip() != "Not yet set") |
                        tracker["*ContactName"].astype(str).str.strip().str.lower().str.contains("intogreat", na=False))
        tracker.loc[separated_mask, "Billable Yes/No"] = "No"

        if separated_mask.any():
            self.log.info(
                    f"InsightfulFeature: Marked {int(separated_mask.sum())} row(s) not billable due to Separation Date"
                )
        return tracker

    # ===================================================================
    # EXCEL WORKBOOK WRITER
    # ===================================================================

    def _build_tracker_workbook(self, tracker: pd.DataFrame, unmatched_columns: set = None, separation_changed_rows: set = None, updated_cells: set = None) -> Workbook:
        """
        Build a styled Insightful tracker workbook.
        Formatting rules
        ----------------
        - Bold white text on a blue header row, autofilter on Row 1,
            frozen header, columns auto-sized to their content.
        - Column A (Identifiers) / Column B (Employee ID) / Billable Yes/No — yellow fill
            wherever either is blank, flagging an incomplete new-user row.
        - Any header in `unmatched_columns` — orange fill, flagging a
            tracker column with no counterpart in the Employee List, so it
            wasn't refreshed this run.
        - "Billable Yes/No" cell on any row index in
            `separation_changed_rows` — red fill, flagging that Separation
            Date changed this run and billable status needs a manual check.
        """

        unmatched_columns       = unmatched_columns or set()
        separation_changed_rows = separation_changed_rows or set()
        updated_cells           = updated_cells or set()

        wb = Workbook()
        ws = wb.active
        ws.title = "Insightful Tracker"

        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="203864")
        thin = Side(style="thin", color="B8B8B8")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        left = Alignment(horizontal="left", vertical="center")
        new_user_flag_fill    = PatternFill("solid", fgColor="FFFF00")  # Col A/B blank
        unmatched_header_fill = PatternFill("solid", fgColor="ED7D31")  # header, no EmpList source
        separation_flag_fill  = PatternFill("solid", fgColor="FF0000")  # Billable Yes/No, Sep. Date changed

        columns          = list(tracker.columns)
        billable_col_idx = (columns.index("Billable Yes/No") + 1) if "Billable Yes/No" in columns else None

        for col_idx, col_name in enumerate(columns, start=1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.font = header_font
            cell.fill = unmatched_header_fill if col_name in unmatched_columns else header_fill
            cell.alignment = center
            cell.border = border

        for row_pos, (row_index, row) in enumerate(zip(tracker.index, tracker.itertuples(index=False))):
            excel_row = row_pos + 2
            for col_idx, value in enumerate(row, start=1):
                cell = ws.cell(row=excel_row, column=col_idx, value=value)
                cell.border = border
                cell.alignment = left
                col_name = columns[col_idx - 1]
                is_blank = value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == ""
                if (row_index, col_name) in updated_cells:
                    cell.fill = new_user_flag_fill  # yellow — value refreshed from Employee List
                if col_idx in _REQUIRED_FILLED_COLUMNS and is_blank:
                    cell.fill = new_user_flag_fill
                if billable_col_idx is not None and col_idx == billable_col_idx and row_index in separation_changed_rows:
                    cell.fill = separation_flag_fill

        last_col_letter = get_column_letter(len(columns)) if len(columns) else "A"
        ws.auto_filter.ref = f"A1:{last_col_letter}1"
        ws.freeze_panes = "A2"

        for col_cells in ws.columns:
            length = max((len(str(c.value)) if c.value is not None else 0) for c in col_cells)
            ws.column_dimensions[get_column_letter(col_cells[0].column)].width = min(max(length + 2, 8), 40)

        return wb
            
    def _write_tracker_workbook(self, tracker, out_path, unmatched_columns=None, separation_changed_rows=None, updated_cells=None) -> None:
        """Write the updated Insightful tracker as a single styled sheet — same styling as the SharePoint copy."""
        wb = self._build_tracker_workbook(tracker, unmatched_columns, separation_changed_rows, updated_cells)
        wb.save(out_path)

    # ===================================================================
    # EMIT HELPERS
    # ===================================================================

    def _emit_result(self, codes):
        if not self.on_result:
            self.log.warning("InsightfulFeature: on_result callback not wired — result dropped")
            return
        normalized = list(codes) if isinstance(codes, (list, tuple)) else [codes]
        self.log.info(f"InsightfulFeature: Emitting result codes | codes={normalized}")
        self.on_result(normalized)

    def _emit_files(self, files: dict):
        if not self.uploaded_files:
            self.log.warning("InsightfulFeature: uploaded_files callback not wired — files dropped")
            return
        self.log.info(f"InsightfulFeature: Handing {len(files)} file(s) to Orchestrator")
        self.uploaded_files(files)

    def _emit_progress(self, percent: int, message: str):
        if not self.on_progress:
            return
        self.log.info(f"InsightfulFeature: Progress | {percent}% — {message}")
        self.on_progress(percent, message)
