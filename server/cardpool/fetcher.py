"""卡表拉取与本地缓存。

策略：
1. 优先使用 data/cards.zhCN.json 缓存（有效期内直接用）；
2. 过期时用 ETag 做条件请求，304 则继续用旧文件；
3. 网络失败且有旧缓存 -> 直接使用（降级，保证断网可用）；
4. 网络失败且无缓存 -> 抛异常，由上层提示。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx

from server.logging_conf import get_logger
from server.settings import get_settings

log = get_logger(__name__)


class CardFetchError(RuntimeError):
    pass


def _read_json(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def ensure_full_card_cache(force: bool = False) -> List[Dict[str, Any]]:
    """拉取完整卡表（含不可收集的衍生卡）。

    官方卡组码里会包含由可组卡带来的衍生牌（如「时空硬币」TIME_020t1），
    这些卡只在 cards.json（完整版）里，collectible 版本没有，因此需要单独缓存。
    """
    cache_file: Path = get_settings().data_dir / "cards.full.zhCN.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    ttl = 7 * 24 * 3600          # 完整卡表变化频率低，缓存 7 天
    fresh = cache_file.exists() and (time.time() - cache_file.stat().st_mtime < ttl)
    if fresh and not force:
        return _read_json(cache_file)

    url = get_settings().cardpool.get(
        "source_url_full", "https://api.hearthstonejson.com/v1/latest/zhCN/cards.json"
    )
    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "hs-deck-forge/0.1 (+local tool)"})
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or not data:
                raise CardFetchError("unexpected full card payload")
            tmp = cache_file.with_suffix(".tmp")
            tmp.write_bytes(resp.content)
            tmp.replace(cache_file)
            log.info("full card cache refreshed: %s cards", len(data))
            return data
    except Exception as e:
        if cache_file.exists():
            log.warning("full card fetch failed, use stale cache: %s", e)
            return _read_json(cache_file)
        raise CardFetchError(f"无法获取完整卡表：{e}") from e


def ensure_card_cache(force: bool = False) -> List[Dict[str, Any]]:
    """返回原始卡表；优先缓存，必要时增量拉取。"""
    st = get_settings()
    cache_file: Path = st.card_cache
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    ttl = float(st.cardpool.get("cache_hours", 24)) * 3600
    fresh = cache_file.exists() and (time.time() - cache_file.stat().st_mtime < ttl)

    if fresh and not force:
        return _read_json(cache_file)

    url = st.cardpool.get("source_url")
    headers = {"User-Agent": "hs-deck-forge/0.1 (+local tool)"}
    etag_file = cache_file.with_suffix(".etag")
    if cache_file.exists() and etag_file.exists():
        headers["If-None-Match"] = etag_file.read_text(encoding="utf-8").strip()

    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == 304 and cache_file.exists():
                cache_file.touch()
                log.info("card cache still fresh (304)")
                return _read_json(cache_file)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or not data:
                raise CardFetchError("unexpected card payload")

            tmp = cache_file.with_suffix(".tmp")
            tmp.write_bytes(resp.content)
            tmp.replace(cache_file)
            etag = resp.headers.get("etag")
            if etag:
                etag_file.write_text(etag, encoding="utf-8")
            log.info("card cache refreshed: %s cards", len(data))
            return data
    except Exception as e:
        if cache_file.exists():
            log.warning("fetch failed, fallback to stale cache: %s", e)
            return _read_json(cache_file)
        raise CardFetchError(f"无法获取卡表且无本地缓存：{e}") from e
