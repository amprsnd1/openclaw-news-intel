from __future__ import annotations

import json
from typing import Dict, Iterable, List


def _trim(text: str, n: int = 240) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


def _link(title: str, url: str) -> str:
    clean_title = title or "(untitled)"
    clean_url = (url or "").strip()
    if clean_url:
        return f"[{clean_title}]({clean_url})"
    return clean_title


def render_items_markdown(items: Iterable[Dict], title: str) -> str:
    lines: List[str] = [f"# {title}", ""]
    count = 0
    for item in items:
        count += 1
        keywords = item.get("keywords_matched")
        if isinstance(keywords, str):
            try:
                keywords = json.loads(keywords)
            except Exception:
                keywords = []
        keywords = keywords or []
        keyword_text = ", ".join(keywords) if keywords else "-"
        matched_terms = item.get("matched_terms") or []
        matched_terms_text = ", ".join(matched_terms) if matched_terms else "-"

        lines.extend(
            [
                f"## {item.get('title', '(untitled)')}",
                f"- Source: {item.get('source', 'unknown')}",
                f"- Date: {item.get('published_at', '')}",
                f"- URL: {item.get('url', '')}",
                f"- Access: {item.get('access_mode', 'public')}",
                f"- Summary: {_trim(item.get('summary', ''))}",
                f"- Matched terms: {matched_terms_text}",
                f"- Matched keywords: {keyword_text}",
                "",
            ]
        )

    if count == 0:
        lines.append("No results.")

    return "\n".join(lines)


def render_search_results_markdown(
    items: Iterable[Dict],
    title: str,
    mode: str = "broad",
    show_weak_matches: bool = False,
    min_terms: int | None = None,
) -> str:
    rows = list(items)
    direct = [r for r in rows if r.get("relevance_class") == "direct_match"]
    strong = [r for r in rows if r.get("relevance_class") == "strong_partial_match"]
    weak = [r for r in rows if r.get("relevance_class") == "weak_partial_match"]
    strong_or_direct = direct + strong

    lines: List[str] = [f"# {title}", ""]

    if min_terms is not None and not rows:
        lines.append(f"No results matched at least {min_terms} query terms.")
        return "\n".join(lines)

    if mode == "precise":
        if not strong_or_direct:
            lines.append("No direct or strong partial matches found.")
            if weak:
                weak_terms = sorted({term for row in weak for term in (row.get("matched_terms") or [])})
                if weak_terms:
                    lines.append("Weak matches exist, but only matched generic context terms:")
                    lines.append(f"- {', '.join(weak_terms)}")
                if not show_weak_matches:
                    lines.append("Use --show-weak-matches to display them.")
            lines.append("")

        if strong_or_direct:
            lines.extend(["## Results", ""])
            _append_search_items(lines, strong_or_direct)

        if show_weak_matches and weak:
            lines.extend(["", "## Weak Matches", ""])
            _append_search_items(lines, weak)
    else:
        if not rows:
            lines.append("No results.")
        else:
            lines.extend(["## Results", ""])
            _append_search_items(lines, rows)

    return "\n".join(lines).rstrip() + "\n"


def _append_search_items(lines: List[str], items: List[Dict]) -> None:
    for idx, item in enumerate(items, start=1):
        matched_terms = item.get("matched_terms") or []
        missing_terms = item.get("missing_terms") or []
        matched_text = ", ".join(matched_terms) if matched_terms else "-"
        missing_text = ", ".join(missing_terms) if missing_terms else "-"
        lines.extend(
            [
                f"{idx}. {_link(item.get('title', '(untitled)'), item.get('url', ''))}",
                f"   Source: {item.get('source', 'unknown')}",
                f"   Date: {item.get('published_at', '')}",
                f"   Matched terms: {matched_text}",
                f"   Missing terms: {missing_text}",
                f"   Relevance: {item.get('relevance_class', 'no_match')}",
                "",
            ]
        )


def render_watchlist_digest_markdown(
    topic: str,
    days: int,
    direct_matches: List[Dict],
    near_misses: List[Dict],
    watchlist: Dict | None,
    collector_status: Dict | None = None,
    candidate_diagnostics: Dict | None = None,
) -> str:
    lines: List[str] = [f"# Digest: {topic} (last {days} day(s))", ""]

    if watchlist:
        lines.extend(["## Collector Status", ""])
        if collector_status:
            warnings = collector_status.get("warnings") or []
            lines.append(f"- Last run status: {collector_status.get('status', 'unknown')}")
            lines.append(f"- Source: {collector_status.get('source', '-')}")
            lines.append(f"- Queries planned: {collector_status.get('query_count', 0)}")
            lines.append(f"- Inserted: {collector_status.get('inserted_count', 0)}")
            lines.append(f"- Updated: {collector_status.get('updated_count', 0)}")
            lines.append(f"- Enriched: {collector_status.get('enriched_count', 0)}")
            if warnings:
                lines.append(f"- Warnings: {len(warnings)}")
                for warning in warnings[:3]:
                    lines.append(f"- Warning detail: {warning}")
            else:
                lines.append("- Warnings: 0")
        else:
            lines.append("- No collection run recorded for this topic.")
        lines.append("")

    if candidate_diagnostics:
        lines.extend(["## Corpus / Candidate Diagnostics", ""])
        lines.append(f"- total candidates considered: {candidate_diagnostics.get('total_candidates_considered', 0)}")
        lines.append(f"- direct matches: {candidate_diagnostics.get('direct_matches', 0)}")
        lines.append(f"- near misses: {candidate_diagnostics.get('near_misses', 0)}")
        lines.append(f"- GDELT candidates: {candidate_diagnostics.get('gdelt_candidates', 0)}")
        lines.append(f"- RSS candidates: {candidate_diagnostics.get('rss_candidates', 0)}")
        lines.append(f"- Fundus/full-text candidates: {candidate_diagnostics.get('fundus_full_text_candidates', 0)}")
        lines.append(f"- dropped before ranking: {candidate_diagnostics.get('dropped_before_ranking', 0)}")
        lines.append(f"- dropped after ranking: {candidate_diagnostics.get('dropped_after_ranking', 0)}")
        warnings = (collector_status or {}).get("warnings") or []
        if any("rate_limited_stop" in str(w) or "429" in str(w) for w in warnings) and candidate_diagnostics.get("gdelt_candidates", 0):
            lines.append("- GDELT live collection was rate-limited. Showing existing cached/stored GDELT metadata where relevant.")
        lines.append("")

    if not direct_matches:
        if (watchlist or {}).get("name") == "europe_ru_war_preparations":
            lines.append("No direct war-preparation signals found for this period.")
        else:
            lines.append("No direct matches found for this period.")
        lines.append("")
    else:
        high = [item for item in direct_matches if item.get("confidence") == "high"]
        medium = [item for item in direct_matches if item.get("confidence") == "medium"]
        low = [item for item in direct_matches if item.get("confidence") not in {"high", "medium"}]

        if not high and (watchlist or {}).get("name") == "europe_ru_war_preparations":
            lines.append("No high-confidence war-preparation signals found.")
            lines.append("")

        lines.extend(["## High Confidence Direct Matches", ""])
        if high:
            _append_watchlist_items(lines, high)
        else:
            lines.append("None.")
            lines.append("")

        lines.extend(["## Medium Confidence Direct Matches", ""])
        if medium:
            _append_watchlist_items(lines, medium)
        else:
            lines.append("None.")
            lines.append("")

        lines.extend(["## Low Confidence Direct Matches", ""])
        if low:
            _append_watchlist_items(lines, low)
        else:
            lines.append("None.")
            lines.append("")

    if near_misses:
        lines.extend(["## Near Misses", ""])
        _append_watchlist_items(lines, near_misses)

    if watchlist:
        gaps = watchlist.get("briefing_focus") or []
        if gaps:
            lines.extend(["## Gaps"])
            for gap in gaps:
                lines.append(f"- {gap}")
            lines.append("")

        lines.extend(["## Suggested Targeted Ingestion", "Run:", "```bash"])
        lines.append(f'news-intel collect --topic "{watchlist.get("name", topic)}" --days 7 --max-items 50 --max-queries 2 --use-cache-first')
        lines.extend(["```", ""])

    return "\n".join(lines).rstrip() + "\n"


def _append_watchlist_items(lines: List[str], items: List[Dict]) -> None:
    for idx, item in enumerate(items, start=1):
        context = ", ".join(item.get("matched_context_terms") or []) or "-"
        core = ", ".join(item.get("matched_core_terms") or []) or "-"
        events = ", ".join(item.get("matched_event_triggers") or []) or "-"
        financial = ", ".join(item.get("matched_financial_terms") or []) or "-"
        discovery_source = item.get("discovery_source") or "-"
        enrichment_status = item.get("enrichment_status") or "not_attempted"
        lines.extend(
            [
                f"{idx}. {_link(item.get('title', '(untitled)'), item.get('url', ''))}",
                f"   Source: {item.get('source', 'unknown')}",
                f"   Date: {item.get('published_at', '')}",
                f"   Access mode: {item.get('access_mode', 'public')}",
                f"   Discovery source: {discovery_source}",
                f"   Enrichment: {enrichment_status}",
                f"   Relevance: {item.get('relevance_class', 'noise')}",
                f"   Confidence: {item.get('confidence', 'low')}",
                f"   Reason: {item.get('reason', '-')}",
                f"   Matched context terms: {context}",
                f"   Matched core terms: {core}",
                f"   Matched event triggers: {events}",
                f"   Matched financial terms: {financial}",
                "",
            ]
        )
