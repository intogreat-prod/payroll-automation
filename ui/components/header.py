# ui/components/header.py

import datetime
import sys

from PyQt6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QApplication
)

from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QProcess

from utils.file_utils import resource_path


class Header(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.on_clicked = None

        self.setFixedHeight(150)

        self.setObjectName("header")

        self._build_ui()

    # =====================================
    # UI
    # =====================================

    def _build_ui(self):

        main_layout = QVBoxLayout()

        main_layout.setContentsMargins(20, 5, 5, 10)
        main_layout.setSpacing(10)

        # TOP BAR
        top_bar = self._build_top_bar()

        # LOGO + DATE
        content = self._build_content()

        main_layout.addLayout(top_bar)
        main_layout.addLayout(content)

        self.setLayout(main_layout)

        self.setStyleSheet("""

            #header {
                background: transparent;
            }

            QLabel {
                color: #1C1C1C;
            }

        """)

    # =====================================
    # TOP BAR
    # =====================================

    def _build_top_bar(self):

        layout = QHBoxLayout()

        layout.addStretch()

        layout.addWidget(
            self._create_top_button(
                "🗘",
                lambda: self.on_clicked('restart'),
                "#4CAF50",
                "Refresh"
            )
        )

        layout.addWidget(
            self._create_top_button(
                "━",
                lambda: self.on_clicked('minimized'),
                "#FF9800",
                "Minimize"
            )
        )

        layout.addWidget(
            self._create_top_button(
                "✕",
                lambda: self.on_clicked('close'),
                "#F44336",
                "Close"
            )
        )

        return layout

    def _create_top_button(self, text, callback, hover_color, hover_text):

        button = QPushButton(text)

        button.setFixedSize(28, 24)

        button.setToolTip(hover_text)

        button.clicked.connect(callback)

        button.setStyleSheet(f"""

            QPushButton {{

                border: none;
                background: transparent;

                color: #7A7A7A;

                font-size: 12px;
                font-weight: 600;

                border-radius: 10px;
            }}

            QPushButton:hover {{

                background: rgba(255, 255, 255, 80);

                color: {hover_color};
            }}

        """)

        return button

    # =====================================
    # CONTENT
    # =====================================

    def _build_content(self):

        layout = QVBoxLayout()

        # LOGO
        logo = QLabel()
        pixmap = QPixmap(resource_path("assets/logo.png"))

        if not pixmap.isNull():

            logo.setPixmap(
                pixmap.scaled(
                    250,
                    250,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            )

        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # DATE
        today = datetime.datetime.now().strftime("%A, %B %d %Y")
        date_label = QLabel(today)
        date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        date_label.setStyleSheet("""

            font-size: 13px;
            color: #5A5A5A;
            font-weight: 500;

        """)

        # ADD HORIZONTALLY
        layout.addWidget(logo)
        layout.addSpacing(15)
        layout.addWidget(date_label)
        layout.addStretch()

        return layout

