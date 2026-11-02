"""FastAPI Gateway Application for SunRoute.

Routes client inference requests across community edge nodes and cloud tiers,
dispatches execution, writes append-only decision audit logs, and exposes telemetry.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel

from cloud.mock_client import MockCloudClient
from edge.schemas import (
    InferenceRequest,
    InferenceResponse,
    NodeKind,
    NodeState,
)
from gateway.decision_log import DecisionAuditLog
from router.core import route
from router.ledger import FairnessLedger
from router.schemas import (
    HierarchyLevel,
    PolicyType,
    RouterConfig,
)

logger = logging.getLogger("gateway")


class NodeRegistration(BaseModel):
    node_id: str
    url: str  # e.g. "http://localhost:8001"
    api_token: str = "dev-edge-token"
    city: str = "city-01"


class GatewayState:
    """Manages active node registry, cloud client, router configuration, and audit log."""

    def __init__(
        self,
        audit_db_path: Path | str = "experiments/decision_audit.db",
        config: RouterConfig | None = None,
    ):
        self.config = config or RouterConfig()
        self.decision_log = DecisionAuditLog(audit_db_path)
        self.ledger = FairnessLedger()
        self.cloud_client = MockCloudClient()
        self.http_client = httpx.AsyncClient(timeout=30.0)

        # Registered edge nodes: node_id -> {"url": str, "token": str, "state": Optional[NodeState]}
        self.registered_nodes: dict[str, dict[str, Any]] = {}

    async def close(self) -> None:
        await self.http_client.aclose()


def create_gateway_app(
    audit_db_path: Path | str = "experiments/decision_audit.db",
    config: RouterConfig | None = None,
) -> FastAPI:
    state = GatewayState(audit_db_path=audit_db_path, config=config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger.info("SunRoute Gateway initializing...")
        yield
        await state.close()
        logger.info("SunRoute Gateway shut down.")

    app = FastAPI(
        title="SunRoute Ingress Gateway",
        version="0.1.0",
        description="Intelligent edge-cloud inference router and telemetry coordinator",
        lifespan=lifespan,
    )
    app.state.gateway = state

    @app.post(
        "/v1/nodes/register",
        status_code=status.HTTP_201_CREATED,
        summary="Register an active edge node with the gateway",
    )
    async def register_node(reg: NodeRegistration) -> dict[str, str]:
        state.registered_nodes[reg.node_id] = {
            "url": reg.url.rstrip("/"),
            "token": reg.api_token,
            "city": reg.city,
            "state": None,
        }
        logger.info("Registered edge node: %s at %s (%s)", reg.node_id, reg.url, reg.city)
        return {"status": "registered", "node_id": reg.node_id}

    @app.get(
        "/v1/telemetry/nodes",
        response_model=list[NodeState],
        summary="Fetch live telemetry from all registered nodes and cloud tier",
    )
    async def get_node_telemetry() -> list[NodeState]:
        nodes_telemetry: list[NodeState] = []

        # 1. Edge nodes
        for node_id, info in state.registered_nodes.items():
            try:
                res = await state.http_client.get(
                    f"{info['url']}/state",
                    timeout=2.0,
                )
                if res.status_code == 200:
                    node_st = NodeState(**res.json())
                    info["state"] = node_st
                    nodes_telemetry.append(node_st)
            except Exception as e:
                logger.warning("Failed polling telemetry from node %s: %s", node_id, e)
                if info.get("state") is not None:
                    nodes_telemetry.append(info["state"])

        # 2. Cloud node
        cloud_st = await state.cloud_client.get_state()
        nodes_telemetry.append(cloud_st)

        return nodes_telemetry

    @app.post(
        "/v1/chat/completions",
        response_model=InferenceResponse,
        summary="Route and execute inference across edge or cloud tier",
    )
    async def route_and_infer(
        request: InferenceRequest,
        policy: PolicyType = Query(default=PolicyType.PROPOSED),
    ) -> InferenceResponse:
        start_t = time.time()

        # 1. Collect current node states
        all_states = await get_node_telemetry()
        edge_states = [s for s in all_states if s.kind != NodeKind.CLOUD]
        cloud_st = next((s for s in all_states if s.kind == NodeKind.CLOUD), None)

        # 2. Invoke pure router
        decision = route(
            request=request,
            node_states=edge_states,
            cloud_state=cloud_st,
            policy=policy,
            origin=request.origin,
            ledger=state.ledger,
            config=state.config,
        )

        logger.info(
            "Routing decision: target=%s level=%s policy=%s reason=%s",
            decision.target_node_id,
            decision.target_level.value,
            decision.policy_used.value,
            decision.reason,
        )

        if decision.target_level == HierarchyLevel.NONE or decision.target_node_id is None:
            # Audit rejected decision
            state.decision_log.record(decision, request, execution_latency_ms=0.0, success=False)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Routing failure: {decision.reason}",
            )

        # 3. Dispatch execution
        response: InferenceResponse | None = None
        success = False

        if decision.target_kind == NodeKind.CLOUD:
            # Dispatch to cloud client
            response = await state.cloud_client.infer(request)
            success = True
        else:
            # Dispatch to edge node via HTTP
            node_info = state.registered_nodes.get(decision.target_node_id)
            if node_info:
                headers = {"Authorization": f"Bearer {node_info['token']}"}
                try:
                    res = await state.http_client.post(
                        f"{node_info['url']}/infer",
                        json=request.model_dump(mode="json"),
                        headers=headers,
                        timeout=30.0,
                    )
                    if res.status_code == 200:
                        response = InferenceResponse(**res.json())
                        success = True
                    else:
                        logger.error(
                            "Edge node %s returned %d: %s",
                            decision.target_node_id,
                            res.status_code,
                            res.text,
                        )
                except Exception as e:
                    logger.error(
                        "Connection error dispatching to edge node %s: %s",
                        decision.target_node_id,
                        e,
                    )

            if not success:
                # If edge node failed, escalate to cloud fallback
                logger.warning("Edge target failed or unreachable. Escalating to cloud fallback.")
                response = await state.cloud_client.infer(request)
                success = True

        total_exec_ms = (time.time() - start_t) * 1000.0

        # 4. Record decision to append-only audit log
        state.decision_log.record(
            decision=decision,
            request=request,
            execution_latency_ms=total_exec_ms,
            success=success,
        )

        # 5. Update fairness ledger
        if response:
            if decision.target_kind != NodeKind.CLOUD and decision.target_node_id:
                state.ledger.record_served(decision.target_node_id, response.output_tokens)
            state.ledger.record_originated(request.origin.site, response.output_tokens)

        return response

    @app.get(
        "/v1/decisions",
        summary="Query append-only decision audit log",
    )
    async def list_decisions(
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict[str, Any]]:
        return state.decision_log.list_decisions(limit=limit, offset=offset)

    @app.get("/v1/nodes", summary="List registered edge nodes and live telemetry")
    async def list_nodes() -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for n_id, reg in state.registered_nodes.items():
            st = reg.get("state")
            nodes.append(
                {
                    "node_id": n_id,
                    "city": reg.get("city", "city-01"),
                    "url": reg.get("url"),
                    "kind": st.kind.value if st else "unknown",
                    "connectivity": st.connectivity.value if st else "unknown",
                    "battery_soc": st.battery_soc if st else 0.0,
                    "solar_w": st.solar_w if st else 0.0,
                    "wind_w": st.wind_w if st else 0.0,
                    "load_w": st.load_w if st else 0.0,
                    "queue_depth": st.queue_depth if st else 0,
                    "temp_c": st.temp_c if st else 0.0,
                }
            )
        return nodes

    @app.get("/v1/metrics/summary", summary="Aggregated metrics summary for dashboard")
    async def get_metrics_summary() -> dict[str, Any]:
        decisions = state.decision_log.list_decisions(limit=500, offset=0)
        total = len(decisions)
        if total == 0:
            return {
                "total_queries": 0,
                "community_edge_share": 0.0,
                "cloud_share": 0.0,
                "locality_rate": 0.0,
                "p50_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "registered_nodes_count": len(state.registered_nodes),
            }

        edge_count = sum(1 for d in decisions if d["target_kind"] != "cloud")
        cloud_count = total - edge_count
        local_count = sum(1 for d in decisions if d["target_level"] in ("local", "city"))

        latencies = sorted(
            d["execution_latency_ms"] for d in decisions if d.get("execution_latency_ms")
        )
        p50 = latencies[len(latencies) // 2] if latencies else 0.0
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0

        return {
            "total_queries": total,
            "community_edge_share": round(edge_count / total, 4),
            "cloud_share": round(cloud_count / total, 4),
            "locality_rate": round(local_count / total, 4),
            "p50_latency_ms": round(p50, 2),
            "p95_latency_ms": round(p95, 2),
            "registered_nodes_count": len(state.registered_nodes),
            "metrics_classification": {
                "latency": "measured",
                "edge_power": "simulated_or_measured",
                "cloud_power": "estimated",
            },
        }

    @app.get("/v1/events", summary="Server-Sent Events (SSE) live telemetry stream")
    async def event_stream() -> Any:
        import asyncio
        import json

        from starlette.responses import StreamingResponse

        async def sse_generator():
            while True:
                heartbeat = {
                    "event": "heartbeat",
                    "timestamp": time.time(),
                    "nodes_count": len(state.registered_nodes),
                    "total_decisions": state.decision_log.count(),
                }
                yield f"data: {json.dumps(heartbeat)}\n\n"
                await asyncio.sleep(2.0)

        return StreamingResponse(sse_generator(), media_type="text/event-stream")

    @app.get("/health", summary="Gateway health check")
    async def health() -> dict[str, Any]:
        return {
            "status": "healthy",
            "registered_edge_nodes": len(state.registered_nodes),
            "total_audit_decisions": state.decision_log.count(),
        }

    return app


# Default gateway instance
app = create_gateway_app()
