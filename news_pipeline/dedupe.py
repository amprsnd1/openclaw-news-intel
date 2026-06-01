from __future__ import annotations

from typing import Dict, Iterable, List, Set

from .normalize import canonicalize_url, title_hash


def dedupe_batch(articles: Iterable[Dict]) -> List[Dict]:
    seen_urls: Set[str] = set()
    seen_titles: Set[str] = set()
    output: List[Dict] = []

    for article in articles:
        canon_url = canonicalize_url(article.get("url", ""))
        thash = title_hash(article.get("title", ""))

        if canon_url and canon_url in seen_urls:
            continue
        if thash and thash in seen_titles:
            continue

        if canon_url:
            seen_urls.add(canon_url)
        if thash:
            seen_titles.add(thash)

        output.append(article)

    return output
