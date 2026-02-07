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
        agent_id: str,
        role_name: str,
        topic: str,
        background: str,
        context: str,
        language: str,
        global_instruction: str,
        persona_prompt: str,
        history: list[ChatMessage],
        priority_message: ChatMessage | None,
    ) -> str:
        return f"reply from {model}"


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
        json={
            "topic": "favorite snacks",
            "background": "深夜帯の雑談",
            "context": "二人で軽く企画検討",
            "language": "日本語",
            "global_instruction": "日本語で議論し、要点を短く整理すること。",
            "models": ["m1", "m2"],
            "seed": 42,
        },
    )
    assert create_response.status_code == 200
    body = create_response.json()
    room_id = body["room_id"]
    assert body["background"] == "深夜帯の雑談"
    assert body["context"] == "二人で軽く企画検討"
    assert body["language"] == "日本語"
    assert "日本語で議論" in body["global_instruction"]
    assert body["personas"][0]["role_name"]

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


def test_room_instructions_can_be_updated_before_start() -> None:
    client = build_client()

    create_response = client.post(
        "/api/room/create",
        json={"topic": "initial", "models": ["m1", "m2"]},
    )
    room_id = create_response.json()["room_id"]
    first_agent_id = create_response.json()["personas"][0]["agent_id"]

    update_response = client.put(
        f"/api/room/{room_id}/instructions",
        json={
            "topic": "updated topic",
            "background": "背景を更新",
            "context": "文脈を更新",
            "language": "日本語",
            "global_instruction": "必ず日本語で、短く建設的に議論すること。",
            "personas": [
                {
                    "agent_id": first_agent_id,
                    "persona_prompt": "あなたは検証担当。根拠を明確に述べてください。",
                }
            ],
        },
    )

    assert update_response.status_code == 200
    body = update_response.json()
    assert body["topic"] == "updated topic"
    assert body["background"] == "背景を更新"
    assert body["context"] == "文脈を更新"
    assert body["language"] == "日本語"
    assert "必ず日本語" in body["global_instruction"]
    assert "検証担当" in body["personas"][0]["persona_prompt"]
