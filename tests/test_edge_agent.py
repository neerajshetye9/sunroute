"""Unit and integration tests for SunRoute Edge Agent."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from edge.agent import create_app
from edge.config import EdgeConfig


@pytest.fixture
def edge_config():
    return EdgeConfig(
        node_id="test-jetson-01",
        city="city-01",
        api_token="valid-secret-token",
        max_queue_depth=2,
        max_prompt_tokens=500,
        max_prompt_chars=1000,
        thermal_limit_c=80.0,
    )


@pytest.fixture
def test_app(edge_config):
    return create_app(edge_config)


@pytest.fixture
async def client(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def make_valid_request_payload(
    prompt: str = "Explain community energy microgrids.",
    prompt_tokens: int = 50,
    priority: str = "normal",
):
    return {
        "request_id": str(uuid.uuid4()),
        "created_at": "2026-11-02T12:00:00Z",
        "origin": {"city": "city-01", "site": "society-12"},
        "task_type": "short_qa",
        "prompt_tokens_est": prompt_tokens,
        "max_output_tokens": 64,
        "latency_target_ms": 2000,
        "priority": priority,
        "privacy": "local_only",
        "min_quality_tier": "basic",
        "prompt": prompt,
    }


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    res = await client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["node_id"] == "test-jetson-01"
    assert "uptime_s" in data
    assert data["queue_depth"] == 0


@pytest.mark.asyncio
async def test_state_endpoint(client: AsyncClient):
    res = await client.get("/state")
    assert res.status_code == 200
    data = res.json()
    assert data["node_id"] == "test-jetson-01"
    assert data["city"] == "city-01"
    assert data["kind"] == "physical"
    assert 0.0 <= data["battery_soc"] <= 1.0
    assert data["connectivity"] == "online"
    assert data["energy_source"] in ("simulated", "measured")


@pytest.mark.asyncio
async def test_infer_missing_auth(client: AsyncClient):
    payload = make_valid_request_payload()
    res = await client.post("/infer", json=payload)
    assert res.status_code == 401
    assert "Missing or invalid Bearer authentication token" in res.json()["detail"]


@pytest.mark.asyncio
async def test_infer_invalid_token(client: AsyncClient):
    payload = make_valid_request_payload()
    headers = {"Authorization": "Bearer wrong-token"}
    res = await client.post("/infer", json=payload, headers=headers)
    assert res.status_code == 401
    assert "Invalid API token" in res.json()["detail"]


@pytest.mark.asyncio
async def test_infer_successful(client: AsyncClient):
    payload = make_valid_request_payload()
    headers = {"Authorization": "Bearer valid-secret-token"}
    res = await client.post("/infer", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["node_id"] == "test-jetson-01"
    assert data["request_id"] == payload["request_id"]
    assert len(data["text"]) > 0
    assert data["prompt_tokens"] == 50
    assert data["output_tokens"] > 0
    assert data["latency_ms"] >= 0.0
    assert data["energy_consumed_j_est"] >= 0.0


@pytest.mark.asyncio
async def test_infer_payload_size_limit(client: AsyncClient):
    # Prompt tokens exceed max_prompt_tokens (500)
    payload = make_valid_request_payload(prompt_tokens=600)
    headers = {"Authorization": "Bearer valid-secret-token"}
    res = await client.post("/infer", json=payload, headers=headers)
    assert res.status_code == 400
    assert "Prompt tokens" in res.json()["detail"]


@pytest.mark.asyncio
async def test_infer_prompt_char_length_limit(client: AsyncClient):
    # Characters exceed max_prompt_chars (1000)
    huge_prompt = "A" * 1200
    payload = make_valid_request_payload(prompt=huge_prompt)
    headers = {"Authorization": "Bearer valid-secret-token"}
    res = await client.post("/infer", json=payload, headers=headers)
    assert res.status_code == 400
    assert "Prompt character length" in res.json()["detail"]


@pytest.mark.asyncio
async def test_infer_invalid_enum_validation(client: AsyncClient):
    payload = make_valid_request_payload()
    payload["task_type"] = "invalid_task_type"
    headers = {"Authorization": "Bearer valid-secret-token"}
    res = await client.post("/infer", json=payload, headers=headers)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_infer_queue_depth_throttling(test_app):
    # Artificially set queue depth to capacity
    test_app.state.manager.queue_depth = 2
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = make_valid_request_payload()
        headers = {"Authorization": "Bearer valid-secret-token"}
        res = await ac.post("/infer", json=payload, headers=headers)
        assert res.status_code == 429
        assert "queue full" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_infer_critical_battery_rejection(test_app):
    # Battery SOC below critical threshold (0.10)
    test_app.state.manager.battery_soc = 0.05
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = make_valid_request_payload(priority="normal")
        headers = {"Authorization": "Bearer valid-secret-token"}
        res = await ac.post("/infer", json=payload, headers=headers)
        assert res.status_code == 503
        assert "Battery critically low" in res.json()["detail"]

        # Essential task should still be permitted under low battery
        payload_essential = make_valid_request_payload(priority="essential")
        res_essential = await ac.post("/infer", json=payload_essential, headers=headers)
        assert res_essential.status_code == 200
