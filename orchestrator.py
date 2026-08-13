"""
orchestrator.py
---------------
Suite root — single source of truth for app state and top-level flow
control (login, config load, update check, suite navigation).

This used to be one large class that also contained every app's flow
(Payroll's upload/checker/tools/settings logic lived inline here, over a
thousand lines of it). As the app grows into the Finance Suite — Payroll,
Billing, and more apps to come — that no longer scales as a single file.

The split:
    orchestrator.py (this file)     — login, config, updates, suite-level
                                       navigation (suite menu, account,
                                       help, credits) — the stuff every
                                       app in the suite shares.
    orchestrators/payroll_orchestrator.py — everything under the Payroll app.
    orchestrators/billing_orchestrator.py — everything under the Billing app.

Each child orchestrator gets a reference back to this suite root (`suite`)
and reads/writes `suite.state` directly, so app state is still one shared
dict — only the handling code moved, not the state.

Architecture
------------
    Orchestrator  →  calls body.show_*()  →  Body renders the screen
    Body          →  fires on_* callbacks →  Orchestrator (or the active
                                              app's child orchestrator)
                                              handles the event

The UI (Body) never calls a service directly.
Services never touch the UI directly.

State dict
----------
All mutable session data lives in self.state so it can be serialised,
logged, and passed to services without coupling those services to this
class. Keys used across the suite:

    app           str | None   Active suite app ("payroll" | "billing")
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

Payroll-specific keys (att_start_date, att_summary_file, converted_file,
etc.) are still stored in this same dict — PayrollOrchestrator just reads
and writes them.
"""

import json
import os
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from orchestrators.payroll_orchestrator import PayrollOrchestrator
from orchestrators.billing_orchestrator import BillingOrchestrator
from services.config_service import ConfigService
from services.msal_service import MSALService
from services.sharepoint_service import SharePointService
from services.outlook_services import OutlookService
from services.power_automate_service import PowerAutomateService
from ui.main_window import MainWindow
from utils.app_config_user import get
from utils.error_handler import register_global_handler
from utils.file_manager import FileManager
from utils.file_utils import app_data_path
from utils.internet import internet_available, ok
from utils.logger import Logger
from utils.updater import DownloadWorker, get_current_version, get_latest_release, is_newer
from utils.email_template import WELCOME_EMAIL

# ---------------------------------------------------------------------------
# Background workers (suite-level — login, config, updates)
# ---------------------------------------------------------------------------

class _ConfigWorker(QThread):
    """Fetches the remote config JSON off the main thread."""
    finished = pyqtSignal(object, str)   # requests.Response
    error    = pyqtSignal(str, str)

    def __init__(self, token: str, config_type: str, config_loc: str):
        super().__init__()
        self.token = token
        self.config_type = config_type
        self.config_loc = config_loc

    def run(self):
        try:
            response = ConfigService(self.config_loc).get(self.token)
            self.finished.emit(response, self.config_type)
        except Exception as e:
            self.error.emit(str(e), self.config_type)

class _UpdateCheckWorker(QThread):
    """Checks GitHub Releases for a newer version off the main thread."""
    finished = pyqtSignal(object)   # (latest_tag, asset_id) | None

    def __init__(self):
        super().__init__()

    def run(self):
        self.finished.emit(get_latest_release())

class _ArchiveWorker(QThread):
    """Runs sort_and_archive off the main thread on startup."""
    finished = pyqtSignal()

    def __init__(self, file_manager):
        super().__init__()
        self.file_manager = file_manager

    def run(self):
        self.file_manager.sort_and_archive()
        self.finished.emit()


# ---------------------------------------------------------------------------
# Orchestrator (suite root)
# ---------------------------------------------------------------------------

class Orchestrator:

    def __init__(self):

        self.envt = get("ENVT", "DEV")

        # Logger is created first so every subsequent step is captured.
        # app_name stamps the session log header — was hardcoded to
        # "Finance Suite"; now reads the suite's configured app name
        # so the header stays correct as more apps are added.
        self.log = Logger(app_data_path(), app_name=get("app", "Finance Suite"))
        self.log.section("ORCHESTRATOR INIT")

        # -----------------------------------------------------------
        # App state  (all mutable session data lives here — shared
        # across the suite root and every child orchestrator)
        # -----------------------------------------------------------
        now = datetime.now()
        self.state = {
            "current":       None,
            "latest":        None,
            "app":           None,
            "source":        None,
            "feature":       None,
            "menu":          None,
            "tool":          None,
            "logged_in":     False,
            "email":         None,
            "name":          None,
            "token":         None,
            "app_config":    None,
            "billing_config":    None,
            "payroll_config":    None,
            "folder_name":   None,
            "guid":          None,
            "variance_file": None,
            "billing_variance_file": None,
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
        self.footer.on_clicked = self._handle_footer_clicks
        self.log.info("Orchestrator: UI callbacks wired")

        self.main_window.show()   # ← window appears immediately

        # -----------------------------------------------------------
        # File manager — archive runs in background after window shows
        # -----------------------------------------------------------
        self.log.info("Orchestrator: Initialising FileManager")
        self._file_manager = FileManager(self.log)

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
        self._config_worker = None
        self._update_worker = None
        self._reload_worker = None

        # -----------------------------------------------------------
        # Breadcrumb nav trail (bottom of Body) — overridden for
        # suite-level utility screens that don't map cleanly onto
        # state["app"/"menu"/"feature"] (Account, Credits, Help,
        # Settings). Reset to None on every body click so derived
        # screens (app/menu/feature) fall back to the normal path.
        # -----------------------------------------------------------
        self._nav_override = None

        # -----------------------------------------------------------
        # Per-app child orchestrators — one per suite app.
        # Each owns its own feature/tool wiring and flow methods; the
        # suite root only routes clicks to whichever app is active.
        # -----------------------------------------------------------
        self.log.info("Orchestrator: Initialising app orchestrators")
        self.payroll_orch = PayrollOrchestrator(self)
        self.billing_orch = BillingOrchestrator(self)

        self.log.info("Orchestrator: Initialisation complete")

    # ===================================================================
    # HELPERS
    # ===================================================================

    def _env_url(self, template: str) -> str:
        """Substitutes the ENVT placeholder in a URL template."""
        return template.replace("ENVT", self.envt)

    def _active_module(self):
        """Returns the child orchestrator for whichever suite app is active, or None."""
        app = self.state.get("app")
        if app == "payroll":
            return self.payroll_orch
        elif app == "billing":
            return self.billing_orch
        return None

    # ===================================================================
    # BREADCRUMB NAV TRAIL
    # ===================================================================

    # Human-friendly labels for menu/feature keys that don't read well
    # just title-cased (e.g. "billing_feature" -> "Billing Automation").
    _MENU_LABELS = {
        "automation": "Automation",
        "tools":      "Tools",
    }
    _FEATURE_LABELS = {
        "payroll_feature":    "Payroll",
        "checker_feature":    "Checker",
        "settings_feature":   "Settings",
        "billing_feature":    "Billing Automation",
        "dbx_to_sprout_tool": "DarwinBox → Sprout",
        "att_summary_tool":   "Attendance Summary",
    }

    def _refresh_breadcrumb(self):
        """
        Recompute and display the nav trail at the bottom of the body.

        Suite-level utility screens (Account, Credits, Help, Settings)
        set self._nav_override directly since they don't map cleanly
        onto state["app"/"menu"/"feature"]; everything else is derived
        from that state so no other navigation method needs to call
        this itself.
        """
        self.body._breadcrumb.show()
        if self._nav_override:
            self.body.set_breadcrumb(self._nav_override)
            return

        app = self.state.get("app")
        if not app:
            self.body.set_breadcrumb(["Home"])
            return

        parts = ["Home", app.title()]

        menu = self.state.get("menu")
        if menu:
            parts.append(self._MENU_LABELS.get(menu, menu.replace("_", " ").title()))

        source = self.state.get("source")
        if source and menu == "automation":
            parts.append(source)

        feature = self.state.get("feature") or self.state.get("tool")
        if feature:
            parts.append(
                self._FEATURE_LABELS.get(feature, feature.replace("_feature", "").replace("_tool", "").replace("_", " ").title())
            )

        self.body.set_breadcrumb(parts)

    def _go_suite_home(self):
        """
        Return to the suite root screen, clearing whatever app/menu/
        feature state was active so the breadcrumb and screen agree.
        """
        self.state["app"] = None
        self.state["menu"] = None
        self.state["source"] = None
        self.state["feature"] = None
        self.state["tool"] = None
        self._nav_override = None
        self.body.show_suite_menu()
        self._refresh_breadcrumb()

    # ===================================================================
    # HANDLE BUTTON CLICKS
    # ===================================================================

    def _handle_body_clicks(self, btn):
        """
        Route body-area button events, then refresh the breadcrumb.

        The breadcrumb refresh happens after every click regardless of
        which branch below handled it (and regardless of its early
        returns), so it never needs to be called individually from each
        navigation method.
        """
        self._nav_override = None
        self._dispatch_body_click(btn)
        self._refresh_breadcrumb()

    def _dispatch_body_click(self, btn):
        """
        Route body-area button events.

        Suite-level actions (login, suite navigation, logout, etc.) are
        handled directly here. Everything else is delegated to whichever
        app's child orchestrator is currently active (self.state["app"]).

        List payloads (btn is a list) carry data from the UI, e.g.
        ["payroll_upload", id_str, version_str] — action name is btn[0].
        """
        self.log.event("Body button clicked", btn=btn)
         # ── Everything else belongs to the active app ───────────────────
        module = self._active_module()
        if module:
            module.handle_click(btn)

        else:
            action = btn
            if isinstance(btn, list):
                action = btn[0]

                if action == "add_user":
                    self.log.info(f"Add user triggered | email={btn[1]}")
                    self._add_user(btn[1])

                else:
                    self.log.warning(f"Unhandled list action | action={action}")
                return

            # ── Suite-level actions ─────────────────────────────────────────
            if action == "retry":
                self.log.info("Orchestrator: Retry triggered — restarting app flow")
                self.start()
                return

            elif action == "login":
                self._login()
                return

            elif "app" in action:
                self._on_suite_app_selected(action)
                return

            elif "util" in action:
                self._on_suite_util_selected(action)
                return

            elif action == "suite_home":
                self._go_suite_home()
                return

            elif action == "logout":
                self.log.info("Orchestrator: Logout triggered")
                self.state["logged_in"] = False
                self.start()
                return

            elif action == "contact_support":
                webbrowser.open("https://intogreatsolutions.com/automation-services/")
                return

            elif action == "open_website":
                webbrowser.open("https://intogreatsolutions.com/automation-services/")
                return

            elif action == "close_credits":
                self._go_suite_home()
                return

            elif action == "update_skipped":
                self._go_suite_home()
                return

            elif action == "update_error_continue":
                self._go_suite_home()
                return
        
            else:
                self.log.warning(f"Orchestrator: Unhandled action — no active app | action={action}")

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
                self._nav_override = ["Home", "About / Credits"]
                self.body.show_credits(datetime.now().year, self.footer.version)
                self._refresh_breadcrumb()
            except Exception:
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
            self.body._breadcrumb.hide()
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

        self._load_config("")

    # ===================================================================
    # CONFIG LOAD  (async)
    # ===================================================================

    def _load_config(self, config_type):
        """
        Fetch the remote JSON config from SharePoint in a background thread.

        Shows a loading indicator immediately, then processes the result
        in _on_config_fetched() when the worker finishes.
        """
        self.log.section("CONFIG LOAD")
        self.log.info(f"Orchestrator: Fetching {config_type.title()} app config from SharePoint")
        if not config_type:
            self.body.update_login_form("loading")
            config_loc = ""
        else:
            config_loc = self.state["app_config"]["app_config"][config_type]

        ConfigService(config_loc).get(self.state["token"])

        self._config_worker = _ConfigWorker(self.state["token"], config_type, config_loc)
        self._config_worker.finished.connect(self._on_config_fetched)
        self._config_worker.error.connect(self._on_config_error)
        self._config_worker.start()

    def _on_config_error(self, error: str, config_type):
        if not config_type:
            self.log.warning(f"Orchestrator: Config request failed | error={error}")
            self.body.update_login_form("config_error")
        else:
            self.log.warning(f"Orchestrator: {config_type.title()} Config request failed | error={error}")
            self.body.show_error_config("config_error", config_type)

    def _on_config_fetched(self, response, config_type):
        """Process the config response returned by _ConfigWorker."""
        if not config_type:
            try:
                config = json.loads(response.text)
            except json.JSONDecodeError as e:
                self.log.warning(f"Orchestrator: Config JSON parse failed | error={e}")
                self.body.update_login_form("json_error")
                return

            self.state["app_config"] = config
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
        else:
            try:
                config = json.loads(response.text)
            except json.JSONDecodeError as e:
                self.log.warning(f"Orchestrator: Config JSON parse failed | error={e}")
                self.body.show_error_config("json_error", config_type)
                return
            
            self.state[f"{config_type}_config"] = config
            self.log.info(f"Orchestrator: {config_type.title()} Config loaded and parsed successfully")

            if config_type == "payroll":
                self.payroll_orch.go_home()
            elif config_type == "billing":
                self.billing_orch.go_home()
            
            self._refresh_breadcrumb()

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
            self._go_suite_home()
            return

        self.state["latest"], asset_id = latest

        if not is_newer(self.state["latest"], self.state["current"]):
            self.log.info(f"Orchestrator: Already up to date | version={self.state['current']}")
            self._go_suite_home()
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
    # SUITE NAVIGATION
    # ===================================================================

    def _on_suite_app_selected(self, app: str):
        """Route from the suite root into whichever app tile was tapped."""
        if app == "app_settings":
            users = self.state["app_config"]["users"]
            self._nav_override = ["Home", "Settings"]
            self.body.show_settings(users)
            return

        clean_app = app.replace("_app", "")
        self.state["app"] = clean_app
        # Clear any nav state left over from a previous visit to this (or
        # another) app so the breadcrumb and screens start clean.
        self.state["menu"] = None
        self.state["source"] = None
        self.state["feature"] = None
        self.state["tool"] = None
        self.log.event("Orchestrator: Suite app selected", app=clean_app)

        self._load_config(clean_app)
        
    def _on_suite_util_selected(self, util: str):
        """Route from the suite root's utility tiles (Account, Updates, Credits, Help)."""
        clean_util = util.replace("_util", "")
        self.log.event("Orchestrator: Suite utility selected", util=clean_util)

        if clean_util == "account":
            self._nav_override = ["Home", "Account"]
            self.body.show_account(self.state.get("name"), self.state.get("email"))
        elif clean_util == "check_update":
            self._check_for_update()
        elif clean_util == "credits":
            self._nav_override = ["Home", "About / Credits"]
            self.body.show_credits(datetime.now().year, self.footer.version)
        elif clean_util == "help":
            self._nav_override = ["Home", "Help / Support"]
            self.body.show_help()

    # ===================================================================
    # SETTINGS MAIN FLOW
    # ===================================================================
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
        self.log.info(f"Add user requested | email={email}")

        state = self.state["app_config"]
        allowed_domain = get("support_email", "@intogreatsolutions.com").split("@")[1]

        if not email:
            self.log.warning("Add user — email field is empty")
            self.body.show_settings_add_user_status("empty_error")
            return

        if allowed_domain not in email:
            self.log.warning(f"Add user — invalid domain | email={email}")
            self.body.show_settings_add_user_status("error_email")
            return

        if email in state["users"]:
            self.log.warning(f"Add user — duplicate | email={email}")
            self.body.show_settings_add_user_status("duplicate_user")
            return

        # ── Power Automate — add to Teams group ──────────────────────
        flow_url   = state["entra"]["flow_url"]
        pa_payload = {
            "UserEmail": email,
            "GroupID":   state["entra"]["teams_group"],
            "GroupName": get("app", "Finance Suite"),
        }

        self.log.info(f"Triggering Power Automate add-user flow | email={email}")
        pa_response = PowerAutomateService().start(flow_url, payload=pa_payload)

        if not ok(pa_response):
            self.log.warning(f"Power Automate flow failed | HTTP={pa_response.status_code}")
            self.body.show_settings_add_user_status("add_user_error")
            return

        self.log.info("Power Automate add-user flow accepted")

        # ── Update users list ────────────────────────────────
        state["users"].append(email)
        self.log.info(f"Persisting updated users list | total={len(state['users'])}")
        self._config_svc = ConfigService("")
        config_response = self._config_svc.update(state, self.state["token"])

        if not ok(config_response):
            self.log.warning(f"Power Automate flow failed | HTTP={pa_response.status_code}")
            self.body.show_settings_add_user_status("add_user_error")
            return

        # ── Graph API — send welcome email ────────────────────────────
        app_loc            = state["app_loc"]
        installation_guide = state.get("installation_guide", "")
        email_url          = "https://graph.microsoft.com/v1.0/me/sendMail"
        email_payload      = {
            "message": {
                "subject": "Welcome to Finance Suite App 🎉",
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

        self.log.info(f"Sending welcome email via Graph | to={email}")
        email_response = OutlookService().send(email_url, payload=email_payload, token=self.state["token"])

        if not ok(email_response):
            self.log.warning(f"Welcome email failed | HTTP={email_response.status_code}")
            self.body.show_settings_add_user_status("add_user_email_error")
            return

        self.log.info("Welcome email sent successfully")
        
        # ── Persist updated users list ────────────────────────────────
        self.log.info(f"User added successfully | email={email}")
        self.body.show_settings_add_user_status("add_user_success")
        self.reload_config_silent(
            on_done=lambda: (
                self.body.show_settings(self.state["app_config"]["users"]),
                self.body.show_settings_add_user_status("add_user_success"),
            )
        )

    # ===================================================================
    # SHARED — silent config reload (no update check)
    # ===================================================================

    def reload_config_silent(self, on_done=None, config_type=None):
        """
        Re-fetches state["app_config"] from SharePoint without re-running the
        post-login flow (no update check, no navigation change).

        Any app orchestrator can call this after a settings save so the UI
        reflects the latest data — pass on_done to redraw whatever screen
        needs the fresh config (e.g. that app's settings screen).
        """
        self.log.info("Orchestrator: Silent config reload")

        if not config_type:
            config_loc = ""
        else:
            config_loc = self.state["app_config"]["app_config"][config_type]

        worker = _ConfigWorker(self.state["token"], config_type, config_loc)
        worker.finished.connect(lambda response: self._on_config_reloaded(response, on_done))
        worker.error.connect(lambda e: self.log.warning(f"Orchestrator: Silent reload failed | {e}"))
        worker.start()
        # Keep a reference so the QThread isn't garbage collected mid-flight
        self._reload_worker = worker

    def _on_config_reloaded(self, response, on_done):
        try:
            self.state["app_config"] = json.loads(response.text)
            self.log.info("Orchestrator: Silent config reload complete")
        except json.JSONDecodeError as e:
            self.log.warning(f"Orchestrator: Silent reload — JSON parse failed | {e}")
            return

        if on_done:
            on_done()

