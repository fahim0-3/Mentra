from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListView, QFrame,
    QDialog, QLineEdit
)
from PyQt5.QtCore import Qt, pyqtSignal as Signal, QTimer
from mentra.ui.components.snackbar import Snackbar
from mentra.ui.sidebar.history_model import ChatHistoryModel
from mentra.ui.sidebar.history_delegate import ChatItemDelegate
from mentra.utils.styles import (
    COLOR_FRAME, STYLE_SCROLLBAR, COLOR_INPUT_BG, COLOR_ACCENT,
    COLOR_TEXT_MAIN, COLOR_TEXT_SUB,
)


class RenameDialog(QDialog):
    """Frameless, dark-themed dialog for renaming a chat (replaces QInputDialog)."""

    def __init__(self, current_title, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedWidth(340)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("renameCard")
        card.setStyleSheet(
            f"#renameCard{{background:{COLOR_FRAME}; border:1px solid #3f3f46; border-radius:14px;}}"
        )
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        title = QLabel("Rename chat")
        title.setStyleSheet(
            f"color:{COLOR_TEXT_MAIN}; font-size:14px; font-weight:600; background:transparent;"
        )
        lay.addWidget(title)

        self.edit = QLineEdit(current_title)
        self.edit.setStyleSheet(
            f"QLineEdit{{background:{COLOR_INPUT_BG}; color:{COLOR_TEXT_MAIN}; "
            f"border:1px solid #3f3f46; border-radius:8px; padding:8px 10px; font-size:13px;}}"
            f"QLineEdit:focus{{border:1px solid {COLOR_ACCENT};}}"
        )
        self.edit.returnPressed.connect(self.accept)
        lay.addWidget(self.edit)

        btns = QHBoxLayout()
        btns.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton{{background:transparent; color:{COLOR_TEXT_SUB}; "
            f"border:1px solid #3f3f46; border-radius:8px; padding:6px 14px; font-size:12px;}}"
            f"QPushButton:hover{{background:#27272a; color:{COLOR_TEXT_MAIN};}}"
        )
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)

        save = QPushButton("Save")
        save.setCursor(Qt.PointingHandCursor)
        save.setStyleSheet(
            f"QPushButton{{background:{COLOR_ACCENT}; color:white; border:none; "
            f"border-radius:8px; padding:6px 16px; font-size:12px; font-weight:600;}}"
            f"QPushButton:hover{{background:#2563eb;}}"
        )
        save.clicked.connect(self.accept)
        btns.addWidget(save)
        lay.addLayout(btns)

        self.edit.setFocus()
        self.edit.selectAll()

    def get_title(self):
        return self.edit.text().strip()


class HistoryPanel(QWidget):
    load_chat = Signal(str)
    new_chat = Signal()
    collapse_clicked = Signal()
    chat_deleted = Signal(str)

    # Internal signals for delegate communication
    rename_requested = Signal(int)  # row
    delete_requested = Signal(int)  # row

    def __init__(self, chat_manager, icons, parent=None):
        super().__init__(parent)
        self.chat_manager = chat_manager
        self.icons = icons
        self.setMinimumWidth(180)
        self.setMaximumWidth(400)
        self.setStyleSheet(
            f"background: {COLOR_FRAME}; border-right: 1px solid #27272a;"
            "border-top-left-radius: 20px; border-bottom-left-radius: 20px;"
        )

        self.undo_registry = {}  # chat_id: {"timer", "chat", "row"}
        self.snackbar = Snackbar(self)
        self.snackbar.undo_clicked.connect(self._on_undo)

        self.model = ChatHistoryModel(self.chat_manager)
        self.delegate = ChatItemDelegate(self.icons, self)

        self.rename_requested.connect(self._on_rename_request)
        self.delete_requested.connect(self._on_delete_request)

        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(10, 20, 10, 20)
        main_lay.setSpacing(15)

        # Header
        hdr = QHBoxLayout()
        self.btn_collapse = QPushButton("⮜")
        self.btn_collapse.setFixedSize(30, 30)
        self.btn_collapse.setCursor(Qt.PointingHandCursor)
        self.btn_collapse.setStyleSheet(
            "QPushButton{background:transparent; color:#a1a1aa; border:none; font-size:18px;}"
            "QPushButton:hover{color:#fafafa; background:#27272a; border-radius:5px;}"
        )
        self.btn_collapse.clicked.connect(self.collapse_clicked.emit)
        hdr.addWidget(self.btn_collapse)

        lbl = QLabel("History")
        lbl.setStyleSheet("color: #fafafa; font-size: 18px; font-weight: bold; background:transparent;")
        hdr.addWidget(lbl)
        hdr.addStretch()

        self.btn_new = QPushButton("＋ New")
        self.btn_new.setFixedSize(70, 30)
        self.btn_new.setCursor(Qt.PointingHandCursor)
        self.btn_new.setStyleSheet(
            "QPushButton{background:#3b82f6; color:white; border:none; border-radius:15px; font-size:13px;}"
            "QPushButton:hover{background:#2563eb;}"
        )
        self.btn_new.clicked.connect(self.new_chat.emit)
        hdr.addWidget(self.btn_new)
        main_lay.addLayout(hdr)

        # ListView
        self.lv = QListView()
        self.lv.setModel(self.model)
        self.lv.setItemDelegate(self.delegate)
        self.lv.setFrameShape(QFrame.NoFrame)
        self.lv.setStyleSheet(
            f"QListView{{background:transparent; border:none;}} "
            f"QListView::item{{background:transparent;}} "
            f"{STYLE_SCROLLBAR}"
        )
        self.lv.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.lv.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.lv.setSpacing(5)
        self.lv.setMouseTracking(True)  # Required for hover effects in delegate
        self.lv.clicked.connect(self._on_item_clicked)

        main_lay.addWidget(self.lv)
        self.refresh()

    def refresh(self):
        self.model.refresh()

    def _on_item_clicked(self, index):
        if index.isValid():
            chat_id = self.model.get_chat_id(index.row())
            if chat_id:
                self.load_chat.emit(chat_id)

    def _on_rename_request(self, row):
        chat_id = self.model.get_chat_id(row)
        if not chat_id:
            return
        chat = self.model.data(self.model.index(row), Qt.UserRole)
        dlg = RenameDialog(chat["title"], self)
        if dlg.exec_() == QDialog.Accepted:
            new_title = dlg.get_title()
            if new_title and new_title != chat["title"]:
                self.model.rename_chat(chat_id, new_title)

    def _on_delete_request(self, row):
        chat_id = self.model.get_chat_id(row)
        if not chat_id:
            return
        # Optimistic: remove from the view immediately; commit to the DB after 5s unless undone.
        chat, orig_row = self.model.soft_remove(chat_id)
        if chat is None:
            return
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda cid=chat_id: self._on_permanently_delete(cid))
        self.undo_registry[chat_id] = {"timer": timer, "chat": chat, "row": orig_row}
        timer.start(5000)

        self.snackbar.show_msg("Chat deleted")
        self.chat_deleted.emit(chat_id)

    def _on_undo(self):
        self.snackbar.hide()
        if not self.undo_registry:
            return
        chat_id = list(self.undo_registry.keys())[-1]
        entry = self.undo_registry.pop(chat_id)
        entry["timer"].stop()
        self.model.restore(entry["chat"], entry["row"])

    def _on_permanently_delete(self, chat_id):
        self.undo_registry.pop(chat_id, None)
        self.model.commit_delete(chat_id)
