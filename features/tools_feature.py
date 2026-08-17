"""
tools_feature.py
-----------------
Suite Toolbox flow — Excel Locker.

Split out of orchestrator.py the same way as settings_feature.py: these
are plain functions taking `self` as the first argument, assigned onto
the Orchestrator class (see the bottom of orchestrator.py) so they run
as normal bound methods with full access to self.state / self.log /
self.body / self.main_window.

Async
-----
QFileDialog (open / save-as) has to run on the main GUI thread — Qt
doesn't allow it from a QThread. So _lock_excel() resolves every
dialog up front (which file(s), and — if "create a copy" is checked —
where to save each locked copy), then hands the actual work (read →
msoffcrypto encrypt → write, one file at a time) off to
_ExcelLockWorker, a background QThread. That's the part that was
actually blocking the UI on a big batch, and it's the part that's now
async. Progress is reported back via a pyqtSignal, the same pattern
used by _ConfigWorker / _UpdateCheckWorker / DownloadWorker in
orchestrator.py.

Status codes
------------
Every result (success or error) is reported as (name, status_code),
where status_code keys into EXCEL_LOCKER_STATUSES in ui/statuses.py —
Body resolves the code to its display message. Nothing in this file
hardcodes user-facing text.
"""

import os
from datetime import datetime

import msoffcrypto
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QFileDialog

from utils.app_config_user import get


# ---------------------------------------------------------------------------
# Background worker — does the actual file read / encrypt / write
# ---------------------------------------------------------------------------

class _ExcelLockWorker(QThread):
    """
    Locks a batch of Excel files off the main thread.

    Parameters
    ----------
    jobs : list[dict]
        One entry per file to lock:
            {
                "file_path":   str,   source file
                "name":        str,   display name (basename)
                "password":    str,
                "output_path": str | None,  resolved save-as path
                                            (create_copy) or None
                                            (locked in place)
                "create_copy": bool,
            }
        All dialogs for these are already resolved before the worker
        starts — this loop does no UI work at all.
    preset_errors : list[tuple[str, str]]
        (name, status_code) pairs already known before the loop starts
        (e.g. "not listed in TXT file") — folded into the final error
        list and counted toward `total`.
    """

    progress = pyqtSignal(int, str)          # percent, message
    finished = pyqtSignal(int, int, list)    # total, locked, errors

    def __init__(self, jobs, preset_errors=None, log=None):
        super().__init__()
        self.jobs = jobs
        self.preset_errors = preset_errors or []
        self.log = log

    def run(self):
        locked = 0
        errors = list(self.preset_errors)
        total = len(self.jobs) + len(self.preset_errors)

        if not self.jobs:
            self.finished.emit(total, locked, errors)
            return

        step = 100 / len(self.jobs)

        for i, job in enumerate(self.jobs, start=1):
            name = job["name"]
            self.progress.emit(int((i - 1) * step), f"Locking {name}…")

            success, code = self._lock_one(job)
            if success:
                locked += 1
            else:
                errors.append((name, code))

            self.progress.emit(int(i * step), f"Locking {name}…")

        self.finished.emit(total, locked, errors)

    def _lock_one(self, job):
        """Returns (success: bool, status_code: str)."""
        file_path   = job["file_path"]
        password    = job["password"]
        create_copy = job["create_copy"]
        output_path = job["output_path"] if create_copy else file_path + ".tmp"

        if not password:
            return False, "no_password_error"

        try:
            with open(file_path, "rb") as input_file:
                office_file = msoffcrypto.OfficeFile(input_file)
                if office_file.is_encrypted():
                    if self.log:
                        self.log.error(
                            f"Failed to lock Excel file: {file_path} is already password-protected."
                        )
                    return False, "already_protected_error"

                with open(output_path, "wb") as output_file:
                    office_file.encrypt(password, output_file)

            if not create_copy:
                os.replace(output_path, file_path)

            return True, ""

        except Exception as e:
            if not create_copy and os.path.exists(output_path):
                os.remove(output_path)
            if self.log:
                self.log.error(f"Failed to lock Excel file: {file_path} - {e}")
            return False, "failed_to_lock_error"


# ---------------------------------------------------------------------------
# TOOLS MAIN FLOW — mixed into Orchestrator
# ---------------------------------------------------------------------------

def _default_password(self, password):
    """Return the given password, or a year-based default if empty."""
    if password:
        return password
    return get("PASSWORD_PREFIX") + str(datetime.now().year)


def _lock_excel(self, password, is_single, create_copy):
    """
    Resolve file dialogs on the main thread, then hand the locking
    work off to a background worker (_run_excel_lock_jobs).
    """
    self.log.section("EXCEL LOCKER")

    # ── Single File ───────────────────────────────────────────────────
    if is_single:
        password = self._default_password(password)

        file_path, _ = QFileDialog.getOpenFileName(
            self.main_window, "Select Excel File", "", "Excel Files (*.xlsx)"
        )
        if not file_path:
            return

        name = os.path.basename(file_path)
        output_path = None
        if create_copy:
            output_path, _ = QFileDialog.getSaveFileName(
                self.main_window, "Save Locked Excel File", file_path, "Excel Files (*.xlsx)"
            )
            if not output_path:
                return
            if not output_path.lower().endswith(".xlsx"):
                output_path += ".xlsx"
        # When a copy is created, the success message should name the
        # new locked copy, not the original source file.
        display_name = os.path.basename(output_path) if create_copy else name
        jobs = [{
            "file_path": file_path, "name": name, "password": password,
            "output_path": output_path, "create_copy": create_copy,
        }]
        self._run_excel_lock_jobs(jobs, single_file=True, single_name=display_name)
        return

    # ── Multiple Files ───────────────────────────────────────────────
    file_paths, _ = QFileDialog.getOpenFileNames(
        self.main_window,
        "Select Excel Files and Metadata",
        "",
        "Excel Files (*.xlsx);;Metadata Files (*.txt);;All Files (*.*)",
        "All Files (*.*)"
    )
    if not file_paths:
        return

    excel_files = [p for p in file_paths if p.lower().endswith(".xlsx")]
    txt_files   = [p for p in file_paths if p.lower().endswith(".txt")]

    if not excel_files:
        self.body.show_excel_locker_result(total=0, locked=0, errors=[("", "no_excel_error")])
        return

    # ── Case A: No TXT → Same Password For All ──────────────────────
    if not txt_files:
        password = self._default_password(password)
        file_entries = [(fp, os.path.basename(fp), password) for fp in excel_files]
        jobs, preset_errors = self._prepare_lock_jobs(file_entries, create_copy)
        self._run_excel_lock_jobs(jobs, preset_errors=preset_errors)
        return

    # ── Validate TXT Count ────────────────────────────────────────────
    if len(txt_files) > 1:
        self.body.show_excel_locker_result(
            total=0, locked=0, errors=[("", "multiple_txt_error")]
        )
        return

    metadata_file = txt_files[0]

    # ── Read TXT Into filename -> password Dictionary ────────────────
    password_map = {}
    try:
        with open(metadata_file, "r", encoding="utf-8") as file:
            lines = file.readlines()

        for line_number, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if not line:
                continue

            parts = line.rsplit(",", 1)
            if len(parts) != 2:
                self.body.show_excel_locker_result(
                    total=0, locked=0, errors=[(str(line_number), "invalid_format_error")]
                )
                return

            filename, file_password = parts[0].strip(), parts[1].strip()

            if not filename or not file_password:
                self.body.show_excel_locker_result(
                    total=0, locked=0, errors=[(str(line_number), "empty_entry_error")]
                )
                return

            if not filename.lower().endswith(".xlsx"):
                self.body.show_excel_locker_result(
                    total=0, locked=0, errors=[(filename, "invalid_filename_error")]
                )
                return

            if filename in password_map:
                self.body.show_excel_locker_result(
                    total=0, locked=0, errors=[(filename, "duplicate_entry_error")]
                )
                return

            password_map[filename] = file_password

    except Exception as e:
        self.body.show_excel_locker_result(
            total=0, locked=0, errors=[(str(e), "metadata_read_error")]
        )
        return

    # ── Case B: Match Selected Files Against the Dictionary ──────────
    selected_files = {os.path.basename(p): p for p in excel_files}

    matched = [
        (file_path, name, password_map[name])
        for name, file_path in selected_files.items()
        if name in password_map
    ]
    preset_errors = [
        (name, "not_listed_error")
        for name in selected_files if name not in password_map
    ]
    preset_errors += [
        (name, "not_uploaded_error")
        for name in password_map if name not in selected_files
    ]

    jobs, save_errors = self._prepare_lock_jobs(matched, create_copy)
    self._run_excel_lock_jobs(
        jobs,
        preset_errors=preset_errors + save_errors,
        total_override=len(selected_files),
    )


def _prepare_lock_jobs(self, file_entries, create_copy):
    """
    Resolve the save-as dialog (if create_copy is checked) for each
    file on the main thread and build the job list for the worker.

    file_entries : list[tuple[file_path, name, password]]

    Returns (jobs, errors) — a save-as cancellation for one file in a
    batch only drops that file (as a "save_cancelled_error"), it
    doesn't abort the rest of the batch.
    """
    jobs = []
    errors = []

    for file_path, name, password in file_entries:
        output_path = None
        if create_copy:
            output_path, _ = QFileDialog.getSaveFileName(
                self.main_window, f"Save Locked Copy — {name}", file_path, "Excel Files (*.xlsx)"
            )
            if not output_path:
                errors.append((name, "save_cancelled_error"))
                continue
            if not output_path.lower().endswith(".xlsx"):
                output_path += ".xlsx"

        jobs.append({
            "file_path": file_path, "name": name, "password": password,
            "output_path": output_path, "create_copy": create_copy,
        })

    return jobs, errors


def _run_excel_lock_jobs(self, jobs, preset_errors=None, single_file=False,
                          single_name=None, total_override=None):
    """Starts _ExcelLockWorker and wires its signals up to Body."""
    preset_errors = preset_errors or []

    self.body.show_excel_locker_progress(
        "Locking file…" if single_file else f"Locking {len(jobs)} file(s)…"
    )

    worker = _ExcelLockWorker(jobs, preset_errors=preset_errors, log=self.log)
    worker.progress.connect(lambda pct, msg: self.body.update_excel_locker_progress(pct, msg))
    worker.finished.connect(
        lambda total, locked, errors: self._on_excel_lock_finished(
            total_override if total_override is not None else total,
            locked, errors, single_file, single_name,
        )
    )
    worker.start()
    # Keep a reference so the QThread isn't garbage collected mid-flight
    self._excel_lock_worker = worker


def _on_excel_lock_finished(self, total, locked, errors, single_file, single_name):
    self.log.info(
        f"Excel Locker finished | total={total} locked={locked} errors={len(errors)}"
    )
    self.body.show_excel_locker_result(
        total=total, locked=locked, errors=errors,
        single_file=single_file, single_name=single_name,
    )


