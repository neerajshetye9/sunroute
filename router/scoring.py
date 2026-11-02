"""Multi-objective candidate scoring for SunRoute router.

Computes normalized (0.0 - 1.0) scores across:
- Energy (battery SOC + surplus generation)
- Capacity (spare memory, queue availability, GPU headroom)
- Latency (estimated RTT + inference execution time vs latency target)
- Locality (geographical proximity to query origin)
- Fairness (ledger credit parity)
- Cloud penalty
"""

from __future__ import annotations

from edge.schemas import InferenceRequest, NodeKind, NodeState
from router.ledger import FairnessLedger
from router.schemas import HierarchyLevel, RouterConfig, ScoreBreakdown


def get_estimated_rtt_ms(level: HierarchyLevel) -> float:
    """Estimated network round-trip time in milliseconds per level."""
    if level == HierarchyLevel.LOCAL:
        return 5.0
    elif level == HierarchyLevel.CITY:
        return 20.0
    elif level == HierarchyLevel.REGION:
        return 65.0
    elif level == HierarchyLevel.CLOUD:
        return 120.0
    return 100.0


def score_candidate(
    request: InferenceRequest,
    node: NodeState,
    config: RouterConfig,
    level: HierarchyLevel,
    ledger: FairnessLedger | None = None,
) -> ScoreBreakdown:
    """Calculate normalized scores and weighted aggregate for a candidate node."""
    is_cloud = node.kind == NodeKind.CLOUD

    # 1. Energy score
    if is_cloud:
        energy_score = 0.20  # Standard grid data center baseline
    else:
        has_surplus = (node.solar_w + node.wind_w) > (node.load_w + config.surplus_threshold_w)
        surplus_boost = 0.25 if has_surplus else 0.0
        energy_score = min(1.0, node.battery_soc + surplus_boost)

    # 2. Capacity score
    free_mem_norm = min(1.0, node.free_mem_mb / 4000.0)
    queue_norm = max(0.0, 1.0 - (node.queue_depth / max(1, config.max_queue_depth)))
    gpu_norm = max(0.0, 1.0 - node.gpu_util)
    capacity_score = 0.3 * free_mem_norm + 0.4 * queue_norm + 0.3 * gpu_norm

    # 3. Latency score (Network RTT + Estimated Execution Time)
    rtt_ms = get_estimated_rtt_ms(level)
    tokens = request.prompt_tokens_est + request.max_output_tokens
    eval_time_ms = 40.0 + (tokens * 8.0) if is_cloud else 120.0 + (tokens * 32.0)

    total_lat_est = rtt_ms + eval_time_ms
    target_budget = max(50.0, float(request.latency_target_ms))
    latency_score = max(0.0, min(1.0, 1.0 - (total_lat_est / (target_budget * 1.5))))

    # 4. Locality score
    if level == HierarchyLevel.LOCAL:
        locality_score = 1.0
    elif level == HierarchyLevel.CITY:
        locality_score = 0.80
    elif level == HierarchyLevel.REGION:
        locality_score = 0.40
    else:
        locality_score = 0.0

    # 5. Fairness score
    if ledger is not None and not is_cloud:
        fairness_score = ledger.get_fairness_score(node.node_id)
    else:
        fairness_score = 0.50

    # 6. Cloud penalty
    cloud_penalty = 1.0 if is_cloud else 0.0

    # 7. Total weighted score
    total_score = (
        (config.w_energy * energy_score)
        + (config.w_capacity * capacity_score)
        + (config.w_latency * latency_score)
        + (config.w_locality * locality_score)
        + (config.w_fairness * fairness_score)
        - (config.w_cloud_penalty * cloud_penalty)
    )

    return ScoreBreakdown(
        energy=round(energy_score, 3),
        capacity=round(capacity_score, 3),
        latency=round(latency_score, 3),
        locality=round(locality_score, 3),
        fairness=round(fairness_score, 3),
        cloud_penalty=round(cloud_penalty, 3),
        total_score=round(total_score, 4),
    )
