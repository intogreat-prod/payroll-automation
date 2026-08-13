"""
orchestrators/billing_orchestrator.py
--------------------------------------
Child orchestrator for the Billing app.

Billing Automation and Settings haven't been scaffolded out yet, so those
route to BillingBody.show_coming_soon() (see
ui/components/body_apps/billing_app.py) instead of trying to render a
half-built screen. Check Variance (the Checker) is real — it mirrors
PayrollOrchestrator's Checker flow: a 2-file upload, an async worker for
the variance generation, and live progress reported back to the UI.

When the rest of Billing gets real features:
    1. Add feature modules under features/billing/ (mirroring features/payroll/).
    2. Build out the real screen(s) in ui/components/body_apps/billing_app.py.
    3. Swap the relevant show_coming_soon(...) call below for the new
       show_*_feature() call, the same way PayrollOrchestrator routes
       "menu"/"source"/"feature"/"tool" actions to their own handler
       methods.

Holds a reference to the suite root (`suite`) the same way
PayrollOrchestrator does, so it can read/write suite.state and call
suite.body.billing.show_*().
"""


import os
import webbrowser

from PyQt6.QtCore import QThread, pyqtSignal

from features.billing.checker import BillingCheckerFeature
from ui.statuses import parse_status_code, BILLING_CHECKER_STATUSES


# ---------------------------------------------------------------------------
# Background worker (Billing Checker)
# ---------------------------------------------------------------------------

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
        self.checker = BillingCheckerFeature(self.log, suite.main_window)

        self.checker.on_result      = self._checker_files_preparation_result
        self.checker.uploaded_files = self._generate_validation
        self.checker.on_progress    = lambda pct, msg: suite.body.billing.update_processing_progress(pct, msg)

        # Keep the validation worker reference alive so the QThread isn't
        # garbage collected mid-run.
        self._validate_worker = None

    # ===================================================================
    # DISPATCH — entry point called by the suite root for any click
    # while the Billing app is active
    # ===================================================================

    def handle_click(self, btn):
        """
        Route Billing-app button events.

        Extend this the same way PayrollOrchestrator.handle_click() does
        as real Billing screens get built out.
        """
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
        "billing_feature":   "Billing Automation",
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

