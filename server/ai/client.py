"""OpenAI 兼容网关客户端（流式 + 非流式）。

实测（2026-10-28）踩过的坑都在这里处理了：
- 网关上部分模型是重推理模型（如 step-5-preview），90 秒都吐不出一个 token，
  首包超时后必须换模型，否则界面就是假死；因此按 model_chain 逐级降级；
- 有些模型把正文放在 reasoning_content 里，只取 content 会得到空串，
  这里两个字段都收，content 为空时退回 reasoning；
- 流式必须用 SSE 增量，网关长文本响应可达 200-330 秒。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from server.logging_conf import get_logger
from server.settings import get_llm_settings, get_settings

log = get_logger(__name__)


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str = ""
    model: str = ""
    elapsed: float = 0.0
    reasoning_len: int = 0
    attempts: List[str] = field(default_factory=list)


def configured() -> bool:
    return get_llm_settings().configured


def _headers() -> Dict[str, str]:
    s = get_llm_settings()
    return {"Authorization": f"Bearer {s.llm_api_key}", "Content-Type": "application/json"}


def _payload(model: str, messages: List[Dict[str, str]], temperature: float, stream: bool) -> Dict[str, Any]:
    return {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }


def _is_timeout(e: Exception) -> bool:
    return isinstance(e, (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError))


def _extract(delta: Dict[str, Any]) -> tuple[str, str]:
    return (delta.get("content") or ""), (delta.get("reasoning_content") or "")


# ---------------------------------------------------------------- 流式
async def astream(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    timeout: Optional[int] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """逐段产出 {'type':'delta'|'done', 'text':.., 'model':..}。"""
    s = get_llm_settings()
    if not s.configured:
        raise LLMError("未配置 LLM 网关（.env 缺 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL）")
    st = get_settings()
    temperature = float(temperature if temperature is not None else st.ai.get("temperature", 0.7))
    timeout = int(timeout or s.llm_timeout or 360)
    models = [model] if model else s.model_chain

    last_err: Optional[Exception] = None
    for m in models:
        t0 = time.time()
        content, reasoning, chunks = [], 0, 0
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=30.0)) as c:
                async with c.stream(
                    "POST", f"{s.base_url}/chat/completions",
                    json=_payload(m, messages, temperature, True), headers=_headers(),
                ) as r:
                    if r.status_code != 200:
                        body = (await r.aread()).decode("utf-8", "replace")[:200]
                        raise LLMError(f"HTTP {r.status_code} {body}")
                    yield {"type": "model", "model": m}
                    async for line in r.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            d = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        delta = ((d.get("choices") or [{}])[0]).get("delta") or {}
                        txt, rea = _extract(delta)
                        if txt:
                            chunks += 1
                            content.append(txt)
                            yield {"type": "delta", "text": txt, "model": m}
                        elif rea:
                            reasoning += len(rea)
        except LLMError:
            raise
        except Exception as e:
            last_err = e
            log.warning("llm stream failed on %s: %s", m, str(e)[:120])
            continue

        text = "".join(content)
        if text.strip():
            yield {
                "type": "done",
                "text": text,
                "model": m,
                "elapsed": round(time.time() - t0, 1),
                "chunks": chunks,
                "reasoning_len": reasoning,
            }
            return
        log.warning("llm %s returned empty content, fallback next", m)

    raise LLMError(f"所有模型均失败：{last_err}")


# ---------------------------------------------------------------- 非流式
def chat(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    timeout: Optional[int] = None,
) -> LLMResult:
    s = get_llm_settings()
    if not s.configured:
        raise LLMError("未配置 LLM 网关")
    st = get_settings()
    temperature = float(temperature if temperature is not None else st.ai.get("temperature", 0.7))
    timeout = int(timeout or s.llm_timeout or 360)
    models = [model] if model else s.model_chain
    attempts: List[str] = []
    last_err: Optional[Exception] = None

    for m in models:
        t0 = time.time()
        content, reasoning, chunks = [], 0, 0
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout, connect=30.0)) as c:
                with c.stream(
                    "POST", f"{s.base_url}/chat/completions",
                    json=_payload(m, messages, temperature, True), headers=_headers(),
                ) as r:
                    if r.status_code != 200:
                        body = r.read().decode("utf-8", "replace")[:200]
                        raise LLMError(f"HTTP {r.status_code} {body}")
                    for line in r.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            d = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        delta = ((d.get("choices") or [{}])[0]).get("delta") or {}
                        txt, rea = _extract(delta)
                        content.append(txt)
                        if rea:
                            reasoning += len(rea)
                        chunks += 1
        except Exception as e:
            last_err = e
            attempts.append(f"{m}: {type(e).__name__} {str(e)[:80]}")
            log.warning("llm chat failed on %s: %s", m, str(e)[:120])
            if not _is_timeout(e):
                continue
            continue

        text = "".join(content).strip()
        if text:
            return LLMResult(text=text, model=m, elapsed=round(time.time() - t0, 1),
                             reasoning_len=reasoning, attempts=attempts)
        attempts.append(f"{m}: empty content ({chunks} chunks)")
        log.warning("llm %s empty, next", m)

    raise LLMError(f"所有模型均失败：{last_err} | {attempts}")
