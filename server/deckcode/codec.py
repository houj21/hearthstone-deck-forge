"""官方卡组码（AAECA...）编解码 —— 纯 Python 实现，不依赖第三方库。

格式（HearthStone DeckString）：
    byte  0        : 保留字节 0x00
    byte  1        : 版本号 = 1
    byte  2        : 赛制 1=狂野 2=标准 3=经典
    byte  3        : 英雄数量 = 1
    varint x N     : 英雄卡 dbfId
    varint         : 单张牌数量
    varint x N     : 每张只带 1 张的卡 dbfId（升序）
    varint         : 双张牌数量
    varint x N     : 每张带 2 张的卡 dbfId（升序）
    varint         : 其它数量牌张数
    (varint dbfId, varint 数量) x N ：升序排列

整数采用 LEB128 变长编码。
"""

from __future__ import annotations

import base64
from typing import Dict, Iterable, List, Tuple

FORMAT_BY_ID = {1: "wild", 2: "standard", 3: "classic"}
FORMAT_ID_BY_NAME = {"wild": 1, "standard": 2, "classic": 3, "twist": 1}


class DeckCodeError(ValueError):
    pass


# ---------------------------------------------------------------- varint
def _read_varint(data: bytes, pos: int) -> Tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise DeckCodeError("卡组码不完整（varint 越界）")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            break
        shift += 7
        if shift > 63:
            raise DeckCodeError("varint 过长")
    return result, pos


def _write_varint(value: int) -> bytes:
    if value < 0:
        raise DeckCodeError("dbfId 不能为负数")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            byte |= 0x80
        out.append(byte)
        if not value:
            break
    return bytes(out)


# ---------------------------------------------------------------- 解码
def parse_deck_string(code: str) -> Dict[str, object]:
    """解析卡组码 -> {format, hero_dbf, cards: [(dbfId, qty)], unknown: [dbfId]}"""
    raw = (code or "").strip().replace("\r", "").replace("\n", "")
    if not raw:
        raise DeckCodeError("卡组码为空")

    # 容错：用户常从网页复制多余前缀，或粘贴成 URL
    if " " in raw:
        parts = [p for p in raw.split(" ") if p.startswith("AAE")]
        if parts:
            raw = parts[0]

    try:
        data = base64.b64decode(raw + "=" * (-len(raw) % 4))
    except Exception as e:
        raise DeckCodeError(f"卡组码不是合法 Base64：{e}") from e

    if len(data) < 5:
        raise DeckCodeError("卡组码长度不足")
    if data[0] != 0x00:
        raise DeckCodeError("卡组码头部异常（应为 0x00）")
    version = data[1]
    if version != 1:
        raise DeckCodeError(f"不支持的卡组码版本 {version}")

    fmt_id = data[2]
    fmt = FORMAT_BY_ID.get(fmt_id, "standard")

    pos = 3
    hero_count, pos = _read_varint(data, pos)
    heroes: List[int] = []
    for _ in range(hero_count):
        dbf, pos = _read_varint(data, pos)
        heroes.append(dbf)
    if not heroes:
        raise DeckCodeError("卡组码缺少英雄")

    cards: List[Tuple[int, int]] = []

    def read_group(qty: int) -> None:
        nonlocal pos
        count, pos = _read_varint(data, pos)
        for _ in range(count):
            dbf, pos = _read_varint(data, pos)
            cards.append((dbf, qty))

    read_group(1)
    read_group(2)

    # 数量不等于 1/2 的牌
    multi_count, pos = _read_varint(data, pos)
    for _ in range(multi_count):
        dbf, pos = _read_varint(data, pos)
        qty, pos = _read_varint(data, pos)
        cards.append((dbf, qty))

    return {
        "format": fmt,
        "hero_dbf": heroes[0],
        "heroes": heroes,
        "cards": sorted(cards, key=lambda x: x[0]),
    }


# ---------------------------------------------------------------- 编码
def encode_deck_string(
    hero_dbf: int,
    cards: Iterable[Tuple[int, int]],
    fmt: str = "standard",
) -> str:
    """把英雄 dbfId 与 [(dbfId, 数量)] 编码成官方卡组码。"""
    fmt_id = FORMAT_ID_BY_NAME.get(fmt, 2)

    singles = sorted(dbf for dbf, q in cards if q == 1)
    doubles = sorted(dbf for dbf, q in cards if q == 2)
    multis = sorted((dbf, q) for dbf, q in cards if q not in (1, 2) and q > 0)

    out = bytearray([0x00, 0x01, fmt_id])
    out += _write_varint(1)
    out += _write_varint(int(hero_dbf))

    out += _write_varint(len(singles))
    for dbf in singles:
        out += _write_varint(int(dbf))

    out += _write_varint(len(doubles))
    for dbf in doubles:
        out += _write_varint(int(dbf))

    out += _write_varint(len(multis))
    for dbf, q in multis:
        out += _write_varint(int(dbf))
        out += _write_varint(int(q))

    return base64.b64encode(bytes(out)).decode("ascii")
