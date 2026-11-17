"""Pure, deterministic routing function for SunRoute.

Implements:
- Pure route() with injected clock and deterministic PRNG
- Hard filters
- Hierarchy levels (local -> city -> region -> cloud)
- Power of two choices inside a level
- Multi-objective scoring (energy, capacity, latency, locality, fairness, cloud penalty)
- Baselines: cloud-only, edge-only, FCFS, and cascade
"""

from __future__ import annotations

import random
import time
from collections.abc import Sequence

from edge.schemas import (
    InferenceRequest,
    NodeKind,
    NodeState,
    Origin,
    TaskType,
)
from router.filters import is_node_eligible
from router.ledger import FairnessLedger
from router.schemas import (
    Decision,
    HierarchyLevel,
    PolicyType,
    RouterConfig,
    ScoreBreakdown,
)
from router.scoring import score_candidate


def partition_by_level(
    nodes: Sequence[NodeState],
    origin: Origin,
) -> tuple[list[NodeState], list[NodeState], list[NodeState]]:
    """Partition edge nodes into local, city, and regional hierarchy tiers."""
    local_nodes: list[NodeState] = []
    city_nodes: list[NodeState] = []
    region_nodes: list[NodeState] = []

    for n in nodes:
        if n.kind == NodeKind.CLOUD:
            continue
        if n.city == origin.city:
            # We treat the first matching node in city or same node as local tier
            if len(local_nodes) == 0:
                local_nodes.append(n)
            else:
                city_nodes.append(n)
        else:
            region_nodes.append(n)

    # If city has only one node, it acts as both local and city
    if not city_nodes and local_nodes:
        city_nodes = list(local_nodes)

    return local_nodes, city_nodes, region_nodes


def pick_power_of_two(
    candidates: list[NodeState],
    request: InferenceRequest,
    config: RouterConfig,
    level: HierarchyLevel,
    ledger: FairnessLedger | None,
    rng: random.Random,
) -> tuple[NodeState, ScoreBreakdown]:
    """Sample two candidates (power of two choices) and return the one with higher score."""
    if len(candidates) == 1:
        chosen = candidates[0]
        sb = score_candidate(request, chosen, config, level, ledger)
        return chosen, sb

    # Sample 2 distinct nodes
    sampled = rng.sample(candidates, 2)
    s1 = score_candidate(request, sampled[0], config, level, ledger)
    s2 = score_candidate(request, sampled[1], config, level, ledger)

    if s1.total_score >= s2.total_score:
        return sampled[0], s1
    return sampled[1], s2


def is_complex_or_heavy_task(request: InferenceRequest) -> tuple[bool, str]:
    """Check if query demands cloud scale (long output, essay, or non-Latin multilingual)."""
    prompt_lower = request.prompt.lower()

    if request.task_type == TaskType.LONG_FORM:
        return True, "task type LONG_FORM escalated to central cloud tier"

    if request.max_output_tokens >= 300:
        return True, f"requested token budget ({request.max_output_tokens}) exceeds edge capacity"

    heavy_keywords = [
        "essay",
        "1000 words",
        "500 words",
        "400 words",
        "300 words",
        "detailed article",
        "comprehensive report",
        "in-depth",
        "write an essay",
    ]
    if any(k in prompt_lower for k in heavy_keywords):
        return True, "task demands extensive generative length (essay/long form)"

    # Non-Latin multilingual scripts (Devanagari, Marathi, Hindi, etc.)
    has_devanagari = any("\u0900" <= ch <= "\u097f" for ch in request.prompt)
    if has_devanagari or any(
        lang in prompt_lower for lang in ["in marathi", "in hindi", "marathi", "hindi"]
    ):
        return True, "multilingual/Devanagari query escalated to central cloud tier"

    return False, ""


def route(
    request: InferenceRequest,
    node_states: Sequence[NodeState],
    cloud_state: NodeState | None = None,
    policy: PolicyType = PolicyType.PROPOSED,
    origin: Origin | None = None,
    ledger: FairnessLedger | None = None,
    config: RouterConfig | None = None,
    now: float | None = None,
    random_seed: int | None = None,
) -> Decision:
    """Pure function routing an inference request to the optimal execution target.

    All clocks and random seeds are injected for complete determinism.
    """
    cfg = config or RouterConfig()
    req_origin = origin or request.origin
    now_ts = now if now is not None else request.created_at.timestamp()
    iso_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts))
    rng = random.Random(random_seed)

    # --------------------------------------------------------------------------
    # 1. Baseline: CLOUD_ONLY
    # --------------------------------------------------------------------------
    if policy == PolicyType.CLOUD_ONLY:
        if cloud_state is not None:
            sb = score_candidate(request, cloud_state, cfg, HierarchyLevel.CLOUD, ledger)
            return Decision(
                target_node_id=cloud_state.node_id,
                target_kind=NodeKind.CLOUD,
                target_level=HierarchyLevel.CLOUD,
                score_breakdown=sb,
                reason="Policy cloud_only: dispatched directly to central data center",
                policy_used=policy,
                timestamp_iso=iso_time,
                selected_node_state=cloud_state,
            )
        return Decision(
            target_node_id=None,
            target_kind=NodeKind.CLOUD,
            target_level=HierarchyLevel.NONE,
            score_breakdown=ScoreBreakdown(),
            reason="Policy cloud_only: no cloud tier configured",
            policy_used=policy,
            timestamp_iso=iso_time,
        )

    # --------------------------------------------------------------------------
    # Filter eligible edge nodes
    # --------------------------------------------------------------------------
    eligible_edge: list[NodeState] = []
    filter_reasons: list[str] = []

    for node in node_states:
        if node.kind == NodeKind.CLOUD:
            continue
        ok, reason = is_node_eligible(request, node, cfg, now_ts)
        if ok:
            eligible_edge.append(node)
        else:
            filter_reasons.append(f"{node.node_id}: {reason}")

    # Check cloud eligibility
    cloud_eligible = False
    if cloud_state is not None:
        ok_cloud, _c_reason = is_node_eligible(request, cloud_state, cfg, now_ts)
        cloud_eligible = ok_cloud

    # --------------------------------------------------------------------------
    # 2. Baseline: EDGE_ONLY
    # --------------------------------------------------------------------------
    if policy == PolicyType.EDGE_ONLY:
        if not eligible_edge:
            reasons_summary = "; ".join(filter_reasons[:3])
            return Decision(
                target_node_id=None,
                target_kind=NodeKind.PHYSICAL,
                target_level=HierarchyLevel.NONE,
                score_breakdown=ScoreBreakdown(),
                reason=f"Policy edge_only: all edge nodes ineligible ({reasons_summary})",
                policy_used=policy,
                timestamp_iso=iso_time,
            )
        # Pick best edge node by score
        scored_edge = [
            (n, score_candidate(request, n, cfg, HierarchyLevel.CITY, ledger))
            for n in eligible_edge
        ]
        scored_edge.sort(key=lambda x: x[1].total_score, reverse=True)
        best_node, best_sb = scored_edge[0]
        return Decision(
            target_node_id=best_node.node_id,
            target_kind=best_node.kind,
            target_level=HierarchyLevel.CITY,
            score_breakdown=best_sb,
            reason="Policy edge_only: routed to top eligible edge node",
            policy_used=policy,
            timestamp_iso=iso_time,
            selected_node_state=best_node,
        )

    # --------------------------------------------------------------------------
    # 3. Baseline: FCFS (First Come, First Served)
    # --------------------------------------------------------------------------
    if policy == PolicyType.FCFS:
        if eligible_edge:
            first_node = eligible_edge[0]
            sb = score_candidate(request, first_node, cfg, HierarchyLevel.CITY, ledger)
            return Decision(
                target_node_id=first_node.node_id,
                target_kind=first_node.kind,
                target_level=HierarchyLevel.CITY,
                score_breakdown=sb,
                reason="Policy FCFS: picked first available eligible edge node without scoring",
                policy_used=policy,
                timestamp_iso=iso_time,
                selected_node_state=first_node,
            )
        if cloud_eligible and cloud_state is not None:
            sb = score_candidate(request, cloud_state, cfg, HierarchyLevel.CLOUD, ledger)
            return Decision(
                target_node_id=cloud_state.node_id,
                target_kind=NodeKind.CLOUD,
                target_level=HierarchyLevel.CLOUD,
                score_breakdown=sb,
                reason="Policy FCFS: edge nodes exhausted, fell back to cloud",
                policy_used=policy,
                timestamp_iso=iso_time,
                selected_node_state=cloud_state,
            )
        return Decision(
            target_node_id=None,
            target_kind=NodeKind.CLOUD,
            target_level=HierarchyLevel.NONE,
            score_breakdown=ScoreBreakdown(),
            reason="Policy FCFS: all nodes ineligible",
            policy_used=policy,
            timestamp_iso=iso_time,
        )

    # --------------------------------------------------------------------------
    # 4. Baseline: CASCADE (Small-Model-First)
    # --------------------------------------------------------------------------
    if policy == PolicyType.CASCADE:
        is_simple_query = request.prompt_tokens_est <= 256 and request.task_type in (
            TaskType.CLASSIFY,
            TaskType.SHORT_QA,
            TaskType.CHAT,
        )
        if is_simple_query and eligible_edge:
            chosen = eligible_edge[0]
            sb = score_candidate(request, chosen, cfg, HierarchyLevel.LOCAL, ledger)
            return Decision(
                target_node_id=chosen.node_id,
                target_kind=chosen.kind,
                target_level=HierarchyLevel.LOCAL,
                score_breakdown=sb,
                reason="Policy cascade: simple prompt satisfied by small edge model",
                policy_used=policy,
                timestamp_iso=iso_time,
                selected_node_state=chosen,
            )
        # Complex or long prompt -> cloud cascade
        if cloud_eligible and cloud_state is not None:
            sb = score_candidate(request, cloud_state, cfg, HierarchyLevel.CLOUD, ledger)
            return Decision(
                target_node_id=cloud_state.node_id,
                target_kind=NodeKind.CLOUD,
                target_level=HierarchyLevel.CLOUD,
                score_breakdown=sb,
                reason="Policy cascade: complex task or large prompt escalated to cloud tier",
                policy_used=policy,
                timestamp_iso=iso_time,
                selected_node_state=cloud_state,
            )

    # --------------------------------------------------------------------------
    # 5. Proposed Router: Hierarchical + Power of Two Choices
    # --------------------------------------------------------------------------
    # Complex tasks, extensive generation demands, or multilingual queries escalate to cloud
    is_heavy, heavy_reason = is_complex_or_heavy_task(request)
    if is_heavy and cloud_eligible and cloud_state is not None:
        sb = score_candidate(request, cloud_state, cfg, HierarchyLevel.CLOUD, ledger)
        return Decision(
            target_node_id=cloud_state.node_id,
            target_kind=NodeKind.CLOUD,
            target_level=HierarchyLevel.CLOUD,
            score_breakdown=sb,
            reason=f"Proposed router: {heavy_reason}",
            policy_used=policy,
            timestamp_iso=iso_time,
            selected_node_state=cloud_state,
        )

    local_nodes, city_nodes, region_nodes = partition_by_level(eligible_edge, req_origin)

    # Tier 1: Local
    if local_nodes:
        node, sb = pick_power_of_two(local_nodes, request, cfg, HierarchyLevel.LOCAL, ledger, rng)
        return Decision(
            target_node_id=node.node_id,
            target_kind=node.kind,
            target_level=HierarchyLevel.LOCAL,
            score_breakdown=sb,
            reason="Proposed router: matched eligible candidate in local site",
            policy_used=policy,
            timestamp_iso=iso_time,
            selected_node_state=node,
        )

    # Tier 2: City Coordinator
    if city_nodes:
        node, sb = pick_power_of_two(city_nodes, request, cfg, HierarchyLevel.CITY, ledger, rng)
        return Decision(
            target_node_id=node.node_id,
            target_kind=node.kind,
            target_level=HierarchyLevel.CITY,
            score_breakdown=sb,
            reason="Proposed router: escalated to city coordinator tier",
            policy_used=policy,
            timestamp_iso=iso_time,
            selected_node_state=node,
        )

    # Tier 3: Regional Neighbouring Cities
    if region_nodes:
        node, sb = pick_power_of_two(region_nodes, request, cfg, HierarchyLevel.REGION, ledger, rng)
        return Decision(
            target_node_id=node.node_id,
            target_kind=node.kind,
            target_level=HierarchyLevel.REGION,
            score_breakdown=sb,
            reason=(
                "Proposed router: local/city capacity depleted, cross-city regional routing applied"
            ),
            policy_used=policy,
            timestamp_iso=iso_time,
            selected_node_state=node,
        )

    # Tier 4: Central Cloud Fallback
    if cloud_eligible and cloud_state is not None:
        sb = score_candidate(request, cloud_state, cfg, HierarchyLevel.CLOUD, ledger)
        return Decision(
            target_node_id=cloud_state.node_id,
            target_kind=NodeKind.CLOUD,
            target_level=HierarchyLevel.CLOUD,
            score_breakdown=sb,
            reason="Proposed router: edge tiers exhausted, fallback to central cloud data center",
            policy_used=policy,
            timestamp_iso=iso_time,
            selected_node_state=cloud_state,
        )

    # All tiers exhausted
    return Decision(
        target_node_id=None,
        target_kind=NodeKind.CLOUD,
        target_level=HierarchyLevel.NONE,
        score_breakdown=ScoreBreakdown(),
        reason=f"No eligible nodes across any tier ({'; '.join(filter_reasons[:3])})",
        policy_used=policy,
        timestamp_iso=iso_time,
    )
