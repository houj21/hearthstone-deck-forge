"""从真实 HSReplay 响应里裁剪出小样本，生成测试 fixture。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = json.loads((ROOT / "data" / "probe" / "payload_2.json").read_text(encoding="utf-8"))
arch = json.loads((ROOT / "data" / "probe" / "payload_1.json").read_text(encoding="utf-8"))

data = src["series"]["data"]
keep = {}
ids = set()
for cls in ("DEATHKNIGHT", "MAGE", "ROGUE"):
    rows = data.get(cls, [])[:4]
    if rows:
        keep[cls] = rows
        for r in rows:
            ids.add(r.get("archetype_id"))

out = {
    "as_of": src.get("as_of"),
    "series": {"metadata": {c: {} for c in keep}, "data": keep},
}
archetypes = [a for a in arch if a.get("id") in ids]

dest = ROOT / "tests" / "fixtures"
(dest / "hsreplay_decks.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
(dest / "hsreplay_archetypes.json").write_text(json.dumps(archetypes, ensure_ascii=False, indent=1), encoding="utf-8")
print("classes:", list(keep), "decks:", sum(len(v) for v in keep.values()), "archetypes:", len(archetypes))
print("arch names:", [a["name"] for a in archetypes])
