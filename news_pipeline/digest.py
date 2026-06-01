from __future__ import annotations

import json
from typing import Dict, Iterable, List


def _trim(text: str, n: int = 240) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


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
