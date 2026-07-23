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
from PyQt6.QtWidgets import QFileDialog, QApplication

from utils.app_config_user import get
from utils.file_utils import att_summary_path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


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
        self._emit_progress(2, "Validating Attendance Period...")
        QApplication.processEvents()
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
        self._emit_progress(5, "Selecting File...")
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
        self._emit_progress(10, f"Reading {filename}")
        QApplication.processEvents()


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
        self._emit_progress(10, "Loading attendance data…")
        df = next(iter(files.values()))

        self._emit_progress(30, f"Filtering {start_date} → {cutoff_date}…")
        df = self._filter_by_date_range(df, start_date, cutoff_date)

        self._emit_progress(50, "Checking required columns…")

        # ── Guard: required Unmand columns ────────────────────────────
        required_cols = ("Late By", "Early Clock Out By")
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            self.log.warning(
                f"AttendanceSummaryTool: Missing required columns | missing={missing}"
            )
            self._emit_result(f"missing_columns_error|{','.join(missing)}")
            return None

        self._emit_progress(60, "Computing Unmand columns…")
        df = self._compute_unmand_columns(df)

        self._emit_progress(75, "Building pivot sheets…")

        # ── Write Excel ──────────────────────────────────────────────
        stamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = att_summary_path() / f"Attendance_Summary_{start_date}_{cutoff_date}_{stamp}.xlsx"

        self._write_workbook(df, out_path, start_date, cutoff_date)
        self.log.info(f"AttendanceSummaryTool: Output written | path={out_path}")

        self._emit_progress(100, "Done.")
        return out_path

    # ===================================================================
    # EXCEL WORKBOOK WRITER
    # ===================================================================

    def _write_workbook(
        self,
        df: pd.DataFrame,
        out_path: Path,
        start_date: str,
        cutoff_date: str,
    ) -> None:
        """
        Write the three-sheet workbook:

        Sheet 1  "{start_date} - {cutoff_date}"
            Raw attendance data with autofilter on row 1.

        Sheet 2  "Attendance Summary"
            Pivot: rows=Employee Id, columns=Status_Unmand values,
            values=count of Detailed Status.

        Sheet 3  "Late Undertime Summary"
            Pivot: rows=Employee Id + Employee Name,
            columns=Late By_Unmand | Early Clock Out By_Unmand | Total,
            values=sum of each.

        Parameters
        ----------
        df          : pd.DataFrame  Processed attendance DataFrame.
        out_path    : Path          Destination .xlsx path.
        start_date  : str           ISO date (yyyy-MM-dd) — period start.
        cutoff_date : str           ISO date (yyyy-MM-dd) — period cutoff.
        """

        wb = Workbook()
        wb.remove(wb.active)   # drop the default empty sheet

        # ── Shared style helpers ──────────────────────────────────────
        _HEADER_FONT   = Font(bold=True, color="FFFFFF")
        _HEADER_FILL   = PatternFill("solid", fgColor="203864")   # dark navy
        _SUBHDR_FILL   = PatternFill("solid", fgColor="2F75B6")   # mid blue
        _TOTAL_FILL    = PatternFill("solid", fgColor="D6E4F7")   # light blue
        _THIN          = Side(style="thin", color="B8B8B8")
        _BORDER        = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
        _CENTER        = Alignment(horizontal="center", vertical="center", wrap_text=True)
        _LEFT          = Alignment(horizontal="left",   vertical="center")
        _RIGHT         = Alignment(horizontal="right",  vertical="center")

        def _style_header_cell(cell, *, fill=None):
            cell.font      = _HEADER_FONT
            cell.fill      = fill or _HEADER_FILL
            cell.alignment = _CENTER
            cell.border    = _BORDER

        def _style_data_cell(cell, align=None):
            cell.border    = _BORDER
            cell.alignment = align or _LEFT

        def _auto_width(ws, min_w=8, max_w=40):
            for col_cells in ws.columns:
                length = max(
                    len(str(c.value)) if c.value is not None else 0
                    for c in col_cells
                )
                ws.column_dimensions[get_column_letter(col_cells[0].column)].width = (
                    min(max(length + 2, min_w), max_w)
                )

        # ── Sheet 1: raw data ─────────────────────────────────────────
        period_label = f"{start_date} - {cutoff_date}"
        self._write_raw_sheet(wb, df, period_label,
                              _style_header_cell, _style_data_cell,
                              _auto_width, _BORDER, _LEFT)

        self._emit_progress(82, "Building Attendance Summary pivot…")

        # ── Sheet 2: Attendance Summary pivot ─────────────────────────
        self._write_attendance_summary_sheet(
            wb, df, _style_header_cell, _style_data_cell,
            _auto_width, _BORDER, _LEFT, _RIGHT, _TOTAL_FILL, _HEADER_FONT,
        )

        self._emit_progress(90, "Building Late Undertime Summary pivot…")

        # ── Sheet 3: Late Undertime Summary pivot ─────────────────────
        self._write_late_undertime_sheet(
            wb, df, _style_header_cell, _style_data_cell,
            _auto_width, _BORDER, _LEFT, _RIGHT, _TOTAL_FILL,
            _SUBHDR_FILL, _HEADER_FONT,
        )

        wb.save(out_path)
        self.log.info(
            f"AttendanceSummaryTool: Workbook saved | sheets={[s.title for s in wb.worksheets]}"
        )

    # ── Sheet 1 helper ────────────────────────────────────────────────

    def _write_raw_sheet(self, wb, df, sheet_name,
                         style_hdr, style_data, auto_width, border, left_align):
        """Write the raw attendance DataFrame with autofilter on row 1."""


        ws = wb.create_sheet(title=sheet_name)

        # Header row
        for col_idx, col_name in enumerate(df.columns, start=1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            style_hdr(cell)

        # Data rows
        for row_idx, row in enumerate(df.itertuples(index=False), start=2):
            for col_idx, value in enumerate(row, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                style_data(cell, align=left_align)

        # Autofilter across all header columns
        last_col_letter = get_column_letter(len(df.columns))
        ws.auto_filter.ref = f"A1:{last_col_letter}1"

        # Freeze the header row
        ws.freeze_panes = "E2"

        auto_width(ws)
        self.log.info(
            f"AttendanceSummaryTool: Raw sheet written | "
            f"sheet='{sheet_name}' rows={len(df)} cols={len(df.columns)}"
        )

    # ── Sheet 2 helper ────────────────────────────────────────────────

    def _write_attendance_summary_sheet(self, wb, df, style_hdr, style_data,
                                        auto_width, border, left_align, right_align,
                                        total_fill, header_font):
        """
        Pivot: rows=Employee Id, columns=Status_Unmand unique values,
        values=count of Detailed Status.  Grand Total column appended.
        """

        ws = wb.create_sheet(title="Attendance Summary")

        emp_col      = self._find_col(df, ("Employee Id", "Employee ID", "Emp ID", "emp_id"))
        status_col   = "Status_Unmand"
        detail_col   = self._find_col(df, ("Detailed Status", "detailed_status"))

        if not emp_col or status_col not in df.columns or not detail_col:
            self.log.warning(
                "AttendanceSummaryTool: Attendance Summary pivot skipped — "
                f"missing columns (emp={emp_col}, status_present={status_col in df.columns}, "
                f"detail={detail_col})"
            )
            ws.cell(row=1, column=1, value="Required columns not found in source data.")
            return

        pivot = (
            df.groupby([emp_col, status_col])[detail_col]
            .count()
            .unstack(fill_value=0)
        )
        pivot.columns.name = None
        pivot["Grand Total"] = pivot.sum(axis=1)
        pivot = pivot.reset_index()

        # Sort status columns alphabetically, keep Grand Total last
        status_cols = sorted(
            [c for c in pivot.columns if c not in (emp_col, "Grand Total")]
        )
        ordered_cols = [emp_col] + status_cols + ["Grand Total"]
        pivot = pivot[ordered_cols]

        # Header
        for col_idx, col_name in enumerate(pivot.columns, start=1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            style_hdr(cell)

        # Data rows
        for row_idx, row in enumerate(pivot.itertuples(index=False), start=2):
            for col_idx, value in enumerate(row, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                is_total = pivot.columns[col_idx - 1] == "Grand Total"
                align    = right_align if col_idx > 1 else left_align
                style_data(cell, align=align)
                if is_total:
                    cell.fill = total_fill
                    cell.font = Font(bold=True)

        ws.freeze_panes = "B2"
        auto_width(ws)
        self.log.info(
            f"AttendanceSummaryTool: Attendance Summary sheet written | "
            f"employees={len(pivot)} status_cols={len(status_cols)}"
        )

    # ── Sheet 3 helper ────────────────────────────────────────────────

    def _write_late_undertime_sheet(self, wb, df, style_hdr, style_data,
                                    auto_width, border, left_align, right_align,
                                    total_fill, subhdr_fill, header_font):
        """
        Pivot: rows=Employee Id + Employee Name,
        columns=Late By_Unmand | Early Clock Out By_Unmand | Total (sum).
        """

        ws = wb.create_sheet(title="Late Undertime Summary")

        emp_col  = self._find_col(df, ("Employee Id", "Employee ID", "Emp ID", "emp_id"))
        name_col = self._find_col(df, ("Employee Name", "EmployeeName", "Name", "emp_name"))
        late_col = "Late By_Unmand"
        eco_col  = "Early Clock Out By_Unmand"

        missing = [
            c for c in (late_col, eco_col) if c not in df.columns
        ] + ([emp_col] if not emp_col else [])

        if missing:
            self.log.warning(
                f"AttendanceSummaryTool: Late Undertime pivot skipped — missing={missing}"
            )
            ws.cell(row=1, column=1, value="Required columns not found in source data.")
            return

        group_keys = [emp_col] + ([name_col] if name_col else [])

        # Coerce Unmand columns to numeric (they are floats but stored as objects)
        work_df = df.copy()
        work_df[late_col] = pd.to_numeric(work_df[late_col], errors="coerce").fillna(0)
        work_df[eco_col]  = pd.to_numeric(work_df[eco_col],  errors="coerce").fillna(0)

        pivot = (
            work_df.groupby(group_keys, as_index=False)
            .agg(
                **{
                    "Late By_Unmand":           (late_col, "sum"),
                    "Early Clock Out By_Unmand": (eco_col,  "sum"),
                }
            )
        )
        pivot["Total"] = pivot["Late By_Unmand"] + pivot["Early Clock Out By_Unmand"]

        # ── Row 1: merged top-level header ───────────────────────────
        id_cols    = group_keys          # 1 or 2 columns
        value_cols = ["Late By_Unmand", "Early Clock Out By_Unmand", "Total"]
        total_cols = len(id_cols) + len(value_cols)

        # Merge the "Values" super-header over the three numeric columns
        id_end  = len(id_cols)
        val_start = id_end + 1

        for ci in range(1, val_start):
            cell = ws.cell(row=1, column=ci, value="")
            style_hdr(cell)

        val_end_col = total_cols
        ws.merge_cells(
            start_row=1, start_column=val_start,
            end_row=1,   end_column=val_end_col,
        )
        merged_cell = ws.cell(row=1, column=val_start, value="Values")
        style_hdr(merged_cell, fill=subhdr_fill)
        merged_cell.alignment = Alignment(horizontal="center", vertical="center")

        # ── Row 2: column labels ──────────────────────────────────────
        all_headers = id_cols + value_cols
        for col_idx, col_name in enumerate(all_headers, start=1):
            cell = ws.cell(row=2, column=col_idx, value=col_name)
            style_hdr(cell)

        # ── Data rows (start at row 3) ────────────────────────────────
        for row_idx, row in enumerate(pivot.itertuples(index=False), start=3):
            for col_idx, value in enumerate(row, start=1):
                col_name = all_headers[col_idx - 1]
                cell     = ws.cell(row=row_idx, column=col_idx, value=value)
                is_total = col_name == "Total"
                align    = right_align if col_name in value_cols else left_align
                style_data(cell, align=align)
                if is_total:
                    cell.fill = total_fill
                    cell.font = Font(bold=True)

        # ── Grand total row ───────────────────────────────────────────
        grand_row = len(pivot) + 3
        ws.cell(row=grand_row, column=1, value="Grand Total").font = Font(bold=True)
        for ci, col_name in enumerate(value_cols, start=val_start):
            col_values = [
                ws.cell(row=r, column=ci).value or 0
                for r in range(3, grand_row)
            ]
            total_cell       = ws.cell(row=grand_row, column=ci, value=sum(col_values))
            total_cell.fill  = total_fill
            total_cell.font  = Font(bold=True)
            total_cell.border = border
            total_cell.alignment = right_align

        ws.freeze_panes = f"A3"
        auto_width(ws)
        self.log.info(
            f"AttendanceSummaryTool: Late Undertime sheet written | "
            f"employees={len(pivot)}"
        )

    # ── Column finder ─────────────────────────────────────────────────

    @staticmethod
    def _find_col(df: pd.DataFrame, candidates: tuple) -> str | None:
        """Return the first candidate column name present in df, else None."""
        for c in candidates:
            if c in df.columns:
                return c
        return None

    # ===================================================================
    # DATE FILTER
    # ===================================================================

    def _filter_by_date_range(self, df: pd.DataFrame, start_date: str, cutoff_date: str) -> pd.DataFrame:
        """
        Return df filtered to rows whose date column falls within
        [start_date, cutoff_date] (inclusive).

        If no recognised date column is found the original df is returned
        unchanged, with a warning logged.

        Parameters
        ----------
        df          : pd.DataFrame  Raw attendance DataFrame.
        start_date  : str           ISO date (yyyy-MM-dd) — period start.
        cutoff_date : str           ISO date (yyyy-MM-dd) — period cutoff.

        Returns
        -------
        pd.DataFrame
            Filtered (or original, if no date column found) DataFrame.
        """
        date_col = None
        for candidate in ("Date", "date", "Attendance Date", "attendance_date"):
            if candidate in df.columns:
                date_col = candidate
                break

        if not date_col:
            self.log.warning(
                "AttendanceSummaryTool: No recognised date column found — skipping date filter"
            )
            return df

        try:
            df = df.copy()
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            start  = pd.to_datetime(start_date)
            cutoff = pd.to_datetime(cutoff_date)
            filtered = df[(df[date_col] >= start) & (df[date_col] <= cutoff)]
            self.log.info(
                f"AttendanceSummaryTool: Date filter applied | "
                f"before={len(df)} after={len(filtered)} "
                f"start={start_date} cutoff={cutoff_date}"
            )
            return filtered.reset_index(drop=True)
        except Exception as e:
            self.log.warning(f"AttendanceSummaryTool: Date filter failed | {e}")
            return df

    # ===================================================================
    # UNMAND COLUMN COMPUTATION
    # ===================================================================

    # Map of shift-name keywords → expected clock-in time (HH:MM:SS)
    _SHIFT_CLOCK_IN = {
        "Shift 6": "07:00:00",
        "Shift 7": "08:00:00",
        "Shift 8": "09:00:00",
        "Shift 9": "10:00:00",
    }

    @staticmethod
    def _hhmmss_to_total_seconds(value: str) -> int | None:
        """
        Parse a "HH:MM:SS" string and return total seconds.

        Returns None if value is blank / unparseable.
        """
        if not isinstance(value, str):
            return None
        parts = value.strip().split(":")
        if len(parts) != 3:
            return None
        try:
            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
            return h * 3600 + m * 60 + s
        except ValueError:
            return None

    @staticmethod
    def _seconds_to_floored_minutes(total_seconds: int) -> float:
        """
        Convert total seconds to floored whole minutes as a float.

        Example: 119 s → 1.00,  3599 s → 59.00
        """
        return float(int(total_seconds // 60))

    def _compute_late_by_unmand(self, row: pd.Series) -> tuple[float, str]:
        """
        Derive the Late By_Unmand value for a single row.

        Rules (evaluated top-to-bottom; first match wins)
        -------------------------------------------------
        1. Policy == "Flexible Schedule (No NSD)"
           → 0.00 if Final Work Duration >= 9 hr, else standard rounding.

        2. Policy == "Flexible Schedule with Grace Period (No NSD)"
           → 0.00 if Clock In <= expected shift start, else standard rounding.

        3. Standard rounding:
           • Parse "Late By" as HH:MM:SS → total seconds.
           • If >= 2 hr (7 200 s) → 0.00.
           • Else floor to whole minutes → e.g. 01:59:49 → 119.00.

        Returns
        -------
        float  Floored minutes, or 0.00 when the override applies.
        """
        raw = row.get("Late By", "")
        total_seconds = self._hhmmss_to_total_seconds(raw)

        if total_seconds is None:
            return 0.00, ""

        policy = str(row.get("Policy", "")).strip()

        # ── Policy: Flexible Schedule (No NSD) ─────────────────────────
        if policy == "Flexible Schedule (No NSD)":
            fwd_raw = row.get("Final Work Duration", "")
            fwd_sec = self._hhmmss_to_total_seconds(fwd_raw)
            if fwd_sec is not None and fwd_sec >= 9 * 3600:
                return 0.00, ""
            # else fall through to standard rounding

        # ── Policy: Flexible Shift with Grace Period (No NSD) ─────────
        elif policy == "Flexible Shift with Grace Period (No NSD)":
            shift_raw = str(row.get("Shift", "")).strip().lower()
            clock_in_raw = str(row.get("Clock In", "")).strip()

            expected_str = None
            for keyword, expected in self._SHIFT_CLOCK_IN.items():
                if keyword in shift_raw:
                    expected_str = expected
                    break

            if expected_str:
                clock_in_sec  = self._hhmmss_to_total_seconds(clock_in_raw)
                expected_sec  = self._hhmmss_to_total_seconds(expected_str)
                if clock_in_sec is not None and expected_sec is not None:
                    if clock_in_sec <= expected_sec:
                        return 0.00, ""
            # If shift not recognised or comparison fails, fall through

        # Order matters — check the stricter threshold first
        if total_seconds >= 4 * 3600:
            return 0.00, "Unpaid Leave"

        if total_seconds >= 2 * 3600:
            return 0.00, "Present,Half Day Unpaid Leave"

        return self._seconds_to_floored_minutes(total_seconds), ""

    def _compute_early_clockout(self, row: pd.Series) -> tuple[float, str]:
        """
        Derive Early Clock Out By_Unmand and Status_Unmand for a single row.

        Rules
        -----
        • >= 4 hr (14 400 s) → 0.00, status = "Unpaid Leave"
        • >= 2 hr  (7 200 s) → 0.00, status = "Present, Half Day Unpaid Leave"
        • < 2 hr             → floored minutes, status = "" (unchanged)

        Returns
        -------
        tuple[float, str]   (early_clock_out_unmand, status_unmand)
        """
        raw = row.get("Early Clock Out By", "")
        total_seconds = self._hhmmss_to_total_seconds(raw)

        if total_seconds is None:
            return 0.00, ""

        # Order matters — check the stricter threshold first
        if total_seconds >= 4 * 3600:
            return 0.00, "Unpaid Leave"

        if total_seconds >= 2 * 3600:
            return 0.00, "Present,Half Day Unpaid Leave"

        return self._seconds_to_floored_minutes(total_seconds), ""

    def _compute_unmand_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add Late By_Unmand, Early Clock Out By_Unmand, and Status_Unmand
        columns to the DataFrame and place them immediately after their
        corresponding original columns.

        Parameters
        ----------
        df : pd.DataFrame
            Attendance DataFrame (already filtered by date).

        Returns
        -------
        pd.DataFrame
            Same DataFrame with the _Unmand columns inserted beside their
            original columns.
        """
        df = df.copy()

        late_unmand = []
        early_unmand = []
        status_unmand = []

        for _, row in df.iterrows():
            late_val, late_status_val = self._compute_late_by_unmand(row)
            early_val, early_status_val = self._compute_early_clockout(row)

            late_unmand.append(late_val)
            early_unmand.append(early_val)

            if late_status_val:
                status_unmand.append(late_status_val)
            elif early_status_val:
                status_unmand.append(early_status_val)
            else:
                status_unmand.append("")

        # Add the new columns
        df["Late By_Unmand"] = late_unmand
        df["Early Clock Out By_Unmand"] = early_unmand
        df["Status_Unmand"] = status_unmand

        # Default Status_Unmand to Status if blank
        mask = df["Status_Unmand"].isna() | (df["Status_Unmand"] == "")
        df.loc[mask, "Status_Unmand"] = df.loc[mask, "Status"]

        # Move _Unmand columns beside their original columns
        column_pairs = [
            ("Late By", "Late By_Unmand"),
            ("Early Clock Out By", "Early Clock Out By_Unmand"),
            ("Status", "Status_Unmand"),
        ]

        # Iterate in reverse so insert positions are not affected
        for original, unmand in reversed(column_pairs):
            if original in df.columns and unmand in df.columns:
                col = df.pop(unmand)
                insert_at = df.columns.get_loc(original) + 1
                df.insert(insert_at, unmand, col)

        self.log.info(
            f"AttendanceSummaryTool: Unmand columns added | rows={len(df)}"
        )

        return df

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
