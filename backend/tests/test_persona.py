from __future__ import annotations

from random import Random

from app.persona import build_display_names, build_persona_prompt, generate_personas


def test_build_display_names_handles_duplicates() -> None:
    names = build_display_names(["a/model", "b/model", "a/model"])
    assert names == ["a/model", "b/model", "a/model (2)"]


def test_build_persona_prompt_for_roles() -> None:
    facilitator = build_persona_prompt(role_type="facilitator", character_profile="")
    character = build_persona_prompt(
        role_type="character",
        character_profile="勢いのあるクリエイター",
    )
    assert "司会" in facilitator
    assert "キャラクター設定" in character


def test_generate_personas_assigns_first_as_facilitator() -> None:
    models = ["m1", "m2", "m3"]
    personas = generate_personas(models=models, rng=Random(10))
    assert len(personas) == 3
    assert personas[0].role_type == "facilitator"
    assert all(persona.display_name for persona in personas)
    assert all(persona.persona_prompt for persona in personas)
