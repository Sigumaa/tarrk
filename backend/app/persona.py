from __future__ import annotations

from random import Random

from app.models import AgentSpec, ConversationMode, RoleType

MODE_FACILITATOR_GUIDE: dict[ConversationMode, str] = {
    "philosophy_debate": ("概念定義のズレを揃え、認識論・倫理・価値判断の順で論点を整理する。"),
    "devils_advocate": ("いったん有力案を立てた後、最強の反対論をぶつけて耐久性を検証する。"),
    "consensus_lab": ("対立を残したままでも進める合意案を作り、実行条件と撤退条件を明確にする。"),
}

MODE_CHARACTER_LIBRARY: dict[ConversationMode, tuple[tuple[str, str, str], ...]] = {
    "philosophy_debate": (
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
            "長期視点の未来洞察者",
            "短期最適ではなく、長期の副作用と継続可能性を評価する。",
            "5年後に残るかを軸に、楽観シナリオと悲観シナリオを並べる。",
        ),
    ),
    "devils_advocate": (
        (
            "鋭利な反対尋問者",
            "案の前提を疑い、見落としたリスクを炙り出す。",
            "賛成案にも必ず強い反対論を1つ作って突きつける。",
        ),
        (
            "失敗シナリオ設計者",
            "最悪ケースの連鎖を具体的に描く。",
            "破綻点を時系列で示し、どこで止血できるかを問う。",
        ),
        (
            "制度批評の観察者",
            "個人の善意より制度設計の歪みに注目する。",
            "利害関係者ごとに、想定外の行動誘因を列挙する。",
        ),
        (
            "反証を積む実験主義者",
            "主張が間違っている条件を先に探す。",
            "反証可能なチェック項目を短く提案して検証に落とす。",
        ),
    ),
    "consensus_lab": (
        (
            "調停型ファシリテーター補佐",
            "対立する主張の共通項を探す。",
            "一致点と保留点を分け、次の判断材料を明示する。",
        ),
        (
            "実装優先の現実主義者",
            "理想論より実装可能性を軸に優先順位を付ける。",
            "最小実行単位に分解して、最初の一歩を具体化する。",
        ),
        (
            "利用者代弁のインタビュアー",
            "使う側の心理的負担と学習コストを見る。",
            "ユーザが迷う瞬間を想定し、改善案に変換する。",
        ),
        (
            "トレードオフ整理者",
            "短期利益と長期負債の交換条件を明確化する。",
            "捨てる要素を先に宣言し、意思決定を進める。",
        ),
    ),
}


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


def _normalize_global_instruction(global_instruction: str) -> str:
    normalized = "\n".join(line.strip() for line in global_instruction.splitlines() if line.strip())
    if len(normalized) <= 1200:
        return normalized
    return f"{normalized[:1197]}..."


def _build_character_profile(*, subject: str, blueprint: tuple[str, str, str]) -> str:
    title, lens, behavior = blueprint
    normalized_subject = _normalize_subject(subject)
    return (
        f"{title}。"
        f"お題「{normalized_subject}」を主にこの観点で扱う: {lens}"
        f"発言時の行動規範: {behavior}"
    )


def build_persona_prompt(
    *,
    role_type: RoleType,
    character_profile: str,
    subject: str,
    mode: ConversationMode,
    global_instruction: str,
) -> str:
    normalized_subject = _normalize_subject(subject)
    normalized_global = _normalize_global_instruction(global_instruction)
    facilitator_guide = MODE_FACILITATOR_GUIDE[mode]

    if role_type == "facilitator":
        prompt = (
            "あなたは議論の司会です。論点を整理し、脱線したらお題に戻してください。"
            f"\n議論モード: {mode}"
            f"\nモードの狙い: {facilitator_guide}"
            f"\nお題: {normalized_subject}"
            "\n司会ルール:"
            "\n- 会話を勝手に終わらせない。終了判断はユーザに委ねる。"
            "\n- 発言は2〜4文。論点整理1文 + 深掘り質問1文を必ず含める。"
            "\n- 直前の発言への応答を明示する。"
        )
        if normalized_global:
            prompt += f"\nユーザ追加指示:\n{normalized_global}"
        return prompt

    normalized_profile = character_profile.strip() or "率直で建設的な議論好きの参加者。"
    prompt = (
        "あなたは議論参加者です。キャラクター設定に沿って発言してください。"
        f"\n議論モード: {mode}"
        f"\nお題: {normalized_subject}"
        f"\nキャラクター設定: {normalized_profile}"
        "\n参加ルール:"
        "\n- 会話を勝手に締めない。結論の可否はユーザが決める。"
        "\n- 毎ターン、他者の主張への賛否を明示し、理由を添える。"
        "\n- 哲学的論点（定義・価値・認識・倫理）を最低1つ含める。"
    )
    if normalized_global:
        prompt += f"\nユーザ追加指示:\n{normalized_global}"
    return prompt


def generate_personas(
    *,
    models: list[str],
    subject: str,
    mode: ConversationMode,
    global_instruction: str,
    rng: Random,
) -> list[AgentSpec]:
    personas: list[AgentSpec] = []
    display_names = build_display_names(models)
    shuffled_blueprints = list(MODE_CHARACTER_LIBRARY[mode])
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
                    mode=mode,
                    global_instruction=global_instruction,
                ),
            )
        )
    return personas
