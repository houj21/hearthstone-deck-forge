"""真实卡组码集成测试（需要真实卡池，默认跳过以加快单测）。

数据源：hearthstone-decks.net 发布的传说天梯卡组。
用途：
  1. 锁定 2026-10 标准轮换判断；
  2. 验证组卡型卡牌自带的衍生牌不会误报成"卡牌不存在"。

运行：set RUN_REAL_POOL_TESTS=1 && python -m pytest tests/test_real_decks.py -q
"""

from __future__ import annotations

import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_REAL_POOL_TESTS") != "1",
    reason="需要真实卡池；设置 RUN_REAL_POOL_TESTS=1 运行",
)

from server.cardpool import service as cards  # noqa: E402
from server.db.base import init_db  # noqa: E402
from server.deckcode.codec import parse_deck_string  # noqa: E402
from server.deckcode.validate import analyze  # noqa: E402

# 当前（2026-10）标准模式的传说卡组，均应校验通过且无缺失卡
STANDARD_DECKS = {
    "Raza Demon Hunter #1 (2026-10-23)": "AAECAea5AwTh+AWKqgeSqgeTqgcNzZ4Gzp4G054G3v8GtpcH4rEHkrIHkr8Hlb8H5eQHk+gHpvgHqf0HAAA=",
    "Egg Priest #38 (2026-10-25)": "AAECAa0GCPCfBMODB/WYB+ybB9edB7DJB4XrB9z7BwuFnwSFhgfFlAfgnQfksgeyxQevyQeT3wfV4Af04Afh+gcAAA==",
    "Pure Paladin #150 (2026-10-26)": "AAECAZ8FCJyfBLSBB7iyB+XBB5bUB53dB9fiB5f6BwvunwTP/gbLqQfErge+sgeDwgfc1QeZ3Qfx8Aev9geygAgAAQGa3Qed3QcAAA==",
}

# 2025-01 的标准卡组，如今应有卡退环境（正是用来锁定轮换边界的样本）
ROTATED_DECK = "AAECAaIHBJegBNCeBr2+BqrqBg2RnwT2nwT3nwTfwwW/9wXI+wXungbZogatpwaQtAa2tQaY4Qbk6gYAAA=="


@pytest.fixture(scope="module", autouse=True)
def real_pool():
    init_db()
    cards.ensure_cardpool()


@pytest.mark.parametrize("name,code", list(STANDARD_DECKS.items()))
def test_current_standard_decks_are_legal(name, code):
    res = analyze(parse_deck_string(code)["cards"], mode="standard")
    assert res["missing"] == [], f"{name} 有卡未识别：{res['missing']}"
    assert res["errors"] == [], f"{name} 校验失败：{res['errors']}"
    assert res["total"] == 30
    assert res["card_class"] in {"DEMONHUNTER", "PRIEST", "PALADIN"}


def test_token_cards_do_not_break_parsing():
    """塞纳留斯之斧 / 阿古斯传送门 属于组卡配件，不应被当成无效卡。"""
    res = analyze(parse_deck_string(STANDARD_DECKS["Raza Demon Hunter #1 (2026-10-23)"])["cards"],
                  mode="standard")
    assert res["missing"] == []
    assert any(t["name"] for t in res["tokens"]) if res["tokens"] else True


def test_old_deck_is_flagged_as_rotated():
    res = analyze(parse_deck_string(ROTATED_DECK)["cards"], mode="standard")
    assert not res["ok"]
    assert any("标准模式下不可使用" in e for e in res["errors"])

    # 同一个卡组在狂野下应当完全合法
    res_wild = analyze(parse_deck_string(ROTATED_DECK)["cards"], mode="wild")
    assert res_wild["ok"], res_wild["errors"]
