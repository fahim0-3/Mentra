import os
import json
from datetime import datetime
from mentra.core.database import DatabaseManager

class ChatManager:
    def __init__(self, storage_file="chat_history.json", db_path="mentra_history.db"):
        self.storage_file = storage_file
        self.db = DatabaseManager(db_path)
        
        # One-time migration
        if os.path.exists(self.storage_file):
            self._migrate_json_to_sqlite()

    def _migrate_json_to_sqlite(self):
        """Import legacy JSON data into the SQLite database."""
        try:
            with open(self.storage_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for chat in data.get("chats", []):
                    # Check if already migrated
                    if not any(c['id'] == chat['id'] for c in self.db.get_all_chats()):
                        self.db.save_chat(
                            chat['id'],
                            chat['title'],
                            chat['timestamp'],
                            chat['messages']
                        )
            # Rename legacy file to avoid repeated migration
            os.rename(self.storage_file, f"{self.storage_file}.backup")
            print(f"Migration complete. Legacy data backed up to {self.storage_file}.backup")
        except Exception as e:
            print(f"Error during migration: {e}")

    def get_all_chats(self):
        return self.db.get_all_chats()

    def save_chat(self, chat_id, messages, title=None):
        timestamp = datetime.now().isoformat()
        
        # Determine title if not provided
        if not title:
            # First user message or default
            for msg in messages:
                if msg["role"] == "user":
                    raw = msg["content"]
                    title = raw[:30] + ("..." if len(raw) > 30 else "")
                    break
        if not title:
            title = "Untitled Chat"

        self.db.save_chat(chat_id, title, timestamp, messages)
        return {"id": chat_id, "title": title, "timestamp": timestamp, "messages": messages}

    def delete_chat(self, chat_id):
        self.db.delete_chat(chat_id)

    def rename_chat(self, chat_id, title):
        self.db.rename_chat(chat_id, title)

    def clear_all_chats(self):
        self.db.clear_all()

    def get_chat(self, chat_id):
        all_chats = self.db.get_all_chats()
        for chat in all_chats:
            if chat["id"] == chat_id:
                chat["messages"] = self.db.get_chat_messages(chat_id)
                return chat
        return None
        
    def get_messages(self, chat_id):
        return self.db.get_chat_messages(chat_id)
