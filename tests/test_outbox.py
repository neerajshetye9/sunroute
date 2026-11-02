"""Failure-injection and persistence tests for SQLite Outbox.

Tests:
1. Normal lifecycle: enqueue -> fetch -> deliver
2. Network failure injection: backoff with jitter, retry attempts, zero data loss
3. Idempotent delivery: duplicate message_id deduplication
4. Disk full / capacity limit: drop policy execution under bounded storage
5. Crash / Restart mid-flush: recovery of in-flight records with zero data loss
6. Expiry TTL: automatic pruning of stale telemetry
"""

import time
import uuid
from pathlib import Path

import pytest

from edge.outbox import SQLiteOutbox


@pytest.fixture
def outbox(tmp_path: Path):
    db_file = tmp_path / "test_outbox.db"
    return SQLiteOutbox(db_path=db_file, max_capacity=10, base_backoff_s=0.1, max_backoff_s=1.0)


def test_outbox_lifecycle(outbox: SQLiteOutbox):
    # Enqueue
    payload = {"node_id": "jetson-01", "temp_c": 52.0}
    msg_id = outbox.enqueue("telemetry", payload)
    assert outbox.count("pending") == 1

    # Fetch batch
    batch = outbox.fetch_batch(batch_size=10)
    assert len(batch) == 1
    assert batch[0].message_id == msg_id
    assert batch[0].payload == payload
    assert batch[0].status == "in_flight"

    # Mark delivered
    outbox.mark_delivered([msg_id])
    assert outbox.count() == 0


def test_failure_injection_network_down(outbox: SQLiteOutbox):
    """Failure test 1: Simulated network failure with backoff and zero data loss."""
    msg_id = outbox.enqueue("telemetry", {"status": "event"})
    assert outbox.count("pending") == 1

    # Attempt flush with a failing sender (simulating connection timeout / AWS down)
    def failing_sender(_msg):
        raise ConnectionError("AWS API Gateway unreachable: simulated network partition")

    delivered = outbox.flush(failing_sender)
    assert delivered == 0

    # Message must NOT be lost; it should be back in 'pending' with incremented attempts
    batch = outbox.fetch_batch(batch_size=10)
    # Because backoff delay is applied, it won't be ready immediately
    assert len(batch) == 0

    # Verify database state
    with outbox._get_connection() as conn:
        cursor = conn.execute(
            "SELECT attempts, status, last_error, next_retry_at FROM outbox WHERE message_id = ?;",
            (msg_id,),
        )
        row = cursor.fetchone()
        assert row["status"] == "pending"
        assert row["attempts"] == 1
        assert "AWS API Gateway unreachable" in row["last_error"]
        assert row["next_retry_at"] > time.time()

    # Total record count is preserved (zero data loss)
    assert outbox.count() == 1


def test_failure_injection_duplicate_delivery(outbox: SQLiteOutbox):
    """Failure test 2: Idempotent message_id deduplication."""
    fixed_id = str(uuid.uuid4())
    payload = {"reading": 42}

    # Enqueue same ID twice
    id1 = outbox.enqueue("telemetry", payload, message_id=fixed_id)
    id2 = outbox.enqueue("telemetry", payload, message_id=fixed_id)

    assert id1 == fixed_id
    assert id2 == fixed_id

    # Queue must only hold 1 record
    assert outbox.count() == 1


def test_failure_injection_bounded_capacity_drop_policy(tmp_path: Path):
    """Failure test 3: Bounded capacity enforcement and drop policy."""
    db_file = tmp_path / "bounded_outbox.db"
    # Small capacity of 3 items
    bounded_outbox = SQLiteOutbox(db_path=db_file, max_capacity=3)

    # Enqueue 3 items
    id1 = bounded_outbox.enqueue("topic", {"item": 1})
    time.sleep(0.01)
    bounded_outbox.enqueue("topic", {"item": 2})
    time.sleep(0.01)
    bounded_outbox.enqueue("topic", {"item": 3})

    assert bounded_outbox.count() == 3

    # Enqueue 4th item (exceeds capacity=3)
    id4 = bounded_outbox.enqueue("topic", {"item": 4})

    # Total must stay at or below capacity
    assert bounded_outbox.count() == 3

    # Oldest item (id1) was evicted by FIFO drop policy
    with bounded_outbox._get_connection() as conn:
        cursor = conn.execute("SELECT message_id FROM outbox ORDER BY created_at ASC;")
        remaining_ids = [r["message_id"] for r in cursor.fetchall()]
        assert id1 not in remaining_ids
        assert id4 in remaining_ids


def test_failure_injection_restart_mid_flush(tmp_path: Path):
    """Failure test 4: Sudden crash/restart mid-flush recovers in-flight records with zero loss."""
    db_file = tmp_path / "crash_test.db"
    outbox1 = SQLiteOutbox(db_path=db_file)

    msg_id = outbox1.enqueue("telemetry", {"critical_metric": 100})

    # Fetch batch -> marks status as 'in_flight'
    batch = outbox1.fetch_batch(batch_size=1)
    assert len(batch) == 1
    assert batch[0].status == "in_flight"

    # Simulate abrupt process death (do not call mark_delivered or mark_failed)
    # Process restarts: new SQLiteOutbox instance opens the same database
    outbox2 = SQLiteOutbox(db_path=db_file)

    # During initialization, recover_in_flight() resets in_flight to pending
    assert outbox2.count("pending") == 1
    assert outbox2.count("in_flight") == 0

    # Ensure message is intact and ready to be delivered
    recovered_batch = outbox2.fetch_batch(batch_size=1)
    assert len(recovered_batch) == 1
    assert recovered_batch[0].message_id == msg_id
    assert recovered_batch[0].payload["critical_metric"] == 100


def test_expiry_ttl_pruning(outbox: SQLiteOutbox):
    """Failure test 5: Messages past their TTL are pruned and not dispatched."""
    # Enqueue with 0.05s TTL
    outbox.enqueue("ephemeral", {"temp": 25}, ttl_s=0.05)
    time.sleep(0.1)

    # Fetch should prune expired message
    batch = outbox.fetch_batch(batch_size=10)
    assert len(batch) == 0
    assert outbox.count() == 0
