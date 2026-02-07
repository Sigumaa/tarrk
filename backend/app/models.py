from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from random import Random
from typing import Literal

from fastapi import WebSocket

MessageRole = Literal["user", "agent"]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class ChatMessage:
    role: MessageRole
    speaker_id: str
    content: str
    timestamp: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class AgentSpec:
    agent_id: str
    model: str
    persona_prompt: str


@dataclass(slots=True)
class Room:
    room_id: str
    topic: str
    agents: list[AgentSpec]
    rng: Random
    messages: list[ChatMessage] = field(default_factory=list)
    running: bool = False
    task: asyncio.Task[None] | None = None
    last_speaker_id: str | None = None
    pending_priority_message: ChatMessage | None = None
    fail_streak: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    ws_connections: set[WebSocket] = field(default_factory=set)
