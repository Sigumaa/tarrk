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
        conversation_mode: str,
        global_instruction: str,
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
        conversation_mode: str,
        global_instruction: str,
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
    room = manager.create_room(
        subject="ピザ論争",
        models=["m1", "m2"],
        conversation_mode="philosophy_debate",
        global_instruction="",
        turn_interval_seconds=0.0,
        seed=1,
    )

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
    room = manager.create_room(
        subject="fail",
        models=["m1"],
        conversation_mode="philosophy_debate",
        global_instruction="",
        turn_interval_seconds=0.0,
        seed=4,
    )

    await manager.start_room(room.room_id, max_rounds=10)
    await asyncio.sleep(0.05)

    assert room.running is False
    assert room.fail_streak >= 2
    assert room.end_reason == "failures"


@pytest.mark.asyncio
async def test_room_emits_generation_logs() -> None:
    manager = RoomManager(llm_client=StaticLLM(), settings=_build_settings(default_max_rounds=2))
    room = manager.create_room(
        subject="ログ確認",
        models=["m1", "m2"],
        conversation_mode="philosophy_debate",
        global_instruction="",
        turn_interval_seconds=0.0,
        seed=5,
    )

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
    room = manager.create_room(
        subject="自由意志",
        models=["m1", "m2"],
        conversation_mode="philosophy_debate",
        global_instruction="",
        turn_interval_seconds=0.02,
        seed=6,
    )

    await manager.start_room(room.room_id)
    await asyncio.sleep(0)
    await manager.stop_room(room.room_id, reason="user_concluded")
    await asyncio.sleep(0.03)

    assert room.running is False
    assert room.end_reason == "user_concluded"


@pytest.mark.asyncio
async def test_room_can_pause_and_resume_without_advancing_rounds() -> None:
    manager = RoomManager(
        llm_client=StaticLLM(),
        settings=_build_settings(default_max_rounds=500, loop_interval_seconds=0.01),
    )
    room = manager.create_room(
        subject="意識",
        models=["m1", "m2"],
        conversation_mode="philosophy_debate",
        global_instruction="",
        turn_interval_seconds=0.02,
        seed=9,
    )

    await manager.start_room(room.room_id)
    await asyncio.sleep(0.08)

    await manager.pause_room(room.room_id)
    await asyncio.sleep(0.03)
    paused_rounds = room.rounds_completed
    assert room.paused is True

    await asyncio.sleep(0.08)
    assert room.rounds_completed == paused_rounds

    await manager.resume_room(room.room_id)
    assert room.paused is False
    await asyncio.sleep(0.08)
    assert room.rounds_completed > paused_rounds

    await manager.stop_room(room.room_id, reason="manual_stop")


@pytest.mark.asyncio
async def test_update_room_config_rebuilds_personas_before_start() -> None:
    manager = RoomManager(llm_client=StaticLLM(), settings=_build_settings(default_max_rounds=10))
    room = manager.create_room(
        subject="意識のハードプロブレム",
        models=["m1", "m2", "m3"],
        conversation_mode="philosophy_debate",
        global_instruction="",
        turn_interval_seconds=0.5,
        seed=7,
    )

    original_profiles = [agent.character_profile for agent in room.agents]
    updated = await manager.update_room_config(
        room.room_id,
        conversation_mode="devils_advocate",
        global_instruction="反証を重視すること",
        turn_interval_seconds=0.1,
    )

    assert updated.conversation_mode == "devils_advocate"
    assert updated.global_instruction == "反証を重視すること"
    assert updated.turn_interval_seconds == 0.1
    assert [agent.character_profile for agent in updated.agents] != original_profiles


@pytest.mark.asyncio
async def test_update_room_config_rejects_mode_change_while_running() -> None:
    manager = RoomManager(llm_client=StaticLLM(), settings=_build_settings(default_max_rounds=300))
    room = manager.create_room(
        subject="自由意志",
        models=["m1", "m2"],
        conversation_mode="philosophy_debate",
        global_instruction="",
        turn_interval_seconds=0.03,
        seed=8,
    )
    await manager.start_room(room.room_id)

    with pytest.raises(RuntimeError):
        await manager.update_room_config(room.room_id, conversation_mode="consensus_lab")

    await manager.stop_room(room.room_id, reason="manual_stop")
