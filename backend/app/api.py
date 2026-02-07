from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.orchestrator import RoomManager

router = APIRouter(prefix="/api")


class CreateRoomRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    models: list[str] = Field(min_length=1, max_length=8)
    background: str = Field(default="", max_length=1500)
    context: str = Field(default="", max_length=1500)
    language: str = Field(default="日本語", min_length=1, max_length=50)
    global_instruction: str = Field(default="", max_length=3000)
    seed: int | None = None


class PersonaResponse(BaseModel):
    agent_id: str
    model: str
    role_name: str
    persona_prompt: str


class CreateRoomResponse(BaseModel):
    room_id: str
    topic: str
    background: str
    context: str
    language: str
    global_instruction: str
    personas: list[PersonaResponse]


class StartRoomRequest(BaseModel):
    max_rounds: int | None = Field(default=None, ge=1, le=500)


class StatusResponse(BaseModel):
    status: str


class UserMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


class UpdatePersonaRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=50)
    persona_prompt: str = Field(min_length=1, max_length=2000)


class UpdateRoomInstructionsRequest(BaseModel):
    topic: str | None = Field(default=None, min_length=1, max_length=500)
    background: str | None = Field(default=None, max_length=1500)
    context: str | None = Field(default=None, max_length=1500)
    language: str | None = Field(default=None, min_length=1, max_length=50)
    global_instruction: str | None = Field(default=None, max_length=3000)
    personas: list[UpdatePersonaRequest] | None = Field(default=None, max_length=8)


def get_room_manager(request: Request) -> RoomManager:
    return cast(RoomManager, request.app.state.room_manager)


RoomManagerDep = Annotated[RoomManager, Depends(get_room_manager)]


@router.post("/room/create", response_model=CreateRoomResponse)
def create_room(payload: CreateRoomRequest, manager: RoomManagerDep) -> CreateRoomResponse:
    room = manager.create_room(
        topic=payload.topic,
        models=payload.models,
        background=payload.background,
        context=payload.context,
        language=payload.language,
        global_instruction=payload.global_instruction,
        seed=payload.seed,
    )
    return CreateRoomResponse(
        room_id=room.room_id,
        topic=room.topic,
        background=room.background,
        context=room.context,
        language=room.language,
        global_instruction=room.global_instruction,
        personas=[
            PersonaResponse(
                agent_id=agent.agent_id,
                model=agent.model,
                role_name=agent.role_name,
                persona_prompt=agent.persona_prompt,
            )
            for agent in room.agents
        ],
    )


@router.put("/room/{room_id}/instructions", response_model=CreateRoomResponse)
async def update_room_instructions(
    room_id: str,
    payload: UpdateRoomInstructionsRequest,
    manager: RoomManagerDep,
) -> CreateRoomResponse:
    persona_overrides: dict[str, str] | None = None
    if payload.personas:
        persona_overrides = {item.agent_id: item.persona_prompt for item in payload.personas}

    try:
        room = await manager.update_room_instructions(
            room_id=room_id,
            topic=payload.topic,
            background=payload.background,
            context=payload.context,
            language=payload.language,
            global_instruction=payload.global_instruction,
            persona_overrides=persona_overrides,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Room not found."
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return CreateRoomResponse(
        room_id=room.room_id,
        topic=room.topic,
        background=room.background,
        context=room.context,
        language=room.language,
        global_instruction=room.global_instruction,
        personas=[
            PersonaResponse(
                agent_id=agent.agent_id,
                model=agent.model,
                role_name=agent.role_name,
                persona_prompt=agent.persona_prompt,
            )
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
