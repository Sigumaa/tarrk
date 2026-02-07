from __future__ import annotations

import asyncio
import contextlib
from random import Random
from uuid import uuid4

from fastapi import WebSocket

from app.config import Settings
from app.models import AgentSpec, ChatMessage, Room
from app.openrouter import LLMClient
from app.persona import generate_personas

DEFAULT_GLOBAL_INSTRUCTION = (
    "会話の目的は、テーマに対して多角的な視点を出し、次に取る行動を明確にすることです。\n"
    "必ず会話言語に従って発話し、専門用語には短い補足を添えてください。\n"
    "他のagentの発言を受けてから話し、同じ主張の反復は避けてください。\n"
    "1ターンは2〜4文で簡潔にまとめ、最後に次の検討ポイントを1つ示してください。"
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


class RoomManager:
    def __init__(self, *, llm_client: LLMClient, settings: Settings) -> None:
        self._llm_client = llm_client
        self._settings = settings
        self._rooms: dict[str, Room] = {}

    def create_room(
        self,
        *,
        topic: str,
        models: list[str],
        background: str = "",
        context: str = "",
        language: str = "日本語",
        global_instruction: str = "",
        seed: int | None = None,
    ) -> Room:
        if not models:
            raise ValueError("At least one model is required.")
        room_id = uuid4().hex[:8]
        rng = Random(seed)
        agents = generate_personas(models=models, rng=rng)
        room = Room(
            room_id=room_id,
            topic=topic,
            background=background,
            context=context,
            language=language,
            global_instruction=global_instruction.strip() or DEFAULT_GLOBAL_INSTRUCTION,
            agents=agents,
            rng=rng,
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
            room.fail_streak = 0
            target_rounds = max_rounds or self._settings.default_max_rounds
            room.task = asyncio.create_task(
                self._run_room_loop(room=room, max_rounds=target_rounds)
            )
        await self._broadcast_room_state(room)

    async def stop_room(self, room_id: str) -> None:
        room = self.get_room(room_id)
        async with room.lock:
            task = room.task
            room.running = False
            room.task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._broadcast_room_state(room)

    async def add_user_message(self, room_id: str, content: str) -> ChatMessage:
        room = self.get_room(room_id)
        message = ChatMessage(role="user", speaker_id="user", content=content)
        room.messages.append(message)
        room.pending_priority_message = message
        await self._broadcast(
            room, {"type": "message", "payload": self._serialize_message(message)}
        )
        return message

    async def update_room_instructions(
        self,
        room_id: str,
        *,
        topic: str | None = None,
        background: str | None = None,
        context: str | None = None,
        language: str | None = None,
        global_instruction: str | None = None,
        persona_overrides: dict[str, str] | None = None,
    ) -> Room:
        room = self.get_room(room_id)
        async with room.lock:
            if room.running:
                raise RuntimeError("Cannot update instructions while room is running.")
            if topic is not None:
                room.topic = topic
            if background is not None:
                room.background = background
            if context is not None:
                room.context = context
            if language is not None:
                room.language = language
            if global_instruction is not None:
                room.global_instruction = global_instruction.strip() or DEFAULT_GLOBAL_INSTRUCTION

            if persona_overrides:
                agent_index = {agent.agent_id: agent for agent in room.agents}
                for agent_id, prompt in persona_overrides.items():
                    agent = agent_index.get(agent_id)
                    if agent is None:
                        raise ValueError(f"Unknown agent_id: {agent_id}")
                    agent.persona_prompt = prompt

        await self._broadcast_snapshot(room)
        return room

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
        try:
            while room.running and rounds < max_rounds:
                speaker = choose_next_speaker(
                    agents=room.agents,
                    last_speaker_id=room.last_speaker_id,
                    rng=room.rng,
                )
                history = trim_history(room.messages, self._settings.history_limit)
                priority_message = room.pending_priority_message
                room.pending_priority_message = None

                try:
                    content = await self._llm_client.generate_reply(
                        model=speaker.model,
                        agent_id=speaker.agent_id,
                        role_name=speaker.role_name,
                        topic=room.topic,
                        background=room.background,
                        context=room.context,
                        language=room.language,
                        global_instruction=room.global_instruction,
                        persona_prompt=speaker.persona_prompt,
                        history=history,
                        priority_message=priority_message,
                    )
                    room.fail_streak = 0
                except Exception as exc:  # noqa: BLE001
                    room.fail_streak += 1
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
                        await self._broadcast(
                            room,
                            {
                                "type": "error",
                                "payload": {"detail": "Stopped after consecutive failures."},
                            },
                        )
                        break
                    await asyncio.sleep(self._settings.loop_interval_seconds)
                    continue

                message = ChatMessage(role="agent", speaker_id=speaker.agent_id, content=content)
                room.messages.append(message)
                room.last_speaker_id = speaker.agent_id
                rounds += 1
                await self._broadcast(
                    room, {"type": "message", "payload": self._serialize_message(message)}
                )
                await asyncio.sleep(self._settings.loop_interval_seconds)
        finally:
            room.running = False
            room.task = None
            await self._broadcast_room_state(room)

    async def _send_room_snapshot(self, *, room: Room, websocket: WebSocket) -> None:
        await websocket.send_json(self._build_snapshot_event(room))

    async def _broadcast_snapshot(self, room: Room) -> None:
        await self._broadcast(room, self._build_snapshot_event(room))

    async def _broadcast_room_state(self, room: Room) -> None:
        await self._broadcast(
            room,
            {
                "type": "room_state",
                "payload": {
                    "room_id": room.room_id,
                    "running": room.running,
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

    @staticmethod
    def _serialize_message(message: ChatMessage) -> dict[str, str]:
        return {
            "role": message.role,
            "speaker_id": message.speaker_id,
            "content": message.content,
            "timestamp": message.timestamp,
        }

    @staticmethod
    def _build_snapshot_event(room: Room) -> dict[str, object]:
        return {
            "type": "room_snapshot",
            "payload": {
                "room_id": room.room_id,
                "topic": room.topic,
                "background": room.background,
                "context": room.context,
                "language": room.language,
                "global_instruction": room.global_instruction,
                "running": room.running,
                "agents": [
                    {
                        "agent_id": agent.agent_id,
                        "model": agent.model,
                        "role_name": agent.role_name,
                        "persona_prompt": agent.persona_prompt,
                    }
                    for agent in room.agents
                ],
                "messages": [RoomManager._serialize_message(message) for message in room.messages],
            },
        }
