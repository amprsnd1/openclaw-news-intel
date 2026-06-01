from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from news_pipeline.cli import cmd_digest
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
    source: str = "BBC",
    access_mode: str = "rss",
) -> None:
    published_at = _iso(1)
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
            "keywords_matched": [],
            "access_mode": access_mode,
            "created_at": published_at,
        }
    )


@pytest.fixture
def temp_db_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "news.sqlite"
    monkeypatch.setenv("NEWS_PIPELINE_DB", str(db_path))
    return db_path


def test_europe_watchlist_direct_requires_context_and_core(temp_db_env: Path, capsys) -> None:
    storage = Storage(temp_db_env)
    storage.init_db()

    _insert_article(
        storage,
        "direct",
        "Germany increases defense budget for air defense procurement amid Russia threat",
        "Europe boosts readiness with procurement and defense spending.",
        "NATO allies discuss troop deployment and military readiness.",
        source="Politico EU",
    )
    _insert_article(
        storage,
        "near_battlefield",
        "Ukraine battlefield update after Russian drone strikes",
        "Frontline operations update.",
        "Frontline clashes and strike footage from the conflict zone.",
        source="BBC",
    )
    _insert_article(
        storage,
        "near_shadow",
        "France seizes Russian shadow fleet tanker amid sanctions enforcement",
        "Sanctions enforcement operation at sea.",
        "Operation focused on maritime sanctions monitoring and vessel seizure.",
        source="Politico EU",
    )
    _insert_article(
        storage,
        "noise",
        "Milan bull mosaic restoration sparks mockery",
        "Art restoration news.",
        "Culture story unrelated to security.",
        source="The Guardian",
    )

    storage.close()

    rc = cmd_digest(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            days=7,
            source=None,
            limit=20,
        )
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "## Key Facts" in out
    assert "Germany increases defense budget for air defense procurement amid Russia threat" in out
    assert "Relevance: direct_match" in out

    # Near misses are separated.
    assert "## Near Misses" in out
    assert "Ukraine battlefield update after Russian drone strikes" in out
    assert "France seizes Russian shadow fleet tanker amid sanctions enforcement" in out

    key_facts_block = out.split("## Key Facts", 1)[1].split("## Main Source List", 1)[0]
    assert "Ukraine battlefield update after Russian drone strikes" not in key_facts_block
    assert "France seizes Russian shadow fleet tanker amid sanctions enforcement" not in key_facts_block

    # Noise is excluded.
    assert "Milan bull mosaic restoration sparks mockery" not in out


def test_no_direct_matches_returns_no_results_state(temp_db_env: Path, capsys) -> None:
    storage = Storage(temp_db_env)
    storage.init_db()

    _insert_article(
        storage,
        "near_only",
        "Ukraine battlefield update after Russian strikes",
        "Frontline report.",
        "Battlefield movements and frontline clashes were reported overnight.",
    )
    _insert_article(
        storage,
        "noise",
        "Colombia election update",
        "Election results.",
        "Domestic politics story.",
        source="The Guardian",
    )
    storage.close()

    rc = cmd_digest(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            days=7,
            source=None,
            limit=20,
        )
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "No direct matches found for this period." in out
    assert "## Near Misses" in out
    assert "Ukraine battlefield update after Russian strikes" in out
    assert "## Gaps" in out
    assert "## Suggested Targeted Ingestion" in out


def test_digest_displays_metadata_only_access_mode(temp_db_env: Path, capsys) -> None:
    storage = Storage(temp_db_env)
    storage.init_db()
    _insert_article(
        storage,
        "meta_direct",
        "NATO launches readiness exercise after Russian cyberattack on rail network",
        "EU emergency defense package raises procurement plans.",
        "Europe civil defense and defense spending policy response.",
        source="Reuters",
        access_mode="metadata_only",
    )
    storage.close()

    rc = cmd_digest(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            days=7,
            source=None,
            limit=20,
        )
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Access mode: metadata_only" in out
