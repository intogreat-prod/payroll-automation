"""
orchestrator.py
---------------
Single source of truth for app state and flow control.

Architecture
------------
    Orchestrator  →  calls body.show_*()  →  Body renders the screen
    Body          →  fires on_* callbacks →  Orchestrator handles the event

The UI (Body) never calls a service directly.
Services never touch the UI directly.

State dict
----------
All mutable session data lives in self.state so it can be serialised,
logged, and passed to services without coupling those services to this
class.  Keys:

    source        str | None   Selected data source ("Sprout" | "DarwinBox")
    feature       str | None   Active feature name
    logged_in     bool         True after successful MSAL login
    email         str | None   Authenticated user's email
    name          str | None   Authenticated user's display name
    token         str | None   Current MSAL Bearer token
    config        dict | None  Remote app configuration JSON
    folder_name   str | None   SharePoint folder path for the current upload
    guid          str | None   Unmand task GUID for status polling
    variance_file Path | None  Local path of the generated checker output
    version       str          Payroll version label, e.g. "v1"
    id            str          Payroll run ID (datetime stamp or user-supplied)
    month_year    str          Current month/year, e.g. "May 2026"
    current       str | None   Installed app version
    latest        str | None   Latest GitHub release version
"""

import io
import json
import os
import re
import sys
import webbrowser
import subprocess
from pathlib import Path
from datetime import datetime

import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal

from features.checker import CheckerFeature
from features.payroll import PayrollFeature
from features.dbx_to_sprout import DarwinToSproutTool
from features.attendance_summary import AttendanceSummaryTool
from services.config_service import ConfigService
from services.msal_service import MSALService
from services.outlook_services import OutlookService
from services.power_automate_service import PowerAutomateService
from services.sharepoint_service import SharePointService
from services.unmand_service import UnmandService
from ui.main_window import MainWindow
from ui.statuses import *
from utils.app_config_user import get
from utils.email_template import WELCOME_EMAIL
from utils.error_handler import register_global_handler
from utils.file_manager import FileManager
from utils.file_utils import app_data_path
from utils.internet import internet_available
from utils.logger import Logger
from utils.updater import DownloadWorker, get_current_version, get_latest_release, is_newer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(response) -> bool:
    """Returns True for any 2xx HTTP status code."""
    return 200 <= response.status_code < 300


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

class _ConfigWorker(QThread):
    """Fetches the remote config JSON off the main thread."""
    finished = pyqtSignal(object)   # requests.Response
    error    = pyqtSignal(str)

    def __init__(self, token: str):
        super().__init__()
        self.token = token

    def run(self):
        try:
            response = ConfigService().get(self.token)
            self.finished.emit(response)
        except Exception as e:
            self.error.emit(str(e))

class _UpdateCheckWorker(QThread):
    """Checks GitHub Releases for a newer version off the main thread."""
    finished = pyqtSignal(object)   # (latest_tag, asset_id) | None

    def __init__(self):
        super().__init__()

    def run(self):
        self.finished.emit(get_latest_release())

class _SharePointUploadWorker(QThread):
    """Uploads payroll CSV files to SharePoint off the main thread."""
    progress = pyqtSignal(int, str)     # current file name and progress
    finished = pyqtSignal(list)         # list of failed logical names (empty = all OK)

    def __init__(self, files: dict, sharepoint: SharePointService,
                 base_url: str, run_id: str, version: str, log):
        super().__init__()
        self.files      = files
        self.sharepoint = sharepoint
        self.base_url   = base_url
        self.run_id     = run_id
        self.version    = version
        self.log        = log

    def run(self):
        errors   = []
        progress = 0
        increment = 100 / len(self.files)

        for logical_name, df in self.files.items():
            progress += increment

            file_name = f"{logical_name}_{self.run_id}_{self.version}.csv"
            url       = f"{self.base_url}/{file_name}:/content"

            self.progress.emit(int(progress),file_name)
            self.log.info(f"SPUploadWorker: Uploading | name={file_name} | {url}")

            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False)

            response = self.sharepoint.put_file(
                url, data=csv_buffer.getvalue(), content_type="text/csv"
            )
            success = _ok(response)
            self.log.result(
                step=f"Upload {file_name}",
                success=success,
                detail=f"HTTP {response.status_code}",
            )
            if not success:
                errors.append(logical_name)

        self.finished.emit(errors)

class _ValidationWorker(QThread):
    """Runs the variance report generation off the main thread."""
    progress = pyqtSignal(int, str)           # percent, message
    finished = pyqtSignal(bool, object)       # success, file_path | error_code

    def __init__(self, files: dict, headers: list, source: str, var_tolerance,
                 log, checker):
        super().__init__()
        self.files         = files
        self.headers       = headers
        self.source        = source
        self.var_tolerance = var_tolerance
        self.log           = log
        self.checker       = checker

    def run(self):
        # Wire the checker's progress callback to this thread's signal
        self.checker.on_progress = lambda pct, msg: self.progress.emit(pct, msg)
        try:
            result = self.checker.generate(self.files, self.headers, self.source, self.var_tolerance)
            self.finished.emit(True, result)
        except Exception as e:
            self.log.error(f"ValidationWorker: Failed — {e}", error=e)
            self.finished.emit(False, "premium_download_error")
        finally:
            self.checker.on_progress = None

class _ArchiveWorker(QThread):
    """Runs sort_and_archive off the main thread on startup."""
    finished = pyqtSignal()

    def __init__(self, file_manager):
        super().__init__()
        self.file_manager = file_manager

    def run(self):
        self.file_manager.sort_and_archive()
        self.finished.emit()

class _DBXConversionWorker(QThread):
    """Runs the conversion to sprout off the main thread."""
    progress = pyqtSignal(int, str)           # percent, message
    finished = pyqtSignal(bool, object)       # success, file_path | error_code

    def __init__(self, files: dict, header_map: dict, log, dbx_to_sprout):
        super().__init__()
        self.files              = files
        self.header_map         = header_map
        self.log                = log
        self.dbx_to_sprout      = dbx_to_sprout

    def run(self):
        # Wire the tool's progress callback to this thread's signal
        self.dbx_to_sprout.on_progress = lambda pct, msg: self.progress.emit(pct, msg)
        try:
            result = self.dbx_to_sprout.generate(self.files, self.header_map)
            self.finished.emit(True, result)
        except Exception as e:
            self.log.error(f"_DBXConversionWorker: Failed — {e}", error=e)
            self.finished.emit(False, "premium_download_error")
        finally:
            self.dbx_to_sprout.on_progress = None

class _AttendanceSummaryWorker(QThread):
    """Runs attendance summary processing off the main thread."""
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, object)

    def __init__(self, files: dict, start_date: str, cutoff_date: str, log, att_summary):
        super().__init__()
        self.files       = files
        self.start_date  = start_date
        self.cutoff_date = cutoff_date
        self.log         = log
        self.att_summary = att_summary

    def run(self):
        self.att_summary.on_progress = lambda pct, msg: self.progress.emit(pct, msg)
        try:
            result = self.att_summary.generate(self.files, self.start_date, self.cutoff_date)
            self.finished.emit(True, result)
        except Exception as e:
            self.log.error(f"_AttendanceSummaryWorker: Failed — {e}", error=e)
            self.finished.emit(False, "processing_error")
        finally:
            self.att_summary.on_progress = None

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:

    def __init__(self):

        self.envt = get("ENVT", "DEV")

        # Logger is created first so every subsequent step is captured
        self.log = Logger(app_data_path())
        self.log.section("ORCHESTRATOR INIT")

        # -----------------------------------------------------------
        # App state  (all mutable session data lives here)
        # -----------------------------------------------------------
        now = datetime.now()
        self.state = {
            "current":       None,
            "latest":        None,
            "source":        None,
            "feature":       None,
            "menu":          None,
            "tool":          None,
            "logged_in":     False,
            "email":         None,
            "name":          None,
            "token":         None,
            "config":        None,
            "folder_name":   None,
            "guid":          None,
            "variance_file": None,
            "converted_file": None,
            "version":       "v1",
            "id":            now.strftime("%Y%m%d_%H%M%S"),
            "month_year":    now.strftime("%B %Y")
        }
        self.log.info(
            f"Orchestrator: State initialised | "
            f"id={self.state['id']} month={self.state['month_year']}"
        )

        # -----------------------------------------------------------
        # User inputs  (optional overrides supplied via the UI form)
        # -----------------------------------------------------------
        self.inputs = {"id": None, "version": None, "user": None}

        # -----------------------------------------------------------
        # Build the window — show it immediately before any heavy work
        # -----------------------------------------------------------
        self.log.info("Orchestrator: Building main window")
        self.main_window = MainWindow()
        self.body        = self.main_window.body
        self.header      = self.main_window.header
        self.footer      = self.main_window.footer

        # Wire UI callbacks → Orchestrator handlers
        self.header.on_clicked = self._handle_header_clicks
        self.body.on_clicked   = self._handle_body_clicks
        self.footer.on_clicked   = self._handle_footer_clicks
        self.log.info("Orchestrator: UI callbacks wired")

        self.main_window.show()   # ← window appears immediately

        # -----------------------------------------------------------
        # File manager — archive runs in background after window shows
        # -----------------------------------------------------------
        self.log.info("Orchestrator: Initialising FileManager")
        self._file_manager = FileManager(self.log, ["validation", "logs"])

        self._archive_worker = _ArchiveWorker(self._file_manager)
        self._archive_worker.start()   # fire and forget — UI is already visible

        # -----------------------------------------------------------
        # Global error handler
        # -----------------------------------------------------------
        self.log.info("Orchestrator: Registering global exception handler")
        register_global_handler(
            log=self.log,
            state=self.state,
            body=self.body,
            file_manager=self._file_manager,
        )

        # -----------------------------------------------------------
        # Feature and tool modules
        # -----------------------------------------------------------
        self.log.info("Orchestrator: Initialising feature modules")
        self.payroll         = PayrollFeature(self.log, self.main_window)
        self.checker         = CheckerFeature(self.log, self.main_window)
        self.dbx_to_sprout   = DarwinToSproutTool(self.log, self.main_window)
        self.att_summary_svc = AttendanceSummaryTool(self.log, self.main_window)

        self.payroll.on_result              = self._payroll_files_preparation_result
        self.payroll.uploaded_files         = self._upload_sp_files
        self.payroll.on_progress            = lambda pct, msg: self.body.update_processing_progress(pct, msg)

        self.checker.on_result              = self._checker_files_preparation_result
        self.checker.uploaded_files         = self._generate_validation
        self.checker.on_progress            = lambda pct, msg: self.body.update_processing_progress(pct, msg)

        self.dbx_to_sprout.on_result        = self._dbx_payroll_preparation_result
        self.dbx_to_sprout.uploaded_files   = self._convert_payroll
        self.dbx_to_sprout.on_progress      = lambda pct, msg: self.body.update_processing_progress(pct, msg)

        self.att_summary_svc.on_result      = self._att_summary_preparation_result
        self.att_summary_svc.uploaded_files = self._run_attendance_summary
        self.att_summary_svc.on_progress    = lambda pct, msg: self.body.update_processing_progress(pct, msg)

        self.log.info("Orchestrator: Feature callbacks wired")

        # -----------------------------------------------------------
        # Services — created lazily (only when first needed)
        # -----------------------------------------------------------
        self._msal       = None
        self._sharepoint = None
        self._config_svc = None

        self._sp_base_url = get("SP_BASE_URL", "")
        self.log.info(
            f"Orchestrator: SP_BASE_URL loaded | set={bool(self._sp_base_url)}"
        )

        # Keep worker references so QThreads aren't garbage collected
        self._config_worker   = None
        self._update_worker   = None
        self._upload_worker   = None
        self._validate_worker = None

        self.log.info("Orchestrator: Initialisation complete")

    # ===================================================================
    # HELPERS
    # ===================================================================

    def _env_url(self, template: str) -> str:
        """Substitutes the ENVT placeholder in a URL template."""
        return template.replace("ENVT", self.envt)

    # ===================================================================
    # HANDLE BUTTON CLICKS
    # ===================================================================

    def _handle_body_clicks(self, btn):
        """
        Route all body-area button events.

        List payloads (btn is a list) carry data from the UI:
            ["payroll_upload", id_str, version_str]
            ["save_deminimis", deminimis_dict]
            ["add_user",       email_str]

        String payloads are simple named actions.
        """
        self.log.event("Body button clicked", btn=btn)

        # ── Payloads with data ────────────────────────────────────────
        if isinstance(btn, list):
            action = btn[0]

            if action == "payroll_upload":
                self.inputs["id"]      = btn[1].strip()
                self.inputs["version"] = btn[2].strip()
                self.log.info(
                    f"Orchestrator: Payroll upload triggered | "
                    f"id_input='{self.inputs['id']}' "
                    f"version_input='{self.inputs['version']}'"
                )
                self._on_payroll_upload_clicked()

            elif action == "save_deminimis":
                self.log.info("Orchestrator: Save deminimis triggered")
                self._save_deminimis(btn[1])

            elif action == "add_user":
                self.log.info(f"Orchestrator: Add user triggered | email={btn[1]}")
                self._add_user(btn[1])

            else:
                self.log.warning(f"Orchestrator: Unhandled list action | action={action}")
            return

        # ── Simple named actions ──────────────────────────────────────
        if btn == "retry":
            self.log.info("Orchestrator: Retry triggered — restarting app flow")
            self.start()

        elif btn == "login":
            self._login()

        elif "menu" in btn:
            self._on_menu_selected(btn)

        elif "source" in btn:
            self._on_source_selected(btn)

        elif "tool" in btn:
            self._on_tool_selected(btn)

        elif "feature" in btn:
            self._on_feature_selected(btn)

        elif btn == "home":
            self.body.show_main_menu()
        
        elif btn == "open_website":
            webbrowser.open("https://intogreatsolutions.com/automation-services/")
        
        elif btn == "close_credits":
            self.start()

        elif btn == "send_unmand":
            self.log.info("Orchestrator: Send to Unmand triggered")
            self._start_unmand()

        elif btn == "check_status":
            self.log.info(f"Orchestrator: Check Unmand status triggered | guid={self.state.get('guid')}")
            self._check_unmand()

        elif btn == "open_new_headers":
            url = self.state["config"]["payroll"]["new_headers_url"]
            self.log.info(f"Orchestrator: Opening new headers URL | url={url}")
            webbrowser.open(url)

        elif btn == "open_payroll_ouput":
            url = (
                self._env_url(self.state["config"]["payroll"]["output_folder"])
                + self.state["folder_name"].replace("input", "output")
            )
            self.log.info(f"Orchestrator: Opening payroll output URL | url={url}")
            webbrowser.open(url)

        elif btn == "checker_upload":
            id_names = self.state["config"]["payroll"]["expected_id_names"]
            self.log.info("Orchestrator: Checker upload triggered")
            self.body.show_processing_progress("Opening local folder...", "checker")
            self.checker.prepare_checker_files(id_names)

        elif btn == "open_checker_output":
            variance_file = self.state["variance_file"]
            self.log.info(f"Orchestrator: Opening checker output | path={variance_file}")
            os.startfile(variance_file)

        elif btn == "open_dbx_to_sprout_output":
            converted_file = self.state["converted_file"]
            self.log.info(f"Orchestrator: Opening DBX to Sprout output | path={converted_file}")
            os.startfile(converted_file)

        elif btn == "open_att_summary_output":
            att_summary_file = self.state.get("att_summary_file")
            self.log.info(f"Orchestrator: Opening attendance summary output | path={att_summary_file}")
            if att_summary_file:
                os.startfile(att_summary_file)

        elif btn == "payroll_headers":
            url = self.state["config"]["payroll"]["headers_url"]
            self.log.info(f"Orchestrator: Opening Payroll Headers | url={url}")
            webbrowser.open(url)

        elif btn == "nd_list":
            url = self.state["config"]["payroll"]["nd_list_url"]
            self.log.info(f"Orchestrator: Opening Night Differential List | url={url}")
            webbrowser.open(url)

        elif btn == "update_skipped":
            self.body.show_main_menu()

        elif btn == "update_error_continue":
            self.body.show_main_menu()

        elif btn == "dbx_to_sprout_upload":
            id_names = self.state["config"]["payroll"]["expected_id_names"]
            self.log.info("Orchestrator: DarwinBox Payroll Register upload triggered")
            self.body.show_processing_progress("Opening local folder...", "dbx_to_sprout")
            #self._on_processing_progress(0, "Selecting file…")
            self.dbx_to_sprout.prepare_darwinbox_payroll(id_names)

        elif btn == "att_summary_upload":
            self.log.info("Orchestrator: DarwinBox Attendance Report upload triggered")
            # Store date picker values before opening file dialog
            self.state["att_start_date"]  = self.body.start_date.date().toString("yyyy-MM-dd")
            self.state["att_cutoff_date"] = self.body.cutoff.date().toString("yyyy-MM-dd")
            self.att_summary_svc.prepare_attendance_file(
                self.state["att_start_date"],
                self.state["att_cutoff_date"],
            )
            self.body.show_processing_progress("Opening local folder...", "att_summary")

        else:
            self.log.warning(f"Orchestrator: Unhandled button | btn={btn}")

    def _handle_header_clicks(self, btn):
        """Route header button events (close / minimise / restart)."""
        self.log.event("Header button clicked", btn=btn)

        if btn == "close":
            self.log.info("Orchestrator: Close triggered — uploading log and closing")
            self.main_window.close()
            self._file_manager.upload_log(self.state)

        elif btn == "minimized":
            self.log.info("Orchestrator: Minimise triggered")
            self.main_window.showMinimized()

        elif btn == "restart":
            self._file_manager.upload_log(self.state)
            executable = Path(sys.argv[0]).resolve() if getattr(sys, "frozen", False) else Path(sys.executable)
            self.log.info(f"Orchestrator: Restart triggered - Loc:{executable}")
            subprocess.Popen([str(executable)])
            os._exit(0)

    def _handle_footer_clicks(self, btn):
        if btn == "credits":
            try:
                self.body.show_credits(datetime.now().year, self.footer.version)
            except:
                webbrowser.open("https://intogreatsolutions.com/automation-services/")

    # ===================================================================
    # ENTRY POINT
    # ===================================================================

    def start(self):
        """
        Check connectivity and show the appropriate initial screen.

        Called once at startup and again if the user clicks "Retry"
        from the no-internet screen.
        """
        self.log.section("APP START")
        self.log.info("Orchestrator: Checking internet connectivity")

        if internet_available():
            self.log.info("Orchestrator: Internet available — showing login screen")
            self.body.show_login()
        else:
            self.log.warning("Orchestrator: No internet connection — showing no-internet screen")
            self.body.show_no_internet()

    # ===================================================================
    # LOGIN FLOW
    # ===================================================================

    def _login(self):
        """
        Initiate MSAL login.

        Creates the MSALService on first call (lazy init) and wires its
        callbacks to Orchestrator handlers before starting the auth flow.
        """
        self.log.section("LOGIN")
        self.log.info("Orchestrator: Login button clicked — starting MSAL login")

        if not self._msal:
            self.log.info("Orchestrator: Creating MSALService (first login)")
            self._msal = MSALService(self.log)
            self._msal.on_login_complete = self._on_login_complete
            self._msal.on_device_code    = self._on_device_code
            self._msal.error_login       = self._on_login_error

        self._msal.start_login()

    def _on_device_code(self, payload: dict):
        """Show the device-code screen while the background thread polls."""
        self.log.info(f"Orchestrator: Device code issued | code={payload.get('user_code')}")
        self.body.update_login_form("device_code", payload)

    def _on_login_error(self, error: str):
        """Surface a login error in the UI."""
        self.log.warning(f"Orchestrator: Login failed | error={error}")
        self.body.update_login_form("login_error", error)

    def _on_login_complete(self, email: str, name: str, token: str):
        """
        Handle a successful login.

        Updates state with user identity and token, creates the
        SharePointService, then fetches the remote config in the background.
        """
        self.log.info(f"Orchestrator: Login complete | name={name} email={email}")

        self.state.update({
            "email":     email,
            "name":      name,
            "token":     token,
            "logged_in": True,
        })

        self.log.info("Orchestrator: Creating SharePointService")
        self._sharepoint = SharePointService(token)

        self._load_config()

    # ===================================================================
    # CONFIG LOAD  (async)
    # ===================================================================

    def _load_config(self):
        """
        Fetch the remote JSON config from SharePoint in a background thread.

        Shows a loading indicator immediately, then processes the result
        in _on_config_fetched() when the worker finishes.
        """
        self.log.section("CONFIG LOAD")
        self.log.info("Orchestrator: Fetching app config from SharePoint")
        self.body.update_login_form("loading")

        self._config_worker = _ConfigWorker(self.state["token"])
        self._config_worker.finished.connect(self._on_config_fetched)
        self._config_worker.error.connect(self._on_config_error)
        self._config_worker.start()

    def _on_config_error(self, error: str):
        self.log.warning(f"Orchestrator: Config request failed | error={error}")
        self.body.update_login_form("config_error")

    def _on_config_fetched(self, response):
        """Process the config response returned by _ConfigWorker."""
        try:
            config = json.loads(response.text)
        except json.JSONDecodeError as e:
            self.log.warning(f"Orchestrator: Config JSON parse failed | error={e}")
            self.body.update_login_form("json_error")
            return

        self.state["config"] = config
        self.log.info("Orchestrator: Config loaded and parsed successfully")

        # ── Access check ─────────────────────────────────────────────
        email         = self.state["email"]
        allowed_users = config.get("users", [])

        if email not in allowed_users:
            self.log.warning(f"Orchestrator: Access denied | email={email}")
            self.body.update_login_form("restricted_user")
            return

        self.log.info(f"Orchestrator: Access granted | name={self.state['name']} email={email}")

        # DEV guardrail — catches a dev build accidentally reaching a real user
        #if self.envt == "DEV":
        #    raise EnvironmentError("DEV build reached a production user — aborting.")

        self._check_for_update()

    # ===================================================================
    # UPDATE CHECK  (async)
    # ===================================================================

    def _check_for_update(self):
        """
        Checks GitHub Releases for a newer version in a background thread.
        Silently skips if the check fails — never blocks the app over this.
        """
        self.log.section("UPDATE CHECK")
        self.state["current"] = get_current_version()
        self.log.info(f"Orchestrator: Current version {self.state['current']} — checking for updates")

        self._update_worker = _UpdateCheckWorker()
        self._update_worker.finished.connect(self._on_update_checked)
        self._update_worker.start()

    def _on_update_checked(self, latest):
        if not latest:
            self.log.info("Orchestrator: Update check failed or no releases found — skipping")
            self.body.show_main_menu()
            return

        self.state["latest"], asset_id = latest

        if not is_newer(self.state["latest"], self.state["current"]):
            self.log.info(f"Orchestrator: Already up to date | version={self.state['current']}")
            self.body.show_main_menu()
            return

        self.log.info(
            f"Orchestrator: New version available | "
            f"{self.state['current']} → {self.state['latest']}"
        )
        self.body.show_update_prompt(
            self.state["current"],
            self.state["latest"],
            on_confirm=lambda: self._do_update(asset_id),
        )

    def _do_update(self, asset_id: str):
        """Downloads the installer and launches it. Closes the app after launch."""
        self.log.info("Orchestrator: User confirmed update — downloading installer")
        self.body.show_update_downloading(self.state["current"], self.state["latest"])

        self._download_worker = DownloadWorker(asset_id, self.log, self._file_manager, self.state)
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.finished.connect(self._on_update_done)
        self._download_worker.start()

    def _on_download_progress(self, percent: int, message: str):
        self.body.update_download_progress(percent, message)

    def _on_update_done(self, success: bool):
        if success:
            self.log.info("Orchestrator: Installer launched — closing app")
            self.main_window.close()
        else:
            self.log.warning("Orchestrator: Update download failed")
            self.body.show_update_error()

    # ===================================================================
    # NAVIGATION
    # ===================================================================
    
    def _on_menu_selected(self, menu: str):
        """Store the selected data menu and advance to their screen."""

        clean_menu = menu.replace("_menu", "")
        self.state["menu"] = clean_menu

        users          = self.state["config"]["users"]
        deminimis      = self.state["config"]["deminimis"]

        self.log.event("Orchestrator:  Menu selected", menu=clean_menu)

        if "automation" == clean_menu:
            self.body.show_sources()
        elif "tools" == clean_menu:
            self.body.show_tools()
        elif "settings" == clean_menu:
            self.body.show_settings(users, deminimis)

    def _on_source_selected(self, source: str):
        """Store the selected data source and advance to the feature screen."""
        if "source" in source:
            clean_source = source.replace("_source", "")
            self.log.event("Orchestrator:  Source selected", source=clean_source)
            self.state["source"] = clean_source
            if "DarwinBox" in source:
                self.body.show_darwin_features()
            else:
                self.body.show_sprout_features()

    def _on_feature_selected(self, feature: str):
        """
        Navigate to the selected feature screen.

        Pulls the data it needs from state["config"] so the features
        themselves stay decoupled from the config schema.
        """
        self.log.event("Feature selected", feature=feature, source=self.state["source"])
        self.state["feature"] = feature

        payroll_cfg    = self.state["config"]["payroll"]
        required_files = payroll_cfg["required_files"]
        users          = self.state["config"]["users"]
        deminimis      = self.state["config"]["deminimis"]

        if feature == "payroll_feature":
            self.log.info(f"Orchestrator: Payroll Selected | required_files={len(required_files)}")
            self.body.show_payroll_feature(required_files, self.state["source"])

        elif feature == "checker_feature":
            self.log.info("Orchestrator: Checker Selected")
            self.body.show_checker_feature(self.state["source"])

    def _on_tool_selected(self, tool: str):
        """
        Navigate to the selected tool screen.
        """
        clean_tool = tool.replace("_tool", "")
        self.state["tool"] = clean_tool
        self.log.event("Orchestrator: Tool selected | required_files=1", tool=clean_tool,)

        if clean_tool == "dbx_to_sprout":
            self.body.show_dbx_to_sprout_tool()
        elif clean_tool == "attendance_summary":
            self.body.show_attendance_summary_tool()


    # ===================================================================
    # PAYROLL MAIN FLOW
    # ===================================================================

    def _on_payroll_upload_clicked(self):
        """
        Entry point for the payroll upload flow.

        Sets the default folder path, runs ID/version validation if the
        user supplied custom inputs, then delegates to PayrollFeature.
        """
        self.log.section("PAYROLL UPLOAD")
        self.log.info("Orchestrator: Payroll upload initiated")

        default_folder = (
            f"{self.state['month_year']}/"
            f"{self.state['id']}/"
            f"{self.state['version']}/input"
        )
        self.state["folder_name"] = default_folder
        self.log.info(f"Orchestrator: Default folder path set | path={default_folder}")

        if self.inputs["id"] or self.inputs["version"]:
            self.log.info("Orchestrator: Custom ID/Version detected — running validation")
            version_status = self._id_version_checks()

            if version_status:
                self.log.warning(f"Orchestrator: Version check failed | codes={version_status}")
                self.body.show_payroll_status(version_status)
                return

        payroll_cfg    = self.state["config"]["payroll"]
        expected_files = payroll_cfg["required_files"]
        source         = self.state["source"]
        token          = self.state["token"]

        self.log.info(
            f"Orchestrator: Starting file preparation | "
            f"source={source} expected_files={len(expected_files)}"
        )
        self.body.show_processing_progress("Opening local folder...", "payroll")
        self.payroll.prepare_payroll_files(expected_files, payroll_cfg, source, token)

    def _payroll_files_preparation_result(self, codes: list):
        """Handle result codes emitted by PayrollFeature."""
        self.log.section("PAYROLL VALIDATION RESULT")
        self.log.info(f"Orchestrator: Payroll file preparation complete | code_count={len(codes)}")

        for code in codes:
            file_name, status_code = parse_status_code(code)
            message_template       = PAYROLL_STATUSES.get(status_code, status_code)
            message                = message_template.format(file_name=file_name or "")
            is_error               = "error" in status_code

            self.log.result(
                step=f"File validation — {file_name or status_code}",
                success=not is_error,
                detail=message,
            )

        self.body.show_payroll_status(codes)

    def _id_version_checks(self) -> list:
        """
        Validate user-supplied ID and version inputs against SharePoint.

        Returns an empty list on success, or a list of status-code strings
        on failure.
        """
        self.log.section("ID / VERSION VALIDATION")
        self.log.info("Orchestrator: Running ID/Version input validation")

        def _found_folder(name: str, folders: list) -> bool:
            return any(f["name"] == name for f in folders)

        if self.inputs["id"] and not self.inputs["version"]:
            self.log.warning("Orchestrator: ID provided without version")
            return ["version_missing_error"]

        if not self.inputs["id"] and self.inputs["version"]:
            self.log.warning("Orchestrator: Version provided without ID")
            return ["id_missing_error"]

        raw_version = self.inputs["version"]

        if raw_version.isdigit():
            version = f"v{raw_version}"
        elif re.fullmatch(r"v\d+", raw_version):
            version = raw_version
        else:
            self.log.warning(f"Orchestrator: Invalid version format | input='{raw_version}'")
            return ["version_input_error"]

        self.log.info(f"Orchestrator: Version normalised | raw={raw_version} normalised={version}")

        payroll_folder = self._env_url(self.state["config"]["payroll"]["folder"])
        month_year     = self.state["month_year"]

        url      = f"{self._sp_base_url}root:/{payroll_folder}/{month_year}:/children"
        response = self._sharepoint.get(url)
        sp_id_folder_list = response.json().get("value", [])

        if not _found_folder(self.inputs["id"], sp_id_folder_list):
            self.log.warning(f"Orchestrator: ID folder not found | id={self.inputs['id']}")
            return ["id_error"]

        url      = f"{self._sp_base_url}root:/{payroll_folder}/{month_year}/{self.inputs['id']}:/children"
        response = self._sharepoint.get(url)
        sp_version_folder_list = response.json().get("value", [])

        if _found_folder(version, sp_version_folder_list):
            self.log.warning(f"Orchestrator: Duplicate version folder | version={version}")
            return ["version_duplicate_error"]

        self.state["id"]          = self.inputs["id"]
        self.state["version"]     = version
        self.state["folder_name"] = f"{month_year}/{self.inputs['id']}/{version}/input"

        self.log.info(f"Orchestrator: ID/Version validation passed | id={self.state['id']} version={version}")
        return []

    def _upload_sp_files(self, files: dict):
        """
        Upload prepared payroll DataFrames as CSV files to SharePoint
        using a background thread.
        """
        self.log.section("SHAREPOINT UPLOAD")

        folder   = self._env_url(self.state["config"]["payroll"]["folder"]) + self.state["folder_name"]
        base_url = f"{self._sp_base_url}root:/{folder}"

        self.log.info(f"Orchestrator: Uploading {len(files)} file(s) to SharePoint | folder={folder}")

        self._upload_worker = _SharePointUploadWorker(
            files       = files,
            sharepoint  = self._sharepoint,
            base_url    = base_url,
            run_id      = self.state["id"],
            version     = self.state["version"],
            log         = self.log,
        )
        self._upload_worker.progress.connect(
            lambda prog, fname: _upload_progress(prog, fname)
        )
        self._upload_worker.finished.connect(self._on_upload_finished)
        self._upload_worker.start()

        def _upload_progress(progress, file_name):
            self.log.info(f"Orchestrator: Uploading {file_name}...")
            self.body.update_processing_progress(progress, f"Uploading {file_name} to Unmand")

    def _on_upload_finished(self, errors: list):
        if errors:
            self.log.warning(f"Orchestrator: SharePoint upload failed | files={errors}")
            self.body.show_payroll_status(["upload_sp_error"])
        else:
            self.log.info(
                f"Orchestrator: All files uploaded | "
                f"id={self.state['id']} version={self.state['version']}"
            )
            self.body.show_payroll_status(["file_success"])

    def _start_unmand(self):
        """Trigger the Unmand payroll processing workflow."""
        self.log.section("UNMAND START")

        api_token   = self.state["config"]["unmand"][self.envt]["token"]
        webhook_url = self.state["config"]["unmand"][self.envt]["webhook"]

        self.log.info("Orchestrator: Creating UnmandService")
        self._unmand = UnmandService(webhook_url, api_token)

        other_files = [
            f for f in self.state["config"]["payroll"]["required_files"]
            if "payroll" not in f and "attendance" not in f
        ]

        payload = {
            "local_app": {
                "id":          self.state["id"],
                "version":     self.state["version"],
                "folder_name": self.state["folder_name"],
                "userEmail":   self.state["email"],
                "userName":    self.state["name"],
                "month_year":  self.state["month_year"],
                "other_files": other_files,
                "source_type": self.state["source"],
            },
            "status":  {},
            "process": "payroll",
        }

        self.log.info(
            f"Orchestrator: Sending Unmand payload | "
            f"id={self.state['id']} version={self.state['version']} "
            f"source={self.state['source']}"
        )
        response = self._unmand.start_process(payload)
        success  = _ok(response)
        self.log.result("Unmand start", success=success, detail=f"HTTP {response.status_code}")

        if not success:
            self.body.show_payroll_status(["unmand_init_error"])
        else:
            self.state["guid"] = response.json().get("taskGuid")
            id_version = (
                f"ID: {self.state['id']} "
                f"Version: {self.state['version']} "
                f"Source: {self.state['source']}"
            )
            self.log.info(f"Orchestrator: Unmand started | guid={self.state['guid']}")
            self.body.show_payroll_status([f"{id_version}|unmand_init_success"])

    def _check_unmand(self):
        """Poll Unmand for the current task status and update the UI."""
        self.log.section("UNMAND STATUS CHECK")
        guid = self.state.get("guid")
        self.log.info(f"Orchestrator: Checking Unmand task status | guid={guid}")

        status = self._unmand.check_status(guid)
        self.log.info(f"Orchestrator: Unmand status received | status={status}")

        if "success" in status:
            id_version = f"ID: {self.state['id']} - Version: {self.state['version']}"
            status = f"{status}|{id_version}"

        self.body.show_payroll_status([status])

    # ===================================================================
    # ADDITIONAL TOOLS MAIN FLOW
    # ===================================================================

    def _dbx_payroll_preparation_result(self, codes: list):
        """Handle result codes emitted by DarwinToSproutTool."""
        self.log.section("DARWINBOX VALIDATION RESULT")
        self.log.info(f"Orchestrator: DarwinBox file preparation complete | code_count={len(codes)}")

        for code in codes:
            file_name, status_code = parse_status_code(code)
            message_template       = DBX_TO_SPROUT_STATUSES.get(status_code, status_code)
            message                = message_template.format(file_name=file_name or "")
            is_error               = "error" in status_code

            self.log.result(
                step=f"DarwinBox file — {file_name or status_code}",
                success=not is_error,
                detail=message,
            )

        self.body.show_dbx_to_sprout_status(codes)

    def _convert_payroll(self, files: dict):
        """
        Download payroll headers from SharePoint, then generate the
        variance report in a background thread.
        """
        self.log.section("DARWINBOX TO SPROUT CONVERSION TOOL")
        self.log.info("Orchestrator: Starting checker conversion tool")

        headers_loc = self.state["config"]["payroll"]["headers_loc"]
        url         = f"{self._sp_base_url}{headers_loc}"

        self.log.info("Orchestrator: Downloading payroll headers from SharePoint")
        response = self._sharepoint.get(url)

        if not _ok(response):
            self.log.warning(f"Orchestrator: Headers download failed | HTTP={response.status_code}")
            self.body.show_checker_status(["premium_download_error"])
            return

        source     = "DarwinBox"
        sheet_name = "Sprout Checker" if source == "Sprout" else "DarwinBox Checker"
        self.log.info(f"Orchestrator: Reading headers sheet | sheet={sheet_name}")

        df      = pd.read_excel(io.BytesIO(response.content), sheet_name=sheet_name, header=12, engine="openpyxl")
        header_map = dict(
                zip(
                    df["Payroll Headers"],
                    df["Sprout Payroll Headers"]
                )
            )
        self.log.info(f"Orchestrator: Loaded {len(header_map)} payroll header(s)")

        self.body.show_processing_progress("Converting payroll file…", "dbx_to_sprout")

        self._validate_worker = _DBXConversionWorker(
            files         = files,
            header_map    = header_map,
            log           = self.log,
            dbx_to_sprout = self.dbx_to_sprout,
        )
        self._validate_worker.progress.connect(self._on_processing_progress)
        self._validate_worker.finished.connect(self._on_conversion_done)
        self._validate_worker.start()

    def _on_conversion_done(self, success: bool, result):
        if success:
            self.state["converted_file"] = result
            self.log.info(f"Orchestrator: Conversion report written | path={result}")
            self.body.show_dbx_to_sprout_status(["converted_success"])
        else:
            self.log.warning(f"Orchestrator: Conversion generation failed | code={result}")
            self.body.show_dbx_to_sprout_status([result])


    # ===================================================================
    # CHECKER MAIN FLOW
    # ===================================================================

    def _checker_files_preparation_result(self, codes: list):
        """Handle result codes emitted by CheckerFeature."""
        self.log.section("CHECKER VALIDATION RESULT")
        self.log.info(
            f"Orchestrator: Checker file preparation complete | code_count={len(codes)}"
        )

        for code in codes:
            file_name, status_code = parse_status_code(code)
            message_template       = CHECKER_STATUSES.get(status_code, status_code)
            message                = message_template.format(file_name=file_name or "")
            is_error               = "error" in status_code

            self.log.result(
                step=f"Checker file — {file_name or status_code}",
                success=not is_error,
                detail=message,
            )

        self.body.show_checker_status(codes)

    def _generate_validation(self, files: dict):
        """
        Download payroll headers from SharePoint, then generate the
        variance report in a background thread.
        """
        self.log.section("CHECKER VALIDATION")
        self.log.info("Orchestrator: Starting checker variance generation")

        headers_loc = self.state["config"]["payroll"]["headers_loc"]
        url         = f"{self._sp_base_url}{headers_loc}"

        self.log.info("Orchestrator: Downloading payroll headers from SharePoint")
        response = self._sharepoint.get(url)

        if not _ok(response):
            self.log.warning(f"Orchestrator: Headers download failed | HTTP={response.status_code}")
            self.body.show_checker_status(["premium_download_error"])
            return

        source     = self.state["source"]
        sheet_name = "Sprout Checker" if source == "Sprout" else "DarwinBox Checker"
        self.log.info(f"Orchestrator: Reading headers sheet | sheet={sheet_name}")

        df      = pd.read_excel(io.BytesIO(response.content), sheet_name=sheet_name, header=12, engine="openpyxl")
        headers = list(df["Payroll Headers"])
        self.log.info(f"Orchestrator: Loaded {len(headers)} payroll header(s)")

        var_tolerance = self.state["config"].get("var_tolerance", 0)

        self.body.show_processing_progress("Running checker validation…", "checker")

        self._validate_worker = _ValidationWorker(
            files         = files,
            headers       = headers,
            source        = source,
            var_tolerance = var_tolerance,
            log           = self.log,
            checker       = self.checker
        )
        self._validate_worker.progress.connect(self._on_processing_progress)
        self._validate_worker.finished.connect(self._on_validation_done)
        self._validate_worker.start()

    def _on_validation_done(self, success: bool, result):
        if success:
            self.state["variance_file"] = result
            self.log.info(f"Orchestrator: Variance report written | path={result}")
            self.body.show_checker_status(["validated_success"])
        else:
            self.log.warning(f"Orchestrator: Variance generation failed | code={result}")
            self.body.show_checker_status([result])

    # ===================================================================
    # ATTENDANCE SUMMARY MAIN FLOW
    # ===================================================================

    def _att_summary_preparation_result(self, codes: list):
        """Handle result codes emitted by AttendanceSummaryTool."""
        self.log.section("ATTENDANCE SUMMARY VALIDATION RESULT")
        self.log.info(f"Orchestrator: Attendance file preparation complete | code_count={len(codes)}")

        for code in codes:
            file_name, status_code = parse_status_code(code)
            message_template       = ATTENDANCE_SUMMARY.get(status_code, status_code)
            message                = message_template.format(file_name=file_name or "")
            is_error               = "error" in status_code
            self.log.result(
                step=f"Attendance file — {file_name or status_code}",
                success=not is_error,
                detail=message,
            )
        self.body.show_attendance_summary_status(codes)

    def _run_attendance_summary(self, files: dict):
        """Process the attendance file in a background thread."""
        self.log.section("ATTENDANCE SUMMARY PROCESSING")
        self.log.info("Orchestrator: Starting attendance summary generation")

        start_date  = self.state.get("att_start_date", "")
        cutoff_date = self.state.get("att_cutoff_date", "")

        self.body.show_processing_progress("Generating attendance summary…", "att_summary")

        #self.att_summary_svc.generate(files, start_date, cutoff_date)

        self._att_summary_worker = _AttendanceSummaryWorker(
            files       = files,
            start_date  = start_date,
            cutoff_date = cutoff_date,
            log         = self.log,
            att_summary = self.att_summary_svc,
        )
        self._att_summary_worker.progress.connect(self._on_processing_progress)
        self._att_summary_worker.finished.connect(self._on_att_summary_done)
        self._att_summary_worker.start()

    def _on_att_summary_done(self, success: bool, result):
        if success:
            self.state["att_summary_file"] = result
            self.log.info(f"Orchestrator: Attendance summary written | path={result}")
            self.body.show_attendance_summary_status(["summarized_success"])
        else:
            self.log.warning(f"Orchestrator: Attendance summary failed | code={result}")
            self.body.show_attendance_summary_status([result])

    # ===================================================================
    # SETTINGS MAIN FLOW
    # ===================================================================

    def _save_deminimis(self, deminimis: dict):
        """
        Validate and persist updated deminimis values to SharePoint.

        Non-empty inputs override the current value; empty inputs keep
        the existing config value unchanged.
        """
        self.log.section("SAVE DEMINIMIS")
        self.log.info("Orchestrator: Processing deminimis save request")

        current_deminimis = self.state["config"]["deminimis"]
        new_deminimis     = {}

        for key, val in deminimis.items():
            if val:
                try:
                    new_deminimis[key] = float(val)
                    self.log.info(f"Orchestrator: Deminimis updated | key={key} value={float(val)}")
                except (ValueError, TypeError):
                    self.log.warning(f"Orchestrator: Invalid deminimis value | key={key} value={val!r}")
                    self.body.show_settings_save_deminimis_status(["deminimis_save_error"])
                    return
            else:
                new_deminimis[key] = current_deminimis[key]

        self.state["config"]["deminimis"] = new_deminimis

        self.log.info("Orchestrator: Saving updated deminimis to SharePoint")
        self._config_svc = ConfigService()
        response = self._config_svc.update(self.state["config"], self.state["token"])
        success  = _ok(response)

        self.log.result("Save deminimis", success=success, detail=f"HTTP {response.status_code}")

        if not success:
            self.body.show_settings_save_deminimis_status(["deminimis_save_error"])
            return
        self.body.show_settings_save_deminimis_status(["deminimis_save_success"])

        # Reload config silently (no update check) then refresh settings screen
        self._reload_config_silent()

    def _add_user(self, email: str):
        """
        Add a new user to the app's allowed-users list.

        Steps:
        1. Validate the email (non-empty and correct domain).
        2. Check for duplicates.
        3. Trigger the Power Automate flow to add the user to Teams.
        4. Send a welcome email via Graph Mail API.
        5. Persist the updated users list to SharePoint config.
        """
        self.log.section("ADD USER")
        self.log.info(f"Orchestrator: Add user requested | email={email}")

        allowed_domain = get("support_email", "@intogreatsolutions.com").split("@")[1]

        if not email:
            self.log.warning("Orchestrator: Add user — email field is empty")
            self.body.show_settings_add_user_status(["empty_error"])
            return

        if allowed_domain not in email:
            self.log.warning(f"Orchestrator: Add user — invalid domain | email={email}")
            self.body.show_settings_add_user_status(["error_email"])
            return

        if email in self.state["config"]["users"]:
            self.log.warning(f"Orchestrator: Add user — duplicate | email={email}")
            self.body.show_settings_add_user_status(["duplicate_user"])
            return

        # ── Power Automate — add to Teams group ──────────────────────
        flow_url   = self.state["config"]["entra"]["flow_url"]
        pa_payload = {
            "UserEmail": email,
            "GroupID":   self.state["config"]["entra"]["teams_group"],
            "GroupName": get("app", "Payroll Automation"),
        }

        self.log.info(f"Orchestrator: Triggering Power Automate add-user flow | email={email}")
        pa_response = PowerAutomateService().start(flow_url, payload=pa_payload)

        if not _ok(pa_response):
            self.log.warning(f"Orchestrator: Power Automate flow failed | HTTP={pa_response.status_code}")
            self.body.show_settings_add_user_status(["add_user_error"])
            return

        self.log.info("Orchestrator: Power Automate add-user flow accepted")

        # ── Graph API — send welcome email ────────────────────────────
        app_loc            = self.state["config"]["payroll"]["app_loc"]
        installation_guide = self.state["config"].get("installation_guide", "")
        email_url          = "https://graph.microsoft.com/v1.0/me/sendMail"
        email_payload      = {
            "message": {
                "subject": "Welcome to Payroll Automation App 🎉",
                "body": {
                    "contentType": "HTML",
                    "content": WELCOME_EMAIL.format(
                        user=self.state["name"],
                        download_link=app_loc,
                        installation_guide=installation_guide,
                    ),
                },
                "toRecipients": [{"emailAddress": {"address": email}}],
                "bccRecipients": [{"emailAddress": {"address": get("support_email")}}],
            }
        }

        self.log.info(f"Orchestrator: Sending welcome email via Graph | to={email}")
        email_response = OutlookService().send(email_url, payload=email_payload, token=self.state["token"])

        if not _ok(email_response):
            self.log.warning(f"Orchestrator: Welcome email failed | HTTP={email_response.status_code}")
            self.body.show_settings_add_user_status(["add_user_email_error"])
            return

        self.log.info("Orchestrator: Welcome email sent successfully")

        # ── Persist updated users list ────────────────────────────────
        self.state["config"]["users"].append(email)
        self.log.info(f"Orchestrator: Persisting updated users list | total={len(self.state['config']['users'])}")
        self._config_svc = ConfigService()
        self._config_svc.update(self.state["config"], self.state["token"])

        self.log.info(f"Orchestrator: User added successfully | email={email}")
        self.body.show_settings_add_user_status(["add_user_success"])
        self._reload_config_silent()

    # ===================================================================
    # INTERNAL — silent config reload (no update check)
    # ===================================================================

    def _reload_config_silent(self):
        """
        Re-fetches state["config"] from SharePoint without re-running the
        post-login flow (no update check, no navigation change).
        Used after settings saves so the UI reflects the latest data.
        """
        self.log.info("Orchestrator: Silent config reload")

        worker = _ConfigWorker(self.state["token"])
        worker.finished.connect(self._on_config_reloaded)
        worker.error.connect(lambda e: self.log.warning(f"Orchestrator: Silent reload failed | {e}"))
        worker.start()
        # Keep a reference
        self._reload_worker = worker

    def _on_config_reloaded(self, response):
        try:
            self.state["config"] = json.loads(response.text)
            self.log.info("Orchestrator: Silent config reload complete")
        except json.JSONDecodeError as e:
            self.log.warning(f"Orchestrator: Silent reload — JSON parse failed | {e}")
            return

        self._on_feature_selected("settings_feature")

    # ===================================================================
    # THREAD (PROGESS UPDATE)
    # ===================================================================
    def _on_processing_progress(self, percent: int, message: str):
        self.body.update_processing_progress(percent, message)
