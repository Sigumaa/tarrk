from __future__ import annotations

from random import Random

from app.models import AgentSpec

TONES: tuple[str, ...] = (
    "playful and witty",
    "skeptical and analytical",
    "optimistic and energetic",
    "calm and philosophical",
    "dramatic and poetic",
    "contrarian but polite",
)

PACING: tuple[str, ...] = (
    "keep replies under 60 words",
    "ask one probing question occasionally",
    "use concrete examples",
    "challenge assumptions gently",
    "avoid repeating previous points",
)


def build_persona(agent_id: str, rng: Random) -> str:
    tone = rng.choice(TONES)
    pacing = rng.choice(PACING)
    return f"You are {agent_id}. Your speaking style is {tone}. Conversation rule: {pacing}."


def generate_personas(models: list[str], rng: Random) -> list[AgentSpec]:
    personas: list[AgentSpec] = []
    for index, model in enumerate(models, start=1):
        agent_id = f"agent-{index}"
        personas.append(
            AgentSpec(
                agent_id=agent_id,
                model=model,
                persona_prompt=build_persona(agent_id=agent_id, rng=rng),
            )
        )
    return personas
