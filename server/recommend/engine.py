"""推荐排序引擎。

排序不是简单按胜率排：样本量小的卡组胜率噪声大，直接排会把偶然的高胜率顶上来。
这里用贝叶斯收缩把胜率往环境均值拉（样本越大越接近真实胜率），再叠加趋势与强势度，
最后做职业多样性贪心（同一职业最多 N 套），避免榜单被单一职业刷屏。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from server.logging_conf import get_logger
from server.meta import service as meta
from server.settings import get_settings

log = get_logger(__name__)


def bucket_labels() -> Dict[str, str]:
    return {b.id: b.label for b in get_settings().buckets}


def _shrunk_score(entry: Dict[str, Any], prior: float, k: float) -> float:
    """贝叶斯收缩后的胜率：(wr*games + prior*k) / (games + k)"""
    games = max(0.0, float(entry.get("sample_size") or 0))
    wr = float(entry.get("win_rate") or 0)
    return (wr * games + prior * k) / (games + k)


def _reason(entry: Dict[str, Any], labels: Dict[str, str], window_label: str) -> str:
    trend = float(entry.get("trend") or 0)
    trend_txt = ""
    if trend >= 0.3:
        trend_txt = f"，较上一轮 ↑{trend:.1f} 个百分点"
    elif trend <= -0.3:
        trend_txt = f"，较上一轮 ↓{abs(trend):.1f} 个百分点"
    buckets = [labels.get(b, b) for b in (entry.get("buckets") or [])]
    bucket_txt = f"，适配 {'/'.join(buckets[:2])}" if buckets else ""
    return (
        f"胜率 {float(entry.get('win_rate') or 0):.1f}%（{int(entry.get('sample_size') or 0):,} 场）"
        f"，{entry.get('style_cn') or ''}节奏{bucket_txt}{trend_txt}"
        f"。数据来自 HSReplay 青铜~黄金 · {window_label}"
    )


def recommend(
    *,
    mode: str = "standard",
    window: str = "current",
    bucket: Optional[str] = None,
    card_class: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    st = get_settings()
    summary = meta.get_summary(mode=mode, window=window, limit=200)
    if not summary.get("ok"):
        return {"ok": False, "message": summary.get("message", "暂无环境快照"), "items": []}

    entries: List[Dict[str, Any]] = summary["entries"]
    if card_class:
        entries = [e for e in entries if e.get("card_class") == card_class.upper()]
    if bucket:
        entries = [e for e in entries if bucket in (e.get("buckets") or [])]
    if not entries:
        return {"ok": True, "items": [], "message": "该条件下暂无推荐（可切换时间窗或分段）"}

    cfg = st.recommend
    k = float(cfg.get("shrink_k", 500))
    max_per_class = int(cfg.get("max_per_class", 2))
    limit = int(limit or cfg.get("top_n", 8))
    strong = float(cfg.get("strong_win_rate", 55.0))
    trend_bonus = float(cfg.get("trend_bonus", 0.6))
    labels = bucket_labels()

    total_games = sum(float(e.get("sample_size") or 0) for e in entries) or 1.0
    prior = sum(float(e.get("win_rate") or 0) * float(e.get("sample_size") or 0)
                for e in entries) / total_games

    scored: List[Dict[str, Any]] = []
    for e in entries:
        score = _shrunk_score(e, prior, k)
        trend = float(e.get("trend") or 0)
        if trend >= 0.3:
            score += trend_bonus
        elif trend <= -0.3:
            score -= trend_bonus
        if float(e.get("win_rate") or 0) >= strong:
            score += 0.3
        scored.append({**e, "score": round(score, 2)})

    scored.sort(key=lambda x: (-x["score"], -float(x.get("sample_size") or 0)))

    picked: List[Dict[str, Any]] = []
    per_class: Dict[str, int] = {}
    for e in scored:
        cls = e.get("card_class") or "?"
        if per_class.get(cls, 0) >= max_per_class:
            continue
        if not e.get("deck_code"):          # 没有可导入卡组码的不上榜单
            continue
        per_class[cls] = per_class.get(cls, 0) + 1
        e["reason"] = _reason(e, labels, summary.get("window_label", "当前版本"))
        picked.append(e)
        if len(picked) >= limit:
            break

    return {
        "ok": True,
        "mode": mode,
        "window": window,
        "window_label": summary.get("window_label", "当前版本"),
        "bucket": bucket or "",
        "bucket_label": labels.get(bucket or "", "全部分段"),
        "updated_at": summary.get("updated_at"),
        "prior_win_rate": round(prior, 2),
        "items": picked,
    }
