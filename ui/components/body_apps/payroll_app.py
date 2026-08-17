"""
payroll_body.py
----------------
Everything under the Payroll app: Payroll Automation, Tools, and Settings,
plus their child screens (source selection, automation views, status/progress
states).

This is NOT a QWidget. It's a plain class composed onto Body — it borrows
Body's root layout, resize/clear helpers, and aux-button/status registries
via `self.body`, the same way the methods behaved when they lived directly
on Body. Orchestrator never talks to this class directly; it only ever
calls `self.body.show_menu()` etc., and Body delegates here.

Widgets created by a screen and referenced only by other Payroll screens
(upload buttons, deminimis inputs, status labels, ...) live on `self`.
`start_date` / `cutoff` are the one exception — Orchestrator reads them
directly as `self.body.start_date` / `self.body.cutoff`, so they're stored
on Body instead of here.
"""

from PyQt6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout,
    QLabel, QFrame, QProgressBar, QHBoxLayout
)
from PyQt6.QtCore import Qt, QDate

from ui.styles import STYLES
from ui.statuses import *
from ui.ui_factory import UIFactory


class PayrollBody:

    def __init__(self, body):
        self.body = body

        self.height = {
            "payroll": 820,
            "checker": 770,
            "settings": 650,
            "dbx_to_sprout": 730,
            "att_summary": 830
        }

    # ===================================================================
    # SCREEN 6 — PAYROLL MENU SELECTION
    # ===================================================================
    def show_menu(self):
        self.body._clear()
        self.body.setStyleSheet(STYLES["body_clear"])
        self.body._resize(350, 400)

        col, layout = UIFactory.button_column(
            [
                ("Payroll Automation", lambda: self.body._emit_clicked("automation_menu"), "payroll_button"),
                ("Tools",              lambda: self.body._emit_clicked("tools_menu"),    "payroll_button"),
                ("Home",           lambda: self.body._emit_clicked("home"),  "payroll_button"),
            ],
            spacing=12,
            parent=self.body
        )

        layout.addStretch()
        self.body._layout.addWidget(col)

    # ===================================================================
    # SCREEN 6 — SOURCE SELECTION
    # ===================================================================
    def show_sources(self):
        self.body._clear()
        self.body._resize(350, 500)

        sources_layout = QVBoxLayout()
        sources_layout.setSpacing(4)
        sources_layout.setContentsMargins(10, 10, 10, 10)
        sources_layout.addWidget(UIFactory.label("Select Source:", font_size=12, font_weight='bold', 
                                                 color='rgba(200, 200, 200, 1)', align='center'))

        col, layout = UIFactory.button_column(
            [
                ("", lambda: self.body._emit_clicked("DarwinBox_source"), "payroll_button", ("assets/darwinbox.png", 100, 50)),
                ("", lambda: self.body._emit_clicked("Sprout_source"), "payroll_button", ("assets/sprout.png", 80, 40)),
                ("Settings", lambda: self.body._emit_clicked("settings_feature"), "payroll_button"),
                ("◀ Back", lambda: self.body._emit_clicked("back"), "payroll_button"),
            ],
            spacing=12,
            parent=self.body

        )

        layout.addStretch()
        sources_layout.addWidget(col)
        self.body._layout.addLayout(sources_layout)

    def _horizontal_sources(self):
        self.body._layout.setSpacing(8)
        self.body.setStyleSheet(STYLES["body_clear"])

        col, layout = UIFactory.button_row(
            [
                ("", lambda: self.body._emit_clicked("DarwinBox_source"), "payroll_button", ("assets/darwinbox.png", 90, 40)),
                ("", lambda: self.body._emit_clicked("Sprout_source"), "payroll_button", ("assets/sprout.png", 80, 30)),
                ("Settings", lambda: self.body._emit_clicked("settings_feature"), "payroll_button"),
                ("◀ Back", lambda: self.body._emit_clicked("back"), "payroll_button"),
            ],
            width=105,
            height=30,
            parent=self.body
        )
        col.setStyleSheet(STYLES['body'])
        self.body._layout.addWidget(col)
    # ===================================================================
    # SCREEN 7 — AUTOMATION FEATURE LIST
    # ===================================================================
    def show_darwin_features(self):
        self.body._clear()
        #self.body.setStyleSheet(STYLES["body_clear"])
        self.body._resize(350, 490)

        darwin_feat_layout = QVBoxLayout()
        darwin_feat_layout.setSpacing(4)
        darwin_feat_layout.setContentsMargins(10, 20, 10, 10)
        darwin_feat_layout.addWidget(UIFactory.image("assets/darwinbox.png", 150, 150))
        darwin_feat_layout.addSpacing(3)

        col, layout = UIFactory.button_column(
            [
                ("Payroll",  lambda: self.body._emit_clicked("payroll_feature"),  "payroll_button"),
                ("Checker",  lambda: self.body._emit_clicked("checker_feature"),  "button"),
                ("◀ Back",     lambda: self.body._emit_clicked("back"), "button"),
            ],
            parent=self.body

        )

        layout.addStretch()
        darwin_feat_layout.addWidget(col)
        self.body._layout.addLayout(darwin_feat_layout)

    def _horizontal_menu_darwin_features(self):
        self.body._layout.setSpacing(8)
        self.body.setStyleSheet(STYLES["body_clear"])

        col, layout = UIFactory.button_row(
            [
                ("Payroll",  lambda: self.body._emit_clicked("payroll_feature"),  "payroll_button"),
                ("Checker",  lambda: self.body._emit_clicked("checker_feature"),  "button"),
                ("◀ Back",     lambda: self.body._emit_clicked("back"), "button"),
            ],
            width=120,
            parent=self.body
        )
        layout.addWidget(UIFactory.image("assets/darwinbox_icon.png", 30, 30))
        col.setStyleSheet(STYLES['body'])
        self.body._layout.addWidget(col)

    def show_sprout_features(self):
        self.body._clear()
        self.body._resize(350, 470)

        sprout_feat_layout = QVBoxLayout()
        sprout_feat_layout.setSpacing(4)
        sprout_feat_layout.setContentsMargins(10, 20, 10, 10)
        sprout_feat_layout.addWidget(UIFactory.image("assets/sprout.png", 120, 120))
        sprout_feat_layout.addSpacing(3)


        col, layout = UIFactory.button_column(
            [
                ("Payroll",  lambda: self.body._emit_clicked("payroll_feature"),  "payroll_button"),
                ("Checker",  lambda: self.body._emit_clicked("checker_feature"),  "button"),
                ("◀ Back",     lambda: self.body._emit_clicked("back"), "button"),
            ],
            parent=self.body

        )

        layout.addStretch()
        sprout_feat_layout.addWidget(col)
        self.body._layout.addLayout(sprout_feat_layout)

    def _horizontal_menu_sprout_features(self):
        self.body._layout.setSpacing(8)
        self.body.setStyleSheet(STYLES["body_clear"])

        col, layout = UIFactory.button_row(
            [
                ("Payroll",  lambda: self.body._emit_clicked("payroll_feature"),  "payroll_button"),
                ("Checker",  lambda: self.body._emit_clicked("checker_feature"),  "button"),
                ("◀ Back",     lambda: self.body._emit_clicked("back"), "button"),
            ],
            width=120,
            parent=self.body
        )
        layout.addWidget(UIFactory.image("assets/sprout_icon.png", 30, 30))
        col.setStyleSheet(STYLES['body'])
        self.body._layout.addWidget(col)

    # ===================================================================
    # SCREEN 8 — TOOL SELECTION
    # ===================================================================
    def show_tools(self):
        self.body._clear()
        self.body._resize(350, 450)

        tools_layout = QVBoxLayout()
        tools_layout.setSpacing(4)
        tools_layout.setContentsMargins(10, 10, 10, 10)
        tools_layout.addWidget(UIFactory.label("Select Tool:", font_size=12, font_weight='bold', 
                                                 color='rgba(200, 200, 200, 1)', align='center'))

        col, layout = UIFactory.button_column(
            [
                ("DarwinBox to Sprout", lambda: self.body._emit_clicked("dbx_to_sprout_tool"), "payroll_button"),
                ("Attendance Summary",   lambda: self.body._emit_clicked("attendance_summary_tool"),    "payroll_button"),
                ("◀ Back",                lambda: self.body._emit_clicked("back"),  "payroll_button"),
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
                ("DarwinBox to Sprout", lambda: self.body._emit_clicked("dbx_to_sprout_tool"), "payroll_button"),
                ("Attendance Summary",   lambda: self.body._emit_clicked("attendance_summary_tool"),    "payroll_button"),
                ("◀ Back",                lambda: self.body._emit_clicked("back"),  "payroll_button"),
            ],
            width=150,
            parent=self.body
        )
        layout.addStretch()
        col.setStyleSheet(STYLES['body'])
        self.body._layout.addWidget(col)

    # ===================================================================
    # SCREEN 9 — SETTINGS
    # ===================================================================
    def show_settings(self, deminimis):
        self.body._clear()
        self._horizontal_sources()
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
        _, btn_row = UIFactory.button_row(
            [
                ("Payroll Headers",         lambda: self.body._emit_clicked("payroll_headers"), "settings_button"),
                ("Night Differential List", lambda: self.body._emit_clicked("nd_list"),         "settings_button"),
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

        self.payroll_settings_status = UIFactory.label("status", align="center")
        self.payroll_settings_status.hide()
        content_layout.addWidget(self.payroll_settings_status)
        self.body._layout.addWidget(content)

    def show_settings_save_deminimis_status(self, code):
        self.body._resize(530, self.height["settings"] + 10)
        self.payroll_settings_status.setText(PAYROLL_STATUSES[code])
        self.payroll_settings_status.setStyleSheet(
                f"color: {'#16A34A' if 'success' in code else '#DC2626'};"
                "font-size: 10px;"
            )
        self.payroll_settings_status.show()
        
    # ===================================================================
    # SCREEN 10 — FEATURE VIEWS
    # ===================================================================
    def show_payroll_feature(self, required_files, source):
        self.body._clear()
        self.required_files_len = len(required_files)

        if "DarwinBox" in source:
            self._horizontal_menu_darwin_features()
        else:
            self._horizontal_menu_sprout_features()

        self.body._layout.setContentsMargins(10, 10, 10, 10)
        self.body._resize(530, self.height['payroll'] + (self.required_files_len * 10))

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
            lambda: self.body._emit_clicked("send_unmand"),
            "payroll_button"
        )
        content_layout.addWidget(payroll_unmand_btn)
        self.body._register_aux_button("payroll", "payroll_unmand", payroll_unmand_btn,
                                  visible_on=["file_success"])

        open_new_btn = UIFactory.button(
            "Open new headers",
            lambda: self.body._emit_clicked("open_new_headers"),
            "payroll_button"
        )
        content_layout.addWidget(open_new_btn)
        self.body._register_aux_button("payroll", "open_new_btn", open_new_btn,
                                  visible_on=["new_headers_error"])

        check_unmand_btn = UIFactory.button(
            "Check Unmand Status",
            lambda: self.body._emit_clicked("check_status"),
            "payroll_button"
        )
        content_layout.addWidget(check_unmand_btn)
        self.body._register_aux_button("payroll", "check_unmand_btn", check_unmand_btn,
                                  visible_on=["unmand_init_success", "unmand_status_pending_error"])

        open_output_btn = UIFactory.button(
            "Open Output",
            lambda: self.body._emit_clicked("open_payroll_ouput"),
            "payroll_button"
        )
        content_layout.addWidget(open_output_btn)
        self.body._register_aux_button("payroll", "open_output_btn", open_output_btn,
                                  visible_on=["unmand_status_success"])

        self.body._layout.addWidget(content)

    def show_checker_feature(self, source):
        self.body._clear()

        if "DarwinBox" in source:
            self._horizontal_menu_darwin_features()
        else:
            self._horizontal_menu_sprout_features()

        self.body._layout.setContentsMargins(10, 10, 10, 10)
        self.body._resize(530, self.height['checker'])

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
            lambda: self.body._emit_clicked("open_checker_output"),
            "payroll_button"
        )
        content_layout.addWidget(open_output_btn)

        self.body._register_aux_button("payroll", "open_output_btn", open_output_btn,
                                    visible_on=["validated_success"])
        
        # Status labels
        for key, status in CHECKER_STATUSES.items():
            lbl = UIFactory.label(status, color="red" if "error" in key else "green", align="center")
            lbl.hide()
            content_layout.addWidget(lbl)

        self.body._layout.addWidget(content)

    # ===================================================================
    # SCREEN 11 — TOOLS
    # ===================================================================
    def show_dbx_to_sprout_tool(self):
        self.body._clear()
        self._horizontal_menu_tools()

        self.body._layout.setContentsMargins(10, 10, 10, 10)
        self.body._resize(530, self.height['dbx_to_sprout'])
        
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
            lambda: self.body._emit_clicked("open_dbx_to_sprout_output"),
            "payroll_button"
        )
        content_layout.addWidget(open_output_btn)

        self.body._register_aux_button("payroll", "open_output_btn", open_output_btn,
                                    visible_on=["converted_success"])
        
        # Status labels
        for key, status in DBX_TO_SPROUT_STATUSES.items():
            lbl = UIFactory.label(status, color="red" if "error" in key else "green", align="center")
            lbl.hide()
            content_layout.addWidget(lbl)

        self.body._layout.addWidget(content)

    def show_attendance_summary_tool(self):
        self.body._clear()
        self._horizontal_menu_tools()
        self.body._layout.setContentsMargins(10, 10, 10, 10)

        self.body._resize(530, self.height['att_summary'])
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
        self.body.start_date = UIFactory.date_picker(
            default_date=QDate.currentDate(),
            width=90,
            style_key='date_picker'
        )
        start_layout.addWidget(self.body.start_date)
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
        self.body.cutoff = UIFactory.date_picker(
            default_date=QDate.currentDate(),
            width=90,
            style_key='date_picker'
        )

        cutoff_layout.addWidget(self.body.cutoff)
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
            lambda: self.body._emit_clicked("open_att_summary_output"),
            "payroll_button"
        )
        content_layout.addWidget(open_output_btn)

        self.body._register_aux_button("payroll", "open_output_btn", open_output_btn,
                                    visible_on=["summarized_success"])
        
        # Status labels
        for key, status in ATTENDANCE_SUMMARY.items():
            lbl = UIFactory.label(status, color="red" if "error" in key else "green", align="center")
            lbl.hide()
            content_layout.addWidget(lbl)

        self.body._layout.addWidget(content)
    # ===================================================================
    # ACTIONS ON CLICK
    # ===================================================================
    
    def _on_payroll_upload_btn_click(self, id_input, version_input):
        """Handle Upload button click: switch to processing state, then emit."""
        self.body._set_btn_processing(self.payroll_upload_btn, "Processing...")
        self.body._hide_aux_buttons()
        self.body._hide_statuses()
        self.body._emit_clicked(["payroll_upload", id_input.text().strip(), version_input.text().strip()])

    def _on_checker_upload_btn_click(self):
        self.body._set_btn_processing(self.checker_upload_btn, "Processing...")
        self.body._hide_aux_buttons()
        self.body._hide_statuses()
        self.body._emit_clicked("checker_upload")

    def _on_save_deminimis_clicked(self, deminimis):
        self.body._hide_aux_buttons()
        self.body._hide_statuses()
        self.body._emit_clicked(['save_deminimis', deminimis])

    def _on_dbx_to_sprout_upload_btn_click(self):
        self.body._set_btn_processing(self.dbx_to_sprout_upload_btn, "Processing...")
        self.body._hide_aux_buttons()
        self.body._hide_statuses()
        self.body._emit_clicked("dbx_to_sprout_upload")

    def _on_attendance_summary_upload_btn_click(self):
        self.body._set_btn_processing(self.att_summary_upload_btn, "Processing...")
        self.body._hide_aux_buttons()
        self.body._hide_statuses()
        self.body._emit_clicked("att_summary_upload")

    # ===================================================================
    # STATUS UI STATE CHANGES
    # ===================================================================

    def _show_status(self, category, codes, statuses, button_statuses, upload_btn, height, payroll_files):
        """Render status labels and reveal aux buttons."""
        result_count = 0


        self.body._hide_statuses()

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
            self.body.statuses["payroll"][code] = stat
            stat.show()
            self.body._layout.addWidget(stat)

            # Reveal any aux buttons triggered by status
            if not category == "settings":
                self.body._show_aux_buttons_for("payroll", status_code)

            # Extra spacing for visible buttons
            if status_code in button_statuses:
                result_count += 2

        # Resize window to fit new content
        self.body._resize(530, height + ((result_count + payroll_files) * 10))

        # Restore upload button state
        if not category == "settings" and not status_code == "file_success":
            self.body._set_btn_default(upload_btn)

    # ===================================================================
    # PAYROLL UI STATE CHANGES
    # ===================================================================

    def show_payroll_status(self, codes):

        # Remove the shared processing progress widgets if they exist
        self.body._main_window.stop_progress_heartbeat()
        for attr in ("processing_status_label", "processing_percent_label", "processing_progress"):
            widget = getattr(self, attr, None)
            if widget is not None:
                self.body._layout.removeWidget(widget)
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
                self.body._layout.removeWidget(widget)
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
    # ADITIONAL TOOLS UI STATE CHANGES
    # ===================================================================

    def show_dbx_to_sprout_status(self, codes):

        # Remove the shared processing progress widgets if they exist
        for attr in ("processing_status_label", "processing_percent_label", "processing_progress"):
            widget = getattr(self, attr, None)
            if widget is not None:
                self.body._layout.removeWidget(widget)
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
                self.body._layout.removeWidget(widget)
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
        self.body._hide_statuses()
        self.body._resize(530, self.height[key] + 80)

        self.processing_status_label = UIFactory.label(
            title,
            style_key="standard",
            align="center",
            word_wrap=True,
        )
        self.body._layout.addWidget(self.processing_status_label)

        self.processing_percent_label = UIFactory.label(
            "0%",
            style_key="header_label",
            align="center",
        )
        self.body._layout.addWidget(self.processing_percent_label)

        self.processing_progress = QProgressBar()
        self.processing_progress.setRange(0, 100)
        self.processing_progress.setValue(0)
        self.processing_progress.setFixedHeight(3)
        self.processing_progress.setStyleSheet(STYLES["progress_bar"])
        self.processing_progress.setTextVisible(False)
        self.body._layout.addWidget(self.processing_progress)
        self.body._main_window.start_progress()

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
            self.body._animate_progress(self.processing_progress, percent, "_payroll_processing_progress_anim")
        if hasattr(self, "processing_percent_label") and self.processing_percent_label:
            self.processing_percent_label.setText(f"{percent}%")
        if hasattr(self, "processing_status_label") and self.processing_status_label:
            self.processing_status_label.setText(message)

