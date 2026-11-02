"""HSReplay 原始数据 -> 中文环境条目。

职责：
1. 解析 "[[dbfId,qty],...]" 卡表字符串；
2. 按卡组原型聚合出胜率、样本、占比、场均时长；
3. 原型名 / 职业名英译中；
4. 依据卡组节奏推断适配分段（免费数据无分段维度，用风格+胜率替代）；
5. 选代表性卡组并生成官方卡组码。
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from server.deckcode.codec import encode_deck_string
from server.deckcode.validate import analyze, hero_dbf_for
from server.logging_conf import get_logger

log = get_logger(__name__)

CLASS_CN = {
    "DEATHKNIGHT": "死亡骑士",
    "DEMONHUNTER": "恶魔猎手",
    "DRUID": "德鲁伊",
    "HUNTER": "猎人",
    "MAGE": "法师",
    "PALADIN": "圣骑士",
    "PRIEST": "牧师",
    "ROGUE": "潜行者",
    "SHAMAN": "萨满祭司",
    "WARLOCK": "术士",
    "WARRIOR": "战士",
}

# HSReplay 原型名里的职业写法（用于剥离后缀）
CLASS_DISPLAY = {
    "DEATHKNIGHT": "Death Knight", "DEMONHUNTER": "Demon Hunter", "DRUID": "Druid",
    "HUNTER": "Hunter", "MAGE": "Mage", "PALADIN": "Paladin", "PRIEST": "Priest",
    "ROGUE": "Rogue", "SHAMAN": "Shaman", "WARLOCK": "Warlock", "WARRIOR": "Warrior",
}

CLASS_SHORT = {
    "DEATHKNIGHT": "DK", "DEMONHUNTER": "瞎", "DRUID": "德", "HUNTER": "猎",
    "MAGE": "法", "PALADIN": "骑", "PRIEST": "牧", "ROGUE": "贼",
    "SHAMAN": "萨", "WARLOCK": "术", "WARRIOR": "战",
}

# 原型关键词英译中（按词命中，顺序敏感：长的优先）
KEYWORD_CN = [
    ("Aggro", "快攻"), ("Face", "打脸"), ("Zoo", "动物园"), ("Token", "铺场"),
    ("Pirate", "海盗"), ("Mech", "机械"), ("Beast", "野兽"), ("Murloc", "鱼人"),
    ("Dragon", "龙"), ("Elemental", "元素"), ("Undead", "亡灵"), ("Demon", "恶魔"),
    ("Naga", "纳迦"), ("Totem", "图腾"), ("Secret", "奥秘"), ("Handbuff", "手牌增益"),
    ("Questline", "任务线"), ("Quest", "任务"), ("Highlander", "宇宙"), ("Reno", "雷诺"),
    ("Raza", "拉扎"), ("Excavate", "发掘"), ("Starship", "星舰"), ("Imbue", "灌注"),
    ("Deathrattle", "亡语"), ("Discover", "发现"), ("Thief", "偷牌"), ("Burn", "烧"),
    ("Mill", "疲劳"), ("Fatigue", "疲劳"), ("Ramp", "跳费"), ("Big", "大哥"),
    ("Cycle", "循环"), ("Egg", "蛋"), ("Sludge", "泥浆"), ("Plague", "瘟疫"),
    ("Protoss", "星灵"), ("Zerg", "异虫"), ("Terran", "人族"), ("Wheel", "轮盘"),
    ("Control", "控制"), ("Combo", "组合技"), ("Midrange", "中速"), ("Tempo", "节奏"),
    ("OTK", "斩杀"), ("Even", "偶数"), ("Odd", "奇数"), ("Weapon", "武器"),
    ("Spell", "法术"), ("Silence", "沉默"), ("Discard", "弃牌"), ("Hostage", "控制"),
    ("XL", "XL"), ("Dungar", "邓加"), ("Wheel", "轮盘"), ("N'Zoth", "恩佐斯"),
    ("C'Thun", "克苏恩"), ("Yogg-Saron", "尤格萨隆"), ("Y'Shaarj", "亚煞极"),
    ("Cannon", "火炮"), ("Aura", "光环"), ("Menagerie", "动物园"), ("Hero", "英雄"),
    ("Location", "地标"), ("Colossal", "巨型"), ("Titan", "泰坦"), ("Forge", "锻造"),
    ("Archetype", "原型"),
]

STYLE_RULES = [
    (("快攻", "打脸", "铺场", "动物园", "海盗", "鱼人"), "aggro"),
    (("中速", "节奏", "图腾", "野兽"), "midrange"),
    (("控制", "宇宙", "雷诺", "疲劳", "泥浆", "星舰"), "control"),
    (("组合技", "斩杀", "循环", "任务线", "轮盘"), "combo"),
]
STYLE_CN = {"aggro": "快攻", "midrange": "中速", "control": "控制", "combo": "组合技"}

# 风格 -> 适配分段（免费数据无分段维度，用风格+胜率推断）
BUCKET_BY_STYLE = {
    "aggro": ["BRONZE_TO_SILVER", "GOLD_TO_PLATINUM"],
    "midrange": ["GOLD_TO_PLATINUM", "DIAMOND_TO_L5"],
    "control": ["DIAMOND_TO_L5", "LEGEND"],
    "combo": ["LEGEND", "TOP1000_LEGEND"],
}
NEXT_BUCKET = {
    "BRONZE_TO_SILVER": "GOLD_TO_PLATINUM",
    "GOLD_TO_PLATINUM": "DIAMOND_TO_L5",
    "DIAMOND_TO_L5": "LEGEND",
    "LEGEND": "TOP1000_LEGEND",
}

MIN_DECK_GAMES = 30       # 代表性卡组的最低样本
FAST_GAME_SEC = 420       # 快于该时长视为快攻
SLOW_GAME_SEC = 560       # 慢于该时长视为控制


def parse_deck_list(raw: str) -> List[Tuple[int, int]]:
    """'[[80647,2],[120985,1]]' -> [(80647,2),(120985,1)]"""
    if not raw:
        return []
    try:
        pairs = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    out: List[Tuple[int, int]] = []
    for p in pairs:
        try:
            dbf, qty = int(p[0]), int(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        if dbf > 0 and qty > 0:
            out.append((dbf, qty))
    return out


def translate_archetype(name_en: str, card_class: str) -> str:
    """英文名 -> 中文名；未命中的词原样保留，便于人工补表。

    例："C'Thun Demon Hunter" + DEMONHUNTER -> "克苏恩恶魔猎手"
    """
    cls = (card_class or "").upper()
    cls_disp = CLASS_DISPLAY.get(cls, cls.title())
    body = (name_en or "").strip()
    suffix = ""
    if body.lower().endswith(cls_disp.lower()):     # 先剥离职业后缀
        body = body[: -len(cls_disp)].strip()
        suffix = CLASS_CN.get(cls, cls_disp)
    elif body.lower().endswith(cls.lower()) and cls.lower() not in ("demonhunter", "deathknight"):
        body = body[: -len(cls)].strip()
        suffix = CLASS_CN.get(cls, cls)

    words = [w for w in re.split(r"[\s\-]+", body) if w]
    cn_words: List[str] = []
    for w in words:
        hit = next((cn for en, cn in KEYWORD_CN if w.lower() == en.lower()), None)
        cn_words.append(hit or w)

    out, prev_latin = "", False
    for w in cn_words + ([suffix] if suffix else []):
        latin = bool(re.search(r"[A-Za-z]", w))
        sep = " " if (prev_latin or latin) and out else ""
        out += sep + w
        prev_latin = latin
    return out or (name_en or "")


def guess_style(name_cn: str, avg_len: float) -> str:
    for keys, style in STYLE_RULES:
        if any(k in name_cn for k in keys):
            return style
    if avg_len <= 0:
        return "midrange"
    if avg_len < FAST_GAME_SEC:
        return "aggro"
    if avg_len >= SLOW_GAME_SEC:
        return "control"
    return "midrange"


def buckets_for(style: str, win_rate: float) -> List[str]:
    base = BUCKET_BY_STYLE.get(style, ["GOLD_TO_PLATINUM", "DIAMOND_TO_L5"])
    out = list(base)
    if win_rate >= 55.0:                    # 强势卡组再向上推一档
        extra = NEXT_BUCKET.get(base[-1])
        if extra and extra not in out:
            out.append(extra)
    return out


def _weighted(rows: List[Dict[str, Any]], key: str) -> float:
    total = sum(r.get("total_games", 0) for r in rows)
    if total <= 0:
        return 0.0
    return round(sum((r.get(key, 0) or 0) * r.get("total_games", 0) for r in rows) / total, 2)


def _pick_deck(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """选代表性卡组：样本够的看胜率，否则看热度。"""
    if not rows:
        return None
    qualified = [r for r in rows if r.get("total_games", 0) >= MIN_DECK_GAMES]
    pool = qualified or rows
    return max(pool, key=lambda r: (r.get("win_rate", 0) or 0) * math.log(r.get("total_games", 0) + 2))


def build_deck(cards: List[Tuple[int, int]], card_class: str, mode: str) -> Dict[str, Any]:
    """生成卡组码并做一次合法性校验；返回 {code, total, ok, issues}"""
    hero = hero_dbf_for(card_class)
    out: Dict[str, Any] = {"code": "", "total": 0, "ok": False, "issues": []}
    if hero is None or not cards:
        return out
    try:
        out["code"] = encode_deck_string(hero, cards, fmt=mode)
    except Exception as e:
        out["issues"].append(f"卡组码生成失败：{e}")
        return out
    try:
        res = analyze(cards, mode=mode, card_class=card_class)
        out["total"] = res.get("total", 0)
        out["ok"] = bool(res.get("ok"))
        out["issues"] = (res.get("errors") or [])[:3]
    except Exception as e:
        out["issues"].append(f"校验异常：{e}")
    return out


def aggregate(
    raw: Dict[str, Any],
    archetypes: Dict[int, Dict[str, Any]],
    *,
    mode: str = "standard",
    min_sample: int = 200,
    limit: int = 60,
) -> List[Dict[str, Any]]:
    """把 HSReplay 原始响应聚合成环境条目（按原型）。"""
    series = (raw or {}).get("series", {})
    data = series.get("data", {}) or {}
    as_of = raw.get("as_of")

    grouped: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
    total_games = 0
    for cls, rows in data.items():
        for r in rows or []:
            key = (cls, int(r.get("archetype_id") or 0))
            grouped[key].append(r)
            total_games += int(r.get("total_games") or 0)

    entries: List[Dict[str, Any]] = []
    for (cls, arch_id), rows in grouped.items():
        games = sum(int(r.get("total_games") or 0) for r in rows)
        if games < min_sample:
            continue
        win_rate = _weighted(rows, "win_rate")
        avg_len = _weighted(rows, "avg_game_length_seconds")
        arche = archetypes.get(arch_id) or {}
        name_en = arche.get("name") or f"Archetype {arch_id}"
        name_cn = translate_archetype(name_en, cls)
        style = guess_style(name_cn, avg_len)

        deck_row = _pick_deck(rows)
        deck_cards = parse_deck_list((deck_row or {}).get("deck_list", ""))
        deck = build_deck(deck_cards, cls, mode)

        entries.append({
            "archetype_id": arch_id,
            "name": name_cn,
            "name_en": name_en,
            "card_class": cls,
            "card_class_cn": CLASS_CN.get(cls, cls),
            "class_short": CLASS_SHORT.get(cls, cls),
            "win_rate": win_rate,
            "sample_size": games,
            "share": round(games / total_games * 100, 2) if total_games else 0.0,
            "avg_game_length": int(avg_len),
            "style": style,
            "style_cn": STYLE_CN.get(style, style),
            "buckets": buckets_for(style, win_rate),
            "deck_code": deck["code"],
            "deck_cards": deck_cards,
            "deck_total": deck["total"],
            "deck_valid": deck["ok"],
            "deck_issues": deck["issues"],
            "deck_games": int((deck_row or {}).get("total_games") or 0),
            "deck_win_rate": float((deck_row or {}).get("win_rate") or 0),
            "deck_id": (deck_row or {}).get("deck_id") or "",
            "deck_count": len(rows),
            "trend": 0.0,
            "as_of": as_of,
            "sources": "hsreplay",
        })

    entries.sort(key=lambda e: (-e["win_rate"], -e["sample_size"]))
    return entries[:limit]
