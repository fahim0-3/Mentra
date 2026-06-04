import sqlite3

class DatabaseManager:
    def __init__(self, db_path="mentra_history.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Chats table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chats (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            # Messages table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (chat_id) REFERENCES chats (id) ON DELETE CASCADE
                )
            """)
            # Indexing for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages (chat_id)")
            conn.commit()

    def get_all_chats(self):
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, timestamp FROM chats ORDER BY timestamp DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_chat_messages(self, chat_id):
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id ASC", (chat_id,))
            return [dict(row) for row in cursor.fetchall()]

    def save_chat(self, chat_id, title, timestamp, messages):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Upsert chat
            cursor.execute("""
                INSERT INTO chats (id, title, timestamp)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    timestamp = excluded.timestamp
            """, (chat_id, title, timestamp))
            
            # Simplified message persistence: Clear and re-add for this prototype
            # In a larger app, we'd only append new messages.
            cursor.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
            for msg in messages:
                cursor.execute("""
                    INSERT INTO messages (chat_id, role, content, timestamp)
                    VALUES (?, ?, ?, ?)
                """, (chat_id, msg["role"], msg["content"], timestamp))
            conn.commit()

    def delete_chat(self, chat_id):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
            conn.commit()

    def rename_chat(self, chat_id, title):
        with self._get_connection() as conn:
            conn.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))
            conn.commit()

    def clear_all(self):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM chats")
            conn.commit()
