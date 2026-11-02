"""Data models and schemas for SunRoute Router."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import yaml

from edge.schemas import NodeKind, NodeState


class PolicyType(str, Enum):
    PROPOSED = "proposed"
    CLOUD_ONLY = "cloud_only"
    EDGE_ONLY = "edge_only"
    FCFS = "fcfs"
    CASCADE = "cascade"


class HierarchyLevel(str, Enum):
    LOCAL = "local"
    CITY = "city"
    REGION = "region"
    CLOUD = "cloud"
    NONE = "none"


@dataclass(frozen=True)
class ScoreBreakdown:
    energy: float = 0.0
    capacity: float = 0.0
    latency: float = 0.0
    locality: float = 0.0
    fairness: float = 0.0
    cloud_penalty: float = 0.0
    total_score: float = 0.0


@dataclass(frozen=True)
class Decision:
    """Immutable routing decision output per CLAUDE.md Section 6."""

    target_node_id: str | None
    target_kind: NodeKind
    target_level: HierarchyLevel
    score_breakdown: ScoreBreakdown
    reason: str
    policy_used: PolicyType
    timestamp_iso: str
    selected_node_state: NodeState | None = None


@dataclass
class RouterConfig:
    """Loaded configuration for routing policies, thresholds, and weights."""

    # Scoring weights
    w_energy: float = 0.25
    w_capacity: float = 0.20
    w_latency: float = 0.20
    w_locality: float = 0.15
    w_fairness: float = 0.10
    w_cloud_penalty: float = 0.10

    # Hard filter thresholds
    min_free_mem_mb: float = 500.0
    max_gpu_util: float = 0.95
    max_queue_depth: int = 10
    max_temp_c: float = 80.0
    min_battery_soc: float = 0.20
    critical_battery_soc: float = 0.10
    telemetry_ttl_s: float = 30.0
    surplus_threshold_w: float = 2.0

    # Hierarchy and sampling
    sample_size: int = 2
    levels: list[str] = field(default_factory=lambda: ["local", "city", "region", "cloud"])

    @classmethod
    def from_yaml(cls, yaml_path: str) -> RouterConfig:
        with open(yaml_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        r_cfg = raw.get("routing", {})
        weights = r_cfg.get("weights", {})
        filters = r_cfg.get("filters", {})
        energy = raw.get("energy", {})

        return cls(
            w_energy=weights.get("energy", 0.25),
            w_capacity=weights.get("capacity", 0.20),
            w_latency=weights.get("latency", 0.20),
            w_locality=weights.get("locality", 0.15),
            w_fairness=weights.get("fairness", 0.10),
            w_cloud_penalty=weights.get("cloud_penalty", 0.10),
            min_free_mem_mb=filters.get("min_free_mem_mb", 500.0),
            max_gpu_util=filters.get("max_gpu_util", 0.95),
            max_queue_depth=filters.get("max_queue_depth", 10),
            max_temp_c=filters.get("max_temp_c", 80.0),
            min_battery_soc=filters.get("min_battery_soc", 0.20),
            critical_battery_soc=filters.get("critical_battery_soc", 0.10),
            telemetry_ttl_s=filters.get("telemetry_ttl_s", 30.0),
            surplus_threshold_w=energy.get("surplus_threshold_w", 2.0),
            sample_size=r_cfg.get("sample_size", 2),
            levels=r_cfg.get("levels", ["local", "city", "region", "cloud"]),
        )
