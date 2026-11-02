"""Pure hard filter evaluation for candidate nodes in SunRoute router."""

from __future__ import annotations

from edge.schemas import (
    ConnectivityStatus,
    InferenceRequest,
    NodeKind,
    NodeState,
    Priority,
    Privacy,
)
from router.schemas import RouterConfig


def is_node_eligible(
    request: InferenceRequest,
    node: NodeState,
    config: RouterConfig,
    now_ts: float,
) -> tuple[bool, str]:
    """Pure deterministic hard filter check.

    Returns (True, 'Eligible') if node meets all criteria; otherwise (False, reason).
    """
    # 1. Connectivity Check
    if node.connectivity == ConnectivityStatus.OFFLINE:
        return False, f"Node {node.node_id} is offline"

    # 2. Telemetry Freshness (Stale check)
    age_s = now_ts - node.ts.timestamp()
    if age_s > config.telemetry_ttl_s:
        return (
            False,
            f"Telemetry stale on {node.node_id} (age={age_s:.1f}s > {config.telemetry_ttl_s}s)",
        )

    # 3. Privacy Constraint
    if request.privacy == Privacy.LOCAL_ONLY:
        if node.kind == NodeKind.CLOUD:
            return (
                False,
                f"Privacy 'local_only' disallows cloud tier for request {request.request_id}",
            )
        if node.city != request.origin.city:
            return (
                False,
                f"Privacy 'local_only' restricts inference to origin city ({request.origin.city})",
            )

    # 4. Thermal Safety Limit (Edge nodes only)
    if node.kind != NodeKind.CLOUD and node.temp_c >= config.max_temp_c:
        return False, (
            f"Temperature {node.temp_c:.1f}°C exceeds thermal limit {config.max_temp_c}°C"
        )

    # 5. Free Memory Threshold
    if node.free_mem_mb < config.min_free_mem_mb:
        return (
            False,
            f"Free RAM {node.free_mem_mb:.0f}MB is below {config.min_free_mem_mb:.0f}MB threshold",
        )

    # 6. GPU Utilization Cap
    if node.gpu_util > config.max_gpu_util:
        gpu_pct = node.gpu_util * 100.0
        max_pct = config.max_gpu_util * 100.0
        return False, f"GPU utilization {gpu_pct:.1f}% exceeds max {max_pct:.1f}%"

    # 7. Queue Depth Limit
    if node.queue_depth >= config.max_queue_depth:
        return False, f"Queue depth {node.queue_depth} exceeds capacity {config.max_queue_depth}"

    # 8. Battery Safety Floors (Edge nodes only)
    if node.kind != NodeKind.CLOUD:
        # Critical shutdown
        if node.battery_soc <= config.critical_battery_soc:
            soc_pct = node.battery_soc * 100.0
            crit_pct = config.critical_battery_soc * 100.0
            return False, f"Battery critically low ({soc_pct:.1f}% <= {crit_pct:.1f}%)"

        # Reserve floor check
        if node.battery_soc < config.min_battery_soc:
            has_surplus = (node.solar_w + node.wind_w) > (node.load_w + config.surplus_threshold_w)
            is_essential = request.priority == Priority.ESSENTIAL

            if not has_surplus and not is_essential:
                soc_pct = node.battery_soc * 100.0
                res_pct = config.min_battery_soc * 100.0
                return (
                    False,
                    f"Battery at reserve floor ({soc_pct:.1f}% < {res_pct:.1f}%) without surplus",
                )

    return True, "Eligible"
