"""表结构与索引（SQLite）。所有表用 IF NOT EXISTS，幂等。"""

from __future__ import annotations

# ---------------------------------------------------------------- 卡池
T_CARDS = """
CREATE TABLE IF NOT EXISTS cards (
    dbf_id      INTEGER PRIMARY KEY,
    card_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    name_en     TEXT,
    cost        INTEGER,
    attack      INTEGER,
    health      INTEGER,
    durability  INTEGER,
    armor       INTEGER,
    type        TEXT,
    race        TEXT,
    races       TEXT,
    rarity      TEXT,
    card_class  TEXT,
    multi_class TEXT,
    card_set    TEXT,
    text        TEXT,
    keywords    TEXT,
    mechanics   TEXT,
    runes       TEXT,
    faction     TEXT,
    spell_school TEXT,
    collectible INTEGER DEFAULT 1,
    is_standard INTEGER DEFAULT 0,
    is_wild     INTEGER DEFAULT 1,
    image_url   TEXT,
    updated_at  TEXT
)
"""

T_CARD_SETS = """
CREATE TABLE IF NOT EXISTS card_sets (
    card_set   TEXT PRIMARY KEY,
    name_cn    TEXT,
    card_count INTEGER DEFAULT 0,
    is_standard INTEGER DEFAULT 0,
    updated_at TEXT
)
"""

T_CARD_TOKENS = """
CREATE TABLE IF NOT EXISTS card_tokens (
    dbf_id      INTEGER PRIMARY KEY,
    card_id     TEXT,
    name        TEXT,
    cost        INTEGER,
    type        TEXT,
    card_class  TEXT,
    card_set    TEXT,
    text        TEXT,
    updated_at  TEXT
)
"""

T_META_INFO = """
CREATE TABLE IF NOT EXISTS meta_info (
    key   TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
)
"""

# ---------------------------------------------------------------- 环境数据
T_META_ENTRY = """
CREATE TABLE IF NOT EXISTS meta_entry (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id    INTEGER,
    deck_name      TEXT NOT NULL,
    deck_name_en   TEXT,
    card_class     TEXT,
    archetype      TEXT,
    rank_bucket    TEXT,
    win_rate       REAL,
    sample_size    INTEGER,
    share          REAL,
    trend          REAL,
    deck_code      TEXT,
    cards_signature TEXT,
    confidence     REAL DEFAULT 0,
    sources        TEXT,
    source_count   INTEGER DEFAULT 1,
    note           TEXT,
    fetched_at     TEXT
)
"""

T_META_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS meta_snapshot (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT,
    mode        TEXT,
    entry_count INTEGER DEFAULT 0,
    source_status TEXT,
    is_current  INTEGER DEFAULT 0
)
"""

T_REFRESH_LOG = """
CREATE TABLE IF NOT EXISTS refresh_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    ended_at   TEXT,
    mode       TEXT,
    source     TEXT,
    status     TEXT,
    entry_count INTEGER DEFAULT 0,
    message    TEXT
)
"""

# ---------------------------------------------------------------- 我的卡组
T_SAVED_DECK = """
CREATE TABLE IF NOT EXISTS saved_deck (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    card_class TEXT,
    mode       TEXT,
    deck_code  TEXT,
    cards      TEXT,
    source     TEXT,
    created_at TEXT,
    updated_at TEXT
)
"""

# ---------------------------------------------------------------- 通用缓存
T_APP_CACHE = """
CREATE TABLE IF NOT EXISTS app_cache (
    cache_key  TEXT PRIMARY KEY,
    payload    TEXT,
    expires_at REAL,
    updated_at TEXT
)
"""

TABLES = [
    T_CARDS,
    T_CARD_SETS,
    T_CARD_TOKENS,
    T_META_INFO,
    T_META_ENTRY,
    T_META_SNAPSHOT,
    T_REFRESH_LOG,
    T_SAVED_DECK,
    T_APP_CACHE,
]

# 轻量迁移：给已有库补列（幂等，按 (表, 列) 判断）
MIGRATIONS = [
    ("meta_entry", "payload", "ALTER TABLE meta_entry ADD COLUMN payload TEXT"),
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_cards_class_cost ON cards(card_class, cost)",
    "CREATE INDEX IF NOT EXISTS idx_cards_set ON cards(card_set)",
    "CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name)",
    "CREATE INDEX IF NOT EXISTS idx_cards_standard ON cards(is_standard)",
    "CREATE INDEX IF NOT EXISTS idx_meta_entry_bucket ON meta_entry(rank_bucket)",
    "CREATE INDEX IF NOT EXISTS idx_meta_entry_snapshot ON meta_entry(snapshot_id)",
    "CREATE INDEX IF NOT EXISTS idx_meta_entry_class ON meta_entry(card_class)",
]
