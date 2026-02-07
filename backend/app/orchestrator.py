from __future__ import annotations

import asyncio
import contextlib
from random import Random
from typing import Literal
from uuid import uuid4

from fastapi import WebSocket

from app.config import Settings
from app.models import AgentSpec, ChatMessage, ConversationMode, GenerationLog, Room
from app.openrouter import LLMClient
from app.persona import generate_personas

ACTS: tuple[tuple[str, str], ...] = (
    ("導入", "お題の前提をそろえ、立場を短く提示する。"),
    ("衝突", "視点の違いをぶつけ、対立点を明確にする。"),
    ("具体化", "実行可能な案・手順・条件に落とし込む。"),
    ("締め", "合意点と未解決点を整理して着地させる。"),
)


def choose_next_speaker(
    *,
    agents: list[AgentSpec],
    last_speaker_id: str | None,
    rng: Random,
) -> AgentSpec:
    if len(agents) == 1:
        return agents[0]
    candidates = [agent for agent in agents if agent.agent_id != last_speaker_id]
    if not candidates:
        candidates = agents
    return rng.choice(candidates)


def trim_history(messages: list[ChatMessage], limit: int) -> list[ChatMessage]:
    if limit <= 0:
        return []
    return messages[-limit:]


def resolve_act(rounds_completed: int, max_rounds: int) -> tuple[str, str]:
    if max_rounds <= 0:
        return ACTS[0]
    index = min(len(ACTS) - 1, int((rounds_completed / max_rounds) * len(ACTS)))
    return ACTS[index]


def build_topic_card(subject: str, rng: Random) -> str:
    cards = (
        f"お題カード: 「{subject}」を30秒デモにするなら、最初に見せる一手は何？",
        f"お題カード: 「{subject}」で一番炎上しそうな点を先に潰すなら？",
        f"お題カード: 「{subject}」を無料で試せる形にするには？",
        f"お題カード: 「{subject}」を友達に1文で勧めるなら？",
    )
    return rng.choice(cards)


class RoomManager:
    def __init__(self, *, llm_client: LLMClient, settings: Settings) -> None:
        self._llm_client = llm_client
        self._settings = settings
        self._rooms: dict[str, Room] = {}

    def create_room(
        self,
        *,
        subject: str,
        models: list[str],
        conversation_mode: ConversationMode,
        global_instruction: str,
        turn_interval_seconds: float,
        seed: int | None = None,
    ) -> Room:
        if not models:
            raise ValueError("At least one model is required.")
        room_id = uuid4().hex[:8]
        persona_seed = seed if seed is not None else int(room_id, 16)
        rng = Random(persona_seed)
        agents = self._build_agents(
            models=models,
            subject=subject,
            conversation_mode=conversation_mode,
            global_instruction=global_instruction,
            persona_seed=persona_seed,
        )
        room = Room(
            room_id=room_id,
            subject=subject,
            agents=agents,
            rng=rng,
            persona_seed=persona_seed,
            conversation_mode=conversation_mode,
            global_instruction=global_instruction.strip(),
            turn_interval_seconds=turn_interval_seconds,
        )
        self._rooms[room_id] = room
        return room

    def get_room(self, room_id: str) -> Room:
        room = self._rooms.get(room_id)
        if room is None:
            raise KeyError(room_id)
        return room

    async def start_room(self, room_id: str, max_rounds: int | None = None) -> None:
        room = self.get_room(room_id)
        async with room.lock:
            if room.running:
                return
            room.running = True
            room.stop_requested = False
            room.stop_reason = None
            room.fail_streak = 0
            room.rounds_completed = 0
            room.current_act = ACTS[0][0]
            room.end_reason = None
            room.topic_card_used = False
            target_rounds = max_rounds or self._settings.default_max_rounds
            room.task = asyncio.create_task(
                self._run_room_loop(room=room, max_rounds=target_rounds)
            )
        await self._broadcast_room_state(room)

    async def stop_room(self, room_id: str, *, reason: str = "manual_stop") -> None:
        room = self.get_room(room_id)
        async with room.lock:
            task = room.task
            room.running = False
            room.stop_requested = True
            room.stop_reason = reason
            room.task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._broadcast_room_state(room)

    async def update_room_config(
        self,
        room_id: str,
        *,
        conversation_mode: ConversationMode | None = None,
        global_instruction: str | None = None,
        turn_interval_seconds: float | None = None,
    ) -> Room:
        room = self.get_room(room_id)
        async with room.lock:
            mode_changed = False
            if conversation_mode is not None and conversation_mode != room.conversation_mode:
                if room.running:
                    raise RuntimeError("Cannot update conversation mode while running.")
                room.conversation_mode = conversation_mode
                mode_changed = True

            if global_instruction is not None:
                normalized = global_instruction.strip()
                if normalized != room.global_instruction:
                    if room.running:
                        raise RuntimeError("Cannot update global instruction while running.")
                    room.global_instruction = normalized
                    mode_changed = True

            if turn_interval_seconds is not None:
                room.turn_interval_seconds = turn_interval_seconds

            if mode_changed:
                room.agents = self._build_agents(
                    models=[agent.model for agent in room.agents],
                    subject=room.subject,
                    conversation_mode=room.conversation_mode,
                    global_instruction=room.global_instruction,
                    persona_seed=room.persona_seed,
                )
        return room

    async def add_user_message(self, room_id: str, content: str) -> ChatMessage:
        room = self.get_room(room_id)
        message = ChatMessage(role="user", speaker_id="user", content=content)
        room.messages.append(message)
        room.pending_priority_message = message
        await self._broadcast(
            room, {"type": "message", "payload": self._serialize_message(message)}
        )
        return message

    async def register_ws(self, room_id: str, websocket: WebSocket) -> None:
        room = self.get_room(room_id)
        room.ws_connections.add(websocket)
        await self._send_room_snapshot(room=room, websocket=websocket)

    async def unregister_ws(self, room_id: str, websocket: WebSocket) -> None:
        try:
            room = self.get_room(room_id)
        except KeyError:
            return
        room.ws_connections.discard(websocket)

    async def _run_room_loop(self, *, room: Room, max_rounds: int) -> None:
        rounds = 0
        end_reason = "max_rounds"
        try:
            while room.running and rounds < max_rounds:
                room.current_act, act_goal = resolve_act(
                    rounds_completed=rounds, max_rounds=max_rounds
                )

                if not room.topic_card_used and max_rounds >= 6 and rounds >= max_rounds // 2:
                    topic_card = ChatMessage(
                        role="user",
                        speaker_id="お題カード",
                        content=build_topic_card(room.subject, room.rng),
                    )
                    room.topic_card_used = True
                    room.messages.append(topic_card)
                    room.pending_priority_message = topic_card
                    await self._broadcast(
                        room,
                        {"type": "message", "payload": self._serialize_message(topic_card)},
                    )

                speaker = choose_next_speaker(
                    agents=room.agents,
                    last_speaker_id=room.last_speaker_id,
                    rng=room.rng,
                )
                history = trim_history(room.messages, self._settings.history_limit)
                priority_message = room.pending_priority_message
                room.pending_priority_message = None

                await self._emit_generation_log(
                    room=room,
                    round_index=rounds + 1,
                    model=speaker.model,
                    display_name=speaker.display_name,
                    act=room.current_act,
                    status="requesting",
                )
                try:
                    content = await self._llm_client.generate_reply(
                        model=speaker.model,
                        display_name=speaker.display_name,
                        role_type=speaker.role_type,
                        subject=room.subject,
                        conversation_mode=room.conversation_mode,
                        global_instruction=room.global_instruction,
                        act_name=room.current_act,
                        act_goal=act_goal,
                        persona_prompt=speaker.persona_prompt,
                        history=history,
                        priority_message=priority_message,
                    )
                    room.fail_streak = 0
                    await self._emit_generation_log(
                        room=room,
                        round_index=rounds + 1,
                        model=speaker.model,
                        display_name=speaker.display_name,
                        act=room.current_act,
                        status="completed",
                    )
                except Exception as exc:  # noqa: BLE001
                    room.fail_streak += 1
                    await self._emit_generation_log(
                        room=room,
                        round_index=rounds + 1,
                        model=speaker.model,
                        display_name=speaker.display_name,
                        act=room.current_act,
                        status="failed",
                        detail=str(exc),
                    )
                    await self._broadcast(
                        room,
                        {
                            "type": "error",
                            "payload": {
                                "detail": f"LLM call failed: {exc}",
                                "fail_streak": room.fail_streak,
                            },
                        },
                    )
                    if room.fail_streak >= self._settings.max_consecutive_failures:
                        room.running = False
                        end_reason = "failures"
                        await self._broadcast(
                            room,
                            {
                                "type": "error",
                                "payload": {"detail": "Stopped after consecutive failures."},
                            },
                        )
                        break
                    await asyncio.sleep(room.turn_interval_seconds)
                    continue

                message = ChatMessage(
                    role="agent",
                    speaker_id=speaker.display_name,
                    content=content,
                )
                room.messages.append(message)
                room.last_speaker_id = speaker.agent_id
                rounds += 1
                room.rounds_completed = rounds
                await self._broadcast(
                    room, {"type": "message", "payload": self._serialize_message(message)}
                )

                await asyncio.sleep(room.turn_interval_seconds)

            if room.stop_requested:
                end_reason = room.stop_reason or "manual_stop"
            elif rounds >= max_rounds and end_reason == "max_rounds":
                end_reason = "max_rounds"
        finally:
            if room.stop_requested:
                end_reason = room.stop_reason or "manual_stop"
            room.end_reason = end_reason
            if room.messages and not self._summary_already_exists(room):
                summary = ChatMessage(
                    role="agent",
                    speaker_id="総括",
                    content=self._build_final_summary(room),
                )
                room.messages.append(summary)
                await self._broadcast(
                    room, {"type": "message", "payload": self._serialize_message(summary)}
                )

            room.running = False
            room.task = None
            room.current_act = "終了"
            await self._broadcast_room_state(room)

    async def _send_room_snapshot(self, *, room: Room, websocket: WebSocket) -> None:
        await websocket.send_json(self._build_snapshot_event(room))

    async def _broadcast_room_state(self, room: Room) -> None:
        await self._broadcast(
            room,
            {
                "type": "room_state",
                "payload": {
                    "room_id": room.room_id,
                    "running": room.running,
                    "current_act": room.current_act,
                    "rounds_completed": room.rounds_completed,
                    "end_reason": room.end_reason,
                },
            },
        )

    async def _broadcast(self, room: Room, event: dict[str, object]) -> None:
        dead_connections: list[WebSocket] = []
        for websocket in room.ws_connections:
            try:
                await websocket.send_json(event)
            except Exception:  # noqa: BLE001
                dead_connections.append(websocket)
        for websocket in dead_connections:
            room.ws_connections.discard(websocket)

    async def _emit_generation_log(
        self,
        *,
        room: Room,
        round_index: int,
        model: str,
        display_name: str,
        act: str,
        status: Literal["requesting", "completed", "failed"],
        detail: str = "",
    ) -> None:
        log = GenerationLog(
            round_index=round_index,
            model=model,
            display_name=display_name,
            act=act,
            status=status,
            detail=detail,
        )
        room.generation_logs.append(log)
        if len(room.generation_logs) > 120:
            room.generation_logs = room.generation_logs[-120:]
        await self._broadcast(
            room,
            {"type": "generation_log", "payload": self._serialize_generation_log(log)},
        )

    @staticmethod
    def _serialize_message(message: ChatMessage) -> dict[str, str]:
        return {
            "role": message.role,
            "speaker_id": message.speaker_id,
            "content": message.content,
            "timestamp": message.timestamp,
        }

    @staticmethod
    def _serialize_generation_log(log: GenerationLog) -> dict[str, str | int]:
        return {
            "round_index": log.round_index,
            "model": log.model,
            "display_name": log.display_name,
            "act": log.act,
            "status": log.status,
            "detail": log.detail,
            "timestamp": log.timestamp,
        }

    @staticmethod
    def _summary_already_exists(room: Room) -> bool:
        if not room.messages:
            return False
        return room.messages[-1].speaker_id == "総括"

    @staticmethod
    def _build_final_summary(room: Room) -> str:
        reason_map = {
            "max_rounds": "ラウンド上限に到達したため終了しました。",
            "manual_stop": "ユーザー操作で終了しました。",
            "user_concluded": "ユーザーが「発展余地が少ない」と判断して終了しました。",
            "failures": "連続エラーにより終了しました。",
            None: "会話が終了しました。",
        }

        agent_messages = [
            message.content
            for message in room.messages
            if message.role == "agent" and message.speaker_id != "総括"
        ]
        last_meaningful = (
            agent_messages[-1]
            if agent_messages
            else "お題の方向性は有望で、短期検証の価値があります。"
        )
        conclusion_text = last_meaningful.strip()
        if len(conclusion_text) > 120:
            conclusion_text = f"{conclusion_text[:117]}..."

        next_step = (
            f"「{room.subject}」について、今日の結論をもとに5分で試せる最小プロトタイプを1つ作り、"
            "反応を確認する。"
        )

        return (
            f"【最終まとめ】{reason_map.get(room.end_reason, reason_map[None])}\n"
            f"今日の結論: {conclusion_text}\n"
            f"次の一手: {next_step}"
        )

    @staticmethod
    def _build_snapshot_event(room: Room) -> dict[str, object]:
        return {
            "type": "room_snapshot",
            "payload": {
                "room_id": room.room_id,
                "subject": room.subject,
                "running": room.running,
                "current_act": room.current_act,
                "rounds_completed": room.rounds_completed,
                "end_reason": room.end_reason,
                "generation_logs": [
                    RoomManager._serialize_generation_log(log) for log in room.generation_logs
                ],
                "conversation_mode": room.conversation_mode,
                "global_instruction": room.global_instruction,
                "turn_interval_seconds": room.turn_interval_seconds,
                "agents": [
                    {
                        "agent_id": agent.agent_id,
                        "model": agent.model,
                        "display_name": agent.display_name,
                        "role_type": agent.role_type,
                        "character_profile": agent.character_profile,
                    }
                    for agent in room.agents
                ],
                "messages": [RoomManager._serialize_message(message) for message in room.messages],
            },
        }

    @staticmethod
    def _build_agents(
        *,
        models: list[str],
        subject: str,
        conversation_mode: ConversationMode,
        global_instruction: str,
        persona_seed: int,
    ) -> list[AgentSpec]:
        persona_rng = Random(persona_seed)
        return generate_personas(
            models=models,
            subject=subject,
            mode=conversation_mode,
            global_instruction=global_instruction,
            rng=persona_rng,
        )
