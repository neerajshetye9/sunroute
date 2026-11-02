"""Unit and integration tests for Gateway, Mock Cloud, and Decision Audit Log."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from cloud.mock_client import MockCloudClient
from edge.agent import create_app as create_edge_app
from edge.config import EdgeConfig
from edge.schemas import (
    InferenceRequest,
    NodeKind,
    Origin,
    Priority,
    Privacy,
    QualityTier,
    TaskType,
)
from gateway.app import create_gateway_app
from gateway.decision_log import DecisionAuditLog
from router.schemas import HierarchyLevel, PolicyType


def make_request(prompt: str = "Test prompt", priority: Priority = Priority.NORMAL):
    return InferenceRequest(
        request_id=uuid.uuid4(),
        created_at=datetime.now(UTC),
        origin=Origin(city="city-01", site="society-12"),
        task_type=TaskType.SHORT_QA,
        prompt_tokens_est=50,
        max_output_tokens=32,
        latency_target_ms=2000,
        priority=priority,
        privacy=Privacy.ANY,
        min_quality_tier=QualityTier.BASIC,
        prompt=prompt,
    )


@pytest.mark.asyncio
async def test_mock_cloud_client():
    client = MockCloudClient()
    req = make_request()
    res = await client.infer(req)

    assert res.request_id == req.request_id
    assert res.node_id == "aws-bedrock-central"
    assert res.prompt_tokens == 50
    assert res.output_tokens > 0
    assert res.latency_ms > 0
    assert res.energy_consumed_j_est > 0

    state = await client.get_state()
    assert state.kind == NodeKind.CLOUD
    assert state.node_id == "aws-bedrock-central"
    assert state.free_mem_mb > 100000


def test_decision_audit_log(tmp_path: Path):
    db_file = tmp_path / "test_audit.db"
    log = DecisionAuditLog(db_file)

    req = make_request()
    from router.schemas import Decision, ScoreBreakdown

    dec = Decision(
        target_node_id="jetson-01",
        target_kind=NodeKind.PHYSICAL,
        target_level=HierarchyLevel.LOCAL,
        score_breakdown=ScoreBreakdown(energy=0.8, total_score=0.75),
        reason="Local node matched",
        policy_used=PolicyType.PROPOSED,
        timestamp_iso="2026-11-02T12:00:00Z",
    )

    rec_id = log.record(dec, req, execution_latency_ms=120.5, success=True)
    assert rec_id is not None
    assert log.count() == 1

    records = log.list_decisions(limit=10)
    assert len(records) == 1
    r = records[0]
    assert r["request_id"] == str(req.request_id)
    assert r["target_node_id"] == "jetson-01"
    assert r["policy_used"] == "proposed"
    assert r["execution_success"] == 1


@pytest.mark.asyncio
async def test_gateway_full_local_loop(tmp_path: Path):
    db_file = tmp_path / "gw_audit.db"
    gw_app = create_gateway_app(audit_db_path=db_file)
    edge_app = create_edge_app(
        EdgeConfig(node_id="edge-01", city="city-01", api_token="secret-token")
    )

    edge_transport = ASGITransport(app=edge_app)
    gw_transport = ASGITransport(app=gw_app)

    async with (
        AsyncClient(transport=edge_transport, base_url="http://edge:8001") as edge_client,
        AsyncClient(transport=gw_transport, base_url="http://gw:8000") as client,
    ):
        # Point gateway's http client to edge test client
        gw_app.state.gateway.http_client = edge_client

        # Register edge node
        reg_res = await client.post(
            "/v1/nodes/register",
            json={
                "node_id": "edge-01",
                "url": "http://edge:8001",
                "api_token": "secret-token",
                "city": "city-01",
            },
        )
        assert reg_res.status_code == 201

        # Check telemetry aggregation
        telemetry_res = await client.get("/v1/telemetry/nodes")
        assert telemetry_res.status_code == 200
        nodes = telemetry_res.json()
        assert len(nodes) == 2  # edge-01 + aws-bedrock-central

        # Test inference via proposed router
        req_payload = {
            "request_id": str(uuid.uuid4()),
            "created_at": "2026-11-02T12:00:00Z",
            "origin": {"city": "city-01", "site": "society-12"},
            "task_type": "short_qa",
            "prompt_tokens_est": 40,
            "max_output_tokens": 30,
            "latency_target_ms": 2000,
            "priority": "normal",
            "privacy": "any",
            "min_quality_tier": "basic",
            "prompt": "Explain local routing.",
        }

        infer_res = await client.post(
            "/v1/chat/completions?policy=proposed",
            json=req_payload,
        )
        assert infer_res.status_code == 200
        data = infer_res.json()
        assert data["node_id"] == "edge-01"

        # Verify audit log was written
        decisions_res = await client.get("/v1/decisions?limit=10")
        assert decisions_res.status_code == 200
        decisions = decisions_res.json()
        assert len(decisions) >= 1
        assert decisions[0]["target_node_id"] == "edge-01"
        assert decisions[0]["execution_success"] == 1
