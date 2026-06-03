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

from utils.file_utils import app_data_path
from utils.app_config_user import get
from services.sharepoint_service import SharePointService


class FileManager:

    def __init__(self, log, managed_folders: list):

        self.log             = log
        self.sp_base_url     = get("SP_BASE_URL", "")
        self.managed_folders = managed_folders
        self._data_root      = os.path.join(app_data_path(), "data")
        self._archive_root   = os.path.join(self._data_root, "archive")

        self.log.info(f"FileManager: Ready | folders={managed_folders} root={self._data_root}")

    # -------------------------------------------------------------------------
    # 1. SORT AND ARCHIVE

    def sort_and_archive(self) -> dict:
        """
        Moves yesterday's (and older) files into the archive tree.
        Returns a count dict: {moved, skipped, failed}.
        """
        self.log.section("FILE ARCHIVE")
        self.log.info("FileManager: Starting archive pass")

        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        counts    = {"moved": 0, "skipped": 0, "failed": 0}

        for folder_name in self.managed_folders:
            folder_path = os.path.join(self._data_root, folder_name)

            if not os.path.exists(folder_path):
                self.log.info(f"FileManager: Folder missing, skipping | {folder_name}")
                continue

            self.log.info(f"FileManager: Scanning | {folder_name}")

            for file_name in os.listdir(folder_path):
                file_path = os.path.join(folder_path, file_name)

                if not os.path.isfile(file_path):
                    continue

                file_date = self._parse_file_date(file_name)

                if file_date is None:
                    # No embedded timestamp — leave it alone
                    self.log.debug(f"FileManager: No date in filename, skipping | {file_name}")
                    counts["skipped"] += 1
                    continue

                if file_date.strftime("%Y-%m-%d") == today_str:
                    counts["skipped"] += 1
                    continue

                target_dir = os.path.join(
                    self._archive_root,
                    file_date.strftime("%Y"),
                    file_date.strftime("%m"),
                    file_date.strftime("%d"),
                    folder_name,
                )
                moved = self._move_file(file_path, target_dir, file_name)
                counts["moved" if moved else "failed"] += 1

        self.log.result(
            step="sort_and_archive",
            success=(counts["failed"] == 0),
            detail=f"moved={counts['moved']} skipped={counts['skipped']} failed={counts['failed']}",
        )
        return counts

    # -------------------------------------------------------------------------
    # 2. UPLOAD LOG

    def upload_log(self, state: dict) -> bool:
        """
        Uploads today's session log to SharePoint.
        Silently returns False if any prerequisite is missing.
        """
        self.log.section("LOG UPLOAD")
        self.log.info("FileManager: Uploading session log")

        if not self.sp_base_url:
            self.log.warning("FileManager: SP_BASE_URL not set — skipping")
            return False

        token = state.get("token")
        if not token:
            self.log.warning("FileManager: No token in state — skipping")
            return False

        config     = state.get("config") or {}
        log_folder = config.get("log_folder")
        if not log_folder:
            self.log.warning("FileManager: log_folder missing from config — skipping")
            return False

        log_file_path = self._resolve_log_file()
        if not log_file_path:
            self.log.warning("FileManager: No log file found for today — skipping")
            return False

        try:
            with open(log_file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            self.log.warning(f"FileManager: Couldn't read log file — {e}", error=e)
            return False

        log_file_name = os.path.basename(log_file_path)
        date_path     = datetime.datetime.now().strftime("%Y/%m/%d")
        url           = f"{self.sp_base_url}root:/{log_folder}/{date_path}/{log_file_name}:/content"

        self.log.info(f"FileManager: Uploading | {log_file_name} → {log_folder}/{date_path}")

        try:
            response = SharePointService(token).put_file(url=url, data=content, content_type="text/plain")
        except requests.exceptions.Timeout:
            self.log.warning("FileManager: Upload timed out")
            return False
        except Exception as e:
            self.log.warning(f"FileManager: Upload failed — {e}", error=e)
            return False

        success = 200 <= response.status_code < 300
        self.log.result("upload_log", success=success, detail=f"HTTP {response.status_code}")
        return success

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
        """
        Finds today's session log file in the logs directory.
        Returns the full path, or None if nothing matches.
        """
        logs_dir  = os.path.join(self._data_root, "logs")
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")

        if not os.path.exists(logs_dir):
            return None

        for file_name in os.listdir(logs_dir):
            file_path = os.path.join(logs_dir, file_name)
            if not os.path.isfile(file_path):
                continue
            parsed_date = self._parse_file_date(file_name)
            if parsed_date and parsed_date.strftime("%Y-%m-%d") == today_str:
                return file_path

        return None
