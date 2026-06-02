import webbrowser

from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLabel,
    QPushButton
)

from PyQt6.QtCore import Qt

from utils.app_config import get, is_env


class Footer(QWidget):

    def __init__(self, version=None, env=None):
        super().__init__()

        # resolve at runtime (safe + flexible)
        self.version = version or get("VERSION", "0.0.0")
        self.env = env or get("ENVT", "DEV")
        self.is_env = is_env()

        self.setFixedHeight(40)
        self.setObjectName("footer")

        self._build_ui()

    def _build_ui(self):

        layout = QHBoxLayout()

        layout.setContentsMargins(15, 5, 15, 5)

        # LEFT: TEAM
        team_label = QLabel("Intogreat Philippines Solutions Inc. - Automation Team")

        team_label.setStyleSheet("""

            color: #3A3A3A;
            font-size: 9px;
            font-weight: 600;

        """)

        # CENTER: VERSION
        version_label = QLabel(f"v{self.version}")

        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        version_label.setStyleSheet("""

            color: #6B6B6B;
            font-size: 11px;
            font-weight: 500;

        """)

        # RIGHT GROUP
        right_layout = QHBoxLayout()

        env_label = QLabel(f"{'ENV' if self.is_env else 'Windows'} | {self.env.upper()}")

        env_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        env_label.setStyleSheet(f"""

            color: {self._get_env_color(self.env)};
            font-size: 8px;
            font-weight: 700;

        """)

        # CREDIT ICON BUTTON
        credit_btn = QPushButton("ⓘ")

        credit_btn.setFixedSize(22, 22)

        credit_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        credit_btn.setToolTip("Open Intogreat's website")

        credit_btn.setStyleSheet("""

            QPushButton {

                border: none;
                background: rgba(255, 255, 255, 80);
                border-radius: 11px;

                font-size: 12px;
                font-weight: bold;
                color: #555;
            }

            QPushButton:hover {

                background: rgba(255, 255, 255, 140);
                color: #000;
            }

        """)

        credit_btn.clicked.connect(self.show_credits)

        # BUILD RIGHT SIDE
        right_layout.addWidget(env_label)

        

        right_widget = QWidget()
        right_widget.setLayout(right_layout)

        # LAYOUT
        layout.addWidget(credit_btn)
        layout.addWidget(team_label)
        layout.addStretch()
        layout.addWidget(right_widget)
        layout.addWidget(version_label)

        self.setLayout(layout)

        self.setStyleSheet("""

            #footer {
                background: transparent;
            }

        """)

    def show_credits(self):
        webbrowser.open("https://intogreatsolutions.com/")

    def _get_env_color(self, env):

        env = env.lower()

        if env == "prod":
            return "#D32F2F"

        elif env == "uat":
            return "#F9A825"

        elif env == "dev":
            return "#388E3C"

        else:
            return "#6B6B6B"