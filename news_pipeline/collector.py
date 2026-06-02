from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

from .ingest.fundus_adapter import enrich_article_fundus, fundus_status
from .ingest.gdelt import fetch_gdelt_query
from .normalize import normalize_article, utc_now_iso
from .relevance import classify_watchlist_article
from .storage import Storage

RESTRICTED_DOMAINS = {
    "reuters.com",
    "www.reuters.com",
    "bloomberg.com",
    "www.bloomberg.com",
    "ft.com",
    "www.ft.com",
    "wsj.com",
    "www.wsj.com",
    "dowjones.com",
    "www.dowjones.com",
}

SOURCE_BY_DOMAIN = {
    "reuters.com": "Reuters",
    "www.reuters.com": "Reuters",
    "bloomberg.com": "Bloomberg",
    "www.bloomberg.com": "Bloomberg",
    "ft.com": "Financial Times",
    "www.ft.com": "Financial Times",
    "wsj.com": "Wall Street Journal",
    "www.wsj.com": "Wall Street Journal",
    "apnews.com": "AP News",
    "www.apnews.com": "AP News",
}

DEFAULT_GDELT_CONFIG = {
    "enabled": True,
    "max_queries_per_topic": 2,
    "max_items_per_query": 10,
    "timeout_seconds": 20,
    "retry_count": 1,
    "backoff_seconds": 30,
    "cache_ttl_minutes": 180,
    "min_delay_between_queries_seconds": 15,
    "stop_on_first_rate_limit": True,
}

BROAD_QUERY_TERMS = {
    "europe",
    "russia",
    "russian",
    "ukraine",
    "war",
    "defense",
    "defence",
    "nato",
    "eu",
}

EUROPE_RU_PREFERRED_GDELT_QUERIES = [
    "NATO Russia readiness eastern Europe",
    "Europe defense spending Russia threat",
    "Poland civil defense Russia",
    "Baltic Sea sabotage Russia infrastructure",
    "EU ammunition production Ukraine Russia",
    "Germany air defense procurement Russia",
]


def _domain(url: str) -> str:
    return urlparse(url or "").netloc.lower()


def access_mode_for_url(url: str) -> str:
    domain = _domain(url)
    if domain in RESTRICTED_DOMAINS:
        return "metadata_only"
    if domain in {"apnews.com", "www.apnews.com"}:
        return "public"
    return "public" if domain else "unknown"


def source_for_url(url: str, fallback: str = "GDELT") -> str:
    domain = _domain(url)
    return SOURCE_BY_DOMAIN.get(domain, domain or fallback)


def _is_broad_query(query: str) -> bool:
    terms = query.lower().split()
    if len(terms) <= 1:
        return True
    if len(terms) <= 2 and all(term in BROAD_QUERY_TERMS for term in terms):
        return True
    return False


def _score_query(query: str, source: str, watchlist: Dict[str, Any]) -> int:
    text = query.lower()
    score = 20 if source == "suggested_query" else 10
    contexts = [str(t).lower() for t in watchlist.get("context_terms") or []]
    cores = [str(t).lower() for t in watchlist.get("core_terms") or []]
    events = [str(t).lower() for t in watchlist.get("event_triggers") or []]
    financial = [str(t).lower() for t in watchlist.get("financial_and_policy_terms") or []]

    if any(t and t in text for t in contexts):
        score += 5
    if any(t and t in text for t in cores):
        score += 8
    if any(t and t in text for t in events):
        score += 4
    if any(t and t in text for t in financial):
        score += 4
    if _is_broad_query(query):
        score -= 100
    return score


def build_gdelt_topic_query_plan(watchlist: Dict[str, Any], max_queries: int = 5) -> List[Dict[str, Any]]:
    watchlist_name = (watchlist.get("name") or "").strip().lower()
    suggested_source = EUROPE_RU_PREFERRED_GDELT_QUERIES if watchlist_name == "europe_ru_war_preparations" else watchlist.get("suggested_queries") or []
    suggested = [str(q).strip() for q in suggested_source if str(q).strip()]

    contexts = [str(t).strip() for t in (watchlist.get("context_terms") or []) if str(t).strip()]
    cores = []
    for key in ("core_terms", "event_triggers", "financial_and_policy_terms"):
        cores.extend(str(t).strip() for t in (watchlist.get(key) or []) if str(t).strip())

    candidates: List[Dict[str, Any]] = []
    for query in suggested:
        if _is_broad_query(query):
            continue
        candidates.append(
            {
                "query": query,
                "source": "suggested_query",
                "score": _score_query(query, "suggested_query", watchlist),
            }
        )

    for context in contexts[:5]:
        for core in cores[:8]:
            query = f"{context} {core}".strip()
            if _is_broad_query(query):
                continue
            candidates.append(
                {
                    "query": query,
                    "source": "generated_context_core",
                    "score": _score_query(query, "generated_context_core", watchlist),
                }
            )

    deduped: Dict[str, Dict[str, Any]] = {}
    for item in candidates:
        key = item["query"].lower()
        if key not in deduped or item["score"] > deduped[key]["score"]:
            deduped[key] = item
    ordered = sorted(deduped.values(), key=lambda item: (item["score"], item["source"] == "suggested_query"), reverse=True)
    return ordered[:max_queries]


def build_gdelt_topic_queries(watchlist: Dict[str, Any], max_queries: int = 5) -> List[str]:
    return [item["query"] for item in build_gdelt_topic_query_plan(watchlist, max_queries=max_queries)]


def _cache_is_fresh(fetched_at: str, ttl_minutes: int) -> bool:
    try:
        fetched = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    return datetime.now(timezone.utc) - fetched.astimezone(timezone.utc) <= timedelta(minutes=ttl_minutes)


def _items_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for article in payload.get("articles") or []:
        items.append(
            {
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "published": article.get("seendate") or "",
                "author": "",
                "summary": article.get("snippet", "") or "",
                "text": "",
                "language": article.get("language", "unknown") or "unknown",
                "country": article.get("sourcecountry", "") or "",
                "topics": ["metadata-only", "gdelt"],
            }
        )
    return items


def _store_discovered_item(
    storage: Storage,
    raw: Dict[str, Any],
    watchlist: Dict[str, Any],
    query: str,
    enrichment_status: str,
) -> Tuple[bool, str | None]:
    url = raw.get("url", "")
    source_name = source_for_url(url)
    access_mode = access_mode_for_url(url)
    source_cfg = {
        "name": source_name,
        "language": raw.get("language", "unknown"),
        "country": raw.get("country", ""),
        "access_mode": access_mode,
    }
    article = normalize_article(raw, source_cfg)
    article["access_mode"] = access_mode

    inserted = storage.insert_article(article)
    article_id = article["id"] if inserted else storage.article_id_for(article.get("url", ""), article.get("title", ""))
    if not article_id:
        return inserted, None

    classification = classify_watchlist_article(article, watchlist)
    storage.upsert_article_metadata(
        article_id,
        {
            "discovery_source": "GDELT",
            "discovery_query": query,
            "access_mode": access_mode,
            "enrichment_status": enrichment_status,
            "enrichment_adapter": None,
            **classification,
        },
    )
    return inserted, article_id


def collect_topic(
    storage: Storage,
    watchlist: Dict[str, Any],
    days: int,
    max_items: int,
    gdelt_config: Dict[str, Any] | None = None,
    source: str = "gdelt",
    enrich: str | None = "fundus",
    max_queries: int | None = None,
    use_cache_first: bool = False,
    dry_run_queries: bool = False,
    sleep_func=time.sleep,
) -> Dict[str, Any]:
    cfg = {**DEFAULT_GDELT_CONFIG, **(gdelt_config or {})}
    topic = watchlist.get("name", watchlist.get("topic", "unknown"))
    warnings: List[str] = []
    inserted = 0
    updated = 0
    enriched = 0
    query_count = 0
    query_statuses: List[Dict[str, str]] = []

    max_query_count = int(max_queries or cfg["max_queries_per_topic"])
    query_plan = build_gdelt_topic_query_plan(watchlist, max_queries=max_query_count)
    if dry_run_queries:
        return {
            "status": "ok",
            "warnings": [],
            "query_count": len(query_plan),
            "inserted_count": 0,
            "updated_count": 0,
            "enriched_count": 0,
            "query_statuses": [
                {"query": item["query"], "source": item["source"], "status": "planned"} for item in query_plan
            ],
        }

    run_id = storage.start_collection_run(topic, source, utc_now_iso())
    try:
        if "gdelt" not in [s.strip() for s in source.split(",")]:
            warnings.append("No supported discovery source requested for collect.")
        elif not cfg.get("enabled", True):
            warnings.append("GDELT topic collection is disabled by config.")
        else:
            queries = query_plan
            query_count = len(queries)
            remaining = max_items
            live_query_attempts = 0
            rate_limited = False
            for item in queries:
                query = item["query"]
                if remaining <= 0:
                    query_statuses.append({"query": query, "source": item["source"], "status": "skipped_max_items"})
                    break
                if rate_limited:
                    query_statuses.append({"query": query, "source": item["source"], "status": "skipped_rate_limited"})
                    continue

                payload = None
                cached = storage.get_gdelt_cache(query)
                if cached and _cache_is_fresh(cached.get("fetched_at", ""), int(cfg["cache_ttl_minutes"])):
                    payload = cached["payload"]
                    query_statuses.append({"query": query, "source": item["source"], "status": "cached"})
                else:
                    if live_query_attempts > 0 and int(cfg.get("min_delay_between_queries_seconds", 0)) > 0:
                        sleep_func(int(cfg["min_delay_between_queries_seconds"]))
                    live_query_attempts += 1
                    query_statuses.append({"query": query, "source": item["source"], "status": "attempted"})
                    payload, warning = fetch_gdelt_query(
                        query,
                        max_items=min(int(cfg["max_items_per_query"]), remaining),
                        timeout=int(cfg["timeout_seconds"]),
                        max_retries=int(cfg["retry_count"]),
                        retry_wait_seconds=int(cfg["backoff_seconds"]),
                    )
                    if warning:
                        warnings.append(warning)
                        if "429" in warning or "rate limited" in warning.lower():
                            warnings.append("rate_limited_stop")
                            query_statuses[-1]["status"] = "rate_limited"
                            if cfg.get("stop_on_first_rate_limit", True):
                                rate_limited = True
                                continue
                        query_statuses[-1]["status"] = "failed"
                        continue
                    storage.set_gdelt_cache(query, utc_now_iso(), payload)

                items = _items_from_payload(payload or {})
                if not items:
                    warnings.append(f"GDELT returned no results for query: {query}")
                    continue

                for raw in items[:remaining]:
                    enrichment_status = "not_attempted"
                    did_insert, article_id = _store_discovered_item(storage, raw, watchlist, query, enrichment_status)
                    if article_id:
                        if did_insert:
                            inserted += 1
                        else:
                            updated += 1
                        remaining -= 1
                    if remaining <= 0:
                        break

        if enrich == "fundus":
            result = enrich_topic(storage, watchlist, days=days, adapter="fundus", max_items=max_items)
            enriched += result["enriched_count"]
            warnings.extend(result["warnings"])

        status = "ok" if not warnings else "warning"
        return {
            "status": status,
            "warnings": warnings,
            "query_count": query_count,
            "inserted_count": inserted,
            "updated_count": updated,
            "enriched_count": enriched,
            "query_statuses": query_statuses,
        }
    finally:
        storage.finish_collection_run(
            run_id,
            utc_now_iso(),
            "warning" if warnings else "ok",
            warnings,
            query_count,
            inserted,
            updated,
            enriched,
        )


def _is_restricted_or_metadata(row: Dict[str, Any]) -> bool:
    domain = _domain(row.get("url", ""))
    return domain in RESTRICTED_DOMAINS or row.get("access_mode") in {"metadata_only", "api_required", "licensed_api"}


def _merge_enrichment_candidates(
    storage: Storage,
    watchlist: Dict[str, Any],
    days: int,
    max_items: int,
    include_rss: bool,
) -> Tuple[List[Dict[str, Any]], Dict[str, int], List[Dict[str, str]]]:
    rows = storage.list_articles_for_enrichment(days=days, topic=watchlist.get("name", ""), limit=max_items)
    candidates: Dict[str, Dict[str, Any]] = {row["id"]: dict(row) for row in rows}
    breakdown = {
        "no_eligible_articles": 0,
        "already_enriched": 0,
        "restricted_paywall": 0,
        "unsupported_source": 0,
        "adapter_unavailable": 0,
        "failed": 0,
        "not_attempted": 0,
    }
    examples: List[Dict[str, str]] = []

    if include_rss:
        recent = storage.list_recent(days=days, limit=max(max_items * 8, 200))
        for row in recent:
            if row["id"] in candidates:
                continue
            classification = classify_watchlist_article(row, watchlist)
            if classification.get("relevance_class") == "noise":
                continue
            enrichment_status = row.get("enrichment_status") or "not_attempted"
            if enrichment_status == "full_text_extracted":
                breakdown["already_enriched"] += 1
                continue
            candidate = dict(row)
            candidate.setdefault("discovery_source", "RSS")
            candidate.setdefault("enrichment_status", enrichment_status)
            candidate.update(classification)
            candidates[candidate["id"]] = candidate

    eligible: List[Dict[str, Any]] = []
    for row in candidates.values():
        status = row.get("enrichment_status") or "not_attempted"
        if status == "full_text_extracted":
            breakdown["already_enriched"] += 1
            continue
        if _is_restricted_or_metadata(row):
            breakdown["restricted_paywall"] += 1
            storage.upsert_article_metadata(
                row["id"],
                {
                    "enrichment_status": "paywall_or_restricted",
                    "enrichment_adapter": "fundus",
                    "access_mode": row.get("access_mode"),
                    "discovery_source": row.get("discovery_source"),
                },
            )
            if len(examples) < 5:
                examples.append({"url": row.get("url", ""), "reason": "restricted/paywall or metadata-only"})
            continue
        eligible.append(row)

    if not eligible:
        breakdown["no_eligible_articles"] = 1
    return eligible[:max_items], breakdown, examples


def enrich_topic(
    storage: Storage,
    watchlist: Dict[str, Any],
    days: int,
    adapter: str,
    max_items: int,
    include_rss: bool = False,
) -> Dict[str, Any]:
    warnings: List[str] = []
    enriched = 0
    breakdown: Dict[str, int] = {
        "no_eligible_articles": 0,
        "already_enriched": 0,
        "restricted_paywall": 0,
        "unsupported_source": 0,
        "adapter_unavailable": 0,
        "failed": 0,
        "not_attempted": 0,
    }
    examples: List[Dict[str, str]] = []
    if adapter != "fundus":
        return {"warnings": [f"Unsupported enrichment adapter: {adapter}"], "enriched_count": 0, "breakdown": breakdown, "examples": examples}

    status = fundus_status()
    rows, breakdown, examples = _merge_enrichment_candidates(storage, watchlist, days, max_items, include_rss=include_rss)
    if not status["available"]:
        warnings.append("Fundus unavailable. Continuing with metadata-only results.")
        for row in rows:
            storage.upsert_article_metadata(
                row["id"],
                {
                    "enrichment_status": "adapter_unavailable",
                    "enrichment_adapter": "fundus",
                    "access_mode": row.get("access_mode"),
                },
            )
            breakdown["adapter_unavailable"] += 1
        return {"warnings": warnings, "enriched_count": 0, "breakdown": breakdown, "examples": examples}

    for row in rows:
        breakdown["not_attempted"] += 1
        result = enrich_article_fundus(row)
        status_name = result.get("status", "failed")
        if status_name == "full_text_extracted":
            storage.update_article_text(
                row["id"],
                summary=result.get("summary"),
                text=result.get("text"),
                title=result.get("title") or None,
                author=result.get("author") or None,
                published_at=result.get("published_at") or None,
            )
            enriched += 1
        elif status_name == "unsupported_source":
            breakdown["unsupported_source"] += 1
            if len(examples) < 5:
                examples.append({"url": row.get("url", ""), "reason": result.get("reason", "unsupported_source")})
        elif status_name == "paywall_or_restricted":
            breakdown["restricted_paywall"] += 1
            if len(examples) < 5:
                examples.append({"url": row.get("url", ""), "reason": result.get("reason", "paywall_or_restricted")})
        elif status_name == "adapter_unavailable":
            breakdown["adapter_unavailable"] += 1
        elif status_name == "failed":
            breakdown["failed"] += 1
            if len(examples) < 5:
                examples.append({"url": row.get("url", ""), "reason": result.get("reason", "failed")})
        storage.upsert_article_metadata(
            row["id"],
            {
                "enrichment_status": status_name,
                "enrichment_adapter": "fundus",
                "access_mode": row.get("access_mode"),
                "discovery_source": row.get("discovery_source") or "RSS",
                "relevance_class": row.get("relevance_class"),
                "confidence": row.get("confidence"),
                "reason": row.get("reason"),
                "matched_context_terms": row.get("matched_context_terms", []),
                "matched_core_terms": row.get("matched_core_terms", []),
                "matched_event_triggers": row.get("matched_event_triggers", []),
                "matched_financial_terms": row.get("matched_financial_terms", []),
            },
        )
    return {"warnings": warnings, "enriched_count": enriched, "breakdown": breakdown, "examples": examples}
