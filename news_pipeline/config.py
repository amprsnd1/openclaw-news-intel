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
        item.setdefault("id", str(item["name"]).strip().lower().replace(" ", "_").replace("/", "_"))
        item.setdefault("category", item.get("adapter", "rss"))
        item.setdefault("language", "unknown")
        item.setdefault("region", "global")
        item.setdefault("country", "")
        item.setdefault("access_mode", "public")
        item.setdefault("adapter", "rss")
        normalized.append(item)
    return normalized


def load_source_groups(path: Path = DEFAULT_SOURCES_FILE) -> Dict[str, Dict[str, Any]]:
    data = _read_yaml(path)
    raw_groups = data.get("source_groups", {}) or {}
    if not isinstance(raw_groups, dict):
        raise ConfigError("'source_groups' must be a map")

    groups: Dict[str, Dict[str, Any]] = {}
    for name, value in raw_groups.items():
        if isinstance(value, list):
            groups[str(name)] = {"description": "", "sources": value}
        elif isinstance(value, dict):
            sources = value.get("sources", [])
            if not isinstance(sources, list):
                raise ConfigError(f"source_groups.{name}.sources must be a list")
            groups[str(name)] = {
                "description": value.get("description", ""),
                "sources": sources,
            }
        else:
            raise ConfigError(f"source_groups.{name} must be a map or list")
    return groups


def load_source_quality(path: Path = DEFAULT_SOURCES_FILE) -> Dict[str, str]:
    data = _read_yaml(path)
    raw_quality = data.get("source_quality", {}) or {}
    if not isinstance(raw_quality, dict):
        raise ConfigError("'source_quality' must be a map")
    return {str(k): str(v) for k, v in raw_quality.items()}


def load_google_news_config(path: Path = DEFAULT_SOURCES_FILE) -> Dict[str, Any]:
    data = _read_yaml(path)
    cfg = data.get("google_news_rss", {}) or {}
    if not isinstance(cfg, dict):
        raise ConfigError("'google_news_rss' must be a map")
    return {
        "enabled": cfg.get("enabled", True),
        "max_queries_per_topic": int(cfg.get("max_queries_per_topic", 3)),
        "max_items_per_query": int(cfg.get("max_items_per_query", 20)),
        "timeout_seconds": int(cfg.get("timeout_seconds", 15)),
        "cache_ttl_minutes": int(cfg.get("cache_ttl_minutes", 60)),
        "user_agent": str(cfg.get("user_agent", "news-intel local research tool")),
    }


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


def load_gdelt_config(path: Path = DEFAULT_SOURCES_FILE) -> Dict[str, Any]:
    data = _read_yaml(path)
    cfg = data.get("gdelt", {}) or {}
    if not isinstance(cfg, dict):
        raise ConfigError("'gdelt' must be a map")
    return {
        "enabled": cfg.get("enabled", True),
        "max_queries_per_topic": int(cfg.get("max_queries_per_topic", 5)),
        "max_items_per_query": int(cfg.get("max_items_per_query", 20)),
        "timeout_seconds": int(cfg.get("timeout_seconds", 15)),
        "retry_count": int(cfg.get("retry_count", 2)),
        "backoff_seconds": int(cfg.get("backoff_seconds", 5)),
        "cache_ttl_minutes": int(cfg.get("cache_ttl_minutes", 60)),
        "min_delay_between_queries_seconds": int(cfg.get("min_delay_between_queries_seconds", 0)),
        "stop_on_first_rate_limit": bool(cfg.get("stop_on_first_rate_limit", True)),
    }


def get_enabled_sources(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [s for s in sources if s.get("enabled", True)]


def resolve_db_path() -> Path:
    db_env = os.getenv("NEWS_PIPELINE_DB", str(DEFAULT_DB_FILE))
    path = Path(db_env)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
