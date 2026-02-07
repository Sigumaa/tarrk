from __future__ import annotations

from typing import Protocol

import httpx

from app.models import ChatMessage


class LLMClient(Protocol):
    async def generate_reply(
        self,
        *,
        model: str,
        agent_id: str,
        role_name: str,
        topic: str,
        background: str,
        context: str,
        language: str,
        global_instruction: str,
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
        agent_id: str,
        role_name: str,
        topic: str,
        background: str,
        context: str,
        language: str,
        global_instruction: str,
        persona_prompt: str,
        history: list[ChatMessage],
        priority_message: ChatMessage | None,
    ) -> str:
        if not self._api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set.")

        system_prompt = self._build_system_prompt(
            agent_id=agent_id,
            role_name=role_name,
            topic=topic,
            background=background,
            context=context,
            language=language,
            global_instruction=global_instruction,
            persona_prompt=persona_prompt,
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
    def _build_system_prompt(
        *,
        agent_id: str,
        role_name: str,
        topic: str,
        background: str,
        context: str,
        language: str,
        global_instruction: str,
        persona_prompt: str,
    ) -> str:
        normalized_background = background.strip() or "指定なし"
        normalized_context = context.strip() or "指定なし"
        normalized_instruction = global_instruction.strip() or "指定なし"
        return (
            "あなたは複数LLMによるラウンドテーブル会話の参加者です。\n"
            f"会話言語: {language}。必ず {language} で発話してください。\n\n"
            "会話の背景情報:\n"
            f"- テーマ: {topic}\n"
            f"- 背景: {normalized_background}\n"
            f"- コンテキスト: {normalized_context}\n"
            "\n"
            "全体システム指示:\n"
            f"{normalized_instruction}\n\n"
            "あなたの担当:\n"
            f"- ID: {agent_id}\n"
            f"- 役割: {role_name}\n"
            f"{persona_prompt}\n"
        )

    @staticmethod
    def _render_history(history: list[ChatMessage], priority_message: ChatMessage | None) -> str:
        lines: list[str] = []
        for message in history:
            lines.append(f"{message.speaker_id}: {message.content}")
        if priority_message is not None:
            lines.append(f"user(priority): {priority_message.content}")
        if not lines:
            return "まだ会話はありません。最初の発言をしてください。"
        return "\n".join(lines[-24:])
