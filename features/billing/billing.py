"""
billing.py
----------
BillingFeature — file collection and validation for the Billing "Start
Automation" upload flow.

This mirrors features/payroll/payroll.py (PayrollFeature) structurally —
same file-picker → read/decrypt → validate → upload hand-off pipeline —
adapted for Billing:

    - No source split (Payroll has Sprout/DarwinBox; Billing has one flow).
    - The Payroll-only domain checks (attendance date format, Total row,
      deduction aggregation, new-header detection against a whitelist
      sheet) are NOT carried over — those are specific to payroll register
      shapes. If Billing turns out to need equivalent checks, add them as
      new private methods and call them from _process_files(), the same
      way PayrollFeature does.

Responsibilities
----------------
1. Open a native file-picker dialog for the user to select their billing
   Excel files (deferred via QTimer so the UI settles first).
2. Read each selected file, decrypting it with msoffcrypto when needed.
3. Verify all required files (from config) are present.
4. Emit the result back to the Orchestrator via callbacks:
       on_result(codes)        — list of status-code strings for the UI
       uploaded_files(dfs)     — dict of validated DataFrames, ready to upload

This class performs NO direct UI calls other than the file-picker dialog.
All status reporting goes through the on_result callback.
"""

import io
from datetime import datetime
from difflib import get_close_matches
from pathlib import Path

import msoffcrypto
import pandas as pd
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QFileDialog, QApplication

from utils.app_config_user import get

# Password format used for encrypted billing files (same convention as Payroll)
_PASSWORD_PREFIX = get("PASSWORD_PREFIX", "")


class BillingFeature:
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

    def prepare_billing_files(self, files: list, billing_metadata: dict):
        """
        Start the billing file preparation flow.

        Defers opening the file dialog to the next Qt event loop tick so
        the UI can fully settle after the button click before the dialog
        appears.

        Parameters
        ----------
        files            : list[str]   Required file names from config.
        billing_metadata : dict        Billing section of the remote config.
        """
        self.log.section("BILLING FILE PREPARATION")
        self.log.info("BillingFeature: Deferring file dialog to next event loop tick")
        QTimer.singleShot(0, lambda: self._open_and_process(files, billing_metadata))

    # ===================================================================
    # STEP 1 — OPEN FILE DIALOG + PROCESS
    # ===================================================================

    def _open_and_process(self, files: list, billing_metadata: dict):
        """
        Open the native file-picker and, if files are selected, run the
        validation pipeline.

        Called by QTimer.singleShot() so it executes after the button
        click has been fully processed by the event loop — this prevents
        the main window from flashing when the dialog appears.
        """
        self.log.info("BillingFeature: Opening file dialog")
        self._emit_progress(2, "Selecting files…")

        file_paths, _ = QFileDialog.getOpenFileNames(
            self.main_window,
            "Select Billing Excel Files",
            "",
            "Excel Files (*.xlsx *.xls)",
        )

        self.log.info(f"BillingFeature: File dialog closed | selected={len(file_paths)} expected_max={len(files)}")

        # ── Guard: nothing selected ───────────────────────────────────
        if not file_paths:
            self.log.info("BillingFeature: No files selected — aborting")
            self._emit_result("no_file_error")
            return

        # ── Guard: too many files ─────────────────────────────────────
        if len(file_paths) > len(files):
            self.log.warning(f"BillingFeature: Too many files | got={len(file_paths)} max={len(files)}")
            self._emit_result("file_exceed_error")
            return

        self.log.info("BillingFeature: File count validated — starting processing")
        self._process_files(file_paths, files, billing_metadata)

    # ===================================================================
    # STEP 2 — VALIDATION PIPELINE
    # ===================================================================

    def _process_files(self, file_paths: list, required_files: list, billing_metadata: dict):
        """
        Run the validation pipeline on the selected files.

        Checks performed (in order)
        ----------------------------
        1. Read / decrypt each file.
        2. Normalise the ID column name (if configured).
        3. Check all required files are present.

        On success, delegates to uploaded_files().
        On any failure, emits the error codes via on_result().
        """
        self._emit_progress(10, "Reading files…")
        QApplication.processEvents()
        dataframes = self._read_files(file_paths)

        expected_id_names = billing_metadata.get("expected_id_names")
        if expected_id_names:
            self._emit_progress(40, "Normalising ID column…")
            self._normalise_id_column(dataframes, expected_id_names)

        self._emit_progress(60, "Checking required files…")
        self._check_required_files(dataframes, required_files)

        # ── Final error sweep ─────────────────────────────────────────
        self._emit_progress(80, "Sending files to Unmand...")
        self.log.info("BillingFeature: Final error check across all files")
        error_codes = [
            f"{file}|{status}"
            for file, status in dataframes.items()
            if not isinstance(status, pd.DataFrame)
        ]

        if error_codes:
            self.log.warning(f"BillingFeature: Validation failed | errors={error_codes}")
            self._emit_result(error_codes)
        else:
            self.log.info("BillingFeature: All files validated — handing off to Orchestrator")
            self._emit_files(dataframes)

    # ===================================================================
    # VALIDATION HELPERS
    # ===================================================================

    def _read_files(self, file_paths: list) -> dict:
        """
        Read each selected file into a DataFrame, decrypting if needed.

        Encrypted files are opened with msoffcrypto using the standard
        INTOGREAT{YYYY} password. Files that cannot be read at all are
        stored as "sensitivity_error" for the error sweep.

        Returns
        -------
        dict[str, pd.DataFrame | str]
            Keys are file names (stem only, no directory).
            Values are DataFrames on success, or an error-code string.
        """
        self.log.info(f"BillingFeature: Reading {len(file_paths)} file(s)")
        dataframes = {}
        year      = datetime.now().year
        progress  = 10
        increment = progress / len(file_paths)

        for file_path in file_paths:
            filename = Path(file_path).name
            progress += increment

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
                self.log.warning(f"BillingFeature: Failed to read or decrypt | file={filename} error={e}")
                dataframes[filename] = "sensitivity_error"

        return dataframes

    def _normalise_id_column(self, dataframes: dict, expected_id_names: list):
        """
        Rename whichever ID column exists to a canonical "Employee ID" label.

        Uses fuzzy matching (difflib.get_close_matches, cutoff=0.6) against
        expected_id_names from config. Files with no matching column are
        left as-is — this is a best-effort convenience, not a hard error.
        """
        self.log.info("BillingFeature: Normalising ID column names")

        for file_, content in dataframes.items():
            if not isinstance(content, pd.DataFrame):
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
                    self.log.info(f"BillingFeature: Renamed column | file={file_} from='{match[0]}' to='Employee ID'")
                    break

    def _check_required_files(self, dataframes: dict, required_files: list):
        """
        Verify every required file has a fuzzy match in the upload set.

        Uses get_close_matches (cutoff=0.5) against the uploaded file
        names. Missing files are added to dataframes with "not_found_error".
        Renames matched keys to the expected file name.
        """
        self.log.info("BillingFeature: Checking all required files are present")
        updated_dataframes = {}

        for expected in required_files:
            match = get_close_matches(expected, list(dataframes.keys()), n=1, cutoff=0.5)
            if not match:
                self.log.warning(f"BillingFeature: Required file missing | expected='{expected}'")
                dataframes[expected] = "not_found_error"
            else:
                updated_dataframes[expected] = dataframes[match[0]]

        dataframes.clear()
        dataframes.update(updated_dataframes)

    # ===================================================================
    # EMIT HELPERS
    # ===================================================================

    def _emit_result(self, codes):
        """Fire the on_result callback with a normalised list of status codes."""
        if not self.on_result:
            self.log.warning("BillingFeature: on_result callback not wired — result dropped")
            return

        normalized = list(codes) if isinstance(codes, (list, tuple)) else [codes]
        self.log.info(f"BillingFeature: Emitting result codes | codes={normalized}")
        self.on_result(normalized)

    def _emit_files(self, files: dict):
        """Fire the uploaded_files callback with the validated DataFrames."""
        if not self.uploaded_files:
            self.log.warning("BillingFeature: uploaded_files callback not wired — files dropped")
            return

        self.log.info(f"BillingFeature: Handing {len(files)} file(s) to Orchestrator")
        self.uploaded_files(files)

    def _emit_progress(self, percent: int, message: str):
        """Fire the on_progress callback to update the UI progress bar."""
        if not self.on_progress:
            return
        self.log.info(f"BillingFeature: Progress | {percent}% — {message}")
        self.on_progress(percent, message)
