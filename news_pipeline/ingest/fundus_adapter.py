from __future__ import annotations

import importlib.util
from typing import Any, Dict, List
from typing import Optional, Tuple


def fundus_status() -> Dict[str, Any]:
    available = importlib.util.find_spec("fundus") is not None
    if available:
        return {
            "adapter": "fundus",
            "available": True,
            "message": "Fundus adapter available.",
        }
    return {
        "adapter": "fundus",
        "available": False,
        "message": 'Fundus dependency missing. Install with: pip install "news-intel[fundus]"',
    }


def fetch_fundus(source_cfg: Dict[str, Any], max_items: int = 50) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Best-effort Fundus adapter.

    Expected source config fields:
    - fundus_collection: e.g. "us", "uk", "de"
    - fundus_publisher: optional publisher inside collection, e.g. "BBCNews"

    If Fundus is unavailable or config is incomplete, returns an empty list.
    """
    status = fundus_status()
    if not status["available"]:
        return [], status["message"]

    try:
        from fundus import Crawler, PublisherCollection
    except Exception as exc:
        return [], f"Fundus import failed: {exc}"

    collection_name = source_cfg.get("fundus_collection")
    publisher_name = source_cfg.get("fundus_publisher")
    if not collection_name:
        return [], f"Fundus source '{source_cfg.get('name', 'unknown')}' missing 'fundus_collection'."

    collection = getattr(PublisherCollection, collection_name, None)
    if collection is None:
        return [], f"Fundus collection '{collection_name}' not found."

    target = collection
    if publisher_name:
        target = getattr(collection, publisher_name, None)
        if target is None:
            return [], f"Fundus publisher '{publisher_name}' not found in collection '{collection_name}'."

    try:
        crawler = Crawler(target)
    except Exception as exc:
        return [], f"Fundus crawler init failed: {exc}"

    items: List[Dict[str, Any]] = []
    try:
        for article in crawler.crawl(max_articles=max_items):
            if article is None:
                continue
            items.append(
                {
                    "title": getattr(article, "title", "") or "",
                    "url": getattr(article, "url", "") or "",
                    "published": getattr(article, "publishing_date", "") or "",
                    "author": ", ".join(getattr(article, "authors", []) or []),
                    "summary": getattr(article, "description", "") or "",
                    "text": getattr(article, "plaintext", "") or getattr(article, "text", "") or "",
                    "language": source_cfg.get("language"),
                    "country": source_cfg.get("country", ""),
                }
            )
    except Exception as exc:
        return [], f"Fundus crawl failed: {exc}"
    return items, None
