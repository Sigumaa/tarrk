from __future__ import annotations

from typing import Protocol

import httpx

from app.models import ChatMessage, RoleType


class LLMClient(Protocol):
    async def generate_reply(
        self,
        *,
        model: str,
        display_name: str,
        role_type: RoleType,
        subject: str,
        act_name: str,
        act_goal: str,
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
        display_name: str,
        role_type: RoleType,
        subject: str,
        act_name: str,
        act_goal: str,
        persona_prompt: str,
        history: list[ChatMessage],
        priority_message: ChatMessage | None,
    ) -> str:
        if not self._api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set.")

        system_prompt = self._build_system_prompt(
            display_name=display_name,
            role_type=role_type,
            subject=subject,
            act_name=act_name,
            act_goal=act_goal,
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
    def _build_system_prompt(
        *,
        display_name: str,
        role_type: RoleType,
        subject: str,
        act_name: str,
        act_goal: str,
        persona_prompt: str,
    ) -> str:
        normalized_subject = subject.strip() or "与えられたお題"
        role_text = "ファシリテーター" if role_type == "facilitator" else "議論参加者"
        return (
            "あなたは複数LLMの会話ルームにいます。\n"
            "必ず日本語で話してください。\n"
            f"あなたの表示名: {display_name}\n"
            f"あなたの役割: {role_text}\n"
            f"議論するお題: {normalized_subject}\n\n"
            f"現在の進行幕: {act_name}\n"
            f"この幕の狙い: {act_goal}\n\n"
            "共通ルール:\n"
            "- 1ターンは3〜6文\n"
            "- 直前の発言を受けてから自分の意見を述べる\n"
            "- 具体例か思考実験を1つ含める\n"
            "- 会話を勝手に終了しない（終了判断はユーザが行う）\n\n"
            f"{persona_prompt}"
        )

    @staticmethod
    def _render_history(history: list[ChatMessage], priority_message: ChatMessage | None) -> str:
        lines: list[str] = []
        for message in history:
            lines.append(f"{message.speaker_id}: {message.content}")
        if priority_message is not None:
            lines.append(f"user(priority): {priority_message.content}")
        if not lines:
            return "まだ会話はありません。お題について議論を始めてください。"
        rendered = "\n".join(lines[-24:])
        max_chars = 6000
        if len(rendered) <= max_chars:
            return rendered
        return "（履歴が長いため末尾のみ利用）\n" + rendered[-max_chars:]

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
