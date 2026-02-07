from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from random import Random
from typing import Literal

from fastapi import WebSocket

MessageRole = Literal["user", "agent"]
RoleType = Literal["facilitator", "character"]
ConversationMode = Literal["philosophy_debate", "devils_advocate", "consensus_lab"]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class ChatMessage:
    role: MessageRole
    speaker_id: str
    content: str
    timestamp: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class GenerationLog:
    round_index: int
    model: str
    display_name: str
    act: str
    status: Literal["requesting", "completed", "failed"]
    detail: str = ""
    timestamp: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class AgentSpec:
    agent_id: str
    model: str
    display_name: str
    role_type: RoleType
    character_profile: str
    persona_prompt: str


@dataclass(slots=True)
class Room:
    room_id: str
    subject: str
    agents: list[AgentSpec]
    rng: Random
    persona_seed: int
    conversation_mode: ConversationMode
    global_instruction: str = ""
    turn_interval_seconds: float = 0.5
    messages: list[ChatMessage] = field(default_factory=list)
    running: bool = False
    task: asyncio.Task[None] | None = None
    last_speaker_id: str | None = None
    pending_priority_message: ChatMessage | None = None
    fail_streak: int = 0
    rounds_completed: int = 0
    current_act: str = "導入"
    paused: bool = False
    topic_card_used: bool = False
    stop_requested: bool = False
    stop_reason: str | None = None
    end_reason: str | None = None
    generation_logs: list[GenerationLog] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    ws_connections: set[WebSocket] = field(default_factory=set)
