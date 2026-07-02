import webbrowser

from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLabel,
    QPushButton
)

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from utils.app_config_user import get, is_env
from utils.file_utils import resource_path


class Footer(QWidget):

    def __init__(self, version=None, env=None):
        super().__init__()

        self.on_clicked = None

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
        team_label = QLabel("Intogreat Solutions, Inc.")

        team_label.setStyleSheet("""

            color: white;
            font-size: 9px;
            font-weight: 600;

        """)

        # CENTER: VERSION
        version_label = QLabel(f"v{self.version}")

        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        version_label.setStyleSheet("""

            color: white;
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
        white_icon = QIcon(resource_path("assets/background_white.png"))
        black_icon = QIcon(resource_path("assets/background.png"))

        credit_btn = QPushButton("")
        credit_btn.setIcon(white_icon)
        credit_btn.setFixedSize(22, 22)
        credit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        credit_btn.setToolTip("Credits")
        credit_btn.clicked.connect(lambda: self.on_clicked('credits'))
        credit_btn.setStyleSheet("""
        QPushButton {
            background: transparent;
            border: none;
        }
        """)


        def enter_event(event):
            credit_btn.setIcon(black_icon)
            QPushButton.enterEvent(credit_btn, event)


        def leave_event(event):
            credit_btn.setIcon(white_icon)
            QPushButton.leaveEvent(credit_btn, event)


        credit_btn.enterEvent = enter_event
        credit_btn.leaveEvent = leave_event

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
        
