"""Append-only SQLite audit log for SunRoute routing decisions.

Guarantees full transparency and auditability: every query's routing path,
scores, reasons, and execution telemetry are permanently recorded.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

from edge.schemas import InferenceRequest
from router.schemas import Decision


class DecisionAuditLog:
    """Thread-safe append-only audit database for routing decisions."""

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
                CREATE TABLE IF NOT EXISTS decision_log (
                    decision_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    timestamp_iso TEXT NOT NULL,
                    policy_used TEXT NOT NULL,
                    target_node_id TEXT,
                    target_kind TEXT,
                    target_level TEXT,
                    score_total REAL,
                    score_energy REAL,
                    score_capacity REAL,
                    score_latency REAL,
                    score_locality REAL,
                    score_fairness REAL,
                    score_cloud_penalty REAL,
                    reason TEXT NOT NULL,
                    origin_city TEXT NOT NULL,
                    origin_site TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    prompt_tokens INTEGER,
                    max_output_tokens INTEGER,
                    execution_latency_ms REAL,
                    execution_success INTEGER NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_decision_req
                ON decision_log(request_id);
                """
            )
            conn.execute("COMMIT;")

    def record(
        self,
        decision: Decision,
        request: InferenceRequest,
        execution_latency_ms: float = 0.0,
        success: bool = True,
    ) -> str:
        """Append an auditable decision record to the log."""
        decision_id = str(uuid.uuid4())
        sb = decision.score_breakdown

        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                """
                INSERT INTO decision_log (
                    decision_id, request_id, timestamp_iso, policy_used,
                    target_node_id, target_kind, target_level,
                    score_total, score_energy, score_capacity, score_latency,
                    score_locality, score_fairness, score_cloud_penalty,
                    reason, origin_city, origin_site, task_type,
                    prompt_tokens, max_output_tokens, execution_latency_ms, execution_success
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    decision_id,
                    str(request.request_id),
                    decision.timestamp_iso,
                    decision.policy_used.value,
                    decision.target_node_id,
                    decision.target_kind.value if decision.target_kind else None,
                    decision.target_level.value,
                    sb.total_score,
                    sb.energy,
                    sb.capacity,
                    sb.latency,
                    sb.locality,
                    sb.fairness,
                    sb.cloud_penalty,
                    decision.reason,
                    request.origin.city,
                    request.origin.site,
                    request.task_type.value,
                    request.prompt_tokens_est,
                    request.max_output_tokens,
                    round(execution_latency_ms, 2),
                    1 if success else 0,
                ),
            )
            conn.execute("COMMIT;")

        return decision_id

    def list_decisions(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Retrieve recent routing decisions."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM decision_log
                ORDER BY rowid DESC
                LIMIT ? OFFSET ?;
                """,
                (limit, offset),
            )
            return [dict(r) for r in cursor.fetchall()]

    def count(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM decision_log;")
            return cursor.fetchone()[0]
