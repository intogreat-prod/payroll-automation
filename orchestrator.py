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
    files         dict | None  Prepared payroll DataFrames (unused post-upload)
    variance_file Path | None  Local path of the generated checker output
    version       str          Payroll version label, e.g. "v1"
    id            str          Payroll run ID (datetime stamp or user-supplied)
    month_year    str          Current month/year, e.g. "May 2026"
"""

import os
import io
import json
import re
import sys
import webbrowser
import subprocess
from datetime import datetime

import pandas as pd

from ui.main_window import MainWindow
from ui.downloader import DownloadWorker
from ui.statuses import (
    PAYROLL_STATUSES,
    CHECKER_STATUSES,
    SETTINGS_STATUSES,
    parse_status_code,
)

from services.msal_service import MSALService
from services.sharepoint_service import SharePointService
from services.config_service import ConfigService
from services.unmand_service import UnmandService
from services.power_automate_service import PowerAutomateService
from services.outlook_services import OutlookService

from utils.error_handler import register_global_handler
from utils.file_manager import FileManager
from utils.internet import internet_available
from utils.logger import Logger
from utils.file_utils import app_data_path, validation_path
from utils.email_template import WELCOME_EMAIL
from utils.app_config_user import get
from utils.updater import DownloadWorker, get_current_version, get_latest_release, is_newer

from features.payroll import PayrollFeature
from features.checker import CheckerFeature


class Orchestrator:

    def __init__(self):

        # Get environment
        self.envt = get('ENVT', 'DEV')

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
            "logged_in":     False,
            "email":         None,
            "name":          None,
            "token":         None,
            "config":        None,
            "folder_name":   None,
            "guid":          None,
            "files":         None,
            "variance_file": None,
            "version":       "v1",
            "id":            now.strftime("%Y%m%d_%H%M%S"),
            "month_year":    now.strftime("%B %Y"),
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
        # Build the window and grab shortcuts to each component
        # -----------------------------------------------------------
        self.log.info("Orchestrator: Building main window")
        self.main_window = MainWindow()
        self.body        = self.main_window.body
        self.header      = self.main_window.header
        self.footer      = self.main_window.footer

        # -----------------------------------------------------------
        # File manager (sort old files into archive on launch)
        # -----------------------------------------------------------
        self.log.info("Orchestrator: Initialising FileManager")
        self._file_manager = FileManager(self.log, ["validation", "logs"])
        self._file_manager.sort_and_archive()

        # -----------------------------------------------------------
        # Global error handler (catches all unhandled exceptions)
        # -----------------------------------------------------------
        self.log.info("Orchestrator: Registering global exception handler")
        register_global_handler(
            log=self.log,
            state=self.state,
            body=self.body,
            file_manager=self._file_manager,
        )

        # -----------------------------------------------------------
        # Wire UI callbacks → Orchestrator handlers
        # -----------------------------------------------------------
        self.header.on_clicked = self._handle_header_clicks
        self.body.on_clicked   = self._handle_body_clicks
        self.log.info("Orchestrator: UI callbacks wired")

        self.main_window.show()

        # -----------------------------------------------------------
        # Feature modules
        # -----------------------------------------------------------
        self.log.info("Orchestrator: Initialising feature modules")
        self.payroll = PayrollFeature(self.log, self.main_window)
        self.checker = CheckerFeature(self.log, self.main_window)

        # Wire feature result callbacks → Orchestrator handlers
        self.payroll.on_result      = self._payroll_files_preparation_result
        self.payroll.uploaded_files = self._upload_sp_files

        self.checker.on_result      = self._checker_files_preparation_result
        self.checker.uploaded_files = self._generate_validation
        self.log.info("Orchestrator: Feature callbacks wired")

        # -----------------------------------------------------------
        # Services — created lazily (only when first needed)
        # -----------------------------------------------------------
        self._msal       = None
        self._sharepoint = None
        self._unmand     = None
        self._config     = None

        # Cache SP base URL from env once so all methods share it
        self._sp_base_url = get("SP_BASE_URL", "")
        self.log.info(
            f"Orchestrator: SP_BASE_URL loaded | "
            f"set={bool(self._sp_base_url)}"
        )

        self.log.info("Orchestrator: Initialisation complete")

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

        elif "source" in btn:
            self._on_source_selected(btn)

        elif "feature" in btn:
            self._on_feature_selected(btn)

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
            url = self.state["config"]["payroll"]["output_folder"].replace('ENVT', self.envt) + self.state['folder_name'].replace('input', 'output')
            self.log.info(f"Orchestrator: Opening payroll output URL | url={url}")
            webbrowser.open(url)

        elif btn == "checker_upload":
            id_names = self.state["config"]["payroll"]["expected_id_names"]
            self.log.info("Orchestrator: Checker upload triggered")
            self.checker.prepare_checker_files(id_names)

        elif btn == "open_checker_output":
            variance_file = self.state["variance_file"]
            self.log.info(f"Orchestrator: Opening checker output | path={variance_file}")
            os.startfile(variance_file)

        elif btn == "payroll_headers":
            url = self.state["config"]["payroll"]["headers_url"]
            self.log.info(f"Orchestrator: Opening Payroll Headers | url={url}")
            webbrowser.open(url)

        elif btn == "nd_list":
            url = self.state["config"]["payroll"]["nd_list_url"]
            self.log.info(f"Orchestrator: Opening Night Differential List | url={url}")
            webbrowser.open(url)

        elif btn == "update_skipped":
            self.body.show_sources()  

        elif btn == "update_error_continue":
            self.body.show_sources()  

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
            # Restart is not yet implemented; placeholder for future use
            self._file_manager.upload_log(self.state)
            self.log.info("Orchestrator: Restart triggered")
            sys.executable
            sys.argv

            subprocess.Popen([sys.executable] + sys.argv)
            os._exit(0)

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
        SharePointService, then immediately fetches the remote config.
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
    # CONFIG LOAD
    # ===================================================================

    def _load_config(self):
        """
        Fetch and parse the remote JSON config from SharePoint.

        On success, checks whether the logged-in user is in the allowed
        users list and navigates accordingly.  On any failure, shows an
        appropriate error state on the login form.
        """
        self.log.section("CONFIG LOAD")
        self.log.info("Orchestrator: Fetching app config from SharePoint")

        self._config = ConfigService()

        # ── Fetch ────────────────────────────────────────────────────
        try:
            response = self._config.get(self.state["token"])
        except Exception as e:
            self.log.warning(f"Orchestrator: Config request failed | error={e}", error=e)
            self.body.update_login_form("config_error")
            return

        # ── Parse ────────────────────────────────────────────────────
        try:
            config = json.loads(response.text)
        except json.JSONDecodeError as e:
            self.log.warning(f"Orchestrator: Config JSON parse failed | error={e}")
            self.body.update_login_form("json_error")
            return

        self.state["config"] = config
        self.log.info("Orchestrator: Config loaded and parsed successfully")

        # ── Access check ─────────────────────────────────────────────
        email = self.state["email"]
        allowed_users = config.get("users", [])

        if self.envt == "DEV":
            raise EnvironmentError("DEV in PROD")

        if email in allowed_users:
            self.log.info(f"Orchestrator: Access granted | name={self.state['name']} email={email}")
            if not self.envt == "DEV":
                self._check_for_update()
            #self.body.show_sources() 

        else:
            self.log.warning(f"Orchestrator: Access denied — user not in allowed list | email={email}")
            self.body.update_login_form("restricted_user")

    # ===================================================================
    # UPDATE APP
    # ===================================================================
    def _check_for_update(self):
        """
        Checks GitHub Releases for a newer version.
        If one is found, shows a prompt and downloads the installer.
        Silently skips if the check fails — never blocks the app over this.
        """

        self.log.section("UPDATE CHECK")
        self.state["current"] = get_current_version()
        self.log.info(f"Orchestrator: Current version {self.state['current']} — checking for updates")
        
        latest = get_latest_release()
        if not latest:
            self.log.info("Orchestrator: Update check failed or no releases found — skipping")
            self.body.show_sources()
            return
        
        self.log.info(f"App Version {self.state['current']}")
        
        self.state["latest"], asset_id = latest

        if not is_newer(self.state["latest"], self.state["current"]):
            self.log.info(f"Orchestrator: Already up to date | version={self.state['current']}")
            self.body.show_sources() 
            return
        
        self.log.info(f"Orchestrator: New version available | {self.state['current']} → {self.state['latest']}")

        # Show a prompt — body handles the Yes/No UI
        # Wire body.on_update_confirmed to trigger the download
        self.body.show_update_prompt(self.state["current"], self.state["latest"], on_confirm=lambda: self._do_update(asset_id))

    def _do_update(self, asset_id: str):
        """Downloads the installer and launches it. Closes the app after launch."""
        self.log.info("Orchestrator: User confirmed update — downloading installer")
        self.body.show_update_downloading(self.state["current"], self.state["latest"])

        self.worker = DownloadWorker(asset_id, self.log, self._file_manager, self.state)
        self.worker.progress.connect(self._on_download_progress)
        self.worker.finished.connect(self._on_update_done)
        self.worker.start()

    def _on_download_progress(self, percent: int, message: str):
        self.body.download_progress.setValue(percent)
        self.body.download_percent_label.setText(f"{percent}%")
        self.body.download_status_label.setText(message)

    def _on_update_done(self, success:bool):
        if success:
            self.log.info("Orchestrator: Installer launched — closing app")
            self.main_window.close()
        else:
            self.log.warning("Orchestrator: Update download failed")
            self.body.show_update_error()

    # ===================================================================
    # NAVIGATION
    # ===================================================================

    def _on_source_selected(self, source: str):
        """Store the selected data source and advance to the feature screen."""
        clean_source = source.replace("_source", "")
        self.log.event("Source selected", source=clean_source)
        self.state["source"] = clean_source
        self.body.show_features()

    def _on_feature_selected(self, feature: str):
        """
        Navigate to the selected feature screen.

        Pulls the data it needs from state["config"] so the features
        themselves stay decoupled from the config schema.
        """
        self.log.event("Feature selected", feature=feature, source=self.state["source"])
        self.state["feature"] = feature

        payroll_cfg   = self.state["config"]["payroll"]
        required_files = payroll_cfg["required_files"]
        users          = self.state["config"]["users"]
        deminimis      = self.state["config"]["deminimis"]

        if feature == "payroll_feature":
            self.log.info(f"Orchestrator: Loading payroll feature | required_files={len(required_files)}")
            self.body.show_payroll_feature(required_files)

        elif feature == "checker_feature":
            self.log.info("Orchestrator: Loading checker feature")
            self.body.show_checker_feature()

        elif feature == "settings_feature":
            self.log.info(
                f"Orchestrator: Loading settings feature | users={len(users)} deminimis={len(deminimis)}")
            self.body.show_settings_feature(users, deminimis)

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

        # Default folder path (used when no ID/version override)
        default_folder = (
            f"{self.state['month_year']}/"
            f"{self.state['id']}/"
            f"{self.state['version']}/input"
        )
        self.state["folder_name"] = default_folder
        self.log.info(
            f"Orchestrator: Default folder path set | path={default_folder}"
        )

        # Run versioning checks only when user supplied custom inputs
        if self.inputs["id"] or self.inputs["version"]:
            self.log.info(
                "Orchestrator: Custom ID/Version detected — running validation"
            )
            version_status = self._id_version_checks()

            if version_status:
                self.log.warning(
                    f"Orchestrator: Version check failed | codes={version_status}"
                )
                self.body.show_payroll_status(version_status)
                return

        # Payroll file preparations requirements
        payroll_cfg    = self.state["config"]["payroll"]
        expected_files = payroll_cfg["required_files"]
        source         = self.state["source"]
        token          = self.state["token"]

        self.log.info(f"Orchestrator: Starting file preparation | source={source} expected_files={len(expected_files)}")
        self.payroll.prepare_payroll_files(expected_files, payroll_cfg, source, token)

    def _payroll_files_preparation_result(self, codes: list):
        """
        Handle the result codes emitted by PayrollFeature.

        Logs each code as a PASS/FAIL line, then passes them to the
        body for display.
        """
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
                detail=message
            )

        self.body.show_payroll_status(codes)

    def _id_version_checks(self) -> list:
        """
        Validate user-supplied ID and version inputs against SharePoint.

        Checks:
        1. Both ID and version must be supplied together (or neither).
        2. Version must match the format vN or a bare integer.
        3. The ID folder must already exist in SharePoint.
        4. The version folder must NOT already exist (prevents duplicates).

        Returns
        -------
        list
            Empty list if all checks pass.
            List of status-code strings if any check fails.
        """
        self.log.section("ID / VERSION VALIDATION")
        self.log.info("Orchestrator: Running ID/Version input validation")

        def _found_folder(name: str, folders: list) -> bool:
            return any(f["name"] == name for f in folders)

        # ── Mutual-dependency check ───────────────────────────────────
        if self.inputs["id"] and not self.inputs["version"]:
            self.log.warning("Orchestrator: ID provided without version")
            return ["version_missing_error"]

        if not self.inputs["id"] and self.inputs["version"]:
            self.log.warning("Orchestrator: Version provided without ID")
            return ["id_missing_error"]

        # ── Normalise version string ──────────────────────────────────
        raw_version = self.inputs["version"]

        if raw_version.isdigit():
            version = f"v{raw_version}"
        elif re.fullmatch(r"v\d+", raw_version):
            version = raw_version
        else:
            self.log.warning(f"Orchestrator: Invalid version format | input='{raw_version}'")
            return ["version_input_error"]

        self.log.info(f"Orchestrator: Version normalised | raw={raw_version} normalised={version}")

        payroll_folder = self.state["config"]["payroll"]["folder"].replace('ENVT', self.envt)

        # ── Validate ID folder exists ─────────────────────────────────
        month_year = self.state["month_year"]
        url = (f"{self._sp_base_url}root:/{payroll_folder}/{month_year}:/children")
        self.log.info(f"Orchestrator: Checking SharePoint for ID folder | month={month_year} id={self.inputs['id']}")

        response           = self._sharepoint.get(url)
        sp_id_folder_list  = response.json().get("value", [])

        if not _found_folder(self.inputs["id"], sp_id_folder_list):
            self.log.warning(f"Orchestrator: ID folder not found in SharePoint | id={self.inputs['id']}")
            return ["id_error"]

        self.log.info(f"Orchestrator: ID folder confirmed | id={self.inputs['id']}")

        # ── Validate version folder is not a duplicate ────────────────
        url = (f"{self._sp_base_url}root:/{payroll_folder}/{month_year}/{self.inputs['id']}:/children")
        self.log.info(f"Orchestrator: Checking for duplicate version folder | version={version}")

        response                = self._sharepoint.get(url)
        sp_version_folder_list  = response.json().get("value", [])

        if _found_folder(version, sp_version_folder_list):
            self.log.warning(f"Orchestrator: Version folder already exists | version={version} id={self.inputs['id']}")
            return ["version_duplicate_error"]

        # ── All checks passed — commit to state ──────────────────────
        self.state["id"]          = self.inputs["id"]
        self.state["version"]     = version
        self.state["folder_name"] = (f"{month_year}/{self.inputs['id']}/{version}/input")

        self.log.info(f"Orchestrator: ID/Version validation passed | id={self.state['id']} version={version}")
        return []

    def _upload_sp_files(self, files: dict):
        """
        Upload prepared payroll DataFrames as CSV files to SharePoint.

        Each DataFrame is serialised to CSV in memory and PUT to the
        session folder.  All files must succeed; if any fail the UI shows
        an upload error and the remaining files are skipped.

        Parameters
        ----------
        files : dict[str, pd.DataFrame]
            Keys are logical file names (without extension or ID suffix).
            Values are validated, ready-to-upload DataFrames.
        """
        self.log.section("SHAREPOINT UPLOAD")

        # Folder environment
        folder    = self.state["config"]["payroll"]["folder"].replace('ENVT', self.envt) + self.state["folder_name"]
        base_url  = f"{self._sp_base_url}root:/{folder}"
        upload_errors = []

        self.log.info(f"Orchestrator: Uploading {len(files)} file(s) to SharePoint | folder={folder}")

        for logical_name, df in files.items():
            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False)

            file_name = (f"{logical_name}_{self.state['id']}_{self.state['version']}.csv")
            url = f"{base_url}/{file_name}:/content"

            self.log.info(f"Orchestrator: Uploading file | name={file_name}")
            response = self._sharepoint.put_file(url, data=csv_buffer.getvalue(), content_type="text/csv")

            success = str(response.status_code).startswith("2")
            self.log.result(
                step=f"Upload {file_name}",
                success=success,
                detail=f"HTTP {response.status_code}"
            )

            if not success:
                upload_errors.append(logical_name)

        if upload_errors:
            self.log.warning(f"Orchestrator: SharePoint upload failed | files={upload_errors}")
            self.body.show_payroll_status(["upload_sp_error"])
            return

        self.log.info(f"Orchestrator: All files uploaded successfully | id={self.state['id']} version={self.state['version']}")
        self.body.show_payroll_status(["file_success"])

    def _start_unmand(self):
        """
        Trigger the Unmand payroll processing workflow.

        Builds the payload from current state and POSTs to the Unmand
        webhook.  On success, stores the task GUID for polling.
        """
        self.log.section("UNMAND START")

        api_token   = self.state["config"]["unmand"][self.envt]["token"]
        webhook_url = self.state["config"]["unmand"][self.envt]["webhook"]

        self.log.info("Orchestrator: Creating UnmandService")
        self._unmand = UnmandService(webhook_url, api_token)

        # Non-payroll/attendance files that Unmand also needs to process
        other_files = [
            f for f in self.state["config"]["payroll"]["required_files"]
            if "payroll" not in f and "attendance" not in f
        ]
        self.log.info(f"Orchestrator: Other files for Unmand payload | files={other_files}")

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

        success = str(response.status_code).startswith("2")
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
        """
        Poll Unmand for the current task status and update the UI.

        Appends ID/version context to success codes so the user can
        correlate the status with the right run.
        """
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
    # CHECKER MAIN FLOW
    # ===================================================================

    def _checker_files_preparation_result(self, codes: list):
        """
        Handle the result codes emitted by CheckerFeature.

        Mirrors _payroll_files_preparation_result but uses CHECKER_STATUSES.
        """
        self.log.section("CHECKER VALIDATION RESULT")
        self.log.info(
            f"Orchestrator: Checker file preparation complete | "
            f"code_count={len(codes)}"
        )

        for code in codes:
            file_name, status_code = parse_status_code(code)
            message_template       = CHECKER_STATUSES.get(status_code, status_code)
            message                = message_template.format(file_name=file_name or "")
            is_error               = "error" in status_code

            self.log.result(
                step=f"Checker file — {file_name or status_code}",
                success=not is_error,
                detail=message
            )

        self.body.show_checker_status(codes)

    def _generate_validation(self, files: dict):
        """
        Download payroll headers from SharePoint and generate the
        variance report Excel file.

        Flow
        ----
        1. Download the Payroll Headers & Premium Excel from SharePoint.
        2. Parse the correct sheet based on the current source.
        3. Load manual and Unmand checker DataFrames from ``files``.
        4. Compute summary totals and per-employee detailed variances.
        5. Write a two-sheet Excel file (Variance Report + Detailed Variance)
           to the local validation folder.
        6. Update state["variance_file"] so the UI can open it.
        """
        self.log.section("CHECKER VALIDATION")
        self.log.info("Orchestrator: Starting checker variance generation")

        # ── Download payroll headers ──────────────────────────────────
        headers_loc = self.state["config"]["payroll"]["headers_loc"]
        url         = f"{self._sp_base_url}{headers_loc}"

        self.log.info("Orchestrator: Downloading payroll headers from SharePoint")
        response = self._sharepoint.get(url)

        if not str(response.status_code).startswith("2"):
            self.log.warning(f"Orchestrator: Headers download failed | HTTP={response.status_code}")
            self.body.show_checker_status(["premium_download_error"])
            return

        excel_file = io.BytesIO(response.content)
        source     = self.state["source"]
        sheet_name = "Sprout Checker" if source == "Sprout" else "DarwinBox Checker"
        self.log.info(f"Orchestrator: Reading headers sheet | sheet={sheet_name}")

        df      = pd.read_excel(excel_file, sheet_name=sheet_name, header=12, engine="openpyxl")
        headers = list(df["Payroll Headers"])
        self.log.info(f"Orchestrator: Loaded {len(headers)} payroll header(s)")

        # ── Separate manual and Unmand DataFrames ─────────────────────
        manual_df = None
        unmand_df = None

        for filename, df in files.items():
            fname_lower = filename.lower()
            if "manual" in fname_lower:
                manual_df = df
                self.log.info(f"Orchestrator: Manual checker identified | file={filename}")
            elif "unmand" in fname_lower:
                unmand_df = df
                self.log.info(f"Orchestrator: Unmand checker identified | file={filename}")

        manual_df = manual_df if manual_df is not None else pd.DataFrame()
        unmand_df = unmand_df if unmand_df is not None else pd.DataFrame()

        # ── Helper: extract total row values ─────────────────────────
        def _get_totals(df: pd.DataFrame) -> dict:
            """
            Return a dict of {header: total_value} from the "Total" row.

            Looks for a row in the Employee ID column that contains the
            word "total" (case-insensitive).  Returns zeros for all
            headers when the row is missing or the DataFrame is empty.
            """
            if isinstance(df, pd.DataFrame) and "Employee ID" in df.columns:
                mask      = df["Employee ID"].astype(str).str.lower().str.contains("total")
                total_row = df[mask]
                if not total_row.empty:
                    row = total_row.iloc[0]
                    return {h: row[h] if h in df.columns else 0 for h in headers}
            return {h: 0 for h in headers}

        # ── Summary totals ────────────────────────────────────────────
        self.log.info("Orchestrator: Computing summary totals")
        manual_totals = _get_totals(manual_df)
        unmand_totals = _get_totals(unmand_df)

        var_tolerance = self.state["config"].get("var_tolerance", 0)
        output        = []

        for h in headers:
            m = pd.to_numeric(manual_totals.get(h, 0), errors="coerce")
            u = pd.to_numeric(unmand_totals.get(h, 0), errors="coerce")
            m = 0 if pd.isna(m) else m
            u = 0 if pd.isna(u) else u
            output.append({
                "Payroll Header":  h,
                "Manual Checker":  m,
                "Unmand Checker":  u,
                "Variance":        m - u,
            })

        output_df = pd.DataFrame(output)

        # ── Detailed per-employee variance ────────────────────────────
        self.log.info("Orchestrator: Computing detailed per-employee variance")
        id_col   = "Employee ID"
        detailed = pd.DataFrame()

        if isinstance(manual_df, pd.DataFrame) and isinstance(unmand_df, pd.DataFrame):
            manual_cols = [h for h in headers if h in manual_df.columns]
            unmand_cols = [h for h in headers if h in unmand_df.columns]

            manual_long = manual_df.melt(
                id_vars=[id_col], value_vars=manual_cols,
                var_name="Payroll Header", value_name="Manual Value"
            )
            unmand_long = unmand_df.melt(
                id_vars=[id_col], value_vars=unmand_cols,
                var_name="Payroll Header", value_name="Unmand Value"
            )

            detailed = pd.merge(
                manual_long, unmand_long,
                on=[id_col, "Payroll Header"],
                how="outer"
            )
            detailed["Manual Value"] = pd.to_numeric(
                detailed["Manual Value"], errors="coerce"
            ).fillna(0)
            detailed["Unmand Value"] = pd.to_numeric(
                detailed["Unmand Value"], errors="coerce"
            ).fillna(0)
            detailed["Variance"] = detailed["Manual Value"] - detailed["Unmand Value"]
            self.log.info(
                f"Orchestrator: Detailed variance computed | rows={len(detailed)}"
            )

        # ── Accuracy metric ───────────────────────────────────────────
        manual_count = len(manual_df)
        unmand_count = len(unmand_df)
        accuracy     = (
            (output_df["Variance"].abs() >= var_tolerance).sum() / len(output_df)
            if len(output_df) > 0 else 0
        )
        accuracy_pct = round((1 - accuracy) * 100, 2)
        self.log.info(
            f"Orchestrator: Accuracy computed | "
            f"manual_rows={manual_count} unmand_rows={unmand_count} "
            f"accuracy={accuracy_pct}%"
        )

        # ── Write Excel output ────────────────────────────────────────
        file_path = (
            validation_path() /
            f"Checker_Variance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )
        self.state["variance_file"] = file_path
        self.log.info(f"Orchestrator: Writing variance report | path={file_path}")

        today = datetime.now().strftime("%Y-%m-%d")

        meta_df = pd.DataFrame({
            "Info":  ["Date", "Manual Rows", "Unmand Rows", "Accuracy Rate", "Tolerance"],
            "Value": [today, manual_count, unmand_count, f"{accuracy_pct}%", f"± {var_tolerance}"],
        })

        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:

            # Sheet 1: summary metadata + variance table
            meta_df.to_excel(writer, sheet_name="Variance Report", index=False, startrow=0)
            output_df.to_excel(writer, sheet_name="Variance Report", index=False, startrow=7)

            # Sheet 2: per-employee detail (only when data exists)
            if not detailed.empty:
                detailed.to_excel(writer, sheet_name="Detailed Variance", index=False)
                self.log.info("Orchestrator: Detailed Variance sheet written")

        self.log.info("Orchestrator: Variance report generation complete")
        self.body.show_checker_status(["validated_success"])

    # ===================================================================
    # SETTINGS MAIN FLOW
    # ===================================================================

    def _save_deminimis(self, deminimis: dict):
        """
        Validate and persist updated deminimis values to SharePoint.

        Non-empty inputs override the current value; empty inputs keep
        the existing config value unchanged.  Any non-numeric input
        triggers an immediate error without saving.
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
                # Keep existing value when the input was left blank
                new_deminimis[key] = current_deminimis[key]

        self.state["config"]["deminimis"] = new_deminimis

        self.log.info("Orchestrator: Saving updated deminimis to SharePoint")
        response = self._config.update(self.state["config"], self.state["token"])

        success = str(response.status_code).startswith("2")
        if success:
            self._load_config()
            self._on_feature_selected("settings_feature")
            self.log.result("Save deminimis", success=success, detail=f"HTTP {response.status_code}")

        if not success:
            self.body.show_settings_save_deminimis_status(["deminimis_save_error"])
            return

        self.body.show_settings_save_deminimis_status(["deminimis_save_success"])

    def _add_user(self, email: str):
        """
        Add a new user to the app's allowed-users list.

        Steps:
        1. Validate the email (non-empty and correct domain).
        2. Check for duplicates against the current users list.
        3. Trigger the Power Automate flow to add the user to Teams.
        4. Send a welcome email via the Graph Mail API.
        5. Persist the updated users list to SharePoint config.
        """
        self.log.section("ADD USER")
        self.log.info(f"Orchestrator: Add user requested | email={email}")

        # ── Input validation ──────────────────────────────────────────
        if not email:
            self.log.warning("Orchestrator: Add user — email field is empty")
            self.body.show_settings_add_user_status(["empty_error"])
            return

        if "@intogreatsolutions.com" not in email:
            self.log.warning(f"Orchestrator: Add user — invalid email domain | email={email}")
            self.body.show_settings_add_user_status(["error_email"])
            return

        if email in self.state["config"]["users"]:
            self.log.warning(f"Orchestrator: Add user — duplicate | email={email}")
            self.body.show_settings_add_user_status(["duplicate_user"])
            return

        # ── Power Automate — add to Teams group ──────────────────────
        flow_url = self.state["config"]["entra"]["flow_url"]
        pa_payload = {
            "UserEmail":  email,
            "GroupID":    self.state["config"]["entra"]["teams_group"],
            "GroupName":  get("app", "Payroll Automation"),
        }

        self.log.info(f"Orchestrator: Triggering Power Automate add-user flow | email={email}")
        power_automate = PowerAutomateService()
        pa_response    = power_automate.start(flow_url, payload=pa_payload)

        if not str(pa_response.status_code).startswith("2"):
            self.log.warning(
                f"Orchestrator: Power Automate flow failed | "
                f"HTTP={pa_response.status_code}"
            )
            self.body.show_settings_add_user_status(["add_user_error"])
            return

        self.log.info("Orchestrator: Power Automate add-user flow accepted")

        # ── Graph API — send welcome email ────────────────────────────
        download_link = self.state['config']['download_link']
        installation_guide = self.state['config']['installation_guide']
        email_url = "https://graph.microsoft.com/v1.0/me/sendMail"
        email_payload = {
            "message": {
                "subject": "Welcome to Payroll Automation App 🎉",
                "body": {
                    "contentType": "HTML",
                    "content": WELCOME_EMAIL.format(user=self.state["name"], 
                                                    download_link=download_link, 
                                                    installation_guide=installation_guide),
                },
                "toRecipients": [
                    {"emailAddress": {"address": email}}
                ],
            }
        }

        self.log.info(f"Orchestrator: Sending welcome email via Graph | to={email}")
        outlook       = OutlookService()
        email_response = outlook.send(email_url, payload=email_payload, token=self.state["token"])

        if not str(email_response.status_code).startswith("2"):
            self.log.warning(f"Orchestrator: Welcome email failed | HTTP={email_response.status_code}")
            # User was added to Teams but email failed — partial success
            self.body.show_settings_add_user_status(["add_user_email_error"])
            return

        self.log.info("Orchestrator: Welcome email sent successfully")

        # ── Persist updated users list ────────────────────────────────
        self.state["config"]["users"].append(email)
        self.log.info(f"Orchestrator: Persisting updated users list | total_users={len(self.state['config']['users'])}")
        self._config.update(self.state["config"], self.state["token"])

        self.log.info(f"Orchestrator: User added successfully | email={email}")
        self._load_config()
        self._on_feature_selected("settings_feature")
        self.body.show_settings_add_user_status(["add_user_success"])
