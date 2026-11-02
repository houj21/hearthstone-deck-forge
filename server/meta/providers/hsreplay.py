"""HSReplay 数据提供源。

接口（通过真实浏览器内核 + 页面内 fetch 调用，无需登录）：
- list_decks_by_win_rate_v2  按职业返回卡组列表（胜率 / 样本 / 完整卡表 / 原型 id）
- archetypes                  原型字典（id -> 名称 + 职业）
- constructed/meta_period     当前补丁与版本周期

免费额度实测（2026-10-28）：
- LeagueRankRange 仅 BRONZE_THROUGH_GOLD 免费，其余 403（会员）；
- TimeRange 仅 CURRENT_EXPANSION / LAST_30_DAYS 免费；
- Region 仅 ALL 免费。
因此“分段推荐”改用：时间窗切分 + 卡组节奏风格推断适配段位。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from server.logging_conf import get_logger
from server.meta.browser import BrowserFetchError, get_browser
from server.settings import get_settings

log = get_logger(__name__)

BASE = "https://hsreplay.net"
EP_DECKS = "/analytics/query/list_decks_by_win_rate_v2/"
EP_ARCHETYPES = "/api/v1/archetypes/"
EP_PERIOD = "/api/v1/constructed/meta_period/latest/"

GAME_TYPE = "RANKED_STANDARD"
LEAGUE = "BRONZE_THROUGH_GOLD"      # 免费档
REGION = "ALL"

# 时间窗：界面可选
TIME_WINDOWS = {
    "current": ("CURRENT_EXPANSION", "当前版本"),
    "30d": ("LAST_30_DAYS", "近 30 天"),
}

PREMIUM_RANK_RANGES = {
    "DIAMOND_THROUGH_LEGEND": "钻石~传说",
    "LEGEND_ONLY": "传说",
    "TOP_1000_LEGEND": "前千传说",
}


class HSReplayProvider:
    name = "hsreplay"
    label = "HSReplay"

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self.warm_url = f"{BASE}/meta/"
        self.errors: List[str] = []

    # ---------------------------------------------------------------- 原始接口
    def decks_url(self, window: str = "current") -> str:
        time_range = TIME_WINDOWS.get(window, TIME_WINDOWS["current"])[0]
        return (
            f"{EP_DECKS}?GameType={GAME_TYPE}&LeagueRankRange={LEAGUE}"
            f"&Region={REGION}&TimeRange={time_range}"
        )

    def fetch_raw(self, window: str = "current", timeout: int = 30) -> Dict[str, Any]:
        b = get_browser(self.headless)
        b.warm(self.warm_url, timeout=timeout)
        try:
            data = b.get_json(self.decks_url(window), timeout=timeout)
        except BrowserFetchError as e:
            self.errors.append(str(e))
            raise
        self._dump(f"decks_{window}.json", data)
        return data

    def fetch_archetypes(self, timeout: int = 30) -> List[Dict[str, Any]]:
        b = get_browser(self.headless)
        b.warm(self.warm_url, timeout=timeout)
        data = b.get_json(f"{EP_ARCHETYPES}?hl=en", timeout=timeout)
        self._dump("archetypes.json", data)
        return data

    def fetch_period(self, timeout: int = 30) -> Dict[str, Any]:
        b = get_browser(self.headless)
        b.warm(self.warm_url, timeout=timeout)
        data = b.get_json(f"{EP_PERIOD}?hl=en", timeout=timeout)
        self._dump("meta_period.json", data)
        return data

    # ---------------------------------------------------------------- 本地留档
    def _dump(self, name: str, data: Any) -> None:
        try:
            d = get_settings().data_dir / "meta"
            d.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            log.debug("dump %s failed: %s", name, e)

    @staticmethod
    def cached(path_name: str) -> Optional[Any]:
        """读取上一轮留档，供断网降级使用。"""
        p = get_settings().data_dir / "meta" / path_name
        try:
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
        return None

    # ---------------------------------------------------------------- 探活
    def probe(self, timeout: int = 30) -> Dict[str, Any]:
        t0 = time.time()
        try:
            data = self.fetch_raw("current", timeout=timeout)
            decks = sum(len(v) for v in data.get("series", {}).get("data", {}).values())
            return {
                "name": self.name,
                "ok": True,
                "decks": decks,
                "as_of": data.get("as_of"),
                "secs": round(time.time() - t0, 1),
            }
        except Exception as e:
            return {"name": self.name, "ok": False, "message": str(e)[:160],
                    "secs": round(time.time() - t0, 1)}
