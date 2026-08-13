"""
additional_tools.py
----------
DarwinToSproutTool — file collection and validation for the DarwinToSprout flow.

Responsibilities
----------------
1. Open a native file-picker dialog for the user to select the DarwinBox raw
   payroll register (single file only).
2. Read the file, decrypting with msoffcrypto when needed.
3. Validate file identity and Employee ID column presence.
4. Convert, format, aggregate, and export a 4-sheet Excel workbook:
       Raw        — original file contents unchanged
       Converted  — payroll columns converted (N.A./0/float → [h]:mm fractions)
       Formatted  — renamed columns per _DETAILS_HEADERS + header_map
       Final      — one row per employee with SUMIF formulas referencing Formatted
5. Emit results back to the Orchestrator via callbacks:
       on_result(codes)       — list of status-code strings for the UI
       uploaded_files(dfs)    — dict of validated DataFrames to Sprout

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
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QFileDialog, QApplication
from utils.app_config_user import get
from utils.file_utils import payroll_app_path, create_path


# Only one file is expected per session
DBXTOSPRT_MAX_FILES = 1

# Password prefix used for encrypted payroll files
_PASSWORD_PREFIX = get("PASSWORD_PREFIX", "")

# String values treated as zero time during conversion
_INVALID_VALUES = {"N.A.", "NA", "na", "-", "", "0", 0}

# Details columns: source name in raw file → display name in output
_DETAILS_HEADERS = {
    "Employee ID":            "Employee ID",
    "Name":                   "Employee Name",
    "Shift Date":             "Shift Date",
    "Shift Name":             "Shift Name",
    "Clockin":                "Clockin",
    "Clockout":                "Clockout",
    "Attendance Policy Name": "Policy",
    "Status":                   "Status",
}

# Excel time-format string; [h] allows totals >= 24 h in the Final sheet
_TIME_FORMAT = "[h]:mm"

# Sheets that require [h]:mm formatting on numeric columns
_TIME_SHEETS = {"Converted", "Formatted", "Final"}


class DarwinToSproutTool:
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

        load_dotenv()

    # ===================================================================
    # PUBLIC ENTRY POINT
    # ===================================================================

    def prepare_darwinbox_payroll(self, id_names: list):
        """
        Start the DarwinBox payroll preparation flow.

        Defers opening the file dialog to the next Qt event loop tick so
        the UI fully settles after the button click before the dialog
        appears — prevents the main window from flashing.

        Parameters
        ----------
        id_names : list[str]
            Expected Employee ID column header variants (from config),
            used for fuzzy matching when normalising the column name.
        """
        self.log.section("DARWINBOX FILE PREPARATION")
        self.log.info("DarwinToSproutTool: Deferring file dialog to next event loop tick")
        QTimer.singleShot(0, lambda: self._open_and_process(id_names))

    # ===================================================================
    # STEP 1 — OPEN FILE DIALOG
    # ===================================================================

    def _open_and_process(self, id_names: list):
        """
        Open the native file-picker and, if a file is selected, run the
        full validation pipeline.

        Called by QTimer.singleShot() — executes after the button click
        has been fully processed by the Qt event loop.

        Parameters
        ----------
        id_names : list[str]
            Employee ID column name variants for fuzzy matching.
        """
        self.log.info("DarwinToSproutTool: Opening file dialog")
        self._emit_progress(0, "Selecting file...")


        # Parent=None keeps the dialog independent of the main window.
        # Passing the main window as parent caused it to briefly flash.
        file_paths, _ = QFileDialog.getOpenFileNames(
            self.main_window,
            "Select DarwinBox Payroll File",
            "",
            "Excel Files (*.xlsx *.xls)",
        )

        self.log.info(
            f"DarwinToSproutTool: File dialog closed | "
            f"selected={len(file_paths)} max={DBXTOSPRT_MAX_FILES}"
        )

        # ── Guard: nothing selected ───────────────────────────────────
        if not file_paths:
            self.log.info("DarwinToSproutTool: No file selected — aborting")
            self._emit_result("no_file_error")
            return

        # ── Guard: more than one file ─────────────────────────────────
        if len(file_paths) > DBXTOSPRT_MAX_FILES:
            self.log.warning(
                f"DarwinToSproutTool: Too many files selected | "
                f"got={len(file_paths)} max={DBXTOSPRT_MAX_FILES}"
            )
            self._emit_result("file_exceed_error")
            return

        self.log.info("DarwinToSproutTool: File count validated — starting processing")
        self._process_payroll(file_paths[0], id_names)

    # ===================================================================
    # STEP 2 — VALIDATION PIPELINE
    # ===================================================================

    def _process_payroll(self, file_path: str, id_names: list):
        """
        Run the full validation pipeline on the selected file.

        Checks performed (in order)
        ----------------------------
        1. Read / decrypt the file.
        2. Normalise the Employee ID column name.

        On success, emits file_success then delegates to uploaded_files().
        On any failure, emits the error code via on_result().

        Parameters
        ----------
        file_path : str
            Absolute path to the selected Excel file.
        id_names  : list[str]
            Employee ID column name variants for fuzzy matching.
        """

        filename, df = self._read_payroll(file_path)

        if not isinstance(df, pd.DataFrame):
            self.log.warning(
                f"DarwinToSproutTool: Aborting — file could not be read | "
                f"file={filename} error={df}"
            )
            self._emit_result(f"{filename}|{df}")
            return

        self._emit_progress(8, "Normalising employee ids...")
        df = self._normalise_employee_id(df, filename, id_names)

        if not isinstance(df, pd.DataFrame):
            self.log.warning(
                f"DarwinToSproutTool: Aborting — validation failed | "
                f"file={filename} error={df}"
            )
            self._emit_result(f"{filename}|{df}")
            return

        self.log.info(
            f"DarwinToSproutTool: File validated — handing off to Orchestrator | "
            f"file={filename}"
        )
        self._emit_result("file_success")
        self._emit_payroll({filename: df})

    # ===================================================================
    # VALIDATION HELPERS
    # ===================================================================

    def _read_payroll(self, file_path: str):
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

        self._emit_progress(5, f"Reading {filename}")
        QApplication.processEvents()

        self.log.info(f"DarwinToSproutTool: Reading file | file={filename}")

        # ── Attempt unencrypted read ──────────────────────────────────
        try:
            df = pd.read_excel(file_path, dtype=str)
            self.log.info(
                f"DarwinToSproutTool: Read OK (unencrypted) | "
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
                f"DarwinToSproutTool: Read OK (decrypted) | "
                f"file={filename} rows={len(df)} cols={len(df.columns)}"
            )
            return filename, df

        except Exception as e:
            self.log.warning(
                f"DarwinToSproutTool: Failed to read or decrypt | "
                f"file={filename} error={e}"
            )
            return filename, "sensitivity_error"

    def _normalise_employee_id(
        self, df: pd.DataFrame, filename: str, id_names: list
    ):
        """
        Rename the Employee ID column to the canonical "Employee ID" label.

        Uses fuzzy matching (difflib.get_close_matches, cutoff=0.6) to find
        the best column name match across the expected id_names list.

        Parameters
        ----------
        df       : pd.DataFrame
        filename : str           — used for logging only
        id_names : list[str]
            Expected Employee ID header variants.

        Returns
        -------
        pd.DataFrame | str
            Updated DataFrame on success, "missing_header_error" if no
            matching column is found.
        """
        self.log.info(
            f"DarwinToSproutTool: Normalising Employee ID column | file={filename}"
        )

        for id_name in id_names:
            match = get_close_matches(id_name, list(df.columns), n=1, cutoff=0.6)
            if match:
                df.rename(columns={match[0]: "Employee ID"}, inplace=True)
                self.log.info(
                    f"DarwinToSproutTool: Renamed Employee ID column | "
                    f"file={filename} from='{match[0]}' to='Employee ID'"
                )
                return df

        self.log.warning(
            f"DarwinToSproutTool: No Employee ID column found | file={filename}"
        )
        return "missing_header_error"

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
                "DarwinToSproutTool: on_result callback not wired — result dropped"
            )
            return

        normalized = list(codes) if isinstance(codes, (list, tuple)) else [codes]
        self.log.info(
            f"DarwinToSproutTool: Emitting result codes | codes={normalized}"
        )
        self.on_result(normalized)

    def _emit_payroll(self, files: dict):
        """
        Fire the uploaded_files callback with the validated DataFrame.

        Parameters
        ----------
        files : dict[str, pd.DataFrame]
            Single-entry dict of the validated, ready-to-use DataFrame.
        """
        if not self.uploaded_files:
            self.log.warning(
                "DarwinToSproutTool: uploaded_files callback not wired — files dropped"
            )
            return

        self.log.info(
            f"DarwinToSproutTool: Handing file to Orchestrator | "
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
            f"DarwinToSproutTool: Progress | {percent}% — {message}"
        )
        self.on_progress(percent, message)

    # ===================================================================
    # GENERATE — PUBLIC ENTRY POINT CALLED BY ORCHESTRATOR
    # ===================================================================

    def generate(self, files: dict, header_map: dict) -> str:
        """
        Build and export the 4-sheet output workbook.

        Expects exactly one file in `files`.

        Sheet layout
        ------------
        Raw       — original file contents, no changes
        Converted — payroll columns converted to [h]:mm Excel fractions
        Formatted — selected + renamed columns (details + payroll)
        Final     — one row per employee; payroll totals via SUMIF formulas
                    referencing the Formatted sheet (live — edits flow through)

        Parameters
        ----------
        files      : dict[str, pd.DataFrame]
            Single validated file from the Orchestrator.
        header_map : dict[str, str]
            Payroll source column → display/target column name mapping.

        Returns
        -------
        str
            Absolute path to the exported Excel workbook.
        """
        self.log.section("DARWINBOX PAYROLL GENERATION")

        filename, raw_df = next(iter(files.items()))
        self.log.info(
            f"DarwinToSproutTool: Starting generation | "
            f"file={filename} rows={len(raw_df)} cols={len(raw_df.columns)}"
        )

        self._emit_progress(10, "Reading complete — converting values…")
        converted_df = self._convert_values(raw_df.copy(), header_map, filename)

        self._emit_progress(20, "Formatting columns…")
        formatted_df = self._format_payroll(converted_df, header_map, filename)

        self._emit_progress(30, "Building employee list…")
        final_df     = self._build_employee_list(formatted_df, filename)

        self._emit_progress(45, "Writing workbook…")

        sheets = {
            "Raw":       raw_df,
            "Converted": converted_df,
            "Formatted": formatted_df,
            "Final":     final_df,
        }

        output_path = self.export_to_excel(sheets, formatted_df, filename)
        self.log.info(
            f"DarwinToSproutTool: Generation complete | path={output_path}"
        )
        return output_path

    # ===================================================================
    # STEP A — CONVERT VALUES (vectorised)
    # ===================================================================

    def _convert_values(
        self, df: pd.DataFrame, header_map: dict, filename: str
    ) -> pd.DataFrame:
        """
        Convert payroll columns to Excel time fractions.

        Conversion rules
        ----------------
        - N.A. / NA / na / "-" / NaN / 0  →  0.0
        - "H:MM:SS" / "HH:MM:SS" / "H:MM" → Excel time
        (seconds are ignored)
        - Decimal hours (e.g. 6.85) → Excel time
        """

        self.log.info(
            f"DarwinToSproutTool: Converting payroll columns | file={filename}"
        )

        payroll_cols = {col.strip() for col in header_map}
        converted = 0
        skipped = 0

        for col in df.columns:
            if col.strip() not in payroll_cols:
                skipped += 1
                continue

            s = df[col].astype(str).str.strip()

            # 1. Invalid values
            invalid_mask = s.isin(_INVALID_VALUES) | (s.str.lower() == "nan")

            # 2. Parse numeric values (decimal hours)
            numeric = pd.to_numeric(s, errors="coerce")

            # Preserve which rows are time strings
            time_str_mask = numeric.isna() & ~invalid_mask

            # 3. Parse HH:MM[:SS] strings
            if time_str_mask.any():
                parts = (
                    s.loc[time_str_mask]
                    .str.split(":", expand=True)
                    .reindex(columns=[0, 1, 2], fill_value="0")
                )

                h = pd.to_numeric(parts[0], errors="coerce").fillna(0)
                m = pd.to_numeric(parts[1], errors="coerce").fillna(0)

                # Seconds intentionally ignored
                total_minutes = h * 60 + m

                numeric.loc[time_str_mask] = total_minutes / 1440

            # 4. Convert ONLY decimal-hour values
            decimal_mask = (
                numeric.notna()
                & ~time_str_mask
                & ~invalid_mask
                & (numeric != 0)
            )

            numeric.loc[decimal_mask] = (
                numeric.loc[decimal_mask] * 60
            ).round() / 1440

            # 5. Invalid / zero values become 0
            numeric = numeric.where(
                numeric.notna() & ~invalid_mask,
                0.0
            ).astype(float)

            df[col] = numeric
            converted += 1

            self.log.info(
                f"DarwinToSproutTool: Converted column | "
                f"file={filename} col='{col}'"
            )

        self.log.info(
            f"DarwinToSproutTool: Conversion complete | "
            f"file={filename} converted={converted} skipped={skipped}"
        )

        return df

    # ===================================================================
    # STEP B — FORMAT (SELECT + RENAME COLUMNS)
    # ===================================================================

    def _format_payroll(
        self, df: pd.DataFrame, header_map: dict, filename: str
    ) -> pd.DataFrame:
        """
        Select and rename columns into the output layout:
          1. Detail columns  (_DETAILS_HEADERS) — identity / shift metadata.
          2. Payroll columns (header_map)        — converted time fractions.

        Columns absent from the source file are warned and skipped.

        Parameters
        ----------
        df         : pd.DataFrame  — converted DataFrame
        header_map : dict[str, str]
        filename   : str           — used for logging only

        Returns
        -------
        pd.DataFrame
        """
        self.log.info(
            f"DarwinToSproutTool: Formatting columns | file={filename}"
        )

        # stripped name → original name, for whitespace-safe lookup
        col_index = {c.strip(): c for c in df.columns}
        cols      = {}   # accumulate here; single DataFrame() call at end

        # ── Detail columns ────────────────────────────────────────────
        for src, tgt in _DETAILS_HEADERS.items():
            if src in col_index:
                cols[tgt] = df[col_index[src]].values
                self.log.info(
                    f"DarwinToSproutTool: Mapped detail column | "
                    f"file={filename} '{src}' → '{tgt}'"
                )
            else:
                self.log.warning(
                    f"DarwinToSproutTool: Detail column not found — skipped | "
                    f"file={filename} col='{src}'"
                )

        # ── Payroll columns ───────────────────────────────────────────
        mapped   = 0
        unmapped = 0
        for src, tgt in header_map.items():
            if src in col_index:
                cols[tgt] = df[col_index[src]].values
                mapped += 1
            else:
                self.log.warning(
                    f"DarwinToSproutTool: Payroll column not found — skipped | "
                    f"file={filename} col='{src}'"
                )
                unmapped += 1

        new_df = pd.DataFrame(cols, index=df.index)

        self.log.info(
            f"DarwinToSproutTool: Formatting complete | "
            f"file={filename} payroll_mapped={mapped} payroll_skipped={unmapped}"
        )
        return new_df

    # ===================================================================
    # STEP C — BUILD EMPLOYEE LIST (for Final sheet row index)
    # ===================================================================

    def _build_employee_list(
        self, df: pd.DataFrame, filename: str
    ) -> pd.DataFrame:
        """
        Extract unique Employee ID + Employee Name pairs from the Formatted
        sheet.  This becomes the row index of the Final sheet; the payroll
        totals are written as SUMIF formulas by export_to_excel so they
        remain live and update when the Formatted sheet is edited.

        Parameters
        ----------
        df       : pd.DataFrame  — formatted DataFrame
        filename : str           — used for logging only

        Returns
        -------
        pd.DataFrame
            Columns: ["Employee ID", "Employee Name"] (one row per employee).
        """
        self.log.info(
            f"DarwinToSproutTool: Building unique employee list for Final sheet | "
            f"file={filename}"
        )

        group_cols = [c for c in ["Employee ID", "Employee Name"] if c in df.columns]

        if not group_cols:
            self.log.warning(
                f"DarwinToSproutTool: No grouping columns found — "
                f"returning empty Final sheet | file={filename}"
            )
            return pd.DataFrame()

        unique_employees = (
            df[group_cols]
            .drop_duplicates()
            .reset_index(drop=True)
        )

        self.log.info(
            f"DarwinToSproutTool: Unique employees found | "
            f"file={filename} count={len(unique_employees)}"
        )
        return unique_employees

    # ===================================================================
    # EXPORT (optimised — no re-open, SUMIF formulas for Final sheet)
    # ===================================================================

    def export_to_excel(
        self,
        sheets:        dict,
        formatted_df:  pd.DataFrame,
        source_filename: str = ""
    ) -> str:
        """
        Write all four sheets to one workbook.

        Raw       — written as-is, no formatting applied.
        Converted — [h]:mm format applied to all float columns.
        Formatted — [h]:mm format applied to all float columns.
        Final     — employee list written first; payroll column headers and
                    SUMIF formulas then injected by _write_final_formulas().

        Optimisation notes
        ------------------
        - Worksheet objects are grabbed directly from the ExcelWriter context
          (writer.sheets[name]) — no load_workbook() re-open after saving.
        - Time columns are detected from DataFrame dtypes, not by scanning
          cells, so no O(rows × cols) type-probe loop is needed.
        - The Alignment object is created once and reused across all cells.

        Parameters
        ----------
        sheets           : dict[str, pd.DataFrame]
            Keys: "Raw", "Converted", "Formatted", "Final".
        formatted_df     : pd.DataFrame
            The Formatted sheet's DataFrame — needed by _write_final_formulas
            to resolve column letters for SUMIF range references.
        source_filename  : str
            Original uploaded file name, used for logging only.
        output_path      : str
            Destination path for the output workbook.

        Returns
        -------
        str
            The output_path that was written.
        """

        output_path = create_path(payroll_app_path() / "Tools") / f"DarwinBox_to_Sprout_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    

        self.log.info(
            f"DarwinToSproutTool: Exporting workbook | "
            f"source={source_filename} path={output_path} "
            f"sheets={list(sheets.keys())}"
        )


        final_df     = sheets.get("Final", pd.DataFrame())
        align_centre = Alignment(horizontal="center")

        # Pre-compute per-sheet progress checkpoints (65–94 %)
        _sheet_progress = {
            "Raw":       55,
            "Converted": 65,
            "Formatted": 75,
            "Final":     85,
        }

        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:

            for sheet_name, df in sheets.items():
                self._emit_progress(
                    _sheet_progress.get(sheet_name, 70),
                    f"Writing sheet: {sheet_name}…"
                )

                df.to_excel(writer, sheet_name=sheet_name, index=False)
                self.log.info(
                    f"DarwinToSproutTool: Wrote sheet | "
                    f"sheet='{sheet_name}' rows={len(df)} cols={len(df.columns)}"
                )

                # Raw sheet — no time formatting needed
                if sheet_name not in _TIME_SHEETS:
                    continue

                ws = writer.sheets[sheet_name]

                # Detect time columns from dtype — avoids scanning 16k cells
                time_col_indices = [
                    col_idx
                    for col_idx, col_name in enumerate(df.columns, start=1)
                    if pd.api.types.is_float_dtype(df[col_name])
                ]

                # Final sheet payroll columns are not in final_df yet
                # (they will be written as formulas below) — skip format pass
                # here; _write_final_formulas handles Final formatting itself.
                if sheet_name == "Final":
                    continue

                for col_idx in time_col_indices:
                    for row_idx in range(2, len(df) + 2):  # +2: 1-based + header
                        cell               = ws.cell(row=row_idx, column=col_idx)
                        cell.number_format = _TIME_FORMAT
                        cell.alignment     = align_centre

                self.log.info(
                    f"DarwinToSproutTool: Applied time format | "
                    f"sheet='{sheet_name}' time_columns={len(time_col_indices)}"
                )

            # ── Inject SUMIF formulas into Final sheet ────────────────
            if not formatted_df.empty and not final_df.empty:
                self._write_final_formulas(
                    writer, formatted_df, final_df, align_centre
                )

        self.log.info(
            f"DarwinToSproutTool: Workbook saved | path={output_path}"
        )
        self._emit_progress(100, "Done")
        return output_path

    # ===================================================================
    # FINAL SHEET — SUMIF FORMULA WRITER
    # ===================================================================

    def _write_final_formulas(
        self,
        writer:       "pd.ExcelWriter",
        formatted_df: pd.DataFrame,
        final_df:     pd.DataFrame,
        align_centre: Alignment,
    ):
        """
        Inject payroll column headers and SUMIF formulas into the Final sheet.

        Formula pattern (per payroll cell)
        ------------------------------------
        =SUMIF(Formatted!$A:$A, Final!$A2, Formatted!$C:$C)
                ^^ Employee ID col ^^       ^^ payroll col ^^

        The Employee ID column in Formatted is used as the criteria range.
        Each Final row matches on its own Employee ID cell (locked column,
        relative row).  The sum range is the corresponding payroll column
        in Formatted.

        When a value is edited in the Formatted sheet, the matching Final
        cell recalculates automatically — no macros or VBA required.

        Parameters
        ----------
        writer       : pd.ExcelWriter  — still open inside the with-block
        formatted_df : pd.DataFrame    — the Formatted sheet's DataFrame
        final_df     : pd.DataFrame    — employee list (ID + Name only)
        align_centre : Alignment       — shared openpyxl Alignment object
        """
        ws_final  = writer.sheets["Final"]
        fmt_cols  = list(formatted_df.columns)

        # ── Locate Employee ID column in Formatted ────────────────────
        if "Employee ID" not in fmt_cols:
            self.log.warning(
                "DarwinToSproutTool: 'Employee ID' not found in Formatted — "
                "SUMIF formulas cannot be written"
            )
            return

        emp_id_col_idx    = fmt_cols.index("Employee ID") + 1  # 1-based
        emp_id_col_letter = get_column_letter(emp_id_col_idx)

        # ── Identify payroll columns (float dtype) in Formatted ───────
        payroll_col_map = {
            col_name: get_column_letter(col_idx)
            for col_idx, col_name in enumerate(fmt_cols, start=1)
            if pd.api.types.is_float_dtype(formatted_df[col_name])
        }

        # Payroll targets not already in final_df (ID + Name are already written)
        final_cols      = list(final_df.columns)
        payroll_targets = [c for c in payroll_col_map if c not in final_cols]

        # ── Write payroll headers in Final row 1 ─────────────────────
        header_start_col = len(final_cols) + 1   # column after ID + Name
        for offset, col_name in enumerate(payroll_targets):
            ws_final.cell(
                row=1, column=header_start_col + offset
            ).value = col_name

        self.log.info(
            f"DarwinToSproutTool: Writing SUMIF formulas into Final sheet | "
            f"employees={len(final_df)} payroll_cols={len(payroll_targets)}"
        )

        # ── Write SUMIF formula per employee row × payroll column ─────
        for row_idx in range(2, len(final_df) + 2):   # +2: 1-based + header

            # Criteria ref: locked column, relative row (e.g. $A2)
            criteria_ref = f"${get_column_letter(1)}{row_idx}"

            for offset, col_name in enumerate(payroll_targets):
                fmt_col_letter = payroll_col_map[col_name]
                final_col_idx  = header_start_col + offset

                # =SUMIF(Formatted!$A:$A, Final!$A2, Formatted!$C:$C)
                formula = (
                    f"=SUMIF("
                    f"Formatted!${emp_id_col_letter}:${emp_id_col_letter},"
                    f"Final!{criteria_ref},"
                    f"Formatted!${fmt_col_letter}:${fmt_col_letter}"
                    f")"
                )

                cell               = ws_final.cell(row=row_idx, column=final_col_idx)
                cell.value         = formula
                cell.number_format = _TIME_FORMAT
                cell.alignment     = align_centre

        self.log.info(
            f"DarwinToSproutTool: SUMIF formulas written | "
            f"employees={len(final_df)} payroll_cols={len(payroll_targets)}"
        )
