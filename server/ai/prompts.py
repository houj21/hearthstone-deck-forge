"""AI 提示词。

设计要点（都是被真实模型坑出来的）：
- 强约束“只输出 JSON，且只用候选池里的卡名”：模型最爱自造卡名或用英文/旧译名；
- 卡面摘要要压缩成一行：卡池上百张，全文太长会把上下文和时延都顶上去；
- 校验失败时把“具体错误”原样回喂，而不是笼统说“再试一次”，重试成功率显著提高。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from server.settings import get_settings

TYPE_CN = {"MINION": "随从", "SPELL": "法术", "WEAPON": "武器", "HERO": "英雄", "LOCATION": "地标"}
RARITY_CN = {
    "FREE": "基础", "COMMON": "普通", "RARE": "稀有", "EPIC": "史诗",
    "LEGENDARY": "传说",
}

DEFAULT_INTENTS = [
    {"id": "faster", "label": "更快（抢血/铺场）"},
    {"id": "greedier", "label": "更贪（后期/大牌）"},
    {"id": "anti_aggro", "label": "针对快攻（解场/嘲讽）"},
    {"id": "anti_control", "label": "针对控制（续航/斩杀）"},
    {"id": "cheaper", "label": "更便宜（少橙卡）"},
    {"id": "combo", "label": "强化斩杀"},
]

INTENT_HINT = {
    "faster": "降低曲线，优先低费、能直接打脸或铺场的卡，保证 1-3 费有牌可出。",
    "greedier": "提高上限，接受较高曲线，带足后期威胁与资源。",
    "anti_aggro": "带足低费解牌、嘲讽、AOE 与回复，能活到中期。",
    "anti_control": "避免被一波清场，保留持续压力与直伤斩杀。",
    "cheaper": "尽量用普通/稀有卡替代史诗与传说，尘数优先低。",
    "combo": "围绕一组能凑出高额斩杀或连锁效果的卡来构筑。",
}

SYSTEM_JSON = (
    "你是《炉石传说》的中文构筑教练，只做标准/狂野构筑，不要谈酒馆战棋或剧情。\n"
    "必须遵守（违反就是错误）：\n"
    "1. 只能用«候选卡池»里出现的卡名，并且要一字不差地照抄，禁止自造卡名、禁止英文卡名、禁止旧译名。\n"
    "2. 卡组必须正好 30 张：同名普通/稀有/史诗最多 2 张，传说最多 1 张。\n"
    "3. 只能用该职业的卡和中立卡。\n"
    "4. 只输出 JSON 本体：不要解释、不要用 ``` 代码块包裹、不要用省略号、不要输出除 JSON 以外的任何字符。\n"
)

SYSTEM_TEXT = (
    "你是《炉石传说》的中文构筑教练，回答用简体中文，简短、具体、只讲能落地的改动，"
    "不要复述卡面，不要吹捧，指出问题时直接给替换方案。"
)

BUILD_SCHEMA = '{"name":"卡组中文名","cards":[{"name":"卡名","qty":2}],"plan":"打法思路，2-3 句中文"}'
SWAP_SCHEMA = (
    '{"swaps":[{"out":"被换下的卡名","in":"换上的卡名","reason":"一句话理由"}],'
    '"note":"整体提醒，一句话"}'
)


def intents() -> List[Dict[str, str]]:
    cfg = get_settings().ai.get("intents")
    if isinstance(cfg, list) and cfg:
        return cfg
    return DEFAULT_INTENTS


def _one_line(card: Dict[str, Any], heat: Optional[int] = None) -> str:
    parts = [
        card.get("name") or "",
        f"{card.get('cost') or 0}费",
        TYPE_CN.get(card.get("type") or "", card.get("type") or ""),
        RARITY_CN.get(card.get("rarity") or "", card.get("rarity") or ""),
    ]
    if card.get("attack") is not None or card.get("health") is not None:
        parts.append(f"{card.get('attack') or 0}/{card.get('health') or 0}")
    if card.get("durability"):
        parts.append(f"耐久{card['durability']}")
    if heat:
        parts.append(f"环境热度{heat}套")
    keywords = (card.get("keywords") or "").replace(",", "/")
    if keywords:
        parts.append(keywords)
    text = (card.get("text") or "").replace("\n", " ").strip()
    if text:
        parts.append(text[:48])
    return "|".join(p for p in parts if p)


def candidate_block(cards: Sequence[Dict[str, Any]], heat: Optional[Dict[int, int]] = None) -> str:
    lines = [_one_line(c, (heat or {}).get(int(c.get("dbf_id") or 0))) for c in cards]
    return "\n".join(l for l in lines if l)


def build_messages(
    *,
    card_class_cn: str,
    mode_cn: str,
    intent_label: str,
    note: str,
    candidates_block: str,
    current_deck_block: str = "",
) -> List[Dict[str, str]]:
    intent_line = INTENT_HINT.get(intent_label, "")
    user = (
        f"职业：{card_class_cn}\n模式：{mode_cn}\n构筑意图：{intent_label}。{intent_line}\n"
        f"补充说明：{note or '（无）'}\n"
    )
    if current_deck_block:
        user += f"\n当前卡组（可在此基础上改，也可以推倒重来）：\n{current_deck_block}\n"
    user += (
        f"\n候选卡池（只能用这里的卡，卡名照抄）：\n{candidates_block}\n\n"
        f"请输出 JSON：{BUILD_SCHEMA}\n"
        "注意 cards 里 qty 之和必须等于 30。"
    )
    return [{"role": "system", "content": SYSTEM_JSON}, {"role": "user", "content": user}]


def swap_messages(
    *,
    card_class_cn: str,
    mode_cn: str,
    intent_label: str,
    note: str,
    deck_block: str,
    target: str,
    candidates_block: str,
) -> List[Dict[str, str]]:
    user = (
        f"职业：{card_class_cn}\n模式：{mode_cn}\n意图：{intent_label}。{INTENT_HINT.get(intent_label,'')}\n"
        f"补充说明：{note or '（无）'}\n\n"
        f"当前卡组（30 张）：\n{deck_block}\n\n"
        f"要替换的卡：{target}\n\n"
        f"候选卡池（换上的卡只能来自这里，卡名照抄）：\n{candidates_block}\n\n"
        f"请给出 2-3 个替换方案，输出 JSON：{SWAP_SCHEMA}\n"
        "out 必须等于「要替换的卡」的卡名；in 必须是候选池里的卡名；"
        "替换后仍要满足 30 张且传说不超过 1 张。"
    )
    return [{"role": "system", "content": SYSTEM_JSON}, {"role": "user", "content": user}]


def review_messages(
    *,
    card_class_cn: str,
    mode_cn: str,
    deck_block: str,
    stats_block: str,
    meta_block: str,
) -> List[Dict[str, str]]:
    user = (
        f"职业：{card_class_cn}（{mode_cn}）\n\n当前卡组：\n{deck_block}\n\n"
        f"本地统计：\n{stats_block}\n\n"
        f"环境参考：\n{meta_block or '（暂无环境快照）'}\n\n"
        "请用中文分三点回答：1) 这套卡组的问题；2) 最该换的 2 张卡与替换建议（卡名要存在于卡池）；"
        "3) 起手与对局节奏建议。控制在 220 字以内。"
    )
    return [{"role": "system", "content": SYSTEM_TEXT}, {"role": "user", "content": user}]


def repair_messages(messages: List[Dict[str, str]], errors: Sequence[str], schema: str) -> List[Dict[str, str]]:
    """把本地校验的具体错误回喂给模型，让它自己修。"""
    return messages + [
        {
            "role": "user",
            "content": (
                "你上一次的输出在本地校验中未通过，错误如下：\n"
                + "\n".join(f"- {e}" for e in errors)
                + f"\n请修正后重新输出同样的 JSON：{schema}\n只输出 JSON。"
            ),
        }
    ]
