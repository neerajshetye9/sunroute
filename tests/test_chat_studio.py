"""Tests for SunRoute multi-user Chat Studio and Ops Copilot endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from gateway.app import create_gateway_app


@pytest.mark.asyncio
async def test_chat_auth_and_conversations():
    app = create_gateway_app(audit_db_path="experiments/test_audit.db", enable_30_cities=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Demo login
        login_resp = await client.post(
            "/v1/auth/login",
            json={"username": "test_student", "display_name": "Test Student", "role": "student"},
        )
        assert login_resp.status_code == 200
        user = login_resp.json()["user"]
        assert user["username"] == "test_student"
        user_id = user["user_id"]

        # 2. List demo users
        users_resp = await client.get("/v1/auth/users")
        assert users_resp.status_code == 200
        assert len(users_resp.json()) >= 4

        # 3. Create conversation
        conv_resp = await client.post(
            "/v1/chat/conversations",
            json={"user_id": user_id, "title": "Microgrid Inquiry"},
        )
        assert conv_resp.status_code == 200
        conv_id = conv_resp.json()["conversation_id"]

        # 4. List conversations
        list_conv = await client.get(f"/v1/chat/conversations?user_id={user_id}")
        assert list_conv.status_code == 200
        assert any(c["conversation_id"] == conv_id for c in list_conv.json())

        # 5. Send chat message
        msg_resp = await client.post(
            "/v1/chat/messages",
            json={
                "conversation_id": conv_id,
                "user_id": user_id,
                "prompt": "Explain solar battery microgrids",
                "origin_city": "city-02",
                "policy": "proposed",
            },
        )
        assert msg_resp.status_code == 200
        data = msg_resp.json()
        assert "assistant_message" in data
        assert "routing_metadata" in data["assistant_message"]
        assert data["assistant_message"]["routing_metadata"]["policy_used"] == "proposed"

        # 6. Retrieve conversation details
        details_resp = await client.get(f"/v1/chat/conversations/{conv_id}")
        assert details_resp.status_code == 200
        msgs = details_resp.json()["messages"]
        assert len(msgs) == 2  # user and assistant

        # 7. Delete conversation
        del_resp = await client.delete(f"/v1/chat/conversations/{conv_id}")
        assert del_resp.status_code == 200


@pytest.mark.asyncio
async def test_ops_copilot():
    app = create_gateway_app(audit_db_path="experiments/test_audit.db", enable_30_cities=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Ask about battery status
        copilot_resp = await client.post(
            "/v1/ops/copilot",
            json={"prompt": "Which nodes have low battery?"},
        )
        assert copilot_resp.status_code == 200
        data = copilot_resp.json()
        assert "response" in data
        assert "Battery" in data["response"]
        assert data["nodes_analyzed"] >= 30

        # Ask about solar power
        solar_resp = await client.post(
            "/v1/ops/copilot",
            json={"prompt": "Show solar generation across all regions"},
        )
        assert solar_resp.status_code == 200
        assert "Solar" in solar_resp.json()["response"]
