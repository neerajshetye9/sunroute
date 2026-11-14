"""Persistent chat store and user manager for SunRoute ChatGPT applications.

Maintains users, conversation sessions, and messages in SQLite with full
routing metadata, attachments, and multi-user isolation.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ChatUser(BaseModel):
    user_id: str
    username: str
    display_name: str
    role: str = "student"  # "student", "researcher", "citizen", "admin"
    default_city: str = "city-02"  # e.g. Pune
    avatar_url: str | None = None


class ChatAttachment(BaseModel):
    name: str
    size: int
    mime_type: str
    data_url: str | None = None  # Base64 data for preview/multimodal


class ChatMessageRecord(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str
    user_id: str
    sender: str  # "user" | "assistant" | "system"
    text: str
    attachments: list[ChatAttachment] = Field(default_factory=list)
    routing_metadata: dict[str, Any] | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ConversationRecord(BaseModel):
    conversation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    title: str = "New Chat"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    message_count: int = 0


DEFAULT_USERS: list[ChatUser] = [
    ChatUser(
        user_id="user-student-01",
        username="student",
        display_name="Aarav Sharma (COEP Pune)",
        role="student",
        default_city="city-02",  # Pune
    ),
    ChatUser(
        user_id="user-researcher-02",
        username="researcher",
        display_name="Dr. Priya Patel (IIT Bombay)",
        role="researcher",
        default_city="city-01",  # Mumbai
    ),
    ChatUser(
        user_id="user-citizen-03",
        username="citizen",
        display_name="Kavita Rao (Nashik Citizen)",
        role="citizen",
        default_city="city-05",  # Nashik
    ),
    ChatUser(
        user_id="user-admin-04",
        username="admin",
        display_name="System Admin (Fleet Ops)",
        role="admin",
        default_city="city-01",  # Mumbai
    ),
]


class ChatStore:
    """Thread-safe SQLite store for multi-user chat sessions and messages."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    default_city TEXT NOT NULL,
                    avatar_url TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    text TEXT NOT NULL,
                    attachments_json TEXT,
                    routing_metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_conv
                ON messages(conversation_id, created_at);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conv_user
                ON conversations(user_id, updated_at DESC);
                """
            )

            # Seed default demo users
            now_iso = datetime.now(UTC).isoformat()
            for u in DEFAULT_USERS:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO users (
                        user_id, username, display_name, role, default_city, avatar_url, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        u.user_id,
                        u.username,
                        u.display_name,
                        u.role,
                        u.default_city,
                        u.avatar_url,
                        now_iso,
                    ),
                )
            conn.execute("COMMIT;")

    def list_users(self) -> list[ChatUser]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM users ORDER BY rowid ASC;")
            return [ChatUser(**dict(r)) for r in cur.fetchall()]

    def get_or_create_user(
        self,
        username: str,
        display_name: str | None = None,
        role: str = "student",
        default_city: str = "city-02",
    ) -> ChatUser:
        clean_user = username.strip().lower()
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM users WHERE username = ?;", (clean_user,))
            row = cur.fetchone()
            if row:
                return ChatUser(**dict(row))
            uid = f"user-{clean_user}-{uuid.uuid4().hex[:6]}"
            disp = display_name or clean_user.capitalize()
            now_iso = datetime.now(UTC).isoformat()
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                """
                INSERT INTO users (
                    user_id, username, display_name, role, default_city, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (uid, clean_user, disp, role, default_city, now_iso),
            )
            conn.execute("COMMIT;")
            return ChatUser(
                user_id=uid,
                username=clean_user,
                display_name=disp,
                role=role,
                default_city=default_city,
            )

    def list_conversations(self, user_id: str) -> list[ConversationRecord]:
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT c.*, COUNT(m.message_id) AS message_count
                FROM conversations c
                LEFT JOIN messages m ON c.conversation_id = m.conversation_id
                WHERE c.user_id = ?
                GROUP BY c.conversation_id
                ORDER BY c.updated_at DESC;
                """,
                (user_id,),
            )
            results: list[ConversationRecord] = []
            for r in cur.fetchall():
                d = dict(r)
                cnt = d.pop("message_count", 0)
                rec = ConversationRecord(**d)
                rec.message_count = cnt
                results.append(rec)
            return results

    def create_conversation(self, user_id: str, title: str = "New Chat") -> ConversationRecord:
        conv_id = str(uuid.uuid4())
        now_iso = datetime.now(UTC).isoformat()
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                """
                INSERT INTO conversations (conversation_id, user_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (conv_id, user_id, title, now_iso, now_iso),
            )
            conn.execute("COMMIT;")
        return ConversationRecord(
            conversation_id=conv_id,
            user_id=user_id,
            title=title,
            created_at=now_iso,
            updated_at=now_iso,
            message_count=0,
        )

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM conversations WHERE conversation_id = ?;",
                (conversation_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return ConversationRecord(**dict(row))

    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        now_iso = datetime.now(UTC).isoformat()
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE conversation_id = ?;",
                (title, now_iso, conversation_id),
            )
            conn.execute("COMMIT;")

    def delete_conversation(self, conversation_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute("DELETE FROM messages WHERE conversation_id = ?;", (conversation_id,))
            conn.execute("DELETE FROM conversations WHERE conversation_id = ?;", (conversation_id,))
            conn.execute("COMMIT;")

    def list_messages(self, conversation_id: str) -> list[ChatMessageRecord]:
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC;",
                (conversation_id,),
            )
            messages: list[ChatMessageRecord] = []
            for r in cur.fetchall():
                d = dict(r)
                att_str = d.pop("attachments_json", None)
                rout_str = d.pop("routing_metadata_json", None)
                attachments = [ChatAttachment(**a) for a in json.loads(att_str)] if att_str else []
                routing_metadata = json.loads(rout_str) if rout_str else None
                messages.append(
                    ChatMessageRecord(
                        **d,
                        attachments=attachments,
                        routing_metadata=routing_metadata,
                    )
                )
            return messages

    def append_message(self, msg: ChatMessageRecord) -> None:
        now_iso = datetime.now(UTC).isoformat()
        att_json = (
            json.dumps([a.model_dump() for a in msg.attachments]) if msg.attachments else None
        )
        rout_json = json.dumps(msg.routing_metadata) if msg.routing_metadata else None

        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                """
                INSERT INTO messages (
                    message_id, conversation_id, user_id, sender, text,
                    attachments_json, routing_metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    msg.message_id,
                    msg.conversation_id,
                    msg.user_id,
                    msg.sender,
                    msg.text,
                    att_json,
                    rout_json,
                    msg.created_at or now_iso,
                ),
            )
            # Bump conversation updated_at
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?;",
                (now_iso, msg.conversation_id),
            )
            conn.execute("COMMIT;")
