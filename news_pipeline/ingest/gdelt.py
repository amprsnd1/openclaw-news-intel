from __future__ import annotations

import importlib.util
from typing import Any, Dict, List
from typing import Optional, Tuple
import time

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"


def _build_query(source_cfg: Dict[str, Any], topic_watchlist: Optional[Dict[str, Any]] = None, days: int = 3) -> str:
    domains = source_cfg.get("domains") or []
    base_terms = []
    if domains:
        base_terms.append("(" + " OR ".join(f"domain:{d}" for d in domains) + ")")

    topic_terms: List[str] = []
    if topic_watchlist:
        topic_terms.extend(topic_watchlist.get("suggested_queries") or [])
        if not topic_terms:
            topic_terms.extend(topic_watchlist.get("context_terms") or [])
            topic_terms.extend(topic_watchlist.get("core_terms") or [])
            topic_terms.extend(topic_watchlist.get("event_triggers") or [])
            topic_terms.extend(topic_watchlist.get("financial_and_policy_terms") or [])
        topic_terms = [str(t).strip() for t in topic_terms if str(t).strip()]
        topic_terms = topic_terms[:8]

    if topic_terms:
        query_part = "(" + " OR ".join(f'"{q}"' for q in topic_terms) + ")"
        base_terms.append(query_part)

    if not base_terms:
        base_terms.append(source_cfg.get("name", "news"))

    return " ".join(base_terms)


def gdelt_status() -> Dict[str, Any]:
    available = importlib.util.find_spec("requests") is not None
    if available:
        return {
            "adapter": "gdelt",
            "available": True,
            "message": "GDELT adapter available.",
        }
    return {
        "adapter": "gdelt",
        "available": False,
        "message": "GDELT dependency missing: requests package unavailable.",
    }


def fetch_gdelt_metadata(
    source_cfg: Dict[str, Any],
    max_items: int = 50,
    timeout: int = 20,
    max_retries: int = 2,
    retry_wait_seconds: int = 5,
    topic_watchlist: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    status = gdelt_status()
    if not status["available"]:
        return [], status["message"]

    try:
        import requests
    except Exception as exc:
        return [], f"GDELT adapter import failed: {exc}"

    timeout = int(source_cfg.get("gdelt_timeout_seconds", timeout))
    max_retries = int(source_cfg.get("gdelt_max_retries", max_retries))
    retry_wait_seconds = int(source_cfg.get("gdelt_retry_wait_seconds", retry_wait_seconds))

    query = _build_query(source_cfg, topic_watchlist=topic_watchlist)
    payload, warning = fetch_gdelt_query(
        query,
        max_items=max_items,
        timeout=timeout,
        max_retries=max_retries,
        retry_wait_seconds=retry_wait_seconds,
        label=f"source '{source_cfg.get('name', 'unknown')}'",
    )
    if warning:
        return [], warning

    articles = payload.get("articles") or []
    items: List[Dict[str, Any]] = []

    for article in articles:
        items.append(
            {
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "published": article.get("seendate") or article.get("socialimage") or "",
                "author": "",
                "summary": article.get("snippet", "") or "",
                "text": "",
                "language": source_cfg.get("language", "unknown"),
                "country": source_cfg.get("country", ""),
                "topics": ["metadata-only"],
            }
        )
    return items, None


def fetch_gdelt_query(
    query: str,
    max_items: int = 50,
    timeout: int = 20,
    max_retries: int = 2,
    retry_wait_seconds: int = 5,
    label: str | None = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    status = gdelt_status()
    subject = label or f"query '{query}'"
    if not status["available"]:
        return {}, status["message"]

    try:
        import requests
    except Exception as exc:
        return {}, f"GDELT adapter import failed: {exc}"

    params = {
        "query": query,
        "mode": "ArtList",
        "maxrecords": min(max_items, 250),
        "format": "json",
    }
    payload: Dict[str, Any] = {}
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(GDELT_DOC_API, params=params, timeout=timeout)
            if response.status_code == 429:
                return {}, f"GDELT rate limited (HTTP 429) for {subject}."
            if response.status_code >= 400:
                return {}, f"GDELT HTTP {response.status_code} for {subject}."
            payload = response.json()
            break
        except requests.Timeout:
            if attempt >= max_retries:
                return {}, f"GDELT timeout after {max_retries + 1} attempt(s) for {subject}."
            time.sleep(retry_wait_seconds)
        except requests.RequestException as exc:
            if attempt >= max_retries:
                return {}, f"GDELT request failed for {subject}: {exc}"
            time.sleep(retry_wait_seconds)
        except Exception:
            if attempt >= max_retries:
                return {}, f"GDELT response parse failed for {subject}."
            time.sleep(retry_wait_seconds)
    return payload, None
