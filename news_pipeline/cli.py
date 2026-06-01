from __future__ import annotations

import argparse
from typing import Any, Dict, List, Tuple

from .config import get_enabled_sources, load_sources, load_watchlists, resolve_db_path
from .dedupe import dedupe_batch
from .digest import render_search_results_markdown, render_watchlist_digest_markdown
from .filters import apply_watchlists
from .ingest.fundus_adapter import fetch_fundus, fundus_status
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


def cmd_digest(args: argparse.Namespace) -> int:
    storage, _, watchlists = _load_runtime()
    watchlist = _find_watchlist(args.topic, watchlists)
    rows_by_id: Dict[str, Dict[str, Any]] = {}

    try:
        if watchlist:
            rows = storage.list_recent(days=args.days, source=args.source, limit=max(args.limit * 30, 300))
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

    ordered = sorted(rows_by_id.values(), key=lambda r: r.get("published_at", ""), reverse=True)[: args.limit]
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
            )
        )
    else:
        print(render_watchlist_digest_markdown(args.topic, args.days, ordered, [], None))
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
