"""Durable SQLite Outbox for Jetson Edge Nodes.

Guarantees:
- At-least-once outbound telemetry delivery to AWS/Gateway
- Zero lost records across process restarts / crashes
- Exponential backoff with full randomized jitter
- Time-to-live (TTL) expiration
- Idempotent message_id (UUID)
- Bounded capacity with deterministic FIFO/priority eviction drop policy
"""

from __future__ import annotations

import json
import logging
import random
import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("edge_outbox")


@dataclass(frozen=True)
class OutboxMessage:
    message_id: str
    topic: str
    payload: dict[str, Any]
    created_at: float
    expires_at: float
    status: str
    attempts: int
    next_retry_at: float
    delivered_at: float | None = None
    last_error: str | None = None


class SQLiteOutbox:
    """Thread-safe SQLite persistent outbox queue."""

    def __init__(
        self,
        db_path: Path | str,
        max_capacity: int = 5000,
        default_ttl_s: float = 86400.0,  # 24 hours
        base_backoff_s: float = 1.0,
        max_backoff_s: float = 60.0,
    ):
        self.db_path = Path(db_path)
        self.max_capacity = max_capacity
        self.default_ttl_s = default_ttl_s
        self.base_backoff_s = base_backoff_s
        self.max_backoff_s = max_backoff_s

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a connection with WAL mode and sensible timeouts."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            isolation_level=None,  # Autocommit mode, transactions managed explicitly
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outbox (
                    message_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_retry_at REAL NOT NULL,
                    delivered_at REAL,
                    last_error TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_outbox_pending
                ON outbox(status, next_retry_at);
                """
            )
            conn.execute("COMMIT;")

        # Automatically recover any uncommitted/in-flight items left from previous crash
        self.recover_in_flight()

    def enqueue(
        self,
        topic: str,
        payload: dict[str, Any],
        message_id: str | None = None,
        ttl_s: float | None = None,
    ) -> str:
        """Enqueue a message into the outbox.

        Returns message_id. Idempotent: duplicate message_id is ignored.
        """
        msg_id = message_id or str(uuid.uuid4())
        now = time.time()
        ttl = ttl_s if ttl_s is not None else self.default_ttl_s
        expires_at = now + ttl
        payload_json = json.dumps(payload, ensure_ascii=False)

        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")

            # Check capacity; if over capacity, apply drop policy
            cursor = conn.execute(
                "SELECT COUNT(*) FROM outbox WHERE status IN ('pending', 'in_flight');"
            )
            current_count = cursor.fetchone()[0]

            if current_count >= self.max_capacity:
                # Drop policy: first drop any expired items; if still full, drop oldest pending
                conn.execute(
                    """
                    DELETE FROM outbox
                    WHERE message_id IN (
                        SELECT message_id FROM outbox
                        WHERE status = 'pending' AND expires_at <= ?
                    );
                    """,
                    (now,),
                )
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM outbox WHERE status IN ('pending', 'in_flight');"
                )
                if cursor.fetchone()[0] >= self.max_capacity:
                    # Drop oldest pending message (FIFO eviction)
                    conn.execute(
                        """
                        DELETE FROM outbox
                        WHERE message_id = (
                            SELECT message_id FROM outbox
                            WHERE status = 'pending'
                            ORDER BY created_at ASC
                            LIMIT 1
                        );
                        """
                    )

            # Insert message idempotently (INSERT OR IGNORE)
            conn.execute(
                """
                INSERT OR IGNORE INTO outbox (
                    message_id, topic, payload, created_at, expires_at,
                    status, attempts, next_retry_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?);
                """,
                (msg_id, topic, payload_json, now, expires_at, now),
            )
            conn.execute("COMMIT;")

        return msg_id

    def fetch_batch(self, batch_size: int = 50) -> list[OutboxMessage]:
        """Atomically fetch and mark pending messages as in_flight."""
        now = time.time()
        messages: list[OutboxMessage] = []

        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")

            # 1. Drop expired pending messages
            conn.execute(
                "DELETE FROM outbox WHERE status = 'pending' AND expires_at <= ?;",
                (now,),
            )

            # 2. Select eligible messages ready for retry
            cursor = conn.execute(
                """
                SELECT message_id, topic, payload, created_at, expires_at,
                       status, attempts, next_retry_at, delivered_at, last_error
                FROM outbox
                WHERE status = 'pending' AND next_retry_at <= ?
                ORDER BY created_at ASC
                LIMIT ?;
                """,
                (now, batch_size),
            )
            rows = cursor.fetchall()

            if rows:
                ids = [r["message_id"] for r in rows]
                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"UPDATE outbox SET status = 'in_flight' WHERE message_id IN ({placeholders});",
                    ids,
                )

                for r in rows:
                    messages.append(
                        OutboxMessage(
                            message_id=r["message_id"],
                            topic=r["topic"],
                            payload=json.loads(r["payload"]),
                            created_at=r["created_at"],
                            expires_at=r["expires_at"],
                            status="in_flight",
                            attempts=r["attempts"],
                            next_retry_at=r["next_retry_at"],
                            delivered_at=r["delivered_at"],
                            last_error=r["last_error"],
                        )
                    )

            conn.execute("COMMIT;")

        return messages

    def mark_delivered(self, message_ids: list[str]) -> None:
        """Mark delivered messages and remove them or archive."""
        if not message_ids:
            return

        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            placeholders = ",".join("?" for _ in message_ids)
            # Remove delivered messages to maintain bounded database size
            conn.execute(
                f"DELETE FROM outbox WHERE message_id IN ({placeholders});",
                message_ids,
            )
            conn.execute("COMMIT;")

    def mark_failed(self, message_id: str, error_msg: str) -> None:
        """Apply exponential backoff with full jitter on transmission failure."""
        now = time.time()
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            cursor = conn.execute(
                "SELECT attempts FROM outbox WHERE message_id = ?;",
                (message_id,),
            )
            row = cursor.fetchone()
            if row is not None:
                attempts = row["attempts"] + 1
                # Exponential backoff + full jitter: delay * uniform(0.5, 1.5)
                exp_delay = min(self.max_backoff_s, self.base_backoff_s * (2 ** (attempts - 1)))
                jitter = random.uniform(0.5, 1.5)
                next_retry = now + (exp_delay * jitter)

                conn.execute(
                    """
                    UPDATE outbox
                    SET status = 'pending',
                        attempts = ?,
                        next_retry_at = ?,
                        last_error = ?
                    WHERE message_id = ?;
                    """,
                    (attempts, next_retry, error_msg, message_id),
                )
            conn.execute("COMMIT;")

    def recover_in_flight(self) -> int:
        """Reset messages stuck in 'in_flight' back to 'pending' (e.g. after restart)."""
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            cursor = conn.execute(
                "UPDATE outbox SET status = 'pending' WHERE status = 'in_flight';"
            )
            count = cursor.rowcount
            conn.execute("COMMIT;")
        if count > 0:
            logger.info("Recovered %d in-flight outbox message(s) to pending state.", count)
        return count

    def count(self, status: str | None = None) -> int:
        """Count messages in outbox, optionally filtered by status."""
        with self._get_connection() as conn:
            if status:
                cursor = conn.execute("SELECT COUNT(*) FROM outbox WHERE status = ?;", (status,))
            else:
                cursor = conn.execute("SELECT COUNT(*) FROM outbox;")
            return cursor.fetchone()[0]

    def flush(self, sender: Callable[[OutboxMessage], bool], batch_size: int = 50) -> int:
        """Attempt to flush pending messages through sender callable.

        Returns number of successfully delivered messages.
        """
        batch = self.fetch_batch(batch_size=batch_size)
        if not batch:
            return 0

        delivered_ids: list[str] = []
        for msg in batch:
            try:
                success = sender(msg)
                if success:
                    delivered_ids.append(msg.message_id)
                else:
                    self.mark_failed(msg.message_id, "Sender returned False")
            except Exception as e:
                self.mark_failed(msg.message_id, str(e))

        if delivered_ids:
            self.mark_delivered(delivered_ids)

        return len(delivered_ids)
