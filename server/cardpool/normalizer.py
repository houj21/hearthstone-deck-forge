"""原始卡表 -> 统一 Card 结构（清洗、剔除非构筑系列、标注标准/狂野、关键词本地化）。"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from server.settings import get_settings

# 合成/分解尘数（普通版本）
DUST_COST = {
    "FREE": 0,
    "COMMON": 40,
    "RARE": 100,
    "EPIC": 400,
    "LEGENDARY": 1600,
}

# 关键词英文 -> 中文（用于筛选 chips）
KEYWORD_CN = {
    "BATTLECRY": "战吼",
    "DEATHRATTLE": "亡语",
    "TAUNT": "嘲讽",
    "DIVINE_SHIELD": "圣盾",
    "CHARGE": "冲锋",
    "RUSH": "突袭",
    "STEALTH": "潜行",
    "WINDFURY": "风怒",
    "LIFESTEAL": "吸血",
    "DISCOVER": "发现",
    "FREEZE": "冻结",
    "SILENCE": "沉默",
    "SECRET": "奥秘",
    "COMBO": "连击",
    "OVERLOAD": "过载",
    "SPELL_DAMAGE": "法术伤害",
    "AURA": "光环",
    "TRIGGER": "扳机",
    "INSPIRE": "激励",
    "DREDGE": "探底",
    "FORGE": "锻造",
    "MANATHIRST": "法力渴求",
    "REBORN": "复生",
    "POISONOUS": "剧毒",
    "FRENZY": "狂乱",
    "TOXIC": "剧毒",
    "START_OF_GAME": "战前准备",
    "MEGA_WINDFURY": "超级风怒",
    "CHOOSE_ONE": "抉择",
    "ADAPT": "进化",
    "QUEST": "任务",
    "SIDEQUEST": "支线任务",
    "CORRUPT": "腐化",
    "OUTCAST": "流放",
    "SPELLBURST": "法术迸发",
    "FRENZY_": "狂乱",
}

# 卡牌类型中文映射
TYPE_CN = {
    "MINION": "随从",
    "SPELL": "法术",
    "WEAPON": "武器",
    "HERO": "英雄",
    "LOCATION": "地点",
    "HERO_POWER": "英雄技能",
    "ENCHANTMENT": "附魔",
}

# 职业中文映射
CLASS_CN = {
    "MAGE": "法师",
    "WARRIOR": "战士",
    "WARLOCK": "术士",
    "PRIEST": "牧师",
    "PALADIN": "圣骑士",
    "HUNTER": "猎人",
    "ROGUE": "潜行者",
    "DRUID": "德鲁伊",
    "SHAMAN": "萨满祭司",
    "DEMONHUNTER": "恶魔猎手",
    "DEATHKNIGHT": "死亡骑士",
    "NEUTRAL": "中立",
}

RARITY_CN = {
    "FREE": "基础",
    "COMMON": "普通",
    "RARE": "稀有",
    "EPIC": "史诗",
    "LEGENDARY": "传说",
}

RUNE_CN = {"blood": "鲜血", "frost": "冰霜", "unholy": "邪恶"}

CARD_BACK_BASE = "https://art.hearthstonejson.com/v1/render/latest/zhCN/256x/{id}.png"


def _str(v: Any) -> Optional[str]:
    return None if v is None else str(v)


def _join(v: Any) -> Optional[str]:
    if isinstance(v, list):
        return ",".join(str(x) for x in v if x is not None)
    return None


def _runes(raw: Dict[str, Any]) -> Optional[str]:
    rc = raw.get("runeCost")
    if not isinstance(rc, dict):
        return None
    parts = []
    for key in ("blood", "frost", "unholy"):
        n = int(rc.get(key, 0) or 0)
        if n:
            parts.append(RUNE_CN[key] * n)
    return "".join(parts) or None


def normalize_card(raw: Dict[str, Any], standard_sets: Iterable[str]) -> Dict[str, Any]:
    """单条原始数据 -> 入库结构。"""
    std = set(standard_sets)
    card_set = raw.get("set") or ""
    card_class = raw.get("cardClass") or ""
    classes = raw.get("classes") or []

    mechanics = raw.get("mechanics") or []
    keywords_cn = sorted({KEYWORD_CN[m] for m in mechanics if m in KEYWORD_CN})

    text = raw.get("text") or ""
    card_type = raw.get("type") or ""

    return {
        "dbf_id": int(raw["dbfId"]),
        "card_id": raw.get("id") or "",
        "name": raw.get("name") or "",
        "cost": raw.get("cost"),
        "attack": raw.get("attack"),
        "health": raw.get("health"),
        "durability": raw.get("durability"),
        "armor": raw.get("armor"),
        "type": card_type,
        "type_cn": TYPE_CN.get(card_type, card_type),
        "race": raw.get("race"),
        "races": _join(raw.get("races")),
        "rarity": raw.get("rarity"),
        "rarity_cn": RARITY_CN.get(raw.get("rarity"), raw.get("rarity")),
        "card_class": card_class,
        "class_cn": CLASS_CN.get(card_class, card_class),
        "multi_class": _join(classes),
        "card_set": card_set,
        "text": text,
        "text_plain": _strip_tags(text),
        "keywords": _join(keywords_cn),
        "mechanics": _join(mechanics),
        "runes": _runes(raw),
        "spell_school": raw.get("spellSchool"),
        "collectible": 1 if raw.get("collectible") else 0,
        "dust_cost": DUST_COST.get(raw.get("rarity"), 0),
        "is_standard": 1 if card_set in std else 0,
        "is_wild": 1,
        "set_is_standard": 1 if card_set in std else 0,
        "image_url": CARD_BACK_BASE.format(id=raw.get("id")),
    }


def _strip_tags(html: str) -> str:
    import re

    if not html:
        return ""
    return re.sub(r"<[^>]+>", "", html).replace("\n", " ").strip()


def is_playable(raw: Dict[str, Any], excluded: Iterable[str]) -> bool:
    """是否进入构筑卡池：排除英雄皮肤、核心隐藏副本、战棋/佣兵等非构筑内容。"""
    if raw.get("set") in set(excluded):
        return False
    if not raw.get("collectible"):
        return False
    if raw.get("type") in {"ENCHANTMENT", "HERO_POWER", "MOVE_MINION_HOVER_TARGET"}:
        return False
    if not raw.get("name"):
        return False
    # 英雄皮肤/id 以 HERO_ 开头者剔除
    if str(raw.get("id", "")).startswith("HERO_"):
        return False
    return True


def names_by_dbf(raw_cards: List[Dict[str, Any]]) -> Dict[int, str]:
    return {int(c["dbfId"]): c.get("name", "") for c in raw_cards if "dbfId" in c}


def std_sets() -> List[str]:
    return list(get_settings().standard_sets)
