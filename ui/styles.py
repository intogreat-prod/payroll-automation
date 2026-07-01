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
       background-color: rgba(255, 255, 255, 0.08);
       color: rgba(220, 220, 220, 1);
       font-weight: bold;
       border: 1px solid rgba(255, 255, 255, 0.2);
   }}
   QPushButton:hover {{
       background-color: rgba(255, 255, 255, 0.18);
       color: white;
       border: 1px solid rgba(255, 255, 255, 0.45);
   }}
   QPushButton:pressed {{
       background-color: rgba(255, 255, 255, 0.08);
       color: rgba(200, 200, 200, 1);
   }}
"""
# ---------------------------------------------------------------------------
# REUSABLE TEMPLATE: accent/gradient payroll button (format with radius= and padding=)
# ---------------------------------------------------------------------------
_PAYROLL_BTN = """
   QPushButton {{
       border-radius: {radius}px;
       padding: {padding}px;
       background-color: rgba(255, 255, 255, 0.08);
       border: 1px solid rgba(255, 255, 255, 0.2);
       color: rgba(220, 220, 220, 1);
       font-weight: bold;
   }}
   QPushButton:hover {{
       background: qlineargradient(
           x1:0, y1:0, x2:1, y2:1,
           stop:0   rgba(30, 100, 45, 0.75),
           stop:0.4 rgba(40, 130, 180, 0.75),
           stop:1   rgba(80, 80, 120, 0.65)
       );
       color: white;
       border: 1px solid rgba(255, 255, 255, 0.35);
   }}
   QPushButton:pressed {{
       background: qlineargradient(
           x1:0, y1:0, x2:1, y2:1,
           stop:0 rgba(60, 150, 200, 0.85),
           stop:1 rgba(25, 90, 40, 0.85)
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
   "settings_button": _PAYROLL_BTN.format(radius=15, padding=8),
   "gradient_button": _PAYROLL_BTN.format(radius=15, padding=8),
   "payroll_button":  _PAYROLL_BTN.format(radius=18, padding=12),
   # --- Input ---
   "input": """
       QLineEdit {
           font-size: 12px;
           color: rgba(220, 220, 220, 1);
           padding: 5px 0 5px 8px;
           background: rgba(255, 255, 255, 0.06);
           border: 1px solid rgba(255, 255, 255, 0.2);
           border-radius: 12px;
       }
       QLineEdit::placeholder {
           color: rgba(180, 180, 180, 0.6);
       }
   """,
   # --- Containers ---
   "main_container": """
       QWidget#container {
           background-color: rgba(15, 15, 20, 0.75);
           border-radius: 40px;
           border: 1px solid rgba(255, 255, 255, 0.12);
       }
   """,
   "body": """
       background: rgba(255, 255, 255, 0.05);
       border: 1px solid rgba(255, 255, 255, 0.1);
       border-radius: 20px;
   """,
   "body_clear": """
       background: transparent;
       border: none;
   """,
   "button_container": """
       QWidget {
           background-color: rgba(255, 255, 255, 0.06);
           border-radius: 25px;
           border: 1px solid rgba(255, 255, 255, 0.12);
       }
   """,
   "feature_content": """
        #featureContent {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 20px;
        }
    """,
   "standard_container": """
            QFrame {
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 15px;
                background-color: transparent;
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
           color: rgba(80, 220, 110, 1);
           background: transparent;
           border: none;
           qproperty-alignment: 'AlignCenter';
       }
   """,
   "failed": """
       QLabel {
           font-size: 14px;
           color: rgba(255, 90, 90, 1);
           background: transparent;
           border: none;
           qproperty-alignment: 'AlignCenter';
       }
   """,
   # --- Standard Text ---
   "header_label": """
       QLabel {
           font-size: 16px;
           font-weight: bold;
           color: rgba(230, 230, 230, 1);
           padding-bottom: 8px;
           background: transparent;
           border: none;
       }
   """,
   "standard": """
       QLabel {
           font-size: 12px;
           color: rgba(200, 200, 200, 1);
           padding: 4px;
           background: transparent;
           border: none;
       }
   """,
   "standard_red": """
       QLabel {
           font-size: 12px;
           color: rgba(255, 90, 90, 1);
           padding: 4px;
           background: transparent;
           border: none;
       }
   """,
   # --- Input Styles ---
   "payroll_input": """
        QLineEdit {
            border: 1px solid #c5cee8;
            border-radius: 12px;
            padding: 4px 8px;
            background: rgba(255, 255, 255, 0.08);
            color: white;
        }
        QLineEdit:hover {
            border-color: qlineargradient(
           x1:0, y1:0, x2:1, y2:1,
           stop:0   rgba(30, 100, 45, 0.75),
           stop:0.4 rgba(40, 130, 180, 0.75),
           stop:1   rgba(80, 80, 120, 0.65)
       );
        }
        """,

   "date_picker": """
        QLineEdit {
            border: 1px solid #c5cee8;
            border-radius: 12px;
            padding: 4px 8px;
            background: rgba(255, 255, 255, 0.08);
            color: white;
        }
        QLineEdit:hover {
            border-color: qlineargradient(
           x1:0, y1:0, x2:1, y2:1,
           stop:0   rgba(30, 100, 45, 0.75),
           stop:0.4 rgba(40, 130, 180, 0.75),
           stop:1   rgba(80, 80, 120, 0.65)
       );
        }
        """,
   # --- Scroll ---
   "settings_scroll": """
       QScrollBar:vertical {
           background: transparent;
           width: 6px;
       }
       QScrollBar::handle:vertical {
           background: rgba(255, 255, 255, 0.2);
           border-radius: 3px;
       }
       QScrollBar::handle:vertical:hover {
           background: rgba(255, 255, 255, 0.4);
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
           background: qradialgradient(
               cx:0.5, cy:0.5,
               radius:0.85,
               fx:0.5, fy:0.35,
               stop:0   rgba(30, 50, 80, 190),
               stop:0.5 rgba(15, 20, 35, 200),
               stop:1   rgba(5,  8,  15, 210)
           );
           border-radius: 40px;
           border: 1px solid rgba(255, 255, 255, 0.1);
       }
       QLabel {
           color: rgba(220, 220, 220, 1);
           font-size: 16px;
       }
   """,

   "calendar_dark":"""
            QCalendarWidget {
                border: 1px solid white;
                border-radius: 12px;
            }
            QCalendarWidget QWidget#qt_calendar_navigationbar {
                background-color: #344052; 
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
                padding: 4px;
            }
            QCalendarWidget QToolButton {
                color: #DADCE0; 
                background: transparent;
                font-weight: bold;
                font-size: 13px;
            }
            QCalendarWidget QToolButton:hover {
                background-color: #768291;
                border-radius: 4px;
            }
            QCalendarWidget QAbstractItemView {
                background-color: #27364C;
                color: #768291;
                selection-background-color: yellow;
                selection-color: #DADCE0;
                border-bottom-left-radius: 12px;
                border-bottom-right-radius: 12px;
            }
            QCalendarWidget QAbstractItemView:disabled {
                color: rgba(44, 44, 62, 0.3);
            }
        """
}