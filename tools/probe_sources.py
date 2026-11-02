"""阶段⑤前置探针：用真实浏览器内核（本机 Edge/Chrome）实测三大平台能否绕过 WAF。

对每个源记录：HTTP 状态、页面标题、是否 Cloudflare 挑战页、HTML 长度、截图。
用法：python tools/probe_sources.py [--headed]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "probe"
OUT.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ("hsreplay", "https://hsreplay.net/meta/"),
    ("hsguru", "https://www.hsguru.com/tierlist"),
    ("nga", "https://bbs.nga.cn/thread.php?fid=422"),
]

CF_MARKS = ("just a moment", "cf-chl", "attention required", "cloudflare", "请稍候", "checking your browser")


def find_browser() -> str | None:
    for path in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ):
        if Path(path).exists():
            return path
    return None


def probe(page, name: str, url: str) -> dict:
    rec: dict = {"name": name, "url": url}
    t0 = time.time()
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        rec["status"] = resp.status if resp else None
        # Cloudflare 挑战页一般 3~8 秒内自动跳转，轮询标题确认
        for _ in range(4):
            page.wait_for_timeout(2500)
            title = (page.title() or "").lower()
            if not any(m in title for m in CF_MARKS):
                break
        rec["title"] = page.title()
        rec["cf_challenge"] = any(m in (page.title() or "").lower() for m in CF_MARKS)
        rec["html_len"] = len(page.content())
        rec["secs"] = round(time.time() - t0, 1)
        page.screenshot(path=str(OUT / f"{name}.png"))
    except Exception as e:
        rec["error"] = str(e)[:200]
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true", help="有头模式（部分 WAF 对无头更敏感）")
    a = ap.parse_args()

    exe = find_browser()
    print("browser exe:", exe)
    results: list[dict] = []
    with sync_playwright() as pw:
        kwargs: dict = {"headless": not a.headed}
        if exe:
            kwargs["executable_path"] = exe
        browser = pw.chromium.launch(**kwargs)
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        page = ctx.new_page()
        for name, url in TARGETS:
            results.append(probe(page, name, url))
            print(json.dumps(results[-1], ensure_ascii=False))
        browser.close()

    (OUT / "probe_result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved:", OUT / "probe_result.json")


if __name__ == "__main__":
    main()
