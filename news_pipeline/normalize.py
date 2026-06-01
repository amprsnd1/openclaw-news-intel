from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Dict
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import re

from dateutil import parser as date_parser

_TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "ref",
    "ref_src",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def to_iso_datetime(value: Any) -> str:
    if not value:
        return utc_now_iso()
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = date_parser.parse(str(value))
        except Exception:
            return utc_now_iso()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def canonicalize_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    query = [(k, v) for (k, v) in parse_qsl(parsed.query, keep_blank_values=True) if k not in _TRACKING_PARAMS and not k.startswith("utm_")]
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            parsed.params,
            urlencode(query, doseq=True),
            "",
        )
    )


def stable_hash(*parts: str, length: int = 32) -> str:
    payload = "||".join((p or "") for p in parts)
    return sha256(payload.encode("utf-8")).hexdigest()[:length]


def normalized_title(title: str) -> str:
    text = (title or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9 ]", "", text)
    return text


def title_hash(title: str) -> str:
    return stable_hash(normalized_title(title), length=24)


def normalize_article(raw: Dict[str, Any], source_cfg: Dict[str, Any]) -> Dict[str, Any]:
    title = (raw.get("title") or "").strip()
    raw_url = raw.get("url") or raw.get("link") or ""
    url = canonicalize_url(str(raw_url))
    published = to_iso_datetime(raw.get("published_at") or raw.get("published") or raw.get("pubDate"))
    summary = (raw.get("summary") or raw.get("description") or "").strip()
    text = (raw.get("text") or "").strip()

    article_id = stable_hash(
        source_cfg.get("name", ""),
        url,
        title,
        published,
    )

    return {
        "id": article_id,
        "source": source_cfg.get("name", "unknown"),
        "title": title,
        "url": url,
        "published_at": published,
        "author": (raw.get("author") or "").strip(),
        "language": raw.get("language") or source_cfg.get("language", "unknown"),
        "country": raw.get("country") or source_cfg.get("country", ""),
        "summary": summary,
        "text": text,
        "topics": raw.get("topics") or [],
        "keywords_matched": [],
        "access_mode": source_cfg.get("access_mode", "public"),
        "created_at": utc_now_iso(),
    }
