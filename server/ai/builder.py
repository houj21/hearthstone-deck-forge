"""AI 工作流：自动构筑 / 换卡建议 / 卡组点评。

三条流水线的共同约束：
- 模型只能从候选池里选卡（提示词硬约束 + 本地复核）；
- 输出必须在本地重新校验，不过就把“具体错误”回喂模型重试（最多 max_repair 次）；
- 重试仍不过 -> 规则兜底，并标注 source=rules，界面如实告诉用户这是兜底结果。
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from server.ai import candidates as cand_mod
from server.ai import prompts, rules
from server.cardpool import service as cards
from server.deckcode.codec import encode_deck_string
from server.deckcode.validate import analyze, hero_dbf_for
from server.logging_conf import get_logger
from server.meta.normalizer import CLASS_CN
from server.settings import get_settings

log = get_logger(__name__)

LLMCallable = Callable[[List[Dict[str, str]], str], Awaitable[str]]

MODE_CN = {"standard": "标准", "wild": "狂野"}


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    return t


def _json_obj(text: str) -> Dict[str, Any]:
    t = _strip_fences(text)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", t)
        if not m:
            raise
        return json.loads(m.group(0))


def _resolve(names_qty: Sequence[Dict[str, Any]]) -> Tuple[List[Tuple[int, int]], List[str]]:
    """卡名 -> dbfId；返回 (entries, 不在卡池里的名字)。"""
    names = [str(c.get("name") or "").strip() for c in names_qty if isinstance(c, dict)]
    found = cards.find_by_names(names)
    entries: List[Tuple[int, int]] = []
    unknown: List[str] = []
    for c in names_qty:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        try:
            qty = int(c.get("qty", 1))
        except (TypeError, ValueError):
            qty = 1
        if not name or qty <= 0:
            continue
        card = found.get(name)
        if not card:
            unknown.append(name)
            continue
        entries.append((int(card["dbf_id"]), qty))
    return entries, unknown


def _deck_code(entries: List[Tuple[int, int]], card_class: str, mode: str) -> str:
    hero = hero_dbf_for(card_class)
    if hero is None or not entries:
        return ""
    try:
        return encode_deck_string(hero, entries, fmt=mode)
    except Exception as e:
        log.warning("encode failed: %s", e)
        return ""


def _view(entries: List[Tuple[int, int]], card_class: str, mode: str) -> Dict[str, Any]:
    by_dbf = cards.get_cards_by_dbf([d for d, _ in entries])
    items, total = [], 0
    for dbf, qty in entries:
        c = by_dbf.get(dbf)
        if not c:
            continue
        items.append({**c, "qty": qty})
        total += qty
    return {
        "cards": sorted([{k: i[k] for k in ("name", "cost", "qty", "rarity", "dbf_id", "type") if k in i}
                         for i in items], key=lambda x: (x.get("cost") or 0, x.get("name") or "")),
        "items": items,
        "total": total,
        "deck_code": _deck_code(entries, card_class, mode),
        "entries": entries,
    }


async def build(
    *,
    card_class: str,
    mode: str = "standard",
    intent: str = "",
    note: str = "",
    llm: Optional[LLMCallable] = None,
) -> Dict[str, Any]:
    """AI 自动构筑一套 30 张卡组。"""
    st = get_settings()
    cls = (card_class or "").upper()
    pool = cand_mod.build_candidates(card_class=cls, mode=mode)
    block = prompts.candidate_block(pool["items"], pool["heat"])
    intent_label = _intent_label(intent)
    messages = prompts.build_messages(
        card_class_cn=CLASS_CN.get(cls, cls),
        mode_cn=MODE_CN.get(mode, mode),
        intent_label=intent_label,
        note=note,
        candidates_block=block,
    )

    result: Dict[str, Any] = {
        "ok": False, "source": "rules", "model": "", "attempts": 0,
        "name": "", "plan": "", "errors": [], "llm_error": "",
        "candidates": len(pool["items"]),
        "card_class": cls, "mode": mode, "intent": intent,
    }

    if llm is not None:
        max_repair = int(st.ai.get("max_repair", 2))
        for attempt in range(max_repair + 1):
            result["attempts"] = attempt + 1
            try:
                text = await llm(messages, "build")
            except Exception as e:
                log.warning("build llm failed: %s", e)
                result["llm_error"] = f"模型调用失败：{str(e)[:120]}"
                break
            try:
                obj = _json_obj(text)
            except json.JSONDecodeError as e:
                result["errors"].append(f"输出不是合法 JSON（{e}）")
                messages = prompts.repair_messages(messages, result["errors"], prompts.BUILD_SCHEMA)
                continue

            raw_cards = obj.get("cards") or []
            entries, unknown = _resolve(raw_cards)
            errors: List[str] = []
            if unknown:
                errors.append(f"{len(unknown)} 个卡名不在卡池：{unknown[:4]}")
            analysis = analyze(entries, mode=mode, card_class=cls)
            errors += list(analysis.get("errors") or [])
            if not errors:
                view = _view(entries, cls, mode)
                result.update({
                    "ok": True, "source": "llm",
                    "name": str(obj.get("name") or f"{CLASS_CN.get(cls, cls)}构筑"),
                    "plan": str(obj.get("plan") or ""),
                    "errors": [], **view,
                    "analysis": analysis,
                })
                return result
            result["errors"] = errors
            messages = prompts.repair_messages(messages, errors, prompts.BUILD_SCHEMA)

    # 规则兜底
    entries = rules.fallback_build(pool["items"], heat=pool["heat"], intent=intent)
    analysis = analyze(entries, mode=mode, card_class=cls)
    view = _view(entries, cls, mode)
    result.update({
        "ok": bool(view["deck_code"]),
        "source": "rules",
        "name": f"{CLASS_CN.get(cls, cls)}（规则兜底）",
        "plan": "模型不可用或输出未通过校验，已按环境热度与曲线配比生成，可继续让 AI 微调。",
        **view,
        "analysis": analysis,
        "errors": list(analysis.get("errors") or []),
    })
    return result


async def suggest_swaps(
    *,
    card_class: str,
    mode: str = "standard",
    deck_entries: Sequence[Tuple[int, int]],
    target_name: str,
    intent: str = "",
    note: str = "",
    llm: Optional[LLMCallable] = None,
) -> Dict[str, Any]:
    """针对卡组里的一张卡给出替换建议。"""
    st = get_settings()
    cls = (card_class or "").upper()
    view = _view(list(deck_entries), cls, mode)
    target = next((i for i in view["items"] if i["name"] == target_name), None)
    result: Dict[str, Any] = {
        "ok": False, "source": "rules", "model": "", "attempts": 0,
        "target": target_name, "swaps": [], "note": "", "errors": [], "llm_error": "",
    }
    if not target:
        result["errors"].append(f"卡组里没有「{target_name}」这张卡")
        return result

    pool = cand_mod.build_candidates(card_class=cls, mode=mode)
    block = prompts.candidate_block(pool["items"], pool["heat"])
    messages = prompts.swap_messages(
        card_class_cn=CLASS_CN.get(cls, cls),
        mode_cn=MODE_CN.get(mode, mode),
        intent_label=_intent_label(intent),
        note=note,
        deck_block=cand_mod.deck_block(view["items"]),
        target=target_name,
        candidates_block=block,
    )

    if llm is not None:
        max_repair = int(st.ai.get("max_repair", 2))
        for attempt in range(max_repair + 1):
            result["attempts"] = attempt + 1
            try:
                text = await llm(messages, "swap")
            except Exception as e:
                result["llm_error"] = f"模型调用失败：{str(e)[:120]}"
                break
            try:
                obj = _json_obj(text)
            except json.JSONDecodeError as e:
                result["errors"].append(f"输出不是合法 JSON（{e}）")
                messages = prompts.repair_messages(messages, result["errors"], prompts.SWAP_SCHEMA)
                continue

            raw_swaps = obj.get("swaps") or []
            swaps, errors = _validate_swaps(raw_swaps, view["entries"], cls, mode, target_name, pool)
            if swaps:
                result.update({"ok": True, "source": "llm", "swaps": swaps,
                               "note": str(obj.get("note") or ""), "errors": []})
                return result
            result["errors"] = errors or ["模型没有给出可用的替换方案"]
            messages = prompts.repair_messages(messages, result["errors"], prompts.SWAP_SCHEMA)

    result.update({
        "ok": True, "source": "rules",
        "swaps": rules.fallback_swaps(view["items"], pool["items"], target=target,
                                      intent=intent, heat=pool["heat"]),
        "note": "（模型不可用，以下为规则兜底建议）",
    })
    return result


def _validate_swaps(
    raw_swaps: Sequence[Dict[str, Any]],
    entries: List[Tuple[int, int]],
    cls: str,
    mode: str,
    target_name: str,
    pool: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """逐个替换方案做本地校验：换上后必须仍是合法 30 张卡组。"""
    errors: List[str] = []
    out: List[Dict[str, Any]] = []
    pool_names = {c["name"]: c for c in pool["items"]}

    for s in raw_swaps:
        if not isinstance(s, dict):
            continue
        out_name = str(s.get("out") or "").strip() or target_name
        in_name = str(s.get("in") or "").strip()
        if not in_name:
            errors.append("替换方案缺少 in 卡名")
            continue
        if in_name not in pool_names and in_name not in cards.find_by_names([in_name]):
            errors.append(f"「{in_name}」不在候选卡池")
            continue
        if in_name == out_name:
            errors.append(f"替换卡与被换卡相同（{in_name}），等于没换")
            continue
        if _at_max_copies(entries, in_name):
            errors.append(f"「{in_name}」已经在卡组里且达到张数上限")
            continue
        new_entries = _apply_swap(entries, out_name, in_name)
        if new_entries is None:
            errors.append(f"「{out_name}」不在当前卡组里")
            continue
        analysis = analyze(new_entries, mode=mode, card_class=cls)
        if analysis.get("errors"):
            errors.append(f"换成「{in_name}」后：{analysis['errors'][0]}")
            continue
        out.append({
            "out": out_name,
            "in": in_name,
            "dbf_id": pool_names.get(in_name, {}).get("dbf_id"),
            "reason": str(s.get("reason") or ""),
            "deck_code": _deck_code(new_entries, cls, mode),
        })
    return out, errors


def _at_max_copies(entries: List[Tuple[int, int]], name: str) -> bool:
    """某张卡是否已在卡组里且达到张数上限（避免“换了等于没换”）。"""
    card = cards.find_by_names([name]).get(name)
    if not card:
        return False
    dbf, limit = int(card["dbf_id"]), (1 if card.get("rarity") == "LEGENDARY" else 2)
    return any(d == dbf and q >= limit for d, q in entries)


def _apply_swap(
    entries: List[Tuple[int, int]], out_name: str, in_name: str
) -> Optional[List[Tuple[int, int]]]:
    """把 out_name 换 1 张成 in_name（in 已在卡组时改为 +1，需满足张数上限）。"""
    by_dbf = cards.get_cards_by_dbf([d for d, _ in entries])
    name_to_dbf = {c["name"]: int(c["dbf_id"]) for c in by_dbf.values()}
    in_card = cards.find_by_names([in_name]).get(in_name)
    if not in_card:
        return None
    out_dbf = name_to_dbf.get(out_name)
    if out_dbf is None:
        return None

    cur = dict(entries)
    cur[out_dbf] = cur.get(out_dbf, 0) - 1
    if cur[out_dbf] <= 0:
        cur.pop(out_dbf)
    in_dbf = int(in_card["dbf_id"])
    max_qty = 1 if in_card.get("rarity") == "LEGENDARY" else 2
    cur[in_dbf] = min(max_qty, cur.get(in_dbf, 0) + 1)
    return [(d, q) for d, q in cur.items() if q > 0]


def review_messages(
    *,
    card_class: str,
    mode: str = "standard",
    deck_entries: Sequence[Tuple[int, int]],
) -> List[Dict[str, str]]:
    """卡组点评的提示词（正文走流式，不要求 JSON）。"""
    cls = (card_class or "").upper()
    view = _view(list(deck_entries), cls, mode)
    analysis = analyze(list(deck_entries), mode=mode, card_class=cls)
    return prompts.review_messages(
        card_class_cn=CLASS_CN.get(cls, cls),
        mode_cn=MODE_CN.get(mode, mode),
        deck_block=cand_mod.deck_block(view["items"]),
        stats_block=cand_mod.stats_block(analysis),
        meta_block=cand_mod.meta_block(cls),
    )


def _intent_label(intent: str) -> str:
    for i in prompts.intents():
        if i.get("id") == intent:
            return i.get("label", intent)
    return intent or "综合强度"
