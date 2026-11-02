"""卡池接口：检索 / 元信息 / 手动刷新。"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from server.cardpool import service as cards
from server.logging_conf import get_logger
from server.settings import get_settings

log = get_logger(__name__)
router = APIRouter(prefix="/api/cards", tags=["cards"])


@router.get("")
def list_cards(
    q: Optional[str] = Query(None, description="卡名/卡面文字模糊搜索"),
    card_class: Optional[str] = Query(None, description="职业英文枚举，如 MAGE"),
    mode: str = Query("standard", pattern="^(standard|wild|all)$"),
    costs: Optional[List[int]] = Query(None, description="精确费用列表，如 1,2,3"),
    cost_min: Optional[int] = Query(None, ge=0, le=30),
    cost_max: Optional[int] = Query(None, ge=0, le=30),
    rarities: Optional[List[str]] = Query(None, description="FREE/COMMON/RARE/EPIC/LEGENDARY"),
    sets: Optional[List[str]] = Query(None, description="系列标识列表"),
    types: Optional[List[str]] = Query(None, description="MINION/SPELL/WEAPON/HERO/LOCATION"),
    keyword: Optional[str] = Query(None, description="关键词（中文），如 战吼"),
    sort: str = Query("cost", pattern="^(cost|name|dust)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=200),
):
    cards.ensure_cardpool()
    return cards.search_cards(
        q=q, card_class=card_class, mode=mode, costs=costs, cost_min=cost_min,
        cost_max=cost_max, rarities=rarities, sets=sets, types=types, keyword=keyword,
        page=page, page_size=page_size, sort=sort,
    )


@router.get("/sets")
def card_sets(mode: str = Query("all", pattern="^(all|standard)$")):
    cards.ensure_cardpool()
    return {"items": cards.list_sets(mode), "version": get_settings().sets_version}


@router.get("/classes")
def card_classes():
    return {"items": cards.list_classes()}


@router.get("/stats")
def stats():
    st = get_settings()
    return {
        "total": cards.card_count(),
        "ingested_at": cards.ingested_at(),
        "sets_version": st.sets_version,
        "standard_sets": st.standard_sets,
        "mode_counts": {
            "standard": cards.search_cards(mode="standard", page_size=1)["total"],
            "wild": cards.search_cards(mode="wild", page_size=1)["total"],
            "all": cards.search_cards(mode="all", page_size=1)["total"],
        },
    }


@router.post("/refresh")
def refresh(force: bool = Body(False, embed=True)):
    try:
        stats = cards.ingest(force=force)
    except Exception as e:
        log.warning("refresh failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))
    return {"ok": True, "stats": stats}


@router.get("/{dbf_id}")
def card_detail(dbf_id: int):
    cards.ensure_cardpool()
    found = cards.get_cards_by_dbf([dbf_id])
    if dbf_id not in found:
        raise HTTPException(status_code=404, detail="卡牌不存在")
    return found[dbf_id]
