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
    QLineEdit, QScrollArea, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QProgressBar
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from ui.styles import STYLES
from ui.statuses import *
from ui.ui_factory import UIFactory
from ui.components.login_form import LoginForm
from utils.file_utils import resource_path


class Body(QWidget):

    def __init__(self):
        super().__init__()

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

    # ===================================================================
    # HELPERS
    # ===================================================================

    def _clear(self):
        """Remove every widget/layout from the root layout."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
                item.layout().deleteLater()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _resize(self, w, h):
        """Ask the parent MainWindow to resize itself."""
        from ui.main_window import MainWindow
        window = self.window()
        if isinstance(window, MainWindow):
            window.resize_to(w, h)

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
        self._resize(530, 600)
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
            "The installer will run in the background.\nThe app will close and restart automatically.",
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
    # SCREEN 5 — SOURCE SELECTION
    # ===================================================================

    def show_sources(self):
        self._clear()
        self._resize(350, 370)

        col, layout = UIFactory.button_column(
            [
                ("DarwinBox", lambda: self._emit_clicked("DarwinBox_source"), "payroll_button"),
                ("Sprout",    lambda: self._emit_clicked("Sprout_source"),    "payroll_button"),
            ],
            spacing=12
        )

        layout.addStretch()
        self._layout.addWidget(col)

    # ===================================================================
    # SCREEN 6 — FEATURE LIST
    # ===================================================================

    def show_features(self):
        self._clear()
        self._resize(350, 400)

        col, layout = UIFactory.button_column(
            [
                ("Payroll",  lambda: self._emit_clicked("payroll_feature"),  "payroll_button"),
                ("Checker",  lambda: self._emit_clicked("checker_feature"),  "button"),
                ("Settings", lambda: self._emit_clicked("settings_feature"), "button"),
            ]
        )

        layout.addStretch()
        self._layout.addWidget(col)

    # ===================================================================
    # SCREEN 7 — FEATURE VIEWS
    # ===================================================================

    def _horizontal_menu(self):
        self._layout.setSpacing(8)
        self.setStyleSheet(STYLES["body_clear"])

        col, layout = UIFactory.button_row(
            [
                ("Payroll",  lambda: self._emit_clicked("payroll_feature"),  "payroll_button"),
                ("Checker",  lambda: self._emit_clicked("checker_feature"),  "button"),
                ("Settings", lambda: self._emit_clicked("settings_feature"), "button"),
            ],
            width=150
        )
        layout.addStretch()
        col.setStyleSheet(STYLES['body'])
        self._layout.addWidget(col)

    def show_payroll_feature(self, required_files):
        self._clear()
        self._horizontal_menu()
        self.required_files_len = len(required_files)

        self._layout.setContentsMargins(10, 10, 10, 10)
        self._resize(530, 760 + (self.required_files_len * 10))

        content = QFrame()
        content.setObjectName("featureContent")
        content.setStyleSheet(STYLES["feature_content"])

        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(3)
        content_layout.setContentsMargins(10, 10, 10, 10)

        # Header
        content_layout.addWidget(UIFactory.label("Required Files:", style_key="header_label"))

        # File list
        for t in required_files:
            content_layout.addWidget(UIFactory.label("• " + t, style_key="standard"))

        # Inputs
        id_input      = UIFactory.input("Enter ID (e.g., 20260422_071827)")
        version_input = UIFactory.input("Enter version number (e.g., v1, v2)")
        content_layout.addWidget(id_input)
        content_layout.addWidget(version_input)

        # Notes
        content_layout.addWidget(UIFactory.label(
            """Note:
            • Headers in Row 1; use Sheet 1.
            • File type must be .xlsx
            • Sensitivity should be set to Public
            • The file should not be password-protected.
            • If required, please use INTOGREAT[YYYY].""",
            style_key="standard_red",
            word_wrap=True,
            align="left"
        ))

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

    def show_checker_feature(self):
        self._clear()
        self._horizontal_menu()

        self._layout.setContentsMargins(10, 10, 10, 10)
        self._resize(530, 620)

        content = QFrame()
        content.setObjectName("featureContent")
        content.setStyleSheet(STYLES["feature_content"])

        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(3)
        content_layout.setContentsMargins(10, 10, 10, 10)

        content_layout.addWidget(UIFactory.label("Required Files:", style_key="header_label"))

        for t in ["Manual Checker", "Unmand Checker"]:
            content_layout.addWidget(UIFactory.label("• " + t, style_key="standard"))

        content_layout.addWidget(UIFactory.label(
            """Note:
            • Headers in Row 1; use Sheet 1.
            • File type must be .xlsx
            • Sensitivity should be set to Public
            • The file should not be password-protected.
            • If required, use INTOGREAT[YYYY].
            • Total should be at the end of every file.""",
            style_key="standard_red",
            word_wrap=True,
            align="left"
        ))

        content_layout.addStretch()

        # Primary upload button
        self.checker_upload_btn = UIFactory.button(
            "Upload",
            lambda: self._on_checker_upload_btn_click(),
            "payroll_button"
        )
        content_layout.addWidget(self.checker_upload_btn)

        # Aux buttons with dynamic visibility
        validate_btn = UIFactory.button(
            "Validate Checker",
            lambda: self._emit_clicked("validate_checker"),
            "payroll_button"
        )
        content_layout.addWidget(validate_btn)
        self._register_aux_button("checker", "validate_btn", validate_btn,
                                  visible_on=["file_success"])

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

    def show_settings_feature(self, users, deminimis):
        self._clear()
        self._horizontal_menu()

        self._layout.setContentsMargins(10, 10, 10, 10)
        self._resize(530, 880)

        content = QFrame()
        content.setObjectName("featureContent")
        content.setStyleSheet(STYLES["feature_content"])

        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(5)
        content_layout.setContentsMargins(10, 10, 10, 10)

        content_layout.addWidget(UIFactory.button(
            "Payroll Headers",
            lambda: self._emit_clicked("payroll_headers"),
            "payroll_button"
        ))

        content_layout.addWidget(UIFactory.button(
            "Night Differential List",
            lambda: self._emit_clicked("nd_list"),
            "payroll_button"
        ))

        content_layout.addWidget(UIFactory.label(
            "Note: Refresh app after updating Payroll Headers or ND List.",
            style_key="standard_red",
            word_wrap=True,
            align="left"
        ))

        content_layout.addWidget(UIFactory.label("Deminimis", style_key="header_label"))

        self.deminimis_inputs = {}
        for detail, val in deminimis.items():
            inp = UIFactory.input("")
            inp.setPlaceholderText(f"{detail}: {val}")
            inp.setFixedHeight(20)
            self.deminimis_inputs[detail] = inp
            content_layout.addWidget(inp)

        self.save_deminimis_btn = UIFactory.button(
            "Save",
            lambda: self._on_save_deminimis_clicked(
                {
                    detail: inp.text().strip()
                    for detail, inp in self.deminimis_inputs.items()
                }
            ),
            "payroll_button"
        )
        content_layout.addWidget(self.save_deminimis_btn)

        content_layout.addWidget(UIFactory.label("Users", style_key="header_label"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(120)
        scroll.setStyleSheet(STYLES['settings_scroll'])

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(10, 10, 10, 10)
        scroll_layout.setSpacing(5)

        if users:
            for u in users:
                scroll_layout.addWidget(UIFactory.label(u, style_key="standard"))
        else:
            scroll_layout.addWidget(UIFactory.label("No users found.", style_key="standard_red"))

        scroll.setWidget(scroll_content)
        content_layout.addWidget(scroll)

        self.add_user_input = UIFactory.input("Add a user (e.g., jdelacruz@intogreatsolutions.com)")
        content_layout.addWidget(self.add_user_input)

        self.add_user_btn = UIFactory.button(
            "Add User",
            lambda: self._on_add_user_clicked(self.add_user_input.text().strip()),
            "payroll_button"
        )
        content_layout.addWidget(self.add_user_btn )

        for key, status in SETTINGS_STATUSES.items():
            lbl = UIFactory.label(status, color="red" if "error" in key else "green", align="center")
            lbl.hide()
            content_layout.addWidget(lbl)

        self._layout.addWidget(content)


    # ===================================================================
    # FEATURES ON CLICK
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
        if not category == "settings":
            self._set_btn_default(upload_btn)

    # ===================================================================
    # PAYROLL UI STATE CHANGES
    # ===================================================================

    def show_payroll_status(self, codes):

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
            height=760,
            payroll_files=self.required_files_len
        )

    # ===================================================================
    # CHECKER UI STATE CHANGES
    # ===================================================================

    def show_checker_status(self, codes):

        self._show_status(
            category="checker",
            codes=codes,
            statuses=CHECKER_STATUSES,
            button_statuses={
                "validated_success"
            },
            upload_btn=self.checker_upload_btn,
            height=620,
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
            height=880,
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
            height=880,
            payroll_files=0
        )
