from __future__ import annotations

import asyncio
from random import Random

import pytest

from app.config import Settings
from app.models import AgentSpec, ChatMessage
from app.orchestrator import RoomManager, choose_next_speaker, resolve_act, trim_history


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
        return f"[{act_name}] {subject}"


class FailingLLM:
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
        raise RuntimeError("boom")


def _build_settings(
    *,
    default_max_rounds: int = 8,
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


def test_resolve_act_changes_with_progress() -> None:
    assert resolve_act(0, 8)[0] == "導入"
    assert resolve_act(3, 8)[0] == "衝突"
    assert resolve_act(5, 8)[0] == "具体化"
    assert resolve_act(7, 8)[0] == "締め"


@pytest.mark.asyncio
async def test_room_loop_finishes_with_summary_on_max_rounds() -> None:
    manager = RoomManager(llm_client=StaticLLM(), settings=_build_settings(default_max_rounds=6))
    room = manager.create_room(subject="ピザ論争", models=["m1", "m2"], seed=1)

    await manager.start_room(room.room_id)
    await asyncio.sleep(0.06)

    assert room.running is False
    assert room.end_reason == "max_rounds"
    assert any(message.speaker_id == "総括" for message in room.messages)
    assert any("今日の結論" in message.content for message in room.messages)


@pytest.mark.asyncio
async def test_room_stops_after_consecutive_failures() -> None:
    manager = RoomManager(
        llm_client=FailingLLM(),
        settings=_build_settings(max_consecutive_failures=2),
    )
    room = manager.create_room(subject="fail", models=["m1"], seed=4)

    await manager.start_room(room.room_id, max_rounds=10)
    await asyncio.sleep(0.05)

    assert room.running is False
    assert room.fail_streak >= 2
    assert room.end_reason == "failures"


@pytest.mark.asyncio
async def test_room_emits_generation_logs() -> None:
    manager = RoomManager(llm_client=StaticLLM(), settings=_build_settings(default_max_rounds=2))
    room = manager.create_room(subject="ログ確認", models=["m1", "m2"], seed=5)

    await manager.start_room(room.room_id)
    await asyncio.sleep(0.05)

    assert room.generation_logs
    statuses = {log.status for log in room.generation_logs}
    assert "requesting" in statuses
    assert "completed" in statuses


@pytest.mark.asyncio
async def test_room_can_be_concluded_by_user() -> None:
    manager = RoomManager(
        llm_client=StaticLLM(),
        settings=_build_settings(default_max_rounds=500, loop_interval_seconds=0.02),
    )
    room = manager.create_room(subject="自由意志", models=["m1", "m2"], seed=6)

    await manager.start_room(room.room_id)
    await asyncio.sleep(0)
    await manager.stop_room(room.room_id, reason="user_concluded")
    await asyncio.sleep(0.03)

    assert room.running is False
    assert room.end_reason == "user_concluded"
