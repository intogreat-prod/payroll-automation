"""
checker.py (Billing)
---------------------
BillingCheckerFeature — file collection, validation, and variance
generation for the Billing "Check Variance" flow.

Mirrors features/payroll/checker.py's file-collection/validation pipeline
almost exactly (same read/decrypt, identity check, ID-column normalising).
Two things are different, on purpose:

1. Only 2 files are ever required (Manual + Unmand) and there's no
   "Total row" requirement — Billing checks are row-level, not totals.
2. generate() doesn't need a headers list downloaded from SharePoint like
   Payroll's does. It compares whatever columns exist in both uploaded
   files directly, and applies the same three-state variance rule used
   in the Finance team's existing MGT Check Excel macro:

       - ID missing from one of the two files  -> "0 HEADCOUNT"
       - value blank on either side             -> "FOR MANUAL"
       - otherwise                              -> Manual value - Unmand value
       - anything that blows up                 -> "ERROR"

   The output is a single "Variance" sheet (no separate master/pivot
   sheets), colour-coded with the same rules as the Excel macro:
   green when the variance is exactly 0, orange for "0 HEADCOUNT",
   red for "ERROR" or a variance outside ±1.

Responsibilities
----------------
1. Open a native file-picker dialog for the user to select exactly two
   checker Excel files: one Manual Checker and one Unmand Checker.
2. Read each file, decrypting with msoffcrypto when needed.
3. Validate file identity (manual / unmand labels) and normalise the ID
   column so both files can be merged on it.
4. Emit results back to the Orchestrator via callbacks:
       on_result(codes)        — list of status-code strings for the UI
       uploaded_files(dfs)     — dict of validated DataFrames for variance
5. generate() — runs off the main thread — merges the two files and
   writes the colour-coded Variance report.

File-picker deferral
--------------------
The dialog is opened via QTimer.singleShot(0, ...) so it fires after the
current Qt event (the button click) has fully resolved.  Without this,
the main window briefly flashes as Qt tries to repaint during the
synchronous dialog open.
"""

import io
import re
from datetime import datetime
from difflib import get_close_matches
from pathlib import Path

import msoffcrypto
import pandas as pd
from dotenv import load_dotenv
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import CellIsRule
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QFileDialog, QApplication

from utils.app_config_user import get
from utils.file_utils import billing_app_path, create_path

# Maximum number of checker files allowed per session
MAX_FILES = 2

# Password format used for encrypted checker files
_PASSWORD_PREFIX = get("PASSWORD_PREFIX", "")

# Fallback ID-column name variants, used only if billing_config doesn't
# define its own "expected_id_names" list.
_DEFAULT_COLUMN_NAMES = [
                        "*ContactName",
                        "Reference",
                        "Total Payroll",
                        "Management Fee",
                        "Attendance Adjustment",
                        "Reimbursables",
                        "Support Point",
                        "Business Improvement",
                        "IT Outsourcing",
                        "Insightful",
                        "Security Bond",
                        "Recruitment Fee",
                        "Fixed Outsourcing Fee",
                        "Total"
                    ]


class BillingCheckerFeature:
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

    def prepare_checker_files(self, cc_names: list = None, additional_map: list = None):
        """
        Start the checker file preparation flow.

        Defers opening the file dialog to the next Qt event loop tick so
        the UI fully settles after the button click before the dialog
        appears — prevents the main window from flashing.

        Parameters
        ----------
        cc_names : list[str], optional
            Expected ID column header variants, used for fuzzy matching
            when normalising the column name. Falls back to
            _DEFAULT_COLUMN_NAMES when not provided.
        """
        self.log.section("BILLING CHECKER FILE PREPARATION")
        self.log.info("BillingCheckerFeature: Deferring file dialog to next event loop tick")
        QTimer.singleShot(0, lambda: self._open_and_process(cc_names or _DEFAULT_COLUMN_NAMES, additional_map))

    # ===================================================================
    # STEP 1 — OPEN FILE DIALOG + PROCESS
    # ===================================================================

    def _open_and_process(self, cc_names: list, additional_map: list):
        """
        Open the native file-picker and, if files are selected, run the
        full validation pipeline.

        Called by QTimer.singleShot() — executes after the button click
        has been fully processed by the Qt event loop.
        """
        self.log.info("BillingCheckerFeature: Opening file dialog")

        # Parent=None keeps the dialog independent of the main window.
        # Passing the main window as parent caused it to briefly flash.

        self._emit_progress(0, "Selecting files…")

        file_paths, _ = QFileDialog.getOpenFileNames(
            self.main_window,
            "Select Billing Checker Excel Files",
            "",
            "Excel Files (*.xlsx *.xls *.csv)",
        )

        self.log.info(f"BillingCheckerFeature: File dialog closed | selected={len(file_paths)} max={MAX_FILES}")

        # ── Guard: nothing selected ───────────────────────────────────
        if not file_paths:
            self.log.info("BillingCheckerFeature: No files selected — aborting")
            self._emit_result("no_file_error")
            return

        # ── Guard: too many files ─────────────────────────────────────
        if len(file_paths) > MAX_FILES:
            self.log.warning(f"BillingCheckerFeature: Too many files | got={len(file_paths)} max={MAX_FILES}")
            self._emit_result("file_exceed_error")
            return

        self.log.info("BillingCheckerFeature: File count validated — starting processing")
        self._process_files(file_paths, cc_names, additional_map)

    # ===================================================================
    # STEP 2 — FULL VALIDATION PIPELINE
    # ===================================================================
    def _process_files(self, file_paths: list, cc_names: list, additional_map: list):
        """
        Run the full validation pipeline: read -> identity check ->
        normalise -> required-columns check -> key-column cleanup.

        Every step's output is checked for per-file errors before moving
        on to the next step, so a bad file (unreadable, wrong currency,
        missing columns, ...) is caught and reported the moment it's
        flagged — instead of leaking a non-DataFrame value into a later
        step that assumes every value is a DataFrame and crashing on it.

        The whole pipeline runs inside a try/except so any unexpected
        error still reaches the UI as "processing_error" rather than
        dying silently on the main thread with nothing ever emitted.
        """
        try:
            self._emit_progress(10, "Reading files…")
            QApplication.processEvents()
            dataframes = self._read_files(file_paths)

            if self._bail_on_errors(dataframes):
                return

            self._emit_progress(15, "Checking file identity…")
            QApplication.processEvents()
            identity_error = self._check_file_identity(dataframes)
            if identity_error:
                self._emit_result(identity_error)
                return

            pipeline = [
                (20, "Normalising ID column…",       self._normalise_columns,        (cc_names, additional_map)),
                (22, "Validating required columns…", self._missing_required_columns, (cc_names,)),
                (23, "Cleaning key columns…",         self._clean_key_columns,        ()),
            ]

            for progress, message, step, args in pipeline:
                self._emit_progress(progress, message)
                QApplication.processEvents()

                result = step(dataframes, *args)
                if result is not None:
                    dataframes = result

                if self._bail_on_errors(dataframes):
                    return

            self.log.info("BillingCheckerFeature: All files validated — handing off to Orchestrator")
            self._emit_result("file_success")
            self._emit_files(dataframes)

        except Exception as e:
            self.log.error(f"BillingCheckerFeature: Unhandled error in validation pipeline — {e}", error=e)
            self._emit_result("processing_error")

    def _bail_on_errors(self, dataframes: dict) -> bool:
        """
        Scan `dataframes` for any non-DataFrame (error) values and emit
        the corresponding status codes if found.

        A value may be a bare code string ("sensitivity_error") or a
        (message, code) tuple set by a validation step — either way,
        only the code itself is emitted to the UI.

        Returns True if errors were found (and emitted); the caller
        should stop the pipeline when this returns True.
        """
        error_codes = []
        for file, status in dataframes.items():
            if isinstance(status, pd.DataFrame):
                continue
            code = status[1] if isinstance(status, tuple) else status
            error_codes.append(f"{status[0] if isinstance(status, tuple) else file}|{code}")

        if error_codes:
            self.log.warning(f"BillingCheckerFeature: Validation failed | errors={error_codes}")
            self._emit_result(error_codes)
            return True

        return False

    # ===================================================================
    # VALIDATION HELPERS
    # ===================================================================

    def _read_files(self, file_paths: list) -> dict:
        """
        Read each selected file into a DataFrame, decrypting if needed.

        Encrypted files are opened with msoffcrypto using the standard
        password. Files that cannot be read at all are stored as
        "sensitivity_error" for the error sweep.

        Returns
        -------
        dict[str, pd.DataFrame | str]
            Keys are file names (stem only, no directory).
            Values are DataFrames on success, or an error-code string.
        """
        self.log.info(f"BillingCheckerFeature: Reading {len(file_paths)} file(s)")
        dataframes = {}
        year       = datetime.now().year
        progress   = 10
        increment  = progress / len(file_paths)

        for file_path in file_paths:
            filename = Path(file_path).name
            progress += increment
            header_row = 3 if "masterfile" in file_path.lower() else 0

            # ── Attempt unencrypted read ──────────────────────────────
            try:
                df                   = pd.read_excel(file_path, dtype=str, header=header_row)
                dataframes[filename] = df

                self._emit_progress(int(progress), f"Read OK | {filename}")
                QApplication.processEvents()
                continue

            except Exception:
                try:
                    df                   = pd.read_csv(file_path, dtype=str, header=header_row, encoding="cp1252")
                    dataframes[filename] = df

                    self._emit_progress(int(progress), f"Read OK | {filename}")
                    QApplication.processEvents()
                    continue   
                except Exception:
                    pass # Fall through to decryption attempt

            # ── Attempt decrypted read ────────────────────────────────
            try:
                password  = f"{_PASSWORD_PREFIX}{year}"
                decrypted = io.BytesIO()

                with open(file_path, "rb") as f:
                    office_file = msoffcrypto.OfficeFile(f)
                    office_file.load_key(password=password)
                    office_file.decrypt(decrypted)

                decrypted.seek(0)
                df                   = pd.read_excel(decrypted, dtype=str, header=header_row)
                dataframes[filename] = df

                self._emit_progress(int(progress), f"Decrypted and read OK | {filename}")
                QApplication.processEvents()

            except Exception as e:
                self.log.warning(f"BillingCheckerFeature: Failed to read or decrypt | file={filename} error={e}")
                dataframes[filename] = "sensitivity_error"

        return dataframes

    def _check_file_identity(self, dataframes: dict) -> str | None:
        """
        Verify both a Manual and an Unmand checker file are present.

        Matches are case-insensitive substring checks on the file name.
        """
        names = [fn.lower() for fn in dataframes]

        has_manual      = any("manual" in fn for fn in names)
        has_pivot       = any("pivot" in fn for fn in names)
        has_unmand      = any("unmand" in fn for fn in names)
        has_masterfile  = any("masterfile" in fn for fn in names)

        if not (has_manual or has_masterfile):
            self.log.warning("BillingCheckerFeature: Masterfile  not found")
            return "manual_error"

        if not (has_unmand or has_pivot):
            self.log.warning("BillingCheckerFeature: Unmand Pivot file not found")
            return "unmand_error"

        self.log.info("BillingCheckerFeature: Both manual and unmand files identified")
        return None

    def _normalise_columns(self, dataframes: dict, cc_names: list, additional_map: list):
        self.log.info("BillingCheckerFeature: Normalising column names")

        # additional_map is optional in billing_config — guard against None
        additional_map = additional_map or {}
        additional_map_lower = {k.lower(): v for k, v in additional_map.items()}

        for file_, df in dataframes.items():

            # Already flagged as an error by an earlier step — leave it alone
            if not isinstance(df, pd.DataFrame):
                continue

            # -------------------------------
            # Normalise column names
            # -------------------------------
            rename_map = {}
            for col in df.columns:
                match = get_close_matches(
                    str(col).strip(),
                    cc_names,
                    n=1,
                    cutoff=0.7
                )
                if match:
                    rename_map[col] = match[0]
                elif col.strip().lower() in additional_map_lower:
                    rename_map[col] = additional_map_lower[col.strip().lower()]

            df.rename(columns=rename_map, inplace=True)

            # -------------------------------
            # Validate
            # -------------------------------
            if "*ContactName" not in df.columns:
                self.log.warning(
                    f"BillingCheckerFeature: ContactName column not found | file={file_}"
                )
                dataframes[file_] = (f"*ContactName column not found in {file_}", "currency_error")
                continue

            # -------------------------------
            # Flagged Non AUD
            # -------------------------------
            if "pivot" in file_.lower() and "Currency" in df.columns:
                mask = df["Currency"] != "AUD"

                if mask.any():
                    self.log.warning(
                        f"BillingCheckerFeature: Non-AUD currency found. | file={file_}"
                    )
                    dataframes[file_] = (f"Non-AUD currency rows found in {file_}", "currency_error")
                    continue

            dataframes[file_] = df

        return dataframes

    def _missing_required_columns(
        self,
        dataframes: dict,
        required_columns: list,
        cutoff: float = 0.8,
    ) -> list[str]:
        """
        Returns a list of required columns that could not be matched.
        """
        for file_, df in dataframes.items():

            if not isinstance(df, pd.DataFrame):
                continue

            columns = [str(c).strip() for c in df.columns]

            missing = []

            for required in required_columns:
                if not get_close_matches(required, columns, n=1, cutoff=cutoff):
                    missing.append(required)


            if missing and "masterfile" in file_.lower():
                self.log.warning(
                    f"BillingCheckerFeature: Missing required columns: {', '.join(missing)}"
                )
                dataframes[file_] = (f"{', '.join(missing)} columns are missing from {file_}", "missing_column_error")

            elif missing and "pivot" in file_.lower():
                for miss in missing:
                    dataframes[file_][miss] = 0

    def _clean_key_columns(self, dataframes: dict):
        """
        Cleans the key columns used for reconciliation.

        *ContactName
            - Drop rows where value is blank, NaN, or 0.

        Reference
            - Remove invoice numbers such as:
                INV-000
                INV000
                INV 000
                Invoice-000

            while preserving the descriptive portion.

            Examples:
                INV-001 Finance      -> Finance
                Finance INV-001      -> Finance
                INV001               -> ""
        """

        self.log.info("BillingCheckerFeature: Cleaning key columns")

        invoice_pattern = re.compile(
            r"\b(?:INV(?:OICE)?)[\s-]*\d+\b",
            flags=re.IGNORECASE,
        )
        invalid_values = ["", "0", "(blank)"]

        for file_, df in dataframes.items():

            if not isinstance(df, pd.DataFrame):
                continue

            # -------------------------
            # Clean Contact Name
            # -------------------------
            if "*ContactName" in df.columns:

                df["*ContactName"] = (
                    df["*ContactName"]
                    .fillna("")
                    .astype(str)
                    .str.strip()
                )

                df.loc[df["*ContactName"].isin(invalid_values), "*ContactName"] = None
                

            # -------------------------
            # Clean Reference
            # -------------------------
            if "Reference" in df.columns:

                df["Reference"] = (
                    df["Reference"]
                    .fillna("")
                    .astype(str)
                    .apply(lambda x: invoice_pattern.sub("", x).strip())
                    .str.replace(r"\s{2,}", " ", regex=True)
                )

                df.loc[df["Reference"].isin(invalid_values), "Reference"] = None

        return dataframes

    # ===================================================================
    # EMIT HELPERS
    # ===================================================================

    def _emit_result(self, codes):
        """Fire the on_result callback with a normalised list of status codes."""
        if not self.on_result:
            self.log.warning("BillingCheckerFeature: on_result callback not wired — result dropped")
            return

        normalized = list(codes) if isinstance(codes, (list, tuple)) else [codes]
        self.log.info(f"BillingCheckerFeature: Emitting result codes | codes={normalized}")
        self.on_result(normalized)

    def _emit_files(self, files: dict):
        """Fire the uploaded_files callback with the validated DataFrames."""
        if not self.uploaded_files:
            self.log.warning("BillingCheckerFeature: uploaded_files callback not wired — files dropped")
            return

        self.log.info(f"BillingCheckerFeature: Handing {len(files)} file(s) to Orchestrator")
        self.uploaded_files(files)

    def _emit_progress(self, percent: int, message: str):
        """Fire the on_progress callback to update the UI progress bar."""
        if not self.on_progress:
            return
        self.log.info(f"BillingCheckerFeature: Progress | {percent}% — {message}")
        self.on_progress(percent, message)

    # ===================================================================
    # VARIANCE GENERATION — runs entirely off the main thread
    # ===================================================================

    def generate(self, files: dict, var_tolerance=0):
        """
        Merge the Manual and Unmand files on their ID column and produce
        a single colour-coded Variance report.

        Variance rule per (*ContactName, column) pair — matches the
        Finance team's MGT Check Excel macro:
            - ID missing from one side entirely -> "0 HEADCOUNT"
            - value blank on either side         -> "FOR MANUAL"
            - otherwise                          -> Manual value - Unmand value
            - anything that can't be compared    -> "ERROR"
        """
        manual_df = None
        unmand_df = None

        for filename, df in files.items():
            fname_lower = filename.lower()
            if "masterfile" in fname_lower:
                manual_df = df
            elif "pivot" in fname_lower:
                unmand_df = df

        manual_df = manual_df if isinstance(manual_df, pd.DataFrame) else pd.DataFrame()
        unmand_df = unmand_df if isinstance(unmand_df, pd.DataFrame) else pd.DataFrame()

        # ------------------------------------------------------------
        # Reconciliation (Wide Variance Report)
        # ------------------------------------------------------------

        KEY_COLUMNS = ["*ContactName", "Reference"]

        metric_columns = [
            c for c in manual_df.columns
            if c not in KEY_COLUMNS and c in unmand_df.columns
        ]

        manual_df = manual_df.drop_duplicates(
            subset=KEY_COLUMNS,
            keep="first"
        )
 
        unmand_df = unmand_df.drop_duplicates(
            subset=KEY_COLUMNS,
            keep="first"
        )

        # Show Total first
        if "Total" in metric_columns:
            metric_columns.remove("Total")
            metric_columns.insert(0, "Total")

        merged = pd.merge(
            manual_df[KEY_COLUMNS + metric_columns],
            unmand_df[KEY_COLUMNS + metric_columns],
            on=KEY_COLUMNS,
            how="outer",
            suffixes=("_masterfile", "_unmand"),
            indicator=True,
        )

        progress = 30
        increment = 60 / max(len(merged), 1)

        report_rows = []

        for _, row in merged.iterrows():

            progress += increment
            self._emit_progress(
                int(progress),
                f"Checking {row.get('*ContactName', '')}"
            )
            QApplication.processEvents()

            report = {
                "*ContactName": row.get("*ContactName"),
                "Reference": row.get("Reference"),
            }

            for col in metric_columns:

                manual_col = f"{col}_unmand"
                unmand_col = f"{col}_masterfile"

                m_val = row.get(manual_col)
                u_val = row.get(unmand_col)

                report[f"{col} (Unmand)"] = m_val
                report[f"{col} (Masterfile)"] = u_val

                try:
                    m_num = pd.to_numeric(
                        str(m_val).replace(",", "").strip(),
                        errors="coerce"
                    )

                    u_num = pd.to_numeric(
                        str(u_val).replace(",", "").strip(),
                        errors="coerce"
                    )

                    m_num = 0 if pd.isna(m_num) else m_num
                    u_num = 0 if pd.isna(u_num) else u_num

                    variance = m_num - u_num

                except Exception:
                    variance = "ERROR"

                report[f"Δ {col}"] = variance

            report_rows.append(report)

        detailed_df = pd.DataFrame(report_rows)

        variance_columns = [
            c for c in detailed_df.columns
            if c.startswith("Δ ")
        ]

        numeric_variance = detailed_df[variance_columns].apply(
            pd.to_numeric,
            errors="coerce"
        )

        # Accuracy is based on the "Total" variance column specifically —
        # number of clients flagged on Δ Total over total number of clients.
        total_var_col = "Δ Total"
        if total_var_col in numeric_variance.columns:
            flagged_total = numeric_variance[total_var_col].abs().ge(var_tolerance)
        else:
            # Fallback: no Total column present — flag on any variance column
            flagged_total = numeric_variance.abs().ge(var_tolerance).any(axis=1)

        total_clients = len(detailed_df)
        flagged_count = int(flagged_total.sum())

        accuracy_pct = (
            round((1 - (flagged_count / total_clients)) * 100, 2)
            if total_clients else 0
        )

        file_path = create_path(billing_app_path() / "Automation" / "Checker") / f"Billing_Checker_Variance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        # ------------------------------------------------------------
        # Metadata block — written above the detailed variance table
        # ------------------------------------------------------------
        today = datetime.now().strftime("%Y-%m-%d")
        meta_df = pd.DataFrame({
            "Info":  ["Date", "Total Clients", "Flagged Clients", "Accuracy Rate", "Tolerance"],
            "Value": [today, total_clients, flagged_count, f"{accuracy_pct}%", f"± {var_tolerance} AUD"],
        })

        # header row (1-indexed) where the detailed table's column
        # headers land, once the meta block + blank row are written first
        detailed_startrow = len(meta_df) + 2  # 0-indexed, mirrors payroll checker's layout
        header_row = detailed_startrow + 1    # 1-indexed, for openpyxl formatting pass

        self._emit_progress(90, "Writing Variance report…")
        QApplication.processEvents()

        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            meta_df.to_excel(writer, sheet_name="Variance", index=False, startrow=0)
            detailed_df.to_excel(writer, sheet_name="Variance", index=False, startrow=detailed_startrow)

        self._emit_progress(95, "Applying formatting…")
        QApplication.processEvents()
        self._apply_variance_formatting(file_path, header_row=header_row, var_tolerance=var_tolerance)

        self.log.info(
            f"BillingCheckerFeature: Variance report complete | "
            f"clients={total_clients} flagged={flagged_count} accuracy={accuracy_pct}%"
        )

        self._emit_progress(100, "Done")

        return {
            "file_path":       file_path,
            "total_clients":   total_clients,
            "flagged_count":   flagged_count,
            "correct_clients": total_clients - flagged_count,
            "accuracy_pct":    accuracy_pct,
            "var_tolerance":   var_tolerance,
        }

    def _apply_variance_formatting(self, file_path, header_row: int = 1, var_tolerance: float = 1.5):
        """
        Apply conditional formatting to every variance (Δ) column.

        Green : |variance| <= tolerance
        Red   : |variance| > tolerance

        header_row is the 1-indexed row holding the detailed table's
        column headers — everything above it (the metadata block) is
        left untouched.
        """

        wb = load_workbook(file_path)
        ws = wb["Variance"]

        green_fill = PatternFill(
            fill_type="solid",
            start_color="C6EFCE",
            end_color="C6EFCE",
        )
        green_font = Font(color="006100")

        red_fill = PatternFill(
            fill_type="solid",
            start_color="FFC7CE",
            end_color="FFC7CE",
        )
        red_font = Font(color="9C0006")

        last_row = ws.max_row
        data_start_row = header_row + 1

        # Find every variance column (header cell lives on header_row)
        for col in ws.iter_cols(1, ws.max_column, min_row=header_row, max_row=header_row):

            if not str(col[0].value).startswith("Δ "):
                continue

            letter = col[0].column_letter
            rng = f"{letter}{data_start_row}:{letter}{last_row}"

            # Between -tolerance and +tolerance -> Green
            ws.conditional_formatting.add(
                rng,
                CellIsRule(
                    operator="between",
                    formula=[str(-var_tolerance), str(var_tolerance)],
                    fill=green_fill,
                    font=green_font,
                ),
            )

            # Greater than tolerance -> Red
            ws.conditional_formatting.add(
                rng,
                CellIsRule(
                    operator="greaterThan",
                    formula=[str(var_tolerance)],
                    fill=red_fill,
                    font=red_font,
                ),
            )

            # Less than -tolerance -> Red
            ws.conditional_formatting.add(
                rng,
                CellIsRule(
                    operator="lessThan",
                    formula=[str(-var_tolerance)],
                    fill=red_fill,
                    font=red_font,
                ),
            )
        # --------------------------------------------------
        # Auto-width + Convert numeric columns
        # --------------------------------------------------

        for col_idx, column in enumerate(ws.iter_cols(1, ws.max_column, min_row=header_row), start=1):

            header = str(column[0].value).strip()

            # ---------- Auto Width ----------
            max_length = len(header)

            for cell in column[1:]:

                if cell.value is not None:
                    max_length = max(max_length, len(str(cell.value)))

            ws.column_dimensions[get_column_letter(col_idx)].width = min(max_length + 3, 35)

            # ---------- Convert to numeric ----------
            if header in ("*ContactName", "Reference"):
                continue

            for cell in column[1:]:

                if cell.value is None:
                    continue

                if isinstance(cell.value, str):

                    text = cell.value.replace(",", "").strip()

                    try:
                        number = float(text)

                        cell.value = number
                        cell.number_format = '#,##0.00'

                    except ValueError:
                        pass
        wb.save(file_path)

