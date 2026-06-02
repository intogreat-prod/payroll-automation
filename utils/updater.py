"""
updater.py — checks for a newer version on GitHub Releases and downloads it.
Called once at startup in Orchestrator.start(). If a newer version is
available, it downloads the installer to a temp folder and prompts the user.
Running the installer with /SILENT replaces the app in place — no manual
steps needed.
Set GITHUB_REPO to your repo in the format "owner/repo-name".
The version in the registry (written by setup_helper) is compared against
the latest GitHub Release tag.
"""
import os
import subprocess
import tempfile
import requests
from utils.app_config import get

# Your GitHub repo — change this
GITHUB_REPO = get("GITHUB_REPO")
# GitHub API endpoint for the latest release
_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

def get_current_version() -> str:
   """Reads the installed version from the registry."""
   return get("VERSION", "0.0.0")

def get_latest_release() -> tuple[str, str] | None:
   """
   Calls the GitHub API and returns (version_tag, installer_download_url).
   Returns None if the check fails for any reason — we never block the app
   over a failed update check.
   """
   try:
       response = requests.get(_API_URL, timeout=5)
       if response.status_code != 200:
           return None
       
       data    = response.json()
       tag     = data.get("tag_name", "").lstrip("v")  # "v1.2.0" → "1.2.0"
       assets  = data.get("assets", [])

       # Find the installer asset — named PayrollAutomation_Setup.exe
       url = next(
           (a["browser_download_url"] for a in assets
            if a["name"].endswith("_Setup.exe")),
           None
       )
       if not tag or not url:
           return None
       
       return tag, url
   except Exception:
       return None

def is_newer(latest: str, current: str) -> bool:
   """Simple tuple comparison — works for MAJOR.MINOR.PATCH format."""
   try:
       return tuple(int(x) for x in latest.split(".")) > \
              tuple(int(x) for x in current.split("."))
   
   except Exception:
       return False

def download_and_run(download_url: str, log) -> bool:
    """
    Downloads the installer to a temp folder and launches it with /VERYSILENT.
    Inno Setup's /VERYSILENT flag installs with no UI at all — the app is
    replaced in the background and the user just needs to relaunch.
    Returns True if the installer was launched, False on any failure.
    """
    try:
        log.info(f"Updater: Downloading installer from {download_url}")

        response = requests.get(download_url, stream=True, timeout=60)
        response.raise_for_status()

        # Write to a temp file — Windows will clean it up eventually
        tmp_dir  = tempfile.mkdtemp()
        tmp_path = os.path.join(tmp_dir, "PayrollAutomation_Setup.exe")

        with open(tmp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        log.info(f"Updater: Installer saved to {tmp_path} — launching")

        # /VERYSILENT   — no UI
        # /NORESTART    — don't reboot after install
        # /CLOSEAPPLICATIONS — close the running app before replacing files
        subprocess.Popen([tmp_path, "/VERYSILENT", "/NORESTART", "/CLOSEAPPLICATIONS"],close_fds=True)
        return True
    except Exception as e:
        log.warning(f"Updater: Failed to download or launch installer — {e}")
        return False