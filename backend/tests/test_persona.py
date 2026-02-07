from __future__ import annotations

from random import Random

from app.persona import build_persona, generate_personas


def test_build_persona_returns_non_empty_text() -> None:
    text = build_persona(agent_id="agent-1", rng=Random(7))
    assert text
    assert "agent-1" in text


def test_generate_personas_matches_models() -> None:
    models = ["openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet"]
    personas = generate_personas(models=models, rng=Random(10))
    assert len(personas) == len(models)
    assert [item.agent_id for item in personas] == ["agent-1", "agent-2"]
    assert [item.model for item in personas] == models
    assert all(item.persona_prompt for item in personas)
