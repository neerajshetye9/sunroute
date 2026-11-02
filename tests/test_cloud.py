"""Unit tests for SunRoute Phase 4 Cloud & AWS components.

Tests:
- AWS capability check auditor and report generation
- BedrockCloudClient with graceful fallback
- Ingestion Lambda and SQS worker handlers
- TelemetryPusher outbox flushing over HTTP
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest

from cloud.bedrock_client import BedrockCloudClient
from cloud.ingestion_handler import api_gateway_handler
from edge.outbox import SQLiteOutbox
from edge.schemas import InferenceRequest, Origin, TaskType
from edge.telemetry_pusher import TelemetryPusher
from scripts.check_aws_capabilities import AWSCapabilityChecker


def test_aws_capability_checker_no_credentials(tmp_path: Path) -> None:
    checker = AWSCapabilityChecker(region_name="us-east-1")
    # In environment without AWS credentials, run_checks returns NO_CREDENTIALS safely
    results = checker.run_checks()
    assert results["verdict"] in ("NO_CREDENTIALS", "AUTH_FAILED", "FULL_ACCESS", "PARTIAL_ACCESS")

    out_file = tmp_path / "test_report.md"
    report = checker.generate_markdown_report(output_path=out_file)
    assert out_file.exists()
    assert "# AWS Capability and Permission Audit Report" in report
    assert "Service Accessibility Matrix" in report


@pytest.mark.asyncio
async def test_bedrock_cloud_client_fallback() -> None:
    client = BedrockCloudClient(model_id="amazon.titan-text-express-v1", fallback_to_mock=True)

    # Health check
    h = client.health()
    assert "status" in h
    assert h["fallback_enabled"] is True

    # State check
    st = client.get_state()
    assert st.node_id == "aws-bedrock-datacenter"
    assert st.kind.value == "cloud"
    assert st.load_w > 0.0

    # Inference execution (transparently handled via calibrated mock fallback if no AWS credentials)
    req = InferenceRequest(
        request_id=uuid4(),
        origin=Origin(city="city-01", site="society-1"),
        task_type=TaskType.SHORT_QA,
        prompt_tokens_est=50,
        max_output_tokens=30,
        latency_target_ms=2000,
        prompt="Explain solar power routing",
    )
    resp = await client.infer(req)
    assert resp.request_id == req.request_id
    assert resp.output_tokens > 0
    assert resp.latency_ms > 0.0
    assert resp.energy_consumed_j_est > 0.0


def test_ingestion_api_gateway_handler_auth_and_validation() -> None:
    # 1. Missing / invalid auth token
    unauth_event = {
        "headers": {"authorization": "Bearer invalid-token"},
        "body": json.dumps({"message_id": "msg-123", "node_id": "node-1"}),
    }
    resp = api_gateway_handler(unauth_event, None)
    assert resp["statusCode"] == 401

    # 2. Missing message_id
    valid_token = "sunroute-telemetry-secret-token"
    with patch.dict("os.environ", {"INGESTION_TOKEN": valid_token}):
        missing_id_event = {
            "headers": {"authorization": f"Bearer {valid_token}"},
            "body": json.dumps({"node_id": "node-1"}),
        }
        resp = api_gateway_handler(missing_id_event, None)
        assert resp["statusCode"] == 400

        # 3. Successful authenticated dry-run payload
        valid_event = {
            "headers": {"authorization": f"Bearer {valid_token}"},
            "body": json.dumps(
                {"message_id": "msg-12345", "node_id": "node-1", "battery_soc": 0.85}
            ),
        }
        resp = api_gateway_handler(valid_event, None)
        assert resp["statusCode"] in (200, 202)
        body = json.loads(resp["body"])
        assert body["message_id"] == "msg-12345"


@pytest.mark.asyncio
async def test_telemetry_pusher_flush(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test_outbox.db")
    outbox = SQLiteOutbox(db_path)

    # Enqueue a test telemetry message
    outbox.enqueue(
        message_id="msg-telemetry-001",
        topic="gateway",
        payload={"node_id": "jetson-01", "temp_c": 52.0, "battery_soc": 0.77},
    )
    assert outbox.count("pending") == 1

    # Create mock ASGI app receiving telemetry
    async def app(scope, receive, send):
        if scope["type"] == "http":
            await send(
                {
                    "type": "http.response.start",
                    "status": 202,
                    "headers": [[b"content-type", b"application/json"]],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"status": "accepted"}',
                }
            )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        pusher = TelemetryPusher(
            outbox_db_path=db_path,
            target_url="http://test/api/v1/telemetry",
            bearer_token="test-token",
        )
        delivered = await pusher.flush_batch(client=test_client)
        assert delivered == 1
        assert outbox.count("pending") == 0
