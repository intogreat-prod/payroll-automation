"""
ui_factory.py — static builders for all reusable PyQt6 widgets.

Every widget in the app should come from here so sizing, style, and
behaviour stay consistent across screens. No business logic here.
"""

from PyQt6.QtWidgets import (
    QComboBox, QPushButton, QLabel, QLineEdit,
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, 
    QCalendarWidget, QDialog, QGridLayout
)
from PyQt6.QtCore import Qt, QDate, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QIcon, QTextCharFormat, QColor

from ui.styles import STYLES
from utils.file_utils import resource_path

_ALIGN_MAP = {
    "left":   Qt.AlignmentFlag.AlignLeft,
    "center": Qt.AlignmentFlag.AlignCenter,
    "right":  Qt.AlignmentFlag.AlignRight,
}

class _DatePickerEdit(QLineEdit):
    """Read-only line edit that pops a frameless calendar on click."""
    date_changed = pyqtSignal(QDate)

    def __init__(self, fmt: str, style:str, parent=None):
        super().__init__(parent)
        self._fmt = fmt
        self.style = style
        self._date = QDate.currentDate()
        self.setReadOnly(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh()

    def date(self) -> QDate:
        return self._date
    
    def set_date(self, date: QDate):
        self._date = date
        self._refresh()

    def mousePressEvent(self, _):
        self._open()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._open()
        else:
            super().keyPressEvent(e)

    def _open(self):
        dlg = QDialog(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        cal = QCalendarWidget(dlg)
        cal.setSelectedDate(self._date)
        cal.setGridVisible(False)
        cal.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        cal.setStyleSheet(self.style)
        # QCalendarWidget paints weekday-header text and weekend-date
        # text from QTextCharFormat internally — QSS "color" can't
        # reach either, so both are set here in code instead.
        weekday_format = QTextCharFormat()
        weekday_format.setForeground(QColor("#DADCE0"))
        cal.setHeaderTextFormat(weekday_format)
        cal.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, weekday_format)
        cal.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, weekday_format)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(cal)
        dlg.setLayout(layout)

        def pick(date: QDate):
            self._date = date
            self._refresh()
            self.date_changed.emit(date)
            dlg.accept()
        cal.activated.connect(pick)
        dlg.move(self.mapToGlobal(self.rect().bottomLeft()))
        dlg.exec()

    def _refresh(self):
        self.setText(self._date.toString(self._fmt))

class _MonthPickerEdit(QLineEdit):
    """Read-only line edit that pops a month/year picker on click."""
    month_changed = pyqtSignal(QDate)

    def __init__(self, style: str, parent=None):
        super().__init__(parent)

        self.style = style
        self._date = QDate.currentDate().addDays(
            1 - QDate.currentDate().day()
        )

        self.setReadOnly(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh()

    def date(self) -> QDate:
        return self._date

    def set_date(self, date: QDate):
        self._date = QDate(date.year(), date.month(), 1)
        self._refresh()

    def mousePressEvent(self, _):
        self._open()

    def keyPressEvent(self, e):
        if e.key() in (
            Qt.Key.Key_Space,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter
        ):
            self._open()
        else:
            super().keyPressEvent(e)

    def _open(self):
        dlg = QDialog(
            self,
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )

        dlg.setStyleSheet(self.style)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # -------------------------
        # YEAR HEADER
        # -------------------------
        header = QHBoxLayout()

        prev_btn = QPushButton("‹")
        next_btn = QPushButton("›")

        year_label = QLabel(str(self._date.year()))
        year_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        header.addWidget(prev_btn)
        header.addWidget(year_label, 1)
        header.addWidget(next_btn)

        layout.addLayout(header)

        # -------------------------
        # MONTHS
        # -------------------------
        months_layout = QGridLayout()
        months_layout.setSpacing(6)

        selected_year = self._date.year()

        months = [
            "Jan", "Feb", "Mar",
            "Apr", "May", "Jun",
            "Jul", "Aug", "Sep",
            "Oct", "Nov", "Dec"
        ]

        def select_month(month):
            date = QDate(selected_year, month, 1)

            self._date = date
            self._refresh()
            self.month_changed.emit(date)

            dlg.accept()

        buttons = []

        for i, month_name in enumerate(months):
            month = i + 1

            btn = QPushButton(month_name)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

            if month == self._date.month():
                btn.setProperty("selected", True)

            btn.clicked.connect(
                lambda checked=False, m=month: select_month(m)
            )

            months_layout.addWidget(
                btn,
                i // 3,
                i % 3
            )

            buttons.append(btn)

        layout.addLayout(months_layout)

        def change_year(delta):
            nonlocal selected_year

            selected_year += delta
            year_label.setText(str(selected_year))

            for i, btn in enumerate(buttons):
                btn.setProperty(
                    "selected",
                    selected_year == self._date.year()
                    and (i + 1) == self._date.month()
                )

                btn.style().unpolish(btn)
                btn.style().polish(btn)

        prev_btn.clicked.connect(lambda: change_year(-1))
        next_btn.clicked.connect(lambda: change_year(1))

        dlg.adjustSize()

        dlg.move(
            self.mapToGlobal(
                self.rect().bottomLeft()
            )
        )

        dlg.exec()

    def _refresh(self):
        self.setText(
            self._date.toString("MMMM yyyy")
        )

class UIFactory:

    # -------------------------------------------------------------------------
    # BUTTON

    @staticmethod
    def button(text: str, callback, style_key: str = "button",
               width: int = None, height: int = None,
               icon: tuple[str, int, int] | None = None) -> QPushButton:
        """Standard clickable button."""
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(STYLES.get(style_key, ""))
        btn.clicked.connect(callback)

        if width:
            btn.setFixedWidth(width)
        if height:
            btn.setFixedHeight(height)
        if icon:
            path, w, h = icon
            btn.setIcon(QIcon(resource_path(path)))
            btn.setIconSize(QSize(w, h))

        return btn

    # -------------------------------------------------------------------------
    # IMAGE

    @staticmethod
    def image(asset_path: str, width: int = 200, height: int = 200,
              fixed_width: int = None, fixed_height: int = None) -> QLabel:
        """
        Loads an asset image, scales it, and returns it as a QLabel.
        Uses resource_path() so it works in both dev and PyInstaller bundles.
        """
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("QLabel { border: none; background: transparent; }")

        pixmap = QPixmap(resource_path(asset_path))
        if not pixmap.isNull():
            pixmap = pixmap.scaled(
                width, height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            label.setPixmap(pixmap)

        if fixed_width:
            label.setFixedWidth(fixed_width)
        if fixed_height:
            label.setFixedHeight(fixed_height)

        return label

    # -------------------------------------------------------------------------
    # LABEL

    @staticmethod
    def link_label(text: str, url: str, font_size: int = 11,
                color: str = "#8F96A3", hover_color: str = "#F5F5F5",
                align: str = "left") -> QLabel:
        """
        Clickable rich-text link styled like link_style's QPushButton, but
        as a QLabel. QSS :hover doesn't work on <a href> tags inside Qt's
        rich-text engine, so hover color is swapped in code via linkHovered
        instead of a stylesheet.
        """
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        label.setOpenExternalLinks(True)

        label.setAlignment(_ALIGN_MAP.get(align.lower(), Qt.AlignmentFlag.AlignLeft))
        label.setStyleSheet(
            f"QLabel {{ background: transparent; border: none; font-size: {font_size}px; }}"
        )
        label.setCursor(Qt.CursorShape.PointingHandCursor)

        def _render(active_color: str, underline: bool):
            decoration = "underline" if underline else "none"
            label.setText(
                f'<a href="{url}" style="color:{active_color}; '
                f'text-decoration:{decoration};">{text}</a>'
            )
        _render(color, underline=False)

        def _on_hover(hovered_url: str):
            _render(hover_color, underline=True) if hovered_url else _render(color, underline=False)

        label.linkHovered.connect(_on_hover)
        return label

    @staticmethod
    def label(
        text: str,
        style_key: str | None = None,
        align: str = "left",
        word_wrap: bool = False,
        font_size: int = 12,
        color: str = "black",
        font_weight: str = "normal",
        italic: bool = False,
        padding_top: int = 0,
        padding_bottom: int = 0,
        padding_right: int = 0,
        padding_left: int = 0,
        underline: bool = False,
        background: str = "transparent",
        border: str = "none",
        width: int | None = None,
        height: int | None = None,
        selectable: bool = False,
        link: bool = False,
        richtext: bool = False
    ) -> QLabel:
        """
        Flexible QLabel builder. style_key applies a preset from STYLES;
        all other kwargs layer inline CSS on top.
        Set link=True to enable clickable <a href> tags.
        """


        lbl = QLabel(text)
        lbl.setAlignment(_ALIGN_MAP.get(align.lower(), Qt.AlignmentFlag.AlignLeft))
        lbl.setWordWrap(word_wrap)

        styles = [STYLES.get(style_key, "")] if style_key else []
        styles += [
            f"font-size: {font_size}px;",
            f"color: {color};",
            f"font-weight: {font_weight};",
            f"background: {background};",
            f"border: {border};",
            f"padding-top: {padding_top};",
            f"padding-bottom: {padding_bottom};",
            f"padding-right: {padding_right};",
            f"padding-left: {padding_left};",
        ]
        if italic:
            styles.append("font-style: italic;")
        if underline:
            styles.append("text-decoration: underline;")

        lbl.setStyleSheet(" ".join(styles))

        if width:
            lbl.setFixedWidth(width)
        if height:
            lbl.setFixedHeight(height)

        if selectable:
            lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
        if link:
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            lbl.setOpenExternalLinks(True)

        if richtext:
            lbl.setTextFormat(Qt.TextFormat.RichText)

        return lbl

    # -------------------------------------------------------------------------
    # INPUT

    @staticmethod
    def input(placeholder: str = "", password: bool = False,
              style: str = "payroll_input", height: int = 30, align: str = "left") -> QLineEdit:
        """Text input field. Set password=True to mask the input."""
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setAlignment(_ALIGN_MAP.get(align.lower(), Qt.AlignmentFlag.AlignLeft))
        field.setStyleSheet(STYLES.get(style, ""))

        if password:
            field.setEchoMode(QLineEdit.EchoMode.Password)

        if height:
            field.setFixedHeight(height)

        return field

    @staticmethod
    def combo_box(items: list = None, style: str = "combo_box",
                height: int = 30, placeholder: str = "") -> QComboBox:
        """
        Dropdown selector. Items can be plain strings, or (label, data)
        tuples if you need to carry a value distinct from the display text
        (e.g. version tag as the label, asset_id as the data) — retrieve it
        later with combo.currentData(). Set placeholder for a disabled first
        row like "Select a version".
        """
        box = QComboBox()
        box.setStyleSheet(STYLES.get(style, ""))

        if height:
            box.setFixedHeight(height)

        if placeholder:
            box.addItem(placeholder, None)
            box.model().item(0).setEnabled(False)
            
        for item in (items or []):
            label, data = item if isinstance(item, tuple) else (item, item)
            box.addItem(label, data)

        return box

    # -------------------------------------------------------------------------
    # DIVIDER

    @staticmethod
    def divider(style_key:str = "standard_divider", shape= QFrame.Shape.HLine, shadow=None) -> QFrame:
        """Horizontal rule separator."""
        line = QFrame()
        if shape:
            line.setFrameShape(shape)
        if shadow:
            line.setFrameShadow(shadow)
        if style_key:
            line.setStyleSheet(style_key)
        return line

    # -------------------------------------------------------------------------
    # CARD

    @staticmethod
    def card(object_name: str = "card", min_height: int = 150) -> tuple[QFrame, QVBoxLayout]:
        """
        Rounded content card. Returns (frame, layout) so the caller can
        add child widgets without reaching inside the frame.
        """
        frame = QFrame()
        frame.setObjectName(object_name)
        frame.setMinimumHeight(min_height)
        frame.setStyleSheet(f"""
            #{object_name} {{
                background: rgba(255, 255, 255, 100);
                border: 1px solid rgba(255, 255, 255, 220);
                border-radius: 20px;
            }}
        """)
        layout = QVBoxLayout()
        frame.setLayout(layout)
        return frame, layout

    # -------------------------------------------------------------------------
    # BUTTON ROW
    @staticmethod
    def button_row(buttons: list[tuple], width: int = None, height: int = None,
                    spacing: int = 10, margin: tuple = (10, 10, 10, 10),
                    parent: QWidget = None, use_container: bool = True,
                    con_style_key: str = "") -> tuple[QWidget | None, QHBoxLayout]:
        """
        Horizontal row of buttons.
        Each entry in buttons is (text, callback) or (text, callback, style_key).
        Returns (container, layout) — container is None if use_container=False.
        """
        if use_container:
            container = QWidget(parent)
            layout    = QHBoxLayout(container)
            container.setStyleSheet(con_style_key)

        else:
            container = None
            layout    = QHBoxLayout()

        layout.setContentsMargins(*margin)
        layout.setSpacing(spacing)

        for item in buttons:
            text, callback = item[0], item[1]
            style_key      = item[2] if len(item) > 2 else "button"
            icon = item[3] if len(item) > 3 else None
            layout.addWidget(UIFactory.button(text, callback, style_key, width=width, height=height, icon=icon))

        return container, layout

    # -------------------------------------------------------------------------
    # BUTTON COLUMN
    @staticmethod
    def button_column(buttons: list[tuple], width: int = None, height: int = None,
                        spacing: int = 10, margin: tuple = (10, 10, 10, 10),
                        parent: QWidget = None, use_container: bool = True, 
                        con_style_key: str = "") -> tuple[QWidget | None, QVBoxLayout]:
        """
        Vertical stack of buttons.
        Each entry in buttons is (text, callback) or (text, callback, style_key).
        Returns (container, layout) — container is None if use_container=False.
        """
        if use_container:
            container = QWidget(parent)
            layout    = QVBoxLayout(container)

            container.setStyleSheet(con_style_key)
        else:
            container = None
            layout    = QVBoxLayout()

        layout.setContentsMargins(*margin)
        layout.setSpacing(spacing)

        for item in buttons:
            text, callback = item[0], item[1]
            style_key      = item[2] if len(item) > 2 else "button"
            icon = item[3] if len(item) > 3 else None
            layout.addWidget(UIFactory.button(text, callback, style_key, width=width, height=height, icon=icon))

        return container, layout


    
    # -------------------------------------------------------------------------
    # DATE PICKER
    @staticmethod
    def date_picker(
        format: str = "MMM d, yyyy",
        default_date: QDate = None,
        style_key: str = "payroll_input",
        width: int = None,
        height: int = None,
        callback=None,
    ) -> _DatePickerEdit:
        """
        Read-only field that pops a calendar on click.
        Connects date_changed signal to callback if provided.
        """
        picker = _DatePickerEdit(fmt=format, style=STYLES['calendar_dark'])
        picker.setStyleSheet(STYLES.get(style_key, ""))
        if default_date:
            picker.set_date(default_date)
        if width:
            picker.setFixedWidth(width)
        if height:
            picker.setFixedHeight(height)
        if callback:
            picker.date_changed.connect(callback)
        return picker

    @staticmethod
    def month_picker(
        default_date: QDate = None,
        style_key: str = "payroll_input",
        width: int = None,
        height: int = None,
        callback=None,
    ) -> _MonthPickerEdit:

        picker = _MonthPickerEdit(
            style=STYLES['calendar_dark']
        )

        picker.setStyleSheet(
            STYLES.get(style_key, "")
        )

        if default_date:
            picker.set_date(default_date)

        if width:
            picker.setFixedWidth(width)

        if height:
            picker.setFixedHeight(height)

        if callback:
            picker.month_changed.connect(callback)

        return picker