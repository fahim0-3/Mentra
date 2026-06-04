from PyQt5.QtCore import QAbstractListModel, Qt, QModelIndex

class ChatHistoryModel(QAbstractListModel):
    """Data model for chat history history sidebar."""
    def __init__(self, chat_manager):
        super().__init__()
        self.chat_manager = chat_manager
        self._chats = []
        self._pending_delete = set()  # chat_ids soft-removed (awaiting undo or commit)

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
        """Reload all data from the database (excluding chats pending deletion)."""
        self.beginResetModel()
        self._chats = [c for c in self.chat_manager.get_all_chats()
                       if c["id"] not in self._pending_delete]
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
        
    def soft_remove(self, chat_id):
        """Remove from the view only (database untouched). Returns (chat, row) for undo."""
        for i, chat in enumerate(self._chats):
            if chat["id"] == chat_id:
                self._pending_delete.add(chat_id)
                self.beginRemoveRows(QModelIndex(), i, i)
                self._chats.pop(i)
                self.endRemoveRows()
                return chat, i
        return None, -1

    def restore(self, chat, row):
        """Re-insert a previously soft-removed chat at its row (database untouched)."""
        if not chat:
            return
        self._pending_delete.discard(chat["id"])
        row = max(0, min(row, len(self._chats)))
        self.beginInsertRows(QModelIndex(), row, row)
        self._chats.insert(row, chat)
        self.endInsertRows()

    def commit_delete(self, chat_id):
        """Permanently delete the chat from the database (the view is already updated)."""
        self.chat_manager.delete_chat(chat_id)
        self._pending_delete.discard(chat_id)

    def rename_chat(self, chat_id, new_title):
        """Update a chat's title in the model and database."""
        for i, chat in enumerate(self._chats):
            if chat["id"] == chat_id:
                chat["title"] = new_title
                self.chat_manager.rename_chat(chat_id, new_title)
                self.dataChanged.emit(self.index(i), self.index(i))
                return True
        return False
