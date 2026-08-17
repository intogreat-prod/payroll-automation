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

Holds a reference to the suite root (`suite`) the same way
PayrollOrchestrator does, so it can read/write suite.state and call
suite.body.billing.show_*().
"""


import io
import os
import webbrowser
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal

from features.billing.billing import BillingFeature
from features.billing.checker import BillingCheckerFeature
from services.unmand_service import UnmandService
from ui.statuses import parse_status_code, BILLING_STATUSES, BILLING_CHECKER_STATUSES
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


class BillingOrchestrator:

    def __init__(self, suite):
        self.suite = suite
        # Tagged logger — every line from this app is prefixed "[Billing]"
        # in the shared session log file.
        self.log = suite.log.for_module("Billing")

        # -----------------------------------------------------------
        # Feature modules (Billing-only)
        # -----------------------------------------------------------
        self.billing = BillingFeature(self.log, suite.main_window)
        self.checker = BillingCheckerFeature(self.log, suite.main_window)

        self.billing.on_result      = self._billing_files_preparation_result
        self.billing.uploaded_files = self._upload_sp_files
        self.billing.on_progress    = lambda pct, msg: suite.body.billing.update_processing_progress(pct, msg)

        self.checker.on_result      = self._checker_files_preparation_result
        self.checker.uploaded_files = self._generate_validation
        self.checker.on_progress    = lambda pct, msg: suite.body.billing.update_processing_progress(pct, msg)

        # -----------------------------------------------------------
        # Services — created lazily (only when first needed)
        # -----------------------------------------------------------
        self._unmand = None

        # Keep worker references alive so the QThreads aren't garbage
        # collected mid-run.
        self._upload_worker   = None
        self._validate_worker = None

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

        elif btn == "send_unmand":
            self.log.info("Send to Unmand triggered")
            self._start_unmand()

        elif btn == "check_status":
            self.log.info(f"Check Unmand status triggered | guid={self.suite.state.get('guid')}")
            self._check_unmand()

        elif btn == "open_billing_output":
            billing_output_file = self.suite.state.get("billing_output_file")
            self.log.info(f"Opening billing output | path={billing_output_file}")
            if billing_output_file:
                os.startfile(billing_output_file)

        elif btn == "checker_upload":
            billing_cfg = self.suite.state.get("billing_config") or {}
            cc_names    = billing_cfg.get("expected_contact_center")
            additional_column_map    = billing_cfg.get("additional_column_map")
            self.log.info("Billing checker upload triggered")
            self.suite.body.billing.show_processing_progress("Opening local folder...", "checker")
            self.checker.prepare_checker_files(cc_names, additional_column_map)

        elif btn == "open_checker_output":
            variance_file = self.suite.state["billing_variance_file"]
            self.log.info(f"Opening billing checker output | path={variance_file}")
            os.startfile(variance_file)

        elif btn in ["client_billing_info", "discounts"]:
            url = self.suite.state["billing_config"][btn]
            self.log.info(f"Opening Payroll Headers | url={url}")
            webbrowser.open(url)

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

        Check Variance is real; Automation/Settings land on the shared
        "coming soon" placeholder until they're scaffolded out.
        """
        self.log.event("Feature selected", feature=feature)
        self.suite.state["feature"] = feature

        if feature == "settings_feature":
            self.suite.body.billing.show_settings_feature()

        elif feature == "checker_feature":
            self.log.info("Checker Selected")
            self.suite.body.billing.show_checker_feature()

        elif feature == "billing_feature":
            billing_cfg    = self.suite.state.get("billing_config") or {}
            required_files = billing_cfg.get("required_files", [])
            self.log.info(f"Billing Automation Selected | required_files={len(required_files)}")
            self.suite.body.billing.show_billing_feature(required_files)

        else:
            title = self._COMING_SOON_TITLES.get(feature, "This feature")
            self.suite.body.billing.show_coming_soon(title)

    def _on_tool_selected(self, tool: str):
        """Navigate to the selected tool screen — placeholder for now."""
        self.log.event("Tool selected", tool=tool)
        self.suite.state["feature"] = tool

        title = self._COMING_SOON_TITLES.get(tool, "This tool")
        self.suite.body.billing.show_coming_soon(title)

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

        state       = self.suite.state
        billing_cfg = state.get("billing_config") or {}
        required_files = billing_cfg.get("required_files", [])

        state["billing_run_id"] = self.suite.inputs["id"] or datetime.now().strftime("%Y%m%d_%H%M%S")

        self.suite.body.billing.show_processing_progress("Opening local folder...", "billing")
        self.billing.prepare_billing_files(required_files, billing_cfg)

    def _billing_files_preparation_result(self, codes: list):
        """Handle result codes emitted by BillingFeature."""
        self.log.section("BILLING VALIDATION RESULT")
        self.log.info(f"Billing file preparation complete | code_count={len(codes)}")

        for code in codes:
            file_name, status_code = parse_status_code(code)
            message_template       = BILLING_STATUSES.get(status_code, status_code)
            message                = message_template.format(file_name=file_name or "")
            is_error               = "error" in status_code

            self.log.result(
                step=f"Billing file validation — {file_name or status_code}",
                success=not is_error,
                detail=message,
            )

        self.suite.body.billing.show_billing_status(codes)

    def _upload_sp_files(self, files: dict):
        """Upload prepared billing DataFrames as CSV files to SharePoint."""
        self.log.section("BILLING SHAREPOINT UPLOAD")

        state       = self.suite.state
        billing_cfg = state.get("billing_config") or {}
        folder      = self.suite._env_url(billing_cfg.get("folder", "")) 
        base_url    = f"{self.suite._sp_base_url}root:/{folder}"

        self.log.info(f"Uploading {len(files)} file(s) to SharePoint | folder={folder}")

        self._upload_worker = _BillingSharePointUploadWorker(
            files      = files,
            sharepoint = self.suite._sharepoint,
            base_url   = base_url,
            run_id     = state.get("billing_run_id", ""),
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
    # CHECKER MAIN FLOW
    # ===================================================================

    def _checker_files_preparation_result(self, codes: list):
        """Handle result codes emitted by BillingCheckerFeature."""
        self.log.section("BILLING CHECKER VALIDATION RESULT")
        self.log.info(f"Checker file preparation complete | code_count={len(codes)}")

        for code in codes:
            file_name, status_code = parse_status_code(code)
            message_template       = BILLING_CHECKER_STATUSES.get(status_code, status_code)
            message                = message_template.format(file_name=file_name or "")
            is_error               = "error" in status_code

            self.log.result(
                step=f"Billing checker file — {file_name or status_code}",
                success=not is_error,
                detail=message,
            )

        self.suite.body.billing.show_checker_status(codes)

    def _generate_validation(self, files: dict):
        """Generate the variance report in a background thread."""
        self.log.section("BILLING CHECKER VALIDATION")
        self.log.info("Starting billing checker variance generation")

        billing_cfg   = self.suite.state.get("billing_config") or {}
        var_tolerance = billing_cfg.get("var_tolerance", 0)

        self.suite.body.billing.show_processing_progress("Running checker validation…", "checker")

        #self.checker.generate(files)

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

