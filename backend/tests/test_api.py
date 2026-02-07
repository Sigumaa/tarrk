from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import ChatMessage
from app.orchestrator import RoomManager


class StaticLLM:
    async def generate_reply(
        self,
        *,
        model: str,
        display_name: str,
        role_type: str,
        subject: str,
        act_name: str,
        act_goal: str,
        persona_prompt: str,
        history: list[ChatMessage],
        priority_message: ChatMessage | None,
    ) -> str:
        return f"[{act_name}] reply from {model}"


def build_client() -> TestClient:
    settings = Settings(
        openrouter_api_key="test",
        loop_interval_seconds=0.0,
        default_max_rounds=1,
        history_limit=6,
        max_consecutive_failures=2,
    )
    manager = RoomManager(llm_client=StaticLLM(), settings=settings)
    app = create_app()
    app.state.room_manager = manager
    return TestClient(app)


def test_room_api_lifecycle() -> None:
    client = build_client()

    create_response = client.post(
        "/api/room/create",
        json={"subject": "favorite snacks", "models": ["m1", "m2"], "seed": 42},
    )
    assert create_response.status_code == 200
    body = create_response.json()
    room_id = body["room_id"]
    assert body["subject"] == "favorite snacks"
    assert body["agents"][0]["display_name"] == "m1"
    assert body["agents"][0]["role_type"] == "facilitator"

    start_response = client.post(f"/api/room/{room_id}/start", json={"max_rounds": 1})
    assert start_response.status_code == 200
    assert start_response.json() == {"status": "running"}

    time.sleep(0.03)

    user_response = client.post(
        f"/api/room/{room_id}/user-message",
        json={"content": "途中参加です"},
    )
    assert user_response.status_code == 200
    assert user_response.json() == {"status": "accepted"}

    stop_response = client.post(f"/api/room/{room_id}/stop")
    assert stop_response.status_code == 200
    assert stop_response.json() == {"status": "stopped"}


def test_room_api_returns_404_for_unknown_room() -> None:
    client = build_client()
    response = client.post("/api/room/missing-room/start", json={})
    assert response.status_code == 404
