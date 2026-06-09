from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pytest

from news_pipeline.cli import cmd_scan, cmd_source_groups, cmd_source_health
from news_pipeline.config import load_source_groups
from news_pipeline.normalize import utc_now_iso
from news_pipeline.scanner import classify_signal, resolve_scan_sources, run_scan
from news_pipeline.storage import Storage


def _watchlist(**overrides):
    data = {
        "name": "europe_ru_war_preparations",
        "topic": "Europe Russia war preparations",
        "default_scan_sources": ["defense_specialist", "google_news_rss"],
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


def _group_sources():
    return [
        {
            "id": "uk_mod",
            "name": "UK Ministry of Defence",
            "adapter": "rss",
            "category": "official_defense",
            "url": "https://example.com/uk-mod.atom",
            "language": "en",
            "country": "UK",
            "access_mode": "public",
            "enabled": True,
        },
        {
            "id": "defense_news",
            "name": "Defense News",
            "adapter": "rss",
            "category": "defense_specialist",
            "url": "https://example.com/defense-news.rss",
            "language": "en",
            "country": "US",
            "access_mode": "public",
            "enabled": True,
        },
        {
            "id": "dw",
            "name": "Deutsche Welle",
            "adapter": "rss",
            "category": "european_local",
            "url": "https://example.com/dw.rss",
            "language": "en",
            "country": "DE",
            "access_mode": "public",
            "enabled": True,
        },
        {
            "id": "ecb",
            "name": "European Central Bank",
            "adapter": "rss",
            "category": "market_signals",
            "url": "https://example.com/ecb.rss",
            "language": "en",
            "country": "EU",
            "access_mode": "public",
            "enabled": True,
        },
    ]


def _source_groups():
    return {
        "official_defense": {"description": "official defense", "sources": ["uk_mod"]},
        "official_eu": {"description": "official eu", "sources": []},
        "official_financial": {"description": "official financial", "sources": ["ecb"]},
        "defense_specialist": {"description": "defense", "sources": ["defense_news"]},
        "european_local": {"description": "local", "sources": ["dw"]},
        "market_signals": {"description": "markets", "sources": ["ecb"]},
        "empty_group": {"description": "empty", "sources": ["missing_source"]},
    }


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

    monkeypatch.setattr("news_pipeline.scanner.feedparser.parse", lambda url, **kwargs: Feed())

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


def test_source_groups_load_from_config() -> None:
    groups = load_source_groups()

    assert "official_defense" in groups
    assert "official_eu" in groups
    assert "official_financial" in groups
    assert "defense_specialist" in groups
    assert "european_local" in groups
    assert "market_signals" in groups
    assert "google_news_rss" in groups["fast_headlines"]["sources"]


@pytest.mark.parametrize(
    ("group", "expected_id"),
    [
        ("official_defense", "uk_mod"),
        ("defense_specialist", "defense_news"),
        ("european_local", "dw"),
        ("market_signals", "ecb"),
    ],
)
def test_scan_source_group_resolves(group: str, expected_id: str) -> None:
    resolved = resolve_scan_sources(group, _group_sources(), source_groups=_source_groups())

    assert [source["id"] for source in resolved["rss_sources"]] == [expected_id]


def test_scan_unknown_source_group_returns_clear_error(storage: Storage) -> None:
    with pytest.raises(ValueError, match="Unknown scan source/group"):
        run_scan(
            storage,
            _group_sources(),
            _watchlist(),
            None,
            since="24h",
            sources="unknown_group",
            source_groups=_source_groups(),
        )


def test_source_groups_command_lists_groups(capsys, temp_db_env: Path) -> None:
    rc = cmd_source_groups(argparse.Namespace())
    out = capsys.readouterr().out

    assert rc == 0
    assert "# Source Groups" in out
    assert "official_defense" in out
    assert "official_eu" in out
    assert "official_financial" in out
    assert "market_signals" in out


def test_source_quality_boosts_but_does_not_create_signal() -> None:
    wl = _watchlist()
    medium = classify_signal(_rss_item("Europe debates defense spending"), wl)
    high = classify_signal({**_rss_item("Europe debates defense spending"), "source_quality": "high"}, wl)
    noise = classify_signal({**_rss_item("Central bank updates calendar"), "source_quality": "high"}, wl)

    assert medium["signal_class"] == "medium_signal"
    assert high["signal_class"] == "high_signal"
    assert noise["signal_class"] == "noise"


def test_source_quality_does_not_promote_shadow_fleet_only_story() -> None:
    signal = classify_signal(
        {**_rss_item("From Pyongyang to Primorsk: sanctions evasion and shadow fleet design"), "source_quality": "high"},
        _watchlist(core_terms=["shadow fleet", "sanctions enforcement", "air defense"]),
    )

    assert signal["signal_class"] == "low_signal"


def test_financial_market_group_can_scan_trade_watchlist(monkeypatch, storage: Storage) -> None:
    watchlist = {
        "name": "global_trade_and_country_flows",
        "context_terms": ["global trade", "exports", "imports", "EU"],
        "core_terms": ["tariffs", "export controls", "shipping"],
        "event_triggers": [],
        "financial_and_policy_terms": ["trade balance"],
        "suggested_queries": ["global trade tariffs"],
    }
    monkeypatch.setattr(
        "news_pipeline.scanner.fetch_rss",
        lambda source_cfg, max_items=50: [
            _rss_item("EU exports hit by new tariffs", "https://example.com/trade"),
        ],
    )

    result = run_scan(
        storage,
        _group_sources(),
        watchlist,
        None,
        since="24h",
        sources="market_signals",
        source_groups=_source_groups(),
        source_quality={"market_signals": "high"},
        only_new=False,
    )

    assert result["signals"]
    assert result["signals"][0]["signal_class"] == "high_signal"


def test_official_defense_group_can_scan_war_prep(monkeypatch, storage: Storage) -> None:
    monkeypatch.setattr(
        "news_pipeline.scanner.fetch_rss",
        lambda source_cfg, max_items=50: [
            _rss_item("NATO readiness plan boosts air defense procurement", "https://example.com/nato"),
        ],
    )

    result = run_scan(
        storage,
        _group_sources(),
        _watchlist(),
        None,
        since="24h",
        sources="official_defense",
        source_groups=_source_groups(),
        source_quality={"official_defense": "high"},
        only_new=False,
    )

    assert result["signals"][0]["signal_class"] == "high_signal"


def test_scan_topic_uses_default_scan_sources_when_source_omitted(monkeypatch, storage: Storage) -> None:
    calls = []

    def fake_fetch(source_cfg, max_items=50):
        calls.append(source_cfg["id"])
        return [_rss_item("NATO readiness plan boosts air defense procurement", f"https://example.com/{source_cfg['id']}")]

    monkeypatch.setattr("news_pipeline.scanner.fetch_rss", fake_fetch)
    monkeypatch.setattr("news_pipeline.scanner.feedparser.parse", lambda url, **kwargs: type("Feed", (), {"entries": []})())

    result = run_scan(
        storage,
        _group_sources(),
        _watchlist(default_scan_sources=["defense_specialist"]),
        None,
        since="24h",
        sources=None,
        source_groups=_source_groups(),
        source_quality={"defense_specialist": "high"},
        only_new=False,
    )

    assert calls == ["defense_news"]
    assert result["default_sources_used"] is True
    assert result["source_groups_used"] == ["defense_specialist"]
    assert result["signals"]


def test_explicit_source_overrides_topic_defaults(monkeypatch, storage: Storage) -> None:
    calls = []
    monkeypatch.setattr(
        "news_pipeline.scanner.fetch_rss",
        lambda source_cfg, max_items=50: calls.append(source_cfg["id"]) or [_rss_item("Europe debates defense spending", f"https://example.com/{source_cfg['id']}")],
    )

    result = run_scan(
        storage,
        _group_sources(),
        _watchlist(default_scan_sources=["defense_specialist"]),
        None,
        since="24h",
        sources="european_local",
        source_groups=_source_groups(),
        only_new=False,
    )

    assert calls == ["dw"]
    assert result["default_sources_used"] is False
    assert result["source_groups_used"] == ["european_local"]


def test_source_group_with_zero_enabled_sources_warns(monkeypatch, storage: Storage) -> None:
    monkeypatch.setattr("news_pipeline.scanner.fetch_rss", lambda source_cfg, max_items=50: [])

    result = run_scan(
        storage,
        _group_sources(),
        _watchlist(),
        None,
        since="24h",
        sources="empty_group",
        source_groups=_source_groups(),
        only_new=False,
    )

    assert "empty_group has no enabled live sources." in result["warnings"]


def test_source_health_command_returns_group_and_source_status(capsys, temp_db_env: Path) -> None:
    rc = cmd_source_health(argparse.Namespace())
    out = capsys.readouterr().out

    assert rc == 0
    assert "# Source Health" in out
    assert "Configured source count:" in out
    assert "Working source count:" in out
    assert "Items last 24h:" in out


def test_google_news_results_remain_public_metadata(monkeypatch, storage: Storage) -> None:
    class Feed:
        entries = [
            {
                "title": "Germany boosts air defense procurement",
                "link": "https://example.com/google-news-item",
                "published": utc_now_iso(),
                "summary": "Russia threat pushes Europe readiness.",
                "source": {"title": "Example News"},
            }
        ]

    monkeypatch.setattr("news_pipeline.scanner.feedparser.parse", lambda url, **kwargs: Feed())

    result = run_scan(
        storage,
        _sources(),
        _watchlist(),
        None,
        since="24h",
        sources="google_news_rss",
        source_groups={},
        only_new=False,
    )

    assert result["signals"][0]["access_mode"] == "public_metadata"
    assert result["signals"][0]["source_category"] == "google_news_rss"


def test_gdelt_restricted_domains_remain_metadata_only(monkeypatch, storage: Storage) -> None:
    monkeypatch.setattr(
        "news_pipeline.scanner.fetch_gdelt_query",
        lambda *args, **kwargs: (
            {
                "articles": [
                    {
                        "title": "NATO readiness and air defense procurement",
                        "url": "https://www.reuters.com/world/test",
                        "seendate": utc_now_iso(),
                        "snippet": "Europe and Russia threat context.",
                        "language": "en",
                        "sourcecountry": "US",
                    }
                ]
            },
            None,
        ),
    )

    result = run_scan(storage, _sources(), _watchlist(), None, since="24h", sources="gdelt", only_new=False)

    assert result["signals"][0]["access_mode"] == "metadata_only"
