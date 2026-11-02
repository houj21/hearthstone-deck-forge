"""pytest 公共夹具。

测试与开发数据隔离：通过环境变量 HSDECK_DATA_DIR 把 SQLite / 卡表缓存
指向临时目录，并使用 tests/fixtures 下的小样本卡表，避免联网与污染真实库。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP_DIR = ROOT / ".pytest_tmp"
# RUN_REAL_POOL_TESTS=1 时不做隔离，直接使用开发库跑真实卡组码集成用例
REAL_POOL = os.environ.get("RUN_REAL_POOL_TESTS") == "1"
if not REAL_POOL:
    os.environ["HSDECK_DATA_DIR"] = str(_TMP_DIR)
    _TMP_DIR.mkdir(exist_ok=True)

import pytest  # noqa: E402

from server.db.base import init_db  # noqa: E402
from server.settings import reload_settings  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "cards_sample.json"


@pytest.fixture(scope="session", autouse=True)
def _isolated_env():
    """清掉上一轮的库与缓存，重建干净数据库。"""
    if REAL_POOL:
        reload_settings()
        init_db()
        yield
        return
    for f in _TMP_DIR.glob("*"):
        try:
            if f.is_file():
                f.unlink()
            else:
                shutil.rmtree(f)
        except Exception:
            pass

    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    (_TMP_DIR / "cards.zhCN.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    reload_settings()
    init_db(force=True)
    yield


@pytest.fixture()
def payload():
    """HSReplay 真实响应裁剪样本（卡组 + 原型字典）。"""
    raw = json.loads((FIXTURE.parent / "hsreplay_decks.json").read_text(encoding="utf-8"))
    arch = json.loads((FIXTURE.parent / "hsreplay_archetypes.json").read_text(encoding="utf-8"))
    return raw, {int(a["id"]): a for a in arch}


@pytest.fixture()
def cardpool():
    """确保卡池已入库，返回 service 模块。"""
    from server.cardpool import service as cs

    if cs.card_count() == 0:
        cs.ingest()
    return cs
