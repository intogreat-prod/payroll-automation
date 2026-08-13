"""
logger.py — app-wide logger.

One Logger instance is created in the suite Orchestrator and passed down to
every service, feature, and util. Nothing creates its own — this keeps all
output in one file.

As of the Finance Suite restructure, every action can also be tagged with
the suite app it belongs to (Payroll, Billing, ...) via for_module(), so a
shared log file stays readable as more apps are added — nothing else about
how callers use the logger changes.

Writes to both the console (colour-coded) and a per-session log file at:
    ~/Documents/Automations/<loc>/data/logs/logs_<session_id>.log

Quick reference:
    log.info("step done")
    log.warning("something off, continuing")
    log.error("failed hard", error=exc)       # appends traceback
    log.section("LOGIN")                      # prints a separator block
    log.event("btn clicked", btn="upload")    # structured key=value line
    log.result("SP upload", success=True, detail="HTTP 201")

Per-module tagging (new):
    payroll_log = log.for_module("Payroll")
    payroll_log.info("Payroll upload started")   # -> [Payroll] Payroll upload started

    billing_log = log.for_module("Billing")
    billing_log.info("Invoice generated")        # -> [Billing] Invoice generated

Both write to the same underlying session log file, so a single log still
tells the whole story of a session, just with a clear tag for which app
each line came from.
"""

import datetime
import traceback
from pathlib import Path

from colorama import Fore, init as colorama_init

colorama_init(autoreset=True)


class Logger:

    _COLOURS = {
        "INFO":    Fore.GREEN,
        "WARNING": Fore.YELLOW,
        "ERROR":   Fore.RED,
        "DEBUG":   Fore.CYAN,
        "EVENT":   Fore.MAGENTA,
        "SECTION": Fore.BLUE,
    }

    def __init__(self, app_data_path, session_id: str = None, app_name: str = "Finance Suite"):
        timestamp  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_id = session_id or timestamp

        self.app_name = app_name
        self.log_file = Path(app_data_path) / "data" / "logs" / f"logs_{session_id}.log"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        self._write_header(session_id)

    # -------------------------------------------------------------------------

    def log(self, message: str, level: str = "INFO", error: Exception = None):
        """Core write — everything else calls this."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        level_up  = level.upper()
        colour    = self._COLOURS.get(level_up, Fore.WHITE)
        entry     = f"[{timestamp}] [{level_up}] {message}"

        print(colour + entry)

        trace = ""
        if error is not None:
            trace = traceback.format_exc()
            # format_exc returns this string when called outside an except block
            if trace.strip() in ("NoneType: None", "None"):
                trace = f"  {type(error).__name__}: {error}"
            print(Fore.RED + trace)

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
            if trace:
                f.write(trace + "\n")

    # -------------------------------------------------------------------------
    # Levels

    def info(self, msg: str):
        """Normal progress — step started, completed, etc."""
        self.log(msg, "INFO")

    def warning(self, msg: str, error: Exception = None):
        """Something's off but we can continue. Pass error= to include the traceback."""
        self.log(msg, "WARNING", error=error)

    def error(self, msg: str, error: Exception = None):
        """Operation failed. Pass error= to include the traceback."""
        self.log(msg, "ERROR", error=error)

    def debug(self, msg: str):
        """Low-level detail, useful during development."""
        self.log(msg, "DEBUG")

    # -------------------------------------------------------------------------
    # Structured helpers

    def section(self, title: str):
        """
        Prints a separator line to mark the start of a new flow.
        Makes it easy to scan a long log file.

            [SECTION] ════════════ LOGIN ════════════
        """
        bar = "═" * max(4, (44 - len(title)) // 2)
        self.log(f"{bar} {title.upper()} {bar}", "SECTION")

    def event(self, action: str, **kwargs):
        """
        Logs a UI or business event with key=value context.

            [EVENT] Button clicked | btn=upload | feature=payroll
        """
        context = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        self.log(action + (f" | {context}" if context else ""), "EVENT")

    def result(self, step: str, success: bool, detail: str = ""):
        """
        Logs a clear PASS / FAIL line for a named step.

            [PASS] SharePoint upload — HTTP 201
            [FAIL] Sort and archive — failed=2
        """
        outcome = "PASS" if success else "FAIL"
        msg     = f"[{outcome}] {step}" + (f" — {detail}" if detail else "")
        self.log(msg, "INFO" if success else "WARNING")

    # -------------------------------------------------------------------------
    # Per-app tagging

    def for_module(self, module_name: str) -> "_ModuleLoggerAdapter":
        """
        Returns a tagged logger for one suite app (e.g. "Payroll", "Billing").

        Every info/warning/error/debug/event/result line written through the
        adapter is prefixed with "[module_name]" so a shared log file stays
        traceable to the right app as the suite grows. section() stays
        untagged since it's a visual separator shared across the whole
        session, not a per-action log line.
        """
        return _ModuleLoggerAdapter(self, module_name)

    # -------------------------------------------------------------------------

    def _write_header(self, session_id: str):
        """Stamps the top of each log file so it's self-identifying."""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = (
            f"{'═' * 60}\n"
            f"  {self.app_name} — Session Log\n"
            f"  Session : {session_id}\n"
            f"  Started : {now}\n"
            f"  File    : {self.log_file}\n"
            f"{'═' * 60}\n"
        )
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(header)

        self.info(f"Logger ready | session={session_id}")
        self.info(f"Log file: {self.log_file}")


class _ModuleLoggerAdapter:
    """
    Thin per-app wrapper around a Logger, returned by Logger.for_module().

    Mirrors Logger's public logging API exactly (info/warning/error/debug/
    event/result/section) so existing call sites keep working unchanged —
    the only difference is every tagged line is prefixed with the module
    name. Writes go through the same underlying Logger, so there's still
    one log file per session.
    """

    def __init__(self, logger: Logger, module_name: str):
        self._logger = logger
        self.module_name = module_name

    def _tag(self, msg: str) -> str:
        return f"[{self.module_name}] {msg}"

    def info(self, msg: str):
        self._logger.info(self._tag(msg))

    def warning(self, msg: str, error: Exception = None):
        self._logger.warning(self._tag(msg), error=error)

    def error(self, msg: str, error: Exception = None):
        self._logger.error(self._tag(msg), error=error)

    def debug(self, msg: str):
        self._logger.debug(self._tag(msg))

    def section(self, title: str):
        # Untagged — this is a shared visual separator, not a per-app line.
        self._logger.section(title)

    def event(self, action: str, **kwargs):
        self._logger.event(self._tag(action), **kwargs)

    def result(self, step: str, success: bool, detail: str = ""):
        self._logger.result(self._tag(step), success, detail)
