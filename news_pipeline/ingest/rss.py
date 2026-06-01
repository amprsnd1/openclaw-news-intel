from __future__ import annotations

from typing import Any, Dict, List

import feedparser


def fetch_rss(source_cfg: Dict[str, Any], max_items: int = 50) -> List[Dict[str, Any]]:
    feed_url = source_cfg.get("url")
    if not feed_url:
        return []

    parsed = feedparser.parse(feed_url)
    entries = parsed.entries[:max_items]
    items: List[Dict[str, Any]] = []

    for entry in entries:
        content_blocks = entry.get("content") or []
        content_text = "\n".join(block.get("value", "") for block in content_blocks if isinstance(block, dict))

        items.append(
            {
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "published": entry.get("published") or entry.get("updated") or "",
                "author": entry.get("author", ""),
                "summary": entry.get("summary", "") or entry.get("description", ""),
                "text": content_text,
                "language": source_cfg.get("language"),
                "country": source_cfg.get("country", ""),
            }
        )
    return items
