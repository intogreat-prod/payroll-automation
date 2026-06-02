"""
ui_factory.py — static builders for all reusable PyQt6 widgets.

Every widget in the app should come from here so sizing, style, and
behaviour stay consistent across screens. No business logic here.
"""

from PyQt6.QtWidgets import (
    QPushButton, QLabel, QLineEdit,
    QFrame, QWidget, QVBoxLayout, QHBoxLayout,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from ui.styles import STYLES
from utils.file_utils import resource_path


class UIFactory:

    # -------------------------------------------------------------------------
    # BUTTON

    @staticmethod
    def button(text: str, callback, style_key: str = "button",
               width: int = None, height: int = None) -> QPushButton:
        """Standard clickable button."""
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(STYLES.get(style_key, ""))
        btn.clicked.connect(callback)

        if width:
            btn.setFixedWidth(width)
        if height:
            btn.setFixedHeight(height)

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
    def label(
        text: str,
        style_key: str | None = None,
        align: str = "left",
        word_wrap: bool = False,
        font_size: int = 12,
        color: str = "black",
        font_weight: str = "normal",
        italic: bool = False,
        underline: bool = False,
        background: str = "transparent",
        border: str = "none",
        width: int | None = None,
        height: int | None = None,
        selectable: bool = False,
        link: bool = False,
    ) -> QLabel:
        """
        Flexible QLabel builder. style_key applies a preset from STYLES;
        all other kwargs layer inline CSS on top.
        Set link=True to enable clickable <a href> tags.
        """
        _ALIGN_MAP = {
            "left":   Qt.AlignmentFlag.AlignLeft,
            "center": Qt.AlignmentFlag.AlignCenter,
            "right":  Qt.AlignmentFlag.AlignRight,
        }

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

        return lbl

    # -------------------------------------------------------------------------
    # INPUT

    @staticmethod
    def input(placeholder: str = "", password: bool = False,
              style: str = "payroll_input") -> QLineEdit:
        """Text input field. Set password=True to mask the input."""
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setStyleSheet(STYLES.get(style, ""))

        if password:
            field.setEchoMode(QLineEdit.EchoMode.Password)

        return field

    # -------------------------------------------------------------------------
    # DIVIDER

    @staticmethod
    def divider() -> QFrame:
        """Horizontal rule separator."""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("color: rgba(0, 0, 0, 0.15);")
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
                   spacing: int = 10, margin: tuple = (10, 10, 10, 10)) -> tuple[QWidget, QHBoxLayout]:
        """
        Horizontal row of buttons.
        Each entry in buttons is (text, callback) or (text, callback, style_key).
        Returns (container, layout) in case you need to add more items later.
        """
        container = QWidget()
        layout    = QHBoxLayout(container)
        layout.setContentsMargins(*margin)
        layout.setSpacing(spacing)

        for item in buttons:
            text, callback = item[0], item[1]
            style_key      = item[2] if len(item) > 2 else "button"
            layout.addWidget(UIFactory.button(text, callback, style_key, width=width, height=height))

        return container, layout

    # -------------------------------------------------------------------------
    # BUTTON COLUMN

    @staticmethod
    def button_column(buttons: list[tuple], width: int = None, height: int = None,
                      spacing: int = 10, margin: tuple = (10, 10, 10, 10)) -> tuple[QWidget, QVBoxLayout]:
        """
        Vertical stack of buttons.
        Each entry in buttons is (text, callback) or (text, callback, style_key).
        Returns (container, layout) in case you need to add more items later.
        """
        container = QWidget()
        layout    = QVBoxLayout(container)
        layout.setContentsMargins(*margin)
        layout.setSpacing(spacing)

        for item in buttons:
            text, callback = item[0], item[1]
            style_key      = item[2] if len(item) > 2 else "button"
            layout.addWidget(UIFactory.button(text, callback, style_key, width=width, height=height))

        return container, layout
