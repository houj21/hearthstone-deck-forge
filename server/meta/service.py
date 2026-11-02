"""环境数据服务：刷新快照、读写快照、源健康状态。

刷新流程：
  真实浏览器内核 -> HSReplay 分析接口 -> 归一化聚合 -> 落快照（DB + JSON 留档）
任何一步失败都降级到上一次留档，并在快照里标注 degraded，界面显示源状态。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.db.base import get_conn
from server.logging_conf import get_logger
from server.meta.browser import browser_available, close_browser
from server.meta.normalizer import aggregate, CLASS_CN, STYLE_CN
from server.meta.providers.hsreplay import HSReplayProvider, TIME_WINDOWS
from server.settings import get_settings

log = get_logger(__name__)

_refresh_lock_state = {"busy": False}


# ---------------------------------------------------------------- 快照读写
def _row_to_entry(r) -> Dict[str, Any]:
    try:
        payload = json.loads(r["payload"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    if payload:
        payload["id"] = r["id"]
        return payload
    return {
        "id": r["id"],
        "name": r["deck_name"],
        "name_en": r["deck_name_en"],
        "card_class": r["card_class"],
        "win_rate": r["win_rate"],
        "sample_size": r["sample_size"],
        "share": r["share"],
        "trend": r["trend"],
        "deck_code": r["deck_code"],
    }


def latest_snapshot(mode: str = "standard") -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM meta_snapshot WHERE is_current=1 AND mode=? ORDER BY id DESC LIMIT 1",
            (mode,),
        ).fetchone()
    if not row:
        return None
    return dict(row)


def snapshot_entries(snapshot_id: int) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM meta_entry WHERE snapshot_id=? ORDER BY win_rate DESC, sample_size DESC",
            (snapshot_id,),
        ).fetchall()
    return [_row_to_entry(r) for r in rows]


def get_summary(
    *,
    mode: str = "standard",
    window: str = "current",
    card_class: Optional[str] = None,
    limit: int = 60,
) -> Dict[str, Any]:
    snap = latest_snapshot(mode)
    if not snap:
        return {"ok": False, "entries": [], "updated_at": None, "message": "尚无环境快照，点击刷新获取"}
    entries = snapshot_entries(int(snap["id"]))
    if card_class:
        entries = [e for e in entries if e.get("card_class") == card_class.upper()]
    st = get_settings()
    ttl = float(st.meta.get("ttl_minutes", 180)) * 60
    age = time.time() - _parse_ts(snap["created_at"])
    return {
        "ok": True,
        "snapshot_id": snap["id"],
        "mode": snap["mode"],
        "window": window,
        "window_label": TIME_WINDOWS.get(window, TIME_WINDOWS["current"])[1],
        "updated_at": snap["created_at"],
        "entry_count": snap["entry_count"],
        "stale": age > ttl,
        "age_minutes": int(age / 60),
        "source_status": _json_load(snap["source_status"]),
        "entries": entries[:limit],
    }


def status() -> Dict[str, Any]:
    st = get_settings()
    snap = latest_snapshot()
    out: Dict[str, Any] = {
        "browser_available": browser_available(),
        "providers": [
            {"name": "hsreplay", "label": "HSReplay", "enabled": True,
             "via": "browser", "note": "免费档：青铜~黄金，当前版本/近30天"},
            {"name": "hsguru", "label": "HSGuru 驴子网", "enabled": False,
             "via": "browser", "note": "本机网络不可达（2026-10 实测超时），已停用"},
            {"name": "nga", "label": "NGA 论坛", "enabled": False,
             "via": "browser", "note": "本机网络不可达（重定向中断），已停用"},
        ],
        "time_windows": [
            {"id": k, "label": v[1], "param": v[0]} for k, v in TIME_WINDOWS.items()
        ],
        "ttl_minutes": st.meta.get("ttl_minutes", 180),
        "refreshing": _refresh_lock_state["busy"],
        "buckets": [{"id": b.id, "label": b.label} for b in st.buckets],
    }
    if snap:
        out["snapshot"] = {
            "id": snap["id"],
            "created_at": snap["created_at"],
            "entry_count": snap["entry_count"],
            "source_status": _json_load(snap["source_status"]),
        }
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT source, status, entry_count, message, started_at FROM refresh_log"
            " ORDER BY id DESC LIMIT 6"
        ).fetchall()
    out["last_refresh"] = [dict(r) for r in rows]
    return out


# ---------------------------------------------------------------- 刷新
def refresh(
    *,
    mode: str = "standard",
    window: str = "current",
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """抓取一轮环境数据并落快照。失败则降级到留档。"""
    if _refresh_lock_state["busy"]:
        return {"ok": False, "message": "正在刷新中，请稍候"}
    _refresh_lock_state["busy"] = True
    st = get_settings()
    timeout = int(timeout or st.meta.get("per_source_timeout", 30))
    started = datetime.now().isoformat(timespec="seconds")
    provider = HSReplayProvider()
    sources: List[Dict[str, Any]] = []
    degraded = False
    message = ""

    try:
        raw = provider.fetch_raw(window, timeout=timeout)
        try:
            arch_raw = provider.fetch_archetypes(timeout=timeout)
        except Exception as e:                      # 原型字典失败不影响主体
            log.warning("archetypes fetch failed: %s", e)
            arch_raw = HSReplayProvider.cached("archetypes.json") or []
            degraded = True
        try:
            period = provider.fetch_period(timeout=timeout)
        except Exception:
            period = HSReplayProvider.cached("meta_period.json") or {}
        arch_map = {int(a.get("id")): a for a in arch_raw if a.get("id") is not None}
        sources.append({"name": "hsreplay", "status": "ok", "decks": _count_decks(raw)})
        source_note = f"HSReplay {TIME_WINDOWS.get(window, TIME_WINDOWS['current'])[1]}"
        if period.get("patch_version"):
            source_note += f" · 补丁 {period['patch_version']}"
    except Exception as e:
        log.error("hsreplay fetch failed: %s", e)
        raw = HSReplayProvider.cached(f"decks_{window}.json")
        arch_raw = HSReplayProvider.cached("archetypes.json") or []
        arch_map = {int(a.get("id")): a for a in arch_raw if a.get("id") is not None}
        if not raw:
            _log_refresh("hsreplay", "error", 0, str(e)[:200], started)
            _refresh_lock_state["busy"] = False
            return {"ok": False, "message": f"抓取失败且无本地留档：{e}"}
        degraded = True
        message = f"实时抓取失败，已降级显示本地留档（{e}）"
        sources.append({"name": "hsreplay", "status": "cached", "message": str(e)[:120]})

    try:
        min_sample = int(st.recommend.get("min_sample_size", 200))
        entries = aggregate(raw, arch_map, mode=mode, min_sample=min_sample)
        prev = _previous_map(mode)
        for e in entries:
            old = prev.get((e["card_class"], e["archetype_id"]))
            e["trend"] = round(e["win_rate"] - old, 2) if old else 0.0
        snapshot_id = _save_snapshot(mode, entries, sources, degraded, message)
        _log_refresh("hsreplay", "ok" if not degraded else "degraded", len(entries),
                     message or source_note, started)
        result = {
            "ok": True,
            "snapshot_id": snapshot_id,
            "entry_count": len(entries),
            "degraded": degraded,
            "message": message,
            "sources": sources,
        }
    finally:
        _refresh_lock_state["busy"] = False
        try:
            close_browser()
        except Exception:
            pass
    return result


def ensure_fresh(max_age_minutes: int = 180) -> bool:
    """快照过期则自动刷新（启动预热 / 定时任务用）。"""
    snap = latest_snapshot()
    if snap and (time.time() - _parse_ts(snap["created_at"])) < max_age_minutes * 60:
        return False
    try:
        refresh()
        return True
    except Exception as e:
        log.warning("auto refresh failed: %s", e)
        return False


# ---------------------------------------------------------------- 内部
def _count_decks(raw: Dict[str, Any]) -> int:
    try:
        return sum(len(v) for v in raw["series"]["data"].values())
    except Exception:
        return 0


def _previous_map(mode: str) -> Dict[tuple, float]:
    out: Dict[tuple, float] = {}
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM meta_snapshot WHERE mode=? AND is_current=1 ORDER BY id DESC LIMIT 1",
            (mode,),
        ).fetchone()
        if not row:
            return out
        for r in conn.execute(
            "SELECT card_class, payload, win_rate FROM meta_entry WHERE snapshot_id=?", (row["id"],)
        ).fetchall():
            try:
                p = json.loads(r["payload"] or "{}")
                key = (r["card_class"], int(p.get("archetype_id") or 0))
                out[key] = float(p.get("win_rate") or r["win_rate"] or 0)
            except Exception:
                continue
    return out


def _save_snapshot(
    mode: str,
    entries: List[Dict[str, Any]],
    sources: List[Dict[str, Any]],
    degraded: bool,
    message: str,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO meta_snapshot (created_at, mode, entry_count, source_status, is_current)"
            " VALUES (?,?,?,?,1)",
            (now, mode, len(entries), json.dumps(
                {"sources": sources, "degraded": degraded, "message": message}, ensure_ascii=False)),
        )
        snap_id = int(cur.lastrowid)
        conn.execute("UPDATE meta_snapshot SET is_current=0 WHERE id<>? AND mode=?", (snap_id, mode))
        conn.executemany(
            """
            INSERT INTO meta_entry (snapshot_id, deck_name, deck_name_en, card_class, archetype,
                                    rank_bucket, win_rate, sample_size, share, trend, deck_code,
                                    cards_signature, confidence, sources, source_count, note,
                                    fetched_at, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    snap_id,
                    e["name"],
                    e.get("name_en", ""),
                    e["card_class"],
                    e.get("style_cn", ""),
                    ",".join(e.get("buckets", [])),
                    e["win_rate"],
                    e["sample_size"],
                    e["share"],
                    e["trend"],
                    e.get("deck_code", ""),
                    json.dumps(e.get("deck_cards", [])),
                    round(min(1.0, e["sample_size"] / 2000.0), 2),
                    "hsreplay",
                    1,
                    e.get("name_en", ""),
                    now,
                    json.dumps(e, ensure_ascii=False),
                )
                for e in entries
            ],
        )
        conn.execute("DELETE FROM meta_snapshot WHERE id<? AND mode=?", (snap_id - 5, mode))
        conn.commit()
    log.info("meta snapshot saved: id=%s entries=%s degraded=%s", snap_id, len(entries), degraded)
    return snap_id


def _log_refresh(source: str, status: str, count: int, message: str, started: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO refresh_log (started_at, ended_at, mode, source, status, entry_count, message)"
                " VALUES (?,?,?,?,?,?,?)",
                (started, now, "standard", source, status, count, message[:400]),
            )
            conn.commit()
    except Exception as e:
        log.warning("refresh log failed: %s", e)


def _json_load(s: Optional[str]) -> Any:
    try:
        return json.loads(s or "{}")
    except json.JSONDecodeError:
        return {}


def _parse_ts(s: str) -> float:
    try:
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0
