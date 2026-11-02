"""SQLite 连接管理（WAL、行工厂、一次性建表）。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from server.logging_conf import get_logger
from server.settings import get_settings

log = get_logger(__name__)
_INITIALIZED = False


def db_path() -> Path:
    return get_settings().db_file


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db(force: bool = False) -> None:
    """建表 + 索引。幂等，进程启动调用一次。"""
    global _INITIALIZED
    if _INITIALIZED and not force:
        return

    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)

    conn = connect()
    try:
        from server.db.models import INDEXES, TABLES

        from server.db.models import MIGRATIONS

        for ddl in TABLES:
            conn.execute(ddl)
        for table, column, sql in MIGRATIONS:      # 旧库补列
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in cols:
                conn.execute(sql)
                log.info("migrated: %s.%s added", table, column)
        for ddl in INDEXES:
            conn.execute(ddl)
        conn.commit()
        log.info("database ready: %s", p)
    finally:
        conn.close()
    _INITIALIZED = True
