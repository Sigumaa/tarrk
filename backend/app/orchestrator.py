from __future__ import annotations

import asyncio
import contextlib
from random import Random
from uuid import uuid4

from fastapi import WebSocket

from app.config import Settings
from app.models import AgentSpec, ChatMessage, RoleType, Room
from app.openrouter import LLMClient
from app.persona import build_persona_prompt, generate_personas


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

    def create_room(self, *, subject: str, models: list[str], seed: int | None = None) -> Room:
        if not models:
            raise ValueError("At least one model is required.")
        room_id = uuid4().hex[:8]
        rng = Random(seed)
        agents = generate_personas(models=models, rng=rng)
        room = Room(room_id=room_id, subject=subject, agents=agents, rng=rng)
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

    async def update_room_setup(
        self,
        room_id: str,
        *,
        subject: str | None = None,
        role_updates: list[tuple[str, RoleType, str]] | None = None,
    ) -> Room:
        room = self.get_room(room_id)
        async with room.lock:
            if room.running:
                raise RuntimeError("Cannot update setup while room is running.")
            if subject is not None:
                room.subject = subject

            if role_updates:
                index = {agent.agent_id: agent for agent in room.agents}
                for agent_id, role_type, character_profile in role_updates:
                    target = index.get(agent_id)
                    if target is None:
                        raise ValueError(f"Unknown agent_id: {agent_id}")
                    target.role_type = role_type
                    target.character_profile = (
                        "" if role_type == "facilitator" else character_profile.strip()
                    )
                    target.persona_prompt = build_persona_prompt(
                        role_type=target.role_type,
                        character_profile=target.character_profile,
                    )

                facilitator_count = sum(
                    1 for agent in room.agents if agent.role_type == "facilitator"
                )
                if facilitator_count != 1:
                    raise ValueError("Exactly one facilitator is required.")

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
                        display_name=speaker.display_name,
                        role_type=speaker.role_type,
                        subject=room.subject,
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

                message = ChatMessage(
                    role="agent",
                    speaker_id=speaker.display_name,
                    content=content,
                )
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
                "subject": room.subject,
                "running": room.running,
                "agents": [
                    {
                        "agent_id": agent.agent_id,
                        "model": agent.model,
                        "display_name": agent.display_name,
                        "role_type": agent.role_type,
                        "character_profile": agent.character_profile,
                        "persona_prompt": agent.persona_prompt,
                    }
                    for agent in room.agents
                ],
                "messages": [RoomManager._serialize_message(message) for message in room.messages],
            },
        }
