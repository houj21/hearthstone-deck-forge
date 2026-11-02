"""探测 LLM 网关：连通性 + 流式格式 + reasoning/content 字段分布。

用法：python tools/probe_llm.py [--model xxx]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.settings import get_llm_settings  # noqa: E402


def probe(model: str) -> None:
    s = get_llm_settings()
    url = f"{s.base_url}/chat/completions"
    payload = {
        "model": model,
        "stream": True,
        "temperature": 0.3,
        "messages": [{"role": "user", "content": "只回复两个字：可用"}],
    }
    headers = {"Authorization": f"Bearer {s.llm_api_key}", "Content-Type": "application/json"}
    t0 = time.time()
    content, reasoning, chunks = "", "", 0
    with httpx.Client(timeout=90.0) as c:
        with c.stream("POST", url, json=payload, headers=headers) as r:
            print(f"[{model}] HTTP {r.status_code} in {time.time()-t0:.1f}s")
            if r.status_code != 200:
                print(r.read().decode("utf-8", "replace")[:400])
                return
            for line in r.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    d = json.loads(data)
                except json.JSONDecodeError:
                    continue
                chunks += 1
                delta = (d.get("choices") or [{}])[0].get("delta", {}) or {}
                content += delta.get("content") or ""
                reasoning += delta.get("reasoning_content") or ""
    print(f"[{model}] chunks={chunks} content_len={len(content)} reasoning_len={len(reasoning)}")
    print(f"[{model}] content: {content[:120]!r}")
    if not content:
        print(f"[{model}] !! content 为空，reasoning: {reasoning[:120]!r}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="探测模型链全部模型")
    ap.add_argument("--model", default="")
    a = ap.parse_args()
    s = get_llm_settings()
    models = s.model_chain if a.all else [a.model or s.llm_model]
    for m in models:
        try:
            probe(m)
        except Exception as e:
            print(f"[{m}] ERROR {e}")
        print("-" * 60)
