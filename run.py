"""交互式一键启动脚本（纯 ASCII，避免 cmd 代码页乱码）。

用法：双击运行，或命令行执行 run.bat
功能：自动建 .venv(py -3.13) -> 装依赖 -> 打印局域网访问地址 -> 启动服务
"""

import hashlib
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PYEXE = VENV / "Scripts" / "python.exe"
PORT = 8765


def _print(*a):
    try:
        print(*a, flush=True)
    except UnicodeEncodeError:
        print(*[str(x).encode("ascii", "replace").decode() for x in a], flush=True)


def ensure_venv():
    if PYEXE.exists():
        return True
    _print("[1/3] Creating virtualenv with py -3.13 ...")
    r = subprocess.run([sys.executable, "-m", "venv", str(VENV)])
    if r.returncode != 0:
        r = subprocess.run(["py", "-3.13", "-m", "venv", str(VENV)])
    return PYEXE.exists()


def ensure_deps():
    """依赖装过就跳过；requirements.txt 一改自动重装（用内容哈希判断）。"""
    req = ROOT / "requirements.txt"
    marker = VENV / ".deps_ok"
    digest = hashlib.sha256(req.read_bytes()).hexdigest() if req.exists() else "none"
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == digest:
        return True
    _print("[2/3] Installing dependencies ...")
    r = subprocess.run(
        [str(PYEXE), "-m", "pip", "install", "-q", "-r", str(req)]
    )
    if r.returncode != 0:
        _print("pip install failed, please check network.")
        return False
    marker.write_text(digest, encoding="utf-8")
    return True


def wait_ready(timeout: int = 90) -> bool:
    for _ in range(timeout // 2):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2)
            return True
        except Exception:
            time.sleep(2)
    return False


def open_browser_when_ready():
    if os.environ.get("DECKFORGE_NO_BROWSER"):
        return

    def _open():
        if wait_ready():
            webbrowser.open(f"http://127.0.0.1:{PORT}")

    threading.Thread(target=_open, daemon=True).start()


def print_hints():
    if not (ROOT / ".env").exists():
        _print("  Hint: no .env found -> AI coach runs in rule-fallback mode")
        _print("        copy .env.example to .env and fill LLM_* to enable it")


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    if not ensure_venv():
        _print("Cannot create .venv. Please install Python 3.13 first.")
        sys.exit(1)
    if not ensure_deps():
        sys.exit(1)

    ip = lan_ip()
    _print("=" * 56)
    _print("  Hearthstone Deck Forge is starting")
    _print("  PC   : http://127.0.0.1:%d" % PORT)
    _print("  Phone: http://%s:%d   (same Wi-Fi)" % (ip, PORT))
    _print("=" * 56)
    print_hints()
    open_browser_when_ready()

    env = dict(os.environ)
    code = subprocess.run(
        [
            str(PYEXE), "-m", "uvicorn", "server.main:app",
            "--host", "0.0.0.0", "--port", str(PORT),
        ],
        cwd=str(ROOT),
        env=env,
    )
    sys.exit(code.returncode)


if __name__ == "__main__":
    main()
