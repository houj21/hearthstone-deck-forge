"""AI 教练层单测（隔离卡池）：JSON 提取、卡名解析、校验重试、规则兜底。"""

from __future__ import annotations

import json

import pytest

from server.ai import builder, rules
from server.cardpool import service as cards


def _pool(card_class: str = "MAGE", mode: str = "standard", page_size: int = 60):
    return cards.search_cards(card_class=card_class, mode=mode, page_size=page_size)["items"]


# ---------------------------------------------------------------- JSON 提取
def test_json_obj_plain():
    assert builder._json_obj('{"cards":[]}')["cards"] == []


def test_json_obj_strips_fences():
    text = '```json\n{"name":"快攻法","cards":[]}\n```'
    assert builder._json_obj(text)["name"] == "快攻法"


def test_json_obj_extracts_from_prose():
    text = '好的，这是我的方案：\n{"cards":[{"name":"火球术","qty":2}]}\n希望满意！'
    assert builder._json_obj(text)["cards"][0]["name"] == "火球术"


def test_json_obj_invalid_raises():
    with pytest.raises(json.JSONDecodeError):
        builder._json_obj("完全没有 JSON")


# ---------------------------------------------------------------- 卡名解析
def test_resolve_unknown_names(cardpool):
    entries, unknown = builder._resolve([{"name": "不存在的卡", "qty": 2}])
    assert entries == []
    assert unknown == ["不存在的卡"]


def test_resolve_maps_real_names(cardpool):
    items = _pool()
    if not items:
        pytest.skip("隔离卡池内无该职业卡")
    name = items[0]["name"]
    entries, unknown = builder._resolve([{"name": name, "qty": 2}])
    assert unknown == []
    assert entries and entries[0][1] == 2


def test_resolve_handles_bad_qty(cardpool):
    """qty=0 直接丢弃；qty 解析不出来时按 1 张（宁可少加，也不静默乱加）。"""
    items = _pool()
    if not items:
        pytest.skip("隔离卡池内无该职业卡")
    name = items[0]["name"]
    entries, _ = builder._resolve([{"name": name, "qty": 0}])
    assert entries == []
    entries, _ = builder._resolve([{"name": name, "qty": "x"}])
    assert entries == [(items[0]["dbf_id"], 1)]


# ---------------------------------------------------------------- 规则兜底
def test_fallback_build_respects_copies_and_size(cardpool):
    items = _pool(page_size=60)
    entries = rules.fallback_build(items)
    total = sum(q for _, q in entries)
    assert total <= 30
    by_dbf = {c["dbf_id"]: c for c in items}
    for dbf, qty in entries:
        rarity = by_dbf.get(dbf, {}).get("rarity")
        assert qty <= (1 if rarity == "LEGENDARY" else 2)
    assert len({d for d, _ in entries}) == len(entries), "同一张卡不应重复出现"


def test_fallback_swaps_excludes_deck_cards(cardpool):
    items = _pool(page_size=60)
    if len(items) < 3:
        pytest.skip("候选卡太少")
    target = items[0]
    deck = [{**items[1], "qty": 2}]
    swaps = rules.fallback_swaps(deck, items, target=target)
    assert swaps, "应给出兜底建议"
    deck_names = {c["name"] for c in deck}
    for s in swaps:
        assert s["in"] not in deck_names
        assert s["out"] == target["name"]
        assert s["reason"]


def test_stats_block_accepts_list_curve():
    """analyze() 的 curve 是按费用下标的列表，不是 dict（阶段⑦线上崩过一次）。"""
    from server.ai.candidates import stats_block

    txt = stats_block({"total": 30, "curve": [0, 4, 6, 5, 0, 0, 0, 0],
                       "dust_total": 3200, "errors": []})
    assert "1费4张" in txt and "2费6张" in txt and "3费5张" in txt
    assert "0费" not in txt, "0 张的费用段不该出现在统计里"


def test_curve_issues_accepts_list_curve():
    issues = rules.curve_issues({"total": 30, "curve": [0, 0, 1, 4, 5, 6, 7, 9]})
    assert any("低费" in i for i in issues)
    assert any("7 费以上" in i for i in issues)


def test_curve_issues_flags_empty_deck():
    issues = rules.curve_issues({"total": 0, "curve": {}})
    assert any("空" in i for i in issues)


def test_curve_issues_flags_wrong_size():
    issues = rules.curve_issues({"total": 28, "curve": {"1": 8, "2": 8, "3": 12}})
    assert any("30" in i for i in issues)


# ---------------------------------------------------------------- 工作流
@pytest.mark.asyncio
async def test_build_falls_back_when_llm_raises(cardpool):
    async def boom(messages, tag):
        raise RuntimeError("网关 502")

    res = await builder.build(card_class="MAGE", mode="standard", intent="faster", llm=boom)
    assert res["source"] == "rules"
    assert res["attempts"] == 1
    assert "网关 502" in res["llm_error"], "模型失败原因要保留给用户看"
    assert res["total"] > 0


@pytest.mark.asyncio
async def test_build_retries_then_succeeds(cardpool):
    """第一次给不存在的卡名 -> 回喂错误重试 -> 第二次给合法卡组。"""
    items = _pool(page_size=60)
    if len(items) < 16:
        pytest.skip("隔离卡池太小，无法凑满 30 张")

    def deck_json():
        entries = rules.fallback_build(items)
        by_dbf = {c["dbf_id"]: c for c in items}
        return json.dumps(
            {"name": "测试卡组", "plan": "思路", "cards": [
                {"name": by_dbf[d]["name"], "qty": q} for d, q in entries
            ]},
            ensure_ascii=False,
        )

    calls = {"n": 0}

    async def llm(messages, tag):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({"name": "错卡组", "plan": "", "cards": [
                {"name": "根本不存在的卡", "qty": 30}]}, ensure_ascii=False)
        return deck_json()

    res = await builder.build(card_class="MAGE", mode="standard", intent="", llm=llm)
    assert res["ok"], res["errors"]
    assert res["source"] == "llm"
    assert res["attempts"] == 2
    assert res["total"] == 30


@pytest.mark.asyncio
async def test_swap_requires_target_in_deck(cardpool):
    res = await builder.suggest_swaps(
        card_class="MAGE", mode="standard", deck_entries=[], target_name="某张卡", llm=None
    )
    assert res["ok"] is False
    assert "没有" in res["errors"][0]
