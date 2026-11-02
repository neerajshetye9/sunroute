"""Unit tests for SunRoute Pure Router.

Tests all edge cases from CLAUDE.md Section 10:
- All nodes ineligible
- Stale telemetry filtering
- SOC at the reserve floor
- Privacy local_only enforcement
- Hierarchical escalation (local -> city -> region -> cloud)
- Power of two choices
- Fairness ledger mechanism
- Baseline policies (cloud_only, edge_only, fcfs, cascade)
- Configuration loading from YAML
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from edge.schemas import (
    ConnectivityStatus,
    EnergySource,
    InferenceRequest,
    NodeKind,
    NodeState,
    Origin,
    Priority,
    Privacy,
    QualityTier,
    TaskType,
)
from router.core import route
from router.filters import is_node_eligible
from router.ledger import FairnessLedger
from router.schemas import HierarchyLevel, PolicyType, RouterConfig


def make_request(
    origin_city: str = "city-01",
    origin_site: str = "society-12",
    prompt_tokens: int = 100,
    priority: Priority = Priority.NORMAL,
    privacy: Privacy = Privacy.ANY,
    task_type: TaskType = TaskType.SHORT_QA,
) -> InferenceRequest:
    return InferenceRequest(
        request_id=uuid.uuid4(),
        created_at=datetime.now(UTC),
        origin=Origin(city=origin_city, site=origin_site),
        task_type=task_type,
        prompt_tokens_est=prompt_tokens,
        max_output_tokens=64,
        latency_target_ms=2000,
        priority=priority,
        privacy=privacy,
        min_quality_tier=QualityTier.BASIC,
        prompt="Explain community microgrids.",
    )


def make_node(
    node_id: str = "node-01",
    city: str = "city-01",
    kind: NodeKind = NodeKind.PHYSICAL,
    soc: float = 0.80,
    temp_c: float = 50.0,
    free_mem_mb: float = 3500.0,
    queue_depth: int = 1,
    solar_w: float = 10.0,
    load_w: float = 6.0,
    connectivity: ConnectivityStatus = ConnectivityStatus.ONLINE,
    ts: datetime | None = None,
) -> NodeState:
    return NodeState(
        node_id=node_id,
        city=city,
        kind=kind,
        models=["qwen-1.5b"],
        free_mem_mb=free_mem_mb,
        gpu_util=0.3,
        queue_depth=queue_depth,
        temp_c=temp_c,
        battery_soc=soc,
        solar_w=solar_w,
        wind_w=1.0,
        load_w=load_w,
        connectivity=connectivity,
        energy_source=EnergySource.MEASURED,
        ts=ts or datetime.now(UTC),
    )


def make_cloud_node() -> NodeState:
    return make_node(
        node_id="aws-cloud-01",
        city="capital-dc",
        kind=NodeKind.CLOUD,
        soc=1.0,
        temp_c=35.0,
        free_mem_mb=64000.0,
        queue_depth=0,
        solar_w=0.0,
        load_w=200.0,
    )


def test_yaml_config_loading():
    config_path = Path(__file__).resolve().parent.parent / "config" / "default.yaml"
    cfg = RouterConfig.from_yaml(str(config_path))
    assert cfg.w_energy == 0.25
    assert cfg.w_capacity == 0.20
    assert cfg.min_battery_soc == 0.20
    assert cfg.sample_size == 2


def test_edge_case_stale_telemetry():
    cfg = RouterConfig(telemetry_ttl_s=30.0)
    req = make_request()
    now_ts = 1000.0

    # Node reported 45 seconds ago (exceeds 30s TTL)
    old_time = datetime.fromtimestamp(now_ts - 45.0, UTC)
    stale_node = make_node(ts=old_time)

    ok, reason = is_node_eligible(req, stale_node, cfg, now_ts)
    assert not ok
    assert "stale" in reason.lower()


def test_edge_case_soc_at_floor():
    cfg = RouterConfig(min_battery_soc=0.20, surplus_threshold_w=2.0)
    now_ts = 1000.0
    now_dt = datetime.fromtimestamp(now_ts, UTC)

    # Battery at 15%, no surplus (solar 2W < load 5W)
    low_bat_node = make_node(soc=0.15, solar_w=2.0, load_w=5.0, ts=now_dt)

    # Normal request -> rejected
    req_normal = make_request(priority=Priority.NORMAL)
    ok, reason = is_node_eligible(req_normal, low_bat_node, cfg, now_ts)
    assert not ok
    assert "reserve floor" in reason.lower()

    # Essential request -> admitted
    req_essential = make_request(priority=Priority.ESSENTIAL)
    ok_ess, _ = is_node_eligible(req_essential, low_bat_node, cfg, now_ts)
    assert ok_ess


def test_edge_case_privacy_local_only():
    cfg = RouterConfig()
    now_ts = 1000.0
    now_dt = datetime.fromtimestamp(now_ts, UTC)
    req_local = make_request(origin_city="city-01", privacy=Privacy.LOCAL_ONLY)

    # Cross-city node
    remote_node = make_node(city="city-02", ts=now_dt)
    ok, reason = is_node_eligible(req_local, remote_node, cfg, now_ts)
    assert not ok
    assert "local_only" in reason.lower()

    # Cloud node
    cloud = make_cloud_node()
    cloud.ts = now_dt
    ok_c, reason_c = is_node_eligible(req_local, cloud, cfg, now_ts)
    assert not ok_c
    assert "disallows cloud" in reason_c.lower()


def test_edge_case_all_nodes_ineligible():
    req = make_request(privacy=Privacy.LOCAL_ONLY)
    now_ts = 1000.0
    now_dt = datetime.fromtimestamp(now_ts, UTC)

    # Only node is offline
    offline_node = make_node(connectivity=ConnectivityStatus.OFFLINE, ts=now_dt)
    cloud = make_cloud_node()
    cloud.ts = now_dt

    decision = route(
        request=req,
        node_states=[offline_node],
        cloud_state=cloud,
        policy=PolicyType.PROPOSED,
        now=now_ts,
    )

    assert decision.target_node_id is None
    assert decision.target_level == HierarchyLevel.NONE
    assert "No eligible nodes" in decision.reason


def test_hierarchical_escalation_local_to_region():
    now_ts = 1000.0
    now_dt = datetime.fromtimestamp(now_ts, UTC)
    req = make_request(origin_city="city-01")

    # City-01 nodes are full (queue depth 10)
    local_full = make_node(node_id="n-local", city="city-01", queue_depth=10, ts=now_dt)
    # Regional city-02 node has spare capacity
    region_avail = make_node(node_id="n-region", city="city-02", queue_depth=0, ts=now_dt)
    cloud = make_cloud_node()
    cloud.ts = now_dt

    decision = route(
        request=req,
        node_states=[local_full, region_avail],
        cloud_state=cloud,
        policy=PolicyType.PROPOSED,
        now=now_ts,
    )

    assert decision.target_node_id == "n-region"
    assert decision.target_level == HierarchyLevel.REGION
    assert "regional" in decision.reason.lower()


def test_hierarchical_escalation_to_cloud_fallback():
    now_ts = 1000.0
    now_dt = datetime.fromtimestamp(now_ts, UTC)
    req = make_request(origin_city="city-01")

    # All edge nodes full
    node1 = make_node(node_id="n1", city="city-01", queue_depth=10, ts=now_dt)
    node2 = make_node(node_id="n2", city="city-02", queue_depth=10, ts=now_dt)
    cloud = make_cloud_node()
    cloud.ts = now_dt

    decision = route(
        request=req,
        node_states=[node1, node2],
        cloud_state=cloud,
        policy=PolicyType.PROPOSED,
        now=now_ts,
    )

    assert decision.target_node_id == "aws-cloud-01"
    assert decision.target_level == HierarchyLevel.CLOUD
    assert decision.target_kind == NodeKind.CLOUD


def test_power_of_two_choices():
    now_ts = 1000.0
    now_dt = datetime.fromtimestamp(now_ts, UTC)
    req = make_request(origin_city="city-01")

    # Two local nodes: node_a high battery (90%), node_b low battery (30%)
    node_a = make_node(node_id="nodeA", city="city-01", soc=0.90, ts=now_dt)
    node_b = make_node(node_id="nodeB", city="city-01", soc=0.30, ts=now_dt)

    decision = route(
        request=req,
        node_states=[node_a, node_b],
        policy=PolicyType.PROPOSED,
        now=now_ts,
        random_seed=42,
    )

    # node_a has higher energy score, must be selected
    assert decision.target_node_id == "nodeA"
    assert decision.score_breakdown.energy > 0.8


def test_fairness_ledger_score_boost():
    ledger = FairnessLedger()
    # node-favored has served 1000 tokens, consumed 0 (high positive balance)
    ledger.record_served("node-favored", 1000)
    # node-deficit has served 0, consumed 5000 (net deficit)
    ledger.record_originated("node-deficit", 5000)

    score_favored = ledger.get_fairness_score("node-favored")
    score_deficit = ledger.get_fairness_score("node-deficit")

    assert score_favored > score_deficit
    assert 0.0 <= score_deficit <= 1.0
    assert 0.0 <= score_favored <= 1.0


def test_baseline_cloud_only():
    req = make_request()
    edge = make_node()
    cloud = make_cloud_node()

    decision = route(
        request=req,
        node_states=[edge],
        cloud_state=cloud,
        policy=PolicyType.CLOUD_ONLY,
    )
    assert decision.target_node_id == "aws-cloud-01"
    assert decision.policy_used == PolicyType.CLOUD_ONLY


def test_baseline_edge_only_rejection():
    req = make_request()
    now_ts = 1000.0
    now_dt = datetime.fromtimestamp(now_ts, UTC)
    # All edge nodes full
    edge_full = make_node(queue_depth=10, ts=now_dt)
    cloud = make_cloud_node()
    cloud.ts = now_dt

    decision = route(
        request=req,
        node_states=[edge_full],
        cloud_state=cloud,
        policy=PolicyType.EDGE_ONLY,
        now=now_ts,
    )
    assert decision.target_node_id is None
    assert decision.target_level == HierarchyLevel.NONE
    assert "edge_only" in decision.reason


def test_baseline_cascade():
    edge = make_node(city="city-01")
    cloud = make_cloud_node()

    # Short query -> edge
    short_req = make_request(prompt_tokens=50, task_type=TaskType.SHORT_QA)
    d_short = route(short_req, [edge], cloud, policy=PolicyType.CASCADE)
    assert d_short.target_node_id == edge.node_id
    assert d_short.target_level == HierarchyLevel.LOCAL

    # Long query (> 256 tokens) -> cascade to cloud
    long_req = make_request(prompt_tokens=512, task_type=TaskType.LONG_FORM)
    d_long = route(long_req, [edge], cloud, policy=PolicyType.CASCADE)
    assert d_long.target_node_id == cloud.node_id
    assert d_long.target_level == HierarchyLevel.CLOUD
