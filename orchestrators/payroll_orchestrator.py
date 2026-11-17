"""
orchestrators/payroll_orchestrator.py
--------------------------------------
Everything under the Payroll app: Automation (upload + Unmand), Tools
(DarwinBox → Sprout, Attendance Summary), Checker, and Settings
(deminimis, add user).

This used to all live inline in orchestrator.py. It's been split out here
because that file was becoming one giant class covering every app in the
suite — Payroll's flow now lives in its own orchestrator, Billing gets its
own (see billing_orchestrator.py), and the suite root only handles login,
config, updates, and top-level navigation between apps.

PayrollOrchestrator holds a reference to the suite root (`suite`) and reads/
writes `suite.state` directly — state is still one shared dict, this class
just owns the handling code for the Payroll slice of it.

Architecture (unchanged from before the split)
-----------------------------------------------
    PayrollOrchestrator  →  calls suite.body.payroll.show_*()  →  Body renders
    Body                 →  fires on_* callbacks               →  handled here

The UI (Body) never calls a service directly. Services never touch the UI.
"""

import io
import os
import re
import webbrowser

import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal

from features.payroll.checker import CheckerFeature
from features.payroll.payroll import PayrollFeature
from features.payroll.dbx_to_sprout import DarwinToSproutTool
from features.payroll.attendance_summary import AttendanceSummaryTool
from features.payroll.payroll_premiums import PayrollPremiumsTool
from services.sharepoint_list_service import SharePointListService
from services.config_service import ConfigService
from services.unmand_service import UnmandService
from ui.statuses import resolve, SUCCESS
from utils.app_config_user import get
from utils.internet import ok



# ---------------------------------------------------------------------------
# Background workers (Payroll-only)
# ---------------------------------------------------------------------------

class _SharePointUploadWorker(QThread):
    """Uploads payroll CSV files to SharePoint off the main thread."""
    progress = pyqtSignal(int, str)     # current file name and progress
    finished = pyqtSignal(list)         # list of failed logical names (empty = all OK)

    def __init__(self, files: dict, sharepoint, base_url: str, run_id: str, version: str, log):
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

            self.progress.emit(int(progress), file_name)
            self.log.info(f"SPUploadWorker: Uploading | name={file_name} | {url}")

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


class _ValidationWorker(QThread):
    """Runs the variance report generation off the main thread."""
    progress = pyqtSignal(int, str)           # percent, message
    finished = pyqtSignal(bool, object)       # success, file_path | error_code

    def __init__(self, files: dict, headers: list, source: str, var_tolerance, log, checker):
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


class _DBXConversionWorker(QThread):
    """Runs the conversion to sprout off the main thread."""
    progress = pyqtSignal(int, str)           # percent, message
    finished = pyqtSignal(bool, object)       # success, file_path | error_code

    def __init__(self, files: dict, header_map: dict, log, dbx_to_sprout):
        super().__init__()
        self.files         = files
        self.header_map    = header_map
        self.log           = log
        self.dbx_to_sprout = dbx_to_sprout

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


class _PremiumsWorker(QThread):
    """Runs the Payroll Premiums generation off the main thread."""
    progress = pyqtSignal(int, str)           # percent, message
    finished = pyqtSignal(bool, object)       # success, file_path | error_code

    def __init__(self, files: dict, lists,log, premiums,):
        super().__init__()
        self.files    = files
        self.lists    = lists
        self.log      = log
        self.premiums = premiums


    def run(self):
        self.premiums.on_progress = lambda pct, msg: self.progress.emit(pct, msg)

        try:
            result = self.premiums.generate(self.files, self.lists)
            self.finished.emit(True, result)
        except Exception as e:
            self.log.error(f"_PremiumsWorker: Failed — {e}", error=e)
            self.finished.emit(False, "processing_error")
        finally:
            self.premiums.on_progress = None


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
# PayrollOrchestrator
# ---------------------------------------------------------------------------

class PayrollOrchestrator:
    """
    Child orchestrator for the Payroll app.

    Args:
        suite: the suite-root Orchestrator instance. Provides shared state
               (suite.state), UI (suite.body), services (suite._sharepoint,
               suite._sp_base_url, suite._env_url), and app-wide helpers
               (suite.inputs) that Payroll's flow reads and writes.
    """

    def __init__(self, suite):
        self.suite = suite
        # Tagged logger — every line from this app is prefixed "[Payroll]"
        # in the shared session log file.
        self.log = suite.log.for_module("Payroll")

        # -----------------------------------------------------------
        # Feature and tool modules (Payroll-only)
        # -----------------------------------------------------------
        self.log.info("PayrollOrchestrator: Initialising feature modules")
        self.payroll         = PayrollFeature(self.log, suite.main_window)
        self.checker         = CheckerFeature(self.log, suite.main_window)
        self.dbx_to_sprout   = DarwinToSproutTool(self.log, suite.main_window)
        self.att_summary_svc = AttendanceSummaryTool(self.log, suite.main_window)
        self.premiums_svc    = PayrollPremiumsTool(self.log, suite.main_window)

        self.payroll.on_result      = self._payroll_files_preparation_result
        self.payroll.uploaded_files = self._upload_sp_files
        self.payroll.on_progress    = lambda pct, msg: suite.body.payroll.update_processing_progress(pct, msg)

        self.checker.on_result      = self._checker_files_preparation_result
        self.checker.uploaded_files = self._generate_validation
        self.checker.on_progress    = lambda pct, msg: suite.body.payroll.update_processing_progress(pct, msg)

        self.dbx_to_sprout.on_result      = self._dbx_payroll_preparation_result
        self.dbx_to_sprout.uploaded_files = self._convert_payroll
        self.dbx_to_sprout.on_progress    = lambda pct, msg: suite.body.payroll.update_processing_progress(pct, msg)

        self.att_summary_svc.on_result      = self._att_summary_preparation_result
        self.att_summary_svc.uploaded_files = self._run_attendance_summary
        self.att_summary_svc.on_progress    = lambda pct, msg: suite.body.payroll.update_processing_progress(pct, msg)

        self.premiums_svc.on_result      = self._premiums_preparation_result
        self.premiums_svc.uploaded_files = self._generate_premiums
        self.premiums_svc.on_progress    = lambda pct, msg: suite.body.payroll.update_processing_progress(pct, msg)

        self.log.info("PayrollOrchestrator: Feature callbacks wired")

        # -----------------------------------------------------------
        # Services — created lazily (only when first needed)
        # -----------------------------------------------------------
        self._unmand     = None
        self._config_svc = None

        # Keep worker references so QThreads aren't garbage collected
        self._upload_worker      = None
        self._validate_worker    = None
        self._att_summary_worker = None
        self._premiums_worker    = None

    # ===================================================================
    # DISPATCH — entry point called by the suite root for any click
    # while the Payroll app is active
    # ===================================================================

    def handle_click(self, btn):
        """
        Route Payroll-app button events.

        List payloads (btn is a list) carry data from the UI:
            ["payroll_upload", id_str, version_str]
            ["save_deminimis", deminimis_dict]
            ["add_user",       email_str]

        String payloads are simple named actions.
        """
        if isinstance(btn, list):
            action = btn[0]

            if action == "payroll_upload":
                self.suite.inputs["id"]      = btn[1].strip()
                self.suite.inputs["version"] = btn[2].strip()
                self.log.info(
                    f"Payroll upload triggered | "
                    f"id_input='{self.suite.inputs['id']}' "
                    f"version_input='{self.suite.inputs['version']}'"
                )
                self._on_payroll_upload_clicked()

            elif action == "save_deminimis":
                self.log.info("Save deminimis triggered")
                self._save_deminimis(btn[1])

            else:
                self.log.warning(f"Unhandled list action | action={action}")
            return

        # ── Simple named actions ──────────────────────────────────────
        
        if btn == "home":
            self.suite.state["app"] = None
            self.suite.state["menu"] = None
            self.suite.state["source"] = None
            self.suite.state["feature"] = None
            self.suite.state["tool"] = None
            self.suite.body.show_suite_menu()

        elif "menu" in btn:
            self._on_menu_selected(btn)

        elif "source" in btn:
            self._on_source_selected(btn)

        elif "tool" in btn:
            self._on_tool_selected(btn)

        elif "feature" in btn:
            self._on_feature_selected(btn)

        elif btn == "back":
            self.go_home()

        elif btn == "send_unmand":
            self.log.info("Send to Unmand triggered")
            self._start_unmand()

        elif btn == "check_status":
            self.log.info(f"Check Unmand status triggered | guid={self.suite.state.get('guid')}")
            self._check_unmand()

        elif btn == "open_new_headers":
            payroll_unmand = self.suite.state["payroll_config"]["automation"]["unmand"]
            url = payroll_unmand["new_headers_url"]
            self.log.info(f"Opening new headers URL | url={url}")
            webbrowser.open(url)

        elif btn == "open_payroll_ouput":
            payroll_unmand = self.suite.state["payroll_config"]["automation"]["unmand"]
            url = (
                self.suite._env_url(payroll_unmand["output_folder"])
                + self.suite.state["folder_name"].replace("input", "output")
            )
            self.log.info(f"Opening payroll output URL | url={url}")
            webbrowser.open(url)

        elif btn == "checker_upload":
            id_names = self.suite.state["payroll_config"]["expected_id_names"]
            self.log.info("Checker upload triggered")
            self.suite.body.payroll.show_processing_progress("Opening local folder...", "checker")
            self.checker.prepare_checker_files(id_names)

        elif btn == "open_checker_output":
            variance_file = self.suite.state["variance_file"]
            self.log.info(f"Opening checker output | path={variance_file}")
            os.startfile(variance_file)

        elif btn == "open_dbx_to_sprout_output":
            converted_file = self.suite.state["converted_file"]
            self.log.info(f"Opening DBX to Sprout output | path={converted_file}")
            os.startfile(converted_file)

        elif btn == "open_att_summary_output":
            att_summary_file = self.suite.state.get("att_summary_file")
            self.log.info(f"Opening attendance summary output | path={att_summary_file}")
            if att_summary_file:
                os.startfile(att_summary_file)

        elif btn == "open_payroll_premium_output":
            premiums_file = self.suite.state.get("premiums_file")
            self.log.info(f"Opening payroll premiums output | path={premiums_file}")
            if premiums_file:
                os.startfile(premiums_file)

        elif btn == "payroll_headers":
            payroll_unmand = self.suite.state["payroll_config"]["automation"]["unmand"]
            url = payroll_unmand["headers_url"]
            self.log.info(f"Opening Payroll Headers | url={url}")
            webbrowser.open(url)

        elif btn == "holiday_calendar":
            payroll_unmand = self.suite.state["payroll_config"]["tools"]["payroll_premiums"]
            url = payroll_unmand["holiday_calendar"]
            self.log.info(f"Opening Holiday Calendar List | url={url}")
            webbrowser.open(url)

        elif btn == "nd_list":
            payroll_unmand = self.suite.state["payroll_config"]["automation"]["unmand"]
            url = payroll_unmand["nd_list_url"]
            self.log.info(f"Opening Night Differential List | url={url}")
            webbrowser.open(url)

        elif btn == "dbx_to_sprout_upload":
            id_names = self.suite.state["payroll_config"]["expected_id_names"]
            self.log.info("DarwinBox Payroll Register upload triggered")
            self.suite.body.payroll.show_processing_progress("Opening local folder...", "dbx_to_sprout")
            self.dbx_to_sprout.prepare_darwinbox_payroll(id_names)

        elif btn == "payroll_premiums_upload":
            id_names = self.suite.state["payroll_config"]["expected_id_names"]
            self.log.info("Payroll Premiums upload triggered")
            self.suite.body.payroll.show_processing_progress("Opening local folder...", "payroll_premiums")
            self.premiums_svc.prepare_premium_files(id_names)

        elif btn == "att_summary_upload":
            self.log.info("DarwinBox Attendance Report upload triggered")
            # Store date picker values before opening file dialog
            self.suite.state["att_start_date"]  = self.suite.body.start_date.date().toString("yyyy-MM-dd")
            self.suite.state["att_cutoff_date"] = self.suite.body.cutoff.date().toString("yyyy-MM-dd")
            self.att_summary_svc.prepare_attendance_file(
                self.suite.state["att_start_date"],
                self.suite.state["att_cutoff_date"],
            )
            self.suite.body.payroll.show_processing_progress("Opening local folder...", "att_summary")

        else:
            self.log.warning(f"Unhandled action | action={btn}")

    def go_home(self):
        """Called by the suite root when 'home'/'back' is pressed while this app is active."""
        self.suite.state["menu"] = None
        self.suite.state["source"] = None
        self.suite.state["feature"] = None
        self.suite.state["tool"] = None
        self.suite.body.payroll.show_menu()

    # ===================================================================
    # NAVIGATION
    # ===================================================================

    def _on_menu_selected(self, menu: str):
        """Store the selected data menu and advance to their screen."""

        clean_menu = menu.replace("_menu", "")
        self.suite.state["menu"] = clean_menu
        self.log.event("Menu selected", menu=clean_menu)

        if "automation" == clean_menu:
            self.suite.body.payroll.show_sources()
        elif "tools" == clean_menu:
            self.suite.body.payroll.show_tools()

    def _on_source_selected(self, source: str):
        """Store the selected data source and advance to the feature screen."""
        if "source" in source:
            clean_source = source.replace("_source", "")
            self.log.event("Source selected", source=clean_source)
            self.suite.state["source"] = clean_source

            if "DarwinBox" in source:
                self.suite.body.payroll.show_darwin_features()
            else:
                self.suite.body.payroll.show_sprout_features()

    def _on_feature_selected(self, feature: str):
        """
        Navigate to the selected feature screen.

        Pulls the data it needs from state["config"] so the features
        themselves stay decoupled from the config schema.
        """
        self.log.event("Feature selected", feature=feature, source=self.suite.state["source"])
        self.suite.state["feature"] = feature

        payroll_unmand = self.suite.state["payroll_config"]["automation"]["unmand"]
        required_files = payroll_unmand["required_files"]

        if feature == "payroll_feature":
            self.log.info(f"Payroll Selected | required_files={len(required_files)}")
            self.suite.body.payroll.show_payroll_feature(required_files, self.suite.state["source"])

        elif feature == "checker_feature":
            self.log.info("Checker Selected")
            self.suite.body.payroll.show_checker_feature(self.suite.state["source"])
        elif feature == "settings_feature":
            deminimis = self.suite.state["payroll_config"]["settings"]["deminimis"]
            self.suite.body.payroll.show_settings(deminimis)    

    def _on_tool_selected(self, tool: str):
        """Navigate to the selected tool screen."""
        clean_tool = tool.replace("_tool", "")
        self.suite.state["tool"] = clean_tool
        self.log.event("Tool selected | required_files=1", tool=clean_tool)

        if clean_tool == "dbx_to_sprout":
            self.suite.body.payroll.show_dbx_to_sprout_tool()
        elif clean_tool == "attendance_summary":
            self.suite.body.payroll.show_attendance_summary_tool()
        elif clean_tool == "payroll_premiums":
            self.suite.body.payroll.show_payroll_premiums_tool()

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
        self.log.info("Payroll upload initiated")

        state = self.suite.state
        default_folder = (
            f"{state['month_year']}/"
            f"{state['id']}/"
            f"{state['version']}/input"
        )
        state["folder_name"] = default_folder
        self.log.info(f"Default folder path set | path={default_folder}")

        if self.suite.inputs["id"] or self.suite.inputs["version"]:
            self.log.info("Custom ID/Version detected — running validation")
            version_status = self._id_version_checks()

            if version_status:
                self.log.warning(f"Version check failed | codes={version_status}")
                self.suite.body.payroll.show_payroll_status(version_status)
                return

        payroll_cfg    = state["payroll_config"]["automations"]
        expected_files = payroll_cfg["required_files"]
        source         = state["source"]
        token          = state["token"]

        self.log.info(
            f"Starting file preparation | "
            f"source={source} expected_files={len(expected_files)}"
        )
        self.suite.body.payroll.show_processing_progress("Opening local folder...", "payroll")
        self.payroll.prepare_payroll_files(expected_files, payroll_cfg, source, token)

    def _payroll_files_preparation_result(self, codes: list):
        """Handle result codes emitted by PayrollFeature."""
        self.log.section("PAYROLL VALIDATION RESULT")
        self.log.info(f"Payroll file preparation complete | code_count={len(codes)}")

        for code in codes:
            r = resolve("payroll", code)
            self.log.result(
                step=f"File validation — {r.value or r.key}",
                success=r.ok,
                detail=r.message,
            )

        self.suite.body.payroll.show_payroll_status(codes)

    def _id_version_checks(self) -> list:
        """
        Validate user-supplied ID and version inputs against SharePoint.

        Returns an empty list on success, or a list of status-code strings
        on failure.
        """
        self.log.section("ID / VERSION VALIDATION")
        self.log.info("Running ID/Version input validation")

        state = self.suite.state

        def _found_folder(name: str, folders: list) -> bool:
            return any(f["name"] == name for f in folders)

        if self.suite.inputs["id"] and not self.suite.inputs["version"]:
            self.log.warning("ID provided without version")
            return ["version_missing_error"]

        if not self.suite.inputs["id"] and self.suite.inputs["version"]:
            self.log.warning("Version provided without ID")
            return ["id_missing_error"]

        raw_version = self.suite.inputs["version"]

        if raw_version.isdigit():
            version = f"v{raw_version}"
        elif re.fullmatch(r"v\d+", raw_version):
            version = raw_version
        else:
            self.log.warning(f"Invalid version format | input='{raw_version}'")
            return ["version_input_error"]

        self.log.info(f"Version normalised | raw={raw_version} normalised={version}")

        payroll_folder = self.suite._env_url(state["payroll_config"]["folder"])
        month_year     = state["month_year"]

        url      = f"{self.suite._sp_base_url}root:/{payroll_folder}/{month_year}:/children"
        response = self.suite._sharepoint.get(url)
        sp_id_folder_list = response.json().get("value", [])

        if not _found_folder(self.suite.inputs["id"], sp_id_folder_list):
            self.log.warning(f"ID folder not found | id={self.suite.inputs['id']}")
            return ["id_error"]

        url      = f"{self.suite._sp_base_url}root:/{payroll_folder}/{month_year}/{self.suite.inputs['id']}:/children"
        response = self.suite._sharepoint.get(url)
        sp_version_folder_list = response.json().get("value", [])

        if _found_folder(version, sp_version_folder_list):
            self.log.warning(f"Duplicate version folder | version={version}")
            return ["version_duplicate_error"]

        state["id"]          = self.suite.inputs["id"]
        state["version"]     = version
        state["folder_name"] = f"{month_year}/{self.suite.inputs['id']}/{version}/input"

        self.log.info(f"ID/Version validation passed | id={state['id']} version={version}")
        return []

    def _upload_sp_files(self, files: dict):
        """
        Upload prepared payroll DataFrames as CSV files to SharePoint
        using a background thread.
        """
        self.log.section("SHAREPOINT UPLOAD")

        state    = self.suite.state
        folder   = self.suite._env_url(state["payroll_config"]["folder"]) + state["folder_name"]
        base_url = f"{self.suite._sp_base_url}root:/{folder}"

        self.log.info(f"Uploading {len(files)} file(s) to SharePoint | folder={folder}")

        self._upload_worker = _SharePointUploadWorker(
            files      = files,
            sharepoint = self.suite._sharepoint,
            base_url   = base_url,
            run_id     = state["id"],
            version    = state["version"],
            log        = self.log,
        )
        self._upload_worker.progress.connect(
            lambda prog, fname: _upload_progress(prog, fname)
        )
        self._upload_worker.finished.connect(self._on_upload_finished)
        self._upload_worker.start()

        def _upload_progress(progress, file_name):
            self.log.info(f"Uploading {file_name}...")
            self.suite.body.payroll.update_processing_progress(progress, f"Uploading {file_name} to Unmand")

    def _on_upload_finished(self, errors: list):
        state = self.suite.state
        if errors:
            self.log.warning(f"SharePoint upload failed | files={errors}")
            self.suite.body.payroll.show_payroll_status(["upload_sp_error"])
        else:
            self.log.info(
                f"All files uploaded | "
                f"id={state['id']} version={state['version']}"
            )
            self.suite.body.payroll.show_payroll_status(["file_success"])

    def _start_unmand(self):
        """Trigger the Unmand payroll processing workflow."""
        self.log.section("UNMAND START")

        state = self.suite.state
        unmand_flow = state["payroll_config"]["automation"]["unmand"]["flow"]
        api_token   = unmand_flow[self.suite.envt]["token"]
        webhook_url = unmand_flow[self.suite.envt]["webhook"]

        self.log.info("Creating UnmandService")
        self._unmand = UnmandService(webhook_url, api_token)

        other_files = [
            f for f in state["payroll_config"]["required_files"]
            if "payroll" not in f and "attendance" not in f
        ]

        payload = {
            "local_app": {
                "id":          state["id"],
                "version":     state["version"],
                "folder_name": state["folder_name"],
                "userEmail":   state["email"],
                "userName":    state["name"],
                "month_year":  state["month_year"],
                "other_files": other_files,
                "source_type": state["source"],
            },
            "status":  {},
            "process": "payroll",
        }

        self.log.info(
            f"Sending Unmand payload | "
            f"id={state['id']} version={state['version']} "
            f"source={state['source']}"
        )
        response = self._unmand.start_process(payload)
        success  = ok(response)
        self.log.result("Unmand start", success=success, detail=f"HTTP {response.status_code}")

        if not success:
            self.suite.body.payroll.show_payroll_status(["unmand_init_error"])
        else:
            state["guid"] = response.json().get("taskGuid")
            id_version = (
                f"ID: {state['id']} "
                f"Version: {state['version']} "
                f"Source: {state['source']}"
            )
            self.log.info(f"Unmand started | guid={state['guid']}")
            self.suite.body.payroll.show_payroll_status([f"{id_version}|unmand_init_success"])

    def _check_unmand(self):
        """Poll Unmand for the current task status and update the UI."""
        self.log.section("UNMAND STATUS CHECK")
        state = self.suite.state
        guid = state.get("guid")
        self.log.info(f"Checking Unmand task status | guid={guid}")

        status = self._unmand.check_status(guid)
        self.log.info(f"Unmand status received | status={status}")

        if resolve("payroll", status).level == SUCCESS:
            id_version = f"ID: {state['id']} - Version: {state['version']}"
            status = f"{status}|{id_version}"

        self.suite.body.payroll.show_payroll_status([status])

    # ===================================================================
    # ADDITIONAL TOOLS MAIN FLOW
    # ===================================================================

    def _dbx_payroll_preparation_result(self, codes: list):
        """Handle result codes emitted by DarwinToSproutTool."""
        self.log.section("DARWINBOX VALIDATION RESULT")
        self.log.info(f"DarwinBox file preparation complete | code_count={len(codes)}")

        for code in codes:
            r = resolve("dbx_to_sprout", code)
            self.log.result(
                step=f"DarwinBox file — {r.value or r.key}",
                success=r.ok,
                detail=r.message,
            )

        self.suite.body.payroll.show_dbx_to_sprout_status(codes)

    def _convert_payroll(self, files: dict):
        """
        Download payroll headers from SharePoint, then generate the
        variance report in a background thread.
        """
        self.log.section("DARWINBOX TO SPROUT CONVERSION TOOL")
        self.log.info("Starting checker conversion tool")

        state       = self.suite.state
        headers_loc = state["payroll_config"]["headers_loc"]
        url         = f"{self.suite._sp_base_url}{headers_loc}"

        self.log.info("Downloading payroll headers from SharePoint")
        response = self.suite._sharepoint.get(url)

        if not ok(response):
            self.log.warning(f"Headers download failed | HTTP={response.status_code}")
            self.suite.body.payroll.show_dbx_to_sprout_status(["premium_download_error"])
            return

        source     = "DarwinBox"
        sheet_name = "Sprout Checker" if source == "Sprout" else "DarwinBox Checker"
        self.log.info(f"Reading headers sheet | sheet={sheet_name}")

        df = pd.read_excel(io.BytesIO(response.content), sheet_name=sheet_name, header=12, engine="openpyxl")
        header_map = dict(
            zip(
                df["Payroll Headers"],
                df["Sprout Payroll Headers"]
            )
        )
        self.log.info(f"Loaded {len(header_map)} payroll header(s)")

        self.suite.body.payroll.show_processing_progress("Converting payroll file…", "dbx_to_sprout")

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
            state = self.suite.state
            state["converted_file"] = result
            self.log.info(f"Conversion report written | path={result}")
            self.suite.body.payroll.show_dbx_to_sprout_status(["converted_success"])
        else:
            self.log.warning(f"Conversion generation failed | code={result}")
            self.suite.body.payroll.show_dbx_to_sprout_status([result])

    # ===================================================================
    # PAYROLL PREMIUMS MAIN FLOW
    # ===================================================================

    def _premiums_preparation_result(self, codes: list):
        """Handle result codes emitted by PayrollPremiumsTool."""
        self.log.section("PAYROLL PREMIUMS VALIDATION RESULT")
        self.log.info(f"Payroll Premiums file preparation complete | code_count={len(codes)}")

        for code in codes:
            r = resolve("payroll_premiums", code)
            self.log.result(
                step=f"Payroll Premiums file — {r.value or r.key}",
                success=r.ok,
                detail=r.message,
            )

        self.suite.body.payroll.show_payroll_premiums_status(codes)

    def _generate_premiums(self, files: dict):
        """Combine the validated Attendance Summary with the holiday list in a background thread."""
        self.log.section("PAYROLL PREMIUMS GENERATION")

        self.suite.body.payroll.show_processing_progress("Generating payroll premiums…", "payroll_premiums")

        cfg   = self.suite.state["payroll_config"]["tools"]["payroll_premiums"]
        lists = SharePointListService(self.suite.state["token"], cfg["site_id"], cfg["holiday_list_id"])

        #self.premiums_svc.generate(files, lists)

        self._premiums_worker = _PremiumsWorker(
            files    = files,
            lists    = lists,
            log      = self.log,
            premiums = self.premiums_svc
        )
        self._premiums_worker.progress.connect(self._on_processing_progress)
        self._premiums_worker.finished.connect(self._on_premiums_done)
        self._premiums_worker.start()

    def _on_premiums_done(self, success: bool, result):
        if success:
            self.suite.state["premiums_file"] = result
            self.log.info(f"Payroll premiums workbook written | path={result}")
            self.suite.body.payroll.show_payroll_premiums_status(["premiums_success"])
        else:
            self.log.warning(f"Payroll premiums generation failed | code={result}")
            self.suite.body.payroll.show_payroll_premiums_status([result])

    # ===================================================================
    # CHECKER MAIN FLOW
    # ===================================================================

    def _checker_files_preparation_result(self, codes: list):
        """Handle result codes emitted by CheckerFeature."""
        self.log.section("CHECKER VALIDATION RESULT")
        self.log.info(f"Checker file preparation complete | code_count={len(codes)}")

        for code in codes:
            r = resolve("payroll_checker", code)
            self.log.result(
                step=f"Checker file — {r.value or r.key}",
                success=r.ok,
                detail=r.message,
            )

        self.suite.body.payroll.show_checker_status(codes)

    def _generate_validation(self, files: dict):
        """
        Download payroll headers from SharePoint, then generate the
        variance report in a background thread.
        """
        self.log.section("CHECKER VALIDATION")
        self.log.info("Starting checker variance generation")

        state       = self.suite.state
        headers_loc = state["payroll_config"]["payroll"]["headers_loc"]
        url         = f"{self.suite._sp_base_url}{headers_loc}"

        self.log.info("Downloading payroll headers from SharePoint")
        response = self.suite._sharepoint.get(url)

        if not ok(response):
            self.log.warning(f"Headers download failed | HTTP={response.status_code}")
            self.suite.body.payroll.show_checker_status(["premium_download_error"])
            return

        source     = state["source"]
        sheet_name = "Sprout Checker" if source == "Sprout" else "DarwinBox Checker"
        self.log.info(f"Reading headers sheet | sheet={sheet_name}")

        df      = pd.read_excel(io.BytesIO(response.content), sheet_name=sheet_name, header=12, engine="openpyxl")
        headers = list(df["Payroll Headers"])
        self.log.info(f"Loaded {len(headers)} payroll header(s)")

        var_tolerance = state["payroll_config"].get("var_tolerance", 0)

        self.suite.body.payroll.show_processing_progress("Running checker validation…", "checker")

        self._validate_worker = _ValidationWorker(
            files         = files,
            headers       = headers,
            source        = source,
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
            state["variance_file"] = result
            self.log.info(f"Variance report written | path={result}")
            self.suite.body.payroll.show_checker_status(["validated_success"])
        else:
            self.log.warning(f"Variance generation failed | code={result}")
            self.suite.body.payroll.show_checker_status([result])

    # ===================================================================
    # ATTENDANCE SUMMARY MAIN FLOW
    # ===================================================================

    def _att_summary_preparation_result(self, codes: list):
        """Handle result codes emitted by AttendanceSummaryTool."""
        self.log.section("ATTENDANCE SUMMARY VALIDATION RESULT")
        self.log.info(f"Attendance file preparation complete | code_count={len(codes)}")

        for code in codes:
            r = resolve("attendance_summary", code)

            self.log.result(
                step=f"Attendance file — {r.value or r.key}",
                success=r.ok,
                detail=r.message,
            )
        self.suite.body.payroll.show_attendance_summary_status(codes)

    def _run_attendance_summary(self, files: dict):
        """Process the attendance file in a background thread."""
        self.log.section("ATTENDANCE SUMMARY PROCESSING")
        self.log.info("Starting attendance summary generation")

        state       = self.suite.state
        start_date  = state.get("att_start_date", "")
        cutoff_date = state.get("att_cutoff_date", "")

        self.suite.body.payroll.show_processing_progress("Generating attendance summary…", "att_summary")

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
        state = self.suite.state
        if success:
            state["att_summary_file"] = result
            self.log.info(f"Attendance summary written | path={result}")
            self.suite.body.payroll.show_attendance_summary_status(["summarized_success"])
        else:
            self.log.warning(f"Attendance summary failed | code={result}")
            self.suite.body.payroll.show_attendance_summary_status([result])

    # ===================================================================
    # SETTINGS MAIN FLOW
    # ===================================================================

    def _save_deminimis(self, deminimis: dict):
        """
        Validate and persist updated deminimis values to SharePoint.

        Non-empty inputs override the current value; empty inputs keep
        the existing payroll_config value unchanged.
        """
        self.log.section("SAVE DEMINIMIS")
        self.log.info("Processing deminimis save request")

        state = self.suite.state
        current_deminimis = state["payroll_config"]["deminimis"]
        new_deminimis     = {}

        if not any(deminimis.values()):
            self.suite.body.payroll.show_settings_save_deminimis_status("error_value")
            return

        for key, val in deminimis.items():
            if val:
                try:
                    new_deminimis[key] = float(val)
                    self.log.info(f"Deminimis updated | key={key} value={float(val)}")
                except (ValueError, TypeError):
                    self.log.warning(f"Invalid deminimis value | key={key} value={val!r}")
                    self.suite.body.payroll.show_settings_save_deminimis_status("deminimis_save_error")
                    return
            else:
                new_deminimis[key] = current_deminimis[key]

        state["payroll_config"]["deminimis"] = new_deminimis

        self.log.info("Saving updated deminimis to SharePoint")
        self._config_svc = ConfigService(state["app_config"]["app_config"]["payroll"])
        response = self._config_svc.update(state["payroll_config"], state["token"])
        success  = ok(response)

        self.log.result("Save deminimis", success=success, detail=f"HTTP {response.status_code}")

        if not success:
            self.suite.body.payroll.show_settings_save_deminimis_status("deminimis_save_error")
            return
        self.suite.body.payroll.show_settings_save_deminimis_status("deminimis_save_success")

        # Reload config silently (no update check) then refresh settings screen
        self.suite.reload_config_silent(on_done=lambda: self.handle_click("settings"), config_type="payroll")

    # ===================================================================
    # THREAD (PROGRESS UPDATE)
    # ===================================================================

    def _on_processing_progress(self, percent: int, message: str):
        self.suite.body.payroll.update_processing_progress(percent, message)
