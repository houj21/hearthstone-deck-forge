"""环境数据层单测：解析、翻译、聚合、快照读写（数据源用裁剪后的真实样本）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.meta import service as meta_service
from server.meta.normalizer import (
    aggregate,
    buckets_for,
    guess_style,
    parse_deck_list,
    translate_archetype,
)

FIX = Path(__file__).parent / "fixtures"


def test_parse_deck_list():
    assert parse_deck_list("[[80647,2],[120985,1]]") == [(80647, 2), (120985, 1)]
    assert parse_deck_list("") == []
    assert parse_deck_list("not json") == []
    assert parse_deck_list("[[1,0],[0,2]]") == []


def test_translate_archetype():
    assert translate_archetype("Egg Priest", "PRIEST") == "蛋牧师"
    assert translate_archetype("C'Thun Demon Hunter", "DEMONHUNTER") == "克苏恩恶魔猎手"
    assert translate_archetype("Zoo Warlock", "WARLOCK").startswith("动物园")
    assert translate_archetype("Quest Warrior", "WARRIOR") == "任务战士"
    assert translate_archetype("Handbuff Death Knight", "DEATHKNIGHT") == "手牌增益死亡骑士"
    assert "原型" in translate_archetype("Archetype 6", "PRIEST")


def test_guess_style_and_buckets():
    assert guess_style("快攻战", 300) == "aggro"
    assert guess_style("控制牧", 700) == "control"
    assert guess_style("未知套路", 300) == "aggro"      # 按时长兜底
    assert guess_style("未知套路", 600) == "control"
    assert "BRONZE_TO_SILVER" in buckets_for("aggro", 50.0)
    assert len(buckets_for("aggro", 58.0)) == 3         # 高胜率再向上一档


def test_aggregate_entries(payload, cardpool):
    raw, arch = payload
    entries = aggregate(raw, arch, mode="standard", min_sample=1)
    assert entries, "样本足够时应产出条目"
    top = entries[0]
    assert top["win_rate"] > 0
    assert top["sample_size"] > 0
    assert top["card_class"] in {"DEATHKNIGHT", "MAGE", "ROGUE"}
    assert top["name"], "原型名不应为空"
    assert top["deck_code"].startswith("AAECA")
    assert 0 <= top["share"] <= 100
    # 按胜率降序
    rates = [e["win_rate"] for e in entries]
    assert rates == sorted(rates, reverse=True)


def test_aggregate_min_sample_filters_noise(payload, cardpool):
    raw, arch = payload
    all_entries = aggregate(raw, arch, mode="standard", min_sample=1)
    few = aggregate(raw, arch, mode="standard", min_sample=10 ** 9)
    assert len(few) == 0
    assert len(all_entries) >= 1


def test_snapshot_roundtrip(payload, cardpool, monkeypatch):
    """把样本聚合成条目后落快照，再读回来字段保持一致。"""
    raw, arch = payload
    entries = aggregate(raw, arch, mode="standard", min_sample=1)

    def fake_fetch(*a, **k):
        return raw

    def fake_arch(*a, **k):
        return list(arch.values())

    from server.meta.providers import hsreplay

    monkeypatch.setattr(hsreplay.HSReplayProvider, "fetch_raw", lambda self, w="current", timeout=30: raw)
    monkeypatch.setattr(hsreplay.HSReplayProvider, "fetch_archetypes", lambda self, timeout=30: list(arch.values()))
    monkeypatch.setattr(hsreplay.HSReplayProvider, "fetch_period", lambda self, timeout=30: {})

    res = meta_service.refresh(mode="standard")
    assert res["ok"], res
    assert res["entry_count"] == len(entries)

    summary = meta_service.get_summary(mode="standard")
    assert summary["ok"]
    assert len(summary["entries"]) == len(entries)
    first = summary["entries"][0]
    assert first["deck_code"].startswith("AAECA")
    assert first["name"] == entries[0]["name"]

    st = meta_service.status()
    assert st["snapshot"]["id"] == res["snapshot_id"]
    assert any(p["name"] == "hsreplay" and p["enabled"] for p in st["providers"])
    assert not any(p["name"] == "hsguru" and p["enabled"] for p in st["providers"])
