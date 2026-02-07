from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.models import RoleType
from app.orchestrator import RoomManager

router = APIRouter(prefix="/api")


class CreateRoomRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    models: list[str] = Field(min_length=1, max_length=8)
    seed: int | None = None


class AgentResponse(BaseModel):
    agent_id: str
    model: str
    display_name: str
    role_type: RoleType
    character_profile: str
    persona_prompt: str


class RoomResponse(BaseModel):
    room_id: str
    subject: str
    agents: list[AgentResponse]


class StartRoomRequest(BaseModel):
    max_rounds: int | None = Field(default=None, ge=1, le=500)


class StatusResponse(BaseModel):
    status: str


class UserMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


class UpdateAgentRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=50)
    role_type: RoleType
    character_profile: str = Field(default="", max_length=1000)


class UpdateRoomSetupRequest(BaseModel):
    subject: str | None = Field(default=None, min_length=1, max_length=500)
    agents: list[UpdateAgentRequest] | None = Field(default=None, max_length=8)


def get_room_manager(request: Request) -> RoomManager:
    return cast(RoomManager, request.app.state.room_manager)


RoomManagerDep = Annotated[RoomManager, Depends(get_room_manager)]


def build_room_response(room_id: str, manager: RoomManager) -> RoomResponse:
    room = manager.get_room(room_id)
    return RoomResponse(
        room_id=room.room_id,
        subject=room.subject,
        agents=[
            AgentResponse(
                agent_id=agent.agent_id,
                model=agent.model,
                display_name=agent.display_name,
                role_type=agent.role_type,
                character_profile=agent.character_profile,
                persona_prompt=agent.persona_prompt,
            )
            for agent in room.agents
        ],
    )


@router.post("/room/create", response_model=RoomResponse)
def create_room(payload: CreateRoomRequest, manager: RoomManagerDep) -> RoomResponse:
    room = manager.create_room(subject=payload.subject, models=payload.models, seed=payload.seed)
    return build_room_response(room.room_id, manager)


@router.put("/room/{room_id}/setup", response_model=RoomResponse)
async def update_room_setup(
    room_id: str,
    payload: UpdateRoomSetupRequest,
    manager: RoomManagerDep,
) -> RoomResponse:
    updates: list[tuple[str, RoleType, str]] | None = None
    if payload.agents is not None:
        updates = [
            (item.agent_id, item.role_type, item.character_profile) for item in payload.agents
        ]
    try:
        await manager.update_room_setup(
            room_id=room_id,
            subject=payload.subject,
            role_updates=updates,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Room not found."
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return build_room_response(room_id, manager)


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
