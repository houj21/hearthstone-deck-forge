"""环境数据 API：状态、快照列表、强制刷新、单条目详情。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from server.logging_conf import get_logger
from server.meta import service as meta

log = get_logger(__name__)
router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("/status")
def status() -> Dict[str, Any]:
    """源健康状态 + 当前快照信息 + 可用时间窗。"""
    return meta.status()


@router.get("/summary")
def summary(
    mode: str = Query("standard", pattern="^(standard|wild)$"),
    window: str = Query("current", pattern="^(current|30d)$"),
    card_class: Optional[str] = None,
    limit: int = Query(60, ge=1, le=200),
) -> Dict[str, Any]:
    """当前环境快照（卡组原型 + 胜率 + 样本 + 卡组码）。"""
    return meta.get_summary(mode=mode, window=window, card_class=card_class, limit=limit)


@router.post("/refresh")
def refresh(
    mode: str = Query("standard", pattern="^(standard|wild)$"),
    window: str = Query("current", pattern="^(current|30d)$"),
) -> Dict[str, Any]:
    """手动触发一次抓取（阻塞，前端需 loading）。"""
    return meta.refresh(mode=mode, window=window)


@router.get("/entry/{entry_id}")
def entry(entry_id: int) -> Dict[str, Any]:
    """单条环境条目详情（供 AI 复盘取卡表）。"""
    from server.db.base import get_conn

    with get_conn() as conn:
        row = conn.execute("SELECT * FROM meta_entry WHERE id=?", (entry_id,)).fetchone()
    if not row:
        return {"ok": False, "message": "条目不存在"}
    return {"ok": True, "entry": meta._row_to_entry(row)}
