from __future__ import annotations

from random import Random

from app.models import AgentSpec, RoleType

CHARACTER_LIBRARY: tuple[tuple[str, str, str], ...] = (
    (
        "定義に厳密な分析哲学者",
        "言葉の定義と推論の妥当性を最優先で点検する。",
        "曖昧な概念を見つけたら、必ず定義し直してから議論を進める。",
    ),
    (
        "価値判断を問う倫理学者",
        "何が善い選択かを当事者への影響から評価する。",
        "便益だけでなく、誰が損をするかを毎回明示して問い直す。",
    ),
    (
        "反例を探す懐疑主義者",
        "主張の抜け穴と前提の弱さを突く。",
        "最低1つの反例か思考実験を出して、議論の強度を上げる。",
    ),
    (
        "現実適合を測る実践主義者",
        "机上の正しさより、実装時の制約と検証可能性を重視する。",
        "小さな検証手順に落とし込み、実行可能性で優先順位を付ける。",
    ),
    (
        "構造を読む社会批評家",
        "個人の好みではなく、制度と構造の影響を分析する。",
        "利害関係者と権力勾配を整理し、見落としを指摘する。",
    ),
    (
        "長期視点の未来洞察者",
        "短期最適ではなく、長期の副作用と継続可能性を評価する。",
        "5年後に残るかを軸に、楽観シナリオと悲観シナリオを並べる。",
    ),
)

FACILITATOR_PROMPT = (
    "あなたは議論の司会です。論点を整理し、脱線したらお題に戻してください。"
    "各ターンで他者の要点を一言で要約し、次に掘るべき問いを1つ提示してください。"
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


def _normalize_subject(subject: str) -> str:
    normalized = " ".join(subject.split())
    if not normalized:
        return "与えられたお題"
    if len(normalized) <= 120:
        return normalized
    return f"{normalized[:117]}..."


def _build_character_profile(*, subject: str, blueprint: tuple[str, str, str]) -> str:
    title, lens, behavior = blueprint
    normalized_subject = _normalize_subject(subject)
    return (
        f"{title}。"
        f"お題「{normalized_subject}」を主にこの観点で扱う: {lens}"
        f"発言時の行動規範: {behavior}"
    )


def build_persona_prompt(*, role_type: RoleType, character_profile: str, subject: str) -> str:
    normalized_subject = _normalize_subject(subject)
    if role_type == "facilitator":
        return (
            f"{FACILITATOR_PROMPT}\n"
            f"お題: {normalized_subject}\n"
            "司会ルール:\n"
            "- 会話を勝手に終わらせない。終了判断はユーザに委ねる。\n"
            "- 発言は2〜4文。論点整理1文 + 深掘り質問1文を必ず含める。"
        )
    normalized = character_profile.strip() or "率直で建設的な議論好きの参加者。"
    return (
        "あなたは議論参加者です。キャラクター設定に沿って発言してください。\n"
        f"お題: {normalized_subject}\n"
        f"キャラクター設定: {normalized}\n"
        "参加ルール:\n"
        "- 会話を勝手に締めない。結論の可否はユーザが決める。\n"
        "- 毎ターン、他者の主張への賛否を明示し、理由を添える。\n"
        "- 哲学的論点（定義・価値・認識・倫理）を最低1つ含める。"
    )


def generate_personas(*, models: list[str], subject: str, rng: Random) -> list[AgentSpec]:
    personas: list[AgentSpec] = []
    display_names = build_display_names(models)
    shuffled_blueprints = list(CHARACTER_LIBRARY)
    rng.shuffle(shuffled_blueprints)
    for index, model in enumerate(models, start=1):
        role_type: RoleType = "facilitator" if index == 1 else "character"
        if role_type == "facilitator":
            character_profile = "議論の交通整理役。論点・争点・未解決点を可視化する。"
        else:
            blueprint = shuffled_blueprints[(index - 2) % len(shuffled_blueprints)]
            character_profile = _build_character_profile(subject=subject, blueprint=blueprint)
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
                    subject=subject,
                ),
            )
        )
    return personas
