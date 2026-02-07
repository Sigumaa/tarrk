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
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            if response.is_error:
                detail = self._extract_error_detail(response)
                if self._should_retry_without_temperature(response.status_code, detail):
                    retry_payload = {
                        "model": model,
                        "messages": payload["messages"],
                    }
                    response = await client.post(
                        f"{self._base_url}/chat/completions",
                        json=retry_payload,
                        headers=headers,
                    )
                    if response.is_error:
                        retry_detail = self._extract_error_detail(response)
                        raise RuntimeError(
                            "OpenRouter API error "
                            f"({response.status_code}) for model '{model}': {retry_detail}"
                        )
                else:
                    raise RuntimeError(
                        "OpenRouter API error "
                        f"({response.status_code}) for model '{model}': {detail}"
                    )

            data = response.json()

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"OpenRouter response does not contain choices for model '{model}'.")
        message = choices[0].get("message", {})
        content = message.get("content")
        if content is None:
            raise RuntimeError(f"OpenRouter response has empty content for model '{model}'.")
        if isinstance(content, list):
            text_parts = [str(part.get("text", "")) for part in content if isinstance(part, dict)]
            reply = " ".join(part for part in text_parts if part).strip()
        else:
            reply = str(content).strip()

        if not reply:
            raise RuntimeError("Model returned empty response.")
        return reply

    @staticmethod
    def _extract_error_detail(response: httpx.Response) -> str:
        try:
            data = response.json()
        except Exception:  # noqa: BLE001
            text = response.text.strip()
            return text or f"HTTP {response.status_code}"

        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                code = error.get("code")
                if isinstance(message, str) and message:
                    if isinstance(code, str) and code:
                        return f"{code}: {message}"
                    return message
            message = data.get("message")
            if isinstance(message, str) and message:
                return message
        text = response.text.strip()
        return text or f"HTTP {response.status_code}"

    @staticmethod
    def _should_retry_without_temperature(status_code: int, detail: str) -> bool:
        lowered = detail.lower()
        return status_code == 400 and (
            "temperature" in lowered
            or "unsupported value" in lowered
            or "unsupported parameter" in lowered
            or "sampling" in lowered
        )

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
        rendered = "\n".join(lines[-24:])
        max_chars = 6000
        if len(rendered) <= max_chars:
            return rendered
        return "（履歴が長いため末尾のみ利用）\n" + rendered[-max_chars:]
