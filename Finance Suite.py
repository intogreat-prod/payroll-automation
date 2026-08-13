"""
Payroll.py — app entry point.

Boots the Qt application, creates the Orchestrator, then hands off to the event loop.
"""

import sys
from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt
from orchestrator import Orchestrator

from utils.file_utils import resource_path


def main():
    app = QApplication(sys.argv)

    pixmap = QPixmap(resource_path("assets/background.png")).scaled(
        100, 100,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation
    )
    splash = QSplashScreen(pixmap, Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()

    orchestrator = Orchestrator()
    orchestrator.start()

    splash.finish(orchestrator.main_window)                                                                                                                                                                                             
    sys.exit(app.exec())


if __name__ == "__main__":
    main()