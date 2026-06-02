"""
logger.py — app-wide logger.

One Logger instance is created in Orchestrator and passed down to every service,
feature, and util. Nothing creates its own — this keeps all output in one file
and lets the caller prefix (e.g. "MSALService:", "PayrollFeature:") do the
work of identifying where a line came from.

Writes to both the console (colour-coded) and a per-session log file at:
    ~/Documents/Automations/<loc>/data/logs/logs_<session_id>.log

Quick reference:
    log.info("step done")
    log.warning("something off, continuing")
    log.error("failed hard", error=exc)       # appends traceback
    log.section("LOGIN")                      # prints a separator block
    log.event("btn clicked", btn="upload")    # structured key=value line
    log.result("SP upload", success=True, detail="HTTP 201")
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

    def __init__(self, app_data_path, session_id: str = None):
        timestamp  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_id = session_id or timestamp

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

    def _write_header(self, session_id: str):
        """Stamps the top of each log file so it's self-identifying."""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = (
            f"{'═' * 60}\n"
            f"  Payroll Automation — Session Log\n"
            f"  Session : {session_id}\n"
            f"  Started : {now}\n"
            f"  File    : {self.log_file}\n"
            f"{'═' * 60}\n"
        )
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(header)

        self.info(f"Logger ready | session={session_id}")
        self.info(f"Log file: {self.log_file}")
