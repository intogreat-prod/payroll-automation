"""
styles.py
---------
All QSS stylesheet strings for the Payroll app in one place.
Import STYLES anywhere you need them.
"""

# ---------------------------------------------------------------------------
# REUSABLE TEMPLATE: dark glass button  (format with radius= and padding=)
# ---------------------------------------------------------------------------
_DARK_BTN = """
    QPushButton {{
        border-radius: {radius}px;
        padding: {padding}px;
        background-color: rgba(0, 0, 0, 0.75);
        color: white;
        font-weight: bold;
        border: 1px solid rgba(255, 255, 255, 0.9);
    }}
    QPushButton:hover {{
        background-color: rgba(255, 255, 255, 0.95);
        color: black;
    }}
    QPushButton:pressed {{
        background-color: rgba(255, 255, 255, 0.7);
        color: black;
    }}
"""

# ---------------------------------------------------------------------------
# REUSABLE TEMPLATE: white/gradient payroll button (format with radius= and padding=)
# ---------------------------------------------------------------------------
_PAYROLL_BTN = """
    QPushButton {{
        border-radius: {radius}px;
        padding: {padding}px;
        background-color: rgba(255, 255, 255, 0.95);
        border: 1px solid rgba(255, 255, 255, 1);
        color: black;
        font-weight: bold;
    }}
    QPushButton:hover {{
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 rgba(56, 144, 67, 0.7),
            stop:0.4 rgba(110, 206, 245, 0.7),
            stop:1 rgba(255, 255, 255, 0.6)
        );
        color: white;
    }}
    QPushButton:pressed {{
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 rgba(90, 180, 230, 0.9),
            stop:1 rgba(40, 120, 55, 0.9)
        );
        color: white;
    }}
"""

# ---------------------------------------------------------------------------
# EXPORTED STYLES DICT
# ---------------------------------------------------------------------------
STYLES = {

    # --- Buttons ---
    "button":          _DARK_BTN.format(radius=18, padding=12),
    "settings_button": _DARK_BTN.format(radius=15, padding=8),
    "gradient_button": _PAYROLL_BTN.format(radius=15, padding=8),
    "payroll_button":  _PAYROLL_BTN.format(radius=18, padding=12),

    # --- Input ---
    "input": """
        QLineEdit {
            font-size: 12px;
            color: #1C1C1C;
            padding: 5px 0 5px 8px;
            background: transparent;
            border: 1px solid black;
            border-radius: 12px;
        }
        QLineEdit::placeholder {
            color: #1C1C1C;
        }
    """,

    # --- Containers ---
    "main_container": """
        QWidget#container {
            background-color: rgba(255, 255, 255, 0.8);
            border-radius: 40px;
            border: 1px solid rgba(255, 255, 255, 1);
        }
    """,

    "body": """
        background: rgba(255, 255, 255, 80);
        border: 1px solid rgba(255, 255, 255, 220);
        border-radius: 20px;
    """,
    "body_clear": """
        background: transparent;
        border: none;
    """,

    "button_container": """
        QWidget {
            background-color: rgba(255, 255, 255, 0.6);
            border-radius: 25px;
            border: 1px solid rgba(255, 255, 255, 1);
        }
    """,

    "feature_content": """
        #featureContent {
            background: rgba(255, 255, 255, 100);
            border: 1px solid rgba(255, 255, 255, 220);
            border-radius: 20px;
        }
    """,

    # --- Status Labels ---
    "transparent_bg": """
            QLabel {
                border: none;
                background: transparent;
            }
        """,
        
    "success": """
        QLabel {
            font-size: 14px;
            color: green;
            background: transparent;
            border: none;
            qproperty-alignment: 'AlignCenter';
        }
    """,

    "failed": """
        QLabel {
            font-size: 14px;
            color: red;
            background: transparent;
            border: none;
            qproperty-alignment: 'AlignCenter';
        }
    """,

    # --- Standard Text --- 
    "header_label":"""
        QLabel {
            font-size: 16px;
            font-weight: bold;
            color: #1C1C1C;
            padding-bottom: 8px;
            background: transparent;
            border: none;
        }
    """,
    "standard": """
            QLabel {
                font-size: 14px;
                color: #222;
                padding: 4px;
                background: transparent;
                border: none;
            }
    """,

    "standard_red": """
        QLabel {
            font-size: 13px;
            color: red;
            padding: 4px;
            background: transparent;
            border: none;
        }
        """,

    # --- Input Styles ---
    "payroll_input": """
        QLineEdit {
            font-size: 14px;
            color: #1C1C1C;
            background: transparent;
            border: none;
            padding-left: 8px
        }
    """,

    # --- Scroll ---
    "settings_scroll": """
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
            }

            QScrollBar::handle:vertical {
                border-radius: 3px;
            }

            QScrollBar::handle:vertical:hover {
                background: #555;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }

            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """,

    # --- App card (MainWindow) ---
    "app_window": """
        QMainWindow {
            background: transparent;
        }
        #appCard {
            background: rgba(255, 255, 255, 180);
            border-radius: 40px;
            border: 1px solid rgba(255, 255, 255, 200);
        }
        QLabel {
            color: black;
            font-size: 16px;
        }
    """,
}
