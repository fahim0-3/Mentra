from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QSizePolicy, QTextEdit, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal as Signal, QSize
from PyQt5.QtGui import QIcon
from mentra.utils.styles import COLOR_ACCENT, COLOR_TEXT_MAIN

class MessageBubble(QWidget):
    """Refactored message bubble component."""
    edit_submitted = Signal(int, str) # index, new_text

    def __init__(self, text, is_user, history_index, icons, parent=None):
        super().__init__(parent)
        self.text = text
        self.is_user = is_user
        self.history_index = history_index
        self.icons = icons
        
        self.setStyleSheet("background:transparent;")
        self.wl = QHBoxLayout(self)
        self.wl.setContentsMargins(20, (15 if is_user else 5), 20, (5 if is_user else 15))
        
        if is_user:
            self.wl.addStretch()

        self.bubble = QFrame()
        if is_user:
            self.bubble.setStyleSheet(
                f"QFrame{{background:{COLOR_ACCENT}; border-radius:20px;}}"
            )
        else:
            self.bubble.setStyleSheet("QFrame{background:transparent;}")
        
        self.bl = QVBoxLayout(self.bubble)
        self.bl.setContentsMargins(16, 10, 16, 10)
        self.bl.setSpacing(4)

        self.lbl = QLabel(text)
        self.lbl.setWordWrap(True)
        self.lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        
        tc = "#ffffff" if is_user else COLOR_TEXT_MAIN
        self.lbl.setStyleSheet(
            f"color:{tc}; font-size:16px; font-family:'Segoe UI'; background:transparent;"
        )
        self.bl.addWidget(self.lbl)

        # Actions row (Copy, Edit)
        self.cr = QWidget()
        self.cr_l = QHBoxLayout(self.cr)
        self.cr_l.setContentsMargins(0, 0, 0, 0)
        self.cr_l.addStretch()

        if is_user and history_index is not None:
            self.btn_edit = self._make_action_btn(self.icons['edit'])
            self.btn_edit.clicked.connect(self._on_edit_clicked)
            self.cr_l.addWidget(self.btn_edit)

        self.btn_copy = self._make_action_btn(self.icons['copy'])
        self.btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.lbl.text()))
        self.cr_l.addWidget(self.btn_copy)
        
        self.bl.addWidget(self.cr, alignment=Qt.AlignRight)
        
        self.wl.addWidget(self.bubble)
        if not is_user:
            self.wl.addStretch()

        # Set stretches for bubble alignment
        if is_user:
            self.wl.setStretch(0, 1) # Left stretch
            self.wl.setStretch(1, 0) # Bubble
        else:
            self.wl.setStretch(0, 0) # Bubble
            self.wl.setStretch(1, 1) # Right stretch

    def setText(self, text):
        self.text = text
        self.lbl.setText(text)

    def _make_action_btn(self, px):
        b = QPushButton()
        b.setIcon(QIcon(px))
        b.setIconSize(QSize(16, 16))
        b.setFixedSize(24, 24)
        b.setCursor(Qt.PointingHandCursor)
        hc = "#1d4ed8" if self.is_user else "#27272a"
        b.setStyleSheet(
            f"QPushButton{{background:transparent; border:none; border-radius:4px;}}"
            f"QPushButton:hover{{background:{hc};}}"
        )
        return b

    def _on_edit_clicked(self):
        self.lbl.hide()
        self.cr.hide()
        
        self.te = QTextEdit()
        self.te.setText(self.text)
        self.te.setStyleSheet(
            "background:#27272a; color:#fff; border-radius:8px; padding:4px; "
            "font-family:'Segoe UI'; font-size:15px;"
        )
        self.te.setMinimumHeight(60)
        
        sv = QPushButton("Submit")
        sv.setFixedSize(100, 24)
        sv.setCursor(Qt.PointingHandCursor)
        sv.setStyleSheet(
            "QPushButton{background:#2563eb; color:white; border:none; "
            "border-radius:4px; font-size:14px; font-family:'Segoe UI';}"
            "QPushButton:hover{background:#1d4ed8;}"
        )
        
        self.bl.insertWidget(0, self.te)
        self.bl.insertWidget(1, sv, alignment=Qt.AlignRight)
        
        def on_save():
            nt = self.te.toPlainText().strip()
            if nt:
                self.edit_submitted.emit(self.history_index, nt)
        
        sv.clicked.connect(on_save)
