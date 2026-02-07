from __future__ import annotations

import asyncio
from random import Random

import pytest

from app.config import Settings
from app.models import AgentSpec, ChatMessage
from app.orchestrator import RoomManager, choose_next_speaker, trim_history


class StaticLLM:
    async def generate_reply(
        self,
        *,
        model: str,
        display_name: str,
        role_type: str,
        subject: str,
        persona_prompt: str,
        history: list[ChatMessage],
        priority_message: ChatMessage | None,
    ) -> str:
        return f"[{display_name}] {subject}"


class FailingLLM:
    async def generate_reply(
        self,
        *,
        model: str,
        display_name: str,
        role_type: str,
        subject: str,
        persona_prompt: str,
        history: list[ChatMessage],
        priority_message: ChatMessage | None,
    ) -> str:
        raise RuntimeError("boom")


def _build_settings(
    *,
    default_max_rounds: int = 3,
    history_limit: int = 5,
    max_consecutive_failures: int = 2,
    loop_interval_seconds: float = 0.0,
) -> Settings:
    return Settings(
        openrouter_api_key="test",
        default_max_rounds=default_max_rounds,
        history_limit=history_limit,
        max_consecutive_failures=max_consecutive_failures,
        loop_interval_seconds=loop_interval_seconds,
    )


def test_choose_next_speaker_excludes_last_speaker() -> None:
    agents = [
        AgentSpec(
            agent_id="a1",
            model="m1",
            display_name="m1",
            role_type="facilitator",
            character_profile="",
            persona_prompt="p1",
        ),
        AgentSpec(
            agent_id="a2",
            model="m2",
            display_name="m2",
            role_type="character",
            character_profile="c2",
            persona_prompt="p2",
        ),
    ]
    speaker = choose_next_speaker(agents=agents, last_speaker_id="a1", rng=Random(1))
    assert speaker.agent_id == "a2"


def test_trim_history_respects_limit() -> None:
    messages = [ChatMessage(role="user", speaker_id="user", content=str(i)) for i in range(6)]
    trimmed = trim_history(messages, limit=3)
    assert [item.content for item in trimmed] == ["3", "4", "5"]


@pytest.mark.asyncio
async def test_room_loop_generates_messages_with_display_name() -> None:
    manager = RoomManager(llm_client=StaticLLM(), settings=_build_settings(default_max_rounds=2))
    room = manager.create_room(subject="ピザ論争", models=["m1", "m2"], seed=1)

    await manager.start_room(room.room_id)
    await asyncio.sleep(0.05)

    assert room.running is False
    agent_messages = [message for message in room.messages if message.role == "agent"]
    assert len(agent_messages) == 2
    assert all(message.speaker_id in {"m1", "m2"} for message in agent_messages)


@pytest.mark.asyncio
async def test_room_stops_after_consecutive_failures() -> None:
    manager = RoomManager(
        llm_client=FailingLLM(),
        settings=_build_settings(max_consecutive_failures=2),
    )
    room = manager.create_room(subject="fail", models=["m1"], seed=2)

    await manager.start_room(room.room_id, max_rounds=10)
    await asyncio.sleep(0.05)

    assert room.running is False
    assert room.fail_streak >= 2


@pytest.mark.asyncio
async def test_update_room_setup_requires_stopped_room() -> None:
    manager = RoomManager(llm_client=StaticLLM(), settings=_build_settings(default_max_rounds=100))
    room = manager.create_room(subject="topic", models=["m1", "m2"], seed=1)

    async with room.lock:
        room.running = True

    with pytest.raises(RuntimeError):
        await manager.update_room_setup(room.room_id, subject="updated")


@pytest.mark.asyncio
async def test_update_room_setup_updates_roles_and_subject() -> None:
    manager = RoomManager(llm_client=StaticLLM(), settings=_build_settings())
    room = manager.create_room(subject="初期お題", models=["m1", "m2"], seed=3)

    await manager.update_room_setup(
        room.room_id,
        subject="更新お題",
        role_updates=[
            (room.agents[0].agent_id, "character", "皮肉屋の論客"),
            (room.agents[1].agent_id, "facilitator", ""),
        ],
    )

    assert room.subject == "更新お題"
    assert room.agents[0].role_type == "character"
    assert room.agents[1].role_type == "facilitator"
