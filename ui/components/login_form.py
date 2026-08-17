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
from urllib.parse import quote


from PyQt6.QtWidgets import QWidget, QVBoxLayout

from ui.ui_factory import UIFactory

from utils.app_config_user import get


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
        title =  UIFactory.label("Welcome to Intogreat's Finance Suite!", align="left", font_size=16, font_weight="bold", color='white')

        subtitle = UIFactory.label("     Sign in your account", font_size=9, color='white')

        # --- Device code (hidden until needed) ---
        self._device_code_label = UIFactory.label("", font_size=12, font_weight="bold", selectable=True, color="white")
        self._device_code_label.hide()

        # --- Login button ---
        self._login_btn = UIFactory.button("Log in", self._on_login_btn_click, "payroll_button")# --- Access request ---

        subject = "Finance Suite Access Request"

        body = """Hi Finance Team,

        I would like to request access to Intogreat's Finance Suite.

        Name:
        Email:

        Thank you.
        """
        mailto = (
            "mailto:i2gfinance@intogreatsolutions.com"
            f"?subject={quote(subject)}"
            f"&body={quote(body)}"
        )

        self._request_access = UIFactory.label(
            f'<style>'
            f'a {{ color:#6AAFA7; text-decoration:underline; }}'
            f'a:hover {{ color:#8AC8C0; }}'
            f'</style>'
            f'<a href="{mailto}">No access yet? Request access</a>',
            align="center",
            link=True,
            richtext=True
        )

        # --- Error labels (hidden until needed) ---
        self._error= UIFactory.label("", color="red", align="center", selectable=True)
        self._error.hide()


        # --- Assemble ---
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self._device_code_label)
        layout.addStretch(10)
        layout.addWidget(self._login_btn)
        layout.addWidget(self._request_access)
        layout.addWidget(self._error)

        layout.addStretch()

        self.setLayout(layout)

    # ===================================================================
    # PUBLIC — called by Body (which gets them from Orchestrator)
    # ===================================================================

    def show_device_code(self, payload):
        self._reset_login_btn()
        self._device_code_label.setText(f"   Enter Code: {payload.get('user_code')}")
        self._device_code_label.show()
        webbrowser.open(payload.get('url'))

    def show_error_login(self, error):
        self._reset_login_btn()
        self._error.setText(str(error))
        self._error.show()

    def show_error_download(self):
        self._reset_login_btn()
        self._error_download.setText(
            "Failed to download the configuration file. "
            f'<a href="mailto:{self._support_email}?subject=Config Download Error">'
            "Contact Support</a>"
        )
        self._error_download.show()

    def show_error_json(self):
        self._reset_login_btn()
        self._error.setText(
            "Invalid JSON format. Please check the file structure. "
            f'<a href="mailto:{self._support_email}?subject=JSON Format Error">'
            "Contact Support</a>"
        )
        self._error.show()

    def show_restricted_user(self):
        self._reset_login_btn()
        self._error.setText('This user account is not authorized to access the system.')
        self._error.show()

    def _on_login_btn_click(self):
        self._login_btn.setText("Logging in...")
        self._login_btn.setEnabled(False)
        self._on_login_callback()

    def _reset_login_btn(self):
        self._login_btn.setText("Log in")
        self._login_btn.setEnabled(True)
