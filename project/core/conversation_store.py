"""本地聊天记录与模型记忆。每次操作独立连接，重启应用后仍可继续对话。"""

import json
from pathlib import Path
import sqlite3
import uuid
from contextlib import contextmanager

import config


def is_process_message(message):
    return message.get("role") == "assistant" and (message.get("metadata") or {}).get("title") == "处理过程"


def conversation_messages(messages):
    return [message for message in normalize_history(messages) if not is_process_message(message)]


def normalize_history(messages):
    """Gradio 6 会把纯文本包装成内容块；存储与模型统一使用文本。"""
    result = []
    for message in messages or []:
        if message.get("role") not in {"user", "assistant"}:
            continue
        content = message.get("content", "")
        if isinstance(content, list):
            content = "\n".join(block.get("text", "") for block in content
                                if isinstance(block, dict) and block.get("type") == "text")
        if isinstance(content, str):
            normalized = {"role": message["role"], "content": content}
            if is_process_message(message):
                normalized["metadata"] = {key: value for key, value in message["metadata"].items()
                                          if key in {"title", "id", "status", "duration"}}
            result.append(normalized)
    return result


class ConversationStore:
    def __init__(self, path=None):
        self.path = Path(path or config.CHAT_HISTORY_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, messages TEXT NOT NULL,
                memory TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            connection.execute("CREATE TABLE IF NOT EXISTS deleted_conversations (id TEXT PRIMARY KEY)")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def new_id():
        return str(uuid.uuid4())

    def list_conversations(self):
        with self._connect() as connection:
            return connection.execute(
                "SELECT title, id FROM conversations ORDER BY updated_at DESC, rowid DESC"
            ).fetchall()

    def get(self, conversation_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT title, messages, memory FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        if not row:
            return {"title": "新的对话", "messages": [], "memory": {}}
        return {"title": row[0], "messages": normalize_history(json.loads(row[1])), "memory": json.loads(row[2])}

    def save(self, conversation_id, messages, memory):
        messages = normalize_history(messages)
        title = next((message["content"].strip().replace("\n", " ")[:24]
                      for message in messages if message["role"] == "user"), "新的对话")
        with self._connect() as connection:
            if connection.execute("SELECT 1 FROM deleted_conversations WHERE id=?", (conversation_id,)).fetchone():
                raise ValueError("此对话已删除，请新建对话。")
            connection.execute("""INSERT INTO conversations VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%f','now'))
                ON CONFLICT(id) DO UPDATE SET title=excluded.title, messages=excluded.messages,
                memory=excluded.memory, updated_at=excluded.updated_at""",
                (conversation_id, title, json.dumps(messages, ensure_ascii=False),
                 json.dumps(memory, ensure_ascii=False)))

    def exists(self, conversation_id):
        with self._connect() as connection:
            return bool(connection.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone())

    def is_deleted(self, conversation_id):
        with self._connect() as connection:
            return bool(connection.execute("SELECT 1 FROM deleted_conversations WHERE id=?", (conversation_id,)).fetchone())

    def delete(self, conversation_id):
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
            if cursor.rowcount:
                connection.execute("INSERT OR IGNORE INTO deleted_conversations VALUES (?)", (conversation_id,))
                return True
        return False
