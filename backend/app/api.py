from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.models import ConversationMode, RoleType
from app.orchestrator import RoomManager

router = APIRouter(prefix="/api")


class CreateRoomRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=2000)
    models: list[str] = Field(min_length=1, max_length=8)
    conversation_mode: ConversationMode = "philosophy_debate"
    global_instruction: str = Field(default="", max_length=1200)
    turn_interval_seconds: float = Field(default=0.5, ge=0.0, le=5.0)
    seed: int | None = None


class AgentResponse(BaseModel):
    agent_id: str
    model: str
    display_name: str
    role_type: RoleType
    character_profile: str


class RoomResponse(BaseModel):
    room_id: str
    subject: str
    conversation_mode: ConversationMode
    global_instruction: str
    turn_interval_seconds: float
    agents: list[AgentResponse]


class StartRoomRequest(BaseModel):
    max_rounds: int | None = Field(default=None, ge=1, le=500)


class UpdateRoomConfigRequest(BaseModel):
    conversation_mode: ConversationMode | None = None
    global_instruction: str | None = Field(default=None, max_length=1200)
    turn_interval_seconds: float | None = Field(default=None, ge=0.0, le=5.0)


class StatusResponse(BaseModel):
    status: str


class UserMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


def get_room_manager(request: Request) -> RoomManager:
    return cast(RoomManager, request.app.state.room_manager)


RoomManagerDep = Annotated[RoomManager, Depends(get_room_manager)]


def build_room_response(room_id: str, manager: RoomManager) -> RoomResponse:
    room = manager.get_room(room_id)
    return RoomResponse(
        room_id=room.room_id,
        subject=room.subject,
        conversation_mode=room.conversation_mode,
        global_instruction=room.global_instruction,
        turn_interval_seconds=room.turn_interval_seconds,
        agents=[
            AgentResponse(
                agent_id=agent.agent_id,
                model=agent.model,
                display_name=agent.display_name,
                role_type=agent.role_type,
                character_profile=agent.character_profile,
            )
            for agent in room.agents
        ],
    )


@router.post("/room/create", response_model=RoomResponse)
def create_room(payload: CreateRoomRequest, manager: RoomManagerDep) -> RoomResponse:
    room = manager.create_room(
        subject=payload.subject,
        models=payload.models,
        conversation_mode=payload.conversation_mode,
        global_instruction=payload.global_instruction,
        turn_interval_seconds=payload.turn_interval_seconds,
        seed=payload.seed,
    )
    return build_room_response(room.room_id, manager)


@router.post("/room/{room_id}/start", response_model=StatusResponse)
async def start_room(
    room_id: str,
    payload: StartRoomRequest,
    manager: RoomManagerDep,
) -> StatusResponse:
    try:
        await manager.start_room(room_id=room_id, max_rounds=payload.max_rounds)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Room not found."
        ) from exc
    return StatusResponse(status="running")


@router.post("/room/{room_id}/stop", response_model=StatusResponse)
async def stop_room(room_id: str, manager: RoomManagerDep) -> StatusResponse:
    try:
        await manager.stop_room(room_id=room_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Room not found."
        ) from exc
    return StatusResponse(status="stopped")


@router.post("/room/{room_id}/pause", response_model=StatusResponse)
async def pause_room(room_id: str, manager: RoomManagerDep) -> StatusResponse:
    try:
        await manager.pause_room(room_id=room_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Room not found."
        ) from exc
    return StatusResponse(status="paused")


@router.post("/room/{room_id}/resume", response_model=StatusResponse)
async def resume_room(room_id: str, manager: RoomManagerDep) -> StatusResponse:
    try:
        await manager.resume_room(room_id=room_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Room not found."
        ) from exc
    return StatusResponse(status="running")


@router.post("/room/{room_id}/conclude", response_model=StatusResponse)
async def conclude_room(room_id: str, manager: RoomManagerDep) -> StatusResponse:
    try:
        await manager.stop_room(room_id=room_id, reason="user_concluded")
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Room not found."
        ) from exc
    return StatusResponse(status="concluded")


@router.post("/room/{room_id}/config", response_model=RoomResponse)
async def update_room_config(
    room_id: str,
    payload: UpdateRoomConfigRequest,
    manager: RoomManagerDep,
) -> RoomResponse:
    try:
        room = await manager.update_room_config(
            room_id=room_id,
            conversation_mode=payload.conversation_mode,
            global_instruction=payload.global_instruction,
            turn_interval_seconds=payload.turn_interval_seconds,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Room not found."
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return build_room_response(room.room_id, manager)


@router.post("/room/{room_id}/user-message", response_model=StatusResponse)
async def add_user_message(
    room_id: str,
    payload: UserMessageRequest,
    manager: RoomManagerDep,
) -> StatusResponse:
    try:
        await manager.add_user_message(room_id=room_id, content=payload.content)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Room not found."
        ) from exc
    return StatusResponse(status="accepted")
