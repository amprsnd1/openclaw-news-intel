from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import quote_plus

import feedparser

from .collector import access_mode_for_url, build_gdelt_topic_query_plan, source_for_url
from .ingest.gdelt import fetch_gdelt_query
from .ingest.rss import fetch_rss
from .normalize import normalize_article, title_hash, utc_now_iso
from .relevance import GENERIC_CONTEXT_TERMS, match_terms_in_fields
from .storage import Storage

SIGNAL_RANK = {"high_signal": 3, "medium_signal": 2, "low_signal": 1, "noise": 0}
MIN_CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}

NOISE_HINTS = {
    "sport",
    "sports",
    "football",
    "soccer",
    "celebrity",
    "movie",
    "music",
    "mosaic",
    "restoration",
    "recipe",
    "fashion",
}

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

SCAN_TERM_ALIASES = {
    "europe_ru_war_preparations": {
        "core": ["troops", "military deployment"],
        "event": ["deploys troops", "troop deployment"],
    }
}


def parse_since_window(value: str | None) -> tuple[datetime, str, int]:
    raw = (value or "6h").strip().lower()
    if not raw:
        raw = "6h"
    unit = raw[-1]
    number = raw[:-1]
    try:
        amount = int(number)
    except ValueError as exc:
        raise ValueError("since must be like 2h, 24h, or 7d") from exc
    if amount < 0:
        raise ValueError("since must be positive")
    if unit == "h":
        delta = timedelta(hours=amount)
    elif unit == "d":
        delta = timedelta(days=amount)
    elif unit == "m":
        delta = timedelta(minutes=amount)
    else:
        raise ValueError("since must use m, h, or d")
    return datetime.now(timezone.utc) - delta, raw, int(delta.total_seconds())


def _dt_from_iso(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_recent(article: Dict[str, Any], since_dt: datetime) -> bool:
    return _dt_from_iso(article.get("published_at", "")) >= since_dt


def scan_key(topic: str | None, query: str | None, sources: Iterable[str], since_label: str) -> str:
    subject = f"topic:{topic}" if topic else f"query:{query}"
    source_key = ",".join(sorted(s.strip().lower() for s in sources if s.strip()))
    return f"{subject}|sources:{source_key}|window:{since_label}".lower()


def watchlist_scan_terms(watchlist: Dict[str, Any] | None, query: str | None = None) -> Dict[str, List[str]]:
    if watchlist:
        aliases = SCAN_TERM_ALIASES.get((watchlist.get("name") or "").strip().lower(), {})
        return {
            "context": list(watchlist.get("context_terms") or watchlist.get("keywords") or []) + list(aliases.get("context", [])),
            "core": list(watchlist.get("core_terms") or watchlist.get("keywords") or []) + list(aliases.get("core", [])),
            "event": list(watchlist.get("event_triggers") or []) + list(aliases.get("event", [])),
            "financial": list(watchlist.get("financial_and_policy_terms") or []) + list(aliases.get("financial", [])),
            "suggested_queries": list(watchlist.get("suggested_queries") or []),
        }
    terms = [t for t in (query or "").split() if t]
    return {
        "context": terms,
        "core": terms,
        "event": [],
        "financial": [],
        "suggested_queries": [query or ""],
    }


def classify_signal(article: Dict[str, Any], watchlist: Dict[str, Any] | None = None, query: str | None = None) -> Dict[str, Any]:
    title = article.get("title", "")
    summary = article.get("summary", "")
    source = article.get("source", "")
    fields = [title, summary, source]
    lower_blob = " ".join(fields).lower()

    if any(hint in lower_blob for hint in NOISE_HINTS):
        return {
            "signal_class": "noise",
            "matched_terms": [],
            "matched_context_terms": [],
            "matched_core_terms": [],
            "matched_event_triggers": [],
            "matched_financial_terms": [],
            "why": "Excluded as unrelated headline noise.",
        }

    terms = watchlist_scan_terms(watchlist, query=query)
    matched_context = match_terms_in_fields(fields, terms["context"])
    matched_core = match_terms_in_fields(fields, terms["core"])
    matched_event = match_terms_in_fields(fields, terms["event"])
    matched_financial = match_terms_in_fields(fields, terms["financial"])
    matched_all = sorted(set(matched_context + matched_core + matched_event + matched_financial))

    if not watchlist:
        query_terms = [str(t).lower() for t in (query or "").split() if t]
        matched = match_terms_in_fields(fields, query_terms)
        if not matched:
            signal = "noise"
            why = "No query terms matched the headline or summary."
        elif len(matched) >= 3 or len(matched) == len(set(query_terms)):
            signal = "high_signal"
            why = "Matched most query terms in headline metadata."
        elif len(matched) >= 2:
            signal = "medium_signal"
            why = "Matched multiple query terms in headline metadata."
        else:
            only = matched[0]
            signal = "low_signal"
            why = "Only one query term matched; useful only as an adjacent signal."
            if only in GENERIC_CONTEXT_TERMS:
                why = "Only one generic context term matched."
        return {
            "signal_class": signal,
            "matched_terms": sorted(set(matched)),
            "matched_context_terms": sorted(set(matched)),
            "matched_core_terms": [],
            "matched_event_triggers": [],
            "matched_financial_terms": [],
            "why": why,
        }

    if not matched_all:
        signal = "noise"
        why = "No watchlist terms matched headline metadata."
    elif matched_context and (matched_event or matched_financial):
        signal = "high_signal"
        why = "Matched watchlist context plus event or policy trigger in headline metadata."
    elif matched_context and len(set(matched_core)) >= 2:
        signal = "high_signal"
        why = "Matched watchlist context plus multiple core signal terms."
    elif matched_context and matched_core:
        signal = "medium_signal"
        why = "Matched watchlist context plus a core signal term."
    elif matched_context or matched_core or matched_event or matched_financial:
        signal = "low_signal"
        why = "Matched adjacent watchlist terms without enough context/core linkage."
    else:
        signal = "noise"
        why = "No relevant signal found."

    return {
        "signal_class": signal,
        "matched_terms": matched_all,
        "matched_context_terms": sorted(set(matched_context)),
        "matched_core_terms": sorted(set(matched_core)),
        "matched_event_triggers": sorted(set(matched_event)),
        "matched_financial_terms": sorted(set(matched_financial)),
        "why": why,
    }


def _source_cfg_for_article(raw: Dict[str, Any], fallback_source: str, access_mode: str = "rss") -> Dict[str, Any]:
    return {
        "name": raw.get("source") or fallback_source,
        "language": raw.get("language", "unknown"),
        "country": raw.get("country", ""),
        "access_mode": raw.get("access_mode") or access_mode,
    }


def _store_candidate(
    storage: Storage,
    raw: Dict[str, Any],
    source_cfg: Dict[str, Any],
    discovery_source: str,
    discovery_query: str | None = None,
) -> Dict[str, Any] | None:
    article = normalize_article(raw, source_cfg)
    if not article.get("title") or not article.get("url"):
        return None
    inserted = storage.insert_article(article)
    article_id = article["id"] if inserted else storage.article_id_for(article.get("url", ""), article.get("title", ""))
    if not article_id:
        return None
    article["id"] = article_id
    storage.upsert_article_metadata(
        article_id,
        {
            "discovery_source": discovery_source,
            "discovery_query": discovery_query,
            "access_mode": article.get("access_mode"),
            "enrichment_status": "not_attempted",
        },
    )
    return article


def _dedupe_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: List[Dict[str, Any]] = []
    for item in candidates:
        url = item.get("url", "")
        thash = title_hash(item.get("title", ""))
        key = item.get("id", "")
        if url and url in seen_urls:
            continue
        if thash and thash in seen_titles:
            continue
        if key and any(existing.get("id") == key for existing in unique):
            continue
        seen_urls.add(url)
        seen_titles.add(thash)
        unique.append(item)
    return unique


def _google_news_items(query: str, max_items: int) -> List[Dict[str, Any]]:
    parsed = feedparser.parse(GOOGLE_NEWS_RSS_URL.format(query=quote_plus(query)))
    items: List[Dict[str, Any]] = []
    for entry in parsed.entries[:max_items]:
        source = "Google News RSS"
        source_info = entry.get("source")
        if isinstance(source_info, dict):
            source = source_info.get("title") or source
        items.append(
            {
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "published": entry.get("published") or entry.get("updated") or "",
                "author": "",
                "summary": entry.get("summary", "") or entry.get("description", ""),
                "text": "",
                "language": "en",
                "country": "",
                "source": source,
                "access_mode": "public_metadata",
            }
        )
    return items


def _gdelt_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for article in payload.get("articles") or []:
        url = article.get("url", "")
        items.append(
            {
                "title": article.get("title", ""),
                "url": url,
                "published": article.get("seendate") or "",
                "author": "",
                "summary": article.get("snippet", "") or "",
                "text": "",
                "language": article.get("language", "unknown") or "unknown",
                "country": article.get("sourcecountry", "") or "",
                "source": source_for_url(url),
                "access_mode": "metadata_only" if access_mode_for_url(url) == "metadata_only" else "public_metadata",
            }
        )
    return items


def _queries_for_scan(watchlist: Dict[str, Any] | None, query: str | None, max_queries: int) -> List[Dict[str, str]]:
    if query:
        return [{"query": query, "source": "free_form_query"}]
    if not watchlist:
        return []
    return build_gdelt_topic_query_plan(watchlist, max_queries=max_queries)


def _source_status_template(sources: Iterable[str]) -> Dict[str, str]:
    statuses = {"rss": "skipped", "google_news_rss": "skipped", "gdelt": "skipped", "fundus": "not used for scan"}
    for source in sources:
        if source in statuses:
            statuses[source] = "pending"
    return statuses


def run_scan(
    storage: Storage,
    sources_cfg: List[Dict[str, Any]],
    watchlist: Dict[str, Any] | None,
    query: str | None,
    since: str = "6h",
    max_items: int = 50,
    sources: str = "rss",
    min_confidence: str = "low",
    only_new: bool = True,
    show_seen: bool = False,
    max_queries: int = 1,
    use_cache_first: bool = False,
    gdelt_config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    since_dt, since_label, _ = parse_since_window(since)
    source_list = [s.strip().lower() for s in sources.split(",") if s.strip()]
    if not source_list:
        source_list = ["rss"]

    statuses = _source_status_template(source_list)
    warnings: List[str] = []
    candidates: List[Dict[str, Any]] = []
    scanned_counts = {"rss": 0, "google_news_rss": 0, "gdelt": 0}
    topic_name = watchlist.get("name") if watchlist else None
    key = scan_key(topic_name, query, source_list, since_label)

    if "rss" in source_list:
        rss_sources = [s for s in sources_cfg if s.get("enabled", True) and s.get("adapter", "rss") == "rss"]
        try:
            for source_cfg in rss_sources:
                raw_items = fetch_rss(source_cfg, max_items=max_items)
                scanned_counts["rss"] += len(raw_items)
                for raw in raw_items:
                    stored = _store_candidate(storage, raw, source_cfg, "rss")
                    if stored and _is_recent(stored, since_dt):
                        candidates.append(stored)
            statuses["rss"] = "ok"
        except Exception as exc:
            statuses["rss"] = "warning"
            warnings.append(f"RSS scan warning: {exc}")

    query_plan = _queries_for_scan(watchlist, query, max_queries=max_queries)
    if "google_news_rss" in source_list:
        try:
            for item in query_plan[:max_queries]:
                raw_items = _google_news_items(item["query"], max_items=max_items)
                scanned_counts["google_news_rss"] += len(raw_items)
                for raw in raw_items:
                    source_cfg = _source_cfg_for_article(raw, raw.get("source") or "Google News RSS", "public_metadata")
                    stored = _store_candidate(storage, raw, source_cfg, "google_news_rss", item["query"])
                    if stored and _is_recent(stored, since_dt):
                        candidates.append(stored)
            statuses["google_news_rss"] = "ok"
        except Exception as exc:
            statuses["google_news_rss"] = "warning"
            warnings.append(f"Google News RSS scan warning: {exc}")

    if "gdelt" in source_list:
        cfg = gdelt_config or {}
        ttl_minutes = int(cfg.get("cache_ttl_minutes", 180))
        try:
            for idx, item in enumerate(query_plan[:max_queries]):
                payload = None
                cached = storage.get_gdelt_cache(item["query"])
                if use_cache_first and cached:
                    fetched_at = cached.get("fetched_at", "")
                    try:
                        fetched = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
                        if fetched.tzinfo is None:
                            fetched = fetched.replace(tzinfo=timezone.utc)
                        if datetime.now(timezone.utc) - fetched.astimezone(timezone.utc) <= timedelta(minutes=ttl_minutes):
                            payload = cached.get("payload")
                            statuses["gdelt"] = "cache"
                    except Exception:
                        payload = None
                if payload is None:
                    payload, warning = fetch_gdelt_query(
                        item["query"],
                        max_items=min(max_items, int(cfg.get("max_items_per_query", 10))),
                        timeout=int(cfg.get("timeout_seconds", 20)),
                        max_retries=int(cfg.get("retry_count", 1)),
                        retry_wait_seconds=int(cfg.get("backoff_seconds", 30)),
                        label=f"scan query '{item['query']}'",
                    )
                    if warning:
                        warnings.append(warning)
                        statuses["gdelt"] = "rate-limited" if "429" in warning else "warning"
                        if "429" in warning:
                            break
                        continue
                    storage.set_gdelt_cache(item["query"], utc_now_iso(), payload)
                    if statuses.get("gdelt") != "cache":
                        statuses["gdelt"] = "ok"
                raw_items = _gdelt_items(payload or {})
                scanned_counts["gdelt"] += len(raw_items)
                for raw in raw_items:
                    source_cfg = _source_cfg_for_article(raw, raw.get("source") or "GDELT", raw.get("access_mode") or "public_metadata")
                    stored = _store_candidate(storage, raw, source_cfg, "gdelt", item["query"])
                    if stored and _is_recent(stored, since_dt):
                        candidates.append(stored)
                if idx < max_queries - 1 and int(cfg.get("min_delay_between_queries_seconds", 0)) > 0:
                    # scan defaults to conservative single-query use; multi-query pacing is handled by collect.
                    pass
            if statuses["gdelt"] == "pending":
                statuses["gdelt"] = "ok"
        except Exception as exc:
            statuses["gdelt"] = "warning"
            warnings.append(f"GDELT scan warning: {exc}")

    candidates = _dedupe_candidates(candidates)
    seen_ids = storage.scan_seen_ids(key)
    signals: List[Dict[str, Any]] = []
    threshold = MIN_CONFIDENCE_RANK.get(min_confidence, 1)
    for candidate in candidates:
        signal = classify_signal(candidate, watchlist=watchlist, query=query)
        candidate.update(signal)
        candidate["signal_rank"] = SIGNAL_RANK.get(candidate.get("signal_class"), 0)
        if candidate["signal_rank"] <= 0:
            continue
        if candidate["signal_rank"] < threshold:
            continue
        if only_new and not show_seen and candidate.get("id") in seen_ids:
            continue
        signals.append(candidate)

    signals.sort(
        key=lambda item: (
            item.get("signal_rank", 0),
            len(item.get("matched_terms") or []),
            item.get("published_at", ""),
        ),
        reverse=True,
    )
    selected = signals[:max_items]
    storage.mark_scan_seen(key, [item.get("id", "") for item in selected])

    broad_warning = None
    if query:
        q_terms = [t.lower() for t in query.split() if t]
        if len(q_terms) <= 1 or all(t in GENERIC_CONTEXT_TERMS for t in q_terms):
            broad_warning = "Free-form query may be too broad; use context plus concrete event terms."
            warnings.append(broad_warning)

    return {
        "topic": topic_name,
        "query": query,
        "since": since_label,
        "sources": source_list,
        "source_status": statuses,
        "warnings": warnings,
        "scanned_counts": scanned_counts,
        "new_items_scanned": len(candidates),
        "signals": selected,
        "seen_hidden": max(0, len(signals) - len(selected)),
    }


def render_scan_markdown(result: Dict[str, Any]) -> str:
    subject = result.get("topic") or result.get("query") or "scan"
    sources = ",".join(result.get("sources") or [])
    signals = result.get("signals") or []
    high = [s for s in signals if s.get("signal_class") == "high_signal"]
    medium = [s for s in signals if s.get("signal_class") == "medium_signal"]
    low = [s for s in signals if s.get("signal_class") == "low_signal"]

    lines = [
        f"# Signal Scan: {subject}",
        f"Window: last {result.get('since')}",
        f"Sources: {sources}",
        f"New items scanned: {result.get('new_items_scanned', 0)}",
        f"Signals found: {len(signals)}",
    ]
    if not high and not medium:
        lines.extend(
            [
                "",
                f"No high or medium signals found in the last {result.get('since')}.",
                "Scanned:",
                f"- RSS items: {result.get('scanned_counts', {}).get('rss', 0)}",
                f"- GDELT items: {result.get('scanned_counts', {}).get('gdelt', 0)}",
                f"- Google News RSS items: {result.get('scanned_counts', {}).get('google_news_rss', 0)}",
                f"- New items: {result.get('new_items_scanned', 0)}",
            ]
        )

    def section(title: str, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        lines.extend(["", f"## {title}"])
        for idx, row in enumerate(rows, start=1):
            matched = ", ".join(row.get("matched_terms") or []) or "-"
            lines.append(f"{idx}. [{row.get('title', 'Untitled')}]({row.get('url', '')})")
            lines.append(f"   Source: {row.get('source', '-')}")
            lines.append(f"   Time: {row.get('published_at', '-')}")
            lines.append(f"   Matched terms: {matched}")
            lines.append(f"   Confidence: {row.get('signal_class')}")
            lines.append(f"   Why it matters: {row.get('why', '-')}")

    section("High Signal", high)
    section("Medium Signal", medium)
    section("Low Signal", low)

    lines.extend(["", "## Source Status"])
    for name, status in (result.get("source_status") or {}).items():
        label = "GDELT" if name == "gdelt" else "RSS" if name == "rss" else "Google News RSS" if name == "google_news_rss" else "Fundus"
        lines.append(f"- {label}: {status}")
    if result.get("warnings"):
        lines.extend(["", "## Source Limits"])
        for warning in result["warnings"]:
            lines.append(f"- {warning}")
    lines.extend(["", "## Gaps"])
    if not high:
        lines.append("- No high-confidence headline signal found in this window.")
    if not medium:
        lines.append("- No medium-confidence headline signal found in this window.")
    if not signals:
        lines.append("- Try a longer window or add `--source rss,google_news_rss` for broader headline discovery.")
    return "\n".join(lines)
