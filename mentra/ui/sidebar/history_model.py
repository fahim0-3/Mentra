from PyQt5.QtCore import QAbstractListModel, Qt, pyqtSignal as Signal, QModelIndex

class ChatHistoryModel(QAbstractListModel):
    """Data model for chat history history sidebar."""
    def __init__(self, chat_manager):
        super().__init__()
        self.chat_manager = chat_manager
        self._chats = []

    def rowCount(self, parent=QModelIndex()):
        return len(self._chats)

    def data(self, index, role=Qt.UserRole):
        if not index.isValid() or index.row() >= len(self._chats):
            return None
        
        chat = self._chats[index.row()]
        if role == Qt.UserRole: # Returns the full chat dictionary
            return chat
        elif role == Qt.DisplayRole:
            return chat["title"]
        elif role == Qt.ToolTipRole:
            return f"{chat['title']}\n{chat['timestamp']}"
        return None

    def refresh(self):
        """Reload all data from the database."""
        self.beginResetModel()
        self._chats = self.chat_manager.get_all_chats()
        self.endResetModel()

    def get_chat_id(self, row):
        if 0 <= row < len(self._chats):
            return self._chats[row]["id"]
        return None

    def remove_chat_by_id(self, chat_id):
        """Remove a chat from the model and database."""
        for i, chat in enumerate(self._chats):
            if chat["id"] == chat_id:
                self.beginRemoveRows(QModelIndex(), i, i)
                self.chat_manager.delete_chat(chat_id)
                self._chats.pop(i)
                self.endRemoveRows()
                return True
        return False
        
    def rename_chat(self, chat_id, new_title):
        """Update a chat's title in the model and database."""
        for i, chat in enumerate(self._chats):
            if chat["id"] == chat_id:
                chat["title"] = new_title
                self.chat_manager.rename_chat(chat_id, new_title)
                self.dataChanged.emit(self.index(i), self.index(i))
                return True
        return False
