"""卡池服务：入库、查询、系列与职业清单。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from server.cardpool.fetcher import CardFetchError, ensure_card_cache, ensure_full_card_cache
from server.cardpool.normalizer import CLASS_CN, is_playable, normalize_card
from server.db.base import get_conn
from server.logging_conf import get_logger
from server.settings import get_settings

log = get_logger(__name__)


# ---------------------------------------------------------------- 入库
def ingest(force: bool = False) -> Dict[str, int]:
    st = get_settings()
    try:
        raw_list = ensure_card_cache(force=force)
    except CardFetchError as e:
        log.error("ingest failed: %s", e)
        raise

    excluded = st.excluded_sets
    standard = st.standard_sets

    cards: List[Dict[str, Any]] = []
    for raw in raw_list:
        if not is_playable(raw, excluded):
            continue
        try:
            cards.append(normalize_card(raw, standard))
        except Exception as e:  # 单条脏数据不影响整体
            log.debug("skip card %s: %s", raw.get("id"), e)

    if not cards:
        raise RuntimeError("卡表清洗后为空，请检查 config/sets.yaml 的 excluded 列表")

    cards = dedupe_by_name(cards)

    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute("DELETE FROM cards")
        conn.executemany(
            """
            INSERT INTO cards (dbf_id, card_id, name, cost, attack, health, durability, armor,
                               type, race, races, rarity, card_class, multi_class, card_set,
                               text, keywords, mechanics, runes, spell_school, collectible,
                               is_standard, is_wild, image_url, updated_at)
            VALUES (:dbf_id, :card_id, :name, :cost, :attack, :health, :durability, :armor,
                    :type, :race, :races, :rarity, :card_class, :multi_class, :card_set,
                    :text, :keywords, :mechanics, :runes, :spell_school, :collectible,
                    :is_standard, :is_wild, :image_url, :updated_at)
            """,
            [
                {**c, "text": c.get("text_plain") or "", "updated_at": now}
                for c in cards
            ],
        )

        _ingest_tokens(conn, excluded, now)

        conn.execute("DELETE FROM card_sets")
        conn.executemany(
            "INSERT INTO card_sets (card_set, name_cn, card_count, is_standard, updated_at) VALUES (?,?,?,?,?)",
            _set_rows(cards, standard, now),
        )

        conn.execute(
            "INSERT OR REPLACE INTO meta_info (key, value, updated_at) VALUES (?,?,?)",
            ("cardpool_ingested_at", now, now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta_info (key, value, updated_at) VALUES (?,?,?)",
            ("sets_version", st.sets_version, now),
        )
        conn.commit()

    stats = {
        "total": len(cards),
        "standard": sum(1 for c in cards if c["is_standard"]),
        "wild": sum(1 for c in cards if not c["is_standard"]),
        "sets": len({c["card_set"] for c in cards}),
    }
    log.info("cardpool ingested: %s", stats)
    return stats


def _ingest_tokens(conn: sqlite3.Connection, excluded: Sequence[str], now: str) -> None:
    """把不可收集的衍生卡（token）落库。

    真实卡组码里会夹带由组卡型卡牌带来的衍生牌（例如「时空硬币」TIME_020t1），
    它们不在 collectible 卡表里；少了这层，解析真实卡组就会误报"卡牌不存在"。
    失败不阻断主流程，只是解析时退化到旧行为。
    """
    try:
        raw_list = ensure_full_card_cache()
    except Exception as e:
        log.warning("token pool skipped: %s", e)
        return

    seen = {int(r["dbf_id"]) for r in conn.execute("SELECT dbf_id FROM cards").fetchall()}
    rows = []
    for raw in raw_list:
        try:
            dbf = int(raw["dbfId"])
        except (KeyError, ValueError, TypeError):
            continue
        if dbf in seen or raw.get("collectible") or not raw.get("name"):
            continue
        if raw.get("set") in excluded:
            continue
        rows.append((
            dbf, raw.get("id"), raw.get("name"), raw.get("cost"), raw.get("type"),
            raw.get("cardClass"), raw.get("set"), _strip_html(raw.get("text")), now,
        ))
    try:
        conn.execute("DELETE FROM card_tokens")
        conn.executemany(
            "INSERT OR REPLACE INTO card_tokens"
            " (dbf_id, card_id, name, cost, type, card_class, card_set, text, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            rows,
        )
        log.info("tokens ingested: %s", len(rows))
    except Exception as e:  # 表不存在（旧库）时忽略
        log.warning("token ingest failed: %s", e)


def _strip_html(s: Optional[str]) -> str:
    import re
    return re.sub(r"<[^>]+>", "", str(s or "")).replace("[x]", "").strip()


def dedupe_by_name(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同名卡去重。

    官方数据里同一张卡常同时存在多个版本（CORE / CORE_HIDDEN / LEGACY / VANILLA），
    游戏内只能带其中一份。规则：优先保留标准可用的版本，其次 CORE 系列，最后取最小 dbfId。
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for c in cards:
        groups.setdefault(c["name"], []).append(c)

    out: List[Dict[str, Any]] = []
    for name, items in groups.items():
        if len(items) == 1:
            out.append(items[0])
            continue
        items.sort(key=lambda x: (
            not x["is_standard"],                    # 标准优先
            0 if x["card_set"].startswith("CORE") else 1,
            x["dbf_id"],
        ))
        out.append(items[0])
    return out


def _set_rows(cards: List[Dict[str, Any]], standard: Sequence[str], now: str):
    names = get_settings().set_names
    counter: Dict[str, int] = {}
    for c in cards:
        counter[c["card_set"]] = counter.get(c["card_set"], 0) + 1
    std = set(standard)
    return [
        (k, names.get(k, k), v, 1 if k in std else 0, now)
        for k, v in sorted(counter.items(), key=lambda x: -x[1])
    ]


def ingested_at() -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM meta_info WHERE key='cardpool_ingested_at'").fetchone()
    return row["value"] if row else None


def card_count() -> int:
    with get_conn() as conn:
        return int(conn.execute("SELECT COUNT(*) c FROM cards").fetchone()["c"])


def ensure_cardpool() -> None:
    """空表则自动入库（首次启动友好）。"""
    if card_count() == 0:
        ingest()


# ---------------------------------------------------------------- 查询
def _class_filter(card_class: Optional[str]) -> Tuple[str, List[Any]]:
    """职业过滤：本职业 + 中立（默认），多职业卡也算合法。"""
    if not card_class or card_class.upper() == "ALL":
        return "", []
    cc = card_class.upper()
    return (" AND (card_class=? OR card_class='NEUTRAL' OR (multi_class IS NOT NULL AND multi_class <> '' AND multi_class LIKE ?)) ",
            [cc, f"%{cc}%"])


def search_cards(
    *,
    q: Optional[str] = None,
    card_class: Optional[str] = None,
    mode: str = "standard",
    costs: Optional[List[int]] = None,
    cost_min: Optional[int] = None,
    cost_max: Optional[int] = None,
    rarities: Optional[List[str]] = None,
    sets: Optional[List[str]] = None,
    types: Optional[List[str]] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 60,
    sort: str = "cost",
) -> Dict[str, Any]:
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))

    where: List[str] = ["1=1"]
    args: List[Any] = []

    if mode == "standard":
        where.append("is_standard=1")
    elif mode == "wild":
        where.append("is_wild=1")

    clause, carg = _class_filter(card_class)
    if clause:
        where.append(clause.strip().removeprefix("AND ").strip())
        args += carg

    if costs:
        where.append(f"cost IN ({','.join('?' * len(costs))})")
        args += [int(c) for c in costs]
    else:
        if cost_min is not None:
            where.append("cost >= ?")
            args.append(int(cost_min))
        if cost_max is not None:
            where.append("cost <= ?")
            args.append(int(cost_max))
    if rarities:
        where.append(f"rarity IN ({','.join('?' * len(rarities))})")
        args += [r.upper() for r in rarities]
    if sets:
        where.append(f"card_set IN ({','.join('?' * len(sets))})")
        args += list(sets)
    if types:
        where.append(f"type IN ({','.join('?' * len(types))})")
        args += [t.upper() for t in types]
    if keyword:
        where.append("(keywords LIKE ? OR text LIKE ?)")
        args += [f"%{keyword}%", f"%{keyword}%"]
    if q:
        qnorm = q.strip()
        where.append("(name LIKE ? OR text LIKE ?)")
        args += [f"%{qnorm}%", f"%{qnorm}%"]

    where_sql = " AND ".join(where)
    order = {
        "cost": "is_standard DESC, cost, name",
        "name": "name",
        "dust": "dust_cost DESC, cost, name",
    }.get(sort, "cost, name")

    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) c FROM cards WHERE {where_sql}", args).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM cards WHERE {where_sql} ORDER BY {order} LIMIT ? OFFSET ?",
            args + [page_size, (page - 1) * page_size],
        ).fetchall()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_card_view(r) for r in rows],
    }


def _card_view(r: sqlite3.Row) -> Dict[str, Any]:
    from server.cardpool.normalizer import CLASS_CN as _CC  # 局部导入避免循环

    cc = r["card_class"]
    return {
        "dbf_id": r["dbf_id"],
        "card_id": r["card_id"],
        "name": r["name"],
        "cost": r["cost"],
        "attack": r["attack"],
        "health": r["health"],
        "durability": r["durability"],
        "armor": r["armor"],
        "type": r["type"],
        "race": r["race"],
        "rarity": r["rarity"],
        "card_class": cc,
        "class_cn": _CC.get(cc, cc),
        "multi_class": r["multi_class"],
        "card_set": r["card_set"],
        "text": r["text"],
        "keywords": r["keywords"],
        "runes": r["runes"],
        "spell_school": r["spell_school"],
        "dust_cost": _dust(r["rarity"]),
        "is_standard": bool(r["is_standard"]),
        "image_url": r["image_url"],
    }


def _dust(rarity: Optional[str]) -> int:
    from server.cardpool.normalizer import DUST_COST

    return DUST_COST.get(rarity or "", 0)


def get_cards_by_dbf(dbf_ids: Sequence[int]) -> Dict[int, Dict[str, Any]]:
    """批量取卡（返回 DBF -> 精简字段），供卡组码解析与 AI 校验使用。"""
    if not dbf_ids:
        return {}
    ids = list(dict.fromkeys(int(x) for x in dbf_ids))
    placeholders = ",".join("?" * len(ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM cards WHERE dbf_id IN ({placeholders})", ids
        ).fetchall()
    return {int(r["dbf_id"]): _card_view(r) for r in rows}


def get_tokens_by_dbf(dbf_ids: Sequence[int]) -> Dict[int, Dict[str, Any]]:
    """批量取衍生卡（不可收集的 token），用于识别卡组码里的附属牌。"""
    if not dbf_ids:
        return {}
    ids = list(dict.fromkeys(int(x) for x in dbf_ids))
    placeholders = ",".join("?" * len(ids))
    try:
        with get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM card_tokens WHERE dbf_id IN ({placeholders})", ids
            ).fetchall()
    except Exception:
        return {}
    return {
        int(r["dbf_id"]): {
            "dbf_id": int(r["dbf_id"]),
            "name": r["name"],
            "cost": r["cost"],
            "type": r["type"],
            "card_class": r["card_class"],
            "card_set": r["card_set"],
            "text": r["text"],
            "is_token": True,
        }
        for r in rows
    }


def find_by_names(names: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """按中文卡名精确查（AI 输出校验用）。"""
    out: Dict[str, Dict[str, Any]] = {}
    if not names:
        return out
    with get_conn() as conn:
        for n in names:
            n = (n or "").strip()
            if not n:
                continue
            row = conn.execute("SELECT * FROM cards WHERE name=? LIMIT 1", (n,)).fetchone()
            if row:
                out[n] = _card_view(row)
    return out


def list_sets(mode: str = "all") -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM card_sets ORDER BY is_standard DESC, card_count DESC"
        ).fetchall()
    out = [
        {
            "set": r["card_set"],
            "name": r["name_cn"] or r["card_set"],
            "count": r["card_count"],
            "is_standard": bool(r["is_standard"]),
        }
        for r in rows
    ]
    if mode == "standard":
        out = [x for x in out if x["is_standard"]]
    return out


def list_classes() -> List[Dict[str, Any]]:
    return [{"id": k, "name": v} for k, v in CLASS_CN.items() if k != "NEUTRAL"]
