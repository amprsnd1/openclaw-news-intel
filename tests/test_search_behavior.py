from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from news_pipeline.cli import cmd_search
from news_pipeline.storage import Storage


def _iso(days_ago: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.replace(microsecond=0).isoformat()


def _insert_article(
    storage: Storage,
    article_id: str,
    title: str,
    summary: str,
    text: str,
    published_at: str,
    keywords: list[str],
    source: str = "BBC",
) -> None:
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


def _storage(tmp_path: Path) -> Storage:
    storage = Storage(tmp_path / "news.sqlite")
    storage.init_db()
    return storage


def test_whole_word_nato_does_not_match_milan_or_donation(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    _insert_article(storage, "milan", "Milan mosaic restoration", "Art story", "", _iso(1), ["art"])
    _insert_article(storage, "donation", "Relief donation campaign", "fundraiser", "", _iso(1), ["aid"])
    _insert_article(storage, "nato", "NATO summit in Brussels", "alliance statement", "", _iso(1), ["NATO"])

    rows = storage.search_articles("NATO", limit=10)
    storage.close()

    ids = [r["id"] for r in rows]
    assert "nato" in ids
    assert "milan" not in ids
    assert "donation" not in ids


def test_whole_word_eu_does_not_match_unrelated_substrings(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    _insert_article(storage, "noise", "Eulogy in Paris", "cultural event", "", _iso(1), ["culture"])
    _insert_article(storage, "eu", "EU migration pact vote", "policy shift", "", _iso(1), ["EU"])

    rows = storage.search_articles("EU", limit=10)
    storage.close()

    ids = [r["id"] for r in rows]
    assert "eu" in ids
    assert "noise" not in ids


def test_whole_word_war_does_not_match_software(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    _insert_article(storage, "soft", "New software release", "tech", "", _iso(1), ["software"])
    _insert_article(storage, "war", "War economy planning", "defense update", "", _iso(1), ["war"])

    rows = storage.search_articles("war", limit=10)
    storage.close()

    ids = [r["id"] for r in rows]
    assert "war" in ids
    assert "soft" not in ids


def test_whole_word_aid_does_not_match_said(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    _insert_article(storage, "said", "He said policy may change", "quote", "", _iso(1), ["quote"])
    _insert_article(storage, "aid", "EU aid package approved", "finance", "", _iso(1), ["aid"])

    rows = storage.search_articles("aid", limit=10)
    storage.close()

    ids = [r["id"] for r in rows]
    assert "aid" in ids
    assert "said" not in ids


def test_sanctions_still_matches_sanctions(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    _insert_article(storage, "s1", "Sanctions package expanded", "new sanctions", "", _iso(1), ["sanctions"])

    rows = storage.search_articles("sanctions", limit=10)
    storage.close()

    assert len(rows) == 1
    assert rows[0]["id"] == "s1"


def test_search_ranks_by_relevance_class(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    _insert_article(storage, "direct", "Ukraine IMF loan package", "IMF loan for Ukraine", "", _iso(1), ["Ukraine", "IMF", "loan"])
    _insert_article(storage, "strong", "Ukraine loan package", "budget support", "", _iso(1), ["Ukraine", "loan"])
    _insert_article(storage, "weak", "Ukraine battlefield update", "military news", "", _iso(1), ["Ukraine"])

    rows = storage.search_articles("Ukraine IMF loan", limit=10)
    storage.close()

    assert [r["id"] for r in rows[:3]] == ["direct", "strong", "weak"]
    assert rows[0]["relevance_class"] == "direct_match"
    assert rows[1]["relevance_class"] == "strong_partial_match"
    assert rows[2]["relevance_class"] == "weak_partial_match"


def test_min_terms_excludes_one_term_matches(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    _insert_article(storage, "strong", "Ukraine loan package", "support", "", _iso(1), ["Ukraine", "loan"])
    _insert_article(storage, "weak", "Ukraine update", "military", "", _iso(1), ["Ukraine"])

    rows = storage.search_articles("Ukraine IMF loan", limit=10, min_terms=2)
    storage.close()

    assert [r["id"] for r in rows] == ["strong"]


def test_mode_precise_hides_weak_by_default(monkeypatch, tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "news.sqlite"
    monkeypatch.setenv("NEWS_PIPELINE_DB", str(db_path))
    storage = Storage(db_path)
    storage.init_db()
    _insert_article(storage, "weak", "Ukraine update", "general update", "", _iso(1), ["Ukraine"])
    storage.close()

    rc = cmd_search(
        argparse.Namespace(
            query="Ukraine IMF loan",
            source=None,
            days=None,
            limit=10,
            mode="precise",
            min_terms=None,
            show_weak_matches=False,
        )
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "No direct or strong partial matches found." in out
    assert "Use --show-weak-matches to display them." in out
    assert "## Weak Matches" not in out


def test_mode_precise_show_weak_matches(monkeypatch, tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "news.sqlite"
    monkeypatch.setenv("NEWS_PIPELINE_DB", str(db_path))
    storage = Storage(db_path)
    storage.init_db()
    _insert_article(storage, "weak", "Ukraine update", "general update", "", _iso(1), ["Ukraine"])
    storage.close()

    rc = cmd_search(
        argparse.Namespace(
            query="Ukraine IMF loan",
            source=None,
            days=None,
            limit=10,
            mode="precise",
            min_terms=None,
            show_weak_matches=True,
        )
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "## Weak Matches" in out
    assert "Relevance: weak_partial_match" in out


def test_search_output_contains_markdown_link_and_terms(monkeypatch, tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "news.sqlite"
    monkeypatch.setenv("NEWS_PIPELINE_DB", str(db_path))
    storage = Storage(db_path)
    storage.init_db()
    _insert_article(storage, "a1", "Ukraine IMF loan package", "Financing deal", "", _iso(1), ["Ukraine", "IMF", "loan"])
    storage.close()

    rc = cmd_search(
        argparse.Namespace(
            query="Ukraine IMF loan",
            source=None,
            days=None,
            limit=10,
            mode="broad",
            min_terms=None,
            show_weak_matches=False,
        )
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "[Ukraine IMF loan package](https://example.com/a1)" in out
    assert "Matched terms: imf, loan, ukraine" in out
    assert "Missing terms: -" in out
    assert "Relevance: direct_match" in out


def test_search_does_not_require_optional_adapters(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    _insert_article(storage, "a1", "Ukraine fiscal outlook", "loan and debt", "", _iso(2), ["Ukraine", "loan"], source="The Guardian")

    rows = storage.search_articles("Ukraine loan", limit=10)
    storage.close()

    assert len(rows) == 1
    assert rows[0]["source"] == "The Guardian"
