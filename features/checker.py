"""
checker.py
----------
CheckerFeature — file collection and validation for the Checker flow.

Responsibilities
----------------
1. Open a native file-picker dialog for the user to select exactly two
   checker Excel files: one Manual Checker and one Unmand Checker.
2. Read each file, decrypting with msoffcrypto when needed.
3. Validate file identity (manual / unmand labels), Employee ID column
   presence, and the existence of a Total row.
4. Emit results back to the Orchestrator via callbacks:
       on_result(codes)        — list of status-code strings for the UI
       uploaded_files(dfs)     — dict of validated DataFrames for variance

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
from difflib import get_close_matches
from pathlib import Path

import msoffcrypto
import pandas as pd
from dotenv import load_dotenv
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QFileDialog

from utils.app_config_user import get
from utils.file_utils import validation_path

# Maximum number of checker files allowed per session
MAX_FILES = 2

# Password format used for encrypted checker files
_PASSWORD_PREFIX = get("PASSWORD_PREFIX","")


class CheckerFeature:
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

        load_dotenv()

    # ===================================================================
    # PUBLIC ENTRY POINT
    # ===================================================================

    def prepare_checker_files(self, id_names: list):
        """
        Start the checker file preparation flow.

        Defers opening the file dialog to the next Qt event loop tick so
        the UI fully settles after the button click before the dialog
        appears — prevents the main window from flashing.

        Parameters
        ----------
        id_names : list[str]
            Expected Employee ID column header variants (from config),
            used for fuzzy matching when normalising the column name.
        """
        self.log.section("CHECKER FILE PREPARATION")
        self.log.info("CheckerFeature: Deferring file dialog to next event loop tick")
        QTimer.singleShot(0, lambda: self._open_and_process(id_names))

    # ===================================================================
    # STEP 1 — OPEN FILE DIALOG + PROCESS
    # ===================================================================

    def _open_and_process(self, id_names: list):
        """
        Open the native file-picker and, if files are selected, run the
        full validation pipeline.

        Called by QTimer.singleShot() — executes after the button click
        has been fully processed by the Qt event loop.

        Parameters
        ----------
        id_names : list[str]
            Employee ID column name variants for fuzzy matching.
        """
        self.log.info("CheckerFeature: Opening file dialog")

        # Parent=None keeps the dialog independent of the main window.
        # Passing the main window as parent caused it to briefly flash.
        file_paths, _ = QFileDialog.getOpenFileNames(
            self.main_window,
            "Select Checker Excel Files",
            "",
            "Excel Files (*.xlsx *.xls)",
        )

        self.log.info(f"CheckerFeature: File dialog closed | selected={len(file_paths)} max={MAX_FILES}")

        # ── Guard: nothing selected ───────────────────────────────────
        if not file_paths:
            self.log.info("CheckerFeature: No files selected — aborting")
            self._emit_result("no_file_error")
            return

        # ── Guard: too many files ─────────────────────────────────────
        if len(file_paths) > MAX_FILES:
            self.log.warning(f"CheckerFeature: Too many files | got={len(file_paths)} max={MAX_FILES}")
            self._emit_result("file_exceed_error")
            return

        self.log.info("CheckerFeature: File count validated — starting processing")
        self._process_files(file_paths, id_names)

    # ===================================================================
    # STEP 2 — FULL VALIDATION PIPELINE
    # ===================================================================

    def _process_files(self, file_paths: list, id_names: list):
        """
        Run the full validation pipeline on the selected files.

        Checks performed (in order)
        ----------------------------
        1. Read / decrypt each file.
        2. Verify both a "manual" and an "unmand" file are present.
        3. Normalise the Employee ID column name.
        4. Check each file has a Total row.

        On success, emits file_success then delegates to uploaded_files().
        On any failure, emits the error codes via on_result().
        """
        dataframes = self._read_files(file_paths)

        # ── Identity check: require both manual and unmand ────────────
        identity_error = self._check_file_identity(dataframes)
        if identity_error:
            self._emit_result(identity_error)
            return

        # ── Structural checks ─────────────────────────────────────────
        self._normalise_employee_id(dataframes, id_names)
        self._check_total_row(dataframes)

        # ── Final error sweep ─────────────────────────────────────────
        self.log.info("CheckerFeature: Final error check across all files")
        error_codes = [
            f"{file}|{status}"
            for file, status in dataframes.items()
            if not isinstance(status, pd.DataFrame)
        ]

        if error_codes:
            self.log.warning(f"CheckerFeature: Validation failed | errors={error_codes}")
            self._emit_result(error_codes)
        else:
            self.log.info("CheckerFeature: All files validated — handing off to Orchestrator")
            self._emit_result("file_success")
            self._emit_files(dataframes)

    # ===================================================================
    # VALIDATION HELPERS
    # ===================================================================

    def _read_files(self, file_paths: list) -> dict:
        """
        Read each selected file into a DataFrame, decrypting if needed.

        Encrypted files are opened with msoffcrypto using the standard
        password.  Files that cannot be read at all are
        stored as "sensitivity_error" for the error sweep.

        Returns
        -------
        dict[str, pd.DataFrame | str]
            Keys are file names (stem only, no directory).
            Values are DataFrames on success, or an error-code string.
        """
        self.log.info(f"CheckerFeature: Reading {len(file_paths)} file(s)")
        dataframes = {}
        year       = datetime.now().year

        for file_path in file_paths:
            # Use pathlib for OS-safe name extraction (fixes the "/" split bug)
            filename = Path(file_path).name

            # ── Attempt unencrypted read ──────────────────────────────
            try:
                df                   = pd.read_excel(file_path, dtype=str)
                dataframes[filename]  = df
                self.log.info(f"CheckerFeature: Read OK | file={filename}")
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
                self.log.info(f"CheckerFeature: Decrypted and read OK | file={filename}")

            except Exception as e:
                self.log.warning(f"CheckerFeature: Failed to read or decrypt |file={filename} error={e}")
                dataframes[filename] = "sensitivity_error"

        return dataframes

    def _check_file_identity(self, dataframes: dict) -> str | None:
        """
        Verify both a Manual and an Unmand checker file are present.

        Matches are case-insensitive substring checks on the file name.

        Returns
        -------
        str or None
            An error-code string if a required file is missing,
            or None if both are present.
        """
        names = [fn.lower() for fn in dataframes]

        has_manual = any("manual" in fn for fn in names)
        has_unmand = any("unmand" in fn for fn in names)

        if not has_manual:
            self.log.warning("CheckerFeature: Manual checker file not found")
            return "manual_error"

        if not has_unmand:
            self.log.warning("CheckerFeature: Unmand checker file not found")
            return "unmand_error"

        self.log.info("CheckerFeature: Both manual and unmand files identified")
        return None

    def _normalise_employee_id(self, dataframes: dict, id_names: list):
        """
        Rename the Employee ID column to the canonical "Employee ID" label.

        Uses fuzzy matching (difflib.get_close_matches, cutoff=0.6) to
        find the best column name match across the expected id_names list.
        Files with no matching column are marked "missing_header_error".
        """
        self.log.info("CheckerFeature: Normalising Employee ID column names")

        for file_, content in dataframes.items():
            if not isinstance(content, pd.DataFrame):
                continue

            found = False
            for id_name in id_names:
                match = get_close_matches(
                    id_name, list(content.columns), n=1, cutoff=0.6
                )
                if match:
                    content.rename(
                        columns={match[0]: "Employee ID"}, inplace=True
                    )
                    self.log.info(
                        f"CheckerFeature: Renamed column | "
                        f"file={file_} from='{match[0]}' to='Employee ID'"
                    )
                    found = True
                    break

            if not found:
                self.log.warning(
                    f"CheckerFeature: No Employee ID column found | file={file_}"
                )
                dataframes[file_] = "missing_header_error"

    def _check_total_row(self, dataframes: dict):
        """
        Verify each file has a "Total" row in the Employee ID column.

        The total row is identified by the Employee ID column containing
        the word "total" (case-insensitive).  Files without it are marked
        "missing_total_error".

        Only files that still hold a DataFrame at this point are checked —
        files already marked with an error string are skipped.
        """
        self.log.info("CheckerFeature: Checking for Total row in each file")

        for file_, content in dataframes.items():
            if not isinstance(content, pd.DataFrame):
                continue
            if "Employee ID" not in content.columns:
                # Column normalisation failed — already marked; skip
                continue

            has_total = (
                content["Employee ID"]
                 .astype(str)
                 .str.lower()
                 .str.contains("total", na=False)
                 .any()
            )

            if has_total:
                self.log.info(
                    f"CheckerFeature: Total row found | file={file_}"
                )
            else:
                self.log.warning(
                    f"CheckerFeature: Missing Total row | file={file_}"
                )
                dataframes[file_] = "missing_total_error"

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
            self.log.warning("CheckerFeature: on_result callback not wired — result dropped")
            return

        normalized = list(codes) if isinstance(codes, (list, tuple)) else [codes]
        self.log.info(f"CheckerFeature: Emitting result codes | codes={normalized}")
        self.on_result(normalized)

    def _emit_files(self, files: dict):
        """
        Fire the uploaded_files callback with the validated DataFrames.

        Parameters
        ----------
        files : dict[str, pd.DataFrame]
            Validated, ready-to-use checker DataFrames.
        """
        if not self.uploaded_files:
            self.log.warning("CheckerFeature: uploaded_files callback not wired — files dropped")
            return

        self.log.info(f"CheckerFeature: Handing {len(files)} file(s) to Orchestrator")
        self.uploaded_files(files)

    def generate(self, files, headers, source, var_tolerance):
        """All pandas variance computation — runs entirely off the main thread."""
        manual_df = None
        unmand_df = None

        for filename, df in files.items():
            fname_lower = filename.lower()
            if "manual" in fname_lower:
                manual_df = df
            elif "unmand" in fname_lower:
                unmand_df = df

        manual_df = manual_df if manual_df is not None else pd.DataFrame()
        unmand_df = unmand_df if unmand_df is not None else pd.DataFrame()

        def _get_totals(df: pd.DataFrame) -> dict:
            if isinstance(df, pd.DataFrame) and "Employee ID" in df.columns:
                mask      = df["Employee ID"].astype(str).str.lower().str.contains("total")
                total_row = df[mask]
                if not total_row.empty:
                    row = total_row.iloc[0]
                    return {h: row[h] if h in df.columns else 0 for h in headers}
            return {h: 0 for h in headers}

        manual_totals = _get_totals(manual_df)
        unmand_totals = _get_totals(unmand_df)

        output = []
        for h in headers:
            m = pd.to_numeric(manual_totals.get(h, 0), errors="coerce")
            u = pd.to_numeric(unmand_totals.get(h, 0), errors="coerce")
            m = 0 if pd.isna(m) else m
            u = 0 if pd.isna(u) else u
            output.append({
                "Payroll Header": h,
                "Manual Checker": m,
                "Unmand Checker": u,
                "Variance":       m - u,
            })

        output_df = pd.DataFrame(output)

        id_col   = "Employee ID"
        detailed = pd.DataFrame()

        if isinstance(manual_df, pd.DataFrame) and isinstance(unmand_df, pd.DataFrame):
            manual_cols = [h for h in headers if h in manual_df.columns]
            unmand_cols = [h for h in headers if h in unmand_df.columns]

            manual_long = manual_df.melt(
                id_vars=[id_col], value_vars=manual_cols,
                var_name="Payroll Header", value_name="Manual Value",
            )
            unmand_long = unmand_df.melt(
                id_vars=[id_col], value_vars=unmand_cols,
                var_name="Payroll Header", value_name="Unmand Value",
            )

            detailed = pd.merge(
                manual_long, unmand_long,
                on=[id_col, "Payroll Header"],
                how="outer",
            )
            detailed["Manual Value"] = pd.to_numeric(
                detailed["Manual Value"], errors="coerce"
            ).fillna(0)
            detailed["Unmand Value"] = pd.to_numeric(
                detailed["Unmand Value"], errors="coerce"
            ).fillna(0)
            detailed["Variance"] = detailed["Manual Value"] - detailed["Unmand Value"]

        manual_count = len(manual_df)
        unmand_count = len(unmand_df)
        accuracy     = (
            (output_df["Variance"].abs() >= var_tolerance).sum() / len(output_df)
            if len(output_df) > 0 else 0
        )
        accuracy_pct = round((1 - accuracy) * 100, 2)

        file_path = (
            validation_path() /
            f"Checker_Variance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )

        today  = datetime.now().strftime("%Y-%m-%d")
        meta_df = pd.DataFrame({
            "Info":  ["Date", "Manual Rows", "Unmand Rows", "Accuracy Rate", "Tolerance"],
            "Value": [today, manual_count, unmand_count, f"{accuracy_pct}%", f"± {var_tolerance}"],
        })

        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            meta_df.to_excel(writer, sheet_name="Variance Report", index=False, startrow=0)
            output_df.to_excel(writer, sheet_name="Variance Report", index=False, startrow=7)
            if not detailed.empty:
                detailed.to_excel(writer, sheet_name="Detailed Variance", index=False)

        return file_path