from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .collector import RESTRICTED_DOMAINS, access_mode_for_url, build_gdelt_topic_query_plan, collect_topic, enrich_topic
from .config import (
    get_enabled_sources,
    load_gdelt_config,
    load_google_news_config,
    load_source_groups,
    load_source_quality,
    load_sources,
    load_watchlists,
    resolve_db_path,
)
from .dedupe import dedupe_batch
from .digest import render_search_results_markdown, render_watchlist_digest_markdown
from .filters import apply_watchlists
from .ingest.fundus_adapter import enrich_article_fundus, fetch_fundus, fundus_status
from .ingest.gdelt import fetch_gdelt_metadata, gdelt_status
from .ingest.rss import fetch_rss
from .normalize import normalize_article, utc_now_iso
from .relevance import classify_watchlist_article
from .scanner import render_all_watchlists_scan_markdown, render_scan_markdown, run_scan, source_diversity_note
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


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _openclaw_paths() -> Dict[str, Path]:
    home = Path.home()
    return {
        "project_skill": _project_root() / "openclaw-skills" / "news-intelligence" / "SKILL.md",
        "runtime_skill": home / ".openclaw" / "custom-skills" / "news-intelligence" / "SKILL.md",
        "config": home / ".openclaw" / "openclaw.json",
    }


def _detect_openclaw_registration() -> str:
    if not shutil.which("openclaw"):
        return "not detected (openclaw command not found)"
    try:
        result = subprocess.run(
            ["openclaw", "skills", "info", "news-intelligence"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception as exc:
        return f"not detected ({exc})"
    output = f"{result.stdout}\n{result.stderr}".lower()
    if result.returncode == 0 and ("ready" in output or "visible to model" in output or "available as command" in output):
        return "detected"
    return "not detected"


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


def _run_ingest(
    storage: Storage,
    all_sources: List[Dict[str, Any]],
    watchlists: List[Dict[str, Any]],
    mode: str,
    max_items: int,
    topic: str | None = None,
) -> Dict[str, Any]:
    topic_watchlist = _find_watchlist(topic, watchlists)
    selected_sources = _select_sources_by_mode(all_sources, mode)
    inserted = 0
    skipped = 0
    matched = 0
    warnings: List[str] = []

    if topic and topic_watchlist is None:
        warnings.append(f"Watchlist topic '{topic}' not found. Proceeding without targeted topic ingestion.")
    if not selected_sources:
        warnings.append(f"No enabled sources configured for mode '{mode}'.")
        return {"mode": mode, "inserted": 0, "skipped": 0, "matched": 0, "warnings": warnings}

    for source_cfg in selected_sources:
        adapter = source_cfg.get("adapter", "rss")
        wl = topic_watchlist if adapter == "gdelt" else None
        try:
            raw_items, warning = _ingest_source(source_cfg, max_items=max_items, topic_watchlist=wl)
        except Exception as exc:
            raw_items, warning = [], f"{adapter.upper()} ingest failed for {source_cfg.get('name', 'unknown')}: {exc}"
        if warning:
            warnings.append(warning)

        try:
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
        except Exception as exc:
            warnings.append(f"{adapter.upper()} ingest normalization/storage warning for {source_cfg.get('name', 'unknown')}: {exc}")

    return {"mode": mode, "inserted": inserted, "skipped": skipped, "matched": matched, "warnings": warnings}


def cmd_ingest(args: argparse.Namespace) -> int:
    storage, all_sources, watchlists = _load_runtime()
    adapter_status = _adapter_statuses()
    topic = getattr(args, "topic", None)

    if args.mode == "fundus" and not adapter_status["fundus"]["available"]:
        print(f"ERROR: {adapter_status['fundus']['message']}")
        storage.close()
        return 2

    try:
        result = _run_ingest(storage, all_sources, watchlists, args.mode, args.max_items, topic=topic)
    finally:
        storage.close()

    for warning in result["warnings"]:
        print(f"WARNING: {warning}")

    print(
        "Ingest complete: "
        f"mode={args.mode} inserted={result['inserted']} skipped={result['skipped']} "
        f"watchlist_matches={result['matched']} warnings={len(result['warnings'])}"
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


def cmd_scan(args: argparse.Namespace) -> int:
    storage, sources, watchlists = _load_runtime()
    source_groups = load_source_groups()
    source_quality = load_source_quality()
    gdelt_config = load_gdelt_config()
    google_news_config = load_google_news_config()
    fresh_ingest = None
    if getattr(args, "fresh", False):
        fresh_ingest = _run_ingest(
            storage,
            sources,
            watchlists,
            "rss",
            int(getattr(args, "fresh_max_items", 200) or 200),
        )

    if getattr(args, "all_watchlists", False):
        combined_signals: List[Dict[str, Any]] = []
        combined_rejected: List[Dict[str, Any]] = []
        rejected_by_topic: Dict[str, int] = {}
        statuses: Dict[str, str] = {"rss": "skipped", "google_news_rss": "skipped", "gdelt": "skipped", "fundus": "not used for scan"}
        warnings: List[str] = []
        source_refs: List[str] = []
        scanned_counts = {"rss": 0, "google_news_rss": 0, "gdelt": 0}
        new_items_scanned = 0
        candidate_matches_before_routing = 0
        suppressed_duplicates = 0
        rejected_by_hard_gates = 0
        reject_reason_counts: Dict[str, int] = {}
        diversity_notes: List[str] = []
        seen_ids: set[str] = set()
        try:
            for watchlist in watchlists:
                result = run_scan(
                    storage,
                    sources,
                    watchlist=watchlist,
                    query=None,
                    since=args.since,
                    max_items=args.max_items,
                    sources=args.source,
                    min_confidence=args.min_confidence,
                    only_new=args.only_new,
                    show_seen=args.show_seen,
                    max_queries=args.max_queries,
                    use_cache_first=args.use_cache_first,
                    gdelt_config=gdelt_config,
                    google_news_config=google_news_config,
                    source_groups=source_groups,
                    source_quality=source_quality,
                    all_watchlists=watchlists,
                    show_rejected=getattr(args, "show_rejected", False),
                    primary_only=False,
                    group_by_primary=True,
                )
                signals = []
                for row in result.get("signals") or []:
                    rid = row.get("id") or row.get("url")
                    candidate_matches_before_routing += 1
                    if rid in seen_ids:
                        suppressed_duplicates += 1
                        continue
                    if rid:
                        seen_ids.add(rid)
                    signals.append(row)
                combined_signals.extend(signals)
                combined_rejected.extend(result.get("rejected") or [])
                rejected_by_hard_gates += int(result.get("rejected_count") or 0)
                for reason, count in (result.get("reject_reason_counts") or {}).items():
                    reject_reason_counts[reason] = reject_reason_counts.get(reason, 0) + int(count)
                rejected = result.get("rejected_count", len(result.get("rejected") or []))
                topic_name = str(watchlist.get("name") or "")
                rejected_by_topic[topic_name] = rejected_by_topic.get(topic_name, 0) + int(rejected)
                for key, value in (result.get("source_status") or {}).items():
                    if value != "skipped":
                        statuses[key] = value
                warnings.extend(result.get("warnings") or [])
                for key in scanned_counts:
                    scanned_counts[key] += int((result.get("scanned_counts") or {}).get(key, 0))
                new_items_scanned += int(result.get("new_items_scanned") or 0)
                for ref in result.get("source_groups_used") or []:
                    if ref not in source_refs:
                        source_refs.append(ref)
        except ValueError as exc:
            storage.close()
            print(f"ERROR: {exc}")
            return 2
        finally:
            try:
                storage.close()
            except Exception:
                pass

        combined_signals.sort(
            key=lambda item: (
                {"high_signal": 3, "medium_signal": 2, "low_signal": 1}.get(item.get("signal_class"), 0),
                len(item.get("matched_terms") or []),
                item.get("published_at", ""),
            ),
            reverse=True,
        )
        final_signals = combined_signals[: args.max_items]
        summary: List[Dict[str, Any]] = []
        for watchlist in watchlists:
            name = str(watchlist.get("name") or "")
            topic_rows = [row for row in final_signals if row.get("primary_topic") == name]
            high = sum(1 for row in topic_rows if row.get("signal_class") == "high_signal")
            medium = sum(1 for row in topic_rows if row.get("signal_class") == "medium_signal")
            low = sum(1 for row in topic_rows if row.get("signal_class") == "low_signal")
            rejected = rejected_by_topic.get(name, 0)
            status = "HIGH ALERT" if high >= 3 else "Active" if high or medium else "Quiet" if low else "No direct signals"
            note = source_diversity_note(name, [row for row in topic_rows if row.get("signal_class") == "high_signal"])
            if note:
                diversity_notes.append(f"{name}: {note}")
            summary.append(
                {
                    "watchlist": name,
                    "high": high,
                    "medium": medium,
                    "low": low,
                    "rejected": rejected,
                    "status": status,
                }
            )
        result = {
            "topic": "all-watchlists",
            "since": args.since,
            "sources": source_refs,
            "source_status": statuses,
            "warnings": sorted(set(warnings)),
            "fresh_ingest": fresh_ingest,
            "scanned_counts": scanned_counts,
            "new_items_scanned": new_items_scanned,
            "signals": final_signals,
            "rejected": combined_rejected[: args.max_items] if getattr(args, "show_rejected", False) else [],
            "watchlist_summary": summary,
            "source_diversity_notes": diversity_notes,
            "routing_diagnostics": {
                "total_scanned": new_items_scanned,
                "candidate_matches_before_routing": candidate_matches_before_routing,
                "shown_signals_after_routing": len(final_signals),
                "suppressed_duplicates": suppressed_duplicates,
                "rejected_by_hard_gates": rejected_by_hard_gates,
                "top_reject_reasons": sorted(reject_reason_counts.items(), key=lambda item: item[1], reverse=True)[:5],
            },
        }
        print(render_all_watchlists_scan_markdown(result))
        return 0

    watchlist = _find_watchlist(args.topic, watchlists) if args.topic else None
    if args.topic and not watchlist:
        storage.close()
        print(f"ERROR: Watchlist topic '{args.topic}' not found.")
        return 2
    if not args.topic and not args.query:
        storage.close()
        print("ERROR: scan requires --topic or --query.")
        return 2
    try:
        result = run_scan(
            storage,
            sources,
            watchlist=watchlist,
            query=args.query,
            since=args.since,
            max_items=args.max_items,
            sources=args.source,
            min_confidence=args.min_confidence,
            only_new=args.only_new,
            show_seen=args.show_seen,
            max_queries=args.max_queries,
            use_cache_first=args.use_cache_first,
            gdelt_config=gdelt_config,
            google_news_config=google_news_config,
            source_groups=source_groups,
            source_quality=source_quality,
            all_watchlists=watchlists,
            show_rejected=getattr(args, "show_rejected", False),
            primary_only=getattr(args, "primary_only", False),
        )
        result["fresh_ingest"] = fresh_ingest
    except ValueError as exc:
        storage.close()
        print(f"ERROR: {exc}")
        return 2
    finally:
        try:
            storage.close()
        except Exception:
            pass

    print(render_scan_markdown(result))
    return 0


def cmd_morning_scan(args: argparse.Namespace) -> int:
    scan_args = argparse.Namespace(
        all_watchlists=True,
        topic=None,
        query=None,
        since=args.since,
        max_items=50,
        source=args.source,
        min_confidence=args.min_confidence,
        only_new=True,
        show_seen=args.show_seen,
        show_rejected=args.show_rejected,
        primary_only=False,
        group_by_primary=True,
        format="markdown",
        max_queries=1,
        use_cache_first=False,
        fresh=True,
        fresh_max_items=args.max_items,
    )
    return cmd_scan(scan_args)


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


def cmd_source_groups(_: argparse.Namespace) -> int:
    storage, sources, _ = _load_runtime()
    try:
        groups = load_source_groups()
    finally:
        storage.close()
    recommended = {
        "official_defense": "Europe-Russia war prep, defense monitoring",
        "official_eu": "EU policy, migration, energy, Ukraine financing",
        "official_financial": "Ukraine financing, fiscal/rates/debt, trade",
        "market_signals": "global trade, Ukraine financing, energy security",
        "defense_specialist": "war prep, China-Taiwan, Iran war risk",
        "european_local": "migration, Europe-Russia, regional early signals",
        "fast_headlines": "broad morning scans",
    }
    lines = ["# Source Groups", ""]
    for name, group in sorted(groups.items()):
        refs = [str(ref) for ref in group.get("sources", [])]
        summary = _source_group_health_summary(refs, sources)
        lines.append(f"- **{name}**")
        lines.append(f"  Description: {group.get('description') or '-'}")
        lines.append(f"  Configured sources: {summary['configured']}")
        lines.append(f"  Enabled sources: {summary['enabled']}")
        lines.append(f"  Disabled roadmap: {summary['disabled_roadmap']}")
        lines.append(f"  Partial feeds: {summary['partial_feed']}")
        lines.append(f"  Known working: {summary['working']}")
        lines.append(f"  Recommended topics: {recommended.get(name, '-')}")
    print("\n".join(lines))
    return 0


def _source_ref_matches(source: Dict[str, Any], ref: str) -> bool:
    key = (ref or "").strip().lower().replace(" ", "_")
    return key in {
        str(source.get("id") or "").strip().lower().replace(" ", "_"),
        str(source.get("name") or "").strip().lower().replace(" ", "_"),
        str(source.get("category") or "").strip().lower().replace(" ", "_"),
    }


def _source_status(source: Dict[str, Any]) -> str:
    return str(source.get("status") or "").strip().lower()


def _source_has_usable_feed(source: Dict[str, Any]) -> bool:
    url = str(source.get("url") or "").strip()
    return bool(url) and url != "roadmap-no-stable-feed"


def _source_health_details(source: Dict[str, Any]) -> Dict[str, str]:
    enabled = bool(source.get("enabled", True))
    status = _source_status(source)
    last_error = str(source.get("last_error") or "").strip()

    if status == "partial_feed":
        return {
            "health_state": "partial_feed",
            "last_fetch_status": "partial_feed",
            "last_error": last_error or "-",
        }
    if not enabled and status == "roadmap_no_stable_feed":
        return {
            "health_state": "disabled_roadmap",
            "last_fetch_status": "disabled_roadmap",
            "last_error": "roadmap_no_stable_feed",
        }
    if not enabled:
        return {
            "health_state": "disabled",
            "last_fetch_status": status or "disabled",
            "last_error": last_error or "-",
        }
    if status in {"fetch_error", "error", "failed", "http_error"} or last_error:
        return {
            "health_state": "failed_enabled",
            "last_fetch_status": status or "fetch_error",
            "last_error": last_error or status or "fetch_error",
        }
    if status in {"ok", "success", "local_config_ok", "enabled_live"} or _source_has_usable_feed(source):
        return {
            "health_state": "working",
            "last_fetch_status": status or "local_config_ok",
            "last_error": "-",
        }
    if status:
        return {
            "health_state": "unknown",
            "last_fetch_status": status,
            "last_error": last_error or "-",
        }
    return {
        "health_state": "not_checked",
        "last_fetch_status": "not_checked",
        "last_error": "-",
    }


def _sources_for_ref(ref: str, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    key = (ref or "").strip().lower().replace(" ", "_")
    if key == "rss":
        return [source for source in sources if source.get("adapter", "rss") == "rss"]
    if key in {"google_news_rss", "gdelt"}:
        return []
    return [source for source in sources if _source_ref_matches(source, ref)]


def _ref_health_details(ref: str, sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    key = (ref or "").strip().lower().replace(" ", "_")
    if key in {"google_news_rss", "gdelt"}:
        return {"enabled": True, "health_state": "working", "sources": []}

    ref_sources = _sources_for_ref(ref, sources)
    if not ref_sources:
        return {"enabled": False, "health_state": "unknown", "sources": []}

    enabled = any(bool(source.get("enabled", True)) for source in ref_sources)
    states = [_source_health_details(source)["health_state"] for source in ref_sources]
    priority = [
        "working",
        "partial_feed",
        "failed_enabled",
        "not_checked",
        "unknown",
        "disabled_roadmap",
        "disabled",
    ]
    state = next((candidate for candidate in priority if candidate in states), "unknown")
    return {"enabled": enabled, "health_state": state, "sources": ref_sources}


def _source_group_health_summary(refs: List[str], sources: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = {
        "configured": len(refs),
        "enabled": 0,
        "working": 0,
        "failed_enabled": 0,
        "disabled_roadmap": 0,
        "partial_feed": 0,
        "unknown": 0,
    }
    for ref in refs:
        details = _ref_health_details(ref, sources)
        state = str(details["health_state"])
        if details.get("enabled"):
            summary["enabled"] += 1
        if state == "working":
            summary["working"] += 1
        elif state == "failed_enabled":
            summary["failed_enabled"] += 1
        elif state == "disabled_roadmap":
            summary["disabled_roadmap"] += 1
        elif state == "partial_feed":
            summary["partial_feed"] += 1
        elif state in {"unknown", "not_checked"}:
            summary["unknown"] += 1
    return summary


def cmd_source_health(_: argparse.Namespace) -> int:
    storage, sources, _ = _load_runtime()
    try:
        groups = load_source_groups()
        rows = storage.list_recent(days=1, limit=10000)
    finally:
        storage.close()

    by_source: Dict[str, Dict[str, int]] = {}
    for row in rows:
        name = str(row.get("source") or "")
        data = by_source.setdefault(name, {"items": 0, "signals": 0})
        data["items"] += 1
        if row.get("stored_relevance_class") in {"direct_match", "near_miss"}:
            data["signals"] += 1

    lines = ["# Source Health", "", "## Groups"]
    for name, group in sorted(groups.items()):
        refs = [str(ref) for ref in group.get("sources", [])]
        group_sources = [source for ref in refs for source in _sources_for_ref(ref, sources)]
        summary = _source_group_health_summary(refs, sources)
        items = sum(by_source.get(str(source.get("name")), {}).get("items", 0) for source in group_sources)
        signals = sum(by_source.get(str(source.get("name")), {}).get("signals", 0) for source in group_sources)
        rate = (signals / items) if items else 0.0
        lines.append(f"- **{name}**")
        lines.append(f"  Description: {group.get('description') or '-'}")
        lines.append(f"  Configured source count: {summary['configured']}")
        lines.append(f"  Enabled source count: {summary['enabled']}")
        lines.append(f"  Working enabled source count: {summary['working']}")
        lines.append(f"  Failed enabled source count: {summary['failed_enabled']}")
        lines.append(f"  Disabled roadmap source count: {summary['disabled_roadmap']}")
        lines.append(f"  Partial feed source count: {summary['partial_feed']}")
        lines.append(f"  Unknown/not checked source count: {summary['unknown']}")
        lines.append(f"  Items last 24h: {items}")
        lines.append(f"  Signals last 24h: {signals}")
        lines.append(f"  Signal rate: {rate:.2f}")
        lines.append("  Last error: -")
        lines.append("  Last checked: local metadata only")

    lines.extend(["", "## Sources"])
    for source in sorted(sources, key=lambda s: str(s.get("id") or s.get("name"))):
        name = str(source.get("name"))
        counts = by_source.get(name, {"items": 0, "signals": 0})
        details = _source_health_details(source)
        status = source.get("status") or details["health_state"]
        lines.append(f"- **{source.get('id') or name}** | {name}")
        lines.append(f"  Group/category: {source.get('category', source.get('adapter', '-'))}")
        lines.append(f"  Enabled: {bool(source.get('enabled', True))}")
        lines.append(f"  Status: {status}")
        lines.append(f"  Access mode: {source.get('access_mode', '-')}")
        lines.append(f"  Health state: {details['health_state']}")
        lines.append(f"  Last fetch status: {details['last_fetch_status']}")
        lines.append(f"  Items last 24h: {counts.get('items', 0)}")
        lines.append(f"  Signals last 24h: {counts.get('signals', 0)}")
        lines.append(f"  Last error: {details['last_error']}")
        lines.append("  Last checked: local metadata only")
    print("\n".join(lines))
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    fatal: List[str] = []
    degraded: List[str] = []
    root = _project_root()
    config_files = [root / "config" / "sources.yaml", root / "config" / "watchlists.yaml"]
    db_path = resolve_db_path()

    cli_path = shutil.which("news-intel") or sys.argv[0]
    config_ok = all(path.exists() for path in config_files)
    if not config_ok:
        missing = ", ".join(str(path) for path in config_files if not path.exists())
        fatal.append(f"missing config file(s): {missing}")

    sources: List[Dict[str, Any]] = []
    watchlists: List[Dict[str, Any]] = []
    source_groups: Dict[str, Dict[str, Any]] = {}
    gdelt_runtime: Dict[str, Any] = {}
    database_ok = False
    rss_ok = False
    google_ok = False
    watchlists_ok = False
    groups_ok = False

    try:
        if config_ok:
            sources = load_sources()
            watchlists = load_watchlists()
            source_groups = load_source_groups()
            google_cfg = load_google_news_config()
            rss_ok = any(s.get("enabled", True) and s.get("adapter", "rss") == "rss" for s in sources)
            google_ok = bool(google_cfg.get("enabled", True))
            watchlists_ok = bool(watchlists)
            groups_ok = bool(source_groups)
            failed_enabled_sources = [
                str(source.get("id") or source.get("name"))
                for source in sources
                if _source_health_details(source)["health_state"] == "failed_enabled"
            ]
            if not rss_ok:
                fatal.append("no enabled RSS sources configured")
            if not watchlists_ok:
                fatal.append("no watchlists loaded")
            if not groups_ok:
                fatal.append("no source groups loaded")
            if not google_ok:
                degraded.append("Google News RSS unavailable")
            if failed_enabled_sources:
                degraded.append(f"enabled source failures: {', '.join(failed_enabled_sources[:5])}")
    except Exception as exc:
        fatal.append(f"config load failed: {exc}")

    storage: Storage | None = None
    try:
        storage = Storage(db_path)
        storage.init_db()
        stats = storage.stats()
        gdelt_runtime = stats.get("gdelt_runtime") or {}
        database_ok = True
    except Exception as exc:
        fatal.append(f"database check failed: {exc}")
    finally:
        if storage is not None:
            try:
                storage.close()
            except Exception:
                pass

    statuses = _adapter_statuses()
    gdelt = statuses["gdelt"]
    fundus = statuses["fundus"]
    if not fundus.get("available"):
        degraded.append("Fundus unavailable")
    if not gdelt.get("available"):
        degraded.append("GDELT unavailable")
    if gdelt_runtime.get("last_429_time"):
        degraded.append("GDELT recently rate-limited")

    paths = _openclaw_paths()
    project_skill_found = paths["project_skill"].exists()
    runtime_skill_found = paths["runtime_skill"].exists()
    registration = _detect_openclaw_registration()
    if not project_skill_found:
        degraded.append("OpenClaw project skill missing")
    if not runtime_skill_found:
        degraded.append("OpenClaw runtime skill missing")
    if registration != "detected":
        degraded.append("OpenClaw skill registration not detected")

    gdelt_message = "available" if gdelt.get("available") else "unavailable"
    if gdelt_runtime.get("last_429_time"):
        gdelt_message += f", last 429: {gdelt_runtime.get('last_429_time')}, retry later"
    else:
        gdelt_message += f" ({gdelt.get('message', '')})"
    fundus_message = "available" if fundus.get("available") else f"unavailable ({fundus.get('message', '')})"

    status_label = "broken" if fatal else "usable_but_degraded" if degraded else "usable"
    lines = [
        "news-intel doctor",
        "Core:",
        f"  Python: ok ({sys.version.split()[0]})",
        f"  CLI: {'ok' if cli_path else 'missing'} ({cli_path or '-'})",
        f"  Config: {'ok' if config_ok else 'missing'}",
        f"  Database: {'ok' if database_ok else 'broken'} ({db_path})",
        f"  Watchlists: {'ok' if watchlists_ok else 'missing'} ({len(watchlists)})",
        f"  Source groups: {'ok' if groups_ok else 'missing'} ({len(source_groups)})",
        "Adapters:",
        f"  RSS: {'ok' if rss_ok else 'missing'}",
        f"  Google News RSS: {'ok' if google_ok else 'disabled'}",
        f"  GDELT: {gdelt_message}",
        f"  Fundus: {fundus_message}",
        "OpenClaw:",
        f"  Project skill: {'found' if project_skill_found else 'missing'} ({paths['project_skill']})",
        f"  Runtime skill: {'found' if runtime_skill_found else 'missing'} ({paths['runtime_skill']})",
        f"  Registration: {registration}",
        "  Recommended command: news-intel morning-scan",
    ]
    if fatal:
        lines.append("Fatal issues:")
        for item in fatal:
            lines.append(f"  - {item}")
    if degraded:
        lines.append("Degraded components:")
        for item in degraded:
            lines.append(f"  - {item}")
        lines.append("Why this is not fatal:")
        lines.append("  - RSS scanning still works when core config, database, and RSS sources are healthy.")
        lines.append("  - morning-scan still works without optional metadata/enrichment adapters.")
        lines.append("  - GDELT, Google News RSS, Fundus, OpenClaw registration, and non-core feeds are optional or external.")
        lines.append("Recommended action:")
        if gdelt_runtime.get("last_429_time"):
            lines.append("  - Retry GDELT later; use conservative --max-queries and --use-cache-first.")
        if not gdelt.get("available"):
            lines.append("  - Check GDELT adapter availability only if topic collection needs it.")
        if not fundus.get("available"):
            lines.append("  - Install optional Fundus extras only if public article enrichment is needed.")
        if not google_ok:
            lines.append("  - Re-enable Google News RSS only if query headline discovery is needed.")
        if any("OpenClaw" in item for item in degraded):
            lines.append("  - Run scripts/install_openclaw_skill.sh if OpenClaw should use the skill.")
        if any(item.startswith("enabled source failures") for item in degraded):
            lines.append("  - Run news-intel source-health to inspect failed_enabled sources.")
        lines.append("  - Use news-intel morning-scan for normal operation.")
    lines.append(f"Status: {status_label}")
    print("\n".join(lines))

    if fatal:
        return 1
    if degraded:
        return 2
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
    parser = argparse.ArgumentParser(prog="news-intel", description="Local headline signal scanner for OpenClaw agents. Start with: news-intel morning-scan")
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

    p_scan = sub.add_parser("scan", help="Fast headline signal scan for a watchlist topic or free-form query")
    subject = p_scan.add_mutually_exclusive_group(required=True)
    subject.add_argument("--topic", type=str, help="Watchlist topic name")
    subject.add_argument("--query", type=str, help="Free-form headline query")
    subject.add_argument("--all-watchlists", action="store_true", help="Scan all configured watchlists")
    p_scan.add_argument("--since", type=str, default="6h", help="Lookback window such as 2h, 24h, or 7d")
    p_scan.add_argument("--max-items", type=int, default=50, help="Maximum signals/items to return")
    p_scan.add_argument("--source", type=str, default=None, help="Comma-separated sources or groups. Omit for topic default scan sources.")
    p_scan.add_argument("--min-confidence", choices=("low", "medium", "high"), default="low", help="Minimum signal tier")
    p_scan.add_argument("--only-new", action="store_true", default=True, help="Hide items already shown by prior scans")
    p_scan.add_argument("--show-seen", action="store_true", help="Show items already returned by prior scans")
    p_scan.add_argument("--show-rejected", action="store_true", help="Show rejected or demoted candidate headlines with reasons")
    p_scan.add_argument("--primary-only", action="store_true", help="Show each article only under its primary watchlist topic")
    p_scan.add_argument("--group-by-primary", action="store_true", help="For all-watchlists scans, keep signals and group each item once under its best primary topic")
    p_scan.add_argument("--format", choices=("markdown",), default="markdown", help="Output format")
    p_scan.add_argument("--max-queries", type=int, default=1, help="Maximum GDELT/Google query plans to use")
    p_scan.add_argument("--use-cache-first", action="store_true", help="Prefer fresh cached GDELT results")
    p_scan.add_argument("--fresh", action="store_true", help="Run fresh RSS ingest before scanning")
    p_scan.add_argument("--fresh-max-items", type=int, default=200, help="RSS max items per source for --fresh")
    p_scan.set_defaults(func=cmd_scan)

    p_morning = sub.add_parser("morning-scan", help="Primary workflow: fresh RSS ingest plus all-watchlists morning signal scan")
    p_morning.add_argument("--since", type=str, default="24h", help="Lookback window such as 24h or 7d")
    p_morning.add_argument("--min-confidence", choices=("low", "medium", "high"), default="medium", help="Minimum signal tier")
    p_morning.add_argument("--max-items", type=int, default=200, help="Fresh RSS ingest max items per source")
    p_morning.add_argument("--show-rejected", action="store_true", help="Show rejected or demoted candidate headlines with reasons")
    p_morning.add_argument("--show-seen", action="store_true", help="Show items already returned by prior scans")
    p_morning.add_argument("--source", type=str, default=None, help="Optional comma-separated sources or groups")
    p_morning.set_defaults(func=cmd_morning_scan)

    p_digest = sub.add_parser("digest", help="Generate markdown digest for a topic")
    p_digest.add_argument("--topic", required=True, type=str, help="Topic name or query")
    p_digest.add_argument("--days", type=int, default=3, help="Window in days")
    p_digest.add_argument("--source", type=str, default=None, help="Filter by source name")
    p_digest.add_argument("--limit", type=int, default=30)
    p_digest.add_argument("--include-metadata-only", action="store_true", help="Explicitly allow relevant metadata-only records in digest output")
    p_digest.set_defaults(func=cmd_digest)

    p_sources = sub.add_parser("sources", help="List configured sources")
    p_sources.set_defaults(func=cmd_sources)

    p_source_groups = sub.add_parser("source-groups", help="List configured scan source groups")
    p_source_groups.set_defaults(func=cmd_source_groups)

    p_source_health = sub.add_parser("source-health", help="Report local/cached source coverage diagnostics")
    p_source_health.set_defaults(func=cmd_source_health)

    p_doctor = sub.add_parser("doctor", help="Diagnose local setup, adapters, database, and OpenClaw skill visibility")
    p_doctor.set_defaults(func=cmd_doctor)

    p_stats = sub.add_parser("stats", help="Pipeline stats")
    p_stats.set_defaults(func=cmd_stats)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)
