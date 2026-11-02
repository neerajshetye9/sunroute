"""Deterministic Fairness Ledger for SunRoute.

Tracks compute contributed versus consumed per node (like net metering).
Guarantees a minimum service floor without blockchain overhead.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NodeLedgerEntry:
    contributed_tokens: int = 0
    consumed_tokens: int = 0
    requests_served: int = 0
    requests_originated: int = 0


class FairnessLedger:
    """In-memory, deterministic fairness accounting ledger."""

    def __init__(self, min_service_floor: float = 0.01):
        self.min_service_floor = min_service_floor
        self._entries: dict[str, NodeLedgerEntry] = {}

    def get_entry(self, node_id: str) -> NodeLedgerEntry:
        if node_id not in self._entries:
            self._entries[node_id] = NodeLedgerEntry()
        return self._entries[node_id]

    def record_served(self, node_id: str, tokens: int) -> None:
        """Record inference compute served by a node."""
        entry = self.get_entry(node_id)
        entry.contributed_tokens += tokens
        entry.requests_served += 1

    def record_originated(self, node_id: str, tokens: int) -> None:
        """Record inference compute requested by a node/site."""
        entry = self.get_entry(node_id)
        entry.consumed_tokens += tokens
        entry.requests_originated += 1

    def get_fairness_score(self, node_id: str) -> float:
        """Calculate a normalized fairness score (0.0 to 1.0) for a candidate node.

        A node that has contributed more than it consumed, or has been underserved,
        receives a higher score to encourage service parity.
        """
        entry = self.get_entry(node_id)

        # Net balance: contributed - consumed
        net_tokens = entry.contributed_tokens - entry.consumed_tokens

        # Baseline parity: 0 balance -> 0.5 score
        # Scale between 0.0 and 1.0 with sigmoid-like clamping
        if net_tokens >= 0:
            # Positive credit: scores from 0.5 to 1.0
            score = 0.5 + 0.5 * min(1.0, net_tokens / 10000.0)
        else:
            # Net deficit: scores from 0.1 to 0.5
            score = max(0.1, 0.5 + 0.4 * (net_tokens / 10000.0))

        # Underserved floor protection (H7): if total network requests > 10
        # and a node's share falls below min_service_floor, provide a starvation boost
        total_served = self.total_requests_served()
        if total_served > 10:
            share = entry.requests_served / total_served
            if share < self.min_service_floor:
                score = max(score, 0.85)

        return round(score, 3)

    def total_requests_served(self) -> int:
        return sum(e.requests_served for e in self._entries.values())
