"""AI 端到端（真实卡池）：模拟网关输出，验证本地校验链路与卡组码闭环。

默认跳过；需要真实卡池时：RUN_REAL_POOL_TESTS=1 pytest tests/test_ai_real.py
"""

from __future__ import annotations

import json
import os

import pytest

from server.ai import builder, rules
from server.ai import candidates as cand_mod

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_REAL_POOL_TESTS") != "1",
    reason="需要真实卡池（RUN_REAL_POOL_TESTS=1）",
)


def _deck_payload(pool: dict) -> tuple[str, list]:
    entries = rules.fallback_build(pool["items"], heat=pool["heat"])
    by_dbf = {int(c["dbf_id"]): c for c in pool["items"]}
    cards = [{"name": by_dbf[d]["name"], "qty": q} for d, q in entries if d in by_dbf]
    return json.dumps({"name": "快攻法", "plan": "低费铺场接直伤", "cards": cards},
                      ensure_ascii=False), entries


async def test_build_with_fake_model_output():
    pool = cand_mod.build_candidates(card_class="MAGE", mode="standard")
    payload, _ = _deck_payload(pool)

    async def llm(messages, tag):
        return payload

    res = await builder.build(card_class="MAGE", mode="standard", intent="faster", llm=llm)
    assert res["ok"], res["errors"]
    assert res["source"] == "llm"
    assert res["total"] == 30
    assert not res["analysis"]["errors"]
    assert res["deck_code"].startswith("AAECA")


async def test_build_rejects_hallucinated_card_names():
    """模型编造卡名 -> 第一次失败并回喂错误，第二次给对才算通过。"""
    pool = cand_mod.build_candidates(card_class="MAGE", mode="standard")
    payload, _ = _deck_payload(pool)
    calls = {"n": 0}

    async def llm(messages, tag):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({"name": "假卡组", "plan": "", "cards": [
                {"name": "完全编造的卡", "qty": 30}]}, ensure_ascii=False)
        return payload

    res = await builder.build(card_class="MAGE", mode="standard", llm=llm)
    assert res["ok"], res["errors"]
    assert res["attempts"] == 2, "应先失败并被回喂修正"
    assert res["total"] == 30


async def test_swap_with_fake_model_output():
    pool = cand_mod.build_candidates(card_class="MAGE", mode="standard")
    _, entries = _deck_payload(pool)
    by_dbf = {int(c["dbf_id"]): c for c in pool["items"]}
    target = by_dbf[entries[2][0]]
    in_deck = {d for d, _ in entries}

    # 选一张不在卡组、费用相近的卡作为替换
    repl = next(
        (c for c in pool["items"]
         if int(c["dbf_id"]) not in in_deck
         and abs(int(c["cost"] or 0) - int(target["cost"] or 0)) <= 1),
        None,
    )
    assert repl is not None, "候选池里应有可替换的卡"

    payload = json.dumps({"swaps": [
        {"out": target["name"], "in": repl["name"], "reason": "曲线更顺"}],
        "note": "测试"}, ensure_ascii=False)

    async def llm(messages, tag):
        return payload

    res = await builder.suggest_swaps(
        card_class="MAGE", mode="standard", deck_entries=entries,
        target_name=target["name"], intent="faster", llm=llm,
    )
    assert res["ok"], res["errors"]
    assert res["source"] == "llm"
    assert res["swaps"] and res["swaps"][0]["in"] == repl["name"]
    assert res["swaps"][0]["deck_code"].startswith("AAECA")


async def test_swap_rejects_illegal_replacement():
    """替换后张数/传说限制不合法时，该方案必须被本地校验挡下。"""
    pool = cand_mod.build_candidates(card_class="MAGE", mode="standard")
    _, entries = _deck_payload(pool)
    by_dbf = {int(c["dbf_id"]): c for c in pool["items"]}
    target = by_dbf[entries[0][0]]
    in_deck = {d for d, _ in entries}
    legendary = next(
        (c for c in pool["items"]
         if c.get("rarity") == "LEGENDARY" and int(c["dbf_id"]) in in_deck),
        None,
    )
    if legendary is None:
        pytest.skip("候选池里没有已在卡组中的传说卡")

    payload = json.dumps({"swaps": [
        {"out": target["name"], "in": legendary["name"], "reason": "试试"}], "note": ""},
        ensure_ascii=False)

    async def llm(messages, tag):
        return payload

    res = await builder.suggest_swaps(
        card_class="MAGE", mode="standard", deck_entries=entries,
        target_name=target["name"], llm=llm,
    )
    assert res["source"] == "rules", "非法替换应被挡下并回退到规则兜底"
    assert res["swaps"], "兜底仍要给出可用建议"
