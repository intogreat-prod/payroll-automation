"""
payroll_premiums.py
-------------------
PayrollPremiumsTool — file collection, validation, capping, breakdown routing
and export for the Payroll Premiums tool.

Input
-----
    Attendance Summary file — file name contains "Attendance Summary"
    Overtime Report file    — file name contains "Report" and "Overtime"

Pipeline
--------
1. Open a native file-picker; guard the file count.
2. Read the files (decrypting with msoffcrypto when needed).
3. Identify the files by name; flag each missing one explicitly.
4. Row-1 header check: Employee ID (fuzzy-matched) renamed to "Employee ID".
5. Keep only the needed columns.
6. generate(): holidays -> capping -> breakdown (routed per row) -> export.

Module flow
-----------
    payroll_premiums -> slicer -> policy / nsd / holiday / ot -> helpers

This class performs NO direct UI calls other than the file-picker dialog.
All status reporting goes through the on_result callback.
"""
import io
import re
from datetime import datetime, timedelta
from difflib import get_close_matches
from pathlib import Path

import msoffcrypto
import pandas as pd
from dotenv import load_dotenv
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QFileDialog, QApplication

from features.payroll.premiums.helpers import (
    MAX_HALF_DAY_HOURS,
    MAX_ORDINARY_HOURS,
    cap_seconds,
    duration_to_seconds,
    format_workbook,
    has_overtime,
    parse_duration,
    parse_work_date,
    prepare_export_frame,
    seconds_to_duration,
)
from features.payroll.premiums.ot import build_ot_lookup, get_ot_windows
from features.payroll.premiums.holiday import (
    ORDINARY_CODE,
    build_holiday_lookup,
    build_rest_day_lookup,
    get_status_scenario,
    is_present,
    is_unpaid_leave,
    is_half_leave_half_unpaid,
    is_present_leave,
    is_request_pending,
    is_unworked_holiday,
    get_day_code,
)
from features.payroll.premiums.slicer import (
    ALL_HEADERS,
    HALF_LEAVE_REMARK,
    OT_WITHOUT_PRESENT_REMARK,
    PRESENT_LEAVE_REMARK,
    PENDING_REQUEST_REMARK,
    UNPAID_LEAVE_REMARK,
    breakdown_flat_ord,
    breakdown_holiday_unworked,
    breakdown_not_computed,
    breakdown_ordinary_no_ot,
    breakdown_ordinary_ot,
    breakdown_premium,
)
from utils.app_config_user import get
from utils.file_utils import payroll_app_path, create_path

# Attendance Summary + Overtime Report
PREMIUMS_FILE_COUNT = 2

# Password prefix used for encrypted payroll files
_PASSWORD_PREFIX = get("PASSWORD_PREFIX", "")

# Output sheet name
_SHEET_NAME = "Payroll Premiums"

# Columns kept from the Attendance Summary (source name -> canonical name)
_ATT_COLUMNS = {
    "Employee ID":         "Employee ID",
    "Date":                "Date",
    "Clock In":            "Clock In",
    "Clock Out":           "Clock Out",
    "Shift":               "Shift",
    "Total Work Duration": "Total Work Hours",   # premium: Overtime is capped by this
    "Final Work Duration": "Final Work Hours",
    "Overtime":            "Overtime",
    "Policy":              "Policy",
    "Status_Unmand":       "Status Final",
    "Detailed Status":     "Detailed Status",
    "Is Late":             "Is Late",          # source header has a trailing space; _norm trims it
}

_OT_COLUMNS = {
    "Employee ID":                                  "Employee ID",
    "Overtime/Cto Application Shift Date":          "Date",
    "Overtime/Cto Application Start Date":          "OT Start Date",
    "Overtime/Cto Application Start Time":          "OT Start Time",
    "Overtime/Cto Application End Date":            "OT End Date",
    "Overtime/Cto Application End Time":            "OT End Time",
    "Request Status":                               "Request Status",
}

_FILENAME = ""


def _to_date(series: pd.Series) -> pd.Series:
    """Parse each value on its own (a column can mix "2026-10-01" and
    "2026-10-01 00:00:00"); unparseable values become NaT."""
    return pd.to_datetime(series.astype(str).str.strip(), errors="coerce", format="mixed")


def _norm(text) -> str:
    """Case / whitespace-insensitive header comparison key."""
    return re.sub(r"\s+", " ", str(text)).strip().lower()


class PayrollPremiumsTool:
    """
    Parameters
    ----------
    log         : Logger
        Shared Logger instance from the Orchestrator.
    main_window : MainWindow
        Used only as the file dialog's parent reference.
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

    def prepare_premium_files(self, id_names: list):
        """
        Start the Payroll Premiums file preparation flow.

        The dialog is deferred to the next Qt event-loop tick so the main
        window does not flash after the button click.
        """
        self.log.section("PAYROLL PREMIUMS FILE PREPARATION")
        self.log.info("PayrollPremiumsTool: Deferring file dialog to next event loop tick")
        QTimer.singleShot(0, lambda: self._open_and_process(id_names))

    # ===================================================================
    # STEP 1 — OPEN FILE DIALOG
    # ===================================================================

    def _open_and_process(self, id_names: list):
        """Open the file-picker and run the validation pipeline."""
        self.log.info("PayrollPremiumsTool: Opening file dialog")
        self._emit_progress(0, "Selecting files...")

        file_paths, _ = QFileDialog.getOpenFileNames(
            self.main_window,
            "Select Attendance Summary File",
            "",
            "Excel Files (*.xlsx *.xls)",
        )

        self.log.info(
            f"PayrollPremiumsTool: File dialog closed | "
            f"selected={len(file_paths)} expected={PREMIUMS_FILE_COUNT}"
        )

        if not file_paths:
            self.log.info("PayrollPremiumsTool: No files selected — aborting")
            self._emit_result("no_file_error")
            return

        if len(file_paths) > PREMIUMS_FILE_COUNT:
            self.log.warning(f"PayrollPremiumsTool: Too many files | got={len(file_paths)}")
            self._emit_result("file_exceed_error")
            return

        self._process_files(file_paths, id_names)

    # ===================================================================
    # STEP 2 — VALIDATION PIPELINE
    # ===================================================================

    def _process_files(self, file_paths: list, id_names: list):
        """
        Checks performed (in order)
        ---------------------------
        1. Read / decrypt each file.
        2. Identify the files by name.
        3. Employee ID present in row 1 (renamed "Employee ID").
        4. Required columns present; keep only those columns.
        5. Date column parseable (currently disabled).
        """
        self._emit_progress(5, "Reading files...")
        QApplication.processEvents()
        dataframes = self._read_files(file_paths)

        read_errors = [
            f"{file}|{status}"
            for file, status in dataframes.items()
            if not isinstance(status, pd.DataFrame)
        ]
        if read_errors:
            self.log.warning(f"PayrollPremiumsTool: Read failed | errors={read_errors}")
            self._emit_result(read_errors)
            return

        self._emit_progress(15, "Checking file identity...")
        identity_errors = self._check_file_identity(dataframes)
        if identity_errors:
            self._emit_result(identity_errors)
            return

        self._emit_progress(20, "Normalising employee ids...")
        self._normalise_employee_id(dataframes, id_names)

        self._emit_progress(25, "Checking required columns...")
        self._select_columns(dataframes)

        self._emit_progress(30, "Checking dates...")
        # self._check_dates(dataframes)

        error_codes = [
            code
            for file, status in dataframes.items()
            if not isinstance(status, pd.DataFrame)
            for code in (status if isinstance(status, list) else [f"{file}|{status}"])
        ]
        if error_codes:
            self.log.warning(f"PayrollPremiumsTool: Validation failed | errors={error_codes}")
            self._emit_result(error_codes)
            return

        self.log.info("PayrollPremiumsTool: Files validated — handing off to Orchestrator")
        self._emit_result("file_success")
        self._emit_files(dataframes)

    # ===================================================================
    # VALIDATION HELPERS
    # ===================================================================

    def _read_files(self, file_paths: list) -> dict:
        """
        Read each file into a DataFrame (row 1 = headers), decrypting if
        needed.  Unreadable files map to the "sensitivity_error" code.
        """
        dataframes = {}
        year       = datetime.now().year

        for file_path in file_paths:
            filename = Path(file_path).name
            self.log.info(f"PayrollPremiumsTool: Reading file | file={filename}")

            try:
                dataframes[filename] = pd.read_excel(file_path, dtype=str)
                continue
            except Exception:
                pass  # fall through to decryption attempt

            try:
                decrypted = io.BytesIO()
                with open(file_path, "rb") as f:
                    office_file = msoffcrypto.OfficeFile(f)
                    office_file.load_key(password=f"{_PASSWORD_PREFIX}{year}")
                    office_file.decrypt(decrypted)
                decrypted.seek(0)
                dataframes[filename] = pd.read_excel(decrypted, dtype=str)
            except Exception as e:
                self.log.warning(
                    f"PayrollPremiumsTool: Failed to read or decrypt | "
                    f"file={filename} error={e}"
                )
                dataframes[filename] = "sensitivity_error"

        return dataframes

    @staticmethod
    def _is_attendance_summary(name: str) -> bool:
        is_att_name = "attendance summary" in re.sub(r"[^a-z0-9]+", " ", name.lower())
        if is_att_name:
            global _FILENAME
            _FILENAME = name
            return True
        return False

    @staticmethod
    def _is_ot(name: str) -> bool:
        lowered = name.lower()
        if "report" in lowered and "overtime" in lowered:
            return True
        tokens = re.split(r"[^a-z0-9]+", lowered)
        return "report" in tokens and "overtime" in tokens

    def _identify_files(self, dataframes: dict):
        """Return (ot_name, att_name). Either may be None."""
        att_name = next((n for n in dataframes if self._is_attendance_summary(n)), None)
        ot_name  = next(
            (n for n in dataframes if self._is_ot(n) and n != att_name), None
        )
        return ot_name, att_name

    def _check_file_identity(self, dataframes: dict) -> list:
        """Flag each missing role explicitly ("ot_error" / "attendance_error")."""
        ot_name, att_name = self._identify_files(dataframes)
        errors = []

        if ot_name is None:
            self.log.warning("PayrollPremiumsTool: Overtime file is missing")
            errors.append("ot_error")
        if att_name is None:
            self.log.warning("PayrollPremiumsTool: Attendance file is missing")
            errors.append("attendance_error")

        if not errors:
            self.log.info(
                f"PayrollPremiumsTool: Files identified | "
                f"overtime={ot_name} attendance={att_name}"
            )
        return errors

    def _normalise_employee_id(self, dataframes: dict, id_names: list):
        """
        Rename the Employee ID column in row 1 to "Employee ID" (fuzzy
        match against id_names, cutoff=0.6).  No match -> "missing_header_error".
        """
        for file_, content in dataframes.items():
            if not isinstance(content, pd.DataFrame):
                continue

            for id_name in id_names:
                match = get_close_matches(id_name, list(content.columns), n=1, cutoff=0.6)
                if match:
                    content.rename(columns={match[0]: "Employee ID"}, inplace=True)
                    self.log.info(
                        f"PayrollPremiumsTool: Renamed Employee ID column | "
                        f"file={file_} from='{match[0]}' to='Employee ID'"
                    )
                    break
            else:
                self.log.warning(
                    f"PayrollPremiumsTool: No Employee ID column found | file={file_}"
                )
                dataframes[file_] = "missing_header_error"

    def _select_columns(self, dataframes: dict):
        """
        Keep only the needed columns (canonical names, matched ignoring
        case / extra spaces). Missing columns become a
        "<file> — Missing column(s): ...|missing_columns_error" code list.
        """
        ot_name, att_name = self._identify_files(dataframes)

        for name, wanted, label in (
            (ot_name, _OT_COLUMNS, "Overtime file"),
            (att_name, _ATT_COLUMNS, "Attendance file"),
        ):
            df = dataframes[name]
            if not isinstance(df, pd.DataFrame):
                continue

            lookup = {}
            for col in df.columns:
                lookup.setdefault(_norm(col), col)  # first occurrence wins

            missing = [k for k in wanted if _norm(k) not in lookup]
            if missing:
                self.log.warning(
                    f"PayrollPremiumsTool: Missing columns | file={name} missing={missing}"
                )
                dataframes[name] = [
                    f"{label} — Missing column(s): {', '.join(missing)}|missing_columns_error"
                ]
                return

            trimmed = df[[lookup[_norm(k)] for k in wanted]].copy()
            trimmed.columns = list(wanted.values())

            # OT file: keep only Approved requests
            if name == ot_name and "Request Status" in trimmed.columns:
                before_count = len(trimmed)
                trimmed = trimmed[
                    trimmed["Request Status"].astype(str).str.strip().str.lower().eq("approved")
                ].copy()
                self.log.info(
                    f"PayrollPremiumsTool: Filtered OT rows by Request Status "
                    f"| before={before_count} after={len(trimmed)}"
                )

            if name == att_name and "Final Work Hours" in trimmed.columns:
                # Hours is always in whole seconds (08:00:00 -> 28800).
                # Final Work Duration already has the 1-hour break deducted.
                trimmed["Hours"] = (
                    trimmed["Final Work Hours"].map(parse_duration).map(duration_to_seconds)
                )

            dataframes[name] = trimmed
            self.log.info(
                f"PayrollPremiumsTool: Columns kept | file={name} "
                f"cols={list(wanted.values())} rows={len(trimmed)}"
            )

    def _check_dates(self, dataframes: dict):
        """Every non-blank Date / Shift Date value must parse as a date."""
        ot_name, att_name = self._identify_files(dataframes)
        for name, col in ((ot_name, "Date"), (att_name, "Shift Date")):
            df = dataframes[name]
            if not isinstance(df, pd.DataFrame):
                continue
            raw    = df[col].astype(str).str.strip()
            filled = ~raw.isin({"", "nan", "NaT", "None"})
            parsed = _to_date(raw[filled])
            if parsed.isna().any():
                self.log.warning(
                    f"PayrollPremiumsTool: Unparseable dates | file={name} col={col} "
                    f"count={int(parsed.isna().sum())}"
                )
                dataframes[name] = "date_format_error"

    # ===================================================================
    # EMIT HELPERS
    # ===================================================================

    def _emit_result(self, codes):
        """Fire on_result with a normalised list of status codes."""
        if not self.on_result:
            self.log.warning(
                "PayrollPremiumsTool: on_result callback not wired — result dropped"
            )
            return
        normalized = list(codes) if isinstance(codes, (list, tuple)) else [codes]
        self.log.info(f"PayrollPremiumsTool: Emitting result codes | codes={normalized}")
        self.on_result(normalized)

    def _emit_files(self, files: dict):
        """Fire uploaded_files with the validated DataFrames."""
        if not self.uploaded_files:
            self.log.warning(
                "PayrollPremiumsTool: uploaded_files callback not wired — files dropped"
            )
            return
        self.log.info(
            f"PayrollPremiumsTool: Handing files to Orchestrator | "
            f"files={list(files.keys())}"
        )
        self.uploaded_files(files)

    def _emit_progress(self, percent: int, message: str):
        """Fire on_progress to update the UI progress bar."""
        if not self.on_progress:
            return
        self.log.info(f"PayrollPremiumsTool: Progress | {percent}% — {message}")
        self.on_progress(percent, message)

    # ===================================================================
    # GENERATE — PUBLIC ENTRY POINT CALLED BY ORCHESTRATOR
    # ===================================================================

    def generate(self, files: dict, lists) -> str:
        """holidays -> capping -> breakdown -> export. Returns the output path."""
        self.log.section("PAYROLL PREMIUMS GENERATION")
        ot_name, att_name = self._identify_files(files)

        self._emit_progress(35, "Fetching Holidays…")
        holidays = self.get_holidays(lists)

        self._emit_progress(40, "Capping work hours…")
        files[att_name] = self._capping_work_hours(files[att_name].copy())

        self._emit_progress(55, "Breaking down work hours into payroll headers…")
        breakdown = self._compute_breakdown(files[att_name].copy(), files[ot_name].copy(), holidays)

        return self._temp_export_prepared(breakdown)

    # ===================================================================
    # GET HOLIDAYS FROM SHAREPOINT LIST
    # ===================================================================

    def get_holidays(self, lists) -> pd.DataFrame:
        """
        Read the holiday list and return Active = Yes rows as
        DataFrame[Date, Holiday Type]. Duplicate dates -> list of types.
        """
        df = lists.to_dataframe()

        # Graph returns INTERNAL names ("Holiday_x0020_Type") -> display names
        df.columns = [str(c).replace("_x0020_", " ") for c in df.columns]

        missing = [c for c in ("field_1", "field_2", "field_4") if c not in df.columns]
        if missing:
            raise UserWarning(f"Holiday list is missing column(s): {', '.join(missing)}")

        df = df.rename(columns={
            "field_1": "Date",
            "field_2": "Holiday Type",
            "field_4": "Active",
        })

        # Active may be a Yes/No column (True/False) or a Choice ("Yes")
        active = df["Active"].astype(str).str.strip().str.lower().isin({"yes", "true", "1"})
        out = df.loc[active, ["Date", "Holiday Type"]].copy()

        out["Date"] = (
            pd.to_datetime(out["Date"], errors="coerce")
            .dt.tz_localize(None)
            .dt.normalize()
        )
        out = out.dropna(subset=["Date"])

        out = out.groupby("Date", as_index=False)["Holiday Type"].agg(list)

        dup_dates = out["Holiday Type"].apply(len).gt(1).sum()
        if dup_dates:
            self.log.info(
                f"PayrollPremiumsTool: Found {dup_dates} date(s) with multiple holiday types"
            )

        self.log.info(f"PayrollPremiumsTool: Holidays loaded | active_rows={len(out)}")
        return out

    # ===================================================================
    # CAPPING
    # ===================================================================

    def _capping_work_hours(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Cap Hours (paid, break already deducted). Hours is in seconds.
        The cap trims the END of the day; the break position does not move.

        Rules:
        - Status Final contains 'Half Day Unpaid Leave' and Hours > 4h -> 14400
        - No Overtime and Hours > 8h                                   -> 28800
        """
        df = df[df["Employee ID"].astype(str).str.startswith("IE0-", na=False)].copy()

        if "Detailed Remarks" not in df.columns:
            df["Detailed Remarks"] = ""

        for idx, row in df.iterrows():
            hours  = seconds_to_duration(row.get("Hours"))
            status = str(row.get("Status Final", "")).strip()

            if "Half Day Unpaid Leave" in status and hours > timedelta(hours=MAX_HALF_DAY_HOURS):
                df.at[idx, "Hours"] = cap_seconds(row.get("Hours"), MAX_HALF_DAY_HOURS)
                df.at[idx, "Detailed Remarks"] = "Half Day Unpaid Cap"
                df.at[idx, "Overtime"] = cap_seconds(row.get("Overtime"), 0)

            elif not has_overtime(row.get("Overtime")) and hours > timedelta(hours=MAX_ORDINARY_HOURS):
                df.at[idx, "Hours"] = cap_seconds(row.get("Hours"), MAX_ORDINARY_HOURS)
                df.at[idx, "Detailed Remarks"] = "Ordinary Capped"

        return df

    # ===================================================================
    # BREAKDOWN — routes each row to its scenario
    # ===================================================================

    @staticmethod
    def _compute_breakdown(att_df: pd.DataFrame, ot_df: pd.DataFrame, holidays: pd.DataFrame) -> pd.DataFrame:
        """
        Route each row to its scenario (first match wins):
            0. Detailed Status "Request Pending" -> not computed, remark "Pending Request"
            1. Present + Weekly Off / Holiday    -> breakdown_premium (RD / Holiday / RD + Holiday)
            2. Holiday, not Present / Weekly Off -> breakdown_holiday_unworked (Ord 8)
            3. Unpaid Leave, not Present         -> SKIPPED: Unpaid Leave
            3b. Present + Leave                  -> Ord 8, remark "Leave"
            3c. Half Day Leave + Half Day Unpaid -> Ord 4
            4. Overtime, not Present             -> CHECK: Overtime without Present status
            5. Ord day, no OT / with OT          -> breakdown_ordinary_no_ot / _ot
            6. anything else (e.g. Weekly Off,Holiday) -> SKIPPED with remark (row kept in output)
        """
        holiday_lookup = build_holiday_lookup(holidays)
        ot_lookup = build_ot_lookup(ot_df)
        rest_day_lookup = build_rest_day_lookup(att_df)   # OT on a weekly off date -> RD
        results = []

        for _, row in att_df.iterrows():

            id = row.get("Employee ID")
            date = row.get("Date")

            if id == "IE0-063":
                pass

            # 0. Pending request (Detailed Status) -> skip until resolved
            if is_request_pending(row):
                results.append(breakdown_not_computed(row, PENDING_REQUEST_REMARK))
                continue

            # 1. RD / Holiday / RD + Holiday -> Status Final Present + Weekly Off / Holiday
            scenario = get_status_scenario(row)
            if scenario:
                results.append(breakdown_premium(row, scenario, holiday_lookup, rest_day_lookup, get_ot_windows(row, ot_lookup)))
                continue

            # 2. Holiday, not Present, not Weekly Off -> Ord 8
            if is_unworked_holiday(row):
                results.append(breakdown_holiday_unworked(row, holiday_lookup))
                continue

            # 3. Unpaid Leave -> not paid even with logs
            if is_unpaid_leave(row):
                results.append(breakdown_not_computed(row, UNPAID_LEAVE_REMARK))
                continue

            # 3b. Present + Leave -> Ord 8
            if is_present_leave(row):
                results.append(breakdown_flat_ord(row, timedelta(hours=8), PRESENT_LEAVE_REMARK))
                continue

            # 3c. Half Day Leave + Half Day Unpaid Leave -> Ord 4 (paid half)
            if is_half_leave_half_unpaid(row):
                results.append(breakdown_flat_ord(row, timedelta(hours=4), HALF_LEAVE_REMARK))
                continue

            # 4. Overtime without Present (e.g. "Weekly Off,Request") -> flag, not computed
            if not is_present(row) and has_overtime(row.get("Overtime")):
                results.append(breakdown_not_computed(row, OT_WITHOUT_PRESENT_REMARK, valid=False))
                continue

            # 5. Ord
            day_code = get_day_code(parse_work_date(row.get("Date")), holiday_lookup)
            has_ot   = has_overtime(row.get("Overtime"))

            if day_code == ORDINARY_CODE and not has_ot:
                results.append(breakdown_ordinary_no_ot(row, holiday_lookup))
            elif day_code == ORDINARY_CODE and has_ot:
                results.append(breakdown_ordinary_ot(row, holiday_lookup, get_ot_windows(row, ot_lookup), rest_day_lookup))
            else:
                # Holiday date, not worked, no unworked-holiday pay (e.g. "Weekly Off,Holiday")
                results.append(breakdown_not_computed(row, f"SKIPPED: {day_code} not worked, no pay."))

        return pd.DataFrame(results).reset_index(drop=True)

    # ===================================================================
    # EXPORT (TEMPORARY until the final output layout is set)
    # ===================================================================

    def _temp_export_prepared(self, df: pd.DataFrame) -> str:
        """Prepare values -> write -> format. No formatting logic here."""
        self._emit_progress(70, "Writing workbook…")

        output_path = (
            create_path(payroll_app_path() / "Tools")
            / _FILENAME.replace("Attendance_Summary", "Payroll_Premiums")
        )

        df = prepare_export_frame(df)
        df.to_excel(output_path, sheet_name=_SHEET_NAME, index=False)
        format_workbook(output_path, _SHEET_NAME, time_columns={"Hours", *ALL_HEADERS})

        self.log.info(
            f"PayrollPremiumsTool: Payroll Premiums exported (TEMP) | path={output_path} rows={len(df)}"
        )
        self._emit_progress(100, "Done")
        return str(output_path)
