"""
error_handler.py — global uncaught exception handler.

register_global_handler() hooks into sys.excepthook so any exception that
slips past a try/except doesn't just silently crash the app. When triggered:

    1. Logs the full traceback
    2. Reports to the Teams channel via Power Automate (if config is loaded)
    3. Shows an error screen in the UI (or a plain dialog if UI isn't ready)
    4. Uploads the session log to SharePoint

Call once in Orchestrator.__init__ before the event loop starts:

    register_global_handler(log=self.log, state=self.state,
                            body=self.body, file_manager=self._file_manager)

Note: sys.excepthook only catches exceptions on the main thread. Worker thread
exceptions (e.g. LoginWorker) need to be handled inside their run() method.
"""

import os
import sys
import traceback
from datetime import datetime
from PyQt6.QtWidgets import QMessageBox, QApplication

from services.power_automate_service import PowerAutomateService
from utils.app_config_user import get


def register_global_handler(log, state: dict = None, body=None, file_manager=None):
    """
    Installs the global exception hook.

    All params except log are optional — the handler degrades gracefully
    if config isn't loaded yet or the UI isn't built.
    """

    #log.section("ERROR HANDLER")

    def _handler(exc_type, exc_value, exc_tb):
        # Let Ctrl-C through so devs can kill the process normally
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

        _log_error(log, exc_type, exc_value, tb_str)
        _maybe_report(log, state, exc_type, exc_value, tb_str)

        if body:
            body.show_system_error(exc_type, exc_value, tb_str)
        else:
            _show_fallback_dialog(exc_type, exc_value, tb_str)

        if file_manager and state:
            log.info("ErrorHandler: Uploading log after crash")
            file_manager.upload_log(state)

    sys.excepthook = _handler
    log.info("ErrorHandler: Global exception hook registered")


def _log_error(log, exc_type, exc_value, tb_str: str):
    log.error(f"UNHANDLED EXCEPTION — {exc_type.__name__}: {exc_value}\n{tb_str}")


def _maybe_report(log, state, exc_type, exc_value, tb_str: str):
    """
    Posts an error card to Teams. Skips silently if config isn't ready yet —
    we don't want the report attempt to cause a second crash.
    """
    if not state:
        log.warning("ErrorHandler: No state yet — skipping Teams report")
        return

    config = state.get("config")
    if not config:
        log.warning("ErrorHandler: Config not loaded — skipping Teams report")
        return

    teams_cfg   = config.get("teams", {})
    webhook_url = teams_cfg.get("flow")
    group_id    = teams_cfg.get("id")

    if not webhook_url or not group_id:
        log.warning("ErrorHandler: Teams config incomplete — skipping report")
        return


    user    = f"{state.get('name', 'Unknown')} | {state.get('email', 'Unknown')}"
    app_env = f"⚠️ {get('app', 'Payroll')} — {get('ENVT', 'UNKNOWN')} ⚠️"

    payload = {
        "Automation":    app_env,
        "GroupID":       group_id,
        "Image":         "",
        "DateTime":      datetime.now().strftime("%Y-%m-%d %I:%M:%S %p — %A"),
        "User":          user,
        "Screen/Action": "Local App (unhandled exception)",
        "Error":         True,
        "Link":          "",
        "Text": (
            f"<b>Type:</b> {exc_type.__name__}<br>"
            f"<b>Message:</b> {exc_value}<br>"
            f"<b>Traceback:</b><br><pre>{tb_str}</pre>"
        ),
    }

    try:
        log.info("ErrorHandler: Sending error report to Teams")
        response = PowerAutomateService().start(webhook_url, payload)

        if str(response.status_code).startswith("2"):
            log.info("ErrorHandler: Report delivered")
        else:
            log.warning(f"ErrorHandler: Teams webhook returned HTTP {response.status_code}")

    except Exception as e:
        # Don't let the report itself cause another crash
        log.warning(f"ErrorHandler: Failed to send report — {e}")


def _show_fallback_dialog(exc_type, exc_value, tb_str: str):
    """Plain QMessageBox fallback for when the main window isn't ready yet."""
    app = QApplication.instance()
    if not app:
        return

    dialog = QMessageBox()
    dialog.setWindowTitle("Unexpected Error")
    dialog.setIcon(QMessageBox.Icon.Critical)
    dialog.setText(
        "<b>An unexpected error occurred.</b><br><br>"
        "The error has been logged and reported to the Automation Team.<br>"
        "Please restart the application."
    )
    dialog.setDetailedText(f"{exc_type.__name__}: {exc_value}\n\n{tb_str}")
    dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
    dialog.exec()
