"""统一日志格式。严禁把 API Key / 完整请求体写进日志。"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


class NoSecretFilter(logging.Filter):
    """抹掉日志里可能混入的 key=... / sk-xxxx 片段。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        low = msg.lower()
        if "sk-" in msg or "api-key" in low or "apikey" in low or "authorization" in low:
            record.msg = "[redacted]"
            record.args = ()
        return True


def setup_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%H:%M:%S")
    )
    handler.addFilter(NoSecretFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
