"""
billing_body.py
----------------
Everything under the Billing app.

Billing Automation, its Checker, and Settings haven't been scaffolded out
yet, so all three route to show_coming_soon() below instead of trying to
render half-built screens. That placeholder mirrors the one already used
by Tools, so the whole app feels consistent instead of just Tools saying
"coming soon" while the others silently crash.

When Billing gets real features, replace the relevant show_coming_soon()
call in billing_orchestrator.py with a proper show_*_feature() screen
(mirroring PayrollBody), the same way PayrollBody's screens were built out.

Attendance Summary (formerly "Attendance Adjustment", formerly a Tool)
now lives under the Features menu instead of Tools — it no longer hands
off to Unmand, so it belongs alongside Billing Automation / Check
Variance rather than in the (currently empty) Tools menu.

Same composition pattern as PayrollBody: not a QWidget, holds a reference
to Body via `self.body` and borrows its layout/clear/resize/emit helpers.
"""

from PyQt6.QtWidgets import (
    QVBoxLayout, QFrame, QProgressBar, QHBoxLayout, QTabWidget, QWidget
)

from PyQt6.QtCore import QDate

from ui.styles import STYLES
from ui.statuses import parse_status_code, BILLING_STATUSES, BILLING_CHECKER_STATUSES, ATT_ADJ_STATUSES, INSIGHTFUL_STATUSES
from ui.ui_factory import UIFactory


class BillingBody:

    def __init__(self, body):
        self.body = body

        self.height = {
            "billing_input": 950,
            "billing_output": 850,
            "att_adj": 770,
            "insightful": 770,
            "checker": 770,
            "settings": 550,
        }

        # Set by show_billing_feature() so show_billing_status() can size
        # the window to fit the required-files list, mirroring PayrollBody.
        self.billing_required_files_len = 0

        # Set by show_attendance_summary_feature() so
        # show_attendance_adjustment_status() can size the window to fit
        # the required-files list.
        self.att_file_count = 0

    # ===================================================================
    # SCREEN 7 — BILLING MENU SELECTION
    # ===================================================================
    def show_menu(self):
        self.body._clear()
        self.body.setStyleSheet(STYLES["body_clear"])
        self.body._resize(350, 400)

        col, layout = UIFactory.button_column(
            [
                ("Billing Automation", lambda: self.body._emit_clicked("automation_menu"), "payroll_button"),
                ("Tools",              lambda: self.body._emit_clicked("tools_menu"),    "payroll_button"),
                ("Home",           lambda: self.body._emit_clicked("home"),  "payroll_button"),
            ],
            spacing=8,
            parent=self.body
        )

        layout.addStretch()
        self.body._layout.addWidget(col)

    # ===================================================================
    # SCREEN 8 — BILLING AUTOMATION FEATURE SELECTION
    # ===================================================================
    def show_automation_menu(self):
        self.body._clear()
        self.body._resize(350, 450)

        sources_layout = QVBoxLayout()
        sources_layout.setSpacing(4)
        sources_layout.setContentsMargins(10, 10, 10, 10)

        col, layout = UIFactory.button_column(
            [
                ("Start Automation", lambda: self.body._emit_clicked("billing_feature"), "payroll_button"),
                ("Check Variance", lambda: self.body._emit_clicked("checker_feature"), "payroll_button"),
                ("Settings", lambda: self.body._emit_clicked("settings_feature"), "payroll_button"),
                ("◀ Back", lambda: self.body._emit_clicked("back"), "payroll_button"),
            ],
            spacing=12,
            parent=self.body

        )

        layout.addStretch()
        sources_layout.addWidget(col)
        self.body._layout.addLayout(sources_layout)

    def _horizontal_automation_menu(self):
        self.body._layout.setSpacing(8)
        self.body.setStyleSheet(STYLES["body_clear"])

        col, layout = UIFactory.button_row(
            [
                ("Start Automation", lambda: self.body._emit_clicked("billing_feature"), "payroll_button"),
                ("Check Variance", lambda: self.body._emit_clicked("checker_feature"), "payroll_button"),
                ("Settings", lambda: self.body._emit_clicked("settings_feature"), "payroll_button"),
                ("◀ Back", lambda: self.body._emit_clicked("back"), "payroll_button"),
            ],
            width=110,
            height=35,
            parent=self.body
        )
        layout.addStretch()
        col.setStyleSheet(STYLES['body'])
        self.body._layout.addWidget(col)


    # ===================================================================
    # SCREEN 9 — TOOL SELECTION
    # ===================================================================
    def show_tools(self):
        """
        Billing app's Tools menu. Attendance Summary moved out to
        Features (it's a local-only generation flow now, not an
        Unmand hand-off tool) — nothing else is scaffolded here yet,
        so this is effectively a placeholder with just Back.
        """
        self.body._clear()
        self.body._resize(350, 440)

        tools_layout = QVBoxLayout()
        tools_layout.setSpacing(4)
        tools_layout.setContentsMargins(10, 10, 10, 10)
        tools_layout.addWidget(UIFactory.label("Select Tool:", font_size=12, font_weight='bold',
                                                    color='rgba(200, 200, 200, 1)', align='center'))

        col, layout = UIFactory.button_column(
            [
                ("Attendance Adjustment", lambda: self.body._emit_clicked("attendance_adjustment_tool"), "payroll_button"),
                ("Insightful", lambda: self.body._emit_clicked("insightful_tool"), "payroll_button"),
                ("◀ Back",       lambda: self.body._emit_clicked("back"),  "payroll_button"),
            ],
            spacing=12,
            parent=self.body,
            con_style_key=STYLES['body_clear']
        )

        layout.addStretch()
        tools_layout.addWidget(col)
        self.body._layout.addLayout(tools_layout)

    def _horizontal_menu_tools(self):
        self.body._layout.setSpacing(8)
        self.body.setStyleSheet(STYLES["body_clear"])

        col, layout = UIFactory.button_row(
            [
                ("Attendance Adjustment", lambda: self.body._emit_clicked("attendance_adjustment_tool"), "payroll_button"),
                ("◀ Back",       lambda: self.body._emit_clicked("back"),  "payroll_button"),
            ],
            spacing=12,
            parent=self.body,
            con_style_key=STYLES['body_clear']
        )
        layout.addStretch()
        col.setStyleSheet(STYLES['body'])
        self.body._layout.addWidget(col)

    # ===================================================================
    # SCREEN 10 — COMING SOON PLACEHOLDER
    # ===================================================================
    def show_coming_soon(self, title: str = "This feature"):
        """
        Shared placeholder for any Billing screen that hasn't been built
        out yet (Automation, Checker, Settings, Tools). Keeps the suite
        navigable instead of hitting a missing-method crash.
        """
        self.body._clear()
        self.body.setStyleSheet(STYLES["body_clear"])
        self.body._resize(350, 320)

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(16, 24, 16, 16)

        layout.addWidget(UIFactory.label(title, style_key="header_label", align="center"))
        layout.addWidget(UIFactory.label(
            "This is coming soon — we're still building this out. Check back shortly.",
            style_key="standard",
            align="center",
            word_wrap=True
        ))
        layout.addStretch()
        layout.addWidget(UIFactory.button(
            "◀ Back",
            lambda: self.body._emit_clicked("back"),
            "payroll_button"
        ))

        self.body._layout.addLayout(layout)

    # ===================================================================
    # SCREEN 11 — AUTOMATION SETTINGS
    # ===================================================================
    def show_settings_feature(self):
        self.body._clear()
        self._horizontal_automation_menu()
        self.body._layout.setContentsMargins(10, 10, 10, 10)
        self.body._resize(530, self.height['settings'])
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
        col, btn_row = UIFactory.button_column(
            [
                ("Client Billing Information", lambda: self.body._emit_clicked("client_billing_info_bill"), "payroll_button"),
                ("Discounts and Maternity", lambda: self.body._emit_clicked("discounts_bill"), "payroll_button"),
                ("Others", lambda: self.body._emit_clicked("others_bill"), "payroll_button"),

            ],
            spacing=8,
            margin=(0, 0, 0, 0),
            use_container=False,
        )

        automation_layout.addLayout(btn_row)
        content_layout.addWidget(automation_con)
        self.body._layout.addWidget(content)

    # ===================================================================
    # SCREEN 11.5 — START AUTOMATION (Billing Upload + Unmand)
    # Mirrors PayrollBody.show_payroll_feature().
    # ===================================================================
    def show_billing_feature(self, required_files):
        self.body._clear()
        self.billing_required_files_len = len(required_files)
        self._horizontal_automation_menu()

        self.body._layout.setContentsMargins(10, 10, 10, 10)
        self.body._resize(530, self.height['billing_input'] + (self.billing_required_files_len * 10))

        content = QFrame()
        content.setObjectName("featureContent")
        content.setStyleSheet(STYLES["feature_content"])
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(8)
        content_layout.setContentsMargins(10, 10, 10, 10)

        content_layout.addWidget(UIFactory.label("Billing Automation", color='white', font_weight="bold", font_size=17))
        content_layout.addWidget(
            UIFactory.label(
                "Validates all input files and submits them to Unmand for billing "
                "automation processing.\n\n"
                "Output: the automated billing result, available once Unmand "
                "finishes running.",
                font_size=11, color='white', word_wrap=True
            )
        )
        content_layout.addSpacing(6)

        # ── Billing Month ──────────────────────────────────────────────
        billing_month_con = QFrame()
        billing_month_con.setStyleSheet(STYLES["standard_container"])

        billing_month_layout = QVBoxLayout(billing_month_con)
        billing_month_layout.setContentsMargins(12, 12, 12, 12)
        billing_month_layout.setSpacing(6)

        billing_month_layout.addWidget(
            UIFactory.label("🗓️ Billing Month", color="white", font_weight="bold", font_size=15)
        )
        billing_month_layout.addWidget(
            UIFactory.label(
                "Select the billing month to consolidate bills.",
                color="white",
                font_size=11,
                padding_bottom=6,
            )
        )

        self.body.billing_month = UIFactory.month_picker(
            default_date=QDate.currentDate(),
            width=90,
            style_key='month_picker'
        )
        billing_month_layout.addWidget(self.body.billing_month)

        content_layout.addWidget(billing_month_con)
        content_layout.addSpacing(6)

        # ── Currencies ──────────────────────────────────────────────
        currencies_con = QFrame()
        currencies_con.setStyleSheet(STYLES["standard_container"])

        currencies_layout = QVBoxLayout(currencies_con)
        currencies_layout.setContentsMargins(12, 12, 12, 12)

        currencies_title = UIFactory.label("🪙 Currencies", color="white", font_weight="bold", font_size=15)
        currencies_layout.addWidget(currencies_title)

        currencies_desc = UIFactory.label(
            "Set the exchange rates to be used for billing conversion.",
            color="white",
            font_size=11,
            padding_bottom=6,
        )
        currencies_layout.addWidget(currencies_desc)

        currency_row = QHBoxLayout()
        currencies = ["AUD", "USD", "EUR"]

        for currency in currencies:
            currency_con = QVBoxLayout()
            currency_con.setSpacing(6)

            currency_label = UIFactory.label(
                f"{currency} to PHP",
                color="white",
                font_weight="bold",
                font_size=12,
                align="center"
            )

            currency_input = UIFactory.input("")

            currency_con.addWidget(currency_label)
            currency_con.addWidget(currency_input)

            currency_row.addLayout(currency_con, 1)

            currencies_layout.addLayout(currency_row)

        content_layout.addWidget(currencies_con)
        content_layout.addSpacing(6)

        # ── Tabs (Input / Output) ──────────────────────────────────────
        self.billing_tabs = QTabWidget()
        self.billing_tabs.setStyleSheet(STYLES["tab_widget"])

        # ── Input Tab ─────────────────────────────────────────────────
        input_tab = QWidget()
        input_layout = QVBoxLayout(input_tab)
        input_layout.setContentsMargins(12, 12, 12, 12)
        input_layout.setSpacing(8)

        input_layout.addWidget(UIFactory.label(
            "Upload the required Excel files below for billing processing.",
            style_key="standard",
            word_wrap=True
        ))

        required_con = QFrame()
        required_con.setStyleSheet(STYLES["standard_container"])

        required_layout = QVBoxLayout(required_con)
        required_layout.setContentsMargins(12, 12, 12, 12)
        required_layout.setSpacing(3)

        required_layout.addWidget(UIFactory.label("🗂️ Required Files", style_key="header_label"))

        columns = QHBoxLayout()
        columns.setSpacing(24)

        files_layout = QVBoxLayout()
        files_layout.setSpacing(1)
        for t in required_files:
            files_layout.addWidget(UIFactory.label(f"• {t}", font_size=11, color="rgba(200, 200, 200, 1)"))

        notes_layout = QVBoxLayout()
        notes_layout.setSpacing(4)
        notes_layout.addWidget(UIFactory.label(
            "Note:\n"
            "• Headers in Row 1; use Sheet 1.\n"
            "• File type must be .xlsx\n"
            "• Sensitivity should be set to Public\n"
            "• The file should not be password-protected.\n"
            "• If required, use INTOGREAT[YYYY].\n",
            style_key="standard_red",
            word_wrap=True,
            align="left"
        ))

        columns.addLayout(files_layout, 1)
        columns.addLayout(notes_layout, 1)
        required_layout.addLayout(columns)

        input_layout.addWidget(required_con)
        input_layout.addStretch()

        # ── Output Tab ────────────────────────────────────────────────
        output_tab = QWidget()
        output_layout = QVBoxLayout(output_tab)
        output_layout.setContentsMargins(12, 12, 12, 12)
        output_layout.setSpacing(8)

        output_layout.addWidget(UIFactory.label(
            "Once processed, the billing output file will appear here for review "
            "and can be sent to Unmand for further handling.",
            style_key="standard",
            word_wrap=True
        ))
        output_layout.addStretch()

        self.billing_tabs.addTab(input_tab, "Unmand Masterfile Creation")
        self.billing_tabs.addTab(output_tab, "Support File Creation")

        self.billing_tabs.currentChanged.connect(
            lambda _: self._on_billing_tabs_changed(self.billing_required_files_len)
        )

        content_layout.addWidget(self.billing_tabs)
        content_layout.addSpacing(6)

        # ── Buttons (fixed, outside tabs) ───────────────────────────────
        self.billing_upload_btn = UIFactory.button(
            "Upload",
            lambda: self._on_billing_upload_btn_click(id_input),
            "payroll_button"
        )
        content_layout.addWidget(self.billing_upload_btn)

        billing_unmand_btn = UIFactory.button(
            "Send to Unmand",
            lambda: self.body._emit_clicked("send_unmand"),
            "payroll_button"
        )
        content_layout.addWidget(billing_unmand_btn)
        self.body._register_aux_button("billing", "billing_unmand", billing_unmand_btn,
                                visible_on=["file_success"])

        check_unmand_btn = UIFactory.button(
            "Check Unmand Status",
            lambda: self.body._emit_clicked("check_status"),
            "payroll_button"
        )
        content_layout.addWidget(check_unmand_btn)
        self.body._register_aux_button("billing", "check_unmand_btn", check_unmand_btn,
                                visible_on=["unmand_init_success", "unmand_status_pending_error"])

        open_output_btn = UIFactory.button(
            "Open Output",
            lambda: self.body._emit_clicked("open_billing_output"),
            "payroll_button"
        )
        content_layout.addWidget(open_output_btn)
        self.body._register_aux_button("billing", "open_output_btn", open_output_btn,
                                visible_on=["unmand_status_success"])

        for key, status in BILLING_STATUSES.items():
            lbl = UIFactory.label(status, color="red" if "error" in key else "green", align="center")
            lbl.hide()
            content_layout.addWidget(lbl)

        content_layout.addStretch()

        self.body._layout.addWidget(content)

    def _billing_tabs_height(self, required_files):
        """Input has the required-files block, Output is just a description,
        so Input needs more vertical room."""
        is_output = getattr(self, "billing_tabs", None) and self.billing_tabs.currentIndex() == 1
        return self.height["billing_output"] if is_output else self.height["billing_input"] + (required_files * 10)

    def _on_billing_tabs_changed(self, required_files):
        self.body._resize(530, self._billing_tabs_height(required_files))

    def _on_billing_upload_btn_click(self, id_input):
        """Handle Upload button click: switch to processing state, then emit."""
        self.body._set_btn_processing(self.billing_upload_btn, "Processing...")
        self.body._hide_aux_buttons()
        self.body._hide_statuses()
        self.body._emit_clicked(["billing_upload", id_input.text().strip(), ""])

    def show_billing_status(self, codes):
        """Render status labels for the Billing Automation screen and reveal aux buttons."""
        # Remove the shared processing progress widgets if they exist
        self.body._main_window.stop_progress_heartbeat()
        for attr in ("processing_status_label", "processing_percent_label", "processing_progress"):
            widget = getattr(self, attr, None)
            if widget is not None:
                self.body._layout.removeWidget(widget)
                widget.deleteLater()
                setattr(self, attr, None)

        self.body._hide_statuses()
        result_count = 0
        status_code  = ""

        for code in codes:
            file_name, status_code = parse_status_code(code)
            message_template = BILLING_STATUSES.get(status_code, status_code)
            message = message_template.format(file_name=file_name or "")
            result_count += 1

            stat = UIFactory.label(
                message,
                color="red" if "error" in status_code else "green",
                align="center",
                selectable=True
            )
            self.body.statuses["billing"][code] = stat
            stat.show()
            self.body._layout.addWidget(stat)

            self.body._show_aux_buttons_for("billing", status_code)

            if status_code in {
                "file_success", "unmand_init_success",
                "unmand_status_pending_error", "unmand_status_success"
            }:
                result_count += 2

        self.body._resize(
            530,
            self.height['billing'] + 15 + ((result_count + self.billing_required_files_len) * 10)
        )

        if status_code != "file_success":
            self.body._set_btn_default(self.billing_upload_btn)

    # ===================================================================
    # SCREEN 12 — CHECK VARIANCE (Billing Checker)
    # ===================================================================
    def show_checker_feature(self):
        self.body._clear()
        self._horizontal_automation_menu()

        self.body._layout.setContentsMargins(10, 10, 10, 10)
        self.body._resize(530, self.height['checker'])

        content = QFrame()
        content.setObjectName("featureContent")
        content.setStyleSheet(STYLES["feature_content"])
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(8)
        content_layout.setContentsMargins(10, 10, 10, 10)

        content_layout.addWidget(UIFactory.label("Manual vs Unmand", color='white', font_weight="bold", font_size=17))
        content_layout.addWidget(
            UIFactory.label(
                "Compares the Manual Billing Checker against the Unmand Billing "
                "Checker row by row and flags every variance.\n\n"
                "Output:\n"
                "• A single Excel report listing each row's variance\n"
                "• Colour-coded the same way as the source checklist — "
                "green = matched, orange = 0 headcount, red = variance or error",
                font_size=11, color='white', word_wrap=True
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
        for t in ["Masterfile", "Unmand Pivot Summary"]:
            required_layout.addWidget(UIFactory.label("• " + t, style_key="standard"))

        required_layout.addSpacing(6)
        required_layout.addWidget(UIFactory.label(
            "Note:\n"
            "• Pivot Header must be in Row 1 and Masterfile in Row 4\n"
            "• File type must be .xlsx\n"
            "• Sensitivity must be set to Public.\n"
            "• File must not be password-protected.\n"
            "• Use INTOGREAT[YYYY] if required.\n"
            "• File name must contain 'Masterfile' or 'Pivot Summary'.\n",
            style_key="standard_red",
            word_wrap=True,
            align="left"
        ))
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
            lambda: self.body._emit_clicked("open_checker_output"),
            "payroll_button"
        )
        content_layout.addWidget(open_output_btn)

        self.body._register_aux_button("billing", "open_output_btn", open_output_btn,
                                    visible_on=["validated_success"])

        # Status labels
        for key, status in BILLING_CHECKER_STATUSES.items():
            lbl = UIFactory.label(status, color="red" if "error" in key else "green", align="center")
            lbl.hide()
            content_layout.addWidget(lbl)

        self.body._layout.addWidget(content)

    def _on_checker_upload_btn_click(self):
        """Handle Upload button click: switch to processing state, then emit."""
        self.body._set_btn_processing(self.checker_upload_btn, "Processing...")
        self.body._hide_aux_buttons()
        self.body._hide_statuses()
        self.body._emit_clicked("checker_upload")

    def show_checker_status(self, codes, summary: dict = None):
        """
        Render status labels for the Checker screen and reveal aux buttons.

        summary : dict, optional
            The result dict from BillingCheckerFeature.generate() —
            {file_path, total_clients, flagged_count, correct_clients,
            accuracy_pct, var_tolerance}. When provided alongside a
            "validated_success" code, an accuracy summary is rendered
            below the status labels.
        """

        # Remove the shared processing progress widgets if they exist
        for attr in ("processing_status_label", "processing_percent_label", "processing_progress"):
            widget = getattr(self, attr, None)
            if widget is not None:
                self.body._layout.removeWidget(widget)
                widget.deleteLater()
                setattr(self, attr, None)

        # Remove any previously-rendered accuracy summary before re-adding
        for attr in ("accuracy_label", "clients_label"):
            widget = getattr(self, attr, None)
            if widget is not None:
                self.body._layout.removeWidget(widget)
                widget.deleteLater()
                setattr(self, attr, None)

        self.body._hide_statuses()
        result_count = 0
        status_code = ""

        for code in codes:
            file_name, status_code = parse_status_code(code)
            message_template = BILLING_CHECKER_STATUSES.get(status_code, status_code)
            message = message_template.format(file_name=file_name or "")
            result_count += 1

            stat = UIFactory.label(
                message,
                color="red" if "error" in status_code else "green",
                align="center",
                selectable=True
            )
            self.body.statuses["billing"][code] = stat
            stat.show()
            self.body._layout.addWidget(stat)

            self.body._show_aux_buttons_for("billing", status_code)

            if status_code == "validated_success":
                result_count += 2

                if summary:
                    result_count += 2
                    self.accuracy_label = UIFactory.label(
                        f"Accuracy: {summary['accuracy_pct']}% "
                        f"(tolerance ± {summary['var_tolerance']} AUD)",
                        color="green" if summary['accuracy_pct'] >= 95 else "orange",
                        align="center",
                        selectable=True,
                    )
                    self.body._layout.addWidget(self.accuracy_label)

                    self.clients_label = UIFactory.label(
                        f"Clients matched: {summary['correct_clients']} / {summary['total_clients']}",
                        style_key="standard",
                        align="center",
                        selectable=True,
                    )
                    self.body._layout.addWidget(self.clients_label)

        self.body._resize(530, self.height['checker'] + (result_count * 10))

        if status_code != "file_success":
            self.body._set_btn_default(self.checker_upload_btn)

    # ===================================================================
    # SCREEN 13 — ATTENDANCE SUMMARY TOOL
    # ===================================================================
    def show_attendance_adjustment_tool(self, required_files):
        self.body._clear()
        self._horizontal_menu_tools()

        self.att_file_count = len(required_files)

        self.body._layout.setContentsMargins(10, 10, 10, 10)
        self.body._resize(530, self.height['att_adj'] + self.att_file_count * 10)

        content = QFrame()
        content.setObjectName("featureContent")
        content.setStyleSheet(STYLES["feature_content"])
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(8)
        content_layout.setContentsMargins(10, 10, 10, 10)

        content_layout.addWidget(UIFactory.label("Attendance Summary", color='white', font_weight="bold", font_size=17))
        content_layout.addWidget(
            UIFactory.label(
                "Pre-checks and formats the attendance and payroll files, computes \n"
                "the attendance adjustment, and generates the output locally.",
                font_size=11, color='white'
            )
        )
        content_layout.addSpacing(6)

        # ── Currencies ──────────────────────────────────────────────
        currencies_con = QFrame()
        currencies_con.setStyleSheet(STYLES["standard_container"])
        
        currencies_layout = QVBoxLayout(currencies_con)
        currencies_layout.setContentsMargins(12, 12, 12, 12)
        
        currencies_title = UIFactory.label("ℹ️ Details", color="white", font_weight="bold", font_size=15)
        currencies_layout.addWidget(currencies_title)
        
        currencies_desc = UIFactory.label(
            "Set the AUD to PHP exchange rate and the Month.",
            color="white",
            font_size=11,
            padding_bottom=6,
        )
        currencies_layout.addWidget(currencies_desc)
        
        currency_row = QHBoxLayout()

        currency_con = QVBoxLayout()
        currency_con.setSpacing(3)

        currency_label = UIFactory.label(
            "AUD to PHP",
            color="white",
            font_weight="bold",
            font_size=12,
            align="center"
        )

        self.exchange_rate_input = UIFactory.input("41.6698", align="center")

        currency_con.addWidget(currency_label)
        currency_con.addWidget(self.exchange_rate_input)

        month_con = QVBoxLayout()
        month_con.setSpacing(3)

        att_label = UIFactory.label(
            "Month",
            color="white",
            font_weight="bold",
            font_size=12,
            align="center"
        )

        self.attendance_month = UIFactory.month_picker(
                    default_date=QDate.currentDate(),
                    width=90,
                    style_key='month_picker'
                )

        month_con.addWidget(att_label)
        month_con.addWidget(self.attendance_month )

        rates_con = QVBoxLayout()
        rates_con.setSpacing(3)
        
        rates_label = UIFactory.label(
            "Rates",
            color="white",
            font_weight="bold",
            font_size=12,
            align="center"
        )
        
        rates_btn = UIFactory.button("Payroll Headers and Rates",
                                     lambda: self.body._emit_clicked("payroll_headers"),
                                     style_key="payroll_button")
        
        rates_con.addWidget(rates_label)
        rates_con.addWidget(rates_btn)

        
        currency_row.addLayout(month_con, 1)
        currency_row.addLayout(currency_con, 1)
        currency_row.addLayout(rates_con, 1)

        currencies_layout.addLayout(currency_row)
        
        content_layout.addWidget(currencies_con)
        content_layout.addSpacing(6)

        # ── Required ───────────────────────────────────────────────────────
        required_con = QFrame()
        required_con.setStyleSheet(STYLES["standard_container"])

        required_layout = QVBoxLayout(required_con)
        required_layout.setContentsMargins(12, 12, 12, 12)
        required_layout.setSpacing(3)

        required_layout.addWidget(UIFactory.label("🗂️ Required Files", style_key="header_label"))

        required_layout.addWidget(UIFactory.label(
                "Upload the required Excel files below to consolidate payroll registers.",
                style_key="standard",
                word_wrap=True
            ))

        columns = QHBoxLayout()
        columns.setSpacing(24)

        files_layout = QVBoxLayout()
        files_layout.setSpacing(1)
        for t in required_files:
            files_layout.addWidget(UIFactory.label(f"• {t}", font_size=11, color="rgba(200, 200, 200, 1)"))

        notes_layout = QVBoxLayout()
        notes_layout.setSpacing(4)
        notes_layout.addWidget(UIFactory.label(
            "Note:\n"
            "• Headers in Row 1; single sheet.\n"
            "• File type must be .xlsx\n"
            "• Sensitivity should be set to Public\n"
            "• The file should not be password-protected.\n"
            "• If required, use INTOGREAT[YYYY].\n",
            style_key="standard_red",
            word_wrap=True,
            align="left"
        ))

        columns.addLayout(files_layout, 30)
        columns.addLayout(notes_layout, 70)
        required_layout.addLayout(columns)

        content_layout.addWidget(required_con)
        content_layout.addStretch()

        # ── Action buttons ─────────────────────────────────────────────────
        self.att_adj_upload_btn = UIFactory.button(
            "Upload",
            lambda: self._on_att_adj_upload_btn_click(),
            "payroll_button"
        )
        content_layout.addWidget(self.att_adj_upload_btn)

        open_output_btn = UIFactory.button(
            "Open Output",
            lambda: self.body._emit_clicked("open_att_adj_output"),
            "payroll_button"
        )
        content_layout.addWidget(open_output_btn)

        self.body._register_aux_button("billing", "open_output_btn", open_output_btn,
                                    visible_on=["generated_success"])

        # Status labels
        for key, status in ATT_ADJ_STATUSES.items():
            lbl = UIFactory.label(status, color="red" if "error" in key else "green", align="center")
            lbl.hide()
            content_layout.addWidget(lbl)

        self.body._layout.addWidget(content)

    def _on_att_adj_upload_btn_click(self):
        """Handle Upload button click: switch to processing state, then emit."""
        self.body._set_btn_processing(self.att_adj_upload_btn, "Processing...")
        self.body._hide_aux_buttons()
        self.body._hide_statuses()
        self.body._emit_clicked("attendance_summary_upload")

    def show_attendance_adjustment_status(self, codes):
        """
        Render status labels for the Attendance Summary screen and
        reveal aux buttons. Mirrors show_billing_status() — this flow
        has a single terminal state ("generated_success") once local
        generation finishes.
        """
        # Remove the shared processing progress widgets if they exist
        self.body._main_window.stop_progress_heartbeat()
        for attr in ("processing_status_label", "processing_percent_label", "processing_progress"):
            widget = getattr(self, attr, None)
            if widget is not None:
                self.body._layout.removeWidget(widget)
                widget.deleteLater()
                setattr(self, attr, None)

        self.body._hide_statuses()
        result_count = 0
        status_code  = ""

        for code in codes:
            file_name, status_code = parse_status_code(code)
            message_template = ATT_ADJ_STATUSES.get(status_code, status_code)
            message = message_template.format(file_name=file_name or "")
            result_count += 1

            stat = UIFactory.label(
                message,
                color="red" if "error" in status_code else "green",
                align="center",
                selectable=True
            )
            self.body.statuses["billing"][code] = stat
            stat.show()
            self.body._layout.addWidget(stat)

            self.body._show_aux_buttons_for("billing", status_code)

        self.body._resize(530, self.height['att_adj'] + (self.att_file_count * 10) + (result_count * 10))

        if status_code != "file_success":
            self.body._set_btn_default(self.att_adj_upload_btn)

    # ===================================================================
    # SCREEN 14 — INSIGHTFUL TOOL
    # ===================================================================
    def show_insightful_tool(self, required_files):
        self.body._clear()
        self._horizontal_menu_tools()

        required_files_count = len(required_files)

        self.body._layout.setContentsMargins(10, 10, 10, 10)
        self.body._resize(530, self.height['insightful'] + (required_files_count * 10))

        content = QFrame()
        content.setObjectName("featureContent")
        content.setStyleSheet(STYLES["feature_content"])
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(8)
        content_layout.setContentsMargins(10, 10, 10, 10)

        content_layout.addWidget(UIFactory.label("Insightful", color='white', font_weight="bold", font_size=17))
        content_layout.addWidget(
            UIFactory.label(
                "Creates Insightful report for the billing automation and update the\n running Insightful tracker. \n",
                font_size=11, color='white'
            )
        )
        content_layout.addSpacing(2)

       # ── Insightful Tracker ─────────────────────────────────────
        insightful_con = QFrame()
        insightful_con.setStyleSheet(STYLES["standard_container"])

        insightful_layout = QVBoxLayout(insightful_con)
        insightful_layout.setContentsMargins(12, 12, 12, 12)
        insightful_layout.setSpacing(6)

        insightful_title = UIFactory.label(
            "Insightful Tracker",
            color="white",
            font_weight="bold",
            font_size=15
        )
        insightful_layout.addWidget(insightful_title)

        insightful_desc = UIFactory.label(
            "A continuously maintained file that tracks Insightful user access, \n"
            "based on the monthly file provided by IT.",
            color="white",
            font_size=11,
            padding_bottom=6,
        )
        insightful_layout.addWidget(insightful_desc)

        insightful_btn = UIFactory.button(
            "Insightful",
            lambda: self.body._emit_clicked("insightful_tracker"),
            style_key="payroll_button"
        )
        insightful_layout.addWidget(insightful_btn)

        content_layout.addWidget(insightful_con)
        content_layout.addSpacing(6)

        # ── Required ───────────────────────────────────────────────────────
        required_con = QFrame()
        required_con.setStyleSheet(STYLES["standard_container"])

        required_layout = QVBoxLayout(required_con)
        required_layout.setContentsMargins(12, 12, 12, 12)
        required_layout.setSpacing(3)

        required_layout.addWidget(UIFactory.label("🗂️ Required Files", style_key="header_label"))

        required_layout.addWidget(UIFactory.label(
                "Upload the required Excel files below to consolidate payroll registers.",
                style_key="standard",
                word_wrap=True
            ))

        columns = QHBoxLayout()
        columns.setSpacing(24)

        files_layout = QVBoxLayout()
        files_layout.setSpacing(1)
        for t in required_files:
            files_layout.addWidget(UIFactory.label(f"• {t}", font_size=11, color="rgba(200, 200, 200, 1)"))

        notes_layout = QVBoxLayout()
        notes_layout.setSpacing(4)
        notes_layout.addWidget(UIFactory.label(
            "Note:\n"
            "• Headers in Row 1; single sheet.\n"
            "• File type must be .xlsx\n"
            "• Sensitivity should be set to Public\n"
            "• The file should not be password-protected.\n"
            "• If required, use INTOGREAT[YYYY].\n",
            style_key="standard_red",
            word_wrap=True,
            align="left"
        ))

        columns.addLayout(files_layout, 30)
        columns.addLayout(notes_layout, 70)
        required_layout.addLayout(columns)

        content_layout.addWidget(required_con)
        content_layout.addStretch()

        # ── Action buttons ─────────────────────────────────────────────────
        self.insightful_upload_btn = UIFactory.button(
            "Upload",
            lambda: self._on_insightful_upload_btn_click(),
            "payroll_button"
        )
        content_layout.addWidget(self.insightful_upload_btn)

        open_output_btn = UIFactory.button(
            "Open Output",
            lambda: self.body._emit_clicked("open_insightful_output"),
            "payroll_button"
        )
        content_layout.addWidget(open_output_btn)

        self.body._register_aux_button("billing", "open_output_btn", open_output_btn,
                                    visible_on=["generated_success"])

        # Status labels
        for key, status in INSIGHTFUL_STATUSES.items():
            lbl = UIFactory.label(status, color="red" if "error" in key else "green", align="center")
            lbl.hide()
            content_layout.addWidget(lbl)

        self.body._layout.addWidget(content)

    def _on_insightful_upload_btn_click(self):
        """Handle Upload button click: switch to processing state, then emit."""
        self.body._set_btn_processing(self.insightful_upload_btn, "Processing...")
        self.body._hide_aux_buttons()
        self.body._hide_statuses()
        self.body._emit_clicked("insightful_upload")

    def show_insightful_status(self, codes):
        """
        Render status labels for the Insightful screen and
        reveal aux buttons. Mirrors show_billing_status() — this flow
        has a single terminal state ("generated_success") once local
        generation finishes.
        """
        # Remove the shared processing progress widgets if they exist
        self.body._main_window.stop_progress_heartbeat()
        for attr in ("processing_status_label", "processing_percent_label", "processing_progress"):
            widget = getattr(self, attr, None)
            if widget is not None:
                self.body._layout.removeWidget(widget)
                widget.deleteLater()
                setattr(self, attr, None)

        self.body._hide_statuses()
        result_count = 0
        status_code  = ""

        for code in codes:
            file_name, status_code = parse_status_code(code)
            message_template = INSIGHTFUL_STATUSES.get(status_code, status_code)
            message = message_template.format(file_name=file_name or "")
            result_count += 1

            stat = UIFactory.label(
                message,
                color="red" if "error" in status_code else "green",
                align="center",
                selectable=True
            )
            self.body.statuses["billing"][code] = stat
            stat.show()
            self.body._layout.addWidget(stat)

            self.body._show_aux_buttons_for("billing", status_code)

        self.body._resize(530, self.height['insightful'] + (self.att_file_count * 10) + (result_count * 10))

        if status_code != "file_success":
            self.body._set_btn_default(self.insightful_upload_btn)

    # ===================================================================
    # PROCESSING PROGRESS BAR (Checker)
    # ===================================================================
    def show_processing_progress(self, title: str = "Processing…", key: str = "checker"):
        """
        Render a generic progress bar while the checker's background
        worker runs. Replaces any previous progress widgets. Call
        show_checker_status() to tear it down and show results.
        """
        self.body._hide_statuses()
        self.body._resize(530, self.height[key] + 80)

        self.processing_status_label = UIFactory.label(
            title, style_key="standard", align="center", word_wrap=True,
        )
        self.body._layout.addWidget(self.processing_status_label)

        self.processing_percent_label = UIFactory.label(
            "0%", style_key="header_label", align="center",
        )
        self.body._layout.addWidget(self.processing_percent_label)

        self.processing_progress = QProgressBar()
        self.processing_progress.setRange(0, 100)
        self.processing_progress.setValue(0)
        self.processing_progress.setFixedHeight(3)
        self.processing_progress.setStyleSheet(STYLES["progress_bar"])
        self.processing_progress.setTextVisible(False)
        self.body._layout.addWidget(self.processing_progress)
        self.body._main_window.start_progress_heartbeat()

    def update_processing_progress(self, percent: int, message: str):
        """Update the shared processing progress bar and labels."""
        if hasattr(self, "processing_progress") and self.processing_progress:
            self.body._animate_progress(self.processing_progress, percent, "_billing_processing,_progress_anim")
        if hasattr(self, "processing_percent_label") and self.processing_percent_label:
            self.processing_percent_label.setText(f"{percent}%")
        if hasattr(self, "processing_status_label") and self.processing_status_label:
            self.processing_status_label.setText(message)
