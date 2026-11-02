"""卡组码单元测试：真实官方卡组码往返 + 各类异常输入 + 卡组合法性校验。"""

from __future__ import annotations

import pytest

from server.deckcode.codec import DeckCodeError, encode_deck_string, parse_deck_string
from server.deckcode.validate import analyze, class_of_hero, hero_dbf_for, is_class_legal, rune_plan

# 真实样本：Hearthstone-Decks.net「Cycle Rogue #60 Legend - maxiebon1234」
REAL_CODE = "AAECAaIHBJegBNCeBr2+BqrqBg2RnwT2nwT3nwTfwwW/9wXI+wXungbZogatpwaQtAa2tQaY4Qbk6gYAAA=="


def test_parse_real_code():
    d = parse_deck_string(REAL_CODE)
    assert d["format"] == "standard"
    assert d["hero_dbf"] == 930                      # 瓦莉拉·萨古纳尔
    assert class_of_hero(930) == "ROGUE"
    assert sum(q for _, q in d["cards"]) == 30       # 30 张
    assert all(1 <= q <= 2 for _, q in d["cards"])
    assert sorted(d["cards"], key=lambda x: x[0]) == d["cards"]


def test_encode_decode_roundtrip():
    d = parse_deck_string(REAL_CODE)
    code = encode_deck_string(d["hero_dbf"], d["cards"], d["format"])
    again = parse_deck_string(code)
    assert again["hero_dbf"] == d["hero_dbf"]
    assert again["cards"] == d["cards"]
    assert again["format"] == d["format"]


def test_hero_map_covers_all_classes():
    from server.deckcode.validate import hero_map

    m = hero_map()
    assert set(m.keys()) == {
        "MAGE", "WARRIOR", "WARLOCK", "PRIEST", "PALADIN", "HUNTER",
        "ROGUE", "DRUID", "SHAMAN", "DEMONHUNTER", "DEATHKNIGHT",
    }
    for cls, info in m.items():
        assert hero_dbf_for(cls) == info["dbf_id"]


def test_encode_three_copies_group():
    """非 1/2 张的分组（如<｜hy_place▁holder▁no▁813｜>中的特殊情况）也要能正确往返。"""
    cards = [(1001, 3), (1002, 2), (1003, 1)]
    code = encode_deck_string(930, cards, "wild")
    got = parse_deck_string(code)
    assert dict(got["cards"]) == dict(cards)
    assert got["format"] == "wild"


def test_invalid_inputs():
    for bad in ["", "not-a-code", "@@@@", "AAECAf0GDo+4AqD9AwxIyggEBKoEDA", "AAAA"]:
        with pytest.raises(DeckCodeError):
            parse_deck_string(bad)


# ---------------------------------------------------------------- 校验
def test_analyze_size_and_copies(cardpool):
    # 1004 冰风雪人（中立普通）、1001 火球术：都允许 2 张，此处只有 4 张 -> 只提示还差多少
    too_few = [(1004, 2), (1001, 2)]
    res = analyze(too_few, mode="standard", card_class="MAGE")
    assert res["total"] == 4
    assert any("还差" in w for w in res["warnings"])
    assert not res["errors"]

    # 1005 大法师安东尼达斯是传说，只能带 1 张
    legendary_x2 = [(1005, 2), (1004, 2)]
    res = analyze(legendary_x2, mode="standard", card_class="MAGE")
    assert any("超过上限" in e for e in res["errors"])


def test_analyze_standard_and_class(cardpool):
    # 1010 远古雕文：EXPERT1 -> 狂野；且属于德鲁伊，若按法师校验会报职业不符
    res = analyze([(1010, 2)], mode="standard", card_class="MAGE")
    assert any("标准模式下不可使用" in e for e in res["errors"])
    assert any("不属于该职业" in e for e in res["errors"])

    res = analyze([(1010, 2)], mode="wild", card_class="DRUID")
    assert res["errors"] == []


def test_multi_class_card_allowed(cardpool):
    card = {"card_class": "NEUTRAL", "multi_class": "MAGE,DRUID"}
    assert is_class_legal(card, "MAGE")
    assert is_class_legal(card, "DRUID")
    assert not is_class_legal(card, "PRIEST")


def test_rune_plan():
    assert rune_plan([{"card_class": "DEATHKNIGHT", "runes": "鲜血鲜血"}]) == {"blood": 2, "frost": 0, "unholy": 0}
    impossible = rune_plan([
        {"card_class": "DEATHKNIGHT", "runes": "鲜血鲜血鲜血"},
        {"card_class": "DEATHKNIGHT", "runes": "冰霜冰霜冰霜"},
    ])
    assert impossible is None
    assert rune_plan([{"card_class": "MAGE"}]) == {"blood": 0, "frost": 0, "unholy": 0}


def test_unknown_dbf_reported(cardpool):
    res = analyze([(999999, 1)], mode="all")
    assert res["missing"] == [999999]
    assert any("不在卡池内" in e for e in res["errors"])
