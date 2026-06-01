from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from news_pipeline.storage import Storage


def _iso(days_ago: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.replace(microsecond=0).isoformat()


def _insert_article(storage: Storage, article_id: str, title: str, summary: str, text: str, published_at: str, keywords: list[str], source: str = "BBC") -> None:
    storage.insert_article(
        {
            "id": article_id,
            "source": source,
            "title": title,
            "url": f"https://example.com/{article_id}",
            "published_at": published_at,
            "author": "",
            "language": "en",
            "country": "UK",
            "summary": summary,
            "text": text,
            "topics": [],
            "keywords_matched": keywords,
            "access_mode": "rss",
            "created_at": published_at,
        }
    )


def test_single_word_search_works(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "news.sqlite")
    storage.init_db()
    _insert_article(storage, "a1", "Ukraine update", "Weekly update", "details", _iso(1), ["Ukraine"])

    rows = storage.search_articles("Ukraine", limit=10)
    storage.close()

    assert len(rows) == 1
    assert rows[0]["id"] == "a1"
    assert "ukraine" in rows[0]["matched_terms"]


def test_multi_word_partial_search_works(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "news.sqlite")
    storage.init_db()
    _insert_article(storage, "a1", "Ukraine market update", "No IMF mention", "", _iso(1), ["Ukraine"])
    _insert_article(storage, "a2", "Energy policy", "loan program overview", "", _iso(1.5), ["loan"])

    rows = storage.search_articles("Ukraine IMF loan", limit=10)
    storage.close()

    assert len(rows) >= 1
    returned_ids = {r["id"] for r in rows}
    assert "a1" in returned_ids or "a2" in returned_ids


def test_search_ranks_stronger_matches_above_weaker(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "news.sqlite")
    storage.init_db()
    _insert_article(
        storage,
        "strong",
        "Ukraine IMF loan package expands",
        "loan approved",
        "",
        _iso(0.5),
        ["Ukraine", "IMF", "loan"],
    )
    _insert_article(
        storage,
        "weak",
        "Ukraine update",
        "general update only",
        "",
        _iso(0.5),
        ["Ukraine"],
    )

    rows = storage.search_articles("Ukraine IMF loan", limit=10)
    storage.close()

    assert len(rows) >= 2
    assert rows[0]["id"] == "strong"


def test_search_returns_no_results_when_none_match(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "news.sqlite")
    storage.init_db()
    _insert_article(storage, "a1", "Energy transition", "grid reforms", "", _iso(1), ["energy"])

    rows = storage.search_articles("mars colony", limit=10)
    storage.close()

    assert rows == []


def test_search_does_not_require_optional_adapters(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "news.sqlite")
    storage.init_db()
    _insert_article(storage, "a1", "Ukraine fiscal outlook", "loan and debt", "", _iso(2), ["Ukraine", "loan"], source="The Guardian")

    rows = storage.search_articles("Ukraine loan", limit=10)
    storage.close()

    assert len(rows) == 1
    assert rows[0]["source"] == "The Guardian"
