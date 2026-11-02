"""冒烟：真实网关跑一遍 AI 构筑 SSE（验证事件流与卡组码闭环）。"""

from __future__ import annotations

import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8765"


def sse(path: str, params: dict, label: str) -> None:
    print(f"\n=== {label} ===")
    t0 = time.time()
    result = None
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as c:
        with c.stream("GET", BASE + path, params=params) as r:
            print("HTTP", r.status_code, r.headers.get("content-type"))
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:].strip())
                t = ev.get("type")
                if t == "status":
                    print(f"  [{time.time()-t0:5.1f}s] status: {ev.get('text')}")
                elif t == "delta":
                    print(f"  [{time.time()-t0:5.1f}s] delta: {(ev.get('text') or '')[:60]!r}")
                elif t == "error":
                    print(f"  [{time.time()-t0:5.1f}s] ERROR: {ev.get('message')}")
                elif t == "result":
                    result = ev
                    print(f"  [{time.time()-t0:5.1f}s] result: ok={ev.get('ok')} source={ev.get('source')}"
                          f" total={ev.get('total')} code={(ev.get('deck_code') or '')[:20]}"
                          f" llm_error={ev.get('llm_error')}")
    print(f"总耗时 {time.time()-t0:.1f}s")
    return result


if __name__ == "__main__":
    st = httpx.get(BASE + "/api/ai/status", timeout=10).json()
    print("status:", json.dumps(st, ensure_ascii=False)[:300])

    res = sse("/api/ai/build", {"card_class": sys.argv[1] if len(sys.argv) > 1 else "MAGE",
                                "mode": "standard", "intent": "faster"}, "AI 自动构筑")
    if res and res.get("deck_code"):
        sse("/api/ai/swap", {"card_class": sys.argv[1] if len(sys.argv) > 1 else "MAGE",
                             "mode": "standard", "deck_code": res["deck_code"],
                             "target": (res.get("cards") or [{}])[0].get("name", ""),
                             "intent": "cheaper"}, "AI 换卡建议")
