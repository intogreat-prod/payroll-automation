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
    QLabel, QFrame, QProgressBar, QHBoxLayout, QTabWidget, QCheckBox
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QDate
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
            "settings": 970,
            "excel_locker_single": 670,
            "excel_locker_multiple": 750,
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

    def _animate_progress(self, bar, percent, anim_attr):
        anim = QPropertyAnimation(bar, b"value")
        anim.setDuration(350)
        anim.setStartValue(bar.value())
        anim.setEndValue(percent)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        setattr(self, anim_attr, anim)

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
    def show_update_prompt(self, current_version: str, latest_version: str, notes: str, on_confirm):
        """
        Shows when a newer version is detected after login.
        on_confirm is a lambda from the Orchestrator that triggers the download.
        """
        self._clear()
        self._resize(400, 600)
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
            f"What's New:",
            style_key="standard",
            align="center",
            word_wrap=True,
            font_weight="bold"
        ))

         # ── Status ────────────────────────────────────────────────────────────────
        note_count = notes.count("\r\n")

        git_release_notes = UIFactory.label(
            notes,
            align="center",
            word_wrap=True,
            style_key="standard"

        )

        if note_count > 3:
            git_release_notes_scroll = QScrollArea()
            git_release_notes_scroll.setWidgetResizable(True)
            git_release_notes_scroll.setStyleSheet(STYLES['settings_scroll'])
            git_release_notes_scroll.setWidget(git_release_notes)
            self._layout.addWidget(git_release_notes_scroll)
        else:
            self._layout.addWidget(git_release_notes)

        self._layout.addStretch()
        self._layout.addWidget(UIFactory.label(
        "The installer will run in the background and auto relaunch. \n If the app did not restart automatically, please open it manually.",
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
        self._main_window.start_progress_heartbeat()

        # Hint text
        self._layout.addWidget(UIFactory.label(
            "Please do not close the application and \n"
            "wait the suite to restart by itself. \n",
            style_key="standard_red",
            align="center"
        ))

        self._layout.addStretch()

    def update_download_progress(self, percent: int, message: str):
        """Update the download progress bar and labels. Called from Orchestrator via signal."""
        self._animate_progress(self.download_progress, percent, "_download_progress_anim")
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
                ("Toolbox", lambda: self._emit_clicked("app_toolbox"), "payroll_button"),
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
    # SCREEN 5.5 — SUITE UTIL SCREEN
    # ===================================================================
    def show_account(self, name: str = None, email: str = None, user_details: tuple = (None, None)):
        """Suite-level account screen — logged-in identity + logout."""
        self._clear()
        self.setStyleSheet(STYLES["body_clear"])
        self._resize(370, 650)

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        con = QFrame()
        con.setStyleSheet(STYLES["standard_container"])

        con_layout = QVBoxLayout(con)
        con_layout.setSpacing(6)
        con_layout.setContentsMargins(16, 16, 16, 16)

        role, photo = user_details

        # Header
        con_layout.addWidget(
            UIFactory.label(
                "Account",
                style_key="header_label",
                align="center"
            )
        )

        # ── Profile photo ───────────────────────────────────────────────
        photo_label = QLabel()
        photo_label.setFixedSize(80, 80)
        photo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if photo:
            pixmap = QPixmap(photo)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    80,
                    80,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation
                )
                photo_label.setPixmap(pixmap)
        else:
            photo_label.setText("👤")
            photo_label.setStyleSheet(
                "font-size: 36px;"
                "background-color: #E5E7EB;"
                "border-radius: 40px;"
            )

        photo_row = QHBoxLayout()
        photo_row.addStretch()
        photo_row.addWidget(photo_label)
        photo_row.addStretch()

        con_layout.addLayout(photo_row)
        con_layout.addSpacing(6)

        # ── Name ────────────────────────────────────────────────────────
        con_layout.addWidget(
            UIFactory.label(
                name or "Unknown User",
                align="center",
                font_weight="bold",
                font_size=14,
                color="white"
            )
        )

        # ── Role ────────────────────────────────────────────────────────
        con_layout.addWidget(
            UIFactory.label(
                role or "User",
                align="center",
                font_size=10,
                color="#A0AEC0"
            )
        )

        # ── Email ───────────────────────────────────────────────────────
        con_layout.addWidget(
            UIFactory.label(
                email or "No email available",
                align="center",
                font_size=9,
                color="#A0AEC0"
            )
        )

        # ── Buttons ─────────────────────────────────────────────────────
        col, btn_layout = UIFactory.button_column(
            [
                (
                    "Log out",
                    lambda: self._emit_clicked("logout"),
                    "gradient_button"
                ),
                (
                    "Home",
                    lambda: self._emit_clicked("suite_home"),
                    "payroll_button"
                ),
            ],
            spacing=8,
            parent=self,
        )

        con_layout.addSpacing(12)
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
    def show_settings(self, users, current_version="", releases=None):
        self._clear()
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._resize(530, self.height["settings"])

        content = QFrame()
        content.setObjectName("featureContent")
        content.setStyleSheet(STYLES["feature_content"])

        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(2)
        content_layout.setContentsMargins(10, 10, 10, 10)

        content_layout.addWidget(
            UIFactory.label(
                "⚙️ Settings",
                color="white",
                font_weight="bold",
                font_size=17
            )
        )
        content_layout.addSpacing(3)

        # ── Users frame ──────────────────────────────────────────────────────
        users_con = QFrame()
        users_con.setStyleSheet(STYLES["standard_container"])

        users_layout = QVBoxLayout(users_con)
        users_layout.setSpacing(1)
        users_layout.setContentsMargins(12, 12, 12, 12)

        users_layout.addWidget(
            UIFactory.label("👨🏻‍💻 Users", style_key="header_label")
        )

        users_layout.addWidget(
            UIFactory.label(
                "Access applies to the entire Finance Suite. Enter the user's email below to grant access.\n"
                "A welcome email with the installation guide will be sent automatically.",
                font_size=11, color='white'
            )
        )
        users_layout.addSpacing(2)


        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(100)
        scroll.setStyleSheet(STYLES["settings_scroll"])

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(10, 10, 10, 10)
        scroll_layout.setSpacing(2)

        if users:
            for u in users:
                scroll_layout.addWidget(
                    UIFactory.label(u, style_key="standard")
                )
        else:
            scroll_layout.addWidget(
                UIFactory.label("No users found.", style_key="standard_red")
            )

        scroll.setWidget(scroll_content)
        users_layout.addWidget(scroll)
        users_layout.addSpacing(2)

        self.add_user_input = UIFactory.input(
            "Add a user (e.g., jdelacruz@intogreatsolutions.com)"
        )
        users_layout.addWidget(self.add_user_input)
        users_layout.addSpacing(2)

        self.add_user_btn = UIFactory.button(
            "Add User",
            lambda: self._on_add_user_clicked(
                self.add_user_input.text().strip()
            ),
            "settings_button",
            height=35
        )

        users_layout.addWidget(self.add_user_btn)

        content_layout.addWidget(users_con)
        content_layout.addSpacing(4)

        # ── Date row: [Start] → [Cutoff] ────────────────────────────────────
        # ── Logs frame ─────────────────────────────────────────────────────────
        logs_con = QFrame()
        logs_con.setStyleSheet(STYLES["standard_container"])

        logs_layout = QVBoxLayout(logs_con)
        logs_layout.setSpacing(2)
        logs_layout.setContentsMargins(12, 12, 12, 12)

        logs_layout.addWidget(
            UIFactory.label("🧾 Logs", style_key="header_label")
        )

        logs_layout.addWidget(
            UIFactory.label(
                "Share logs with Support to help troubleshoot issues.\n"
                "Select a date range below, or check “Current Log” to share only the current log.",
                font_size=11, color='white'
            )
        )
        users_layout.addSpacing(2)


        # ── Date row: [Start] → [Cutoff] ───────────────────────────────────────
        date_picker_row = QHBoxLayout()

        # Left stretch
        date_picker_row.addStretch()

        # Start date
        start_layout = QVBoxLayout()
        start_layout.setSpacing(4)

        start_layout.addWidget(
            UIFactory.label(
                "Start Date:",
                font_weight="bold",
                color="white"
            )
        )

        self.start_date = UIFactory.date_picker(
            default_date=QDate.currentDate(),
            width=90,
            style_key="date_picker"
        )

        start_layout.addWidget(self.start_date)
        date_picker_row.addLayout(start_layout)

        # Arrow
        arrow_label = UIFactory.label(
            "➜",
            color="white",
            font_size=18
        )
        arrow_label.setAlignment(Qt.AlignmentFlag.AlignBottom)
        arrow_label.setContentsMargins(10, 0, 10, 4)

        date_picker_row.addWidget(arrow_label)

        # Cutoff date
        cutoff_layout = QVBoxLayout()
        cutoff_layout.setSpacing(4)

        cutoff_layout.addWidget(
            UIFactory.label(
                "End Date:",
                font_weight="bold",
                color="white"
            )
        )

        self.end_date = UIFactory.date_picker(
            default_date=QDate.currentDate(),
            width=90,
            style_key="date_picker"
        )

        cutoff_layout.addWidget(self.end_date)
        date_picker_row.addLayout(cutoff_layout)
        date_picker_row.addStretch()


        # Current Log checkbox
        self.share_logs_current_cbox = QCheckBox("Current Log")

        date_picker_row.addWidget(self.share_logs_current_cbox)

        # Right stretch
        date_picker_row.addStretch()

        logs_layout.addLayout(date_picker_row)
        logs_layout.addSpacing(10)

        self.share_logs_btn = UIFactory.button(
            "Share Logs with Support",
            lambda: self._on_share_logs_clicked(),
            "settings_button",
            height=35
        )

        logs_layout.addWidget(self.share_logs_btn)

        # Add Logs container to main content
        content_layout.addWidget(logs_con)
        content_layout.addSpacing(4)

        # ── App Version frame ────────────────────────────────────────────
        version_con = QFrame()
        version_con.setStyleSheet(STYLES["standard_container"])

        version_layout = QVBoxLayout(version_con)
        version_layout.setSpacing(2)
        version_layout.setContentsMargins(12, 12, 12, 12)

        version_layout.addWidget(
            UIFactory.label("🌀 App Version", style_key="header_label")
        )

        version_layout.addWidget(
            UIFactory.label(
                f"Current version: {current_version}\n"
                "Roll back to a previous release if the current version has issues.",
                font_size=11, color='white'
            )
        )

        version_layout.addSpacing(2)
        version_items = [
           (f"v{tag}", (tag, asset_id))
           for tag, asset_id, _body in (releases or [])
           if tag != current_version
       ]
        self.version_dropdown = UIFactory.combo_box(
            items=version_items,
            height=30,
            placeholder="No previous versions available" if not version_items else "Select a version",
        )
        self.version_dropdown.setEnabled(bool(version_items))

        version_layout.addWidget(self.version_dropdown)
        version_layout.addSpacing(2)

        self.rollback_btn = UIFactory.button(
            "Rollback to Selected Version",
            lambda: self._on_rollback_clicked_ui(self.version_dropdown.currentData()),
            "settings_button",
            height=35
        )

        self.rollback_btn.setEnabled(self.version_dropdown.count() > 0)
        version_layout.addWidget(self.rollback_btn)

        content_layout.addWidget(version_con)
        content_layout.addSpacing(4)

        # ── Status ──────────────────────────────────────────────────────────
        self.app_settings_status = UIFactory.label(
            "",
            align="center",
            font_size=8
        )
        self.app_settings_status.hide()

        content_layout.addWidget(self.app_settings_status)
        content_layout.addStretch()

        # Add content to main layout
        self._layout.addWidget(content)

        # Home button
        self._layout.addWidget(
            UIFactory.button(
                "Home",
                lambda: self._emit_clicked("suite_home"),
                "payroll_button"
            )
        )

    def show_settings_status(self, code):
        self._resize(530, self.height["settings"] + 20)

        if isinstance(code, tuple):
            code_, filename = code
        else:
            code_ = code
            filename = ""

        if "success" in code_ or "error" in code_:
            self.share_logs_btn.setDisabled(False)
            self.share_logs_btn.setText("Share Logs with Support")

        message_template = APP_SETTINGS_STATUSES[code_]
        status = message_template.format(file_name=filename or "")

        if "log" in status:
            status = status.replace(" log/s", "")


        self.app_settings_status.setText(status)
        
        self.app_settings_status.setStyleSheet(
                f"color: {'#16A34A' if 'success' in code_ else '#DC2626' if 'error' in code_ else '#D3D0D0'};"
                "font-size: 10px;"
            )
        self.app_settings_status.show()

    # ===================================================================
    # SETTINGS ACTIONS ON CLICK
    # ===================================================================
    def _on_add_user_clicked(self, email):
        self._hide_aux_buttons()
        self._hide_statuses()
        self._emit_clicked(['add_user', email])

    def _on_share_logs_clicked(self):
        self._hide_aux_buttons()
        self._hide_statuses()
        self.share_logs_btn.setDisabled(True)
        self.share_logs_btn.setText("Sharing...")

        current_file = self.share_logs_current_cbox.isChecked()
        start_date = self.start_date.date().toPyDate()
        end_date = self.end_date.date().toPyDate()
        self._emit_clicked(["share_logs", current_file, start_date, end_date])

    def _on_excel_locker_upload_btn_click(self):
        is_single = self.excel_locker_tabs.currentIndex() == 0

        if is_single:
            password = self.excel_locker_single_password.text().strip()
            create_copy = self.excel_locker_single_create_copy.isChecked()
            self._set_btn_processing(self.excel_locker_single_upload_btn, "Locking...")
        else:
            password = self.excel_locker_multiple_password.text().strip()
            create_copy = self.excel_locker_multiple_create_copy.isChecked()
            self._set_btn_processing(self.excel_locker_multiple_upload_btn, "Locking...")

        self._hide_aux_buttons()
        self._hide_statuses()
        self.excel_locker_status.hide()

        self._emit_clicked([
            'lock_excel',
            password,
            is_single,
            create_copy
        ])

    def _on_rollback_clicked_ui(self, selection):
        self._emit_clicked(["rollback", selection])

    # ===================================================================
    # SCREEN 5 — TOOLBOX
    # ===================================================================
    def show_toolbox(self):
        self._clear()
        self._resize(350, 400)

        tools_layout = QVBoxLayout()
        tools_layout.setSpacing(4)
        tools_layout.setContentsMargins(10, 10, 10, 10)
        tools_layout.addWidget(UIFactory.label("Toolbox", font_size=12, font_weight='bold', 
                                                 color='rgba(200, 200, 200, 1)', align='center'))

        col, layout = UIFactory.button_column(
            [
                ("Excel Locker", lambda: self._emit_clicked("excel_locker_tool"), "payroll_button"),
                ("Home",                lambda: self._emit_clicked("suite_home"),  "payroll_button"),
            ],
            spacing=12,
            parent=self,
            con_style_key=STYLES['body_clear']
        )

        layout.addStretch()
        tools_layout.addWidget(col)
        self._layout.addLayout(tools_layout)

    def _horizontal_tools(self):
        self._layout.setSpacing(8)
        self.setStyleSheet(STYLES["body_clear"])

        col, layout = UIFactory.button_row(
            [
                ("Excel Locker", lambda: self._emit_clicked("excel_locker_tool"), "payroll_button"),
                ("◀ Back",                lambda: self._emit_clicked("back"),  "payroll_button"),
            ],
            width=150,
            parent=self
        )
        layout.addStretch()
        col.setStyleSheet(STYLES['body'])
        self._layout.addWidget(col)

    # ===================================================================
    # EXCEL LOCKER
    # ===================================================================
    def show_excel_locker_tool(self, password):
        self._clear()
        self._horizontal_tools()

        self._layout.setContentsMargins(10, 10, 10, 10)
        self._resize(530, self.height['excel_locker_single'])

        content = QFrame()
        content.setObjectName("featureContent")
        content.setStyleSheet(STYLES["feature_content"])

        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(8)
        content_layout.setContentsMargins(10, 10, 10, 10)

        # ── Title ────────────────────────────────────────────────────────────────
        content_layout.addWidget(
            UIFactory.label(
                "🔒 Excel Locker",
                color="white",
                font_weight="bold",
                font_size=17
            )
        )

        # ── Description ──────────────────────────────────────────────────────────
        content_layout.addWidget(
            UIFactory.label(
                f"Protect Excel files with a default {password} or a password of your choice, either individually or in bulk.<br><br>"
                "For bulk files, use a .txt metadata file to assign specific passwords to each file.<br>"
                "Enable 'Create a copy' to keep the original files unchanged.",
                font_size=11,
                color="white",
                word_wrap=True
            )
        )

        content_layout.addSpacing(3)

        # ── Tabs ─────────────────────────────────────────────────────────────────
        self.excel_locker_tabs = QTabWidget()
        self.excel_locker_tabs.setStyleSheet(STYLES["tab_widget"])

        # ── Single File Tab ──────────────────────────────────────────────────────
        single_tab = QWidget()
        single_layout = QVBoxLayout(single_tab)
        single_layout.setContentsMargins(12, 12, 12, 12)
        single_layout.setSpacing(8)

        single_layout.addWidget(
            UIFactory.label(
                "Select an Excel file and use the default password or set your own password<br>" 
                " to protect it.<br>",
                style_key="standard"
            )
        )
        single_layout.addWidget(
            UIFactory.label(
                "🔐 Password:",
                style_key="header_label"
            )
        )

        copy_container = QFrame()
        copy_layout = QHBoxLayout(copy_container)
        copy_layout.setContentsMargins(0, 0, 0, 0)
        copy_layout.setSpacing(8)

        self.excel_locker_single_password = UIFactory.input("")
        self.excel_locker_single_password.setFixedHeight(30)
        self.excel_locker_single_password.setPlaceholderText(password)

        self.excel_locker_single_create_copy = QCheckBox("Create a copy")

        copy_layout.addWidget(self.excel_locker_single_password, 75)
        copy_layout.addWidget(self.excel_locker_single_create_copy, 25)
        copy_layout.addStretch()
        single_layout.addWidget(copy_container)
        

        self.excel_locker_single_upload_btn = UIFactory.button(
            "Upload",
            lambda: self._on_excel_locker_upload_btn_click(),
            "payroll_button"
        )

        single_layout.addWidget(self.excel_locker_single_upload_btn)
        single_layout.addStretch()

        # ── Multiple Files Tab ───────────────────────────────────────────────────
        multiple_tab = QWidget()
        multiple_layout = QVBoxLayout(multiple_tab)
        multiple_layout.setContentsMargins(12, 12, 12, 12)
        multiple_layout.setSpacing(8)

        multiple_layout.addWidget(
            UIFactory.label(
                "Select multiple Excel files and optionally provide a .txt metadata file "
                "to assign specific passwords to each file, or use the default password "
                "or a password of your choice for all files.<br><br>"
                "<b>TXT format:</b><br>"
                "filename.xlsx,password<br>"
                "filename1.xlsx,password123",
                style_key="standard",
                word_wrap=True
            )
        )

        multiple_layout.addWidget(
            UIFactory.label(
                "🔐 Password:",
                style_key="header_label"
            )
        )

        copy_container = QFrame()
        copy_layout = QHBoxLayout(copy_container)
        copy_layout.setContentsMargins(0, 0, 0, 0)
        copy_layout.setSpacing(8)

        self.excel_locker_multiple_password = UIFactory.input("")
        self.excel_locker_multiple_password.setPlaceholderText(password)
        self.excel_locker_multiple_password.setFixedHeight(30)

        self.excel_locker_multiple_create_copy = QCheckBox("Create a copy")

        copy_layout.addWidget(self.excel_locker_multiple_password, 75)
        copy_layout.addWidget(self.excel_locker_multiple_create_copy, 25)
        copy_layout.addStretch()
        multiple_layout.addWidget(copy_container)


        self.excel_locker_multiple_upload_btn = UIFactory.button(
            "Upload",
            lambda: self._on_excel_locker_upload_btn_click(),
            "payroll_button"
        )

        multiple_layout.addWidget(self.excel_locker_multiple_upload_btn)
        multiple_layout.addStretch()

        # ── Add Tabs ─────────────────────────────────────────────────────────────
        self.excel_locker_tabs.addTab(
            single_tab,
            "Single File"
        )

        self.excel_locker_tabs.addTab(
            multiple_tab,
            "Multiple Files"
        )

        # Resize based on tab
        self.excel_locker_tabs.currentChanged.connect(self._on_excel_locker_tab_changed)

        content_layout.addWidget(self.excel_locker_tabs)

        # ── Status ────────────────────────────────────────────────────────────────
        self.excel_locker_status_scroll = QScrollArea()
        self.excel_locker_status_scroll.setWidgetResizable(True)
        self.excel_locker_status_scroll.setStyleSheet(STYLES['settings_scroll'])
        self.excel_locker_status_scroll.hide()

        self.excel_locker_status = UIFactory.label(
            "",
            color="green",
            align="center"
        )
        self.excel_locker_status.hide()
        self.excel_locker_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        content_layout.addWidget(self.excel_locker_status_scroll)
        content_layout.addWidget(self.excel_locker_status)
        content_layout.addStretch()
        self._layout.addWidget(content)

        # Kept so show/update/hide-progress can add/remove widgets into the
        # same frame the tabs and status label live in.
        self.excel_locker_content_layout = content_layout

    def _excel_locker_height(self):
        """Multiple Files has an extra instructions block (TXT format
        example), so it needs more vertical room than Single File."""
        is_multiple = getattr(self, "excel_locker_tabs", None) and self.excel_locker_tabs.currentIndex() == 1
        return self.height["excel_locker_multiple"] if is_multiple else self.height["excel_locker_single"]

    def _on_excel_locker_tab_changed(self, index):
        self._resize(530, self._excel_locker_height())

    # ===================================================================
    # EXCEL LOCKER PROGRESS BAR
    # ===================================================================

    def show_excel_locker_progress(self, title: str = "Locking files…"):
        """
        Render a progress bar under the Excel Locker tabs while the
        background worker locks the selected file(s). Mirrors the
        show_processing_progress()/update_processing_progress() pattern
        used by Payroll/Billing (see body_apps/payroll_app.py and
        body_apps/billing_app.py).
        """
        self._resize(530, self._excel_locker_height() + 40)

        self.excel_locker_progress_label = UIFactory.label(
            title,
            style_key="standard",
            align="center",
            word_wrap=True,
        )
        self.excel_locker_content_layout.addWidget(self.excel_locker_progress_label)

        self.excel_locker_percent_label = UIFactory.label(
            "0%",
            style_key="header_label",
            align="center",
        )
        self.excel_locker_content_layout.addWidget(self.excel_locker_percent_label)

        self.excel_locker_progress = QProgressBar()
        self.excel_locker_progress.setRange(0, 100)
        self.excel_locker_progress.setValue(0)
        self.excel_locker_progress.setFixedHeight(3)
        self.excel_locker_progress.setStyleSheet(STYLES["progress_bar"])
        self.excel_locker_progress.setTextVisible(False)
        self.excel_locker_content_layout.addWidget(self.excel_locker_progress)
        self._main_window.start_progress_heartbeat()

    def update_excel_locker_progress(self, percent: int, message: str):
        """Update the Excel Locker progress bar and labels. Called from
        Orchestrator via the worker's progress signal."""
        if getattr(self, "excel_locker_progress", None):
            self._animate_progress(self.excel_locker_progress, percent, "_excel_locker_progress_animation")
        if getattr(self, "excel_locker_percent_label", None):
            self.excel_locker_percent_label.setText(f"{percent}%")
        if getattr(self, "excel_locker_progress_label", None):
            self.excel_locker_progress_label.setText(message)

    def _clear_excel_locker_progress(self):
        self._main_window.stop_progress_heartbeat()
        for attr in ("excel_locker_progress_label", "excel_locker_percent_label", "excel_locker_progress"):
            widget = getattr(self, attr, None)
            if widget is not None:
                self.excel_locker_content_layout.removeWidget(widget)
                widget.deleteLater()
                setattr(self, attr, None)

    def show_excel_locker_result(self, total, locked, errors, single_file=False, single_name=None):
        """
        Single entry point for all excel-locker status output.

        - Multi-file, no errors: "5 out of 5 locked."
        - Single-file, no errors: "filename.xlsx locked successfully."
        - Errors present: one line per file, resolved from
          EXCEL_LOCKER_STATUSES (see ui/statuses.py) via each
          (name, status_code) pair in `errors`.
        Box height grows/shrinks to fit the number of lines shown.
        """
        self._clear_excel_locker_progress()
        self._set_btn_default(self.excel_locker_single_upload_btn, "Upload")
        self._set_btn_default(self.excel_locker_multiple_upload_btn, "Upload")

        if not errors:
            if single_file and single_name:
                message = EXCEL_LOCKER_STATUSES["locked_success"].format(file_name=single_name)
            else:
                message = f"{locked} out of {total} locked successfully."
            line_count = 1
            is_success = True
        else:
            lines = [
                EXCEL_LOCKER_STATUSES.get(code, code).format(file_name=name)
                for name, code in errors
            ]
            if locked > 0:
                summary = f"{locked} out of {total} locked succesfully."
                lines.insert(0, f'<span style="color:#16A34A;">{summary}</span>')
            line_count = len(lines)
            message = "<br>".join(lines)
            is_success = False

       # Dynamic height: base height for one line, plus a bit per extra line.
        line_count = message.count("<br>") + 1
        base_height = self._excel_locker_height()
        line_height = 14
        max_lines_before_scroll = 8

        visible_lines = min(line_count, max_lines_before_scroll)
        extra_height = max(0, (visible_lines - 1) * line_height)

        self._resize(530, base_height + 10 + extra_height)


        if line_count > 8:
            # ── Scrollable status ───────────────────────────────────────────────
            status_label = self.excel_locker_status_scroll.widget()

            if status_label is None:
                status_label = QLabel()
                status_label.setWordWrap(True)
                status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

                self.excel_locker_status_scroll.setWidget(status_label)

            status_label.setText(message)

            status_label.setStyleSheet(
                f"color: {'#16A34A' if is_success else '#DC2626'};"
                "font-size: 10px;"
            )

            status_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse |
                Qt.TextInteractionFlag.TextSelectableByKeyboard
            )

            self.excel_locker_status_scroll.show()
            self.excel_locker_status.hide()

        else:
            # ── Normal status ───────────────────────────────────────────────────
            self.excel_locker_status.setText(message)
            self.excel_locker_status.setStyleSheet(
                f"color: {'#16A34A' if is_success else '#DC2626'};"
                "font-size: 10px;"
            )

            self.excel_locker_status.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse |
                Qt.TextInteractionFlag.TextSelectableByKeyboard
            )

            self.excel_locker_status.show()
            self.excel_locker_status_scroll.hide()


