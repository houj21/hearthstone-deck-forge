"""本机真实浏览器内核（Edge/Chrome）抓取，用于绕过 Cloudflare 校验。

要点：
- Playwright 同步 API 只能在创建它的线程里使用，因此按线程隔离实例；
- 先访问站点首页拿到 CF 校验 Cookie，再用页面内 fetch 取接口 JSON（同源，自带 Cookie）；
- 每个线程一个浏览器，用完后关闭，避免进程泄漏。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from server.logging_conf import get_logger
from server.settings import get_settings

log = get_logger(__name__)

_tls = threading.local()
_lock = threading.RLock()

CANDIDATE_EXES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def find_executable() -> Optional[str]:
    for p in CANDIDATE_EXES:
        if Path(p).exists():
            return p
    return None


class Browser:
    """轻量封装：一个 page 走完“过校验 -> 取 JSON”的流程。"""

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self._pw = None
        self._browser = None
        self._page = None
        self.warmed: set[str] = set()

    # ---------------- 生命周期
    def start(self) -> None:
        if self._browser:
            return
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        kwargs: Dict[str, Any] = {"headless": self.headless}
        exe = find_executable()
        if exe:
            kwargs["executable_path"] = exe
        self._browser = self._pw.chromium.launch(**kwargs)
        ctx = self._browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=UA,
            locale="zh-CN",
        )
        self._page = ctx.new_page()
        log.debug("browser started (headless=%s, exe=%s)", self.headless, exe or "bundled")

    def close(self) -> None:
        for closer in (
            lambda: self._browser and self._browser.close(),
            lambda: self._pw and self._pw.stop(),
        ):
            try:
                closer()
            except Exception:
                pass
        self._browser = self._page = self._pw = None

    # ---------------- 行为
    def warm(self, url: str, timeout: int = 30) -> None:
        """访问站点首页完成 Cloudflare 校验。"""
        self.start()
        origin = "/".join(url.split("/")[:3])
        if origin in self.warmed:
            return
        resp = self._page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        self._page.wait_for_timeout(2500)
        self.warmed.add(origin)
        log.info("browser warmed: %s -> %s", origin, resp.status if resp else "?")

    def get_json(self, url: str, timeout: int = 30) -> Dict[str, Any]:
        """在页面上下文里 fetch 接口，返回 (status, body)。"""
        self.start()
        js = """
        async ([u, ms]) => {
          const ac = new AbortController();
          const t = setTimeout(() => ac.abort(), ms);
          try {
            const r = await fetch(u, {
              signal: ac.signal,
              credentials: 'omit',
              headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}
            });
            const txt = await r.text();
            return {status: r.status, body: txt};
          } catch (e) {
            return {status: 0, body: '', error: String(e)};
          } finally { clearTimeout(t); }
        }
        """
        raw = self._page.evaluate(js, [url, timeout * 1000])
        status = int(raw.get("status", 0))
        body = raw.get("body") or ""
        if status != 200:
            raise BrowserFetchError(f"HTTP {status} <- {url} {raw.get('error','')}".strip())
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            raise BrowserFetchError(f"响应不是 JSON：{url} ({e})") from e


class BrowserFetchError(RuntimeError):
    pass


def get_browser(headless: bool = True) -> Browser:
    """按线程复用浏览器实例。"""
    with _lock:
        b: Optional[Browser] = getattr(_tls, "browser", None)
        if b is None:
            b = Browser(headless=headless)
            _tls.browser = b
        return b


def close_browser() -> None:
    b: Optional[Browser] = getattr(_tls, "browser", None)
    if b is not None:
        b.close()
        _tls.browser = None


def browser_available() -> bool:
    """是否具备真实浏览器抓取能力（本机浏览器存在或已安装 playwright 内核）。"""
    if find_executable():
        return True
    try:
        import playwright  # noqa: F401

        return True
    except Exception:
        return False
