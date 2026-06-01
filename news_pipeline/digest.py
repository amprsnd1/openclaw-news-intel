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
) -> str:
    lines: List[str] = [f"# Digest: {topic} (last {days} day(s))", ""]

    if not direct_matches:
        lines.append("No direct matches found for this period.")
        lines.append("")
    else:
        lines.extend(["## Key Facts", ""])
        _append_watchlist_items(lines, direct_matches)
        lines.extend(["## Main Source List", ""])
        _append_watchlist_items(lines, direct_matches)

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
        lines.append(f'news-intel ingest --mode gdelt --topic "{watchlist.get("name", topic)}" --max-items 25')
        lines.extend(["```", ""])

    return "\n".join(lines).rstrip() + "\n"


def _append_watchlist_items(lines: List[str], items: List[Dict]) -> None:
    for idx, item in enumerate(items, start=1):
        context = ", ".join(item.get("matched_context_terms") or []) or "-"
        core = ", ".join(item.get("matched_core_terms") or []) or "-"
        events = ", ".join(item.get("matched_event_triggers") or []) or "-"
        financial = ", ".join(item.get("matched_financial_terms") or []) or "-"
        lines.extend(
            [
                f"{idx}. {_link(item.get('title', '(untitled)'), item.get('url', ''))}",
                f"   Source: {item.get('source', 'unknown')}",
                f"   Date: {item.get('published_at', '')}",
                f"   Access mode: {item.get('access_mode', 'public')}",
                f"   Relevance: {item.get('relevance_class', 'noise')}",
                f"   Matched context terms: {context}",
                f"   Matched core terms: {core}",
                f"   Matched event triggers: {events}",
                f"   Matched financial terms: {financial}",
                "",
            ]
        )
