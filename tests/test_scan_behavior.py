from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pytest

from news_pipeline.cli import cmd_scan, cmd_source_groups, cmd_source_health
from news_pipeline.config import load_source_groups
from news_pipeline.normalize import utc_now_iso
from news_pipeline.scanner import (
    build_signal_clusters,
    classify_across_watchlists,
    classify_signal,
    render_all_watchlists_scan_markdown,
    render_scan_markdown,
    resolve_scan_sources,
    run_scan,
)
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


def _simple_watchlist(name: str, context: list[str], core: list[str], event: list[str] | None = None, financial: list[str] | None = None) -> dict:
    return {
        "name": name,
        "topic": name,
        "context_terms": context,
        "core_terms": core,
        "event_triggers": event or [],
        "financial_and_policy_terms": financial or [],
        "suggested_queries": [],
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
    assert low["signal_class"] == "noise"
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
    assert "Signal:" in out
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

    assert signal["signal_class"] == "noise"


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


def test_ukraine_financing_rejects_eu_tech_story() -> None:
    wl = _simple_watchlist("ukraine_financing", ["EU", "Ukraine"], ["loan", "funds"])
    signal = classify_signal(_rss_item("EU orders Meta to reopen WhatsApp to rival AI assistants"), wl)

    assert signal["signal_class"] == "noise"
    assert "no Ukraine context" in signal["reject_reason"]


def test_ukraine_financing_rejects_hungary_recovery_fund_without_ukraine() -> None:
    wl = _simple_watchlist("ukraine_financing", ["EU", "Ukraine"], ["loan", "frozen funds"])
    signal = classify_signal(_rss_item("Hungary submits revised EU recovery plan over frozen funds"), wl)

    assert signal["signal_class"] == "noise"
    assert "no Ukraine context" in signal["reject_reason"]


def test_ukraine_financing_accepts_ukraine_imf_loan() -> None:
    wl = _simple_watchlist("ukraine_financing", ["Ukraine", "Kyiv"], ["IMF", "loan"])
    signal = classify_signal(_rss_item("Ukraine secures new IMF loan tranche for budget support"), wl)

    assert signal["signal_class"] in {"medium_signal", "high_signal"}
    assert "ukraine" in signal["matched_context_terms"]


def test_europe_war_prep_rejects_generic_kyiv_battlefield_headline() -> None:
    signal = classify_signal(_rss_item("Kyiv strikes key Russian supply lines"), _watchlist())

    assert signal["signal_class"] == "noise"
    assert "no Europe/NATO/member-state context" in signal["reject_reason"]


def test_europe_war_prep_accepts_nato_deployment_eastern_europe() -> None:
    signal = classify_signal(_rss_item("NATO deploys troops to Eastern Europe amid Russia threat"), _watchlist())

    assert signal["signal_class"] in {"medium_signal", "high_signal"}
    assert signal["missing_required_terms"] == []


def test_global_trade_demotes_iran_war_without_flow_terms() -> None:
    wl = _simple_watchlist("global_trade_and_country_flows", ["Iran", "US"], ["shipping", "tariffs"])
    signal = classify_signal(_rss_item("US and Iran exchange missile strikes overnight"), wl)

    assert signal["signal_class"] == "noise"
    assert "no trade" in signal["reject_reason"]


def test_global_trade_accepts_hormuz_oil_shipping_disruption() -> None:
    wl = _simple_watchlist("global_trade_and_country_flows", ["Iran", "Strait of Hormuz"], ["shipping", "oil flows"])
    signal = classify_signal(_rss_item("Iran threat disrupts Strait of Hormuz shipping and oil flows"), wl)

    assert signal["signal_class"] in {"medium_signal", "high_signal"}
    assert "shipping" in signal["matched_financial_terms"] or "shipping" in signal["matched_core_terms"]


def test_migration_policy_accepts_eu_return_hubs() -> None:
    wl = _simple_watchlist("migration_policy_europe", ["EU", "Europe"], ["return hubs", "asylum"])
    signal = classify_signal(_rss_item("EU agrees new return hubs for rejected asylum seekers"), wl)

    assert signal["signal_class"] in {"medium_signal", "high_signal"}


def test_migration_policy_rejects_generic_crime_story() -> None:
    wl = _simple_watchlist("migration_policy_europe", ["UK", "EU"], ["migration", "asylum"])
    signal = classify_signal(_rss_item("UK police investigate crime involving migrant suspect"), wl)

    assert signal["signal_class"] == "noise"
    assert "no migration policy term" in signal["reject_reason"]


def test_primary_and_secondary_topic_assignment() -> None:
    iran = _simple_watchlist("iran_war_risk", ["Iran", "US", "Strait of Hormuz"], ["missile strike", "shipping", "US base"])
    trade = _simple_watchlist("global_trade_and_country_flows", ["Iran", "Strait of Hormuz"], ["shipping"])
    article = _rss_item("Iran missile strike near US base disrupts Strait of Hormuz shipping")

    routed = classify_across_watchlists(article, [iran, trade], current_watchlist=iran)

    assert routed["primary_topic"] == "iran_war_risk"
    assert "global_trade_and_country_flows" in routed["secondary_topics"]


def test_primary_only_demotes_secondary_topic(monkeypatch, storage: Storage) -> None:
    iran = _simple_watchlist("iran_war_risk", ["Iran", "US", "Strait of Hormuz"], ["missile strike", "shipping", "US base"])
    trade = _simple_watchlist("global_trade_and_country_flows", ["Iran", "Strait of Hormuz"], ["shipping"])
    monkeypatch.setattr(
        "news_pipeline.scanner.fetch_rss",
        lambda source_cfg, max_items=50: [_rss_item("Iran missile strike near US base disrupts Strait of Hormuz shipping")],
    )

    result = run_scan(
        storage,
        _sources(),
        trade,
        None,
        since="24h",
        sources="rss",
        only_new=False,
        all_watchlists=[iran, trade],
        primary_only=True,
        show_rejected=True,
    )

    assert result["signals"] == []
    assert result["rejected"]
    assert "Primary topic is iran_war_risk" in result["rejected"][0]["reject_reason"]


def test_group_by_primary_preserves_secondary_discovered_signal(monkeypatch, storage: Storage) -> None:
    iran = _simple_watchlist("iran_war_risk", ["Iran", "US", "Strait of Hormuz"], ["missile strike", "shipping", "US base"])
    trade = _simple_watchlist("global_trade_and_country_flows", ["Iran", "Strait of Hormuz"], ["shipping"])
    monkeypatch.setattr(
        "news_pipeline.scanner.fetch_rss",
        lambda source_cfg, max_items=50: [_rss_item("Iran missile strike near US base disrupts Strait of Hormuz shipping")],
    )

    result = run_scan(
        storage,
        _sources(),
        trade,
        None,
        since="24h",
        sources="rss",
        only_new=False,
        all_watchlists=[iran, trade],
        group_by_primary=True,
    )

    assert result["signals"]
    assert result["signals"][0]["primary_topic"] == "iran_war_risk"
    assert "global_trade_and_country_flows" in result["signals"][0]["secondary_topics"]


def test_rejected_items_hidden_by_default_and_shown_when_requested(monkeypatch, storage: Storage) -> None:
    wl = _simple_watchlist("ukraine_financing", ["Ukraine"], ["loan"])
    monkeypatch.setattr(
        "news_pipeline.scanner.fetch_rss",
        lambda source_cfg, max_items=50: [_rss_item("EU orders Meta to reopen WhatsApp to rival AI assistants")],
    )

    hidden = run_scan(storage, _sources(), wl, None, since="24h", sources="rss", only_new=False, show_rejected=False)
    shown = run_scan(storage, _sources(), wl, None, since="24h", sources="rss", only_new=False, show_rejected=True)

    assert hidden["rejected"] == []
    assert hidden["rejected_count"] == 1
    assert shown["rejected"]
    assert "Rejected / Demoted" in render_scan_markdown(shown)


def test_scan_output_includes_url_topic_summary_and_source_diversity() -> None:
    result = {
        "topic": "iran_war_risk",
        "since": "24h",
        "sources": ["rss"],
        "source_groups_used": ["rss"],
        "new_items_scanned": 1,
        "scanned_counts": {"rss": 1, "gdelt": 0, "google_news_rss": 0},
        "source_status": {"rss": "ok", "gdelt": "skipped", "google_news_rss": "skipped", "fundus": "not used for scan"},
        "warnings": [],
        "signals": [
            {
                "title": "US launches strikes on Iran",
                "url": "https://example.com/iran",
                "source": "Example",
                "published_at": utc_now_iso(),
                "primary_topic": "iran_war_risk",
                "secondary_topics": ["global_trade_and_country_flows"],
                "signal_class": "high_signal",
                "source_quality": "medium",
                "matched_terms": ["Iran", "US"],
                "why": "Direct escalation.",
            }
        ],
        "rejected": [],
        "rejected_count": 0,
        "source_diversity_note": "Warning: high alert based on limited source diversity.",
    }

    out = render_scan_markdown(result)

    assert "[US launches strikes on Iran](https://example.com/iran)" in out
    assert "Primary topic: iran_war_risk" in out
    assert "Secondary topics: global_trade_and_country_flows" in out
    assert "Signal: high_signal" in out
    assert "## Watchlist Summary" in out
    assert "Warning: high alert based on limited source diversity." in out


def test_all_watchlists_primary_only_cli_runs_without_duplicates(monkeypatch, capsys, temp_db_env: Path) -> None:
    monkeypatch.setattr(
        "news_pipeline.scanner.fetch_rss",
        lambda source_cfg, max_items=50: [_rss_item("Ukraine secures IMF loan tranche for budget support")],
    )
    monkeypatch.setattr("news_pipeline.scanner.feedparser.parse", lambda url, **kwargs: type("Feed", (), {"entries": []})())

    rc = cmd_scan(
        argparse.Namespace(
            all_watchlists=True,
            topic=None,
            query=None,
            since="24h",
            max_items=50,
            source="rss",
            min_confidence="medium",
            only_new=False,
            show_seen=False,
            show_rejected=False,
            primary_only=True,
            group_by_primary=False,
            format="markdown",
            max_queries=1,
            use_cache_first=False,
        )
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "# Watchlist Signal Scan - Last 24h" in out
    assert "Primary topic: ukraine_financing" in out
    assert out.count("Ukraine secures IMF loan tranche for budget support") == 1
    assert "## Watchlist Summary" in out
    assert "## Routing Diagnostics" in out
    assert "Candidate matches before routing:" in out
    assert "Suppressed duplicates:" in out


def test_all_watchlists_group_by_primary_preserves_high_medium_and_secondary(monkeypatch, capsys, temp_db_env: Path) -> None:
    iran = _simple_watchlist("iran_war_risk", ["Iran", "US", "Strait of Hormuz"], ["missile strike", "shipping", "US base"])
    trade = _simple_watchlist("global_trade_and_country_flows", ["Iran", "Strait of Hormuz"], ["shipping"])
    monkeypatch.setattr("news_pipeline.cli.load_watchlists", lambda: [iran, trade])
    monkeypatch.setattr("news_pipeline.cli.load_sources", lambda: _sources())
    monkeypatch.setattr("news_pipeline.scanner.fetch_rss", lambda source_cfg, max_items=50: [_rss_item("Iran missile strike near US base disrupts Strait of Hormuz shipping")])

    rc = cmd_scan(
        argparse.Namespace(
            all_watchlists=True,
            topic=None,
            query=None,
            since="24h",
            max_items=50,
            source="rss",
            min_confidence="medium",
            only_new=False,
            show_seen=False,
            show_rejected=False,
            primary_only=False,
            group_by_primary=True,
            format="markdown",
            max_queries=1,
            use_cache_first=False,
        )
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Primary topic: iran_war_risk" in out
    assert "Secondary topics: global_trade_and_country_flows" in out
    assert out.count("Iran missile strike near US base disrupts Strait of Hormuz shipping") == 1
    assert "| iran_war_risk | 1 | 0 | 0 |" in out


def test_iran_military_strike_routes_primary_to_iran_war_risk() -> None:
    iran = _simple_watchlist("iran_war_risk", ["Iran", "US"], ["war"], event=["missile", "strike", "base"])
    trade = _simple_watchlist("global_trade_and_country_flows", ["Iran", "global"], ["oil", "shipping", "inflation"])

    signal = classify_across_watchlists(_rss_item("US launches missile strikes on Iran after base attack"), [iran, trade])

    assert signal["primary_topic"] == "iran_war_risk"
    assert signal["signal_class"] in {"high_signal", "medium_signal"}


def test_iran_inflation_ecb_headline_routes_primary_to_global_trade_secondary_iran() -> None:
    iran = _simple_watchlist("iran_war_risk", ["Iran", "US"], ["war"])
    trade = _simple_watchlist("global_trade_and_country_flows", ["Iran", "ECB", "eurozone"], ["inflation", "rates", "interest rates"])

    signal = classify_across_watchlists(
        _rss_item("ECB raises eurozone interest rates as Iran war stokes inflation"),
        [iran, trade],
    )

    assert signal["primary_topic"] == "global_trade_and_country_flows"
    assert "iran_war_risk" in signal["secondary_topics"]
    assert "inflation" in signal["spillover_topics"]


def test_non_eu_energy_headlines_rejected_from_eu_energy_security() -> None:
    energy = _simple_watchlist("eu_energy_security", ["EU", "Europe"], ["oil", "gas", "energy security"])

    cuba = classify_signal(_rss_item("US slaps sanctions on Cuba's oil and gas company"), energy)
    caribbean = classify_signal(_rss_item("Caribbean countries are feeling the squeeze from this energy crisis"), energy)

    assert cuba["signal_class"] == "noise"
    assert "no EU/Europe/member-state energy-security context" in cuba["reject_reason"]
    assert caribbean["signal_class"] == "noise"
    assert "no EU/Europe/member-state energy-security context" in caribbean["reject_reason"]


def test_nato_europe_military_cut_rejected_from_china_taiwan_risk() -> None:
    china = _simple_watchlist("china_taiwan_risk", ["China", "Taiwan", "Pacific"], ["fighter jets", "warships", "blockade"])

    signal = classify_signal(_rss_item("US plans major cut to fighter jets, warships for NATO operations in Europe"), china)

    assert signal["signal_class"] == "noise"
    assert "no China/Taiwan/PLA/Pacific/semiconductor context" in signal["reject_reason"]


def test_china_taiwan_blockade_routes_primary_to_china_taiwan_risk() -> None:
    china = _simple_watchlist("china_taiwan_risk", ["China", "Taiwan", "Taiwan Strait"], ["blockade", "PLA", "military"])
    europe = _watchlist()

    signal = classify_across_watchlists(_rss_item("China launches PLA blockade drills around Taiwan Strait"), [china, europe])

    assert signal["primary_topic"] == "china_taiwan_risk"
    assert signal["signal_class"] in {"high_signal", "medium_signal"}


def test_generic_defense_tech_not_promoted_as_europe_war_prep() -> None:
    signal = classify_signal(_rss_item("MBDA showcases hybrid high-energy laser interceptor counter-drone system"), _watchlist())

    assert signal["signal_class"] in {"noise", "low_signal"}
    assert signal["signal_class"] not in {"high_signal", "medium_signal"}


def test_europe_procurement_headline_routes_primary_to_europe_war_prep() -> None:
    europe = _watchlist()
    iran = _simple_watchlist("iran_war_risk", ["Iran"], ["strike"])

    signal = classify_across_watchlists(
        _rss_item("NATO announces air defense procurement for Eastern Europe readiness"),
        [europe, iran],
    )

    assert signal["primary_topic"] == "europe_ru_war_preparations"
    assert signal["signal_class"] in {"high_signal", "medium_signal"}


def test_all_watchlists_renderer_outputs_links_clusters_and_spillover() -> None:
    now = utc_now_iso()
    signals = [
        {
            "title": "US launches missile strikes on Iran",
            "url": "https://example.com/iran-1",
            "source": "Defense News",
            "published_at": now,
            "primary_topic": "iran_war_risk",
            "secondary_topics": ["global_trade_and_country_flows"],
            "spillover_topics": ["oil", "shipping"],
            "signal_class": "high_signal",
            "source_quality": "high",
            "matched_terms": ["Iran", "missile", "strikes"],
            "why": "Direct military escalation.",
        },
        {
            "title": "Iran retaliates with missile fire near US base",
            "url": "https://example.com/iran-2",
            "source": "DW",
            "published_at": now,
            "primary_topic": "iran_war_risk",
            "secondary_topics": ["global_trade_and_country_flows"],
            "spillover_topics": ["oil"],
            "signal_class": "high_signal",
            "source_quality": "medium",
            "matched_terms": ["Iran", "missile", "base"],
            "why": "Direct military escalation.",
        },
    ]
    result = {
        "since": "24h",
        "sources": ["rss"],
        "new_items_scanned": 2,
        "signals": signals,
        "rejected": [],
        "routing_diagnostics": {"total_scanned": 2, "candidate_matches_before_routing": 2, "shown_signals_after_routing": 2},
        "watchlist_summary": [{"watchlist": "iran_war_risk", "high": 2, "medium": 0, "low": 0, "rejected": 0, "status": "Active"}],
        "source_status": {"rss": "ok"},
    }

    clusters = build_signal_clusters(signals)
    out = render_all_watchlists_scan_markdown(result)

    assert clusters[0]["title"] == "US-Iran military escalation"
    assert clusters[0]["source_count"] == 2
    assert "Latest:" in out
    assert "## Top Alerts" in out
    assert "#### Cluster: US-Iran military escalation" in out
    assert "[US launches missile strikes on Iran](https://example.com/iran-1)" in out
    assert "## Market / Energy Spillover" in out
    assert out.count("US launches missile strikes on Iran") >= 1
