"""端到端 UI 冒烟：加载首页，检查控制台报错，抓 PC / 手机两版截图。

用法：python tests/smoke_ui.py [--url http://127.0.0.1:8765]
复用本机 Edge/Chrome，无需下载 Playwright 浏览器内核。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "data" / "shots"

# 真实样本：Hearthstone-Decks.net「Cycle Rogue #60 Legend - maxiebon1234」
REAL_CODE = "AAECAaIHBJegBNCeBr2+BqrqBg2RnwT2nwT3nwTfwwW/9wXI+wXungbZogatpwaQtAa2tQaY4Qbk6gYAAA=="


def find_browser_channel() -> str | None:
    for p in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ):
        if Path(p).exists():
            return "msedge" if "Edge" in p else "chrome"
    return None


def run(url: str) -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    channel = find_browser_channel()
    errors: list[str] = []

    with sync_playwright() as pw:
        launch_args = {"headless": True}
        if channel:
            launch_args["channel"] = channel
        browser = pw.chromium.launch(**launch_args)

        # ---- PC ----
        page = browser.new_page(viewport={"width": 1440, "height": 940})
        page.on("console", lambda m: errors.append(f"[console.{m.type}] {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))
        page.goto(url, wait_until="networkidle", timeout=45000)
        page.wait_for_selector("#healthHint .status-dot", timeout=30000)

        # 环境视图：等待 HSReplay 卡片渲染（首次进入会自动抓取）
        meta_cards = 0
        meta_first = ""
        try:
            page.wait_for_selector("#metaDeckList .deck-card", timeout=120000)
            meta_cards = page.locator("#metaDeckList .deck-card").count()
            meta_first = page.locator("#metaDeckList .deck-card").first.inner_text().replace("\n", " | ")[:90]
        except Exception as e:
            errors.append(f"[meta] {str(e)[:80]}")
        page.screenshot(path=str(SHOTS / "pc_meta.png"))

        # 推荐榜 -> 一键导入组卡器（闭环）
        recommend_cards = page.locator("#metaRecommend .deck-card").count()
        recommend_first = page.locator("#metaRecommend .deck-card").first.inner_text().replace("\n", " | ")[:90]
        imported_from_meta = ""
        try:
            page.wait_for_selector("#metaRecommend [data-import]", timeout=30000)
            page.locator("#metaRecommend [data-import]").first.click()
            page.wait_for_function(
                "document.getElementById('deckCount').textContent.startsWith('30')",
                timeout=20000,
            )
            imported_from_meta = page.locator("#deckCount").inner_text()
        except Exception as e:
            errors.append(f"[recommend-import] {str(e)[:80]}")
        page.screenshot(path=str(SHOTS / "pc_recommend_import.png"))

        # 组卡视图：切过去并加两张卡
        page.click('.desknav button[data-view="viewBuilder"]')
        page.wait_for_selector("#viewBuilder.active .mini-card", state="visible", timeout=30000)
        cards = page.locator("#viewBuilder .mini-card").count()
        page.locator("#viewBuilder .mini-card").nth(0).click()
        page.locator("#viewBuilder .mini-card").nth(1).click()
        deck_count = page.locator("#deckCount").inner_text()
        curve_bars = page.locator(".curve-bar").count()
        page.screenshot(path=str(SHOTS / "pc_builder.png"))

        # 卡组码：导入真实样本 -> 导出回归
        page.fill("#deckCodeInput", REAL_CODE)
        page.click("#btnImportCode")
        page.wait_for_function(
            "document.getElementById('deckCount').textContent.startsWith('30')",
            timeout=15000,
        )
        imported_count = page.locator("#deckCount").inner_text()
        imported_rows = page.locator("#deckList .deck-row[data-dbf]").count()
        export_code = page.locator("#deckCodeInput").input_value()
        page.screenshot(path=str(SHOTS / "pc_import.png"))

        # AI 教练：真实网关流式构筑 -> 采纳进组卡器
        ai_chips = 0
        ai_deck_ok = False
        try:
            page.click("#btnAi")
            page.wait_for_selector("#intentChips .chip", timeout=15000)
            ai_chips = page.locator("#intentChips .chip").count()
            page.locator("#intentChips .chip").first.click()
            page.click("#btnBuild")
            page.wait_for_function(
                "document.getElementById('aiOut').textContent.includes('卡组码')",
                timeout=180000,
            )
            ai_deck_ok = True
            page.screenshot(path=str(SHOTS / "pc_ai_build.png"))
            page.click("#btnApplyDeck")
            page.wait_for_function(
                "document.getElementById('deckCount').textContent.startsWith('30')",
                timeout=20000,
            )
            ai_applied = page.locator("#deckCount").inner_text()
        except Exception as e:
            errors.append(f"[ai] {str(e)[:100]}")
            ai_applied = ""
        page.screenshot(path=str(SHOTS / "pc_ai_applied.png"))

        # 组卡面板「AI 优化」按钮 -> 抽屉里流式点评
        ai_suggest_ok = False
        try:
            page.click("#btnAiSuggest")
            page.wait_for_function(
                "document.getElementById('aiOut').textContent.trim().length > 40",
                timeout=150000,
            )
            ai_suggest_ok = True
        except Exception as e:
            errors.append(f"[ai-suggest] {str(e)[:80]}")
        page.screenshot(path=str(SHOTS / "pc_ai_suggest.png"))

        # ---- 手机（iPhone 15 尺寸 + iOS UA）----
        m = browser.new_page(
            viewport={"width": 390, "height": 844},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                       "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
        )
        m.on("pageerror", lambda e: errors.append(f"[mobile pageerror] {e}"))
        m.goto(url, wait_until="networkidle", timeout=45000)
        tabbar_visible = m.locator(".tabbar").is_visible()
        m.screenshot(path=str(SHOTS / "mobile_home.png"))
        m.click('.tabbar button[data-view="viewBuilder"]')
        m.wait_for_selector("#viewBuilder.active .mini-card", state="visible", timeout=30000)
        m.screenshot(path=str(SHOTS / "mobile_builder.png"))

        # 手机端 AI 抽屉适配（底部抽屉 + 意图选中态 + 无横向溢出）
        ai_mobile = {"chips": 0, "width": 0, "pressed": False, "no_overflow": False, "btns": False}
        try:
            m.click("#btnAi")
            m.wait_for_selector("#drawer.open", timeout=10000)
            m.wait_for_selector("#intentChips .chip", timeout=15000)
            chips = m.locator("#intentChips .chip")
            ai_mobile["chips"] = chips.count()
            chips.first.click()
            ai_mobile["pressed"] = chips.first.get_attribute("aria-pressed") == "true"
            ai_mobile["width"] = int(m.evaluate(
                "document.getElementById('drawer').getBoundingClientRect().width"))
            ai_mobile["no_overflow"] = bool(m.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"))
            ai_mobile["btns"] = all(
                m.locator(f"#{i}").is_visible()
                for i in ["btnBuild", "btnSwap", "btnReview", "btnApplyDeck"])
        except Exception as e:
            errors.append(f"[ai-mobile] {str(e)[:100]}")
        m.screenshot(path=str(SHOTS / "mobile_ai_drawer.png"))

        browser.close()

    print("=" * 60)
    print(f"环境卡片数            : {meta_cards}")
    print(f"环境首条              : {meta_first}")
    print(f"推荐榜条目数          : {recommend_cards}")
    print(f"推荐榜首条            : {recommend_first}")
    print(f"推荐一键导入后张数    : {imported_from_meta}")
    print(f"AI 意图 chips         : {ai_chips}")
    print(f"AI 采纳后张数         : {ai_applied or '（失败）'}")
    print(f"组卡页 AI 优化按钮    : {'可用' if ai_suggest_ok else '（失败）'}")
    print(f"手机 AI 抽屉          : chips={ai_mobile['chips']} 宽={ai_mobile['width']}"
          f" 选中态={ai_mobile['pressed']} 无溢出={ai_mobile['no_overflow']} 按钮可见={ai_mobile['btns']}")
    print(f"卡池卡片数(PC)        : {cards}")
    print(f"卡组计数(点两下后)    : {deck_count}")
    print(f"法力曲线柱数          : {curve_bars}")
    print(f"导入真实卡组码后       : {imported_count} / {imported_rows} 行")
    print(f"导出卡组码前缀合法     : {export_code.startswith('AAECA')}")
    print(f"手机底部 Tab 可见     : {tabbar_visible}")
    print(f"控制台错误            : {len(errors)}")
    for e in errors[:10]:
        print("   " + e)
    print("截图目录              :", SHOTS)
    print("=" * 60)
    return 1 if errors else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    a = ap.parse_args()
    sys.exit(run(a.url))
