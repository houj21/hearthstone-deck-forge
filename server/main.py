"""应用装配：生命周期、静态资源、路由、UTF-8 兜底。"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from server.db.base import init_db
from server.logging_conf import get_logger, setup_logging
from server.settings import ensure_utf8_stdio, get_settings

ensure_utf8_stdio()
log = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    st = get_settings()
    try:
        init_db()
    except Exception as e:  # 数据库异常不应阻止服务启动，前端显示降级状态
        log.error("init_db failed: %s", e)

    # 卡池预热：后台执行，避免首次请求被 3MB 卡表下载阻塞
    async def _warmup() -> None:
        try:
            from server.cardpool.service import ensure_cardpool

            await asyncio.to_thread(ensure_cardpool)
        except Exception as e:
            log.warning("cardpool warmup failed: %s", e)

    async def _warmup_meta() -> None:
        """环境数据预热：快照过期才抓，避免每次启动都开浏览器。"""
        try:
            from server.meta.service import ensure_fresh

            await asyncio.to_thread(ensure_fresh)
        except Exception as e:
            log.warning("meta warmup failed: %s", e)

    asyncio.create_task(_warmup())
    asyncio.create_task(_warmup_meta())
    log.info("%s starting on 0.0.0.0:%s (pid=%s)", st.title, st.port, os.getpid())
    yield
    log.info("server stopped")


def create_app() -> FastAPI:
    st = get_settings()
    app = FastAPI(title=st.title, version=st.version, lifespan=lifespan)

    from server.api.cards import router as cards_router
    from server.api.decks import router as decks_router
    from server.api.health import router as health_router
    from server.api.meta import router as meta_router
    from server.api.ai import router as ai_router
    from server.api.recommend import router as recommend_router

    app.include_router(health_router)
    app.include_router(ai_router)
    app.include_router(cards_router)
    app.include_router(decks_router)
    app.include_router(meta_router)
    app.include_router(recommend_router)

    # 后续阶段会陆续挂载 cards / decks / meta / recommend / ai
    # from server.api.cards import router as cards_router
    # app.include_router(cards_router)

    static_dir = WEB_DIR / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from fastapi.responses import FileResponse

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(str(WEB_DIR / "templates" / "index.html"))

    @app.middleware("http")
    async def _ensure_json_charset(request, call_next):
        """显式补 charset=utf-8：避免部分客户端按本地代码页猜编码导致中文乱码。"""
        response = await call_next(request)
        ctype = response.headers.get("content-type", "")
        if ctype.startswith("application/json") and "charset" not in ctype:
            response.headers["content-type"] = "application/json; charset=utf-8"
        return response

    @app.exception_handler(Exception)
    async def _unhandled(request, exc):  # pragma: no cover
        log.exception("unhandled error: %s", exc)
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    ensure_utf8_stdio()
    st = get_settings()
    uvicorn.run(app, host="0.0.0.0", port=st.port, log_level="info")
