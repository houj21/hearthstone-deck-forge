"""候选卡池：给模型的选卡范围。

直接把整个职业卡池（上千张）塞进提示词会又慢又贵，而且模型更容易跑偏。
这里按“环境真实在用”优先排序：
1. 先取当前环境快照里该职业卡组实际携带的卡（带出现套数，作为热度提示）；
2. 不够再用本职业+中立卡池补齐（按曲线分布，保证各费用段都有得选）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from server.cardpool import service as cards
from server.logging_conf import get_logger
from server.meta import service as meta
from server.settings import get_settings

log = get_logger(__name__)


def build_candidates(
    *,
    card_class: str,
    mode: str = "standard",
    limit: int | None = None,
) -> Dict[str, Any]:
    st = get_settings()
    limit = int(limit or st.ai.get("max_candidates", 120))
    cls = (card_class or "").upper()

    heat: Dict[int, int] = {}
    snapshot = meta.latest_snapshot(mode=mode)
    if snapshot:
        for e in meta.snapshot_entries(int(snapshot["id"])):
            if (e.get("card_class") or "").upper() != cls:
                continue
            for dbf, _qty in e.get("deck_cards") or []:
                try:
                    heat[int(dbf)] = heat.get(int(dbf), 0) + 1
                except (TypeError, ValueError):
                    continue

    picked: List[Dict[str, Any]] = []
    seen: set[int] = set()

    if heat:
        found = cards.get_cards_by_dbf(list(heat.keys()))
        for dbf in sorted(heat, key=lambda d: -heat[d]):
            c = found.get(dbf)
            if not c or dbf in seen:
                continue
            if not _eligible(c, mode):
                continue
            picked.append(c)
            seen.add(dbf)
            if len(picked) >= limit:
                break

    if len(picked) < limit:
        res = cards.search_cards(card_class=cls, mode=mode, page_size=max(60, limit * 2), sort="cost")
        for c in res.get("items", []):
            dbf = int(c.get("dbf_id") or 0)
            if dbf in seen or not _eligible(c, mode):
                continue
            picked.append(c)
            seen.add(dbf)
            if len(picked) >= limit:
                break

    return {
        "items": picked,
        "heat": heat,
        "source": f"环境在用 {min(len(heat), len(picked))} 张 + 卡池补齐至 {len(picked)} 张",
    }


def _eligible(c: Dict[str, Any], mode: str) -> bool:
    if mode == "standard" and not c.get("is_standard"):
        return False
    return (c.get("type") or "") != "HERO"


# ---------------------------------------------------------------- 展示用块
def deck_block(items: List[Dict[str, Any]]) -> str:
    """卡组 -> 提示词里的文本块。"""
    return "\n".join(f"{c.get('qty')}x {c.get('name')}（{c.get('cost')}费）" for c in items)


def stats_block(analysis: Dict[str, Any]) -> str:
    """注意：analyze() 的 curve 是按费用下标的列表 [0费张数, 1费张数, ...]，不是 dict。"""
    curve = analysis.get("curve") or []
    if isinstance(curve, dict):                       # 兼容旧的 dict 形态
        items = [(int(k), v) for k, v in curve.items()]
    else:
        items = list(enumerate(curve))
    curve_txt = " ".join(f"{cost}费{n}张" for cost, n in items if n)
    return (
        f"总张数 {analysis.get('total')}；曲线：{curve_txt or '（空）'}；"
        f"尘数约 {analysis.get('dust_total')}；问题：{('；'.join(analysis.get('errors') or [])) or '无'}"
    )


def meta_block(card_class: str, limit: int = 3) -> str:
    """当前环境里该职业的主流原型，作为点评参考。"""
    try:
        summary = meta.get_summary(mode="standard", card_class=card_class.upper(), limit=limit)
    except Exception:
        return ""
    if not summary.get("entries"):
        return ""
    return "\n".join(
        f"- {e['name']}：胜率 {e['win_rate']}%，样本 {e['sample_size']}，{e.get('style_cn')}节奏"
        for e in summary["entries"]
    )


def _json(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False)
