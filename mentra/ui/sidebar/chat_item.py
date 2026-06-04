from datetime import datetime
from PyQt5.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QWidget,
    QSizePolicy, QPushButton
)
from PyQt5.QtCore import Qt, pyqtSignal as Signal
from PyQt5.QtGui import QIcon

class ChatItem(QFrame):
    clicked = Signal(str)  # chat_id
    rename_requested = Signal(str, str) # chat_id, new_title
    delete_requested = Signal(str)      # chat_id

    def __init__(self, chat_id, title, timestamp, icons, parent=None):
        super().__init__(parent)
        self.chat_id = chat_id
        self.full_title = title
        self.icons = icons # dict of pixmaps
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(65)
        self.setObjectName("chatItem")
        self.setMouseTracking(True)
        self.setStyleSheet(
            "#chatItem{border-radius:10px; background: transparent; padding: 5px;}"
            "#chatItem:hover{background: #27272a;}"
        )

        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(10, 5, 10, 5)
        main_lay.setSpacing(2)

        # Top row: Title/Edit | Buttons
        self.top_row = QHBoxLayout()
        self.top_row.setContentsMargins(0, 0, 0, 0)
        self.top_row.setSpacing(5)
        
        # Label
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("color: #fafafa; font-size: 14px; font-weight: 500; background:transparent;")
        self.lbl_title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.lbl_title.setMinimumWidth(0)
        self.top_row.addWidget(self.lbl_title)

        # Inline Editor (hidden by default)
        self.edit_title = QLineEdit(title)
        self.edit_title.setStyleSheet("background: #3f3f3f; color: white; border: none; border-radius: 4px; padding: 2px;")
        self.edit_title.setVisible(False)
        self.edit_title.returnPressed.connect(self._save_rename)
        self.top_row.addWidget(self.edit_title)

        # Action Buttons container (hidden unless hovered)
        self.actions = QWidget()
        self.actions.setVisible(False)
        al = QHBoxLayout(self.actions)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(5)

        self.btn_edit = self._make_tool_btn(self.icons['edit'])
        self.btn_edit.clicked.connect(self._start_rename)
        al.addWidget(self.btn_edit)

        self.btn_del = self._make_tool_btn(self.icons['delete'])
        self.btn_del.clicked.connect(lambda: self.delete_requested.emit(self.chat_id))
        al.addWidget(self.btn_del)

        self.top_row.addWidget(self.actions)
        main_lay.addLayout(self.top_row)

        try:
            # Format timestamp nicely
            dt = datetime.fromisoformat(timestamp)
            time_str = dt.strftime("%b %d, %H:%M")
        except:
            time_str = timestamp
            
        self.lbl_time = QLabel(time_str)
        self.lbl_time.setStyleSheet("color: #a1a1aa; font-size: 11px; background:transparent;")
        main_lay.addWidget(self.lbl_time)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        available = self.width() - 75 # Padding + buttons
        elided = self.fontMetrics().elidedText(self.full_title, Qt.ElideRight, available)
        self.lbl_title.setText(elided)

    def _make_tool_btn(self, px):
        b = QPushButton()
        b.setIcon(QIcon(px))
        b.setFixedSize(24, 24)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet("background: transparent; border: none;")
        return b

    def enterEvent(self, ev):
        if not self.edit_title.isVisible():
            self.actions.setVisible(True)
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.actions.setVisible(False)
        super().leaveEvent(ev)

    def _start_rename(self):
        self.lbl_title.setVisible(False)
        self.actions.setVisible(False)
        # Display full title in editor
        self.edit_title.setText(self.full_title)
        self.edit_title.setVisible(True)
        self.edit_title.setFocus()
        self.edit_title.selectAll()

    def _save_rename(self):
        nt = self.edit_title.text().strip()
        if nt:
            self.full_title = nt
            self.lbl_title.setText(nt)
            self.rename_requested.emit(self.chat_id, nt)
        self.edit_title.setVisible(False)
        self.lbl_title.setVisible(True)

    def keyPressEvent(self, ev):
        if self.edit_title.isVisible() and ev.key() == Qt.Key_Escape:
            self.edit_title.setVisible(False)
            self.lbl_title.setVisible(True)
        else:
            super().keyPressEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and not self.edit_title.isVisible():
            self.clicked.emit(self.chat_id)
        super().mousePressEvent(ev)
