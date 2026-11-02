"""健康检查与运行信息。"""

from __future__ import annotations

import os
import socket
import sqlite3
from datetime import datetime

from fastapi import APIRouter

from server.db.base import db_path
from server.logging_conf import get_logger
from server.settings import get_llm_settings, get_settings

log = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["health"])


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@router.get("/health")
def health():
    """进程/数据库/AI 配置状态，前端据此显示顶部状态条。"""
    st = get_settings()
    llm = get_llm_settings()

    db_ok, card_count, set_count = True, 0, 0
    try:
        conn = sqlite3.connect(db_path(), timeout=5.0)
        conn.row_factory = sqlite3.Row
        card_count = conn.execute("SELECT COUNT(*) c FROM cards").fetchone()["c"]
        set_count = conn.execute("SELECT COUNT(*) c FROM card_sets").fetchone()["c"]
        conn.close()
    except Exception as e:  # 数据库未初始化时不应 500
        db_ok = False
        log.warning("db check failed: %s", e)

    return {
        "status": "ok" if db_ok else "degraded",
        "app": st.title,
        "version": st.version,
        "time": datetime.now().isoformat(timespec="seconds"),
        "db": {"ok": db_ok, "path": str(db_path()), "cards": card_count, "sets": set_count},
        "sets_config_version": st.sets_version,
        "ai": {
            # 只有 True/False，不返回任何凭证
            "configured": llm.configured,
            "models": llm.model_chain,
            "stream": bool(st.ai.get("stream", True)),
        },
        "access": {
            "local": f"http://127.0.0.1:{st.port}",
            "lan": f"http://{lan_ip()}:{st.port}",
            "pid": os.getpid(),
        },
    }
