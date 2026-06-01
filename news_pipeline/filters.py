from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import re

from dateutil import parser as date_parser


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = date_parser.parse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _contains_keyword(text: str, keyword: str) -> bool:
    if not keyword:
        return False
    pattern = re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)
    return bool(pattern.search(text))


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(phrase and phrase.lower() in text.lower())


def match_watchlist(article: Dict[str, Any], watchlist: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    source_filter = watchlist.get("sources") or []
    if source_filter and article.get("source") not in source_filter:
        return None

    published = _parse_iso(article.get("published_at", ""))
    if published is None:
        return None

    date_from = _parse_iso(watchlist.get("date_from") or "")
    date_to = _parse_iso(watchlist.get("date_to") or "")
    if date_from and published < date_from:
        return None
    if date_to and published > date_to:
        return None

    corpus = "\n".join(
        [
            article.get("title", ""),
            article.get("summary", ""),
            article.get("text", ""),
        ]
    )

    matched_keywords = [kw for kw in watchlist.get("keywords", []) if _contains_keyword(corpus, kw)]
    matched_phrases = [ph for ph in watchlist.get("phrases", []) if _contains_phrase(corpus, ph)]

    if not matched_keywords and not matched_phrases:
        return None

    return {
        "watchlist": watchlist.get("name", "default"),
        "topic": watchlist.get("topic", watchlist.get("name", "default")),
        "matched_keywords": matched_keywords,
        "matched_phrases": matched_phrases,
    }


def apply_watchlists(article: Dict[str, Any], watchlists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    matches = []
    for watchlist in watchlists:
        match = match_watchlist(article, watchlist)
        if match:
            matches.append(match)

    flat_keywords = []
    for match in matches:
        flat_keywords.extend(match.get("matched_keywords", []))
        flat_keywords.extend(match.get("matched_phrases", []))

    if flat_keywords:
        article["keywords_matched"] = sorted(set(flat_keywords))

    return matches


def filter_by_days(items: List[Dict[str, Any]], days: int) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    output: List[Dict[str, Any]] = []
    for item in items:
        dt = _parse_iso(item.get("published_at", ""))
        if dt and dt >= cutoff:
            output.append(item)
    return output
