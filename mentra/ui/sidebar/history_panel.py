from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListView, QFrame, QInputDialog, QLineEdit
)
from PyQt5.QtCore import Qt, pyqtSignal as Signal, QTimer
from mentra.ui.components.snackbar import Snackbar
from mentra.ui.sidebar.history_model import ChatHistoryModel
from mentra.ui.sidebar.history_delegate import ChatItemDelegate
from mentra.utils.styles import COLOR_FRAME, STYLE_SCROLLBAR

class HistoryPanel(QWidget):
    load_chat = Signal(str)
    new_chat = Signal()
    collapse_clicked = Signal()
    chat_deleted = Signal(str)
    
    # Internal signals for delegate communication
    rename_requested = Signal(int) # row
    delete_requested = Signal(int) # row

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

        self.undo_registry = {} # chat_id: QTimer
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
        self.lv.setMouseTracking(True) # Required for hover effects in delegate
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
        if not chat_id: return
        
        # Simple InputDialog for rename (could be improved later)
        chat = self.model.data(self.model.index(row), Qt.UserRole)
        new_title, ok = QInputDialog.getText(
            self, "Rename Chat", "New Title:", QLineEdit.Normal, chat["title"]
        )
        if ok and new_title.strip():
            self.model.rename_chat(chat_id, new_title.strip())

    def _on_delete_request(self, row):
        chat_id = self.model.get_chat_id(row)
        if not chat_id: return
        
        # Use undo snackbar
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda cid=chat_id: self._on_permanently_delete(cid))
        self.undo_registry[chat_id] = timer
        timer.start(5000)

        self.snackbar.show_msg("Chat deleted")
        self.chat_deleted.emit(chat_id)
        # Note: model removal needs careful handling if undo is cancelled
        self.model.refresh() # Temporarily reload (or we could store deleted IDs in model)

    def _on_undo(self):
        self.snackbar.hide()
        if self.undo_registry:
            chat_id = list(self.undo_registry.keys())[-1]
            timer = self.undo_registry.pop(chat_id)
            timer.stop()
            self.model.refresh()

    def _on_permanently_delete(self, chat_id):
        if chat_id in self.undo_registry:
            self.undo_registry.pop(chat_id)
        self.model.remove_chat_by_id(chat_id)
