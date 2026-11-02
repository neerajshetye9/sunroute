#!/usr/bin/env python3
"""Runs the complete local loop on one command:
1. Spawns/tests Edge Agent
2. Spawns/tests Gateway
3. Dispatches inference requests across all 5 policies
4. Queries and prints the append-only decision audit log
5. Verifies end-to-end correctness and exits 0
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from httpx import ASGITransport, AsyncClient  # noqa: E402

from edge.agent import create_app as create_edge_app  # noqa: E402
from edge.config import EdgeConfig  # noqa: E402
from gateway.app import create_gateway_app  # noqa: E402
from router.schemas import PolicyType  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("local_loop")


async def run_local_loop(db_path: Path) -> None:
    print("\n" + "=" * 70)
    print("SUNROUTE: STARTING LOCAL LOOP VERIFICATION (Phase 2 Exit Check)")
    print("=" * 70)

    # 1. Initialize Edge Agent
    edge_cfg = EdgeConfig(
        node_id="jetson-local-01",
        city="city-01",
        site="society-12",
        api_token="test-secret-token",
    )
    edge_app = create_edge_app(edge_cfg)

    # 2. Initialize Gateway
    gateway_app = create_gateway_app(audit_db_path=db_path)

    # In-memory transports for seamless, self-contained execution
    edge_transport = ASGITransport(app=edge_app)
    gateway_transport = ASGITransport(app=gateway_app)

    async with (
        AsyncClient(transport=edge_transport, base_url="http://edge-node:8001") as edge_client,
        AsyncClient(transport=gateway_transport, base_url="http://gateway:8000") as gw_client,
    ):
        # Override gateway http_client to route to edge_client
        gateway_app.state.gateway.http_client = edge_client

        # 3. Register edge node with gateway
        print("\n[Step 1] Registering Edge Node with Gateway...")
        reg_payload = {
            "node_id": "jetson-local-01",
            "url": "http://edge-node:8001",
            "api_token": "test-secret-token",
            "city": "city-01",
        }
        reg_res = await gw_client.post("/v1/nodes/register", json=reg_payload)
        assert reg_res.status_code == 201, f"Registration failed: {reg_res.text}"
        print(f"✓ Registered: {reg_res.json()}")

        # 4. Verify telemetry polling
        print("\n[Step 2] Polling live telemetry from all nodes...")
        telemetry_res = await gw_client.get("/v1/telemetry/nodes")
        assert telemetry_res.status_code == 200
        nodes = telemetry_res.json()
        print(f"✓ Active nodes visible to gateway ({len(nodes)}):")
        for n in nodes:
            soc_pct = n["battery_soc"] * 100.0
            print(
                f"  - [{n['kind']}] {n['node_id']} ({n['city']}) | "
                f"battery={soc_pct:.0f}% | queue={n['queue_depth']}"
            )

        # 5. Run inference queries across all 5 policies
        policies = [
            PolicyType.PROPOSED,
            PolicyType.CLOUD_ONLY,
            PolicyType.EDGE_ONLY,
            PolicyType.FCFS,
            PolicyType.CASCADE,
        ]

        print("\n[Step 3] Dispatching inference queries across all 5 policies...")
        for p in policies:
            req_id = str(uuid.uuid4())
            req_payload = {
                "request_id": req_id,
                "created_at": datetime.now(UTC).isoformat(),
                "origin": {"city": "city-01", "site": "society-12"},
                "task_type": "short_qa",
                "prompt_tokens_est": 60,
                "max_output_tokens": 40,
                "latency_target_ms": 2000,
                "priority": "normal",
                "privacy": "any",
                "min_quality_tier": "basic",
                "prompt": f"Test prompt evaluating policy {p.value}.",
            }

            res = await gw_client.post(
                f"/v1/chat/completions?policy={p.value}",
                json=req_payload,
            )
            assert res.status_code == 200, f"Query failed for {p.value}: {res.text}"
            data = res.json()
            out_toks = data["output_tokens"]
            lat = data["latency_ms"]
            print(
                f"  ✓ [{p.value:<10}] -> target={data['node_id']:<20} "
                f"tokens={out_toks:<3} latency={lat:.1f}ms"
            )

        # 6. Query and display decision audit log
        print("\n[Step 4] Querying Append-Only Decision Audit Log...")
        audit_res = await gw_client.get("/v1/decisions?limit=10")
        assert audit_res.status_code == 200
        decisions = audit_res.json()

        print("\n" + "-" * 90)
        hdr = (
            f"{'POLICY':<12} | {'TARGET NODE':<20} | {'TIER':<8} | "
            f"{'SCORE':<7} | {'LATENCY':<9} | {'REASON'}"
        )
        print(hdr)
        print("-" * 90)
        for d in reversed(decisions):
            score_str = f"{d['score_total']:.3f}" if d["score_total"] is not None else "N/A"
            lat_str = f"{d['execution_latency_ms']:.1f}ms"
            row = (
                f"{d['policy_used']:<12} | {d['target_node_id']:<20} | {d['target_level']:<8} | "
                f"{score_str:<7} | {lat_str:<9} | {d['reason'][:25]}..."
            )
            print(row)
        print("-" * 90)

    print("\n" + "=" * 70)
    print("SUCCESS: Full local loop executed end-to-end on one command!")
    print(f"Audit log saved to: {db_path}")
    print("=" * 70 + "\n")


def main() -> None:
    tmp_db = PROJECT_ROOT / "experiments" / "local_loop_audit.db"
    asyncio.run(run_local_loop(tmp_db))


if __name__ == "__main__":
    main()
