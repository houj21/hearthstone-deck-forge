"""推荐 API：按分段/职业/时间窗给出榜单。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from server.logging_conf import get_logger
from server.recommend import engine

log = get_logger(__name__)
router = APIRouter(prefix="/api/recommend", tags=["recommend"])


@router.get("")
def recommend(
    mode: str = Query("standard", pattern="^(standard|wild)$"),
    window: str = Query("current", pattern="^(current|30d)$"),
    bucket: Optional[str] = None,
    card_class: Optional[str] = None,
    limit: int = Query(0, ge=0, le=50),
) -> Dict[str, Any]:
    """推荐榜：贝叶斯收缩胜率 + 趋势 + 职业多样性。"""
    return engine.recommend(
        mode=mode,
        window=window,
        bucket=bucket,
        card_class=card_class,
        limit=limit or None,
    )


@router.get("/buckets")
def buckets() -> Dict[str, Any]:
    """可选分段档位（来自 config/app.yaml）。"""
    from server.settings import get_settings

    st = get_settings()
    return {
        "items": [{"id": b.id, "label": b.label, "order": b.order} for b in st.buckets],
        "min_sample_size": st.recommend.get("min_sample_size", 200),
    }
