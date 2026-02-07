from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.orchestrator import RoomManager

router = APIRouter(prefix="/api")


class CreateRoomRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    models: list[str] = Field(min_length=1, max_length=8)
    seed: int | None = None


class CreateRoomResponse(BaseModel):
    room_id: str
    topic: str
    personas: list[dict[str, str]]


class StartRoomRequest(BaseModel):
    max_rounds: int | None = Field(default=None, ge=1, le=500)


class StatusResponse(BaseModel):
    status: str


class UserMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


def get_room_manager(request: Request) -> RoomManager:
    return cast(RoomManager, request.app.state.room_manager)


RoomManagerDep = Annotated[RoomManager, Depends(get_room_manager)]


@router.post("/room/create", response_model=CreateRoomResponse)
def create_room(payload: CreateRoomRequest, manager: RoomManagerDep) -> CreateRoomResponse:
    room = manager.create_room(topic=payload.topic, models=payload.models, seed=payload.seed)
    return CreateRoomResponse(
        room_id=room.room_id,
        topic=room.topic,
        personas=[
            {
                "agent_id": agent.agent_id,
                "model": agent.model,
                "persona_prompt": agent.persona_prompt,
            }
            for agent in room.agents
        ],
    )


@router.post("/room/{room_id}/start", response_model=StatusResponse)
async def start_room(
    room_id: str, payload: StartRoomRequest, manager: RoomManagerDep
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
