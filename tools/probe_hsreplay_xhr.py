"""第二轮：捕获全部 JSON 响应 + 检查页面内嵌状态数据，定位胜率数据源。"""

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

captured: list[dict] = []
PAYLOADS: dict[str, object] = {}


def on_response(resp):
    url = resp.url
    if resp.request.resource_type not in ("xhr", "fetch"):
        return
    try:
        ctype = resp.headers.get("content-type", "")
        if "json" not in ctype:
            return
        body = resp.json()
    except Exception:
        return
    size = len(json.dumps(body))
    captured.append({
        "url": url[:160],
        "status": resp.status,
        "size": size,
        "shape": list(body.keys())[:15] if isinstance(body, dict) else f"list[{len(body)}]",
    })
    if size > 20000:
        PAYLOADS[url[:200]] = body


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=EXE)
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        page = ctx.new_page()
        page.on("response", on_response)
        page.goto("https://hsreplay.net/meta/", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(7000)

        # 页面是否内嵌了初始状态
        embedded = page.evaluate(
            """() => {
              const keys = [];
              for (const k in window) {
                try {
                  const v = window[k];
                  if (v && typeof v === 'object' && JSON.stringify(v).length > 10000) {
                    keys.push({key: k, size: JSON.stringify(v).length});
                  }
                } catch (e) {}
              }
              return keys.sort((a,b)=>b.size-a.size).slice(0, 8);
            }"""
        )

        (OUT / "hsreplay_xhr2.json").write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")
        (OUT / "hsreplay_embedded.json").write_text(json.dumps(embedded, ensure_ascii=False, indent=2), encoding="utf-8")
        for c in sorted(captured, key=lambda x: -x["size"]):
            print(c["status"], f"{c['size']:>9}", c["url"])
            print("     ", c["shape"])
        print("embedded:", embedded)
        # 保存最大的几个响应体供离线分析
        for i, (u, b) in enumerate(sorted(PAYLOADS.items(), key=lambda kv: -len(json.dumps(kv[1])))[:5]):
            p = OUT / f"payload_{i}.json"
            p.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
            print("saved", p, u)
        browser.close()


if __name__ == "__main__":
    main()
