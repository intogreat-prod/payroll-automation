"""
login_form.py
-------------
Pure UI widget for the login screen.

Exposes:
  show_device_code(code, url)   — display the device code to the user
  show_error_login(error)       — authentication error
  show_error_download()         — config file download failed
  show_error_json()             — config file has invalid JSON
"""

import webbrowser

from PyQt6.QtWidgets import QWidget, QVBoxLayout

from ui.ui_factory import UIFactory

from utils.app_config import get


class LoginForm(QWidget):

    def __init__(self, on_login_callback):
        super().__init__()

        self._support_email = get("support_email", "")
        self._on_login_callback = on_login_callback

        self._build_ui()

    # ===================================================================
    # BUILD
    # ===================================================================

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # --- Title ---
        title =  UIFactory.label("Welcome to Intogreat's Payroll Automation!", align="center", font_size=16, font_weight="bold")

        subtitle = UIFactory.label("Sign in your account", font_size=9, color='grey')

        # --- Device code (hidden until needed) ---
        self._device_code_label = UIFactory.label("", font_size=12, font_weight="bold", selectable=True)
        self._device_code_label.hide()

        # --- Login button ---
        login_btn = UIFactory.button("Log in", self._on_login_callback, "payroll_button")


        # --- Error labels (hidden until needed) ---
        self._error_login = UIFactory.label("", color="red", align="center", selectable=True)
        self._error_login.hide()

        self._error_download = UIFactory.label("", color="red", align="center", link=True)
        self._error_download.hide()

        self._error_json = UIFactory.label("", color="red", align="center", link=True)
        self._error_json.hide()

        self._restricted_user = UIFactory.label("", color="red", align="center", selectable=True)
        self._restricted_user.hide()

        # --- Assemble ---
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self._device_code_label)
        layout.addStretch(10)
        layout.addWidget(login_btn)
        layout.addWidget(self._error_login)
        layout.addWidget(self._error_download)
        layout.addWidget(self._error_json)
        layout.addWidget(self._restricted_user)

        layout.addStretch()

        self.setLayout(layout)

    # ===================================================================
    # PUBLIC — called by Body (which gets them from Orchestrator)
    # ===================================================================

    def show_device_code(self, payload):
        self._device_code_label.setText(f"Enter Code: {payload.get('user_code')}")
        self._device_code_label.show()
        webbrowser.open(payload.get('url'))

    def show_error_login(self, error):
        self._error_login.setText(str(error))
        self._error_login.show()

    def show_error_download(self):
        self._error_download.setText(
            "Failed to download the configuration file. "
            f'<a href="mailto:{self._support_email}?subject=Config Download Error">'
            "Contact Support</a>"
        )
        self._error_download.show()

    def show_error_json(self):
        self._error_json.setText(
            "Invalid JSON format. Please check the file structure. "
            f'<a href="mailto:{self._support_email}?subject=JSON Format Error">'
            "Contact Support</a>"
        )
        self._error_json.show()

    def show_restricted_user(self):
        self._restricted_user.setText('This user account is not authorized to access the system.')
        self._restricted_user.show()

