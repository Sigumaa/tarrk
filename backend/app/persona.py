from __future__ import annotations

from random import Random

from app.models import AgentSpec, RoleType

CHARACTER_LIBRARY: tuple[str, ...] = (
    "熱量の高い起業家。即実行を重視し、勢いのある言葉で提案する。",
    "現実的なプロダクトマネージャー。優先順位と実現性で整理して話す。",
    "皮肉屋だが頭の切れる批評家。弱点を突きつつ代替案も出す。",
    "ユーザー目線のインタビュアー。感情と使い心地の観点を必ず入れる。",
    "コストに厳しい運用担当。維持費と障害リスクを細かく見る。",
    "発想が大胆なクリエイター。意外性のある案を具体例つきで出す。",
)

FACILITATOR_PROMPT = (
    "あなたは議論の司会です。論点を整理し、脱線したらお題に戻してください。"
    "各ターンで他者の要点を一言で要約し、次に考える観点を示してください。"
)


def build_display_names(models: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    names: list[str] = []
    for model in models:
        current = counts.get(model, 0) + 1
        counts[model] = current
        if current == 1:
            names.append(model)
        else:
            names.append(f"{model} ({current})")
    return names


def build_persona_prompt(*, role_type: RoleType, character_profile: str) -> str:
    if role_type == "facilitator":
        return FACILITATOR_PROMPT
    normalized = character_profile.strip() or "率直で建設的な議論好きの参加者。"
    return (
        "あなたは議論参加者です。キャラクター設定に沿って発言してください。"
        f"キャラクター設定: {normalized}"
    )


def generate_personas(models: list[str], rng: Random) -> list[AgentSpec]:
    personas: list[AgentSpec] = []
    display_names = build_display_names(models)
    for index, model in enumerate(models, start=1):
        role_type: RoleType = "facilitator" if index == 1 else "character"
        character_profile = "" if role_type == "facilitator" else rng.choice(CHARACTER_LIBRARY)
        personas.append(
            AgentSpec(
                agent_id=f"agent-{index}",
                model=model,
                display_name=display_names[index - 1],
                role_type=role_type,
                character_profile=character_profile,
                persona_prompt=build_persona_prompt(
                    role_type=role_type,
                    character_profile=character_profile,
                ),
            )
        )
    return personas
