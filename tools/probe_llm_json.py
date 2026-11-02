"""实测：模型能否按提示词稳定输出“可直接校验通过”的卡组 JSON。

这是 AI 自动构筑能不能用的关键验证，走的是真实代码路径（候选池 -> 提示词 -> 网关 -> 本地校验）。

用法：python tools/probe_llm_json.py [--class MAGE] [--models a,b]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.ai import candidates as cands            # noqa: E402
from server.ai import prompts                        # noqa: E402
from server.ai.client import chat, LLMError          # noqa: E402
from server.cardpool import service as cards         # noqa: E402
from server.deckcode.codec import encode_deck_string  # noqa: E402
from server.deckcode.validate import analyze, hero_dbf_for  # noqa: E402
from server.db.base import init_db                   # noqa: E402
from server.meta.normalizer import CLASS_CN          # noqa: E402
from server.settings import get_llm_settings         # noqa: E402


def strip_fences(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    return t


def validate_deck(obj: dict, card_class: str, mode: str) -> tuple[list[str], dict]:
    errors: list[str] = []
    raw_cards = obj.get("cards")
    if not isinstance(raw_cards, list) or not raw_cards:
        return ["输出缺少 cards 数组"], {}

    names = [str(c.get("name", "")).strip() for c in raw_cards if isinstance(c, dict)]
    found = cards.find_by_names(names)
    unknown = [n for n in names if n and n not in found]
    if unknown:
        errors.append(f"{len(unknown)} 个卡名不在卡池：{unknown[:5]}")

    entries, total = [], 0
    for c in raw_cards:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name", "")).strip()
        try:
            qty = int(c.get("qty", 1))
        except (TypeError, ValueError):
            qty = 1
        card = found.get(name)
        if card and qty > 0:
            entries.append((int(card["dbf_id"]), qty))
            total += qty
    if total != 30:
        errors.append(f"总张数 {total} != 30")

    res = analyze(entries, mode=mode, card_class=card_class)
    errors += res.get("errors") or []
    res["entries"] = entries
    return errors, res


def run(card_class: str, models: list[str], mode: str = "standard") -> None:
    init_db()
    cards.ensure_cardpool()
    pool = cands.build_candidates(card_class=card_class, mode=mode)
    print(f"候选池：{pool['source']}")
    msgs = prompts.build_messages(
        card_class_cn=CLASS_CN.get(card_class, card_class),
        mode_cn="标准" if mode == "standard" else "狂野",
        intent_label="更快（抢血/铺场）",
        note="",
        candidates_block=prompts.candidate_block(pool["items"], pool["heat"]),
    )
    print(f"提示词长度：{sum(len(m['content']) for m in msgs)} 字符\n" + "=" * 60)

    for m in models:
        t0 = time.time()
        try:
            r = chat(msgs, model=m, timeout=120)
        except LLMError as e:
            print(f"[{m}] 调用失败：{str(e)[:120]}")
            print("-" * 60)
            continue
        secs = round(time.time() - t0, 1)
        try:
            obj = json.loads(strip_fences(r.text))
        except json.JSONDecodeError as e:
            print(f"[{m}] {secs}s JSON 解析失败：{e}\n原始输出前 200 字：{r.text[:200]!r}")
            print("-" * 60)
            continue
        errors, res = validate_deck(obj, card_class, mode)
        hero = hero_dbf_for(card_class)
        code = encode_deck_string(hero, res.get("entries", []), fmt=mode) if hero and res.get("entries") else ""
        print(f"[{m}] {secs}s 模型耗时 {r.elapsed}s | 卡组名 {obj.get('name')!r}")
        print(f"[{m}] 张数 {res.get('total')} 尘 {res.get('dust_total')} | 卡组码 {code[:24]}…")
        print(f"[{m}] 校验：{'通过' if not errors else str(len(errors)) + ' 个问题 -> ' + '；'.join(errors[:4])}")
        print("-" * 60)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--class", dest="cls", default="MAGE")
    ap.add_argument("--mode", default="standard")
    ap.add_argument("--models", default="")
    a = ap.parse_args()
    s = get_llm_settings()
    models = [x.strip() for x in a.models.split(",") if x.strip()] or s.model_chain
    run(a.cls.upper(), models, a.mode)
