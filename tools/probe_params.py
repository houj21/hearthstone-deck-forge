"""验证 HSReplay 分析接口的参数枚举（LeagueRankRange / TimeRange / Region）。"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "probe"

EXE = next((p for p in (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
) if Path(p).exists()), None)

CANDIDATES = {
    "LeagueRankRange": ["BRONZE_THROUGH_GOLD", "DIAMOND_THROUGH_LEGEND", "LEGEND_ONLY",
                        "LEGEND", "TOP_1000_LEGEND", "ALL", "BRONZE_THROUGH_LEGEND"],
    "TimeRange": ["CURRENT_EXPANSION", "LAST_1_DAY", "LAST_3_DAYS", "LAST_7_DAYS",
                  "LAST_14_DAYS", "LAST_30_DAYS", "THIS_MONTH"],
    "Region": ["ALL", "US", "EU", "AP", "CN"],
}


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=EXE)
        page = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="zh-CN",
        ).new_page()
        page.goto("https://hsreplay.net/meta/", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3000)

        result: dict[str, list] = {k: [] for k in CANDIDATES}
        for param, values in CANDIDATES.items():
            for v in values:
                url = (
                    "/analytics/query/list_decks_by_win_rate_v2/?GameType=RANKED_STANDARD"
                    f"&{param}={v}&Region=ALL&TimeRange=CURRENT_EXPANSION"
                )
                if param == "TimeRange":
                    url = (
                        "/analytics/query/list_decks_by_win_rate_v2/?GameType=RANKED_STANDARD"
                        f"&LeagueRankRange=BRONZE_THROUGH_GOLD&Region=ALL&{param}={v}"
                    )
                if param == "Region":
                    url = (
                        "/analytics/query/list_decks_by_win_rate_v2/?GameType=RANKED_STANDARD"
                        f"&LeagueRankRange=BRONZE_THROUGH_GOLD&Region={v}&TimeRange=CURRENT_EXPANSION"
                    )
                out = page.evaluate(
                    """async (u) => {
                        try {
                          const r = await fetch(u, {credentials:'omit'});
                          if (!r.ok) return {status: r.status};
                          const j = await r.json();
                          const n = j.series?.data ? Object.values(j.series.data).reduce((s,a)=>s+a.length,0) : 0;
                          return {status: r.status, decks: n, as_of: j.as_of};
                        } catch (e) { return {error: String(e).slice(0,80)}; }
                    }""",
                    url,
                )
                result[param].append({"value": v, **out})
                print(param, v, out)

        (OUT / "hsreplay_params.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        browser.close()


if __name__ == "__main__":
    main()
