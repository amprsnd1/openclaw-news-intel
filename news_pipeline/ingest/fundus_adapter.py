from __future__ import annotations

import importlib.util
from typing import Any, Dict, List
from typing import Optional, Tuple
from urllib.parse import urlparse

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

PUBLIC_FUNDUS_DOMAINS = {
    "bbc.com",
    "www.bbc.com",
    "bbc.co.uk",
    "www.bbc.co.uk",
    "theguardian.com",
    "www.theguardian.com",
    "politico.eu",
    "www.politico.eu",
    "apnews.com",
    "www.apnews.com",
    "spiegel.de",
    "www.spiegel.de",
    "lemonde.fr",
    "www.lemonde.fr",
    "dw.com",
    "www.dw.com",
    "businessinsider.com",
    "www.businessinsider.com",
    "taipeitimes.com",
    "www.taipeitimes.com",
    "dailymaverick.co.za",
    "www.dailymaverick.co.za",
    "lrt.lt",
    "www.lrt.lt",
}


def fundus_status() -> Dict[str, Any]:
    available = importlib.util.find_spec("fundus") is not None
    if available:
        return {
            "adapter": "fundus",
            "available": True,
            "message": "Fundus adapter available.",
        }
    return {
        "adapter": "fundus",
        "available": False,
        "message": 'Fundus dependency missing. Install with: pip install "news-intel[fundus]"',
    }


def fetch_fundus(source_cfg: Dict[str, Any], max_items: int = 50) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Best-effort Fundus adapter.

    Expected source config fields:
    - fundus_collection: e.g. "us", "uk", "de"
    - fundus_publisher: optional publisher inside collection, e.g. "BBCNews"

    If Fundus is unavailable or config is incomplete, returns an empty list.
    """
    status = fundus_status()
    if not status["available"]:
        return [], status["message"]

    try:
        from fundus import Crawler, PublisherCollection
    except Exception as exc:
        return [], f"Fundus import failed: {exc}"

    collection_name = source_cfg.get("fundus_collection")
    publisher_name = source_cfg.get("fundus_publisher")
    if not collection_name:
        return [], f"Fundus source '{source_cfg.get('name', 'unknown')}' missing 'fundus_collection'."

    collection = getattr(PublisherCollection, collection_name, None)
    if collection is None:
        return [], f"Fundus collection '{collection_name}' not found."

    target = collection
    if publisher_name:
        target = getattr(collection, publisher_name, None)
        if target is None:
            return [], f"Fundus publisher '{publisher_name}' not found in collection '{collection_name}'."

    try:
        crawler = Crawler(target)
    except Exception as exc:
        return [], f"Fundus crawler init failed: {exc}"

    items: List[Dict[str, Any]] = []
    try:
        for article in crawler.crawl(max_articles=max_items):
            if article is None:
                continue
            items.append(
                {
                    "title": getattr(article, "title", "") or "",
                    "url": getattr(article, "url", "") or "",
                    "published": getattr(article, "publishing_date", "") or "",
                    "author": ", ".join(getattr(article, "authors", []) or []),
                    "summary": getattr(article, "description", "") or "",
                    "text": getattr(article, "plaintext", "") or getattr(article, "text", "") or "",
                    "language": source_cfg.get("language"),
                    "country": source_cfg.get("country", ""),
                }
            )
    except Exception as exc:
        return [], f"Fundus crawl failed: {exc}"
    return items, None


def enrich_article_fundus(article: Dict[str, Any]) -> Dict[str, Any]:
    url = article.get("url", "")
    domain = urlparse(url).netloc.lower()
    if domain in RESTRICTED_DOMAINS or article.get("access_mode") in {"metadata_only", "api_required", "licensed_api"}:
        return {"status": "paywall_or_restricted", "reason": "Restricted or metadata-only source."}

    status = fundus_status()
    if not status["available"]:
        return {"status": "adapter_unavailable", "reason": status["message"]}

    publisher = _publisher_for_domain(domain)
    if publisher is None:
        return {"status": "unsupported_source", "reason": f"Fundus URL extraction is not configured for domain: {domain}"}

    try:
        import requests
    except Exception as exc:
        return {"status": "failed", "reason": f"requests import failed: {exc}"}

    try:
        response = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "news-intel/0.1 public-source-enrichment"},
        )
    except requests.RequestException as exc:
        return {"status": "failed", "reason": f"request failed: {exc}"}

    if response.status_code in {401, 402, 403}:
        return {"status": "paywall_or_restricted", "reason": f"HTTP {response.status_code}"}
    if response.status_code >= 400:
        return {"status": "failed", "reason": f"HTTP {response.status_code}"}

    try:
        parsed = publisher.parser().parse(response.text, error_handling="suppress")
    except Exception as exc:
        return {"status": "failed", "reason": f"Fundus parse failed: {exc}"}

    if parsed.get("free_access") is False:
        return {"status": "paywall_or_restricted", "reason": "Fundus parser marked article as not freely accessible."}

    text = _body_to_text(parsed.get("body"))
    title = str(parsed.get("title") or article.get("title") or "")
    publishing_date = parsed.get("publishing_date") or article.get("published_at") or ""
    authors = parsed.get("authors") or []
    if hasattr(authors, "__iter__") and not isinstance(authors, str):
        author = ", ".join(str(a) for a in authors if a)
    else:
        author = str(authors or "")

    if not text.strip():
        return {
            "status": "failed",
            "reason": "Fundus parsed article but produced no body text.",
            "title": title,
            "published_at": str(publishing_date or ""),
            "author": author,
            "text": "",
            "text_length": 0,
        }

    return {
        "status": "full_text_extracted",
        "reason": "Fundus parser extracted public article text.",
        "title": title,
        "published_at": str(publishing_date or ""),
        "author": author,
        "summary": article.get("summary", ""),
        "text": text,
        "text_length": len(text),
    }


def _publisher_for_domain(domain: str):
    if domain not in PUBLIC_FUNDUS_DOMAINS:
        return None
    try:
        from fundus import PublisherCollection
    except Exception:
        return None

    mapping = {
        "bbc.com": PublisherCollection.uk.BBC,
        "www.bbc.com": PublisherCollection.uk.BBC,
        "bbc.co.uk": PublisherCollection.uk.BBC,
        "www.bbc.co.uk": PublisherCollection.uk.BBC,
        "theguardian.com": PublisherCollection.uk.TheGuardian,
        "www.theguardian.com": PublisherCollection.uk.TheGuardian,
        "politico.eu": PublisherCollection.be.PoliticoEu,
        "www.politico.eu": PublisherCollection.be.PoliticoEu,
        "apnews.com": PublisherCollection.us.APNews,
        "www.apnews.com": PublisherCollection.us.APNews,
        "spiegel.de": PublisherCollection.de.SpiegelOnline,
        "www.spiegel.de": PublisherCollection.de.SpiegelOnline,
        "lemonde.fr": PublisherCollection.fr.LeMonde,
        "www.lemonde.fr": PublisherCollection.fr.LeMonde,
        "dw.com": PublisherCollection.de.DW,
        "www.dw.com": PublisherCollection.de.DW,
        "businessinsider.com": PublisherCollection.us.BusinessInsider,
        "www.businessinsider.com": PublisherCollection.us.BusinessInsider,
        "taipeitimes.com": PublisherCollection.tw.TaipeiTimes,
        "www.taipeitimes.com": PublisherCollection.tw.TaipeiTimes,
        "dailymaverick.co.za": PublisherCollection.za.DailyMaverick,
        "www.dailymaverick.co.za": PublisherCollection.za.DailyMaverick,
        "lrt.lt": PublisherCollection.lt.LRT,
        "www.lrt.lt": PublisherCollection.lt.LRT,
    }
    return mapping.get(domain)


def _body_to_text(body: Any) -> str:
    if not body:
        return ""
    text = getattr(body, "text", None)
    if text:
        if callable(text):
            try:
                return str(text())
            except Exception:
                pass
        return str(text)
    if hasattr(body, "as_text_sequence"):
        try:
            return "\n".join(str(part) for part in body.as_text_sequence() if str(part).strip())
        except Exception:
            pass
    return str(body)
