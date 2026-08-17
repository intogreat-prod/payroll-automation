"""
file_manager.py — local file housekeeping and log upload.

Two jobs:

1. sort_and_archive()
   Runs on every app launch. Moves any log or validation file from a
   previous day into a dated archive folder:
       <app_data>/data/archive/YYYY/MM/DD/<folder>/

   Files are identified by the timestamp embedded in their name
   (<prefix>_YYYYMMDD_HHMMSS.<ext>). Anything that doesn't match
   that pattern is left alone.

2. upload_log()
   Runs on normal close and after any crash. Uploads the current
   session log to SharePoint so the team can check it remotely.
"""

import os
import shutil
import datetime
import requests
from pathlib import Path

from utils.file_utils import app_data_path
from utils.app_config_user import get
from services.sharepoint_service import SharePointService


class FileManager:

    def __init__(self, log):
        self.log             = log
        self.sp_base_url     = get("SP_BASE_URL", "")
        self.exclude_folder  = ["archive", "auth"]
        self._data_root      = os.path.join(app_data_path(), "data")
        self._archive_root   = os.path.join(self._data_root, "archive")

        self.log.info(
            f"FileManager: Ready | exclude={self.exclude_folder} "
            f"root={self._data_root}"
        )


    # -------------------------------------------------------------------------
    # 1. SORT AND ARCHIVE

    def sort_and_archive(self) -> dict:
        """
        Recursively moves yesterday's (and older) files into the archive tree.

        The configured exclude folder is never processed.

        The original directory structure is preserved under:

            archive/YYYY/MM/DD/<relative path>

        Returns:
            {
                "moved": int,
                "skipped": int,
                "failed": int
            }
        """
        self.log.section("FILE ARCHIVE")
        self.log.info("FileManager: Starting archive pass")

        today = datetime.datetime.now().date()

        counts = {
            "moved": 0,
            "skipped": 0,
            "failed": 0,
        }

        if not os.path.exists(self._data_root):
            self.log.info(
                f"FileManager: Data root missing | {self._data_root}"
            )
            return counts

        for root, dirs, files in os.walk(self._data_root):
            # Prevent the archive itself from being scanned.
            dirs[:] = [
                directory
                for directory in dirs
                if directory not in 
                    self.exclude_folder or directory
                    and directory != os.path.basename(self._archive_root)
            ]

            for file_name in files:
                file_path = os.path.join(root, file_name)

                file_date = self._parse_file_date(file_name)

                if file_date is None:
                    self.log.debug(
                        f"FileManager: No date in filename, skipping | {file_name}"
                    )
                    counts["skipped"] += 1
                    continue

                if file_date.date() == today:
                    counts["skipped"] += 1
                    continue

                # Path relative to data root.
                relative_dir = os.path.relpath(root, self._data_root)

                # Preserve original folder tree inside archive.
                target_dir = os.path.join(
                    self._archive_root,
                    file_date.strftime("%Y"),
                    file_date.strftime("%m"),
                    file_date.strftime("%d"),
                    relative_dir,
                )

                moved = self._move_file(
                    file_path,
                    target_dir,
                    file_name,
                )

                counts["moved" if moved else "failed"] += 1

        self.log.result(
            step="sort_and_archive",
            success=(counts["failed"] == 0),
            detail=(
                f"moved={counts['moved']} "
                f"skipped={counts['skipped']} "
                f"failed={counts['failed']}"
            ),
        )

        return counts

    # -------------------------------------------------------------------------
    # 2. UPLOAD LOG
    def _upload_single_file(self, state: dict, file_path: Path) -> bool:
        if not self.sp_base_url:
            self.log.warning("FileManager: SP_BASE_URL not set — skipping")
            return False
        
        token = state.get("token")
        if not token:
            self.log.warning("FileManager: No token in state — skipping")
            return False
        
        config     = state.get("app_config") or {}
        log_folder = config.get("log_folder")
        
        if not log_folder:
            self.log.warning("FileManager: log_folder missing from config — skipping")
            return False
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            self.log.warning(f"FileManager: Couldn't read log file — {e}", error=e)
            return False
        
        file_date = self._parse_file_date(file_path.name) or datetime.datetime.now()
        date_path = file_date.strftime("%Y/%m/%d")

        url       = f"{self.sp_base_url}root:/{log_folder}/{date_path}/{file_path.name}:/content"
        self.log.info(f"FileManager: Uploading | {file_path.name} → {log_folder}/{date_path}")
        
        try:
            response = SharePointService(token).put_file(url=url, data=content, content_type="text/plain")
        except requests.exceptions.Timeout:
            self.log.warning("FileManager: Upload timed out")
            return False
        except Exception as e:
            self.log.warning(f"FileManager: Upload failed — {e}", error=e)
            return False
        
        success = 200 <= response.status_code < 300
        self.log.result("upload_single_file", success=success, detail=f"{file_path.name} → HTTP {response.status_code}")

        return success
    
    def upload_log(self, state: dict):
        """
        Uploads today's session log to SharePoint.
        Returns (success: bool, filename: str | None).
        """
        self.log.section("LOG UPLOAD")
        self.log.info("FileManager: Uploading session log")
        log_file_path = self._resolve_log_file()

        if not log_file_path:
            self.log.warning("FileManager: No log file found for today — skipping")
            return False, None
        
        file_path = Path(log_file_path)
        success = self._upload_single_file(state, file_path)
        return success, file_path.name

    def upload_logs_range(self, state: dict, start_date, end_date) -> dict:
        self.log.section("LOG UPLOAD — RANGE")
        self.log.info(f"FileManager: Uploading logs | {start_date} → {end_date}")

        if start_date > end_date:
            start_date, end_date = end_date, start_date

        counts = {"uploaded": 0, "failed": 0, "filename":f"{start_date} - {end_date}"}
        current_date = start_date

        while current_date <= end_date:
            files = self._files_for_date(current_date)
            if not files:
                self.log.debug(f"FileManager: No logs found | {current_date}")
            for file_path in files:
                success = self._upload_single_file(state, file_path)
                counts["uploaded" if success else "failed"] += 1
            current_date += datetime.timedelta(days=1)

        self.log.result(
            step="upload_logs_range",
            success=(counts["failed"] == 0),
            detail=f"uploaded={counts['uploaded']} failed={counts['failed']}"
        )

        return counts

    def _files_for_date(self, target_date):
        today = datetime.datetime.now().date()
        if target_date == today:
            folder = Path(self._data_root) / "logs"
        else:
            folder = (
                Path(self._archive_root)
                / target_date.strftime("%Y")
                / target_date.strftime("%m")
                / target_date.strftime("%d")
                / "logs"
            )

        if not folder.exists():
            return []
        
        matches = []
        for f in sorted(folder.iterdir()):
            if not f.is_file():
                continue
            
            file_date = self._parse_file_date(f.name)
            if file_date and file_date.date() == target_date:
                matches.append(f)

        return matches
    # -------------------------------------------------------------------------
    # Private helpers

    def _parse_file_date(self, file_name: str) -> datetime.datetime | None:
        """
        Extracts a datetime from a filename ending in _YYYYMMDD_HHMMSS.<ext>.
        Returns None if it doesn't match.
        """
        try:
            base  = os.path.splitext(file_name)[0]
            parts = base.split("_")
            return datetime.datetime.strptime(parts[-2] + parts[-1], "%Y%m%d%H%M%S")
        except Exception:
            return None

    def _move_file(self, src: str, target_dir: str, file_name: str) -> bool:
        """Moves a file, creating the target directory if needed. Returns True on success."""
        try:
            os.makedirs(target_dir, exist_ok=True)
            shutil.move(src, os.path.join(target_dir, file_name))
            self.log.info(f"FileManager: Moved | {file_name} → {target_dir}")
            return True
        except Exception as e:
            self.log.warning(f"FileManager: Move failed | {file_name} — {e}", error=e)
            return False

    def _resolve_log_file(self) -> str | None:
        logs_dir  = os.path.join(self._data_root, "logs")
        today     = datetime.datetime.now().date()

        if not os.path.exists(logs_dir):
            return None
        candidates = []

        for file_name in os.listdir(logs_dir):
            file_path = os.path.join(logs_dir, file_name)

            if not os.path.isfile(file_path):
                continue

            parsed_date = self._parse_file_date(file_name)
            if parsed_date and parsed_date.date() == today:
                candidates.append((parsed_date, file_path))

        if not candidates:
            return None
        
        candidates.sort(key=lambda pair: pair[0])
        return candidates[-1][1]   # latest timestamp for today

    def delete_folder(self, loc: str) -> bool:
        """Deletes a folder and all of its contents."""
        try:
            if not os.path.isdir(loc):
                self.log.warning(f"FileManager: Folder not found — {loc}")
                return False

            shutil.rmtree(loc)

            self.log.info(f"FileManager: Folder deleted — {loc}")
            return True

        except Exception as e:
            self.log.warning(
                f"FileManager: Failed to delete folder — {loc} | {e}",
                error=e
            )
            return False