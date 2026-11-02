"""卡池层单元测试：清洗规则、模式过滤、职业/费用/关键词检索、按名精确匹配。"""

from __future__ import annotations


def _names(cs, **kw):
    return [c["name"] for c in cs.search_cards(**kw)["items"]]


def test_ingest_excludes_non_playable(cardpool):
    """英雄皮肤、不可收集卡、乱斗卡应被剔除。"""
    all_names = _names(cardpool, mode="all", page_size=300)
    assert "吉安娜·普罗德摩尔" not in all_names
    assert "乱斗玩意" not in all_names
    assert "绵羊" not in all_names          # collectible 缺失 -> 令牌类不入池

    sets = {s["set"] for s in cardpool.list_sets()}
    assert "HERO_SKINS" not in sets
    assert "TB" not in sets


def test_core_hidden_playable_and_deduped(cardpool):
    """回归：CORE_HIDDEN 里藏着唯一可用版本，不能整体剔除；同名卡要去重。"""
    all_names = _names(cardpool, mode="all", page_size=300)
    assert "隐藏副本卡" in all_names

    hits = [c for c in cardpool.search_cards(q="火球术", mode="all", page_size=50)["items"]
            if c["name"] == "火球术"]
    assert len(hits) == 1                    # CORE / CORE_HIDDEN / LEGACY 只保留一张
    assert hits[0]["card_set"] == "CORE"


def test_standard_and_wild_split(cardpool):
    std = cardpool.search_cards(mode="standard", page_size=200)
    wild = cardpool.search_cards(mode="wild", page_size=200)
    allc = cardpool.search_cards(mode="all", page_size=200)
    assert std["total"] < allc["total"]
    assert wild["total"] == allc["total"]            # 狂野包含标准
    std_names = [c["name"] for c in std["items"]]
    assert "远古雕文" not in std_names               # EXPERT1 属狂野
    assert "火球术（LEGACY）" not in "".join(std_names)


def test_class_filter_includes_neutral_and_multi(cardpool):
    res = cardpool.search_cards(card_class="MAGE", mode="standard", page_size=200)
    names = [c["name"] for c in res["items"]]
    assert "火球术" in names
    assert "冰风雪人" in names                       # 中立
    assert "跨界学者" in names                       # 法师/德鲁伊多职业
    assert "虚空之光" not in names                   # 牧师专属
    for c in res["items"]:
        assert c["card_class"] == "MAGE" or c["card_class"] == "NEUTRAL" or c["multi_class"]


def test_cost_and_rarity_filter(cardpool):
    r = cardpool.search_cards(card_class="MAGE", mode="standard", costs=[4], page_size=50)
    assert {c["cost"] for c in r["items"]} == {4}

    r = cardpool.search_cards(mode="all", rarities=["LEGENDARY"], page_size=50)
    assert r["total"] == 1                            # 传说皮肤已被剔除，只剩安东尼达斯
    assert r["items"][0]["dust_cost"] == 1600


def test_keyword_and_text_search(cardpool):
    r = cardpool.search_cards(mode="all", keyword="战吼", page_size=50)
    names = [c["name"] for c in r["items"]]
    assert "翡翠巨兽" in names
    assert "火球术" not in names

    r = cardpool.search_cards(mode="all", q="发现", page_size=50)
    assert any("跨界学者" == n for n in [c["name"] for c in r["items"]])


def test_find_by_names_and_dbf(cardpool):
    hit = cardpool.find_by_names(["火球术"])
    assert "火球术" in hit
    assert hit["火球术"]["card_class"] == "MAGE"

    by_dbf = cardpool.get_cards_by_dbf([1001, 1007])
    assert set(by_dbf.keys()) == {1001, 1007}
    assert by_dbf[1007]["card_set"] == "EMERALD_DREAM"


def test_runes_and_dust(cardpool):
    dk = cardpool.get_cards_by_dbf([1009])[1009]
    assert dk["runes"] == "鲜血鲜血"
    assert dk["dust_cost"] == 100                     # 稀有 100 尘

    epic = cardpool.get_cards_by_dbf([1007])[1007]
    assert epic["dust_cost"] == 400


def test_pagination(cardpool):
    p1 = cardpool.search_cards(mode="all", sort="name", page=1, page_size=3)
    p2 = cardpool.search_cards(mode="all", sort="name", page=2, page_size=3)
    assert len(p1["items"]) == 3
    assert {c["dbf_id"] for c in p1["items"]}.isdisjoint({c["dbf_id"] for c in p2["items"]})
    assert p1["total"] == p2["total"]
