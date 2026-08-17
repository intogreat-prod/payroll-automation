"""
settings_feature.py
--------------------
Suite Settings flow — Add User, Log Upload.
Split out of orchestrator.py: these are plain functions taking `self`
as their first argument, assigned onto the Orchestrator class (see the
bottom of orchestrator.py) so they run as normal bound methods with
full access to self.state / self.log / self.body /
self.reload_config_silent(). The silent config reload itself stays in
orchestrator.py — it's shared suite infrastructure, not settings
business logic — this file just calls it.
Log Upload
----------
Mirrors the tools_feature.py Excel Locker split: the actual upload
work (SharePoint calls, one file at a time) happens off the main
thread in _LogUploadWorker, so it can't stall the UI on a big date
range. Unlike the Excel Locker there's no per-file progress bar here
— just a start status and a final result, same as Add User.
The worker doesn't touch SharePoint directly — it delegates to
FileManager.upload_log() / upload_logs_range(), which already know
how to resolve a date to either the live logs/ folder or the
archive/YYYY/MM/DD/logs/ tree.
"""
from PyQt6.QtCore import QThread, pyqtSignal
from services.config_service import ConfigService
from services.outlook_services import OutlookService
from services.power_automate_service import PowerAutomateService
from utils.file_manager import FileManager
from utils.app_config_user import get
from utils.internet import ok
from utils.email_template import WELCOME_EMAIL

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
        # NOTE: previously logged pa_response.status_code here by mistake —
        # this is the config-update call failing, not the Power Automate one.
        self.log.warning(f"Config update failed | HTTP={config_response.status_code}")
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

    self.log.info(f"User added successfully | email={email}")
    self.body.show_settings_add_user_status("add_user_success")
    self.reload_config_silent(
        on_done=lambda: (
            self.body.show_settings(self.state["app_config"]["users"]),
            self.body.show_settings_add_user_status("add_user_success"),
        )
    )


# ---------------------------------------------------------------------------
# Background worker — does the actual upload work
# ---------------------------------------------------------------------------
class _LogUploadWorker(QThread):
   """
   Uploads logs to SharePoint off the main thread.
   Parameters
   ----------
   file_manager : FileManager
   state        : dict          full orchestrator state (token, app_config)
   current      : bool          Case 1 — upload today's live log only
   start_date   : date | None   Case 2/3 — range start (inclusive)
   end_date     : date | None   Case 2/3 — range end (inclusive)
   `current` takes priority — if True, start_date/end_date are ignored.
   When `current` is False, start_date == end_date is just a
   single-day range; FileManager.upload_logs_range() already handles
   that as a loop of length 1, so Case 2 and Case 3 don't need to be
   branched separately here.
   """
   finished = pyqtSignal(dict)   # {"uploaded": int, "failed": int}
   error    = pyqtSignal(str)
   def __init__(self, file_manager, state, current=False, start_date=None, end_date=None):
       super().__init__()
       self.file_manager = file_manager
       self.state         = state
       self.current       = current
       self.start_date    = start_date
       self.end_date      = end_date
       self.filename      = None

   def run(self):
       try:
           if self.current:
               success, self.filename = self.file_manager.upload_log(self.state)
               summary = {"uploaded": 1 if success else 0, 
                          "failed": 0 if success else 1,
                          "filename": self.filename 
                        }
           else:
               summary = self.file_manager.upload_logs_range(
                   self.state, self.start_date, self.end_date
               )
               summary.setdefault("filename", None)

           self.finished.emit(summary)
       except Exception as e:
           self.error.emit(str(e))

# ---------------------------------------------------------------------------
# LOG UPLOAD MAIN FLOW — mixed into Orchestrator
# ---------------------------------------------------------------------------
def _upload_logs(self, current: bool, start_date=None, end_date=None):
    """
    Validates inputs on the main thread, then hands the actual upload
    off to _LogUploadWorker.
    current      — Case 1, current session log
    start_date / end_date — Case 2 (same date = single day) / Case 3
                                (different dates = range), both resolved
                                the same way by FileManager.
    """
    self.log.section("SETTINGS — LOG UPLOAD")
    self.log.info(f"Log upload requested | current={current} range=({start_date}, {end_date})")
    
    # ── Validate ──────────────────────────────────────────────────
    if not current:
        if not start_date or not end_date:
            self.log.warning("Log upload — missing start/end date")
            self.body.show_settings_status("missing_dates_error")
            return
        
        if start_date > end_date:
            self.log.warning(f"Log upload — start after end | {start_date} > {end_date}")
            self.body.show_settings_status("invalid_range_error")
            return
        
    if not self.state.get("token"):
        self.log.warning("Log upload — no token in state")
        self.body.show_settings_status("no_token_error")
        return
    
    # ── Kick off worker ──────────────────────────────────────────
    self.body.show_settings_status("uploading")
    self._file_manager = FileManager(self.log)
    worker = _LogUploadWorker(
        self._file_manager,
        self.state,
        current=current,
        start_date=start_date,
        end_date=end_date,
    )

    worker.finished.connect(self._on_log_upload_finished)
    worker.error.connect(self._on_log_upload_error)
    worker.start()
    # Keep a reference so the QThread isn't garbage collected mid-flight
    self._log_upload_worker = worker

def _on_log_upload_finished(self, summary: dict):
    uploaded = summary.get("uploaded", 0)
    failed   = summary.get("failed", 0)
    filename = summary.get("filename", "")

    detail = f"uploaded={uploaded} failed={failed}"
    if filename:
        detail += f"filename={filename}"

    self.log.result(
        step="upload_logs",
        success=(failed == 0),
        detail=detail,
    )
    if uploaded == 0 and failed == 0:
        self.body.show_settings_status("no_logs_found")
    elif failed == 0:
        self.body.show_settings_status(("upload_success", filename))
    elif uploaded == 0:
        self.body.show_settings_status("upload_error")
    else:
        self.body.show_settings_status("upload_partial_success")

def _on_log_upload_error(self, message: str):
   self.log.warning(f"Log upload failed | {message}")
   self.body.show_settings_status("upload_error")