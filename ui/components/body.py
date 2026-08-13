"""
body.py
-------
The main content area of the app.

Responsibilities (UI only):
  - Renders different screens: no internet, login, source list, feature list, feature view
  - Exposes callback hooks for the Orchestrator to wire:
      body.on_clicked

What it does NOT do:
  - No business logic
  - No service calls (MSAL, SharePoint, etc.)
  - No state management beyond what's needed to render the current screen
"""

from PyQt6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout,
    QLabel, QFrame, QProgressBar, QHBoxLayout
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QPixmap

from ui.styles import STYLES
from ui.statuses import *
from ui.ui_factory import UIFactory
from ui.components.login_form import LoginForm
from utils.file_utils import resource_path

from ui.components.body_apps.payroll_app import PayrollBody
from ui.components.body_apps.billing_app import BillingBody

ACCENT = "#4FD1C5"  # teal, pulled from the intogreat logo mark

class Body(QWidget):

    def __init__(self, main_window):
        super().__init__()

        self._main_window = main_window

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(50)
        self.setStyleSheet(STYLES["body"])

        # ---------------------------------------------------------------
        # Callback hook — wired by Orchestrator after construction
        # ---------------------------------------------------------------
        self.on_clicked = None

        # ---------------------------------------------------------------
        # Screen container — screens are swapped in/out of this via
        # _clear(). It's nested one level below Body itself so the
        # breadcrumb bar (below) can stay put across every _clear()
        # call instead of getting wiped with the rest of the screen.
        # ---------------------------------------------------------------
        self._screen_container = QWidget()
        self._layout = QVBoxLayout(self._screen_container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)

        # Reserve extra window height for the breadcrumb bar so every
        # existing self._resize(w, h) call across the app doesn't need
        # to be touched individually — see _resize() below.
        self._breadcrumb_reserved_height = 22

        self._breadcrumb = UIFactory.label(
            "Home",
            style_key="breadcrumb_bar",
            align="center",
        )
        #self._breadcrumb.hide()
        self._breadcrumb.setFixedHeight(self._breadcrumb_reserved_height)

        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)
        self._root_layout.addWidget(self._screen_container, 1)
        self._root_layout.addWidget(self._breadcrumb, 0)

        # ---------------------------------------------------------------
        # Aux UI storage
        # Buttons and statuses are keyed by feature, then by a unique name.
        # Each button entry: { "widget": QPushButton, "visible_on": [status_code, ...] }
        # ---------------------------------------------------------------
        self.statuses = {
            "payroll":  {},
            "billing":  {}
        }

        self.buttons = {
            "payroll": {},
            "billing": {}
        }

        self.height = {
            "settings": 600,
        }

        # ---------------------------------------------------------------
        # App modules — composed onto Body, not inherited from it.
        # Each borrows Body's _clear()/_resize()/_emit_clicked()/_layout
        # via the `body` reference passed in, so screen-building code can
        # live in its own file without changing how Orchestrator talks
        # to the UI (it only ever calls self.body.show_x()).
        # ---------------------------------------------------------------
        self.payroll = PayrollBody(self)
        self.billing = BillingBody(self)

    # ===================================================================
    # HELPERS
    # ===================================================================

    def _clear(self):
        """Remove every widget/layout from the root layout."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().setParent(None)
            elif item.layout():
                self._clear_layout(item.layout())
                item.layout().deleteLater()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().setParent(None)
            elif item.layout():
                self._clear_layout(item.layout())
                item.layout().deleteLater()

    def _resize(self, w, h):
        """
        Ask the parent MainWindow to resize itself.

        Adds a fixed allowance for the breadcrumb bar so none of the
        per-screen resize calls scattered across body.py / body_apps
        need to be adjusted individually.
        """
        extra = self._breadcrumb_reserved_height if self._breadcrumb.isVisible() else 0
        self._main_window.resize_to(w, h + self._breadcrumb_reserved_height)

    def set_breadcrumb(self, parts):
        """
        Update the persistent nav trail at the bottom of the body.

        Args:
            parts: a string, or a list/tuple of path segments, e.g.
                   ["Home", "Billing", "Automation"]. Rendered as
                   "Home ▸ Billing ▸ Automation".
        """
        if not parts:
            parts = ["Home"]
        if isinstance(parts, str):
            text = parts
        else:
            text = " ▸ ".join(str(p) for p in parts if p)
        self._breadcrumb.setText(text)

    def _hide_statuses(self):
        try:
            for feature in self.statuses:
                for key, wid in self.statuses[feature].items():
                    wid.hide()
        except:
            pass

    def _hide_aux_buttons(self):
        """Hide every registered aux button across all features."""
        try:
            for feature in self.buttons:
                for key, entry in self.buttons[feature].items():
                    entry["widget"].hide()
        except:
            pass

    def _show_aux_buttons_for(self, feature, status_code):
        """Show only the aux buttons whose visible_on list contains this status_code."""
        self._hide_aux_buttons()
        for key, entry in self.buttons[feature].items():
            if status_code in entry["visible_on"]:
                entry["widget"].show()

    def _register_aux_button(self, feature, key, widget, visible_on):
        """
        Register an aux button so the visibility system can manage it.

        Args:
            feature (str):     e.g. "payroll"
            key (str):         unique name for this button
            widget (QPushButton): the button widget
            visible_on (list): list of status_codes that should reveal this button
        """
        widget.hide()
        self.buttons[feature][key] = {
            "widget":     widget,
            "visible_on": visible_on
        }

    def _set_btn_processing(self, btn, processing_text="Processing..."):
        """Switch a button to its processing state and disable it."""
        btn.setText(processing_text)
        btn.setEnabled(False)

    def _set_btn_default(self, btn, default_text="Upload"):
        """Restore a button to its default state."""
        btn.setText(default_text)
        btn.setEnabled(True)

    def _emit_clicked(self, btn):
        if self.on_clicked:
            self.on_clicked(btn)

    # ===================================================================
    # SCREEN 0 — SYSTEM ERROR
    # ===================================================================

    def show_system_error(self, exc_type, exc_value, tb_str):
        """
        Called by the global error handler for unhandled exceptions.
        Renders a system error screen directly in the app body.
        """
        self._clear()
        self._resize(530, 700)
        self._layout.setContentsMargins(16, 16, 16, 16)

        self._layout.addWidget(UIFactory.label(
            "Something went wrong",
            style_key="header_label", 
            align='center'
        ))

        # 🖼️ IMAGE
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setStyleSheet("""
            QLabel {
                border: none;
                background: transparent;
            }
        """)

        pixmap = QPixmap(resource_path("assets/system_error.png"))  # can also use .png/.jpg
        pixmap = pixmap.scaled(
            200,
            150,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        image_label.setPixmap(pixmap)
        image_label.setFixedWidth(300)
        self._layout.addWidget(image_label, alignment=Qt.AlignmentFlag.AlignCenter)


        self._layout.addWidget(UIFactory.label(
            f"{exc_type.__name__}: {exc_value}",
            color="red",
            align="center"
        ))
        self._layout.addWidget(UIFactory.label(
            "This error has been logged and reported.\nPlease restart the application.",
            style_key="standard",
            word_wrap=True,
            align="center"
        ))
        # Collapsible traceback
        from PyQt6.QtWidgets import QPlainTextEdit
        tb_box = QPlainTextEdit()
        tb_box.setReadOnly(True)
        tb_box.setPlainText(tb_str)
        tb_box.setFixedHeight(140)
        tb_box.setStyleSheet("font-family: Courier New; font-size: 9pt; color: #c0392b; background: #fff5f5;")
        tb_box.hide()
        toggle_btn = UIFactory.button(
            "Show Details",
            lambda: (tb_box.show() if tb_box.isHidden() else tb_box.hide()) or
                    toggle_btn.setText("Hide Details" if not tb_box.isHidden() else "Show Details"),
            "button"
        )
        self._layout.addWidget(toggle_btn)
        self._layout.addWidget(tb_box)
        self._layout.addStretch()

    def show_credits(self, year, app_version):
        self._clear()
        self._resize(530, 900)
        self._layout.setContentsMargins(32, 24, 32, 24)
        self._layout.setSpacing(0)

        # -------------------------
        # Header
        # -------------------------
        # NOTE: the "intogreat / Finance Suite" wordmark already lives in
        # your persistent header, so we don't repeat "Finance Suite" here.
        # Just version + a short description.
        version = UIFactory.label(
            f"Version {app_version}",
            font_size=11,
            color="#8F96A3",
            align="center"
        )
        description = UIFactory.label(
            "Finance Suite centralizes finance automation tools, streamlining repetitive tasks, "
            "validating data, and improving operational efficiency through intelligent workflows.",
            font_size=11,
            color="#BEBEBE",
            align="center",
            word_wrap=True
        )
        # -------------------------
        # Team card (grouped, bordered)
        # -------------------------
        team_card = QFrame()
        team_card.setObjectName("credits_card")
        team_layout = QVBoxLayout(team_card)
        team_layout.setContentsMargins(20, 20, 20, 20)
        team_layout.setSpacing(14)
        company = UIFactory.label(
            f"<b style='color:{ACCENT};'>Developed by</b><br>"
            "Intogreat Philippines Solutions Inc.<br>"
            "Automation Team",
            font_size=12, color="#F5F5F5", align="center", richtext=True
        )
        developer = UIFactory.label(
            "<b>Lead Developer</b><br>"
            "Roi Edzel Lagliva",
            font_size=12, color="#F5F5F5", align="center", richtext=True
        )
        contributors = UIFactory.label(
            "<b>Contributors</b><br>"
            "Finance Team &bull; HR Team &bull; Automation Team",
            font_size=12, color="#F5F5F5", align="center", richtext=True
        )
        team_layout.addWidget(company)
        team_layout.addWidget(UIFactory.divider())
        team_layout.addWidget(developer)
        team_layout.addWidget(UIFactory.divider())
        team_layout.addWidget(contributors)
        # -------------------------
        # Built with
        # -------------------------
        technologies = UIFactory.label(
            "<b>Built With</b><br>"
            "Python &bull; PyQt6 &bull; Pandas &bull; OpenPyXL<br>"
            "Microsoft Graph API &bull; SharePoint &bull; Unmand",
            font_size=12, color="#E6E6E6", align="center", richtext=True
        )
        # -------------------------
        # Footer: legal notice + copyright, visually demoted
        # -------------------------
        footer_card = QFrame()
        footer_card.setObjectName("credits_footer")
        footer_layout = QVBoxLayout(footer_card)
        footer_layout.setContentsMargins(16, 12, 16, 12)
        footer_layout.setSpacing(6)
        notice = UIFactory.label(
            "<b>Confidentiality Notice</b><br>"
            "This software is proprietary and confidential to Intogreat Philippines "
            "Solutions Inc. Unauthorized reproduction, distribution, modification, "
            "reverse engineering, disclosure, or use without prior written "
            "authorization is strictly prohibited.",
            font_size=10, color="#8F96A3", align="center", word_wrap=True, richtext=True
        )
        copyright = UIFactory.label(
            f"© {year} Intogreat Philippines Solutions Inc. All rights reserved.",
            font_size=10, color="#6B7280", align="center", richtext=True
        )
        footer_layout.addWidget(notice)
        footer_layout.addWidget(copyright)
        # -------------------------
        # Buttons: one primary (accent-filled), one secondary (ghost)
        # -------------------------
        website_btn = UIFactory.button(
            "Visit Website",
            lambda: self._emit_clicked("open_website"),
            "credits_web_button"
        )
        close_btn = UIFactory.button(
            "Close",
            lambda: self._emit_clicked("close_credits"),
            "payroll_button"
        )
        # -------------------------
        # Layout
        # -------------------------
        self._layout.addStretch(1)
        self._layout.addWidget(version)
        self._layout.addSpacing(12)
        self._layout.addWidget(description)
        self._layout.addSpacing(24)
        self._layout.addWidget(team_card)
        self._layout.addSpacing(20)
        self._layout.addWidget(technologies)
        self._layout.addSpacing(24)
        self._layout.addWidget(footer_card)
        self._layout.addSpacing(20)
        self._layout.addWidget(website_btn)
        self._layout.addSpacing(8)
        self._layout.addWidget(close_btn)
        self._layout.addStretch(2)

    # ===================================================================
    # SCREEN 1 — NO INTERNET
    # ===================================================================

    def show_no_internet(self):
        self._clear()
        self._resize(350, 440)
        self._layout.setContentsMargins(10, 10, 10, 10)

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        pixmap = QPixmap(resource_path("assets/no_internet.png"))
        if not pixmap.isNull():
            image_label.setPixmap(
                pixmap.scaled(
                    150, 150,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            )
            image_label.setFixedWidth(300)

        retry_btn = UIFactory.button("Retry", lambda: self._emit_clicked("retry"), "payroll_button")

        self._layout.addWidget(image_label, alignment=Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(retry_btn)
        self._layout.addStretch()

    # ===================================================================
    # SCREEN 2 — LOGIN
    # ===================================================================

    def show_login(self):
        self._clear()
        self._resize(400, 370)

        self._login_form = LoginForm(on_login_callback=lambda: self._emit_clicked("login"))

        self._layout.addStretch()
        self._layout.addWidget(self._login_form)
        self._layout.addStretch()

    def update_login_form(self, action: str, *args):
        LOGIN_FORM_STATUSES = {
            "device_code":     ((400, 390), "show_device_code"),
            "restricted_user": ((400, 390), "show_restricted_user"),
            "login_error":     ((400, 390), "show_error_login"),
            "config_error":    ((400, 390), "show_error_download"),
            "json_error":      ((400, 390), "show_error_json"),
        }

        if not hasattr(self, "_login_form"):
            return

        entry = LOGIN_FORM_STATUSES.get(action)
        if not entry:
            return

        resize, method_name = entry
        self._resize(*resize)

        method = getattr(self._login_form, method_name, None)
        if callable(method):
            method(*args)
    
    # ===================================================================
    # SCREEN 3 — UPDATE AVAILABLE
    # ===================================================================
    def show_update_prompt(self, current_version: str, latest_version: str, on_confirm):
        """
        Shows when a newer version is detected after login.
        on_confirm is a lambda from the Orchestrator that triggers the download.
        """
        self._clear()
        self._resize(400, 530)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(10)
        self._layout.addWidget(UIFactory.label(
            "Update Available",
            style_key="header_label",
            align="center"
        ))
        self._layout.addWidget(UIFactory.label(
            f"A new version of Finance Suite is available.",
            style_key="standard",
            align="center",
            word_wrap=True
        ))
        self._layout.addWidget(UIFactory.label(
            f"Current version:  {current_version}\nLatest version:     {latest_version}",
            style_key="standard",
            align="center",
            word_wrap=True
        ))
        self._layout.addWidget(UIFactory.label(
        "The installer will run in the background. \n If the app did not restart automatically, please open it manually.",
            style_key="standard_red",
            align="center",
            word_wrap=True
        ))
        self._layout.addStretch()
        # Update now — triggers download then closes the app
        self.update_btn = UIFactory.button(
            "Update Now",
            lambda: (
                self._set_btn_processing(self.update_btn, "Downloading..."),
                on_confirm()
            ),
            "credits_web_button"
        )
        self._layout.addWidget(self.update_btn)
        # Skip — proceeds to the normal sources screen
        self._layout.addWidget(UIFactory.button(
            "Skip for Now",
            lambda: self._emit_clicked("update_skipped"),
            "button"
        ))

    # ===================================================================
    # SCREEN 3.5 — UPDATE DOWNLOADING
    # ===================================================================
    def show_update_downloading(self, current_version: str, latest_version: str):
        """
        Shows download progress UI while installer is being downloaded.
        """

        self._clear()
        self._resize(400, 470)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(12)

        # Header
        self._layout.addWidget(UIFactory.label(
            "Updating Finance Suite",
            style_key="header_label",
            align="center"
        ))

        # Version info
        self._layout.addWidget(UIFactory.label(
            f"{current_version} → {latest_version}",
            style_key="standard",
            align="center"
        ))

        # Status text (dynamic update target)
        self.download_status_label = UIFactory.label(
            "Preparing download...",
            style_key="standard",
            align="center",
            word_wrap=True
        )
        self._layout.addWidget(self.download_status_label)

        # Progress label (percentage)
        self.download_percent_label = UIFactory.label(
            "0%",
            style_key="header_label",
            align="center"
        )
        self._layout.addWidget(self.download_percent_label)

        # Progress bar
        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        self.download_progress.setFixedHeight(3)
        self.download_progress.setStyleSheet(STYLES["progress_bar"])
        self.download_progress.setTextVisible(False)
        self._layout.addWidget(self.download_progress)

        # Hint text
        self._layout.addWidget(UIFactory.label(
            "Please do not close the application.",
            style_key="standard_red",
            align="center"
        ))

        self._layout.addStretch()

    def update_download_progress(self, percent: int, message: str):
        """Update the download progress bar and labels. Called from Orchestrator via signal."""
        self.download_progress.setValue(percent)
        self.download_percent_label.setText(f"{percent}%")
        self.download_status_label.setText(message)

    # ===================================================================
    # SCREEN 4 — UPDATE DOWNLOAD FAILED
    # ===================================================================
    def show_update_error(self):
        """
        Shows when the installer download fails.
        Lets the user continue into the app normally.
        """
        self._clear()
        self._resize(400, 400)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(10)
        self._layout.addWidget(UIFactory.label(
            "Update Failed",
            style_key="header_label",
            align="center"
        ))
        self._layout.addWidget(UIFactory.label(
            "The update could not be downloaded.\nPlease check your connection and try again later.",
            style_key="standard_red",
            align="center",
            word_wrap=True
        ))
        self._layout.addStretch()
        self._layout.addWidget(UIFactory.button(
            "Continue",
            lambda: self._emit_clicked("update_error_continue"),
            "payroll_button"
        ))

    # ===================================================================
    # SCREEN 5 — SUITE ROOT
    # ===================================================================
    def show_suite_menu(self):
        """
        Top-level landing screen for the whole suite.
        - Apps:    primary tile buttons, the growing list of apps (Payroll, Billing, ...)
        - Utility: secondary actions (Account, Updates, Credits, Help) rendered
                    as a small footer-style row of text links, not tiles.
        """
        self._clear()
        self.setStyleSheet(STYLES["body_clear"])
        self._resize(370, 570)
        suite_layout = QVBoxLayout()
        suite_layout.setSpacing(5)
        suite_layout.setContentsMargins(10, 10, 10, 10)
        # ── Apps container ──────────────────────────────────────────
        apps_con = QFrame()
        apps_con.setStyleSheet(STYLES["standard_container"])
        apps_layout = QVBoxLayout(apps_con)
        apps_layout.setSpacing(1)
        apps_layout.setContentsMargins(12, 12, 12, 12)
        apps_layout.addWidget(UIFactory.label("Home", style_key="header_label", align="center"))
        apps_col, apps_btn_layout = UIFactory.button_column(
            [
                ("Payroll", lambda: self._emit_clicked("payroll_app"), "payroll_button"),
                ("Billing", lambda: self._emit_clicked("billing_app"), "payroll_button"),
                ("Toolbox", lambda: self._emit_clicked("toolbox"), "payroll_button"),
                ("Settings", lambda: self._emit_clicked("app_settings"), "payroll_button"),
            ],
            spacing=8,
            parent=self,
        )

        self._error_json = UIFactory.label("", color="red", align="center", link=True)
        self._error_json.hide()

        apps_layout.addWidget(apps_col)
        apps_layout.addWidget(self._error_json)
        suite_layout.addWidget(apps_con)

        # ── Utility row — flat text links, footer-style ───────────────
        utility_row1 = QHBoxLayout()
        utility_row1.setSpacing(18)
        utility_row1.setContentsMargins(4, 0, 4, 4)
        utility_row1.addStretch()

        for label, action in [
            ("Account", "account_util"),
            ("Check for Updates", "check_update_util"),
        ]:
            btn = UIFactory.button(label, lambda _, a=action: self._emit_clicked(a), "")
            btn.setStyleSheet("link_style")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            utility_row1.addWidget(btn)
        utility_row1.addStretch()

        utility_row2 = QHBoxLayout()
        utility_row2.setSpacing(18)
        utility_row2.setContentsMargins(4, 0, 4, 4)
        utility_row2.addStretch()

        for label, action in [
            ("About / Credits", "credits_util"),
            ("Help / Support", "help_util"),
        ]:
            btn = UIFactory.button(label, lambda _, a=action: self._emit_clicked(a), "")
            btn.setStyleSheet("link_style")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            utility_row2.addWidget(btn)
        utility_row2.addStretch()


        suite_layout.addLayout(utility_row1)
        suite_layout.addLayout(utility_row2)

        self._layout.addLayout(suite_layout)

    def show_error_config(self, error, config):
        self._resize(370, 530)
        if error == "config_error":
            self._error_json.setText(f"Failed to download the {config.title()} configuration file. ")
        elif error == "json_error":
            self._error_json.setText(f"Invalid JSON format. Please check the {config.title()} config file structure. ")
        self._error_json.show()

    # ===================================================================
    # ACTIONS ON CLICK
    # ===================================================================
    def _on_add_user_clicked(self, email):
        self._hide_aux_buttons()
        self._hide_statuses()
        self._emit_clicked(['add_user', email])

    # ===================================================================
    # SCREEN 5.5 — SUITE UTIL SCREEN
    # ===================================================================
    def show_account(self, name: str = None, email: str = None):
        """Suite-level account screen — logged-in identity + logout."""
        self._clear()
        self.setStyleSheet(STYLES["body_clear"])
        self._resize(370, 320)

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        con = QFrame()
        con.setStyleSheet(STYLES["standard_container"])
        con_layout = QVBoxLayout(con)
        con_layout.setSpacing(6)
        con_layout.setContentsMargins(12, 12, 12, 12)

        con_layout.addWidget(UIFactory.label("Account", style_key="header_label"))
        con_layout.addWidget(UIFactory.label(
            f"{name}\n{email}" if email else "Not signed in",
            style_key="standard"
        ))

        col, btn_layout = UIFactory.button_column(
            [
                ("Log out", lambda: self._emit_clicked("logout"), "settings_button"),
                ("Home",    lambda: self._emit_clicked("suite_home"), "payroll_button"),
            ],
            spacing=8,
            parent=self,
        )
        btn_layout.addStretch()

        con_layout.addSpacing(6)
        con_layout.addWidget(col)
        layout.addWidget(con)
        layout.addStretch()
        self._layout.addLayout(layout)

    def show_help(self):
        """Suite-level help/support placeholder."""
        self._clear()
        self.setStyleSheet(STYLES["body_clear"])
        self._resize(370, 320)

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        con = QFrame()
        con.setStyleSheet(STYLES["standard_container"])
        con_layout = QVBoxLayout(con)
        con_layout.setSpacing(6)
        con_layout.setContentsMargins(12, 12, 12, 12)

        con_layout.addWidget(UIFactory.label("Help / Support", style_key="header_label"))
        con_layout.addWidget(UIFactory.label(
            "Ran into an issue? Reach out to the Automation Team or send us a report.",
            style_key="standard",
            word_wrap=True
        ))

        col, btn_layout = UIFactory.button_column(
            [
                ("Contact Automation Team", lambda: self._emit_clicked("contact_support"), "settings_button"),
                ("Home",                    lambda: self._emit_clicked("suite_home"),      "payroll_button"),
            ],
            spacing=8,
            parent=self,
        )
        btn_layout.addStretch()

        con_layout.addSpacing(6)
        con_layout.addWidget(col)
        layout.addWidget(con)
        layout.addStretch()
        self._layout.addLayout(layout)

    # ===================================================================
    # SCREEN 5 — SUITE ROOT
    # ===================================================================
    def show_settings(self, users):
        self._clear()
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._resize(530, self.height["settings"])

        self._layout.addWidget(UIFactory.button( "Home",
            lambda: self._emit_clicked("suite_home"), "payroll_button"
            )
        )

        content = QFrame()
        content.setObjectName("featureContent")
        content.setStyleSheet(STYLES["feature_content"])

        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(4)
        content_layout.setContentsMargins(10, 10, 10, 10)

        content_layout.addWidget(UIFactory.label("⚙️ Settings", color='white', font_weight="bold", font_size=17))
        content_layout.addSpacing(3)

        # ── Users frame ──────────────────────────────────────────────────────────
        users_con = QFrame()
        users_con.setStyleSheet(STYLES["standard_container"])

        users_layout = QVBoxLayout(users_con)
        users_layout.setSpacing(2)
        users_layout.setContentsMargins(12, 12, 12, 12)

        users_layout.addWidget(UIFactory.label("Users", style_key="header_label"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(120)
        scroll.setStyleSheet(STYLES['settings_scroll'])

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(10, 10, 10, 10)
        scroll_layout.setSpacing(2)

        if users:
            for u in users:
                scroll_layout.addWidget(UIFactory.label(u, style_key="standard"))
        else:
            scroll_layout.addWidget(UIFactory.label("No users found.", style_key="standard_red"))

        scroll.setWidget(scroll_content)
        users_layout.addWidget(scroll)
        users_layout.addSpacing(4)

        self.add_user_input = UIFactory.input("Add a user (e.g., jdelacruz@intogreatsolutions.com)")
        users_layout.addWidget(self.add_user_input)
        users_layout.addSpacing(4)

        self.add_user_btn = UIFactory.button(
            "Add User",
            lambda: self._on_add_user_clicked(self.add_user_input.text().strip()),
            "settings_button",
            height=35
        )

        users_layout.addWidget(self.add_user_btn)
        content_layout.addWidget(users_con)
        content_layout.addStretch()

        # Status labels
        self.app_settings_status = UIFactory.label("", align="center", font_size=8)
        self.app_settings_status.hide()
        content_layout.addWidget(self.app_settings_status)

        self._layout.addWidget(content)

    def show_settings_add_user_status(self, code):
        self._resize(530, self.height["settings"] + 10)
        self.app_settings_status.setText(APP_SETTINGS_STATUSES[code])
        self.app_settings_status.setStyleSheet(
                f"color: {'#16A34A' if 'success' in code else '#DC2626'};"
                "font-size: 10px;"
            )
        self.app_settings_status.show()
