"""FastAPI Gateway Application for SunRoute.

Routes client inference requests across community edge nodes and cloud tiers,
dispatches execution, writes append-only decision audit logs, and exposes telemetry.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from cloud.factory import get_cloud_client
from cloud.mock_client import generate_cloud_knowledge_response
from edge.schemas import (
    ConnectivityStatus,
    EnergySource,
    InferenceRequest,
    InferenceResponse,
    NodeKind,
    NodeState,
    Origin,
    TaskType,
)
from gateway.chat_store import (
    ChatAttachment,
    ChatMessageRecord,
    ChatStore,
)
from gateway.decision_log import DecisionAuditLog
from router.core import route
from router.ledger import FairnessLedger
from router.schemas import (
    HierarchyLevel,
    PolicyType,
    RouterConfig,
)
from simulator.energy import NodeEnergySimulator, SolarConfig
from simulator.topology import StateTopology

logger = logging.getLogger("gateway")

CITY_NAMES: dict[str, str] = {
    "city-01": "Mumbai (State Capital & Cloud DC)",
    "city-02": "Pune (Tech Hub)",
    "city-03": "Nagpur (Central Solar Hub)",
    "city-04": "Nashik (Wine & Wind Zone)",
    "city-05": "Thane (Metro Suburban Edge)",
    "city-06": "Chhatrapati Sambhajinagar",
    "city-07": "Solapur (High Irradiance Grid)",
    "city-08": "Kolhapur (Western Ghats Hydro/Wind)",
    "city-09": "Amravati (Cotton Belt Solar)",
    "city-10": "Nanded (East River Grid)",
    "city-11": "Sangli (Wind Farm Cluster)",
    "city-12": "Jalgaon (Khandesh Solar Valley)",
    "city-13": "Akola (Vidarbha Thermal & Solar)",
    "city-14": "Latur (Marathwada Solar Park)",
    "city-15": "Dhule (Dhule Solar Power Plant)",
    "city-16": "Ahmednagar (Sugar Mill Biomass & Solar)",
    "city-17": "Chandrapur (Eastern Border Grid)",
    "city-18": "Parbhani (Central Solar Node)",
    "city-19": "Ichalkaranji (Textile Renewable Grid)",
    "city-20": "Jalna (Steel Industrial Edge)",
    "city-21": "Navi Mumbai (Harbour Edge Cluster)",
    "city-22": "Panvel (Transit Node Edge)",
    "city-23": "Satara (Koyna & Chalkewadi Wind Zone)",
    "city-24": "Beed (Wind Corridor Node)",
    "city-25": "Yavatmal (Vidarbha Edge Node)",
    "city-26": "Gondia (Eastern Forest Microgrid)",
    "city-27": "Barshi (Rural Cooperative Edge)",
    "city-28": "Bhusawal (Railway Renewable Microgrid)",
    "city-29": "Badlapur (Foothills Clean Edge)",
    "city-30": "Ambarnath (Mid-Urban Edge Node)",
}


class ChatCompletionResponse(InferenceResponse):
    """Inference response extended with rich routing metadata for transparency."""

    routing_metadata: dict[str, Any] | None = None


class NodeRegistration(BaseModel):
    node_id: str
    url: str  # e.g. "http://localhost:8001"
    api_token: str = "dev-edge-token"
    city: str = "city-01"


class LoginRequest(BaseModel):
    username: str
    password: str = "demo"
    display_name: str | None = None
    role: str = "student"
    default_city: str = "city-02"


class CreateConversationRequest(BaseModel):
    user_id: str
    title: str = "New Chat"


class SendChatMessageRequest(BaseModel):
    conversation_id: str
    user_id: str
    prompt: str
    policy: PolicyType = PolicyType.PROPOSED
    origin_city: str = "city-02"
    attachments: list[ChatAttachment] = []
    max_output_tokens: int = 120


class OpsCopilotRequest(BaseModel):
    prompt: str


class GatewayState:
    """Manages active node registry, 30-city topology, router, and audit log."""

    def __init__(
        self,
        audit_db_path: Path | str = "experiments/decision_audit.db",
        config: RouterConfig | None = None,
        enable_30_cities: bool = False,
    ):
        self.config = config or RouterConfig()
        self.decision_log = DecisionAuditLog(audit_db_path)
        self.chat_store = ChatStore("experiments/chat_history.db")
        self.ledger = FairnessLedger()
        self.cloud_client = get_cloud_client(fallback_to_mock=True)
        self.http_client = httpx.AsyncClient(timeout=30.0)

        # 30-city topology & naming
        self.topology = StateTopology()
        self.city_names = CITY_NAMES
        self.enable_30_cities = enable_30_cities
        self.simulated_nodes: dict[str, NodeEnergySimulator] = {}
        self.node_to_city: dict[str, str] = {}

        if self.enable_30_cities:
            for c_id, c_info in self.topology.cities.items():
                nid = f"node-{c_id}-1"
                self.node_to_city[nid] = c_id
                c_num = int(c_id.split("-")[1])
                self.simulated_nodes[nid] = NodeEnergySimulator(
                    node_id=nid,
                    city=c_id,
                    solar_config=SolarConfig(
                        latitude=18.5 + (c_info.y_km / 100.0),
                        longitude=73.0 + (c_info.x_km / 100.0),
                    ),
                    seed=42 + c_num,
                )

        # Registered edge nodes: node_id -> {"url": str, "token": str, "state": Optional[NodeState]}
        self.registered_nodes: dict[str, dict[str, Any]] = {}

        # Auto-seed nodes from environment if configured
        seed_env = os.environ.get("SEED_NODES", "")
        if seed_env:
            for item in seed_env.split(","):
                item = item.strip()
                if not item:
                    continue
                parts = item.split(";")
                if len(parts) >= 2:
                    nid, url = parts[0].split("=", 1) if "=" in parts[0] else (parts[0], parts[0])
                    city = parts[1] if len(parts) > 1 else "city-01"
                    tok = parts[2] if len(parts) > 2 else "sunroute-edge-secret-token"
                    self.registered_nodes[nid] = {
                        "url": url.rstrip("/"),
                        "token": tok,
                        "city": city,
                        "state": None,
                    }
                    self.node_to_city[nid] = city

    async def close(self) -> None:
        await self.http_client.aclose()


def create_gateway_app(
    audit_db_path: Path | str = "experiments/decision_audit.db",
    config: RouterConfig | None = None,
    enable_30_cities: bool = False,
) -> FastAPI:
    state = GatewayState(
        audit_db_path=audit_db_path, config=config, enable_30_cities=enable_30_cities
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger.info(
            "SunRoute Gateway initializing (30-city simulation=%s)...",
            state.enable_30_cities,
        )
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", summary="Gateway health check")
    @app.get("/v1/health", summary="Gateway health check (v1)")
    async def get_health() -> dict[str, Any]:
        total_nodes = (
            len(state.topology.cities) if state.enable_30_cities else len(state.registered_nodes)
        )
        return {
            "status": "healthy",
            "service": "sunroute-gateway",
            "registered_nodes": total_nodes,
            "cloud_backend": type(state.cloud_client).__name__,
            "topology_cities_active": len(state.topology.cities) if state.enable_30_cities else 0,
        }

    @app.get("/v1/cities", summary="List all 30 cities in the network topology")
    async def list_cities() -> list[dict[str, Any]]:
        cities_list: list[dict[str, Any]] = []
        for c_id, c_info in state.topology.cities.items():
            cities_list.append(
                {
                    "city_id": c_id,
                    "name": state.city_names.get(c_id, c_info.name),
                    "region": c_info.region,
                    "x_km": c_info.x_km,
                    "y_km": c_info.y_km,
                    "is_capital": c_info.is_capital,
                }
            )
        return cities_list

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
        state.node_to_city[reg.node_id] = reg.city
        logger.info("Registered edge node: %s at %s (%s)", reg.node_id, reg.url, reg.city)
        return {"status": "registered", "node_id": reg.node_id}

    @app.get(
        "/v1/telemetry/nodes",
        response_model=list[NodeState],
        summary="Fetch live telemetry from all registered and simulated nodes",
    )
    async def get_node_telemetry() -> list[NodeState]:
        nodes_telemetry: list[NodeState] = []
        covered_cities: set[str] = set()

        # 1. Registered HTTP Edge nodes (e.g. Jetson or Docker nodes)
        for node_id, info in state.registered_nodes.items():
            city_id = info.get("city", "city-01")
            covered_cities.add(city_id)
            try:
                res = await state.http_client.get(
                    f"{info['url']}/state",
                    timeout=2.0,
                )
                if res.status_code == 200:
                    node_st = NodeState(**res.json())
                    info["state"] = node_st
                    nodes_telemetry.append(node_st)
                    continue
            except Exception as e:
                logger.warning("Failed polling telemetry from node %s: %s", node_id, e)
            if info.get("state") is not None:
                nodes_telemetry.append(info["state"])

        # 2. 30-city simulated nodes (if enabled)
        if state.enable_30_cities:
            now_dt = datetime.now(UTC)
            now_sec = time.time()
            for c_id, _ in state.topology.cities.items():
                if c_id in covered_cities:
                    continue  # already covered by a real HTTP node
                nid = f"node-{c_id}-1"
                sim = state.simulated_nodes.get(nid)
                if sim:
                    sim_data = sim.step(
                        sim_timestamp=now_dt,
                        sim_second=now_sec,
                        dt_seconds=5.0,
                        is_inferring=False,
                    )
                    soc = sim_data["battery_soc_simulated"]
                    solar_w = sim_data["solar_w_simulated"]
                    wind_w = sim_data["wind_w_simulated"]
                    load_w = sim_data["load_w_simulated"]
                else:
                    soc, solar_w, wind_w, load_w = 0.75, 15.0, 3.0, 7.5

                c_num = int(c_id.split("-")[1])
                nodes_telemetry.append(
                    NodeState(
                        node_id=nid,
                        city=c_id,
                        kind=NodeKind.EMULATED,
                        models=["Llama-3.2-1B-Instruct-Q4_K_M"],
                        free_mem_mb=2800 + (c_num * 15) % 800,
                        gpu_util=round(0.15 + (c_num % 5) * 0.05, 2),
                        queue_depth=c_num % 2,
                        temp_c=round(48.0 + (c_num % 7) * 1.5, 1),
                        battery_soc=round(soc, 3),
                        solar_w=round(solar_w, 2),
                        wind_w=round(wind_w, 2),
                        load_w=round(load_w, 2),
                        connectivity=ConnectivityStatus.ONLINE,
                        energy_source=EnergySource.SIMULATED,
                    )
                )

        # 3. Cloud node
        if inspect.iscoroutinefunction(state.cloud_client.get_state):
            cloud_st = await state.cloud_client.get_state()
        else:
            cloud_st = state.cloud_client.get_state()
        nodes_telemetry.append(cloud_st)

        return nodes_telemetry

    @app.post(
        "/v1/chat/completions",
        response_model=ChatCompletionResponse,
        summary="Route and execute inference across edge or cloud tier",
    )
    async def route_and_infer(
        request: InferenceRequest,
        policy: PolicyType = Query(default=PolicyType.PROPOSED),
    ) -> ChatCompletionResponse:
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
            state.decision_log.record(decision, request, execution_latency_ms=0.0, success=False)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Routing failure: {decision.reason}",
            )

        # 3. Dispatch execution
        response: ChatCompletionResponse | None = None
        success = False

        is_cloud = decision.target_kind == NodeKind.CLOUD or decision.target_node_id in (
            "aws-bedrock-central",
            "aws-bedrock-datacenter",
            "nvidia-nim-datacenter",
        )
        if is_cloud:
            cloud_res = await state.cloud_client.infer(request)
            response = ChatCompletionResponse(
                request_id=cloud_res.request_id,
                node_id=cloud_res.node_id,
                text=cloud_res.text,
                prompt_tokens=cloud_res.prompt_tokens,
                output_tokens=cloud_res.output_tokens,
                latency_ms=cloud_res.latency_ms,
                energy_consumed_j_est=cloud_res.energy_consumed_j_est,
            )
            success = True
        else:
            # Check for live HTTP edge node
            node_info = state.registered_nodes.get(decision.target_node_id)
            if node_info and node_info.get("url"):
                headers = {"Authorization": f"Bearer {node_info['token']}"}
                # Apply prompt enhancer so local SLM generates a clean, complete, concise answer
                target_words = max(25, min(55, request.max_output_tokens // 2))
                raw_prompt = request.prompt
                if "<|im_start|>" not in raw_prompt:
                    enhanced_prompt = (
                        "<|im_start|>system\n"
                        "You are an edge AI assistant powered by a local renewable microgrid. "
                        f"Answer directly and completely in under {target_words} words. "
                        "Always conclude your thought cleanly with a period.<|im_end|>\n"
                        f"<|im_start|>user\n{raw_prompt}<|im_end|>\n"
                        "<|im_start|>assistant\n"
                    )
                else:
                    enhanced_prompt = raw_prompt

                enhanced_req_dict = request.model_dump(mode="json")
                enhanced_req_dict["prompt"] = enhanced_prompt

                try:
                    res = await state.http_client.post(
                        f"{node_info['url']}/infer",
                        json=enhanced_req_dict,
                        headers=headers,
                        timeout=30.0,
                    )
                    if res.status_code == 200:
                        raw = res.json()
                        response = ChatCompletionResponse(**raw)
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

            if not success and decision.target_node_id in state.simulated_nodes:
                # Digital Twin execution calibrated to physical Jetson Orin Nano Super
                target_city = state.node_to_city.get(decision.target_node_id, "city-01")
                city_name = state.city_names.get(target_city, target_city)
                origin_city = request.origin.city
                rtt = state.topology.calculate_rtt_ms(origin_city, target_city)

                # Query active edge LLM engine so simulated node returns real intelligent text
                generated_text: str | None = None
                actual_prompt_toks = request.prompt_tokens_est
                actual_out_toks = 35

                # Prioritize physical hardware / live llama-server (e.g. jetson-01) over mock nodes
                sorted_nodes = sorted(
                    state.registered_nodes.items(),
                    key=lambda item: 0 if item[0] == "jetson-01" else 1,
                )
                for _nid, n_info in sorted_nodes:
                    if n_info.get("url"):
                        try:
                            headers = {"Authorization": f"Bearer {n_info['token']}"}
                            enhanced_dict = request.model_dump(mode="json")
                            target_words = max(25, min(55, request.max_output_tokens // 2))
                            raw_prompt = request.prompt
                            if "<|im_start|>" not in raw_prompt:
                                enhanced_dict["prompt"] = (
                                    "<|im_start|>system\n"
                                    "You are an edge AI assistant on a clean renewable microgrid. "
                                    f"Answer completely in under {target_words} words. "
                                    "Always conclude cleanly with a period.<|im_end|>\n"
                                    f"<|im_start|>user\n{raw_prompt}<|im_end|>\n"
                                    "<|im_start|>assistant\n"
                                )
                            res = await state.http_client.post(
                                f"{n_info['url']}/infer",
                                json=enhanced_dict,
                                headers=headers,
                                timeout=15.0,
                            )
                            if res.status_code == 200:
                                raw_data = res.json()
                                cand_text = raw_data.get("text", "").strip()
                                # Verify it's real generated output, not an unconfigured placeholder
                                if cand_text and not cand_text.startswith("[SunRoute"):
                                    generated_text = cand_text
                                    actual_prompt_toks = raw_data.get(
                                        "prompt_tokens", actual_prompt_toks
                                    )
                                    actual_out_toks = raw_data.get("output_tokens", actual_out_toks)
                                    break
                        except Exception as e:
                            logger.debug(
                                "LLM pass-through on %s failed: %s",
                                n_info.get("url"),
                                e,
                            )

                if not generated_text:
                    generated_text = generate_cloud_knowledge_response(request.prompt)

                # Digital Twin calibrated to physical Jetson Orin Nano Super:
                # 0.339 J/token total measured, 28.13 t/s generation, 42.1 ms TTFT
                output_tokens = min(request.max_output_tokens, actual_out_toks)
                energy_j = output_tokens * 0.339
                exec_delay_ms = round(42.1 + (output_tokens / 28.13) * 1000.0 + rtt, 2)

                response = ChatCompletionResponse(
                    request_id=request.request_id,
                    node_id=decision.target_node_id,
                    text=f"[{city_name} Community Node]\n\n{generated_text}",
                    prompt_tokens=actual_prompt_toks,
                    output_tokens=output_tokens,
                    latency_ms=exec_delay_ms,
                    energy_consumed_j_est=round(energy_j, 3),
                )
                success = True

            if not success:
                logger.warning("Edge target unreachable. Escalating to cloud fallback.")
                cloud_res = await state.cloud_client.infer(request)
                response = ChatCompletionResponse(
                    request_id=cloud_res.request_id,
                    node_id=cloud_res.node_id,
                    text=cloud_res.text,
                    prompt_tokens=cloud_res.prompt_tokens,
                    output_tokens=cloud_res.output_tokens,
                    latency_ms=cloud_res.latency_ms,
                    energy_consumed_j_est=cloud_res.energy_consumed_j_est,
                )
                success = True

        total_exec_ms = (time.time() - start_t) * 1000.0

        # Attach rich routing metadata for ChatGPT UI transparency
        target_city_id = state.node_to_city.get(decision.target_node_id, "")
        if "nvidia" in str(decision.target_node_id).lower():
            target_city_name = "NVIDIA NIM Cloud Datacenter"
        elif "bedrock" in str(decision.target_node_id).lower():
            target_city_name = "AWS Bedrock Central"
        elif decision.target_kind == NodeKind.CLOUD:
            target_city_name = "Central Cloud Datacenter"
        else:
            target_city_name = (
                state.city_names.get(target_city_id, "Central Cloud Datacenter")
                if target_city_id
                else "Central Cloud Datacenter"
            )
        decision_id = str(uuid.uuid4())
        sb = decision.score_breakdown
        response.routing_metadata = {
            "decision_id": decision_id,
            "policy_used": decision.policy_used.value,
            "target_node_id": decision.target_node_id,
            "target_kind": (
                decision.target_kind.value
                if hasattr(decision.target_kind, "value")
                else str(decision.target_kind)
            ),
            "target_level": (
                decision.target_level.value
                if hasattr(decision.target_level, "value")
                else str(decision.target_level)
            ),
            "reason": decision.reason,
            "score_total": round(sb.total_score, 4) if sb else None,
            "score_energy": round(sb.energy, 4) if sb else None,
            "score_latency": round(sb.latency, 4) if sb else None,
            "score_locality": round(sb.locality, 4) if sb else None,
            "score_fairness": round(sb.fairness, 4) if sb else None,
            "origin_city": request.origin.city,
            "origin_city_name": state.city_names.get(request.origin.city, request.origin.city),
            "target_city_name": target_city_name,
            "execution_latency_ms": round(total_exec_ms, 2),
            "energy_consumed_j_est": response.energy_consumed_j_est,
        }

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

    @app.get("/v1/nodes", summary="List edge fleet and 30-city live telemetry")
    async def list_nodes() -> list[dict[str, Any]]:
        telemetry = await get_node_telemetry()
        nodes: list[dict[str, Any]] = []
        for st in telemetry:
            if st.kind == NodeKind.CLOUD:
                continue
            city_info = state.topology.cities.get(st.city)
            city_name = state.city_names.get(st.city, st.city)
            nodes.append(
                {
                    "node_id": st.node_id,
                    "city": st.city,
                    "city_name": city_name,
                    "region": city_info.region if city_info else "unknown",
                    "x_km": city_info.x_km if city_info else 0.0,
                    "y_km": city_info.y_km if city_info else 0.0,
                    "kind": st.kind.value,
                    "connectivity": st.connectivity.value,
                    "battery_soc": st.battery_soc,
                    "solar_w": st.solar_w,
                    "wind_w": st.wind_w,
                    "load_w": st.load_w,
                    "queue_depth": st.queue_depth,
                    "temp_c": st.temp_c,
                    "energy_source": st.energy_source.value,
                }
            )
        return nodes

    @app.get("/v1/metrics/summary", summary="Aggregated metrics summary for dashboard")
    async def get_metrics_summary() -> dict[str, Any]:
        decisions = state.decision_log.list_decisions(limit=500, offset=0)
        total = len(decisions)
        total_nodes = (
            len(state.topology.cities) if state.enable_30_cities else len(state.registered_nodes)
        )
        if total == 0:
            return {
                "total_queries": 0,
                "community_edge_share": 0.0,
                "cloud_share": 0.0,
                "locality_rate": 0.0,
                "p50_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "registered_nodes_count": total_nodes,
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
            "registered_nodes_count": total_nodes,
            "metrics_classification": {
                "latency": "measured",
                "edge_power": "simulated_or_measured",
                "cloud_power": "estimated",
            },
        }

    @app.get("/v1/events", summary="Server-Sent Events (SSE) live telemetry stream")
    async def event_stream() -> Any:
        import json

        from starlette.responses import StreamingResponse

        async def sse_generator():
            while True:
                total_nodes = (
                    len(state.topology.cities)
                    if state.enable_30_cities
                    else len(state.registered_nodes)
                )
                heartbeat = {
                    "event": "heartbeat",
                    "timestamp": time.time(),
                    "nodes_count": total_nodes,
                    "total_decisions": state.decision_log.count(),
                }
                yield f"data: {json.dumps(heartbeat)}\n\n"
                await asyncio.sleep(2.0)

        return StreamingResponse(sse_generator(), media_type="text/event-stream")

    # ── Multi-User & Persistent Chat Studio Endpoints ───────────────

    @app.post("/v1/auth/login", summary="Demo login and user profile retrieval")
    async def login(req: LoginRequest) -> dict[str, Any]:
        user = state.chat_store.get_or_create_user(
            username=req.username,
            display_name=req.display_name,
            role=req.role,
            default_city=req.default_city,
        )
        return {"status": "ok", "user": user.model_dump()}

    @app.get("/v1/auth/users", summary="List predefined demo personas")
    async def list_demo_users() -> list[dict[str, Any]]:
        users = state.chat_store.list_users()
        return [u.model_dump() for u in users]

    @app.get("/v1/chat/conversations", summary="List chat conversations for a user")
    async def list_conversations(user_id: str = Query(...)) -> list[dict[str, Any]]:
        convs = state.chat_store.list_conversations(user_id)
        return [c.model_dump() for c in convs]

    @app.post("/v1/chat/conversations", summary="Create a new chat conversation")
    async def create_conversation(req: CreateConversationRequest) -> dict[str, Any]:
        conv = state.chat_store.create_conversation(user_id=req.user_id, title=req.title)
        return conv.model_dump()

    @app.get("/v1/chat/conversations/{conversation_id}", summary="Get conversation messages")
    async def get_conversation_details(conversation_id: str) -> dict[str, Any]:
        conv = state.chat_store.get_conversation(conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        messages = state.chat_store.list_messages(conversation_id)
        return {
            "conversation": conv.model_dump(),
            "messages": [m.model_dump() for m in messages],
        }

    @app.delete("/v1/chat/conversations/{conversation_id}", summary="Delete conversation")
    async def delete_conversation(conversation_id: str) -> dict[str, str]:
        state.chat_store.delete_conversation(conversation_id)
        return {"status": "deleted", "conversation_id": conversation_id}

    @app.post("/v1/chat/messages", summary="Send message in conversation with routing")
    async def send_chat_message(req: SendChatMessageRequest) -> dict[str, Any]:
        # Ensure conversation exists
        conv = state.chat_store.get_conversation(req.conversation_id)
        if not conv:
            title_cand = req.prompt.strip()[:40] + ("..." if len(req.prompt.strip()) > 40 else "")
            conv = state.chat_store.create_conversation(user_id=req.user_id, title=title_cand)
            conv_id = conv.conversation_id
        else:
            conv_id = req.conversation_id
            if conv.message_count == 0 and conv.title in ("New Chat", ""):
                title_cand = req.prompt.strip()[:40] + (
                    "..." if len(req.prompt.strip()) > 40 else ""
                )
                state.chat_store.update_conversation_title(conv_id, title_cand)

        # Record user message
        user_msg = ChatMessageRecord(
            conversation_id=conv_id,
            user_id=req.user_id,
            sender="user",
            text=req.prompt,
            attachments=req.attachments,
        )
        state.chat_store.append_message(user_msg)

        # Build inference request
        task_kind = TaskType.CHAT
        if req.attachments and any("image" in a.mime_type for a in req.attachments):
            task_kind = TaskType.VISION

        infer_req = InferenceRequest(
            request_id=uuid.uuid4(),
            prompt=req.prompt,
            task_type=task_kind,
            prompt_tokens_est=max(10, len(req.prompt.split()) * 2),
            max_output_tokens=req.max_output_tokens,
            latency_target_ms=3000.0,
            origin=Origin(
                city=req.origin_city,
                site=f"{req.origin_city}-user-society",
            ),
        )

        # Execute routing and dispatch
        response = await route_and_infer(request=infer_req, policy=req.policy)

        # Record assistant message
        asst_msg = ChatMessageRecord(
            conversation_id=conv_id,
            user_id=req.user_id,
            sender="assistant",
            text=response.text,
            routing_metadata=response.routing_metadata,
        )
        state.chat_store.append_message(asst_msg)

        return {
            "conversation_id": conv_id,
            "user_message": user_msg.model_dump(),
            "assistant_message": asst_msg.model_dump(),
        }

    # ── System Monitor AI Ops Copilot Endpoint ───────────────────────

    @app.post("/v1/ops/copilot", summary="Inquire about fleet telemetry and system routing")
    async def ops_copilot(req: OpsCopilotRequest) -> dict[str, Any]:
        prompt_lower = req.prompt.lower()
        nodes_telem = await get_node_telemetry()
        recent_decisions = state.decision_log.list_decisions(limit=10)

        # Compute fleet aggregates
        edge_nodes = [n for n in nodes_telem if n.kind != NodeKind.CLOUD]
        total_edge = len(edge_nodes)
        online_count = sum(1 for n in edge_nodes if n.connectivity == ConnectivityStatus.ONLINE)
        avg_soc = (sum(n.battery_soc for n in edge_nodes) / total_edge) if total_edge else 0.0
        total_solar_w = sum(n.solar_w for n in edge_nodes)
        total_wind_w = sum(n.wind_w for n in edge_nodes)
        total_load_w = sum(n.load_w for n in edge_nodes)

        low_soc_nodes = [n for n in edge_nodes if n.battery_soc < 0.65]
        top_solar_nodes = sorted(edge_nodes, key=lambda n: n.solar_w, reverse=True)[:5]

        # Analyze question intent
        if any(w in prompt_lower for w in ["battery", "soc", "charge", "reserve"]):
            if low_soc_nodes:
                items_str = ", ".join(
                    f"{state.city_names.get(n.city, n.city)} "
                    f"({n.battery_soc * 100:.1f}%, solar: {n.solar_w:.1f}W)"
                    for n in low_soc_nodes[:5]
                )
                answer = (
                    f"🔋 **Fleet Battery Diagnosis**:\n\n"
                    f"• Average Fleet Battery SOC: **{avg_soc * 100:.1f}%** "
                    f"across {total_edge} microgrids.\n"
                    f"• **{len(low_soc_nodes)} nodes** operate below 65% battery floor.\n"
                    f"• Lowest charge sites: {items_str}.\n\n"
                    "💡 *Routing Recommendation*: Queries originating near low-SOC sites are\n"
                    "automatically offloaded to neighbor microgrids with surplus solar generation."
                )
            else:
                answer = (
                    f"🔋 **Fleet Battery Status Healthy**:\n\n"
                    f"• All {total_edge} microgrid nodes have healthy reserves above 65% SOC "
                    f"(fleet avg: **{avg_soc * 100:.1f}%**).\n"
                    "• Local edge inference capacity is currently at 100% availability."
                )

        elif any(w in prompt_lower for w in ["solar", "generation", "wind", "renewable", "power"]):
            top_str = "\n".join(
                f"• **{state.city_names.get(n.city, n.city)}**: {n.solar_w:.1f} W solar "
                f"(SOC: {n.battery_soc * 100:.1f}%)"
                for n in top_solar_nodes
            )
            net_surplus = max(0.0, total_solar_w + total_wind_w - total_load_w)
            answer = (
                f"☀️ **Renewable Generation Telemetry**:\n\n"
                f"• Total Fleet Solar: **{total_solar_w:.1f} W**\n"
                f"• Total Fleet Wind: **{total_wind_w:.1f} W**\n"
                f"• Total Compute Load: **{total_load_w:.1f} W**\n"
                f"• Net Clean Surplus: **{net_surplus:.1f} W**\n\n"
                f"**Top Solar Producing Microgrids**:\n{top_str}"
            )

        elif any(
            w in prompt_lower for w in ["why", "route", "decision", "bedrock", "cloud", "fallback"]
        ):
            cloud_decisions = [d for d in recent_decisions if d.get("target_kind") == "cloud"]
            if cloud_decisions:
                last_cloud = cloud_decisions[0]
                answer = (
                    f"☁️ **Routing & Cloud Audit Analysis**:\n\n"
                    f"• Recent cloud offload rate: "
                    f"**{len(cloud_decisions)}/{len(recent_decisions)} recent queries**.\n"
                    f"• Most recent cloud decision ID: `{last_cloud.get('decision_id')}`\n"
                    f"• Reason: *{last_cloud.get('reason')}*\n"
                    f"• Origin: {last_cloud.get('origin_city')} / {last_cloud.get('origin_site')}\n"
                    f"• Latency: {last_cloud.get('execution_latency_ms')} ms\n\n"
                    "SunRoute routes to AWS Bedrock when battery drops below reserve floors,\n"
                    "when tokens exceed edge limits, or when latency SLAs require cloud compute."
                )
            else:
                answer = (
                    "⚡ **Routing Efficiency Report**:\n\n"
                    f"• In the last {len(recent_decisions)} requests, **100% of queries were\n"
                    "successfully resolved on community edge microgrids**.\n"
                    "• Zero cloud escalations were triggered because local battery and solar\n"
                    "reserves satisfied all operational SLAs."
                )

        else:
            backend_name = type(state.cloud_client).__name__
            answer = (
                f"📊 **SunRoute Microgrid Fleet Operations Summary**:\n\n"
                f"• **Active Nodes**: {online_count}/{total_edge} microgrid nodes online.\n"
                f"• **Solar Generation**: {total_solar_w:.1f} W | **Wind**: {total_wind_w:.1f} W\n"
                f"• **Fleet Battery Reserve**: {avg_soc * 100:.1f}% average SOC\n"
                f"• **Recent Audit Decisions**: {len(recent_decisions)} logged in SQLite\n"
                f"• **Cloud Fallback Tier**: AWS Bedrock Runtime ({backend_name})\n\n"
                "You can ask me questions like: *'Which nodes have low battery?'*, "
                "*'Show solar generation'*, or *'Why was the last query routed to cloud?'*."
            )

        return {
            "prompt": req.prompt,
            "response": answer,
            "telemetry_timestamp": datetime.now(UTC).isoformat(),
            "nodes_analyzed": len(nodes_telem),
        }

    # Mount compiled frontend dashboard if built
    dist_path = Path(__file__).resolve().parent.parent / "dashboard" / "dist"
    if dist_path.exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="static")

    return app


# Default gateway instance (enables 30-city simulation by default)
app = create_gateway_app(enable_30_cities=True)
