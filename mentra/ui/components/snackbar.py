from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt, pyqtSignal as Signal

class Snackbar(QFrame):
    undo_clicked = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedWidth(240)
        self.setFixedHeight(40)
        self.setStyleSheet(
            "background: #27272a; border-radius: 8px; border: 1px solid #3f3f46;"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)

        self.lbl = QLabel("Chat deleted")
        self.lbl.setStyleSheet("color: white; font-size: 13px; border: none;")
        lay.addWidget(self.lbl)

        self.btn_undo = QPushButton("Undo")
        self.btn_undo.setCursor(Qt.PointingHandCursor)
        self.btn_undo.setStyleSheet(
            "color: #3b82f6; font-weight: bold; background: transparent; border: none; font-size: 13px;"
        )
        self.btn_undo.clicked.connect(self.undo_clicked.emit)
        lay.addWidget(self.btn_undo)
        self.hide()

    def show_msg(self, text="Chat deleted"):
        self.lbl.setText(text)
        self.show()
        # Position at bottom left of parent
        self.move(10, self.parent().height() - 60)
        self.raise_()
