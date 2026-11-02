"""规则兜底：模型不可用或校验反复不过时，用确定性规则给出仍然可用的结果。

兜底不是“随便给一套”：曲线按常见构筑配比分配，卡全部来自候选池（环境实际在用优先），
因此断网/网关故障时 AI 教练依然可用，只是没有自然语言解释。
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

MAX_COPIES = {"LEGENDARY": 1}
DEFAULT_COPIES = 2

# 30 张的曲线配比（费用段 -> 张数），按主流构筑习惯给的经验值
CURVE_TARGET: List[Tuple[Tuple[int, int], int]] = [
    ((0, 1), 4),
    ((2, 2), 6),
    ((3, 3), 6),
    ((4, 4), 5),
    ((5, 5), 4),
    ((6, 6), 3),
    ((7, 99), 2),
]

INTENT_COST_SHIFT = {"faster": -1, "greedier": 1, "anti_aggro": 0, "anti_control": 0, "combo": 0, "cheaper": 0}


def _copies(card: Dict[str, Any]) -> int:
    return MAX_COPIES.get(card.get("rarity") or "", DEFAULT_COPIES)


def fallback_build(
    candidates: Sequence[Dict[str, Any]],
    *,
    heat: Dict[int, int] | None = None,
    intent: str = "",
) -> List[Tuple[int, int]]:
    """按曲线配比从候选池里凑 30 张。返回 [(dbfId, qty)]。"""
    heat = heat or {}
    pool = [c for c in candidates if int(c.get("cost") or 0) >= 0]
    pool.sort(key=lambda c: (-heat.get(int(c.get("dbf_id") or 0), 0), int(c.get("cost") or 0)))

    used: Dict[int, int] = {}
    entries: List[Tuple[int, int]] = []
    total = 0
    for (lo, hi), want in CURVE_TARGET:
        if total >= 30:
            break
        bucket = [c for c in pool if lo <= int(c.get("cost") or 0) <= hi]
        for c in bucket:
            if total >= 30 or want <= 0:
                break
            dbf = int(c.get("dbf_id") or 0)
            if not dbf or dbf in used:
                continue
            qty = min(_copies(c), want)
            used[dbf] = qty
            entries.append((dbf, qty))
            total += qty
            want -= qty
    # 不够 30 张时用剩余高分卡补齐
    if total < 30:
        for c in pool:
            if total >= 30:
                break
            dbf = int(c.get("dbf_id") or 0)
            if not dbf or dbf in used:
                continue
            qty = min(_copies(c), 30 - total)
            used[dbf] = qty
            entries.append((dbf, qty))
            total += qty
    return entries


def fallback_swaps(
    deck_items: Sequence[Dict[str, Any]],
    candidates: Sequence[Dict[str, Any]],
    *,
    target: Dict[str, Any],
    intent: str = "",
    heat: Dict[int, int] | None = None,
    top: int = 3,
) -> List[Dict[str, Any]]:
    """给“换掉某张卡”的候选：优先同费用段、环境热度高、符合意图。"""
    heat = heat or {}
    in_deck = {int(c.get("dbf_id") or 0): c for c in deck_items}
    target_cost = int(target.get("cost") or 0)
    shift = INTENT_COST_SHIFT.get(intent or "", 0)
    want_lo, want_hi = target_cost - 1 + shift, target_cost + 1 + shift

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for c in candidates:
        dbf = int(c.get("dbf_id") or 0)
        if not dbf or dbf in in_deck:
            continue
        cost = int(c.get("cost") or 0)
        if (c.get("card_class") or "") not in (target.get("card_class"), "NEUTRAL") and not c.get("multi_class"):
            continue
        score = heat.get(dbf, 0) * 2.0
        if want_lo <= cost <= want_hi:
            score += 3.0
        score -= abs(cost - (target_cost + shift)) * 0.5
        if intent == "cheaper":
            score += (2 if (c.get("rarity") in ("COMMON", "RARE", "FREE")) else -2)
        if intent == "faster":
            score += max(0, 3 - cost) * 0.6
        if intent == "greedier":
            score += max(0, cost - 3) * 0.4
        scored.append((score, c))

    scored.sort(key=lambda x: -x[0])
    out = []
    for score, c in scored[:top]:
        out.append({
            "out": target.get("name") or "",
            "in": c.get("name") or "",
            "dbf_id": c.get("dbf_id"),
            "reason": (
                f"{c.get('cost')}费，环境出现 {heat.get(int(c.get('dbf_id') or 0), 0)} 套，"
                f"替换 {target_cost}费 的「{target.get('name')}」后曲线更均衡"
            ),
            "score": round(score, 2),
        })
    return out


def _curve_items(curve: Any) -> List[Tuple[int, int]]:
    """统一成 [(费用, 张数)]：analyze() 给的是按下标的列表。"""
    if isinstance(curve, dict):
        return [(int(k), int(v or 0)) for k, v in curve.items()]
    return [(i, int(n or 0)) for i, n in enumerate(curve or [])]


def curve_issues(analysis: Dict[str, Any]) -> List[str]:
    """基于统计结果给出中文提醒（不依赖模型）。"""
    out: List[str] = []
    total = int(analysis.get("total") or 0)
    if not total:
        return ["卡组是空的，先导入或构筑一套卡组"]
    low = sum(n for c, n in _curve_items(analysis.get("curve")) if c <= 2)
    high = sum(n for c, n in _curve_items(analysis.get("curve")) if c >= 7)
    if total >= 20 and low < 6:
        out.append(f"低费（1-2 费）只有 {low} 张，容易被快攻抢死，建议补到 8-10 张")
    if high > 8:
        out.append(f"7 费以上有 {high} 张，卡手风险高，建议压到 5 张以内")
    if total != 30:
        out.append(f"当前 {total} 张，卡组需要正好 30 张")
    return out
