"""
payroll.py
----------
PayrollFeature — file collection and validation for the Payroll upload flow.

Responsibilities
----------------
1. Download the Payroll Headers reference file from SharePoint so
   uploaded files can be validated against the expected column list.
2. Open a native file-picker dialog for the user to select their
   Excel payroll files (deferred via QTimer so the UI settles first).
3. Read each selected file, decrypting it with msoffcrypto when needed.
4. Run a series of validation checks (date format, header presence,
   total row, required files, new headers).
5. Emit the result back to the Orchestrator via callbacks:
       on_result(codes)        — list of status-code strings for the UI
       uploaded_files(dfs)     — dict of validated DataFrames, ready to upload

This class performs NO direct UI calls other than the file-picker dialog.
All status reporting goes through the on_result callback.

File-picker deferral
--------------------
The dialog is opened via QTimer.singleShot(0, ...) so it fires after the
current Qt event (the button click) has fully resolved.  Without this,
the main window briefly flashes as Qt tries to repaint during the
synchronous dialog open.
"""

import io
import json
import os
from datetime import datetime
from difflib import get_close_matches
from pathlib import Path

import msoffcrypto
import pandas as pd
from dotenv import load_dotenv
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QFileDialog

from services.sharepoint_service import SharePointService
from ui.statuses import parse_status_code
from utils.app_config_user import get

# Maximum number of files the user may select in one upload session
MAX_FILES = None   # None = derived from len(required_files) at runtime

# Password format used for encrypted payroll files
_PASSWORD_PREFIX = get("PASSWORD_PREFIX","")


class PayrollFeature:
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

    # ===================================================================
    # PUBLIC ENTRY POINT
    # ===================================================================

    def prepare_payroll_files( self,files: list, payroll_metadata: dict, source: str, token: str,):
        """
        Start the payroll file preparation flow.

        Downloads the headers reference first, then defers opening the
        file dialog to the next Qt event loop tick so the UI can fully
        settle after the button click before the dialog appears.

        Parameters
        ----------
        files            : list[str]   Required file names from config.
        payroll_metadata : dict        Payroll section of the remote config.
        source           : str         "Sprout" or "DarwinBox".
        token            : str         MSAL Bearer token for SharePoint.
        """
        self.log.section("PAYROLL FILE PREPARATION")
        self.log.info("PayrollFeature: Initialising SharePointService")
        self._sharepoint = SharePointService(token)

        # ── Download payroll headers reference ────────────────────────
        headers = self._download_headers(payroll_metadata, source)
        if headers is None:
            # Error already emitted inside _download_headers
            return

        # ── Defer file picker so the button click event fully resolves ─
        self.log.info("PayrollFeature: Deferring file dialog to next event loop tick")
        QTimer.singleShot(0,lambda: self._open_and_process(files, payroll_metadata, source, headers))


    # ===================================================================
    # STEP 1 — DOWNLOAD HEADERS REFERENCE
    # ===================================================================

    def _download_headers(self, payroll_metadata: dict, source: str):
        """
        Fetch the Payroll Headers Excel from SharePoint and return the
        list of expected column headers for the current source.

        Returns
        -------
        list[str] or None
            The header list on success, or None on any failure (result
            already emitted before returning None).
        """
        base_url    = get("SP_BASE_URL", "")
        headers_loc = payroll_metadata["headers_loc"]
        url         = f"{base_url}{headers_loc}"

        self.log.info(f"PayrollFeature: Downloading headers from SharePoint")
        response = self._sharepoint.get(url)

        if not str(response.status_code).startswith("2"):
            self.log.warning(f"PayrollFeature: Headers download failed | HTTP={response.status_code}")
            self._emit_result("premium_download_error")
            return None

        # Parse the sheet that corresponds to the selected source
        sheet_name = ("Sprout Payroll Headers" if source == "Sprout"else "DarwinBox Payroll Headers")
        self.log.info(f"PayrollFeature: Parsing headers sheet | sheet={sheet_name}")

        try:
            excel_file = io.BytesIO(response.content)
            df = pd.read_excel(excel_file, sheet_name=sheet_name, header=12, engine="openpyxl")
            payroll_headers = list(df["Headers"])
            self.log.info(f"PayrollFeature: Loaded {len(payroll_headers)} payroll header(s)")
            return payroll_headers

        except Exception as e:
            self.log.warning(f"PayrollFeature: Failed to parse headers sheet — {e}", error=e)
            self._emit_result("sensitivity_error")
            return None

    # ===================================================================
    # STEP 2 — OPEN FILE DIALOG + PROCESS
    # ===================================================================

    def _open_and_process(self, files: list,payroll_metadata: dict,source: str,payroll_headers: list,):
        """
        Open the native file-picker and, if files are selected, run
        the full validation pipeline.

        Called by QTimer.singleShot() so it executes after the button
        click has been fully processed by the event loop — this prevents
        the main window from flashing when the dialog appears.

        Parameters
        ----------
        files           : list[str]   Required file names from config.
        payroll_metadata: dict        Payroll section of the remote config.
        source          : str         "Sprout" or "DarwinBox".
        payroll_headers : list[str]   Column whitelist from the reference sheet.
        """
        self.log.info("PayrollFeature: Opening file dialog")

        # Parent=None keeps the dialog independent of the main window.
        # Passing the main window as parent caused it to briefly flash.
        file_paths, _ = QFileDialog.getOpenFileNames(
            self.main_window,
            "Select Payroll Excel Files",
            "",
            "Excel Files (*.xlsx *.xls)",
        )

        self.log.info(f"PayrollFeature: File dialog closed | selected={len(file_paths)} expected_max={len(files)}")

        # ── Guard: nothing selected ───────────────────────────────────
        if not file_paths:
            self.log.info("PayrollFeature: No files selected — aborting")
            self._emit_result("no_file_error")
            return

        # ── Guard: too many files ─────────────────────────────────────
        if len(file_paths) > len(files):
            self.log.warning(f"PayrollFeature: Too many files | got={len(file_paths)} max={len(files)}")
            self._emit_result("file_exceed_error")
            return

        self.log.info("PayrollFeature: File count validated — starting processing")
        self._process_files(file_paths, files, payroll_metadata, payroll_headers)

    # ===================================================================
    # STEP 3 — FULL VALIDATION PIPELINE
    # ===================================================================

    def _process_files(self, file_paths: list, required_files: list, payroll_metadata: dict,payroll_headers: list,):
        """
        Run the full validation pipeline on the selected files.

        Checks performed (in order)
        ----------------------------
        1. Read / decrypt each file.
        2. Validate attendance date format.
        3. Detect new/unknown headers in the payroll register.
        4. Normalise Employee ID column name.
        5. Check all required files are present.
        6. Verify the Total row exists in the current payroll.
        7. Aggregate deduction files by Employee ID.

        On success, delegates to uploaded_files().
        On any failure, emits the error codes via on_result().
        """
        dataframes = self._read_files(file_paths)

        self._validate_attendance_dates(dataframes)
        new_headers = self._detect_new_headers(dataframes, payroll_headers, payroll_metadata)
        if new_headers:
            # New headers were found and uploaded — stop here
            return

        self._normalise_employee_id(dataframes, payroll_metadata["expected_id_names"])
        self._check_required_files(dataframes, required_files)
        self._check_total_row(dataframes)
        self._aggregate_deductions(dataframes)

        # ── Final error sweep ─────────────────────────────────────────
        self.log.info("PayrollFeature: Final error check across all files")
        error_codes = [
            f"{file}|{status}"
            for file, status in dataframes.items()
            if not isinstance(status, pd.DataFrame)
        ]

        if error_codes:
            self.log.warning(f"PayrollFeature: Validation failed | errors={error_codes}")
            self._emit_result(error_codes)
        else:
            self.log.info("PayrollFeature: All files validated — handing off to Orchestrator")
            self._emit_files(dataframes)

    # ===================================================================
    # VALIDATION HELPERS
    # ===================================================================

    def _read_files(self, file_paths: list) -> dict:
        """
        Read each selected file into a DataFrame, decrypting if needed.

        Encrypted files are opened with msoffcrypto using the standard
        INTOGREAT{YYYY} password.  Files that cannot be read at all are
        stored as "sensitivity_error" for the error sweep.

        Returns
        -------
        dict[str, pd.DataFrame | str]
            Keys are file names (stem only, no directory).
            Values are DataFrames on success, or an error-code string.
        """
        self.log.info(f"PayrollFeature: Reading {len(file_paths)} file(s)")
        dataframes = {}
        year       = datetime.now().year

        for file_path in file_paths:
            # Use pathlib for OS-safe name extraction (fixes the "/" split bug)
            filename = Path(file_path).name

            # ── Attempt unencrypted read ──────────────────────────────
            try:
                df                  = pd.read_excel(file_path, dtype=str)
                dataframes[filename] = df
                self.log.info(f"PayrollFeature: Read OK | file={filename}")
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
                df                   = pd.read_excel(decrypted, dtype=str)
                dataframes[filename]  = df
                self.log.info(f"PayrollFeature: Decrypted and read OK | file={filename}")

            except Exception as e:
                self.log.warning(f"PayrollFeature: Failed to read or decrypt | file={filename} error={e}")
                dataframes[filename] = "sensitivity_error"

        return dataframes

    def _validate_attendance_dates(self, dataframes: dict):
        """
        Flag attendance files that contain weekday-name date strings.

        Attendance files exported from some HRIS systems format dates as
        "Monday, 1 Apr 2026" — the ", " suffix breaks downstream parsing.
        Files with this pattern are marked "date_format_error".
        """
        self.log.info("PayrollFeature: Validating attendance date formats")

        for filename, df in dataframes.items():
            if "attendance" not in filename.lower():
                continue
            if not isinstance(df, pd.DataFrame):
                continue

            has_day_name = (
                df.astype(str)
                 .apply(lambda col: col.str.contains("day,", na=False))
                 .any()
                 .any()
            )
            if has_day_name:
                self.log.warning(f"PayrollFeature: Invalid date format detected | file={filename}")
                dataframes[filename] = "date_format_error"

    def _detect_new_headers(self, dataframes: dict, payroll_headers: list, payroll_metadata: dict,) -> bool:
        """
        Check the payroll register for columns not in the whitelist.

        When new headers are found they are uploaded to SharePoint and
        the user is notified via "new_headers_error".  The upload flow
        stops here so the team can review and approve the new columns
        before they are processed.

        Returns
        -------
        bool
            True if new headers were found (and uploaded).
            False if the register is clean.
        """
        self.log.info("PayrollFeature: Checking payroll register for new/unknown headers")
        new_headers = {}

        for filename, df in dataframes.items():
            if not isinstance(df, pd.DataFrame):
                continue
            if "payroll register" not in filename.lower():
                continue

            unknown = [
                col for col in df.columns
                if col not in payroll_headers and "Unnamed" not in col
            ]
            if unknown:
                new_headers[filename] = unknown

        if not new_headers:
            self.log.info("PayrollFeature: No new headers found")
            return False

        self.log.info(f"PayrollFeature: New headers detected — uploading | headers={new_headers}")

        base_url        = get("SP_BASE_URL", "")
        new_headers_loc = payroll_metadata["new_headers_loc"]
        url             = f"{base_url}{new_headers_loc}"

        self._sharepoint.put_file(url, json.dumps(new_headers, indent=4))
        self.log.info("PayrollFeature: New headers uploaded to SharePoint")
        self._emit_result("new_headers_error")
        return True

    def _normalise_employee_id(self, dataframes: dict, expected_id_names: list):
        """
        Rename the Employee ID column to the canonical "Employee ID" label.

        Uses fuzzy matching (difflib.get_close_matches, cutoff=0.6) to
        find the best column name match across the expected_id_names list.
        Files with no matching column are marked "missing_header_error".
        """
        self.log.info("PayrollFeature: Normalising Employee ID column names")

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
                    self.log.info(f"PayrollFeature: Renamed column | file={file_} from='{match[0]}' to='Employee ID'")
                    found = True
                    break

            if not found:
                self.log.warning(f"PayrollFeature: No Employee ID column found | file={file_}")
                dataframes[file_] = "missing_header_error"

    def _check_required_files(self, dataframes: dict, required_files: list):
        """
        Verify every required file has a fuzzy match in the upload set.

        Uses get_close_matches (cutoff=0.5) against the uploaded file
        names.  Missing files are added to dataframes with "not_found_error".
        Renames matched keys to the expected file name.
        """
        self.log.info("PayrollFeature: Checking all required files are present")
        updated_dataframes = {}

        for expected in required_files:
            match = get_close_matches(expected, list(dataframes.keys()), n=1, cutoff=0.5)
            if not match:
                self.log.warning(f"PayrollFeature: Required file missing | expected='{expected}'")
                dataframes[expected] = "not_found_error"
            else:
                updated_dataframes[expected] = dataframes[match[0]]

        # replace original dict content
        dataframes.clear()
        dataframes.update(updated_dataframes)

    def _check_total_row(self, dataframes: dict):
        """
        Verify the current payroll file has a "Total" row.

        The total row is identified by the Employee ID column containing
        the word "total" (case-insensitive).  Files without it are marked
        "missing_total_error".
        """
        self.log.info("PayrollFeature: Checking for Total row in current payroll")

        for filename, df in dataframes.items():
            if not ("curr" in filename.lower() and "payroll" in filename.lower()):
                continue
            if not isinstance(df, pd.DataFrame):
                continue
            if "Employee ID" not in df.columns:
                continue

            has_total = (
                df["Employee ID"]
                 .astype(str)
                 .str.lower()
                 .str.contains("total", na=False)
                 .any()
            )
            if has_total:
                self.log.info(f"PayrollFeature: Total row found | file={filename}")
            else:
                self.log.warning(f"PayrollFeature: Missing Total row | file={filename}")
                dataframes[filename] = "missing_total_error"

    def _aggregate_deductions(self, dataframes: dict):
        """
        Group deduction files by Employee ID and sum the Number/Amount column.

        Deduction files may have one row per transaction.  The payroll
        processor expects a single row per employee, so we aggregate here
        before uploading.
        """
        self.log.info("PayrollFeature: Aggregating deduction files by Employee ID")
        for filename, df in dataframes.items():
            if "deduct" not in filename.lower():
                continue
            if not isinstance(df, pd.DataFrame):
                continue

            if "Charge Type/Category" not in df.columns:
                dataframes[filename] = "category_column_error"

            df["Number/Amount"] = pd.to_numeric(df["Number/Amount"], errors="coerce").fillna(0)

            aggregated = df.groupby(["Employee ID", "Charge Type/Category"], as_index=False).agg({"Number/Amount": "sum"})

            dataframes[filename] = aggregated
            self.log.info(f"PayrollFeature: Deductions aggregated | file={filename} employees={len(aggregated)}")

    # ===================================================================
    # EMIT HELPERS
    # ===================================================================

    def _emit_result(self, codes):
        """
        Fire the on_result callback with a normalised list of status codes.

        Parameters
        ----------
        codes : str | list[str]
            One or more status-code strings for the UI to display.
        """
        if not self.on_result:
            self.log.warning("PayrollFeature: on_result callback not wired — result dropped")
            return

        normalized = list(codes) if isinstance(codes, (list, tuple)) else [codes]
        self.log.info(f"PayrollFeature: Emitting result codes | codes={normalized}")
        self.on_result(normalized)

    def _emit_files(self, files: dict):
        """
        Fire the uploaded_files callback with the validated DataFrames.

        Parameters
        ----------
        files : dict[str, pd.DataFrame]
            Validated, ready-to-upload payroll DataFrames.
        """
        if not self.uploaded_files:
            self.log.warning("PayrollFeature: uploaded_files callback not wired — files dropped")
            return

        self.log.info(f"PayrollFeature: Handing {len(files)} file(s) to Orchestrator")
        self.uploaded_files(files)
