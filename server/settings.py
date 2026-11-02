"""全局配置读取：config/app.yaml + config/sets.yaml + 环境变量 / .env。

约定：
- 服务器行为（端口、源开关、分段档位）走 YAML，便于人工编辑；
- AI 凭证与模型走环境变量或根目录 .env，绝不写死在代码与 YAML 里。
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"


# ---------------------------------------------------------------- AI 凭证（来自环境）
class LLMSettings(BaseSettings):
    """OpenAI 兼容网关凭证与模型配置。

    注意：必须显式指定模型。网关的 model=auto 会被路由到只输出
    reasoning_content 的推理模型，导致 content 为空。
    """

    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_model_fallbacks: str = ""
    llm_timeout: int = 360

    @property
    def configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @property
    def base_url(self) -> str:
        return self.llm_base_url.rstrip("/")

    @property
    def model_chain(self) -> List[str]:
        chain = [m.strip() for m in [self.llm_model] if m.strip()]
        chain += [m.strip() for m in self.llm_model_fallbacks.split(",") if m.strip()]
        seen, out = set(), []
        for m in chain:
            if m not in seen:
                seen.add(m)
                out.append(m)
        return out


# ---------------------------------------------------------------- YAML 配置
def _load_yaml(name: str) -> Dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


class Bucket(BaseModel):
    id: str
    label: str
    order: int = 0


class Settings(BaseModel):
    root: Path = ROOT
    host: str = "0.0.0.0"
    port: int = 8765
    title: str = "炉石卡组构筑器"
    version: str = "0.1.0"
    data_dir: Path = ROOT / "data"
    db_file: Path = ROOT / "data" / "app.db"
    card_cache: Path = ROOT / "data" / "cards.zhCN.json"
    cardpool: Dict[str, Any] = Field(default_factory=dict)
    meta: Dict[str, Any] = Field(default_factory=dict)
    recommend: Dict[str, Any] = Field(default_factory=dict)
    ai: Dict[str, Any] = Field(default_factory=dict)
    buckets: List[Bucket] = Field(default_factory=list)
    excluded_sets: List[str] = Field(default_factory=list)
    standard_sets: List[str] = Field(default_factory=list)
    set_names: Dict[str, str] = Field(default_factory=dict)
    sets_version: str = ""


def _build_settings() -> Settings:
    app_yaml = _load_yaml("app.yaml")
    sets_yaml = _load_yaml("sets.yaml")

    server = app_yaml.get("server", {})
    paths = app_yaml.get("paths", {})
    root = ROOT

    def _p(key: str, default: str) -> Path:
        rel = paths.get(key, default)
        p = Path(rel)
        return p if p.is_absolute() else root / p

    data_dir = _p("data_dir", "data")
    db_file = _p("db_file", "data/app.db")
    card_cache = _p("card_cache", "data/cards.zhCN.json")

    # 测试用：允许通过环境变量把数据目录整体挪走
    alt = os.environ.get("HSDECK_DATA_DIR")
    if alt:
        data_dir = Path(alt)
        db_file = data_dir / "app.db"
        card_cache = data_dir / "cards.zhCN.json"

    return Settings(
        root=root,
        host=server.get("host", "0.0.0.0"),
        port=int(server.get("port", 8765)),
        title=server.get("title", "炉石卡组构筑器"),
        version=server.get("version", "0.1.0"),
        data_dir=data_dir,
        db_file=db_file,
        card_cache=card_cache,
        cardpool=app_yaml.get("cardpool", {}),
        meta=app_yaml.get("meta", {}),
        recommend=app_yaml.get("recommend", {}),
        ai=app_yaml.get("ai", {}),
        buckets=[Bucket(**b) for b in app_yaml.get("recommend", {}).get("buckets", [])],
        excluded_sets=sets_yaml.get("excluded", []) or [],
        standard_sets=sets_yaml.get("standard", []) or [],
        set_names=sets_yaml.get("set_names", {}) or {},
        sets_version=sets_yaml.get("version", ""),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = _build_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s


@lru_cache(maxsize=1)
def get_llm_settings() -> LLMSettings:
    return LLMSettings()


def reload_settings() -> None:
    """测试或热重载时使用。"""
    get_settings.cache_clear()
    get_llm_settings.cache_clear()


def ensure_utf8_stdio() -> None:
    """Windows 下把 stdout/stderr 重定向到文件/管道时，GBK 回退会因中文/符号
    抛 UnicodeEncodeError 直接崩服，这里统一兜底。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass
