"""
main_window.py
--------------
The top-level PyQt6 window shell.

Builds the fixed chrome (Header, Body, Footer) inside a frosted-glass
card and exposes resize_to() for screens that need different sizes.
"""

from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QColor

from ui.styles import STYLES
from ui.components.header import Header
from ui.components.body import Body
from ui.components.footer import Footer

from utils.file_utils import resource_path


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        # Frameless + translucent for the glass card look
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowIcon(QIcon(resource_path("assets/icon.ico")))
        self.resize(400, 350)

        # ---------------------------------------------------------------
        # Center window on screen
        # ---------------------------------------------------------------
        screen = QApplication.primaryScreen().availableGeometry()

        screen_width = screen.width()
        screen_height = screen.height()

        window_width = self.width()
        window_height = self.height()

        x = (screen_width - window_width) // 2
        y = int((screen_height - window_height) * 0.1)

        self.move(x, y)

        # ---------------------------------------------------------------
        # Outer container (needed for WA_TranslucentBackground)
        # ---------------------------------------------------------------
        container = QWidget()
        self.setCentralWidget(container)

        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(5, 5, 5, 5)
        container.setLayout(outer_layout)

        # ---------------------------------------------------------------
        # App card — the frosted-glass rounded rectangle
        # ---------------------------------------------------------------
        self.app_card = QWidget()
        self.app_card.setObjectName("appCard")
        self.app_card.setMinimumSize(400, 200)

        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(10, 10, 10, 10)
        self.app_card.setLayout(card_layout)
        

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(10)
        shadow.setOffset(0, 0)
        shadow.setColor(QColor(100, 180, 255 ,160))

        self.app_card.setGraphicsEffect(shadow)

        # ---------------------------------------------------------------
        # Fixed components
        # ---------------------------------------------------------------
        self.header = Header()
        self.body = Body(self)
        self.footer = Footer()

        card_layout.addWidget(self.header)
        card_layout.addWidget(self.body, stretch=1)
        card_layout.addWidget(self.footer)

        outer_layout.addWidget(self.app_card, alignment=Qt.AlignmentFlag.AlignCenter)

        self.setStyleSheet(STYLES["app_window"])

    # ===================================================================
    # PUBLIC
    # ===================================================================

    def resize_to(self, w, h):
        self,self.setUpdatesEnabled(False)
        self.setFixedSize(w, h)
        self.app_card.setFixedSize(w - 10, h - 10)
        self.setUpdatesEnabled(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            drag_height = int(self.height() * 0.2)

            if event.position().y() <= drag_height:
                self.drag_position = (
                    event.globalPosition().toPoint()
                    - self.frameGeometry().topLeft()
                )
                event.accept()
            else:
                self.drag_position = None
                event.ignore()

    def mouseMoveEvent(self, event):
        if (
            event.buttons() & Qt.MouseButton.LeftButton
            and self.drag_position is not None
        ):
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_position = None
        event.accept()