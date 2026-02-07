from __future__ import annotations

from typing import Protocol

import httpx

from app.models import ChatMessage


class LLMClient(Protocol):
    async def generate_reply(
        self,
        *,
        model: str,
        topic: str,
        persona_prompt: str,
        history: list[ChatMessage],
        priority_message: ChatMessage | None,
    ) -> str: ...


class OpenRouterClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_temperature: float,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model_temperature = model_temperature
        self._timeout = timeout_seconds

    async def generate_reply(
        self,
        *,
        model: str,
        topic: str,
        persona_prompt: str,
        history: list[ChatMessage],
        priority_message: ChatMessage | None,
    ) -> str:
        if not self._api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set.")

        system_prompt = (
            "You are in a multi-agent chat room.\n"
            f"Topic: {topic}\n"
            f"{persona_prompt}\n"
            "Respond with exactly one natural chat turn."
        )
        payload = {
            "model": model,
            "temperature": self._model_temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": self._render_history(history, priority_message)},
            ],
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions", json=payload, headers=headers
            )
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            text_parts = [str(part.get("text", "")) for part in content if isinstance(part, dict)]
            reply = " ".join(part for part in text_parts if part).strip()
        else:
            reply = str(content).strip()

        if not reply:
            raise RuntimeError("Model returned empty response.")
        return reply

    @staticmethod
    def _render_history(history: list[ChatMessage], priority_message: ChatMessage | None) -> str:
        lines: list[str] = []
        for message in history:
            lines.append(f"{message.speaker_id}: {message.content}")
        if priority_message is not None:
            lines.append(f"Priority from user: {priority_message.content}")
        if not lines:
            return "No previous chat yet. Start the conversation."
        return "\n".join(lines[-24:])
