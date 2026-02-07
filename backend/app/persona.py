from __future__ import annotations

from random import Random

from app.models import AgentSpec

ROLE_LIBRARY: tuple[dict[str, str], ...] = (
    {
        "name": "ファシリテーター",
        "focus": "議論の流れを整理し、話題が散ったら主題に戻す",
        "style": "要点を短くまとめ、次の論点を提案する",
    },
    {
        "name": "実務家",
        "focus": "実現可能性、コスト、運用負荷を具体化する",
        "style": "手順・条件・トレードオフを明確に述べる",
    },
    {
        "name": "懐疑派",
        "focus": "見落としや反証可能性を指摘して議論を健全化する",
        "style": "断定を避け、根拠確認の問いを投げる",
    },
    {
        "name": "クリエイター",
        "focus": "新規性の高い提案を出し、体験価値を押し上げる",
        "style": "具体例と比喩を使って発想を広げる",
    },
    {
        "name": "ユーザー代弁者",
        "focus": "ユーザー感情、使いやすさ、継続利用の観点を守る",
        "style": "体験の分かりやすさを優先して話す",
    },
    {
        "name": "検証担当",
        "focus": "主張をテスト観点へ落とし込み、検証方法を示す",
        "style": "仮説・確認項目・判断条件をセットで述べる",
    },
)

TURN_RULES: tuple[str, ...] = (
    "1ターンは2〜4文で簡潔に話す",
    "他のagentの発言を1つ受けてから自分の主張を述べる",
    "最後に次の検討ポイントを1つ提示する",
    "同じ主張の繰り返しを避ける",
)


def assign_roles(agent_count: int, rng: Random) -> list[dict[str, str]]:
    roles = list(ROLE_LIBRARY)
    rng.shuffle(roles)
    selected: list[dict[str, str]] = []
    for index in range(agent_count):
        selected.append(roles[index % len(roles)])
    return selected


def build_persona(agent_id: str, role: dict[str, str], rng: Random) -> str:
    turn_rule = rng.choice(TURN_RULES)
    return (
        f"あなたは {agent_id}。\n"
        f"役割: {role['name']}\n"
        f"注力点: {role['focus']}\n"
        f"話し方: {role['style']}\n"
        f"会話ルール: {turn_rule}"
    )


def generate_personas(models: list[str], rng: Random) -> list[AgentSpec]:
    assigned_roles = assign_roles(agent_count=len(models), rng=rng)
    personas: list[AgentSpec] = []
    for index, model in enumerate(models, start=1):
        agent_id = f"agent-{index}"
        role = assigned_roles[index - 1]
        personas.append(
            AgentSpec(
                agent_id=agent_id,
                model=model,
                role_name=role["name"],
                persona_prompt=build_persona(agent_id=agent_id, role=role, rng=rng),
            )
        )
    return personas
