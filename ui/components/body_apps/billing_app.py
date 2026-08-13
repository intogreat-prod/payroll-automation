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

Same composition pattern as PayrollBody: not a QWidget, holds a reference
to Body via `self.body` and borrows its layout/clear/resize/emit helpers.
"""

from PyQt6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout,
    QLabel, QFrame, QProgressBar, QHBoxLayout
)


from ui.styles import STYLES
from ui.statuses import BILLING_CHECKER_STATUSES, parse_status_code
from ui.ui_factory import UIFactory


class BillingBody:

    def __init__(self, body):
        self.body = body

        self.height = {
            "billing": 820,
            "checker": 770,
            "settings": 520,
        }

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
                ("Start Automation", lambda: self.body._emit_clicked("billing_feature"), "payroll_button" ),
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
                ("Start Automation", lambda: self.body._emit_clicked("billing_feature"), "payroll_button" ),
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
        Billing app's Tools menu. Nothing's scaffolded here yet, so the
        only option routes straight to show_coming_soon().
        """
        self.body._clear()
        self.body._resize(350, 400)

        tools_layout = QVBoxLayout()
        tools_layout.setSpacing(4)
        tools_layout.setContentsMargins(10, 10, 10, 10)
        tools_layout.addWidget(UIFactory.label("Select Tool:", font_size=12, font_weight='bold',
                                                    color='rgba(200, 200, 200, 1)', align='center'))

        col, layout = UIFactory.button_column(
            [
                ("Coming Soon", lambda: self.body._emit_clicked("billing_tools_tool"), "payroll_button"),
                ("◀ Back",       lambda: self.body._emit_clicked("back"),  "payroll_button"),
            ],
            spacing=12,
            parent=self.body,
            con_style_key=STYLES['body_clear']
        )

        layout.addStretch()
        tools_layout.addWidget(col)
        self.body._layout.addLayout(tools_layout)

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
                ("Client Billing Information", lambda: self.body._emit_clicked("client_billing_info"), "payroll_button"),
                ("Discounts and Maternity", lambda: self.body._emit_clicked("discounts"), "payroll_button"),
            ],
            spacing=8,
            margin=(0, 0, 0, 0),
            use_container=False,
        )

        automation_layout.addLayout(btn_row)
        content_layout.addWidget(automation_con)
        self.body._layout.addWidget(content)

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

    def update_processing_progress(self, percent: int, message: str):
        """Update the shared processing progress bar and labels."""
        if hasattr(self, "processing_progress") and self.processing_progress:
            self.processing_progress.setValue(percent)
        if hasattr(self, "processing_percent_label") and self.processing_percent_label:
            self.processing_percent_label.setText(f"{percent}%")
        if hasattr(self, "processing_status_label") and self.processing_status_label:
            self.processing_status_label.setText(message)