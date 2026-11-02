"""HSReplay /meta/ 结构采样（独立页面，避免 NGA 导航干扰）。"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "probe"
OUT.mkdir(parents=True, exist_ok=True)

EXE = next((p for p in (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
) if Path(p).exists()), None)


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=EXE)
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 2400},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        page = ctx.new_page()
        page.goto("https://hsreplay.net/meta/", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(5000)

        info = page.evaluate(
            """() => {
              const out = {h1: document.querySelector('h1')?.innerText || '', tables: []};
              document.querySelectorAll('table').forEach(t => {
                const rows = [...t.querySelectorAll('tbody tr')];
                if (!rows.length) return;
                out.tables.push({
                  cls: t.className,
                  rows: rows.length,
                  headers: [...t.querySelectorAll('thead th')].map(x => x.innerText.trim()),
                  first: rows.slice(0,2).map(r => r.innerText.replace(/\\n/g,' | ').slice(0,220)),
                });
              });
              // 类别分块（按职业分组的标题）
              out.sections = [...document.querySelectorAll('h2,h3')].slice(0,20).map(h => h.innerText.trim());
              // 展开卡组列表的按钮特征
              out.expanders = [...document.querySelectorAll('button, .toggle-deck-list, a')].filter(e => /deck list|card list/i.test(e.innerText)).length;
              // 分段选择控件
              out.selects = [...document.querySelectorAll('select')].map(s => ({
                id: s.id || s.name, opts: [...s.options].slice(0,15).map(o => ({v:o.value, t:o.innerText.trim()}))
              }));
              // 底部是否标注时间段
              out.body_snip = document.body.innerText.slice(0, 400);
              return out;
            }"""
        )
        (OUT / "hsreplay_structure.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(info, ensure_ascii=False, indent=1)[:3500])
        page.screenshot(path=str(OUT / "hsreplay_meta.png"), full_page=True)
        browser.close()


if __name__ == "__main__":
    main()
