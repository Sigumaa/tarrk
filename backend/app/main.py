from __future__ import annotations

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.config import Settings
from app.openrouter import OpenRouterClient
from app.orchestrator import RoomManager


def create_app() -> FastAPI:
    settings = Settings()
    llm_client = OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model_temperature=settings.model_temperature,
    )
    manager = RoomManager(llm_client=llm_client, settings=settings)

    app = FastAPI(title="LLM Chat Room", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.state.room_manager = manager

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.websocket("/ws/room/{room_id}")
    async def room_socket(websocket: WebSocket, room_id: str) -> None:
        await websocket.accept()
        try:
            await manager.register_ws(room_id=room_id, websocket=websocket)
        except KeyError:
            await websocket.send_json({"type": "error", "payload": {"detail": "Room not found."}})
            await websocket.close(code=4404)
            return

        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await manager.unregister_ws(room_id=room_id, websocket=websocket)

    return app


app = create_app()
