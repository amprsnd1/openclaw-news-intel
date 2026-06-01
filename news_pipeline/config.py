from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import os

import yaml

def _detect_project_root() -> Path:
    env_root = os.getenv("NEWS_PIPELINE_ROOT")
    candidates = []
    if env_root:
        candidates.append(Path(env_root).expanduser().resolve())
    candidates.append(Path.cwd().resolve())
    candidates.append(Path(__file__).resolve().parent.parent)

    for candidate in candidates:
        if (candidate / "config" / "sources.yaml").exists():
            return candidate
    return candidates[-1]


PROJECT_ROOT = _detect_project_root()
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_SOURCES_FILE = CONFIG_DIR / "sources.yaml"
DEFAULT_WATCHLISTS_FILE = CONFIG_DIR / "watchlists.yaml"
DEFAULT_DB_FILE = DATA_DIR / "news.sqlite"


class ConfigError(RuntimeError):
    pass


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Invalid YAML root (expected map): {path}")
    return data


def load_sources(path: Path = DEFAULT_SOURCES_FILE) -> List[Dict[str, Any]]:
    data = _read_yaml(path)
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        raise ConfigError("'sources' must be a list")

    normalized = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        if "name" not in src:
            raise ConfigError("Every source must include 'name'")
        item = dict(src)
        item.setdefault("enabled", True)
        item.setdefault("type", "news")
        item.setdefault("language", "unknown")
        item.setdefault("region", "global")
        item.setdefault("country", "")
        item.setdefault("access_mode", "public")
        item.setdefault("adapter", "rss")
        normalized.append(item)
    return normalized


def load_watchlists(path: Path = DEFAULT_WATCHLISTS_FILE) -> List[Dict[str, Any]]:
    data = _read_yaml(path)
    watchlists = data.get("watchlists", [])
    if not isinstance(watchlists, list):
        raise ConfigError("'watchlists' must be a list")

    normalized = []
    for wl in watchlists:
        if not isinstance(wl, dict):
            continue
        item = dict(wl)
        item.setdefault("name", item.get("topic", "default"))
        item.setdefault("topic", item["name"])
        item.setdefault("keywords", [])
        item.setdefault("phrases", [])
        item.setdefault("sources", [])
        item.setdefault("date_from", None)
        item.setdefault("date_to", None)
        normalized.append(item)
    return normalized


def get_enabled_sources(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [s for s in sources if s.get("enabled", True)]


def resolve_db_path() -> Path:
    db_env = os.getenv("NEWS_PIPELINE_DB", str(DEFAULT_DB_FILE))
    path = Path(db_env)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
