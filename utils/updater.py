"""
updater.py — checks for a newer version on GitHub Releases and downloads it.
Uses a Personal Access Token stored in Credential Manager to access the
private repo. The token only needs Contents: Read-only permission.
"""

import os
import sys
import time
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests
from PyQt6.QtCore import QThread, pyqtSignal

from utils.app_config_user import get

# Your private GitHub repo
GITHUB_REPO = "intogreat-prod/payroll-automation"
_API_URL     = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def _get_token() -> str:
    """Reads the GitHub PAT from Credential Manager."""
    try:
        return get("GH_PAT")
    except Exception:
        return ""


def _auth_headers() -> dict:
    """Returns the Authorization header for GitHub API calls."""
    token = _get_token()
    if not token:
        return {"Accept": "application/vnd.github+json"}
    return {
        "Authorization": f"Bearer {token}",
        "Accept":        "application/vnd.github+json",
    }


def get_current_version() -> str:
    return get("VERSION", "0.0.0")


def get_latest_release() -> tuple[str, str] | None:
    """
    Calls the GitHub API and returns (version_tag, asset_id).
    Returns None on any failure — never blocks the app.
    """
    try:
        response = requests.get(_API_URL, headers=_auth_headers(), timeout=5)
        if response.status_code != 200:
            return None
        data   = response.json()
        tag    = data.get("tag_name", "").lstrip("v")
        assets = data.get("assets", [])
        asset  = next(
            (a for a in assets if a["name"].endswith("_Setup.exe")),
            None,
        )
        if not tag or not asset:
            return None
        return tag, str(asset["id"]), data["body"]
    except Exception:
        return None


def is_newer(latest: str, current: str) -> bool:
    try:
        return (
            tuple(int(x) for x in latest.split(".")) >
            tuple(int(x) for x in current.split("."))
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# QThread worker — download + launch installer with progress reporting
# ---------------------------------------------------------------------------

class DownloadWorker(QThread):
    progress = pyqtSignal(int, str)   # percent, message
    finished = pyqtSignal(bool, str)

    def __init__(self, asset_id: str, log, file_manager, state: dict):
        super().__init__()
        self.asset_id     = asset_id
        self.log          = log
        self.file_manager = file_manager
        self.state        = state
        self.app_loc      = get("installation_loc") + "/Finance Suite.exe"

    def run(self):
        tmp_dir = None
        try:
            self.log.info(f"Updater: Downloading asset {self.asset_id}")

            url = (
                f"https://api.github.com/repos/{GITHUB_REPO}"
                f"/releases/assets/{self.asset_id}"
            )
            headers = {
                **_auth_headers(),
                "Accept": "application/octet-stream",
            }

            response = requests.get(url, headers=headers, stream=True, timeout=60)
            response.raise_for_status()

            total      = int(response.headers.get("content-length", 0))
            downloaded = 0

            tmp_dir  = tempfile.mkdtemp()
            tmp_path = os.path.join(tmp_dir, "FinanceSuite_User_Setup.exe")

            self.progress.emit(0, "Starting download...")

            with open(tmp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        percent = int((downloaded / total) * 100)
                        self.progress.emit(percent, "Downloading update...")

            self.progress.emit(100, "Download complete...")
            self.log.info(f"Updater: Downloaded installer to {tmp_path}")
            # Installer launch + process exit now happen on the MAIN
            # thread (see Orchestrator._on_update_done). sys.exit() here
            # only ends this background thread, not the process — the
            # running app (and its lock on Finance Suite.exe) would
            # still be alive when Inno tries to overwrite it, causing
            # that file to silently fail to update.
            self.finished.emit(True, tmp_path)
            
        except Exception as e:
            self.log.warning(f"Updater: Download failed — {e}")
            self.finished.emit(False, "")
            if tmp_dir:
                try:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    self.log.info(f"Updater: Cleaned up temp directory {tmp_dir}")
                except Exception as e:
                    self.log.warning(f"Updater: Failed to clean up temp directory - {e}")
