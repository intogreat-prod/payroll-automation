"""
Payroll.py — app entry point.

Boots the Qt application, creates the Orchestrator, then hands off to the event loop.
"""

import sys
from PyQt6.QtWidgets import QApplication
from orchestrator import Orchestrator


def main():
    app = QApplication(sys.argv)

    orchestrator = Orchestrator()
    orchestrator.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
