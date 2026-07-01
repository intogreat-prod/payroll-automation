"""
attendance_summary.py
---------------------
AttendanceSummaryTool — file collection and validation for the Attendance Summary flow.

Responsibilities
----------------
1. Open a native file-picker dialog for the user to select the attendance file
   (single file only).
2. Read the file, decrypting with msoffcrypto when needed.
3. Validate the file can be read successfully.
4. Emit results back to the Orchestrator via callbacks:
       on_result(codes)       — list of status-code strings for the UI
       uploaded_files(dfs)    — dict of validated DataFrames to the Orchestrator

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
from datetime import datetime
from pathlib import Path

import msoffcrypto
import pandas as pd
from dotenv import load_dotenv
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QFileDialog

from utils.app_config_user import get


# Only one file is expected per session
ATTENDANCE_MAX_FILES = 1

# Password prefix used for encrypted files
_PASSWORD_PREFIX = get("PASSWORD_PREFIX", "")


class AttendanceSummaryTool:
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

        self._start_date  = ""
        self._cutoff_date = ""

        load_dotenv()

    # ===================================================================
    # PUBLIC ENTRY POINT
    # ===================================================================

    def prepare_attendance_file(self, start_date: str = "", cutoff_date: str = ""):
        """
        Start the Attendance Summary file preparation flow.

        Parameters
        ----------
        start_date  : str  ISO date string (yyyy-MM-dd) for the period start.
        cutoff_date : str  ISO date string (yyyy-MM-dd) for the period cutoff.

        Defers opening the file dialog to the next Qt event loop tick so
        the UI fully settles after the button click before the dialog
        appears — prevents the main window from flashing.
        """
        self._start_date  = start_date
        self._cutoff_date = cutoff_date
        self.log.section("ATTENDANCE SUMMARY FILE PREPARATION")
        self.log.info("AttendanceSummaryTool: Deferring file dialog to next event loop tick")
        QTimer.singleShot(0, self._open_and_process)

    # ===================================================================
    # STEP 1 — OPEN FILE DIALOG
    # ===================================================================

    def _open_and_process(self):
        """
        Open the native file-picker and, if a file is selected, run the
        full validation pipeline.

        Called by QTimer.singleShot() — executes after the button click
        has been fully processed by the Qt event loop.
        """
        self.log.info("AttendanceSummaryTool: Opening file dialog")

        # ── Guard: validate date range ────────────────────────────────
        if self._start_date and self._cutoff_date:
            try:
                start  = datetime.strptime(self._start_date,  "%Y-%m-%d")
                cutoff = datetime.strptime(self._cutoff_date, "%Y-%m-%d")
                if start > cutoff:
                    self.log.warning(
                        f"AttendanceSummaryTool: Invalid date range | "
                        f"start={self._start_date} cutoff={self._cutoff_date}"
                    )
                    self._emit_result("date_range_error")
                    return
                if start == cutoff:
                    self.log.warning("AttendanceSummaryTool: Start and cutoff dates are the same")
                    self._emit_result("date_same_error")
                    return
            except ValueError as e:
                self.log.warning(f"AttendanceSummaryTool: Date parse error | {e}")
                self._emit_result("date_format_error")
                return

        # Parent=None keeps the dialog independent of the main window.
        # Passing the main window as parent caused it to briefly flash.
        file_paths, _ = QFileDialog.getOpenFileNames(
            self.main_window,
            "Select Attendance File",
            "",
            "Excel Files (*.xlsx *.xls)",
        )

        self.log.info(
            f"AttendanceSummaryTool: File dialog closed | "
            f"selected={len(file_paths)} max={ATTENDANCE_MAX_FILES}"
        )

        # ── Guard: nothing selected ───────────────────────────────────
        if not file_paths:
            self.log.info("AttendanceSummaryTool: No file selected — aborting")
            self._emit_result("no_file_error")
            return

        # ── Guard: more than one file ─────────────────────────────────
        if len(file_paths) > ATTENDANCE_MAX_FILES:
            self.log.warning(
                f"AttendanceSummaryTool: Too many files selected | "
                f"got={len(file_paths)} max={ATTENDANCE_MAX_FILES}"
            )
            self._emit_result("file_exceed_error")
            return

        self.log.info("AttendanceSummaryTool: File count validated — starting processing")
        self._process_file(file_paths[0])

    # ===================================================================
    # STEP 2 — VALIDATION PIPELINE
    # ===================================================================

    def _process_file(self, file_path: str):
        """
        Run the full validation pipeline on the selected file.

        Checks performed (in order)
        ----------------------------
        1. Read / decrypt the file.

        On success, emits file_success then delegates to uploaded_files().
        On any failure, emits the error code via on_result().

        Parameters
        ----------
        file_path : str
            Absolute path to the selected Excel file.
        """
        self._emit_progress(10, "Reading attendance file…")
        filename, df = self._read_file(file_path)

        if not isinstance(df, pd.DataFrame):
            self.log.warning(
                f"AttendanceSummaryTool: Aborting — file could not be read | "
                f"file={filename} error={df}"
            )
            self._emit_result(f"{filename}|{df}")
            return

        self._emit_progress(80, "Validating file structure…")
        self.log.info(
            f"AttendanceSummaryTool: File validated — handing off to Orchestrator | "
            f"file={filename}"
        )
        self._emit_progress(100, "Ready.")
        self._emit_result("file_success")
        self._emit_files({filename: df})

    # ===================================================================
    # READ HELPER
    # ===================================================================

    def _read_file(self, file_path: str):
        """
        Read the selected file into a DataFrame, decrypting if needed.

        Encrypted files are opened with msoffcrypto using the standard
        password ({PREFIX}{year}).  Files that cannot be read at all are
        returned with a "sensitivity_error" code.

        Parameters
        ----------
        file_path : str
            Absolute path to the Excel file.

        Returns
        -------
        tuple[str, pd.DataFrame | str]
            (filename, DataFrame) on success.
            (filename, "sensitivity_error") if the file cannot be read.
        """
        filename = Path(file_path).name
        year     = datetime.now().year

        self.log.info(f"AttendanceSummaryTool: Reading file | file={filename}")

        # ── Attempt unencrypted read ──────────────────────────────────
        try:
            df = pd.read_excel(file_path, dtype=str)
            self.log.info(
                f"AttendanceSummaryTool: Read OK (unencrypted) | "
                f"file={filename} rows={len(df)} cols={len(df.columns)}"
            )
            return filename, df
        except Exception:
            pass  # fall through to decryption attempt

        # ── Attempt decrypted read ────────────────────────────────────
        try:
            password  = f"{_PASSWORD_PREFIX}{year}"
            decrypted = io.BytesIO()

            with open(file_path, "rb") as f:
                office_file = msoffcrypto.OfficeFile(f)
                office_file.load_key(password=password)
                office_file.decrypt(decrypted)

            decrypted.seek(0)
            df = pd.read_excel(decrypted, dtype=str)
            self.log.info(
                f"AttendanceSummaryTool: Read OK (decrypted) | "
                f"file={filename} rows={len(df)} cols={len(df.columns)}"
            )
            return filename, df

        except Exception as e:
            self.log.warning(
                f"AttendanceSummaryTool: Failed to read or decrypt | "
                f"file={filename} error={e}"
            )
            return filename, "sensitivity_error"

    # ===================================================================
    # GENERATION (called by _AttendanceSummaryWorker)
    # ===================================================================

    def generate(self, files: dict, start_date: str, cutoff_date: str):
        """
        Process the validated attendance DataFrame and produce the summary
        Excel output.

        Parameters
        ----------
        files       : dict[str, pd.DataFrame]
            Single-entry dict from uploaded_files callback.
        start_date  : str  ISO date (yyyy-MM-dd) — period start.
        cutoff_date : str  ISO date (yyyy-MM-dd) — period cutoff.

        Returns
        -------
        Path
            Local path to the generated summary Excel file.
        """
        from pathlib import Path
        from datetime import datetime

        self._emit_progress(10, "Loading attendance data…")
        df = next(iter(files.values()))

        self._emit_progress(30, f"Filtering {start_date} → {cutoff_date}…")

        # ── Filter by date range ──────────────────────────────────────
        # Attempt to find a date column (common DarwinBox column names)
        date_col = None
        for candidate in ("Date", "date", "Attendance Date", "attendance_date"):
            if candidate in df.columns:
                date_col = candidate
                break

        if date_col:
            try:
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                start  = pd.to_datetime(start_date)
                cutoff = pd.to_datetime(cutoff_date)
                df = df[(df[date_col] >= start) & (df[date_col] <= cutoff)]
                self.log.info(
                    f"AttendanceSummaryTool: Filtered by date range | "
                    f"rows={len(df)} start={start_date} cutoff={cutoff_date}"
                )
            except Exception as e:
                self.log.warning(f"AttendanceSummaryTool: Date filter failed | {e}")
        else:
            self.log.warning("AttendanceSummaryTool: No recognised date column found — skipping filter")

        self._emit_progress(60, "Calculating attendance metrics…")

        # ── Build summary ─────────────────────────────────────────────
        # Identify employee-id column
        emp_col = None
        for candidate in ("Employee ID", "EmployeeID", "Emp ID", "emp_id", "employee_id"):
            if candidate in df.columns:
                emp_col = candidate
                break

        if emp_col:
            summary = df.groupby(emp_col).size().reset_index(name="Total Days")
        else:
            summary = df.copy()

        self._emit_progress(85, "Writing output file…")

        # ── Write Excel ───────────────────────────────────────────────
        from utils.file_utils import app_data_path
        import os

        out_dir = Path(app_data_path()) / "validation"
        out_dir.mkdir(parents=True, exist_ok=True)

        stamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"attendance_summary_{start_date}_{cutoff_date}_{stamp}.xlsx"

        summary.to_excel(out_path, index=False)
        self.log.info(f"AttendanceSummaryTool: Output written | path={out_path}")

        self._emit_progress(100, "Done.")
        return out_path

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
            self.log.warning(
                "AttendanceSummaryTool: on_result callback not wired — result dropped"
            )
            return

        normalized = list(codes) if isinstance(codes, (list, tuple)) else [codes]
        self.log.info(
            f"AttendanceSummaryTool: Emitting result codes | codes={normalized}"
        )
        self.on_result(normalized)

    def _emit_files(self, files: dict):
        """
        Fire the uploaded_files callback with the validated DataFrame.

        Parameters
        ----------
        files : dict[str, pd.DataFrame]
            Single-entry dict of the validated, ready-to-use DataFrame.
        """
        if not self.uploaded_files:
            self.log.warning(
                "AttendanceSummaryTool: uploaded_files callback not wired — files dropped"
            )
            return

        self.log.info(
            f"AttendanceSummaryTool: Handing file to Orchestrator | "
            f"files={list(files.keys())}"
        )
        self.uploaded_files(files)

    def _emit_progress(self, percent: int, message: str):
        """
        Fire the on_progress callback to update the UI progress bar.

        Parameters
        ----------
        percent : int
            Completion percentage (0–100).
        message : str
            Short human-readable label for the current stage.
        """
        if not self.on_progress:
            return
        self.log.info(
            f"AttendanceSummaryTool: Progress | {percent}% — {message}"
        )
        self.on_progress(percent, message)
