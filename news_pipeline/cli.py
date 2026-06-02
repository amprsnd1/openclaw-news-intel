from __future__ import annotations

import argparse
from typing import Any, Dict, List, Tuple

from .collector import RESTRICTED_DOMAINS, access_mode_for_url, build_gdelt_topic_query_plan, collect_topic, enrich_topic
from .config import get_enabled_sources, load_gdelt_config, load_sources, load_watchlists, resolve_db_path
from .dedupe import dedupe_batch
from .digest import render_search_results_markdown, render_watchlist_digest_markdown
from .filters import apply_watchlists
from .ingest.fundus_adapter import enrich_article_fundus, fetch_fundus, fundus_status
from .ingest.gdelt import fetch_gdelt_metadata, gdelt_status
from .ingest.rss import fetch_rss
from .normalize import normalize_article, utc_now_iso
from .relevance import classify_watchlist_article
from .storage import Storage

SUPPORTED_MODES = ("rss", "fundus", "gdelt", "all")


def _load_runtime() -> tuple[Storage, List[Dict[str, Any]], List[Dict[str, Any]]]:
    storage = Storage(resolve_db_path())
    storage.init_db()

    sources = load_sources()
    for s in sources:
        s["updated_at"] = utc_now_iso()
    storage.upsert_sources(sources)

    watchlists = load_watchlists()
    storage.upsert_watchlists(watchlists)

    return storage, sources, watchlists


def _adapter_statuses() -> Dict[str, Dict[str, Any]]:
    return {
        "rss": {"adapter": "rss", "available": True, "message": "RSS adapter available."},
        "fundus": fundus_status(),
        "gdelt": gdelt_status(),
    }


def _select_sources_by_mode(sources: List[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
    enabled = get_enabled_sources(sources)
    if mode == "all":
        return enabled
    return [s for s in enabled if s.get("adapter", "rss") == mode]


def _find_watchlist(topic: str | None, watchlists: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    if not topic:
        return None
    topic_norm = topic.strip().lower()
    for watchlist in watchlists:
        name = (watchlist.get("name") or "").strip().lower()
        topic_name = (watchlist.get("topic") or "").strip().lower()
        if topic_norm in {name, topic_name}:
            return watchlist
    return None


def _ingest_source(
    source_cfg: Dict[str, Any],
    max_items: int,
    topic_watchlist: Dict[str, Any] | None = None,
) -> Tuple[List[Dict[str, Any]], str | None]:
    adapter = source_cfg.get("adapter", "rss")

    if adapter == "rss":
        try:
            return fetch_rss(source_cfg, max_items=max_items), None
        except Exception as exc:
            return [], f"RSS ingest failed for {source_cfg.get('name', 'unknown')}: {exc}"

    if adapter == "fundus":
        return fetch_fundus(source_cfg, max_items=max_items)

    if adapter == "gdelt":
        return fetch_gdelt_metadata(source_cfg, max_items=max_items, topic_watchlist=topic_watchlist)

    return [], f"Unknown adapter '{adapter}' for source {source_cfg.get('name', 'unknown')}"


def cmd_ingest(args: argparse.Namespace) -> int:
    storage, all_sources, watchlists = _load_runtime()
    adapter_status = _adapter_statuses()
    topic = getattr(args, "topic", None)
    topic_watchlist = _find_watchlist(topic, watchlists)

    if args.mode == "fundus" and not adapter_status["fundus"]["available"]:
        print(f"ERROR: {adapter_status['fundus']['message']}")
        storage.close()
        return 2

    selected_sources = _select_sources_by_mode(all_sources, args.mode)
    if not selected_sources:
        print(f"No enabled sources configured for mode '{args.mode}'.")
        storage.close()
        return 0

    inserted = 0
    skipped = 0
    matched = 0
    warnings: List[str] = []
    if topic and topic_watchlist is None:
        warnings.append(f"Watchlist topic '{topic}' not found. Proceeding without targeted topic ingestion.")

    try:
        for source_cfg in selected_sources:
            adapter = source_cfg.get("adapter", "rss")
            wl = topic_watchlist if adapter == "gdelt" else None
            raw_items, warning = _ingest_source(source_cfg, max_items=args.max_items, topic_watchlist=wl)
            if warning:
                warnings.append(warning)

            normalized = [normalize_article(item, source_cfg) for item in raw_items]
            normalized = dedupe_batch(normalized)

            for article in normalized:
                did_insert = storage.insert_article(article)
                if not did_insert:
                    skipped += 1
                    continue

                inserted += 1
                wl_matches = apply_watchlists(article, watchlists)
                for match in wl_matches:
                    storage.insert_match(article["id"], match)
                    matched += 1
    finally:
        storage.close()

    for warning in warnings:
        print(f"WARNING: {warning}")

    print(
        "Ingest complete: "
        f"mode={args.mode} inserted={inserted} skipped={skipped} "
        f"watchlist_matches={matched} warnings={len(warnings)}"
    )
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    storage, _, _ = _load_runtime()
    try:
        rows = storage.search_articles(
            query=args.query,
            source=args.source,
            days=args.days,
            limit=args.limit,
            min_terms=getattr(args, "min_terms", None),
        )
    finally:
        storage.close()

    title = f"Search Results: {args.query}"
    print(
        render_search_results_markdown(
            rows,
            title,
            mode=getattr(args, "mode", "broad"),
            show_weak_matches=getattr(args, "show_weak_matches", False),
            min_terms=getattr(args, "min_terms", None),
        )
    )
    return 0


def _watchlist_terms(topic: str, watchlists: List[Dict[str, Any]]) -> List[str]:
    topic_norm = topic.strip().lower()
    for watchlist in watchlists:
        name = (watchlist.get("name") or "").strip().lower()
        topic_name = (watchlist.get("topic") or "").strip().lower()
        if topic_norm in {name, topic_name}:
            keywords = watchlist.get("keywords") or []
            phrases = watchlist.get("phrases") or []
            terms = [t for t in (keywords + phrases) if t]
            return terms or [topic]
    return [topic]


def _digest_rank(row: Dict[str, Any]) -> tuple:
    relevance_rank = {"direct_match": 3, "near_miss": 2, "noise": 0}.get(row.get("relevance_class"), 0)
    confidence_rank = {"high": 3, "medium": 2, "low": 1}.get(row.get("confidence"), 0)
    match_count = sum(
        len(row.get(key) or [])
        for key in (
            "matched_context_terms",
            "matched_core_terms",
            "matched_event_triggers",
            "matched_financial_terms",
        )
    )
    source = (row.get("source") or "").lower()
    quality_rank = 2 if any(name in source for name in ("bbc", "guardian", "politico", "ap news", "dw", "spiegel", "le monde", "newsweek", "stripes", "jamestown")) else 1
    discovery = (row.get("discovery_source") or "").lower()
    discovery_rank = 2 if discovery == "gdelt" else 1
    enrichment_rank = 2 if row.get("enrichment_status") == "full_text_extracted" else 1
    return (
        relevance_rank,
        confidence_rank,
        match_count,
        discovery_rank,
        enrichment_rank,
        quality_rank,
        row.get("published_at", ""),
    )


def _candidate_diagnostics(rows: List[Dict[str, Any]], selected_count: int) -> Dict[str, Any]:
    return {
        "total_candidates_considered": len(rows),
        "direct_matches": sum(1 for row in rows if row.get("relevance_class") == "direct_match"),
        "near_misses": sum(1 for row in rows if row.get("relevance_class") == "near_miss"),
        "gdelt_candidates": sum(1 for row in rows if (row.get("discovery_source") or "").lower() == "gdelt"),
        "rss_candidates": sum(1 for row in rows if (row.get("discovery_source") or "").lower() in {"", "rss"} or not row.get("discovery_source")),
        "fundus_full_text_candidates": sum(1 for row in rows if row.get("enrichment_status") == "full_text_extracted"),
        "dropped_before_ranking": 0,
        "dropped_after_ranking": max(0, len(rows) - selected_count),
    }


def _reserve_gdelt_visibility(ordered: List[Dict[str, Any]], all_rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    if limit <= 0:
        return []
    selected = ordered[:limit]
    selected_ids = {row.get("id") for row in selected}
    gdelt_rows = [
        row
        for row in sorted(all_rows, key=_digest_rank, reverse=True)
        if (row.get("discovery_source") or "").lower() == "gdelt" and row.get("id") not in selected_ids
    ]
    if not gdelt_rows:
        return selected

    reserve_count = min(2, limit, len(gdelt_rows))
    rss_replaceable = [
        row
        for row in reversed(selected)
        if (row.get("discovery_source") or "").lower() != "gdelt"
        and row.get("relevance_class") != "direct_match"
    ]
    for gdelt_row, replace_row in zip(gdelt_rows[:reserve_count], rss_replaceable):
        replace_idx = selected.index(replace_row)
        selected[replace_idx] = gdelt_row
        selected_ids.add(gdelt_row.get("id"))
    return sorted(selected, key=_digest_rank, reverse=True)


def cmd_digest(args: argparse.Namespace) -> int:
    storage, _, watchlists = _load_runtime()
    watchlist = _find_watchlist(args.topic, watchlists)
    rows_by_id: Dict[str, Dict[str, Any]] = {}
    collector_status: Dict[str, Any] | None = None

    try:
        if watchlist:
            collector_status = storage.latest_collection_run(watchlist.get("name", args.topic))
            rows = storage.list_recent(days=args.days, source=args.source, limit=max(args.limit * 80, 1000))
            for row in rows:
                enriched = dict(row)
                if "text" not in enriched:
                    enriched["text"] = ""
                classification = classify_watchlist_article(enriched, watchlist)
                enriched.update(classification)
                rows_by_id[enriched["id"]] = enriched
        else:
            terms = _watchlist_terms(args.topic, watchlists)
            for term in terms:
                rows = storage.search_articles(
                    query=term,
                    source=args.source,
                    days=args.days,
                    limit=args.limit,
                )
                for row in rows:
                    rows_by_id[row["id"]] = row
    finally:
        storage.close()

    all_rows = [row for row in rows_by_id.values() if row.get("relevance_class") != "noise"]
    ranked_rows = sorted(all_rows, key=_digest_rank, reverse=True)
    ordered = _reserve_gdelt_visibility(ranked_rows, all_rows, args.limit) if watchlist else ranked_rows[: args.limit]
    diagnostics = _candidate_diagnostics(all_rows, selected_count=len(ordered))
    if watchlist:
        direct = [r for r in ordered if r.get("relevance_class") == "direct_match"]
        near = [r for r in ordered if r.get("relevance_class") == "near_miss"]
        print(
            render_watchlist_digest_markdown(
                topic=args.topic,
                days=args.days,
                direct_matches=direct,
                near_misses=near,
                watchlist=watchlist,
                collector_status=collector_status,
                candidate_diagnostics=diagnostics,
            )
        )
    else:
        print(render_watchlist_digest_markdown(args.topic, args.days, ordered, [], None))
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    storage, _, watchlists = _load_runtime()
    watchlist = _find_watchlist(args.topic, watchlists)
    if not watchlist:
        storage.close()
        print(f"ERROR: Watchlist topic '{args.topic}' not found.")
        return 2

    if getattr(args, "dry_run_queries", False):
        try:
            max_queries_arg = getattr(args, "max_queries", None)
            max_queries = max_queries_arg if max_queries_arg is not None else load_gdelt_config().get("max_queries_per_topic", 2)
            plan = build_gdelt_topic_query_plan(watchlist, max_queries=max_queries)
        finally:
            storage.close()
        print(f"# Planned GDELT Queries: {args.topic}")
        print(f"- Topic: {args.topic}")
        print(f"- Query count: {len(plan)}")
        print("")
        print("## Planned Queries")
        for idx, item in enumerate(plan, start=1):
            print(f"{idx}. {item['query']}")
            print(f"   Source: {item['source']}")
        return 0

    enrich = None if args.no_enrich else args.enrich
    try:
        result = collect_topic(
            storage,
            watchlist,
            days=args.days,
            max_items=args.max_items,
            gdelt_config=load_gdelt_config(),
            source=args.source,
            enrich=enrich,
            max_queries=getattr(args, "max_queries", None),
            use_cache_first=getattr(args, "use_cache_first", False),
        )
    finally:
        storage.close()

    for warning in result["warnings"]:
        print(f"WARNING: {warning}")
    query_statuses = result.get("query_statuses") or []
    if query_statuses:
        if any(item.get("status") == "cached" for item in query_statuses):
            print("Using cached GDELT results where available.")
        print("GDELT query status:")
        for item in query_statuses:
            print(f"- {item.get('status')}: {item.get('query')} ({item.get('source')})")
    print(
        "Collect complete: "
        f"topic={args.topic} source={args.source} status={result['status']} "
        f"queries={result['query_count']} inserted={result['inserted_count']} "
        f"updated={result['updated_count']} enriched={result['enriched_count']} "
        f"warnings={len(result['warnings'])}"
    )
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    storage, _, watchlists = _load_runtime()
    watchlist = _find_watchlist(args.topic, watchlists)
    if not watchlist:
        storage.close()
        print(f"ERROR: Watchlist topic '{args.topic}' not found.")
        return 2

    try:
        result = enrich_topic(
            storage,
            watchlist,
            days=args.days,
            adapter=args.adapter,
            max_items=args.max_items,
            include_rss=getattr(args, "include_rss", False),
        )
    finally:
        storage.close()

    for warning in result["warnings"]:
        print(f"WARNING: {warning}")
    breakdown = result.get("breakdown") or {}
    examples = result.get("examples") or []
    if breakdown:
        print("Enrichment breakdown:")
        for key in (
            "no_eligible_articles",
            "already_enriched",
            "restricted_paywall",
            "unsupported_source",
            "adapter_unavailable",
            "failed",
            "not_attempted",
        ):
            print(f"- {key}: {breakdown.get(key, 0)}")
    if examples:
        print("Skipped examples:")
        for example in examples[:5]:
            print(f"- {example.get('url', '')} | reason={example.get('reason', '')}")
    print(
        "Enrich complete: "
        f"topic={args.topic} adapter={args.adapter} enriched={result['enriched_count']} "
        f"warnings={len(result['warnings'])}"
    )
    return 0


def cmd_enrich_url(args: argparse.Namespace) -> int:
    if args.adapter != "fundus":
        print(f"ERROR: Unsupported enrichment adapter: {args.adapter}")
        return 2

    from urllib.parse import urlparse

    url = args.url
    domain = urlparse(url).netloc.lower()
    access_mode = access_mode_for_url(url)
    status = fundus_status()
    restricted = domain in RESTRICTED_DOMAINS or access_mode in {"metadata_only", "api_required", "licensed_api"}
    eligible = bool(status["available"]) and not restricted
    result = enrich_article_fundus({"url": url, "access_mode": access_mode}) if eligible or restricted else {"status": "adapter_unavailable"}
    extraction_status = result.get("status", "failed")
    title = result.get("title", "") or ""
    published_at = result.get("published_at", "") or result.get("published", "") or ""
    author = result.get("author", "") or ""
    text = result.get("text", "") or ""
    reason = result.get("reason") or extraction_status

    lines = [
        "# Enrich URL Diagnostic",
        f"- url: {url}",
        f"- domain: {domain or '-'}",
        f"- adapter availability: {'available' if status['available'] else 'unavailable'}",
        f"- access_mode decision: {access_mode}",
        f"- restricted/paywalled decision: {'yes' if restricted else 'no'}",
        f"- eligibility: {'eligible' if eligible else 'not_eligible'}",
        f"- extraction status: {extraction_status}",
        f"- title: {title or '-'}",
        f"- published_at: {published_at or '-'}",
        f"- author: {author or '-'}",
        f"- text_length: {len(text)}",
        f"- failure reason: {reason}",
    ]
    print("\n".join(lines))
    return 0


def cmd_sources(_: argparse.Namespace) -> int:
    storage, _, _ = _load_runtime()
    statuses = _adapter_statuses()
    try:
        rows = storage.list_sources()
    finally:
        storage.close()

    lines = ["# Sources", "", "## Adapter Status"]
    for adapter in ("rss", "fundus", "gdelt"):
        status = statuses[adapter]
        flag = "available" if status["available"] else "unavailable"
        lines.append(f"- {adapter}: {flag} ({status['message']})")

    lines.append("")
    lines.append("## Source List")
    for s in rows:
        enabled = "enabled" if s.get("enabled") else "disabled"
        adapter = s.get("adapter", "rss")
        adapter_flag = "available" if statuses.get(adapter, {}).get("available", True) else "unavailable"
        lines.append(
            f"- **{s.get('name')}** | type={s.get('source_type')} | adapter={adapter}({adapter_flag}) "
            f"| access={s.get('access_mode')} | url={s.get('url')} | {enabled}"
        )
    print("\n".join(lines))
    return 0


def cmd_stats(_: argparse.Namespace) -> int:
    storage, _, _ = _load_runtime()
    statuses = _adapter_statuses()
    try:
        stats = storage.stats()
    finally:
        storage.close()

    lines = [
        "# Stats",
        "",
        f"- Total articles: {stats['total_articles']}",
        f"- Enabled sources: {stats['enabled_sources']}",
        f"- Total watchlist matches: {stats['total_matches']}",
        "",
        "## Enabled Sources by Adapter",
    ]
    for row in stats["enabled_sources_by_adapter"]:
        lines.append(f"- {row['adapter']}: {row['count']}")

    lines.extend(["", "## Adapter Status"])
    for adapter in ("rss", "fundus", "gdelt"):
        status = statuses[adapter]
        flag = "available" if status["available"] else "unavailable"
        lines.append(f"- {adapter}: {flag} ({status['message']})")

    gdelt_runtime = stats.get("gdelt_runtime") or {}
    latest = gdelt_runtime.get("latest_run") or {}
    lines.extend(["", "## GDELT Runtime"])
    if latest:
        lines.append(f"- Last GDELT run: {latest.get('topic')} at {latest.get('finished_at') or latest.get('started_at')}")
        lines.append(f"- Last status: {latest.get('status')}")
    else:
        lines.append("- Last GDELT run: none")
        lines.append("- Last status: -")
    lines.append(f"- Last HTTP 429 time: {gdelt_runtime.get('last_429_time') or '-'}")
    lines.append(f"- Cache entries: {gdelt_runtime.get('cache_entries', 0)}")
    lines.append(f"- Fresh cache entries: {gdelt_runtime.get('fresh_cache_entries', 0)}")
    if gdelt_runtime.get("last_429_time"):
        lines.append("- Recommended next retry time: later; use --max-queries 1 --use-cache-first to avoid hammering GDELT.")
    else:
        lines.append("- Recommended next retry time: now, conservatively with --max-queries 1 --use-cache-first.")

    lines.extend(["", "## Articles by Source"])
    for row in stats["articles_by_source"]:
        lines.append(f"- {row['source']}: {row['count']}")
    print("\n".join(lines))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="news-intel", description="Local news intelligence pipeline MVP")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Fetch and store new articles")
    p_ingest.add_argument("--mode", choices=SUPPORTED_MODES, default="rss", help="Ingestion mode")
    p_ingest.add_argument("--max-items", type=int, default=50, help="Max items per source")
    p_ingest.add_argument("--topic", type=str, default=None, help="Optional watchlist topic for targeted gdelt ingest")
    p_ingest.set_defaults(func=cmd_ingest)

    p_collect = sub.add_parser("collect", help="Collect topic-relevant metadata, primarily from GDELT")
    p_collect.add_argument("--topic", required=True, type=str, help="Watchlist topic name")
    p_collect.add_argument("--days", type=int, default=7, help="Window in days")
    p_collect.add_argument("--max-items", type=int, default=100, help="Maximum articles to collect")
    p_collect.add_argument("--source", type=str, default="gdelt", help="Discovery source list, e.g. gdelt or gdelt,rss")
    p_collect.add_argument("--enrich", choices=("fundus",), default="fundus", help="Optional enrichment adapter")
    p_collect.add_argument("--no-enrich", action="store_true", help="Skip enrichment")
    p_collect.add_argument("--max-queries", type=int, default=None, help="Maximum GDELT queries to execute")
    p_collect.add_argument("--dry-run-queries", action="store_true", help="Print planned GDELT queries without network calls")
    p_collect.add_argument("--use-cache-first", action="store_true", help="Prefer and report fresh cached GDELT results")
    p_collect.set_defaults(func=cmd_collect)

    p_enrich = sub.add_parser("enrich", help="Enrich already collected articles")
    p_enrich.add_argument("--topic", required=True, type=str, help="Watchlist topic name")
    p_enrich.add_argument("--days", type=int, default=7, help="Window in days")
    p_enrich.add_argument("--adapter", choices=("fundus",), default="fundus", help="Enrichment adapter")
    p_enrich.add_argument("--max-items", type=int, default=50, help="Maximum articles to enrich")
    p_enrich.add_argument("--include-rss", action="store_true", help="Also consider matching RSS/public articles for enrichment")
    p_enrich.set_defaults(func=cmd_enrich)

    p_enrich_url = sub.add_parser("enrich-url", help="Diagnose optional URL enrichment for a public article")
    p_enrich_url.add_argument("url", type=str, help="Article URL to diagnose")
    p_enrich_url.add_argument("--adapter", choices=("fundus",), default="fundus", help="Enrichment adapter")
    p_enrich_url.set_defaults(func=cmd_enrich_url)

    p_search = sub.add_parser("search", help="Search ingested articles")
    p_search.add_argument("query", type=str, help="Keyword or phrase")
    p_search.add_argument("--source", type=str, default=None, help="Filter by source name")
    p_search.add_argument("--days", type=int, default=None, help="Only include last N days")
    p_search.add_argument("--limit", type=int, default=30)
    p_search.add_argument("--mode", choices=("broad", "precise"), default="broad", help="Search relevance mode")
    p_search.add_argument("--min-terms", type=int, default=None, help="Minimum number of query terms that must match")
    p_search.add_argument(
        "--show-weak-matches",
        action="store_true",
        help="When using --mode precise, include weak matches in a separate section",
    )
    p_search.set_defaults(func=cmd_search)

    p_digest = sub.add_parser("digest", help="Generate markdown digest for a topic")
    p_digest.add_argument("--topic", required=True, type=str, help="Topic name or query")
    p_digest.add_argument("--days", type=int, default=3, help="Window in days")
    p_digest.add_argument("--source", type=str, default=None, help="Filter by source name")
    p_digest.add_argument("--limit", type=int, default=30)
    p_digest.add_argument("--include-metadata-only", action="store_true", help="Explicitly allow relevant metadata-only records in digest output")
    p_digest.set_defaults(func=cmd_digest)

    p_sources = sub.add_parser("sources", help="List configured sources")
    p_sources.set_defaults(func=cmd_sources)

    p_stats = sub.add_parser("stats", help="Pipeline stats")
    p_stats.set_defaults(func=cmd_stats)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)
