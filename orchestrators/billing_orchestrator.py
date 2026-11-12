"""
orchestrators/billing_orchestrator.py
--------------------------------------
Child orchestrator for the Billing app.

Start Automation and Check Variance (the Checker) are both real now.
Start Automation mirrors PayrollOrchestrator's Automation flow: a file
upload, a SharePoint upload worker, then a Send-to-Unmand / Check-status
round trip. Check Variance mirrors PayrollOrchestrator's Checker flow: a
2-file upload, an async worker for the variance generation, and live
progress reported back to the UI. Settings is still a placeholder and
routes to BillingBody.show_coming_soon() (see
ui/components/body_apps/billing_app.py).

Attendance Summary (formerly "Attendance Adjustment", formerly a Tool)
now lives under Features and no longer touches SharePoint or Unmand at
all — files are validated locally, then AttendanceAdjustmentTool.
generate() runs the computation and writes the output .xlsx directly.
Rates come from billing_config, AUD-PHP/Month/Year come from
suite.state (set by the UI or defaulted to the current month).

Holds a reference to the suite root (`suite`) the same way
PayrollOrchestrator does, so it can read/write suite.state and call
suite.body.billing.show_*().
"""


import io
import os
import webbrowser
from datetime import datetime

from PyQt6.QtCore import QDate, QThread, pyqtSignal

from features.billing.billing import BillingFeature
from features.billing.checker import BillingCheckerFeature
from features.billing.attendance_adjustment import AttendanceAdjustmentTool
from features.billing.insightful import InsightfulTool

from services.unmand_service import UnmandService
from ui.statuses import resolve
from utils.internet import ok


# ---------------------------------------------------------------------------
# Background workers (Billing)
# ---------------------------------------------------------------------------

class _BillingSharePointUploadWorker(QThread):
    """Uploads billing CSV files to SharePoint off the main thread.

    Mirrors PayrollOrchestrator's _SharePointUploadWorker.
    """
    progress = pyqtSignal(int, str)     # current file name and progress
    finished = pyqtSignal(list)         # list of failed logical names (empty = all OK)

    def __init__(self, files: dict, sharepoint, base_url: str, run_id: str, log):
        super().__init__()
        self.files      = files
        self.sharepoint = sharepoint
        self.base_url   = base_url
        self.run_id     = run_id
        self.log        = log

    def run(self):
        errors    = []
        progress  = 0
        increment = 100 / len(self.files)

        for logical_name, df in self.files.items():
            progress += increment

            file_name = f"{logical_name}_{self.run_id}.csv"
            url       = f"{self.base_url}/{file_name}:/content"

            self.progress.emit(int(progress), file_name)
            self.log.info(f"BillingSPUploadWorker: Uploading | name={file_name} | {url}")

            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False)

            response = self.sharepoint.put_file(
                url, data=csv_buffer.getvalue(), content_type="text/csv"
            )
            success = ok(response)
            self.log.result(
                step=f"Upload {file_name}",
                success=success,
                detail=f"HTTP {response.status_code}",
            )
            if not success:
                errors.append(logical_name)

        self.finished.emit(errors)


class _BillingValidationWorker(QThread):
    """Runs the billing variance report generation off the main thread."""
    progress = pyqtSignal(int, str)           # percent, message
    finished = pyqtSignal(bool, object)       # success, file_path | error_code

    def __init__(self, files: dict, var_tolerance, log, checker):
        super().__init__()
        self.files         = files
        self.var_tolerance = var_tolerance
        self.log           = log
        self.checker       = checker

    def run(self):
        # Wire the checker's progress callback to this thread's signal
        self.checker.on_progress = lambda pct, msg: self.progress.emit(pct, msg)
        try:
            result = self.checker.generate(self.files, self.var_tolerance)
            self.finished.emit(True, result)
        except Exception as e:
            self.log.error(f"_BillingValidationWorker: Failed — {e}", error=e)
            self.finished.emit(False, "processing_error")
        finally:
            self.checker.on_progress = None


class _AttendanceAdjustmentWorker(QThread):
    progress = pyqtSignal(int, str)
    result = pyqtSignal(list)
    finished = pyqtSignal(bool, object)

    def __init__(self, files: dict, token: str, rates_loc: str, source: str, sheet_config: dict, date: tuple, aud_php: float, log, att_adj):
        super().__init__()
        self.files          = files
        self.token          = token
        self.rates_loc      = rates_loc
        self.source         = source
        self.sheet_config   = sheet_config
        self.date           = date
        self.aud_php        = aud_php
        self.log            = log
        self.att_adj        = att_adj
        self.last_error_codes = None 

    def _capture_result(self, code):
            codes = list(code) if isinstance(code, (list, tuple)) else [code]
            self.last_error_codes = codes
            self.result.emit(codes)

    def run(self):
        self.att_adj.on_progress = lambda pct, msg: self.progress.emit(pct, msg)
        self.att_adj.on_result = self._capture_result

        try:
            result = self.att_adj.generate(self.files, self.token, self.rates_loc, self.source, self.sheet_config, self.date, self.aud_php)

            if result is None:
                fallback = self.last_error_codes[0] if self.last_error_codes else "processing_error"
                self.finished.emit(False, fallback)
            else:
                self.finished.emit(True, result)

        except Exception as e:
            self.log.error(f"_AttendanceAdjustmentWorker: Failed — {e}", error=e)
            fallback = self.last_error_codes[0] if self.last_error_codes else "processing_error"
            self.finished.emit(False, fallback)

        finally:
            self.att_adj.on_progress = None
            self.att_adj.on_result = None


class _InsightfulWorker(QThread):
    """Runs Insightful tracker generation off the main thread.

    Mirrors _AttendanceAdjustmentWorker, but generate() here can finish
    with result=None for two different reasons: an outright error, or
    new user(s) being found (tracker updated, run intentionally
    stopped). Either way the last code captured via on_result is used
    as the fallback so the UI shows the right message.
    """
    progress = pyqtSignal(int, str)
    result   = pyqtSignal(list)
    finished = pyqtSignal(bool, object)

    def __init__(self, files: dict, token: str, tracker_loc: str, log, insightful):
        super().__init__()
        self.files       = files
        self.token       = token
        self.tracker_loc = tracker_loc
        self.log         = log
        self.insightful  = insightful
        self.last_error_codes = None

    def _capture_result(self, code):
        codes = list(code) if isinstance(code, (list, tuple)) else [code]
        self.last_error_codes = codes
        self.result.emit(codes)

    def run(self):
        self.insightful.on_progress = lambda pct, msg: self.progress.emit(pct, msg)
        self.insightful.on_result   = self._capture_result

        try:
            result = self.insightful.generate(self.files, self.token, self.tracker_loc)

            if result is None:
                fallback = self.last_error_codes[0] if self.last_error_codes else "processing_error"
                self.finished.emit(False, fallback)
            else:
                self.finished.emit(True, result)

        except Exception as e:
            self.log.error(f"_InsightfulWorker: Failed — {e}", error=e)
            fallback = self.last_error_codes[0] if self.last_error_codes else "processing_error"
            self.finished.emit(False, fallback)

        finally:
            self.insightful.on_progress = None
            self.insightful.on_result = None


class BillingOrchestrator:

    def __init__(self, suite):
        self.suite = suite
        # Tagged logger — every line from this app is prefixed "[Billing]"
        # in the shared session log file.
        self.log = suite.log.for_module("Billing")

        # -----------------------------------------------------------
        # Feature modules (Billing-only)
        # -----------------------------------------------------------
        self.billing    = BillingFeature(self.log, suite.main_window)
        self.checker    = BillingCheckerFeature(self.log, suite.main_window)
        self.att_adj    = AttendanceAdjustmentTool(self.log, suite.main_window)
        self.insightful = InsightfulTool(self.log, suite.main_window)

        self.billing.on_result          = self._billing_files_preparation_result
        self.billing.uploaded_files     = self._upload_sp_files
        self.billing.on_progress        = lambda pct, msg: suite.body.billing.update_processing_progress(pct, msg)

        self.checker.on_result          = self._checker_files_preparation_result
        self.checker.uploaded_files     = self._generate_validation
        self.checker.on_progress        = lambda pct, msg: suite.body.billing.update_processing_progress(pct, msg)

        self.att_adj.on_result          = self._att_adj_files_preparation_result
        self.att_adj.uploaded_files     = self._generate_att_adj
        self.att_adj.on_progress        = lambda pct, msg: suite.body.billing.update_processing_progress(pct, msg)

        self.insightful.on_result       = self._insightful_files_preparation_result
        self.insightful.uploaded_files  = self._generate_insightful
        self.insightful.on_progress     = lambda pct, msg: suite.body.billing.update_processing_progress(pct, msg)

        # -----------------------------------------------------------
        # Services — created lazily (only when first needed)
        # -----------------------------------------------------------
        self._unmand = None

        # Keep worker references alive so the QThreads aren't garbage
        # collected mid-run.
        self._upload_worker         = None
        self._validate_worker       = None
        self._att_adj_worker        = None
        self._insightful_worker     = None

    # ===================================================================
    # DISPATCH — entry point called by the suite root for any click
    # while the Billing app is active
    # ===================================================================

    def handle_click(self, btn):
        """
        Route Billing-app button events.

        List payloads (btn is a list) carry data from the UI:
            ["billing_upload", id_str, version_str]

        String payloads are simple named actions.
        """
        if isinstance(btn, list):
            action = btn[0]

            if action == "billing_upload":
                self.suite.inputs["id"]      = btn[1].strip()
                self.suite.inputs["version"] = btn[2].strip()
                self.log.info(
                    f"Billing upload triggered | "
                    f"id_input='{self.suite.inputs['id']}' "
                    f"version_input='{self.suite.inputs['version']}'"
                )
                self._on_billing_upload_clicked()
            else:
                self.log.warning(f"Unhandled list action | action={action}")
            return

        # ── Simple named actions ──────────────────────────────────────
        if btn == "home":
            self.suite.state["app"] = None
            self.suite.state["menu"] = None
            self.suite.state["feature"] = None
            self.suite.body.show_suite_menu()
        elif btn == "back":
            self.go_home()

        # ── Simple named actions ──────────────────────────────────────
        elif "menu" in btn:
            self._on_menu_selected(btn)

        elif "tool" in btn:
            self._on_tool_selected(btn)

        elif "feature" in btn:
            self._on_feature_selected(btn)

        elif "_bill" in btn:
            btn_ = btn.removesuffix("_bill")
            url = self.suite.state["billing_config"]["settings"][btn_]
            self.log.info(f"Opening File | url={url}")
            webbrowser.open(url)

        elif btn == "send_unmand":
            self.log.info("Send to Unmand triggered")
            self._start_unmand()

        elif btn == "check_status":
            self.log.info(f"Check Unmand status triggered | guid={self.suite.state.get('guid')}")
            self._check_unmand()

        elif btn == "payroll_headers":
            url = self.suite.state["billing_config"]["tools"]["att_adj"]["headers_rates"]
            self.log.info(f"Opening Payroll Headers | url={url}")
            webbrowser.open(url)

        elif btn == "insightful_tracker":
            url = self.suite.state["billing_config"]["tools"]["insightful"]["tracker"]
            self.log.info(f"Opening Insightful Tracker | url={url}")
            webbrowser.open(url)

        elif btn == "open_billing_output":
            billing_output_file = self.suite.state.get("billing_output_file")
            self.log.info(f"Opening billing output | path={billing_output_file}")
            if billing_output_file:
                os.startfile(billing_output_file)

        elif btn == "checker_upload":
            checker_cfg = self.suite.state["billing_config"]["automation"].get("checker") or {}
            cc_names    = checker_cfg.get("expected_contact_center")
            additional_column_map    = checker_cfg.get("additional_column_map")
            self.log.info("Billing checker upload triggered")
            self.suite.body.billing.show_processing_progress("Opening local folder...", "checker")
            self.checker.prepare_checker_files(cc_names, additional_column_map)

        elif btn == "attendance_summary_upload":
            self.log.info("Attendance Summary generation triggered")
            self._on_att_adj_upload_clicked()

        elif btn == "insightful_upload":
            self.log.info("Insightful generation triggered")
            self._on_insightful_upload_clicked()

        elif btn == "open_att_adj_output":
            att_adj_output_file = self.suite.state.get("att_adj_output_file")
            self.log.info(f"Opening Attendance Summary output | path={att_adj_output_file}")
            if att_adj_output_file:
                os.startfile(att_adj_output_file)

        elif btn == "open_insightful_output":
            insightful_output_file = self.suite.state.get("insightful_output_file")
            self.log.info(f"Opening Insightful output | path={insightful_output_file}")
            if insightful_output_file:
                os.startfile(insightful_output_file)

        elif btn == "open_checker_output":
            variance_file = self.suite.state["billing_variance_file"]
            self.log.info(f"Opening billing checker output | path={variance_file}")
            os.startfile(variance_file)

        else:
            self.log.warning(f"Unhandled action | action={btn}")

    def go_home(self):
        """Called by the suite root when 'home'/'back' is pressed while this app is active."""
        self.suite.state["menu"] = None
        self.suite.state["feature"] = None
        self.suite.body.billing.show_menu()

    # ===================================================================
    # NAVIGATION
    # ===================================================================

    # Human-friendly titles for the shared "coming soon" placeholder,
    # keyed by the feature/tool action name.
    _COMING_SOON_TITLES = {
        "billing_tools_tool": "Billing Tools",
    }

    def _on_menu_selected(self, menu: str):
        """Store the selected data menu and advance to their screen."""

        clean_menu = menu.replace("_menu", "")
        self.suite.state["menu"] = clean_menu
        self.suite.state["feature"] = None

        self.log.event("Menu selected", menu=clean_menu)
        if "automation" == clean_menu:
            self.suite.body.billing.show_automation_menu()

        elif "tools" == clean_menu:
            self.suite.body.billing.show_tools()

    def _on_feature_selected(self, feature: str):
        """
        Navigate to the selected feature screen.

        Check Variance and Attendance Summary are real; Automation/
        Settings land on the shared "coming soon" placeholder until
        they're scaffolded out.
        """
        self.log.event("Feature selected", feature=feature)
        self.suite.state["feature"] = feature

        if feature == "settings_feature":
            self.suite.body.billing.show_settings_feature()

        elif feature == "checker_feature":
            self.log.info("Checker Selected")
            self.suite.body.billing.show_checker_feature()

        elif feature == "billing_feature":
            automation_cfg    = self.suite.state["billing_config"]["automation"].get("unmand") or {}
            required_files = automation_cfg.get("required_files", [])
            self.log.info(f"Billing Automation Selected | required_files={len(required_files)}")
            self.suite.body.billing.show_billing_feature(required_files)

        elif feature == "attendance_summary_feature":
            self.log.info("Attendance Summary Selected")
            self.suite.body.billing.show_attendance_summary_feature()

        else:
            title = self._COMING_SOON_TITLES.get(feature, "This feature")
            self.suite.body.billing.show_coming_soon(title)

    def _on_tool_selected(self, tool: str):
        """Navigate to the selected tool screen — placeholder for now."""
        clean_tool = tool.replace("_tool", "")
        self.log.event("Tool selected", tool=clean_tool)
        self.suite.state["tool"] = clean_tool

        if "attendance_adjustment" == clean_tool:
            files = self.suite.state["billing_config"]["tools"]["att_adj"]["files"]
            self.suite.body.billing.show_attendance_adjustment_tool(files)

        elif "insightful" == clean_tool:
            files = self.suite.state["billing_config"]["tools"]["insightful"]["files"]
            self.suite.body.billing.show_insightful_tool(files)

    # ===================================================================
    # BILLING AUTOMATION MAIN FLOW
    # Mirrors PayrollOrchestrator's PAYROLL MAIN FLOW section. Billing has
    # no Sprout/DarwinBox source split, and — unlike Payroll's
    # _id_version_checks() — doesn't validate the Run ID/Version against
    # an existing SharePoint folder structure, since that folder
    # convention is Payroll-specific. Run ID/Version are still accepted
    # from the UI and used to tag the uploaded file names + Unmand
    # payload; if Billing later needs the same duplicate-run guard,
    # add a _id_version_checks() here the same way Payroll does.
    # ===================================================================

    def _on_billing_upload_clicked(self):
        """Entry point for the Billing Automation upload flow."""
        self.log.section("BILLING UPLOAD")
        self.log.info("Billing upload initiated")

        automation_cfg    = self.suite.state["billing_config"]["automation"].get("unmand") or {}
        required_files = automation_cfg.get("required_files", [])

        automation_cfg["billing_run_id"] = datetime.now().strftime("%B %Y")

        self.suite.body.billing.show_processing_progress("Opening local folder...", "billing")
        self.billing.prepare_billing_files(required_files, automation_cfg)

    def _billing_files_preparation_result(self, codes: list):
        """Handle result codes emitted by BillingFeature."""
        self.log.section("BILLING VALIDATION RESULT")
        self.log.info(f"Billing file preparation complete | code_count={len(codes)}")

        for code in codes:
            r = resolve("billing", code)
            self.log.result(
                step=f"Billing file validation — {r.value or r.key}",
                success=r.ok,
                detail=r.message,
            )

        self.suite.body.billing.show_billing_status(codes)

    def _upload_sp_files(self, files: dict):
        """Upload prepared billing DataFrames as CSV files to SharePoint."""
        self.log.section("BILLING SHAREPOINT UPLOAD")

        state       = self.suite.state
        billing_cfg = state["billing_config"]["automation"].get("unmand") or {}
        folder      = self.suite._env_url(billing_cfg.get("folder", ""))
        base_url    = f"{self.suite._sp_base_url}root:/{folder}"

        self.log.info(f"Uploading {len(files)} file(s) to SharePoint | folder={folder}")

        self._upload_worker = _BillingSharePointUploadWorker(
            files      = files,
            sharepoint = self.suite._sharepoint,
            base_url   = base_url,
            run_id     = billing_cfg.get("billing_run_id", ""),
            log        = self.log,
        )
        self._upload_worker.progress.connect(
            lambda prog, fname: self.suite.body.billing.update_processing_progress(
                prog, f"Uploading {fname} to Unmand"
            )
        )
        self._upload_worker.finished.connect(self._on_upload_finished)
        self._upload_worker.start()

    def _on_upload_finished(self, errors: list):
        if errors:
            self.log.warning(f"Billing SharePoint upload failed | files={errors}")
            self.suite.body.billing.show_billing_status(["upload_sp_error"])
        else:
            self.log.info("Billing files uploaded successfully")
            self.suite.body.billing.show_billing_status(["file_success"])

    def _start_unmand(self):
        """Trigger the Unmand billing automation workflow."""
        self.log.section("BILLING UNMAND START")

        state       = self.suite.state
        billing_cfg = state.get("billing_config") or {}
        unmand_cfg  = (billing_cfg.get("unmand") or {}).get(self.suite.envt, {})
        api_token   = unmand_cfg.get("token")
        webhook_url = unmand_cfg.get("webhook")

        if not api_token or not webhook_url:
            self.log.warning("Billing Unmand config missing — cannot start")
            self.suite.body.billing.show_billing_status(["unmand_init_error"])
            return

        self.log.info("Creating UnmandService")
        self._unmand = UnmandService(webhook_url, api_token)

        payload = {
            "local_app": {
                "run_id":     state.get("billing_run_id", ""),
                "userEmail":  state["email"],
                "userName":   state["name"],
            },
            "status":  {},
            "process": "billing",
        }

        self.log.info(f"Sending Unmand payload | run_id={state.get('billing_run_id', '')}")
        response = self._unmand.start_process(payload)
        success  = ok(response)
        self.log.result("Billing Unmand start", success=success, detail=f"HTTP {response.status_code}")

        if not success:
            self.suite.body.billing.show_billing_status(["unmand_init_error"])
        else:
            state["guid"] = response.json().get("taskGuid")
            self.log.info(f"Billing Unmand started | guid={state['guid']}")
            run_id_label = f"Run ID: {state.get('billing_run_id', '')}"
            self.suite.body.billing.show_billing_status([f"{run_id_label}|unmand_init_success"])

    def _check_unmand(self):
        """Poll Unmand for the current billing task status and update the UI."""
        self.log.section("BILLING UNMAND STATUS CHECK")
        state = self.suite.state
        guid  = state.get("guid")
        self.log.info(f"Checking Unmand task status | guid={guid}")

        status = self._unmand.check_status(guid)
        self.log.info(f"Unmand status received | status={status}")

        self.suite.body.billing.show_billing_status([status])

    # ===================================================================
    # ATTENDANCE SUMMARY MAIN FLOW
    # Local generation only — no SharePoint upload, no Unmand hand-off.
    # Rates/AUD-PHP/Month/Year are read from config + suite.state at
    # generation time and passed into AttendanceAdjustmentTool.
    # generate() as arguments.
    # ===================================================================

    def _on_att_adj_upload_clicked(self):
        """Entry point for the Attendance Summary file-selection flow."""
        self.log.section("ATTENDANCE SUMMARY FILE SELECTION")
        self.log.info("Attendance Summary file selection initiated")

        billing_cfg = self.suite.state["billing_config"]
        att_adj_cfg =  billing_cfg["tools"]["att_adj"]
        id_names_cfg = billing_cfg.get("expected_id_names", {})
        req_files_cfg = att_adj_cfg.get("files", [])

        self.exchange_rate = self.suite.body.billing.exchange_rate_input.text()

        self.suite.body.billing.show_processing_progress("Opening local folder...", "att_adj")
        self.att_adj.prepare_attendance_adjustment_files(id_names_cfg, req_files_cfg, self.exchange_rate)

    def _att_adj_files_preparation_result(self, codes: list):
        """Handle result codes emitted by AttendanceAdjustmentTool."""
        self.log.section("ATTENDANCE SUMMARY VALIDATION RESULT")
        self.log.info(f"Attendance Summary file preparation complete | code_count={len(codes)}")

        for code in codes:
            r = resolve("att_adj", code)
            self.log.result(
                step=f"Attendance Summary file validation — {r.value or r.key}",
                success=r.ok,
                detail=r.message,
            )

        self.suite.body.billing.show_attendance_adjustment_status(codes)

    def _generate_att_adj(self, files: dict):
        """
        Kick off local Attendance Summary generation once files are
        validated. Rates come from config; AUD-PHP and Month/Year come
        from whatever the user set on the Attendance Summary screen
        (falls back to config/current month if unset).
        """
        self.log.section("ATTENDANCE SUMMARY GENERATION")

        date = self.suite.body.billing.attendance_month.date()

        att_adj_cfg = self.suite.state["billing_config"]["tools"].get("att_adj", {})
        rates_loc  = att_adj_cfg.get("rates_loc", "")
        source  = att_adj_cfg.get("source", "")
        sheet_config  = att_adj_cfg.get("sheet_config", "")
        gst_loc  = att_adj_cfg.get("gst_loc", "")

        #self.att_adj.generate(
        #    files, 
        #    self.suite.state["token"],
        #    rates_loc,
        #    source,
        #    sheet_config,
        #    (date.year(), date.month(), date.day()),
        #    float(self.exchange_rate)
        #    )

        self._att_adj_worker = _AttendanceAdjustmentWorker(
            files       = files,
            token       = self.suite.state["token"],
            rates_loc   = rates_loc,
            source      = source, # Sprout or Darwin
            sheet_config= sheet_config,
            date        = (date.year(), date.month(), date.day()),
            aud_php     = float(self.exchange_rate),
            log         = self.log,
            att_adj     = self.att_adj,
        )
        self._att_adj_worker.progress.connect(self._on_processing_progress)
        self._att_adj_worker.result.connect(self._att_adj_files_preparation_result)
        self._att_adj_worker.finished.connect(self._on_att_adj_generated)
        self._att_adj_worker.start()

    def _on_att_adj_generated(self, success: bool, result):
        state = self.suite.state
        if success:
            state["att_adj_output_file"] = str(result)
            self.log.info(f"Attendance Summary written | path={result}")
            self.suite.body.billing.show_attendance_adjustment_status(["generated_success"])
        else:
            self.log.warning(f"Attendance Summary generation failed | code={result}")
            self.suite.body.billing.show_attendance_adjustment_status([result])

    # ===================================================================
    # INSIGHTFUL MAIN FLOW
    # Local generation only — no SharePoint upload, no Unmand hand-off.
    # generation time and passed into InsightfulFeature.
    # generate() as arguments.
    # ===================================================================

    def _on_insightful_upload_clicked(self):
        """Entry point for the Attendance Summary file-selection flow."""
        self.log.section("ATTENDANCE SUMMARY FILE SELECTION")
        self.log.info("Attendance Summary file selection initiated")

        billing_cfg = self.suite.state["billing_config"]
        insightful_cfg =  billing_cfg["tools"]["insightful"]
        id_names_cfg = billing_cfg.get("expected_id_names", {})
        req_files_cfg = insightful_cfg.get("files", [])

        self.suite.body.billing.show_processing_progress("Opening local folder...", "insightful")
        self.insightful.prepare_insightful_files(id_names_cfg, req_files_cfg)

    def _insightful_files_preparation_result(self, codes: list):
        """Handle result codes emitted by InsightfulTool."""
        self.log.section("INSIGHTFUL VALIDATION RESULT")
        self.log.info(f"Insightful file preparation complete | code_count={len(codes)}")

        for code in codes:
            r = resolve("insightful", code)
            self.log.result(
                step=f"Insightful file validation — {r.value or r.key}",
                success=r.ok,
                detail=r.message,
            )

        self.suite.body.billing.show_insightful_status(codes)

    def _generate_insightful(self, files: dict):
        """
        Kick off Insightful tracker generation once files are validated.
        The tracker location comes from config; generation itself (new
        user check, tracker update, SharePoint upload) runs in
        _InsightfulWorker off the main thread.
        """
        self.log.section("INSIGHTFUL GENERATION")

        insightful_cfg = self.suite.state["billing_config"]["tools"].get("insightful", {})
        tracker_loc    = insightful_cfg.get("tracker_loc", "")

        #self.insightful.generate(files, self.suite.state["token"], tracker_loc)

        self._insightful_worker = _InsightfulWorker(
            files       = files,
            token       = self.suite.state["token"],
            tracker_loc = tracker_loc,
            log         = self.log,
            insightful  = self.insightful,
        )
        self._insightful_worker.progress.connect(self._on_processing_progress)
        self._insightful_worker.result.connect(self._insightful_files_preparation_result)
        self._insightful_worker.finished.connect(self._on_insightful_generated)
        self._insightful_worker.start()

    def _on_insightful_generated(self, success: bool, result):
        """
        Handle the outcome of _InsightfulWorker.

        result is either an output Path (success), or a status code
        string — which may be a genuine error, or "new_user_found"
        (tracker was updated and re-uploaded, but the run stopped
        intentionally so the admin can complete the new row).
        """
        state = self.suite.state
        if success:
            state["insightful_output_file"] = str(result)
            self.log.info(f"Insightful tracker written | path={result}")
            self.suite.body.billing.show_insightful_status(["generated_success"])
        else:
            self.log.warning(f"Insightful generation stopped | code={result}")
            self.suite.body.billing.show_insightful_status([result])

    # ===================================================================
    # CHECKER MAIN FLOW
    # ===================================================================

    def _checker_files_preparation_result(self, codes: list):
        """Handle result codes emitted by BillingCheckerFeature."""
        self.log.section("BILLING CHECKER VALIDATION RESULT")
        self.log.info(f"Checker file preparation complete | code_count={len(codes)}")

        for code in codes:
            r = resolve("billing_checker", code)
            self.log.result(
                step=f"Billing checker file — {r.value or r.key}",
                success=r.ok,
                detail=r.message,
            )

        self.suite.body.billing.show_checker_status(codes)

    def _generate_validation(self, files: dict):
        """Generate the variance report in a background thread."""
        self.log.section("BILLING CHECKER VALIDATION")
        self.log.info("Starting billing checker variance generation")

        billing_cfg   = self.suite.state.get("billing_config") or {}
        var_tolerance = billing_cfg.get("var_tolerance", 0)

        self.suite.body.billing.show_processing_progress("Running checker validation…", "checker")

        self._validate_worker = _BillingValidationWorker(
            files         = files,
            var_tolerance = var_tolerance,
            log           = self.log,
            checker       = self.checker,
        )
        self._validate_worker.progress.connect(self._on_processing_progress)
        self._validate_worker.finished.connect(self._on_validation_done)
        self._validate_worker.start()

    def _on_validation_done(self, success: bool, result):
        state = self.suite.state
        if success:
            # result is the summary dict returned by checker.generate():
            # {file_path, total_clients, flagged_count, correct_clients,
            #  accuracy_pct, var_tolerance}
            state["billing_variance_file"]    = result["file_path"]
            state["billing_variance_summary"] = result
            self.log.info(
                f"Billing variance report written | path={result['file_path']} "
                f"accuracy={result['accuracy_pct']}% "
                f"clients={result['correct_clients']}/{result['total_clients']}"
            )
            self.suite.body.billing.show_checker_status(["validated_success"], summary=result)
        else:
            self.log.warning(f"Billing variance generation failed | code={result}")
            self.suite.body.billing.show_checker_status([result])

    # ===================================================================
    # THREAD (PROGRESS UPDATE)
    # ===================================================================

    def _on_processing_progress(self, percent: int, message: str):
        self.suite.body.billing.update_processing_progress(percent, message)
