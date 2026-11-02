"""一次性工具：从官方 zhCN 卡表提取各职业的英雄卡 DBF 编号，生成 config/heroes.json。

用法：python tools/extract_heroes.py
（需要联网下载完整卡表；结果写入 config/heroes.json）
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
URL = "https://api.hearthstonejson.com/v1/latest/zhCN/cards.json"
CLASSES = [
    "MAGE", "WARRIOR", "WARLOCK", "PRIEST", "PALADIN", "HUNTER",
    "ROGUE", "DRUID", "SHAMAN", "DEMONHUNTER", "DEATHKNIGHT",
]

CACHE = Path(ROOT) / "data" / "cards.full.zhCN.json"


def load() -> list[dict]:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    print("downloading full card set ...")
    r = httpx.get(URL, timeout=120, follow_redirects=True)
    r.raise_for_status()
    CACHE.write_bytes(r.content)
    return r.json()


def main() -> None:
    cards = load()
    heroes: dict[str, list[dict]] = defaultdict(list)
    for c in cards:
        if c.get("type") != "HERO":
            continue
        cls = c.get("cardClass")
        if cls not in CLASSES:
            continue
        cid = str(c.get("id", ""))
        # 默认英雄的 id 形如 HERO_01..HERO_11；其余是皮肤或次级英雄，不参与卡组码
        if not re.fullmatch(r"HERO_\d+", cid):
            continue
        heroes[cls].append({
            "dbf": c["dbfId"],
            "id": cid,
            "name": c.get("name", ""),
            "set": c.get("set", ""),
            "cost": c.get("cost"),
            "collectible": bool(c.get("collectible")),
        })

    out: dict[str, dict] = {}
    for cls, items in heroes.items():
        if not items:
            continue
        # 优先：可收集的英雄卡（如塔维什），其次基础英雄（VANILLA/BASIC），再次 cost 最小最早出现的
        ranked = sorted(
            items,
            key=lambda x: (
                not x["collectible"],
                x["set"] not in {"VANILLA", "BASIC", "CORE"},
                x["cost"] if x["cost"] is not None else 99,
                x["dbf"],
            ),
        )
        pick = ranked[0]
        out[cls] = pick
        print(f"{cls:<12} {pick['dbf']:<8} {pick['id']:<12} {pick['name']}  (共 {len(items)} 个候选)")

    target = ROOT / "config" / "heroes.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {target}")


if __name__ == "__main__":
    main()
