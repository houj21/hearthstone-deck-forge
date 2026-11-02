"""卡组合法性校验：数量上限、职业限制、模式轮换、死亡骑士符文、曲线与尘数。"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from server.cardpool import service as cards
from server.settings import ROOT

MAX_COPIES = {"LEGENDARY": 1}
DEFAULT_MAX_COPIES = 2
DECK_SIZE = 30


@lru_cache(maxsize=1)
def hero_map() -> Dict[str, Dict[str, Any]]:
    """职业 -> 默认英雄 dbfId（数据来自官方卡表，见 tools/extract_heroes.py）。"""
    p = ROOT / "config" / "heroes.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def hero_dbf_for(card_class: str) -> Optional[int]:
    h = hero_map().get(card_class.upper())
    return h.get("dbf_id") if h else None


def class_of_hero(dbf: int) -> Optional[str]:
    for cls, info in hero_map().items():
        if info.get("dbf_id") == dbf:
            return cls
    return None


def is_class_legal(card: Dict[str, Any], card_class: str) -> bool:
    """职业合法性：本职业、中立，或多职业卡包含该职业。

    注意：多职业卡在官方数据里 cardClass 常为 NEUTRAL 且带 classes 列表，
    此时必须以 classes 为准，否则会被错误地放进任何职业的卡组。
    """
    cc = (card.get("card_class") or "").upper()
    target = (card_class or "").upper()
    multi = [m.upper() for m in (card.get("multi_class") or "").split(",") if m]
    if multi:
        return target in multi
    return cc == target or cc == "NEUTRAL"


def _parse_runes(runes: Optional[str]) -> Dict[str, int]:
    """「鲜血鲜血」 -> {'blood':2}"""
    out = {"blood": 0, "frost": 0, "unholy": 0}
    if not runes:
        return out
    mapping = {"鲜血": "blood", "冰霜": "frost", "邪恶": "unholy"}
    for ch in ["鲜血", "冰霜", "邪恶"]:
        out[mapping[ch]] = runes.count(ch)
    return out


def rune_plan(card_list: Sequence[Dict[str, Any]]) -> Optional[Dict[str, int]]:
    """死亡骑士符文方案：找到能覆盖所有带符文卡的 3 符文组合，返回 None 表示不可行。"""
    need = {"blood": 0, "frost": 0, "unholy": 0}
    for c in card_list:
        if (c.get("card_class") or "") != "DEATHKNIGHT":
            continue
        r = _parse_runes(c.get("runes"))
        for k in need:
            need[k] = max(need[k], r[k])
    if sum(need.values()) == 0:
        return {"blood": 0, "frost": 0, "unholy": 0}
    if sum(need.values()) > 3:
        return None
    return need


def analyze(
    entries: Sequence[Tuple[int, int]],
    *,
    mode: str = "standard",
    card_class: Optional[str] = None,
    apply_missing: bool = False,
) -> Dict[str, Any]:
    """entries: [(dbfId, 数量)]，返回完整卡组分析结果。"""
    errors: List[str] = []
    warnings: List[str] = []
    missing: List[int] = []

    found = cards.get_cards_by_dbf([int(d) for d, _ in entries])

    items: List[Dict[str, Any]] = []
    tokens: List[Dict[str, Any]] = []
    for dbf, qty in entries:
        dbf = int(dbf)
        qty = int(qty)
        card = found.get(dbf)
        if card is None:
            tok = cards.get_tokens_by_dbf([dbf]).get(dbf)
            if tok:                       # 组卡型卡牌自带的衍生牌：展示但不计入 30 张
                tokens.append({**tok, "qty": qty})
                continue
            missing.append(dbf)
            continue
        items.append({**card, "qty": qty})

    # 组卡型卡牌的配件（衍生牌）在官方卡组码里占位，游戏内同样按 30 张显示
    total = sum(it["qty"] for it in items) + sum(t["qty"] for t in tokens)

    if missing:
        errors.append(f"{len(missing)} 张卡不在卡池内（可能是狂野/怀旧卡或卡牌已变动）")

    # 张数上限
    for it in items:
        limit = MAX_COPIES.get(it.get("rarity") or "", DEFAULT_MAX_COPIES)
        if it["qty"] > limit:
            errors.append(f"「{it['name']}」数量 {it['qty']} 超过上限 {limit}")

    # 模式轮换
    if mode == "standard":
        bad = [it["name"] for it in items if not it.get("is_standard")]
        if bad:
            errors.append(f"标准模式下不可使用：{('、'.join(bad[:5]))}{'…' if len(bad) > 5 else ''}")

    # 职业推断与校验
    class_cards = [it for it in items if (it.get("card_class") or "") not in ("NEUTRAL", "")]
    if class_cards:
        from collections import Counter

        counted = Counter(it["card_class"] for it in class_cards)
        detected = counted.most_common(1)[0][0]
    else:
        detected = None

    final_class = (card_class or detected or "").upper() or None
    if card_class and detected and card_class.upper() != detected:
        errors.append(f"卡组含非 {card_class} 职业的卡（检测到 {detected}）")

    if final_class:
        illegal = [it["name"] for it in items if not is_class_legal(it, final_class)]
        if illegal:
            errors.append(f"不属于该职业的卡：{'、'.join(illegal[:5])}")

    # 符文
    if final_class == "DEATHKNIGHT" and not missing:
        plan = rune_plan(items)
        if plan is None:
            errors.append("死亡骑士符文需求冲突：这些卡无法用最多 3 个符文同时满足")

    # 张数
    if total != DECK_SIZE:
        errors.append(f"卡组必须为 {DECK_SIZE} 张，当前 {total} 张") if total > DECK_SIZE else warnings.append(
            f"还差 {DECK_SIZE - total} 张才能凑齐卡组")

    # 统计
    curve = [0] * 8
    dust = 0
    for it in items:
        k = min(it.get("cost") or 0, 7)
        curve[k] += it["qty"]
        dust += (it.get("dust_cost") or 0) * it["qty"]

    return {
        "ok": not errors,
        "card_class": final_class,
        "hero_dbf": hero_dbf_for(final_class) if final_class else None,
        "total": total,
        "errors": errors,
        "warnings": warnings,
        "missing": missing,
        "curve": curve,
        "dust_total": dust,
        "tokens": tokens,
        "items": sorted(items, key=lambda x: ((x.get("cost") or 0), x["name"])),
    }


def entries_to_view(entries: Iterable[Tuple[int, int]], mode: str, card_class: Optional[str] = None):
    """把简洁条目转换为可持久化的 [{dbf_id, qty}]。"""
    return [{"dbf_id": int(d), "qty": int(q)} for d, q in entries]
