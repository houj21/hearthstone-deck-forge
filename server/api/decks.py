"""卡组接口：卡组码解析/生成/校验，本地保存。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from server.cardpool import service as cards
from server.deckcode.codec import DeckCodeError, encode_deck_string, parse_deck_string
from server.deckcode.validate import analyze, class_of_hero, hero_dbf_for, hero_map
from server.db.base import get_conn
from server.logging_conf import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/decks", tags=["decks"])


class ParseIn(BaseModel):
    code: str = Field(..., min_length=8, description="官方卡组码 AAECA...")
    mode: str = "standard"


class CardEntry(BaseModel):
    dbf_id: int
    qty: int = Field(1, ge=1, le=2)


class EncodeIn(BaseModel):
    card_class: Optional[str] = None
    mode: str = "standard"
    fmt: str = "standard"
    cards: List[CardEntry]


class SaveIn(BaseModel):
    name: str = "我的卡组"
    card_class: Optional[str] = None
    mode: str = "standard"
    cards: List[CardEntry]
    deck_code: Optional[str] = None


@router.post("/parse")
def parse_deck(payload: ParseIn) -> Dict[str, Any]:
    cards.ensure_cardpool()
    try:
        parsed = parse_deck_string(payload.code)
    except DeckCodeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    hero_dbf = int(parsed["hero_dbf"])  # type: ignore[index]
    hero_class = class_of_hero(hero_dbf)
    entries = parsed["cards"]  # type: ignore[index]
    result = analyze(entries, mode=payload.mode, card_class=hero_class)

    result["deck_code"] = payload.code.strip()
    result["source_format"] = parsed["format"]  # type: ignore[index]
    result["hero_dbf_from_code"] = hero_dbf
    return result


@router.post("/encode")
def encode_deck(payload: EncodeIn) -> Dict[str, Any]:
    cards.ensure_cardpool()
    entries = [(c.dbf_id, c.qty) for c in payload.cards]
    info = analyze(entries, mode=payload.mode, card_class=payload.card_class)

    hero_dbf = info["hero_dbf"]
    if not hero_dbf:
        raise HTTPException(status_code=400, detail="无法确定卡组职业，请指定 card_class")

    # 即使有错误也允许导出（方便玩家边改边导出），但把错误一并返回
    code = encode_deck_string(hero_dbf, entries, payload.fmt)
    return {"deck_code": code, "ok": info["ok"], "errors": info["errors"], "warnings": info["warnings"]}


@router.get("/heroes")
def heroes():
    return {"items": [{"class": k, **v} for k, v in hero_map().items()]}


@router.post("/validate")
def validate(payload: EncodeIn):
    cards.ensure_cardpool()
    return analyze([(c.dbf_id, c.qty) for c in payload.cards],
                   mode=payload.mode, card_class=payload.card_class)


# ---------------------------------------------------------------- 本地保存
@router.post("/save")
def save_deck(payload: SaveIn):
    from datetime import datetime

    now = datetime.now().isoformat(timespec="seconds")
    cards_json = ",".join(f"{c.dbf_id}:{c.qty}" for c in payload.cards)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO saved_deck (name, card_class, mode, deck_code, cards, source, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (payload.name, payload.card_class, payload.mode, payload.deck_code, cards_json, "local", now, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM saved_deck WHERE id=?", (cur.lastrowid,)).fetchone()
    return {"id": row["id"], "name": row["name"], "created_at": row["created_at"]}


@router.get("/saved")
def list_saved():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM saved_deck ORDER BY updated_at DESC LIMIT 100").fetchall()
    return {"items": [_saved_view(r) for r in rows]}


@router.get("/saved/{deck_id}")
def get_saved(deck_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM saved_deck WHERE id=?", (deck_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="卡组不存在")
    return _saved_view(row)


def _saved_view(r) -> Dict[str, Any]:
    entries = []
    for part in (r["cards"] or "").split(","):
        if not part or ":" not in part:
            continue
        dbf, qty = part.split(":")
        try:
            entries.append({"dbf_id": int(dbf), "qty": int(qty)})
        except ValueError:
            continue
    return {
        "id": r["id"],
        "name": r["name"],
        "card_class": r["card_class"],
        "mode": r["mode"],
        "deck_code": r["deck_code"],
        "cards": entries,
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }
