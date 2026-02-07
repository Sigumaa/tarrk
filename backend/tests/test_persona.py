from __future__ import annotations

from random import Random

from app.persona import assign_roles, build_persona, generate_personas


def test_build_persona_returns_non_empty_text() -> None:
    role = assign_roles(agent_count=1, rng=Random(3))[0]
    text = build_persona(agent_id="agent-1", role=role, rng=Random(7))
    assert text
    assert "agent-1" in text
    assert role["name"] in text


def test_assign_roles_returns_requested_count() -> None:
    roles = assign_roles(agent_count=7, rng=Random(1))
    assert len(roles) == 7
    assert all("name" in role for role in roles)


def test_generate_personas_matches_models() -> None:
    models = ["openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet"]
    personas = generate_personas(models=models, rng=Random(10))
    assert len(personas) == len(models)
    assert [item.agent_id for item in personas] == ["agent-1", "agent-2"]
    assert [item.model for item in personas] == models
    assert all(item.role_name for item in personas)
    assert all(item.persona_prompt for item in personas)
