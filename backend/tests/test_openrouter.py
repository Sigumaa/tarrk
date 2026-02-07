from __future__ import annotations

import httpx

from app.models import ChatMessage
from app.openrouter import OpenRouterClient


def test_build_system_prompt_includes_subject_and_role() -> None:
    prompt = OpenRouterClient._build_system_prompt(
        display_name="anthropic/claude-sonnet-4.5",
        role_type="facilitator",
        subject="面白い週末ハックの案出し",
        act_name="導入",
        act_goal="お題の前提をそろえる",
        persona_prompt="司会として論点を整理してください。",
    )
    assert "必ず日本語で話してください" in prompt
    assert "議論するお題: 面白い週末ハックの案出し" in prompt
    assert "現在の進行幕: 導入" in prompt
    assert "あなたの役割: ファシリテーター" in prompt


def test_render_history_handles_priority_and_empty_case() -> None:
    empty = OpenRouterClient._render_history(history=[], priority_message=None)
    assert "まだ会話はありません" in empty

    history = [ChatMessage(role="agent", speaker_id="model-a", content="まず要件整理しよう")]
    priority = ChatMessage(role="user", speaker_id="user", content="コストも重視して")
    rendered = OpenRouterClient._render_history(history=history, priority_message=priority)
    assert "model-a: まず要件整理しよう" in rendered
    assert "user(priority): コストも重視して" in rendered


def test_extract_error_detail_prefers_nested_error_message() -> None:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(
        status_code=400,
        json={"error": {"code": "bad_request", "message": "Model is not available for this key."}},
        request=request,
    )
    detail = OpenRouterClient._extract_error_detail(response)
    assert detail == "bad_request: Model is not available for this key."


def test_should_retry_without_temperature_matches_temperature_error() -> None:
    should_retry = OpenRouterClient._should_retry_without_temperature(
        400,
        "Unsupported parameter: temperature",
    )
    assert should_retry is True


def test_render_history_truncates_very_long_history() -> None:
    long_text = "a" * 7000
    history = [ChatMessage(role="agent", speaker_id="model-a", content=long_text)]
    rendered = OpenRouterClient._render_history(history=history, priority_message=None)
    assert rendered.startswith("（履歴が長いため末尾のみ利用）")
    assert len(rendered) <= 6100
