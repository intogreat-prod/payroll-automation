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

import time

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

        # Root layout — screens are swapped in/out of this
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)

        # ---------------------------------------------------------------
        # Aux UI storage
        # Buttons and statuses are keyed by feature, then by a unique name.
        # Each button entry: { "widget": QPushButton, "visible_on": [status_code, ...] }
        # ---------------------------------------------------------------
        self.statuses = {
            "payroll":  {},
            "checker":  {},
            "settings": {}
        }

        self.buttons = {
            "payroll": {},
            "checker": {}
        }

        self.height = {
            "payroll": 820,
            "checker": 770,
            "settings": 910,
            "dbx_to_sprout": 730,
            "att_summary": 850
        }

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

    def _resize(self, w, h):
        """Ask the parent MainWindow to resize itself."""
        self._main_window.resize_to(w, h)

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
        self._resize(400, 400)

        self._login_form = LoginForm(on_login_callback=lambda: self._emit_clicked("login"))

        self._layout.addStretch()
        self._layout.addWidget(self._login_form)
        self._layout.addStretch()

    def update_login_form(self, action: str, *args):
        LOGIN_FORM_STATUSES = {
            "device_code":     ((400, 400), "show_device_code"),
            "restricted_user": ((400, 410), "show_restricted_user"),
            "login_error":     ((400, 400), "show_error_login"),
            "config_error":    ((400, 410), "show_error_download"),
            "json_error":      ((400, 410), "show_error_json"),
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
        self._resize(400, 550)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(10)
        self._layout.addWidget(UIFactory.label(
            "Update Available",
            style_key="header_label",
            align="center"
        ))
        self._layout.addWidget(UIFactory.label(
            f"A new version of Payroll Automation is available.",
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
            "payroll_button"
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
            "Updating Payroll Automation",
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
    # SCREEN 5 — MAIN MENU SELECTION
    # ===================================================================
    def show_main_menu(self):
        self._clear()
        self.setStyleSheet(STYLES["body_clear"])
        self._resize(350, 420)

        col, layout = UIFactory.button_column(
            [
                ("Payroll Automation", lambda: self._emit_clicked("automation_menu"), "payroll_button"),
                ("Tools",              lambda: self._emit_clicked("tools_menu"),    "payroll_button"),
                ("Settings",           lambda: self._emit_clicked("settings_menu"),  "payroll_button"),
            ],
            spacing=12,
            parent=self
        )

        layout.addStretch()
        self._layout.addWidget(col)

    def _horizontal_main_menu(self):
        self._layout.setSpacing(8)
        self.setStyleSheet(STYLES["body_clear"])

        col, layout = UIFactory.button_row(
            [
                ("Payroll Automation", lambda: self._emit_clicked("automation_menu"), "payroll_button"),
                ("Tools",              lambda: self._emit_clicked("tools_menu"),    "payroll_button"),
                ("Settings",           lambda: self._emit_clicked("settings_menu"),  "payroll_button"),
            ],
            width=150,
            parent=self
        )
        layout.addStretch()
        col.setStyleSheet(STYLES['body'])
        self._layout.addWidget(col)
    
    # ===================================================================
    # SCREEN 6 — SOURCE SELECTION
    # ===================================================================
    def show_sources(self):
        self._clear()
        #self.setStyleSheet(STYLES["body_clear"])
        self._resize(350, 450)

        sources_layout = QVBoxLayout()
        sources_layout.setSpacing(4)
        sources_layout.setContentsMargins(10, 10, 10, 10)
        sources_layout.addWidget(UIFactory.label("Select Source:", font_size=12, font_weight='bold', 
                                                 color='rgba(200, 200, 200, 1)', align='center'))

        col, layout = UIFactory.button_column(
            [
                ("", lambda: self._emit_clicked("DarwinBox_source"), "payroll_button", ("assets/darwinbox.png", 100, 50)),
                ("", lambda: self._emit_clicked("Sprout_source"), "payroll_button", ("assets/sprout.png", 80, 40)),
                ("Home", lambda: self._emit_clicked("home"), "payroll_button"),
            ],
            spacing=12,
            parent=self

        )

        layout.addStretch()
        sources_layout.addWidget(col)
        self._layout.addLayout(sources_layout)

    # ===================================================================
    # SCREEN 7 — FEATURE LIST
    # ===================================================================
    def show_darwin_features(self):
        self._clear()
        #self.setStyleSheet(STYLES["body_clear"])
        self._resize(350, 475)

        darwin_feat_layout = QVBoxLayout()
        darwin_feat_layout.setSpacing(4)
        darwin_feat_layout.setContentsMargins(10, 20, 10, 10)
        darwin_feat_layout.addWidget(UIFactory.image("assets/darwinbox.png", 150, 150))
        darwin_feat_layout.addSpacing(3)

        col, layout = UIFactory.button_column(
            [
                ("Payroll",  lambda: self._emit_clicked("payroll_feature"),  "payroll_button"),
                ("Checker",  lambda: self._emit_clicked("checker_feature"),  "button"),
                ("Home",     lambda: self._emit_clicked("home"), "button"),
            ],
            parent=self

        )

        layout.addStretch()
        darwin_feat_layout.addWidget(col)
        self._layout.addLayout(darwin_feat_layout)

    def _horizontal_menu_darwin_features(self):
        self._layout.setSpacing(8)
        self.setStyleSheet(STYLES["body_clear"])

        col, layout = UIFactory.button_row(
            [
                ("Payroll",  lambda: self._emit_clicked("payroll_feature"),  "payroll_button"),
                ("Checker",  lambda: self._emit_clicked("checker_feature"),  "button"),
                ("Home",     lambda: self._emit_clicked("home"), "button"),
            ],
            width=120,
            parent=self
        )
        layout.addWidget(UIFactory.image("assets/darwinbox_icon.png", 30, 30))
        col.setStyleSheet(STYLES['body'])
        self._layout.addWidget(col)

    def show_sprout_features(self):
        self._clear()
        self._resize(350, 480)

        sprout_feat_layout = QVBoxLayout()
        sprout_feat_layout.setSpacing(4)
        sprout_feat_layout.setContentsMargins(10, 20, 10, 10)
        sprout_feat_layout.addWidget(UIFactory.image("assets/sprout.png", 120, 120))
        sprout_feat_layout.addSpacing(3)


        col, layout = UIFactory.button_column(
            [
                ("Payroll",  lambda: self._emit_clicked("payroll_feature"),  "payroll_button"),
                ("Checker",  lambda: self._emit_clicked("checker_feature"),  "button"),
                ("Home",     lambda: self._emit_clicked("home"), "button"),
            ],
            parent=self

        )

        layout.addStretch()
        sprout_feat_layout.addWidget(col)
        self._layout.addLayout(sprout_feat_layout)

    def _horizontal_menu_sprout_features(self):
        self._layout.setSpacing(8)
        self.setStyleSheet(STYLES["body_clear"])

        col, layout = UIFactory.button_row(
            [
                ("Payroll",  lambda: self._emit_clicked("payroll_feature"),  "payroll_button"),
                ("Checker",  lambda: self._emit_clicked("checker_feature"),  "button"),
                ("Home",     lambda: self._emit_clicked("home"), "button"),
            ],
            width=120,
            parent=self
        )
        layout.addWidget(UIFactory.image("assets/sprout_icon.png", 30, 30))
        col.setStyleSheet(STYLES['body'])
        self._layout.addWidget(col)

    # ===================================================================
    # SCREEN 8 — TOOL SELECTION
    # ===================================================================
    def show_tools(self):
        self._clear()
        self._resize(350, 450)

        tools_layout = QVBoxLayout()
        tools_layout.setSpacing(4)
        tools_layout.setContentsMargins(10, 10, 10, 10)
        tools_layout.addWidget(UIFactory.label("Select Tool:", font_size=12, font_weight='bold', 
                                                 color='rgba(200, 200, 200, 1)', align='center'))

        col, layout = UIFactory.button_column(
            [
                ("DarwinBox to Sprout", lambda: self._emit_clicked("dbx_to_sprout_tool"), "payroll_button"),
                ("Attendance Summary",   lambda: self._emit_clicked("attendance_summary_tool"),    "payroll_button"),
                ("Home",                lambda: self._emit_clicked("home"),  "payroll_button"),
            ],
            spacing=12,
            parent=self,
            con_style_key=STYLES['body_clear']
        )

        layout.addStretch()
        tools_layout.addWidget(col)
        self._layout.addLayout(tools_layout)

    def _horizontal_menu_tools(self):
        self._layout.setSpacing(8)
        self.setStyleSheet(STYLES["body_clear"])

        col, layout = UIFactory.button_row(
            [
                ("DarwinBox to Sprout", lambda: self._emit_clicked("dbx_to_sprout_tool"), "payroll_button"),
                ("Attendance Summary",   lambda: self._emit_clicked("attendance_summary_tool"),    "payroll_button"),
                ("Home",                lambda: self._emit_clicked("home"),  "payroll_button"),
            ],
            width=150,
            parent=self
        )
        layout.addStretch()
        col.setStyleSheet(STYLES['body'])
        self._layout.addWidget(col)

    # ===================================================================
    # SCREEN 9 — SETTINGS
    # ===================================================================
    def show_settings(self, users, deminimis):
        self._clear()
        self._horizontal_main_menu()
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._resize(530, self.height['settings'])

        content = QFrame()
        content.setObjectName("featureContent")
        content.setStyleSheet(STYLES["feature_content"])

        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(4)
        content_layout.setContentsMargins(10, 10, 10, 10)

        content_layout.addWidget(UIFactory.label("⚙️ Settings", color='white', font_weight="bold", font_size=17))
        content_layout.addSpacing(3)

        # ── Automation Files frame ───────────────────────────────────────────────
        automation_con = QFrame()
        automation_con.setStyleSheet(STYLES["standard_container"])

        automation_layout = QVBoxLayout(automation_con)
        automation_layout.setSpacing(2)
        automation_layout.setContentsMargins(12, 12, 12, 12)

        automation_layout.addWidget(UIFactory.label("Automation Files", style_key="header_label"))
        _, btn_row = UIFactory.button_row(
            [
                ("Payroll Headers",         lambda: self._emit_clicked("payroll_headers"), "settings_button"),
                ("Night Differential List", lambda: self._emit_clicked("nd_list"),         "settings_button"),
            ],
            spacing=8,
            margin=(0, 0, 0, 0),
            use_container=False,
        )

        automation_layout.addLayout(btn_row)
        automation_layout.addSpacing(2)

        automation_layout.addWidget(UIFactory.label(
            "Note: Refresh app after updating Payroll Headers or ND List.",
            style_key="standard_red",
            word_wrap=True,
            align="left"
        ))
        content_layout.addWidget(automation_con)
        content_layout.addSpacing(4)

        # ── Deminimis frame ──────────────────────────────────────────────────────
        deminimis_con = QFrame()
        deminimis_con.setStyleSheet(STYLES["standard_container"])

        deminimis_layout = QVBoxLayout(deminimis_con)
        deminimis_layout.setSpacing(6)
        deminimis_layout.setContentsMargins(12, 12, 12, 12)

        deminimis_layout.addWidget(UIFactory.label("Deminimis", style_key="header_label"))

        # Label row
        labels_row = QHBoxLayout()
        labels_row.setSpacing(8)

        for detail in deminimis:
            labels_row.addWidget(UIFactory.label(detail, font_weight="bold", color='white'))
        deminimis_layout.addLayout(labels_row)

        # Input row
        inputs_row = QHBoxLayout()
        inputs_row.setSpacing(6)
        self.deminimis_inputs = {}
        for detail, val in deminimis.items():
            inp = UIFactory.input("")
            inp.setPlaceholderText(str(val))
            inp.setFixedHeight(30)
            self.deminimis_inputs[detail] = inp
            inputs_row.addWidget(inp)

        deminimis_layout.addLayout(inputs_row)
        deminimis_layout.addSpacing(2)

        self.save_deminimis_btn = UIFactory.button(
            "Save",
            lambda: self._on_save_deminimis_clicked(
                {
                    detail: inp.text().strip()
                    for detail, inp in self.deminimis_inputs.items()
                }
            ),
            "settings_button",
            height=35,
        )

        deminimis_layout.addWidget(self.save_deminimis_btn)
        content_layout.addWidget(deminimis_con)
        content_layout.addSpacing(6)

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
        for key, status in SETTINGS_STATUSES.items():
            lbl = UIFactory.label(status, color="red" if "error" in key else "green", align="center")
            lbl.hide()
            content_layout.addWidget(lbl)

        self._layout.addWidget(content)

    # ===================================================================
    # SCREEN 10 — FEATURE VIEWS
    # ===================================================================
    def show_payroll_feature(self, required_files, source):
        self._clear()
        self.required_files_len = len(required_files)

        if "DarwinBox" in source:
            self._horizontal_menu_darwin_features()
        else:
            self._horizontal_menu_sprout_features()

        self._layout.setContentsMargins(10, 10, 10, 10)
        self._resize(530, self.height['payroll'] + (self.required_files_len * 10))

        content = QFrame()
        content.setObjectName("featureContent")
        content.setStyleSheet(STYLES["feature_content"])
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(8)
        content_layout.setContentsMargins(10, 10, 10, 10)

        content_layout.addWidget(UIFactory.label("Payroll Automation", color='white', font_weight="bold", font_size=17))
        content_layout.addWidget(
            UIFactory.label(
                "Validates all input files and submits them to Unmand for payroll header validation"
                "using the formulas defined in the \n Premium Headers Excel. The process applies "
                "payroll rates, identifies data variations.\n\n"
                ""
                "Outputs an Excel file containing the Mapping Table, Checker, and Checking Table,"
                "along with a TXT file that \nincludes the detailed computation results.",
                font_size=11, color='white'
            )
        )
        content_layout.addSpacing(6)

        # ── Versioning ──────────────────────────────────────────────
        versioning_con = QFrame()
        versioning_con.setStyleSheet(STYLES["standard_container"])

        versioning_layout = QVBoxLayout(versioning_con)
        versioning_layout.setContentsMargins(12, 12, 12, 12)
        versioning_layout.setSpacing(6)

        versioning_layout.addWidget(
            UIFactory.label(
                "🏷️ Versioning",
                color="white",
                font_weight="bold",
                font_size=15,
            )
        )

        versioning_layout.addWidget(
            UIFactory.label(
                "Enter the Run ID and Version to resume a previous run, or leave them blank to start a new one.",
                color="white",
                font_size=11,
                padding_bottom=6,
            )
        )

        versioning_row = QHBoxLayout()
        versioning_row.setSpacing(16)

        # Run ID
        run_id_layout = QVBoxLayout()
        run_id_layout.setSpacing(4)

        run_id_layout.addWidget(
            UIFactory.label(
                "Run ID:",
                color="white",
                font_weight="bold",
            )
        )

        id_input = UIFactory.input("e.g., 20260422_071827")
        run_id_layout.addWidget(id_input)

        # Version
        version_layout = QVBoxLayout()
        version_layout.setSpacing(4)

        version_layout.addWidget(
            UIFactory.label(
                "Version:",
                color="white",
                font_weight="bold",
            )
        )

        version_input = UIFactory.input("e.g., v1")
        version_layout.addWidget(version_input)

        # Add columns
        versioning_row.addLayout(run_id_layout, 1)
        versioning_row.addSpacing(16)
        versioning_row.addLayout(version_layout, 1)

        versioning_layout.addLayout(versioning_row)

        # Add to page
        content_layout.addWidget(versioning_con)
        content_layout.addSpacing(6)

        # ── Required Files Frame ────────────────────────────────────
        required_con = QFrame()
        required_con.setStyleSheet(STYLES["standard_container"])

        required_layout = QVBoxLayout(required_con)
        required_layout.setContentsMargins(12, 12, 12, 12)
        required_layout.setSpacing(3)

        required_layout.addWidget(
            UIFactory.label("🗂️ Required Files", style_key="header_label")
        )

        # Two-column layout
        columns = QHBoxLayout()
        columns.setSpacing(24)

        # Left column - Required Files
        files_layout = QVBoxLayout()
        files_layout.setSpacing(1)

        for t in required_files:
            files_layout.addWidget(
                UIFactory.label(f"• {t}", font_size=11, color="rgba(200, 200, 200, 1)")
            )

        # Right column - Notes
        notes_layout = QVBoxLayout()
        notes_layout.setSpacing(4)
        notes_layout.addWidget(UIFactory.label(
            "Note:\n"
            "• Headers in Row 1; use Sheet 1.\n"
            "• File type must be .xlsx\n"
            "• Sensitivity should be set to Public\n"
            "• The file should not be password-protected.\n"
            "• If required, use INTOGREAT[YYYY].\n"
            "• Total should be at the end row.\n"
            "• No headers should be the same.\n",
            style_key="standard_red",
            word_wrap=True,
            align="left"
        ))

        columns.addLayout(files_layout, 1)
        columns.addLayout(notes_layout, 1)

        required_layout.addLayout(columns)

        content_layout.addWidget(required_con)
        content_layout.addStretch()

        # ---------------------------------------------------------------
        # PRIMARY — Upload button (with processing state)
        # ---------------------------------------------------------------
        self.payroll_upload_btn = UIFactory.button(
            "Upload",
            lambda: self._on_payroll_upload_btn_click(id_input, version_input),
            "payroll_button"
        )
        content_layout.addWidget(self.payroll_upload_btn)

        # ---------------------------------------------------------------
        # AUX BUTTONS — registered with the dynamic visibility system
        # ---------------------------------------------------------------
        payroll_unmand_btn = UIFactory.button(
            "Send to Unmand",
            lambda: self._emit_clicked("send_unmand"),
            "payroll_button"
        )
        content_layout.addWidget(payroll_unmand_btn)
        self._register_aux_button("payroll", "payroll_unmand", payroll_unmand_btn,
                                  visible_on=["file_success"])

        open_new_btn = UIFactory.button(
            "Open new headers",
            lambda: self._emit_clicked("open_new_headers"),
            "payroll_button"
        )
        content_layout.addWidget(open_new_btn)
        self._register_aux_button("payroll", "open_new_btn", open_new_btn,
                                  visible_on=["new_headers_error"])

        check_unmand_btn = UIFactory.button(
            "Check Unmand Status",
            lambda: self._emit_clicked("check_status"),
            "payroll_button"
        )
        content_layout.addWidget(check_unmand_btn)
        self._register_aux_button("payroll", "check_unmand_btn", check_unmand_btn,
                                  visible_on=["unmand_init_success", "unmand_status_pending_error"])

        open_output_btn = UIFactory.button(
            "Open Output",
            lambda: self._emit_clicked("open_payroll_ouput"),
            "payroll_button"
        )
        content_layout.addWidget(open_output_btn)
        self._register_aux_button("payroll", "open_output_btn", open_output_btn,
                                  visible_on=["unmand_status_success"])

        self._layout.addWidget(content)

    def show_checker_feature(self, source):
        self._clear()

        if "DarwinBox" in source:
            self._horizontal_menu_darwin_features()
        else:
            self._horizontal_menu_sprout_features()

        self._layout.setContentsMargins(10, 10, 10, 10)
        self._resize(530, self.height['checker'])

        content = QFrame()
        content.setObjectName("featureContent")
        content.setStyleSheet(STYLES["feature_content"])

        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(8)
        content_layout.setContentsMargins(10, 10, 10, 10)

        content_layout.addWidget(UIFactory.label("Unmand vs Manual", color='white', font_weight="bold", font_size=17))
        content_layout.addWidget(
                UIFactory.label(
                    "Compares the Unmand output with the Finance Manual Checker using "
                    "the formulas defined in the Premium Headers Excel.\n\n"
                    "The automation validates payroll rates, detects data variations, "
                    "and generates a detailed comparison report.\n\n"
                    "Output:\n"
                    "• Excel report with the overall accuracy rate\n"
                    "• Total number of rows compared\n"
                    "• Detailed cell-by-cell comparison of both outputs",
                    font_size=11,
                    color="white",
                    word_wrap=True
                )
            )
        content_layout.addSpacing(6)

       # ── Required Files Frame ────────────────────────────────────
        required_con = QFrame()
        required_con.setStyleSheet(STYLES["standard_container"])

        required_layout = QVBoxLayout(required_con)
        required_layout.setContentsMargins(12, 12, 12, 12)
        required_layout.setSpacing(8)

        required_layout.addWidget(
            UIFactory.label("🗂️ Required Files", style_key="header_label")
        )

        # Two columns
        columns = QHBoxLayout()
        columns.setSpacing(32)

        # ── Left Column: Files ──────────────────────────────────────
        files_layout = QVBoxLayout()
        files_layout.setSpacing(6)

        for t in ["Manual Checker", "Unmand Automation Output"]:
            files_layout.addWidget(
                UIFactory.label(f"• {t}", style_key="standard")
            )

        files_layout.addStretch()

        # ── Right Column: Notes ─────────────────────────────────────
        notes_layout = QVBoxLayout()
        notes_layout.setSpacing(6)
        notes_layout.addWidget(
            UIFactory.label(
                "Note:\n"
                "• Headers must be in Row 1 (Sheet 1)\n"
                "• File type must be .xlsx\n"
                "• Sensitivity must be set to Public.\n"
                "• File must not be password-protected.\n"
                "• Use INTOGREAT[YYYY] if required.\n"
                "• Total must be at the end of each row.",
                style_key="standard_red",
                word_wrap=True,
                align="left"
            )
        )

        # Add columns
        columns.addLayout(files_layout, 1)
        columns.addLayout(notes_layout, 2)

        required_layout.addLayout(columns)

        content_layout.addWidget(required_con)
        content_layout.addStretch()

        # ── Action buttons ───────────────────────────────────────────────────────
        self.checker_upload_btn = UIFactory.button(
            "Upload",
            lambda: self._on_checker_upload_btn_click(),
            "payroll_button"
        )
        content_layout.addWidget(self.checker_upload_btn)

        open_output_btn = UIFactory.button(
            "Open Output",
            lambda: self._emit_clicked("open_checker_output"),
            "payroll_button"
        )
        content_layout.addWidget(open_output_btn)

        self._register_aux_button("checker", "open_output_btn", open_output_btn,
                                    visible_on=["validated_success"])
        
        # Status labels
        for key, status in CHECKER_STATUSES.items():
            lbl = UIFactory.label(status, color="red" if "error" in key else "green", align="center")
            lbl.hide()
            content_layout.addWidget(lbl)

        self._layout.addWidget(content)

    # ===================================================================
    # SCREEN 11 — TOOLS
    # ===================================================================
    def show_dbx_to_sprout_tool(self):
        self._clear()
        self._horizontal_menu_tools()

        self._layout.setContentsMargins(10, 10, 10, 10)
        self._resize(530, self.height['dbx_to_sprout'])
        
        content = QFrame()
        content.setObjectName("featureContent")
        content.setStyleSheet(STYLES["feature_content"])
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(8)
        content_layout.setContentsMargins(10, 10, 10, 10)

        content_layout.addWidget(UIFactory.label("DarwinBox to Sprout Payroll", color='white', font_weight="bold", font_size=17))
        content_layout.addWidget(
            UIFactory.label(
                "This process extracts data from the DarwinBox Payroll Register, "
                "converts payroll-related headers into \n standardized time categories, and "
                "consolidates all records at the employee level.\n\n"
                "The output provides a unified view of each employee's time and "
                "payroll-related information for \n reporting, analysis, and downstream processing.",
                font_size=11, color='white'
            )
        )
        content_layout.addSpacing(6)

        # ── Required Files frame ─────────────────────────────────────────────────
        required_con = QFrame()
        required_con.setStyleSheet(STYLES['standard_container'])

        required_layout = QVBoxLayout(required_con)
        required_layout.setSpacing(4)
        required_layout.setContentsMargins(12, 12, 12, 12)

        required_layout.addWidget(UIFactory.label("🗂️ Required Files:", style_key="header_label"))
        for t in ["DarwinBox Payroll Register"]:
            required_layout.addWidget(UIFactory.label("• " + t, style_key="standard"))

        required_layout.addSpacing(6)
        required_layout.addWidget(UIFactory.label(
            "Note:\n"
            "• Headers in Row 1; use Sheet 1.\n"
            "• File type must be .xlsx\n"
            "• Sensitivity should be set to Public\n"
            "• The file should not be password-protected.\n"
            "• If required, use INTOGREAT[YYYY].\n"
            "• No headers should be the same.",
            style_key="standard_red",
            word_wrap=True,
            align="left"
        ))
        content_layout.addWidget(required_con)
        content_layout.addStretch()

        # ── Action buttons ───────────────────────────────────────────────────────
        self.dbx_to_sprout_upload_btn = UIFactory.button(
            "Upload",
            lambda: self._on_dbx_to_sprout_upload_btn_click(),
            "payroll_button"
        )
        content_layout.addWidget(self.dbx_to_sprout_upload_btn)

        open_output_btn = UIFactory.button(
            "Open Output",
            lambda: self._emit_clicked("open_dbx_to_sprout_output"),
            "payroll_button"
        )
        content_layout.addWidget(open_output_btn)

        self._register_aux_button("checker", "open_output_btn", open_output_btn,
                                    visible_on=["converted_success"])
        
        # Status labels
        for key, status in DBX_TO_SPROUT_STATUSES.items():
            lbl = UIFactory.label(status, color="red" if "error" in key else "green", align="center")
            lbl.hide()
            content_layout.addWidget(lbl)

        self._layout.addWidget(content)

    def show_attendance_summary_tool(self):
        self._clear()
        self._horizontal_menu_tools()
        self._layout.setContentsMargins(10, 10, 10, 10)

        self._resize(530, self.height['att_summary'])
        content = QFrame()
        content.setObjectName("featureContent")
        content.setStyleSheet(STYLES["feature_content"])

        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(8)  # was 1 — gave everything a cramped feel
        content_layout.setContentsMargins(10, 10, 10, 10)

        content_layout.addWidget(UIFactory.label("DarwinBox Attendance Summary", color='white', font_weight="bold", font_size=17))
        content_layout.addWidget(
            UIFactory.label(
                "This process extracts data from the DarwinBox Attendance Report, "
                "filtering the records based on cut-off periods \n and calculating "
                "attendance metrics, including present days, absences, unpaid leave, lates, and early-outs.\n\n"
                "Generates summarized reports to support payroll processing and attendance monitoring.",
                font_size=11, color='white'
            )
        )
        content_layout.addSpacing(6)

        # ── Attendance Period frame ──────────────────────────────────────────────
        attendance_con = QFrame()
        attendance_con.setStyleSheet(STYLES['standard_container'])

        attendance_layout = QVBoxLayout(attendance_con)
        attendance_layout.setSpacing(6)
        attendance_layout.setContentsMargins(12, 12, 12, 12)

        attendance_layout.addWidget(UIFactory.label("📅 Attendance Period", color='white', font_weight="bold", font_size=15))
        attendance_layout.addWidget(UIFactory.label(
            "Select the attendance period to include in the report.",
            font_size=11, color="white", padding_bottom=5
        ))

        # Date row: [Start] → [Cutoff]
        date_picker_row = QHBoxLayout()
        date_picker_row.setSpacing(0)

        # Start date
        start_layout = QVBoxLayout()
        start_layout.setSpacing(4)

        start_layout.addWidget(UIFactory.label("Start Date:", font_weight="bold", color='white'))
        self.start_date = UIFactory.date_picker(
            default_date=QDate.currentDate(),
            width=90,
            style_key='date_picker'
        )
        start_layout.addWidget(self.start_date)
        date_picker_row.addLayout(start_layout)

        # Arrow in between
        arrow_label = UIFactory.label("➜", color='white', font_size=18)
        arrow_label.setAlignment(Qt.AlignmentFlag.AlignBottom)
        arrow_label.setContentsMargins(10, 0, 10, 4)  # nudge arrow to sit level with the pickers
        date_picker_row.addWidget(arrow_label)

        # Cutoff date
        cutoff_layout = QVBoxLayout()
        cutoff_layout.setSpacing(4)

        cutoff_layout.addWidget(UIFactory.label("Cutoff Date:", font_weight="bold", color='white'))
        self.cutoff = UIFactory.date_picker(
            default_date=QDate.currentDate(),
            width=90,
            style_key='date_picker'
        )

        cutoff_layout.addWidget(self.cutoff)
        date_picker_row.addLayout(cutoff_layout)
        date_picker_row.addStretch()  # keep pickers left-anchored
        attendance_layout.addLayout(date_picker_row)
        content_layout.addWidget(attendance_con)
        content_layout.addSpacing(6)

        # ── Required Files frame ─────────────────────────────────────────────────
        required_con = QFrame()
        required_con.setStyleSheet(STYLES['standard_container'])
        required_layout = QVBoxLayout(required_con)
        required_layout.setSpacing(4)
        required_layout.setContentsMargins(12, 12, 12, 12)

        required_layout.addWidget(UIFactory.label("🗂️ Required Files:", color='white', font_weight="bold", font_size=15, padding_bottom=5))
        for t in ["DarwinBox Attendance Report"]:
            required_layout.addWidget(UIFactory.label("• " + t, style_key='standard'))

        required_layout.addSpacing(4)
        required_layout.addWidget(UIFactory.label(
            "Note:\n"
            "• Headers in Row 1; use Sheet 1.\n"
            "• File type must be .xlsx\n"
            "• Sensitivity should be set to Public\n"
            "• The file should not be password-protected.\n"
            "• If required, use INTOGREAT[YYYY].\n"
            "• No headers should be the same.",
            style_key="standard_red",
            word_wrap=True,
            align="left"
        ))

        content_layout.addWidget(required_con)
        content_layout.addStretch()
        
        # ── Action buttons ───────────────────────────────────────────────────────
        self.att_summary_upload_btn = UIFactory.button(
            "Upload",
            lambda: self._on_attendance_summary_upload_btn_click(),
            "payroll_button"
        )
        content_layout.addWidget(self.att_summary_upload_btn)

        open_output_btn = UIFactory.button(
            "Open Output",
            lambda: self._emit_clicked("open_att_summary_output"),
            "payroll_button"
        )
        content_layout.addWidget(open_output_btn)

        self._register_aux_button("checker", "open_output_btn", open_output_btn,
                                    visible_on=["summarized_success"])
        
        # Status labels
        for key, status in ATTENDANCE_SUMMARY.items():
            lbl = UIFactory.label(status, color="red" if "error" in key else "green", align="center")
            lbl.hide()
            content_layout.addWidget(lbl)

        self._layout.addWidget(content)
    # ===================================================================
    # ACTIONS ON CLICK
    # ===================================================================
    
    def _on_payroll_upload_btn_click(self, id_input, version_input):
        """Handle Upload button click: switch to processing state, then emit."""
        self._set_btn_processing(self.payroll_upload_btn, "Processing...")
        self._hide_aux_buttons()
        self._hide_statuses()
        self._emit_clicked(["payroll_upload", id_input.text().strip(), version_input.text().strip()])

    def _on_checker_upload_btn_click(self):
        self._set_btn_processing(self.checker_upload_btn, "Processing...")
        self._hide_aux_buttons()
        self._hide_statuses()
        self._emit_clicked("checker_upload")

    def _on_save_deminimis_clicked(self, deminimis):
        self._hide_aux_buttons()
        self._hide_statuses()
        self._emit_clicked(['save_deminimis', deminimis])

    def _on_add_user_clicked(self, email):
        self._hide_aux_buttons()
        self._hide_statuses()
        self._emit_clicked(['add_user', email])

    def _on_dbx_to_sprout_upload_btn_click(self):
        self._set_btn_processing(self.dbx_to_sprout_upload_btn, "Processing...")
        self._hide_aux_buttons()
        self._hide_statuses()
        self._emit_clicked("dbx_to_sprout_upload")

    def _on_attendance_summary_upload_btn_click(self):
        self._set_btn_processing(self.att_summary_upload_btn, "Processing...")
        self._hide_aux_buttons()
        self._hide_statuses()
        self._emit_clicked("att_summary_upload")

    # ===================================================================
    # STATUS UI STATE CHANGES
    # ===================================================================

    def _show_status(self, category, codes, statuses, button_statuses, upload_btn, height, payroll_files):
        """Render status labels and reveal aux buttons."""
        result_count = 0


        self._hide_statuses()

        for code in codes:

            # Parse incoming status code
            file_name, status_code = parse_status_code(code)

            # Resolve status message
            message_template = statuses.get(status_code, status_code)
            message = message_template.format(file_name=file_name or "")

            result_count += 1

            # Create status label
            stat = UIFactory.label(
                message,
                color="red" if "error" in status_code else "green",
                align="center",
                selectable=True
            )

            # Store and render status
            self.statuses[category][code] = stat
            stat.show()
            self._layout.addWidget(stat)

            # Reveal any aux buttons triggered by status
            if not category == "settings":
                self._show_aux_buttons_for(category, status_code)

            # Extra spacing for visible buttons
            if status_code in button_statuses:
                result_count += 2

        # Resize window to fit new content
        self._resize(530, height + ((result_count + payroll_files) * 10))

        # Restore upload button state
        if not category == "settings" and not status_code == "file_success":
            self._set_btn_default(upload_btn)

    # ===================================================================
    # PAYROLL UI STATE CHANGES
    # ===================================================================

    def show_payroll_status(self, codes):

        # Remove the shared processing progress widgets if they exist
        for attr in ("processing_status_label", "processing_percent_label", "processing_progress"):
            widget = getattr(self, attr, None)
            if widget is not None:
                self._layout.removeWidget(widget)
                widget.deleteLater()
                setattr(self, attr, None)

        self._show_status(
            category="payroll",
            codes=codes,
            statuses=PAYROLL_STATUSES,
            button_statuses={
                "new_headers_error",
                "file_success",
                "unmand_init_success",
                "unmand_status_pending_error",
                "unmand_status_success"
            },
            upload_btn=self.payroll_upload_btn,
            height=self.height['payroll'] + 15,
            payroll_files=self.required_files_len
        )

    # ===================================================================
    # CHECKER UI STATE CHANGES
    # ===================================================================

    def show_checker_status(self, codes):

        # Remove the shared processing progress widgets if they exist
        for attr in ("processing_status_label", "processing_percent_label", "processing_progress"):
            widget = getattr(self, attr, None)
            if widget is not None:
                self._layout.removeWidget(widget)
                widget.deleteLater()
                setattr(self, attr, None)

        self._show_status(
            category="checker",
            codes=codes,
            statuses=CHECKER_STATUSES,
            button_statuses={
                "validated_success"
            },
            upload_btn=self.checker_upload_btn,
            height=self.height['checker'],
            payroll_files=0
        )

    # ===================================================================
    # SETTINGS UI STATE CHANGES
    # ===================================================================

    def show_settings_add_user_status(self, codes):

        self._show_status(
            category="settings",
            codes=codes,
            statuses=SETTINGS_STATUSES,
            button_statuses={
                "settings_saved_success"
            },
            upload_btn=self.add_user_btn,
            height=self.height['settings'],
            payroll_files=0
        )

    def show_settings_save_deminimis_status(self, codes):

        self._show_status(
            category="settings",
            codes=codes,
            statuses=SETTINGS_STATUSES,
            button_statuses={
                "settings_saved_success"
            },
            upload_btn=self.save_deminimis_btn,
            height=self.height['settings'],
            payroll_files=0
        )

    # ===================================================================
    # ADITIONAL TOOLS UI STATE CHANGES
    # ===================================================================

    def show_dbx_to_sprout_status(self, codes):

        # Remove the shared processing progress widgets if they exist
        for attr in ("processing_status_label", "processing_percent_label", "processing_progress"):
            widget = getattr(self, attr, None)
            if widget is not None:
                self._layout.removeWidget(widget)
                widget.deleteLater()
                setattr(self, attr, None)

        self._show_status(
            category="checker",
            codes=codes,
            statuses=DBX_TO_SPROUT_STATUSES,
            button_statuses={
                "converted_success"
            },
            upload_btn=self.dbx_to_sprout_upload_btn,
            height=self.height['dbx_to_sprout'],
            payroll_files=0
        )

    def show_attendance_summary_status(self, codes):

        # Remove the shared processing progress widgets if they exist
        for attr in ("processing_status_label", "processing_percent_label", "processing_progress"):
            widget = getattr(self, attr, None)
            if widget is not None:
                self._layout.removeWidget(widget)
                widget.deleteLater()
                setattr(self, attr, None)

        self._show_status(
            category="checker",
            codes=codes,
            statuses=ATTENDANCE_SUMMARY,
            button_statuses={
                "summarized_success"
            },
            upload_btn=self.att_summary_upload_btn,
            height=self.height['att_summary'],
            payroll_files=0
        )

    # ===================================================================
    # PROCESSING PROGRESS BAR
    # ===================================================================

    def show_processing_progress(self, title: str = "Processing…", key: str = "payroll"):
        """
        Render a generic progress bar while a background worker runs.
        Replaces any previous progress widgets. Call show_*_status() to
        tear it down and show results.

        Parameters
        ----------
        title : str
            Short label shown above the progress bar (e.g. "Converting…").
        """
        self._hide_statuses()
        self._resize(530, self.height[key] + 100)

        self.processing_status_label = UIFactory.label(
            title,
            style_key="standard",
            align="center",
            word_wrap=True,
        )
        self._layout.addWidget(self.processing_status_label)

        self.processing_percent_label = UIFactory.label(
            "0%",
            style_key="header_label",
            align="center",
        )
        self._layout.addWidget(self.processing_percent_label)

        self.processing_progress = QProgressBar()
        self.processing_progress.setRange(0, 100)
        self.processing_progress.setValue(0)
        self.processing_progress.setTextVisible(False)
        self._layout.addWidget(self.processing_progress)

    def update_processing_progress(self, percent: int, message: str):
        """
        Update the shared processing progress bar and labels.
        Called from Orchestrator via the worker's progress signal.

        Parameters
        ----------
        percent : int   0–100
        message : str   Current stage label
        """
        if hasattr(self, "processing_progress") and self.processing_progress:
            self.processing_progress.setValue(percent)
        if hasattr(self, "processing_percent_label") and self.processing_percent_label:
            self.processing_percent_label.setText(f"{percent}%")
        if hasattr(self, "processing_status_label") and self.processing_status_label:
            self.processing_status_label.setText(message)

