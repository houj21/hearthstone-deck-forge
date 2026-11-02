"""AI 教练 API：全部走 SSE（网关长文本响应可达 200-330 秒，非流式必然超时）。

事件类型（前端按 type 分派）：
- status   阶段进度（挑卡/生成中/校验中/重试）
- delta    文本增量（点评流式正文；构筑场景用于回显思路）
- result   最终结果（含卡组码与校验结论）
- error    失败
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from server.ai import builder, client, prompts
from server.logging_conf import get_logger
from server.settings import get_llm_settings

log = get_logger(__name__)
router = APIRouter(prefix="/api/ai", tags=["ai"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",          # 关掉 Nginx 缓冲，否则流式会攒着不发
}


def _ev(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/status")
def status() -> Dict[str, Any]:
    s = get_llm_settings()
    return {
        "configured": s.configured,
        "base_url": s.base_url,
        "model": s.llm_model,
        "model_chain": s.model_chain,
        "intents": prompts.intents(),
    }


@router.get("/build")
async def build(
    card_class: str = Query("MAGE"),
    mode: str = Query("standard", pattern="^(standard|wild)$"),
    intent: str = "",
    note: str = "",
) -> StreamingResponse:
    return StreamingResponse(
        _build_events(card_class=card_class.upper(), mode=mode, intent=intent, note=note),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/swap")
async def swap(
    card_class: str = Query("MAGE"),
    mode: str = Query("standard", pattern="^(standard|wild)$"),
    deck_code: str = "",
    target: str = "",
    intent: str = "",
    note: str = "",
) -> StreamingResponse:
    return StreamingResponse(
        _swap_events(card_class=card_class.upper(), mode=mode, deck_code=deck_code,
                     target=target, intent=intent, note=note),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/review")
async def review(
    card_class: str = Query("MAGE"),
    mode: str = Query("standard", pattern="^(standard|wild)$"),
    deck_code: str = "",
) -> StreamingResponse:
    return StreamingResponse(
        _review_events(card_class=card_class.upper(), mode=mode, deck_code=deck_code),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# ---------------------------------------------------------------- 内部
def _entries_from_code(deck_code: str) -> List[Any]:
    from server.deckcode.codec import parse_deck_string

    if not deck_code:
        return []
    try:
        return parse_deck_string(deck_code)["cards"]
    except Exception as e:
        log.warning("deck code parse failed: %s", e)
        return []


async def _collect(messages: List[Dict[str, str]], on_progress) -> str:
    """调用网关并收集全文，同时把进度回调出去。"""
    buf: List[str] = []
    async for chunk in client.astream(messages):
        if chunk.get("type") == "delta":
            buf.append(chunk["text"])
            if len(buf) % 20 == 1:
                on_progress(f"模型输出中…（已接收 {sum(len(x) for x in buf)} 字）")
        elif chunk.get("type") == "model":
            on_progress(f"使用模型 {chunk.get('model')}")
    return "".join(buf)


async def _build_events(*, card_class: str, mode: str, intent: str, note: str) -> AsyncIterator[str]:
    yield _ev({"type": "status", "text": "正在挑选候选卡（优先环境在用）…"})

    progress: List[str] = []

    async def llm(messages: List[Dict[str, str]], tag: str) -> str:
        return await _collect(messages, progress.append)

    task = asyncio.create_task(
        builder.build(card_class=card_class, mode=mode, intent=intent, note=note, llm=llm)
    )
    while not task.done():
        while progress:
            yield _ev({"type": "status", "text": progress.pop(0)})
        await asyncio.sleep(0.5)
    while progress:
        yield _ev({"type": "status", "text": progress.pop(0)})

    try:
        res = task.result()
    except Exception as e:
        log.exception("ai build failed")
        yield _ev({"type": "error", "message": f"构筑失败：{e}"})
        return

    yield _ev({"type": "status", "text": "本地校验中…"})
    if res.get("plan"):
        yield _ev({"type": "delta", "text": f"【{res.get('name')}】\n{res['plan']}\n\n"})
    res.pop("items", None)
    res.pop("entries", None)
    yield _ev({"type": "result", **res})


async def _swap_events(
    *, card_class: str, mode: str, deck_code: str, target: str, intent: str, note: str
) -> AsyncIterator[str]:
    entries = _entries_from_code(deck_code)
    if not entries:
        yield _ev({"type": "error", "message": "当前卡组为空或卡组码无效"})
        return
    if not target:
        yield _ev({"type": "error", "message": "请先在组卡器里点一张卡作为换卡对象"})
        return

    yield _ev({"type": "status", "text": f"正在为「{target}」找替换…"})
    progress: List[str] = []

    async def llm(messages: List[Dict[str, str]], tag: str) -> str:
        return await _collect(messages, progress.append)

    task = asyncio.create_task(
        builder.suggest_swaps(
            card_class=card_class, mode=mode, deck_entries=entries,
            target_name=target, intent=intent, note=note, llm=llm,
        )
    )
    while not task.done():
        while progress:
            yield _ev({"type": "status", "text": progress.pop(0)})
        await asyncio.sleep(0.5)
    while progress:
        yield _ev({"type": "status", "text": progress.pop(0)})

    try:
        res = task.result()
    except Exception as e:
        log.exception("ai swap failed")
        yield _ev({"type": "error", "message": f"换卡建议失败：{e}"})
        return

    if res.get("errors"):
        yield _ev({"type": "status", "text": "；".join(res["errors"][:3])})
    for s in res.get("swaps", []):
        yield _ev({"type": "delta", "text": f"· {s['out']} → {s['in']}：{s.get('reason') or ''}\n"})
    yield _ev({"type": "result", **res})


async def _review_events(*, card_class: str, mode: str, deck_code: str) -> AsyncIterator[str]:
    entries = _entries_from_code(deck_code)
    if not entries:
        yield _ev({"type": "error", "message": "当前卡组为空或卡组码无效"})
        return
    messages = builder.review_messages(card_class=card_class, mode=mode, deck_entries=entries)
    yield _ev({"type": "status", "text": "正在点评…"})
    try:
        async for chunk in client.astream(messages):
            if chunk.get("type") == "delta":
                yield _ev({"type": "delta", "text": chunk["text"]})
            elif chunk.get("type") == "done":
                yield _ev({"type": "result", "text": chunk["text"], "model": chunk.get("model")})
    except Exception as e:
        log.exception("ai review failed")
        yield _ev({"type": "error", "message": str(e)[:200]})
