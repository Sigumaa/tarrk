from __future__ import annotations

import httpx

from app.models import ChatMessage
from app.openrouter import OpenRouterClient


def test_build_system_prompt_includes_global_and_role_instruction() -> None:
    prompt = OpenRouterClient._build_system_prompt(
        agent_id="agent-2",
        role_name="懐疑派",
        topic="新機能の方向性",
        background="既存ユーザーの継続率が低い",
        context="次スプリントでMVPを決める",
        language="日本語",
        global_instruction="必ず日本語で建設的に議論し、結論候補を示すこと。",
        persona_prompt="あなたはagent-2。役割は懐疑派。",
    )

    assert "会話言語: 日本語" in prompt
    assert "テーマ: 新機能の方向性" in prompt
    assert "背景: 既存ユーザーの継続率が低い" in prompt
    assert "コンテキスト: 次スプリントでMVPを決める" in prompt
    assert "必ず日本語で建設的に議論" in prompt
    assert "役割: 懐疑派" in prompt


def test_render_history_handles_priority_and_empty_case() -> None:
    empty = OpenRouterClient._render_history(history=[], priority_message=None)
    assert "まだ会話はありません" in empty

    history = [ChatMessage(role="agent", speaker_id="agent-1", content="まず要件整理しよう")]
    priority = ChatMessage(role="user", speaker_id="user", content="コストも重視して")
    rendered = OpenRouterClient._render_history(history=history, priority_message=priority)

    assert "agent-1: まず要件整理しよう" in rendered
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
    history = [ChatMessage(role="agent", speaker_id="agent-1", content=long_text)]
    rendered = OpenRouterClient._render_history(history=history, priority_message=None)
    assert rendered.startswith("（履歴が長いため末尾のみ利用）")
    assert len(rendered) <= 6100
