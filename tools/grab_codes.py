"""用本机 Edge 渲染 hearthstone-decks.net，抓取真实卡组码用于解析器对照验证。"""

from __future__ import annotations

import re
import sys

from playwright.sync_api import sync_playwright

PAGES = [
    "https://hearthstone-decks.net/standard/",
    "https://hearthstone-decks.net/",
]
CODE_RE = re.compile(r"AAECA[A-Za-z0-9+/=]{40,}")


def main() -> None:
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        page = b.new_page()
        found: list[str] = []
        for url in PAGES:
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(2500)
                html = page.content()
                codes = CODE_RE.findall(html)
                for c in codes:
                    if c not in found:
                        found.append(c)
            except Exception as e:
                print("skip", url, e, file=sys.stderr)
        b.close()

    print(f"共找到 {len(found)} 个卡组码")
    for c in found[:15]:
        print(c)


if __name__ == "__main__":
    main()
