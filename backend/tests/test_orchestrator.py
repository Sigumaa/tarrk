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
        return f"[{model}] {topic}"


class FailingLLM:
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
        AgentSpec(agent_id="agent-1", model="m1", role_name="r1", persona_prompt="p1"),
        AgentSpec(agent_id="agent-2", model="m2", role_name="r2", persona_prompt="p2"),
    ]
    speaker = choose_next_speaker(agents=agents, last_speaker_id="agent-1", rng=Random(1))
    assert speaker.agent_id == "agent-2"


def test_trim_history_respects_limit() -> None:
    messages = [ChatMessage(role="user", speaker_id="user", content=str(i)) for i in range(6)]
    trimmed = trim_history(messages, limit=3)
    assert [item.content for item in trimmed] == ["3", "4", "5"]


@pytest.mark.asyncio
async def test_room_loop_generates_messages() -> None:
    manager = RoomManager(llm_client=StaticLLM(), settings=_build_settings(default_max_rounds=2))
    room = manager.create_room(
        topic="pizza",
        models=["m1", "m2"],
        background="社内ハッカソン企画",
        context="対象は20代の夜食ユーザー",
        language="日本語",
        global_instruction="日本語で会話し、要点をまとめること。",
        seed=1,
    )

    await manager.start_room(room.room_id)
    await asyncio.sleep(0.05)

    assert room.running is False
    assert len([message for message in room.messages if message.role == "agent"]) == 2
    assert room.background == "社内ハッカソン企画"
    assert room.context == "対象は20代の夜食ユーザー"
    assert room.language == "日本語"
    assert "日本語で会話" in room.global_instruction


@pytest.mark.asyncio
async def test_room_stops_after_consecutive_failures() -> None:
    manager = RoomManager(
        llm_client=FailingLLM(), settings=_build_settings(max_consecutive_failures=2)
    )
    room = manager.create_room(topic="fail", models=["m1"], seed=2)

    await manager.start_room(room.room_id, max_rounds=10)
    await asyncio.sleep(0.05)

    assert room.running is False
    assert room.fail_streak >= 2


@pytest.mark.asyncio
async def test_update_instructions_fails_while_running() -> None:
    manager = RoomManager(llm_client=StaticLLM(), settings=_build_settings(default_max_rounds=100))
    room = manager.create_room(topic="topic", models=["m1", "m2"], seed=1)

    async with room.lock:
        room.running = True

    with pytest.raises(RuntimeError):
        await manager.update_room_instructions(room.room_id, topic="updated")
