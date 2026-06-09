from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pytest

from news_pipeline.cli import cmd_scan
from news_pipeline.normalize import utc_now_iso
from news_pipeline.scanner import classify_signal, run_scan
from news_pipeline.storage import Storage


def _watchlist(**overrides):
    data = {
        "name": "europe_ru_war_preparations",
        "topic": "Europe Russia war preparations",
        "suggested_queries": ["NATO Russia readiness eastern Europe"],
        "context_terms": ["Europe", "Russia", "NATO", "Poland", "Baltic Sea", "Germany"],
        "core_terms": ["troop deployment", "civil defense", "defense spending", "air defense", "readiness"],
        "event_triggers": ["sabotage", "cyberattack"],
        "financial_and_policy_terms": ["procurement", "ammunition production"],
    }
    data.update(overrides)
    return data


def _sources():
    return [
        {
            "name": "BBC",
            "adapter": "rss",
            "url": "https://example.com/rss",
            "language": "en",
            "country": "UK",
            "access_mode": "rss",
            "enabled": True,
        }
    ]


def _rss_item(title: str, url: str = "https://bbc.com/news/1", summary: str = "") -> dict:
    return {
        "title": title,
        "url": url,
        "published": utc_now_iso(),
        "summary": summary,
        "text": "",
        "language": "en",
        "country": "UK",
    }


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    store = Storage(tmp_path / "news.sqlite")
    store.init_db()
    yield store
    store.close()


@pytest.fixture
def temp_db_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "news.sqlite"
    monkeypatch.setenv("NEWS_PIPELINE_DB", str(db_path))
    return db_path


def test_scan_topic_loads_watchlist_terms() -> None:
    signal = classify_signal(
        _rss_item("NATO deploys troops to Eastern Europe as Russia risk grows"),
        watchlist=_watchlist(),
    )

    assert signal["signal_class"] in {"high_signal", "medium_signal"}
    assert "nato" in signal["matched_context_terms"]


def test_scan_query_works_without_watchlist() -> None:
    signal = classify_signal(
        _rss_item("NATO troops move to eastern Europe", summary="Russia readiness concerns"),
        query="NATO troops eastern Europe",
    )

    assert signal["signal_class"] == "high_signal"
    assert "nato" in signal["matched_terms"]


def test_rss_scan_returns_headline_matches(monkeypatch, storage: Storage) -> None:
    monkeypatch.setattr(
        "news_pipeline.scanner.fetch_rss",
        lambda source_cfg, max_items=50: [
            _rss_item("Poland announces civil defense drills amid Russia threat"),
            _rss_item("Celebrity chef launches new show", "https://bbc.com/news/2"),
        ],
    )

    result = run_scan(storage, _sources(), _watchlist(), None, since="24h", sources="rss", only_new=False)

    assert result["source_status"]["rss"] == "ok"
    assert len(result["signals"]) == 1
    assert result["signals"][0]["signal_class"] == "medium_signal"


def test_google_news_rss_scan_parses_mocked_feed(monkeypatch, storage: Storage) -> None:
    class Feed:
        entries = [
            {
                "title": "Germany boosts air defense procurement",
                "link": "https://example.com/germany-air-defense",
                "published": utc_now_iso(),
                "summary": "Russia threat pushes Europe readiness.",
                "source": {"title": "Example News"},
            }
        ]

    monkeypatch.setattr("news_pipeline.scanner.feedparser.parse", lambda url: Feed())

    result = run_scan(
        storage,
        _sources(),
        _watchlist(),
        None,
        since="24h",
        sources="google_news_rss",
        only_new=False,
    )

    assert result["scanned_counts"]["google_news_rss"] == 1
    assert result["signals"][0]["source"] == "Example News"
    assert result["signals"][0]["signal_class"] == "high_signal"


def test_gdelt_scan_handles_429_gracefully(monkeypatch, storage: Storage) -> None:
    monkeypatch.setattr(
        "news_pipeline.scanner.fetch_gdelt_query",
        lambda *args, **kwargs: ({}, "GDELT rate limited (HTTP 429) for scan query."),
    )

    result = run_scan(storage, _sources(), _watchlist(), None, since="24h", sources="gdelt", only_new=False)

    assert result["source_status"]["gdelt"] == "rate-limited"
    assert result["signals"] == []
    assert any("429" in warning for warning in result["warnings"])


def test_scan_classifies_high_medium_low_and_noise() -> None:
    wl = _watchlist()

    high = classify_signal(_rss_item("Germany boosts air defense procurement amid Russia threat"), wl)
    medium = classify_signal(_rss_item("EU debates defense spending as Europe worries grow"), wl)
    low = classify_signal(_rss_item("NATO summit opens in Europe"), wl)
    noise = classify_signal(_rss_item("Milan mosaic restoration delights visitors"), wl)

    assert high["signal_class"] == "high_signal"
    assert medium["signal_class"] == "medium_signal"
    assert low["signal_class"] == "low_signal"
    assert noise["signal_class"] == "noise"


def test_scan_prevents_substring_false_positives() -> None:
    signal = classify_signal(_rss_item("Milan mosaic restoration opens to visitors"), _watchlist())

    assert signal["signal_class"] == "noise"
    assert "nato" not in signal["matched_terms"]


def test_only_new_hides_seen_and_show_seen_restores(monkeypatch, storage: Storage) -> None:
    monkeypatch.setattr(
        "news_pipeline.scanner.fetch_rss",
        lambda source_cfg, max_items=50: [
            _rss_item("Poland announces civil defense drills amid Russia threat"),
        ],
    )

    first = run_scan(storage, _sources(), _watchlist(), None, since="24h", sources="rss", only_new=True)
    second = run_scan(storage, _sources(), _watchlist(), None, since="24h", sources="rss", only_new=True)
    third = run_scan(storage, _sources(), _watchlist(), None, since="24h", sources="rss", only_new=True, show_seen=True)

    assert len(first["signals"]) == 1
    assert second["signals"] == []
    assert len(third["signals"]) == 1


def test_scan_dedupes_by_url_and_title(monkeypatch, storage: Storage) -> None:
    monkeypatch.setattr(
        "news_pipeline.scanner.fetch_rss",
        lambda source_cfg, max_items=50: [
            _rss_item("NATO deploys troops to Eastern Europe", "https://bbc.com/news/same"),
            _rss_item("NATO deploys troops to Eastern Europe", "https://bbc.com/news/other"),
            _rss_item("NATO deploys troops to Eastern Europe", "https://bbc.com/news/same"),
        ],
    )

    result = run_scan(storage, _sources(), _watchlist(), None, since="24h", sources="rss", only_new=False)

    assert len(result["signals"]) == 1


def test_scan_output_contains_required_fields(monkeypatch, capsys, temp_db_env: Path) -> None:
    monkeypatch.setattr(
        "news_pipeline.scanner.fetch_rss",
        lambda source_cfg, max_items=50: [
            _rss_item("Poland announces civil defense drills amid Russia threat"),
        ],
    )
    rc = cmd_scan(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            query=None,
            since="24h",
            max_items=50,
            source="rss",
            min_confidence="low",
            only_new=False,
            show_seen=False,
            format="markdown",
            max_queries=1,
            use_cache_first=False,
        )
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "# Signal Scan: europe_ru_war_preparations" in out
    assert "[Poland announces civil defense drills amid Russia threat](" in out
    assert "Source:" in out
    assert "Time:" in out
    assert "Matched terms:" in out
    assert "Confidence:" in out
    assert "Why it matters:" in out
