"""推荐排序引擎单测（用真实样本裁剪出的快照）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.recommend import engine

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def snapshot(payload, cardpool, monkeypatch):
    """用样本生成一份环境快照，供推荐引擎消费。"""
    raw, arch = payload
    from server.meta.providers import hsreplay

    monkeypatch.setattr(hsreplay.HSReplayProvider, "fetch_raw", lambda self, w="current", timeout=30: raw)
    monkeypatch.setattr(hsreplay.HSReplayProvider, "fetch_archetypes", lambda self, timeout=30: list(arch.values()))
    monkeypatch.setattr(hsreplay.HSReplayProvider, "fetch_period", lambda self, timeout=30: {})
    from server.meta import service as meta_service

    res = meta_service.refresh(mode="standard")
    assert res["ok"]
    return res["snapshot_id"]


def test_recommend_basic(snapshot):
    out = engine.recommend()
    assert out["ok"], out
    assert out["items"], "样本足够时应有推荐"
    scores = [i["score"] for i in out["items"]]
    assert scores == sorted(scores, reverse=True)
    for it in out["items"]:
        assert it["deck_code"].startswith("AAECA")
        assert it["reason"], "每条推荐都要有理由"


def test_recommend_class_diversity(snapshot):
    from server.settings import get_settings

    max_per_class = int(get_settings().recommend.get("max_per_class", 2))
    out = engine.recommend(limit=20)
    counts: dict[str, int] = {}
    for it in out["items"]:
        counts[it["card_class"]] = counts.get(it["card_class"], 0) + 1
    assert all(c <= max_per_class for c in counts.values()), counts


def test_recommend_bucket_filter(snapshot):
    all_out = engine.recommend(limit=20)
    assert all_out["items"]
    bucket = all_out["items"][0]["buckets"][0]
    filtered = engine.recommend(bucket=bucket, limit=20)
    assert filtered["bucket_label"]
    for it in filtered["items"]:
        assert bucket in it["buckets"]


def test_recommend_class_filter(snapshot):
    out = engine.recommend(card_class="MAGE", limit=20)
    assert all(i["card_class"] == "MAGE" for i in out["items"])


def test_recommend_no_snapshot(monkeypatch, cardpool):
    """无快照时返回 ok=False，不抛异常（界面显示空态）。"""
    monkeypatch.setattr(engine.meta, "get_summary", lambda **k: {"ok": False, "message": "无快照", "entries": []})
    out = engine.recommend()
    assert out["ok"] is False
    assert out["items"] == []


def test_shrink_suppresses_small_sample():
    """同等胜率下，样本大的排在前面（收缩后分数更高）。"""
    prior = 50.0
    big = {"win_rate": 60.0, "sample_size": 5000}
    small = {"win_rate": 60.0, "sample_size": 200}
    assert engine._shrunk_score(big, prior, 500) > engine._shrunk_score(small, prior, 500)
