from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from news_pipeline.cli import cmd_collect, cmd_digest, cmd_enrich, cmd_enrich_url
from news_pipeline.collector import build_gdelt_topic_query_plan, build_gdelt_topic_queries, collect_topic
from news_pipeline.relevance import classify_watchlist_article
from news_pipeline.storage import Storage
from news_pipeline.ingest.fundus_adapter import _publisher_for_domain


def _watchlist(**overrides):
    data = {
        "name": "topic",
        "suggested_queries": ["Europe Russia defense budget", "NATO readiness Russia Europe"],
        "context_terms": ["Europe", "Russia", "NATO"],
        "core_terms": ["defense budget", "readiness", "air defense"],
        "event_triggers": ["NATO summit"],
        "financial_and_policy_terms": ["procurement"],
    }
    data.update(overrides)
    return data


def _europe_watchlist(**overrides):
    data = _watchlist(
        name="europe_ru_war_preparations",
        suggested_queries=[
            "Europe Russia",
            "NATO Russia readiness eastern Europe",
            "Europe defense spending Russia threat",
        ],
        context_terms=["Europe", "Russia", "Russian", "NATO", "Poland", "Baltic Sea", "Germany", "France", "Ukraine"],
        core_terms=["defense budget", "readiness", "air defense", "civil defense", "sabotage"],
        event_triggers=["NATO summit", "Baltic Sea cable damage"],
        financial_and_policy_terms=["procurement", "ammunition production"],
    )
    data.update(overrides)
    return data


@pytest.fixture
def temp_db_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "news.sqlite"
    monkeypatch.setenv("NEWS_PIPELINE_DB", str(db_path))
    return db_path


def _articles_for(urls: list[str]):
    return {
        "articles": [
            {
                "title": f"NATO readiness and air defense procurement {idx}",
                "url": url,
                "seendate": "20260601T120000Z",
                "snippet": "Europe and Russia threat context with defense budget and air defense procurement.",
                "language": "en",
                "sourcecountry": "US",
            }
            for idx, url in enumerate(urls)
        ]
    }


def _gdelt_test_config() -> dict:
    return {
        "enabled": True,
        "max_queries_per_topic": 2,
        "max_items_per_query": 10,
        "timeout_seconds": 1,
        "retry_count": 0,
        "backoff_seconds": 0,
        "cache_ttl_minutes": 60,
        "min_delay_between_queries_seconds": 0,
        "stop_on_first_rate_limit": True,
    }


def test_collect_builds_queries_from_suggested_queries() -> None:
    queries = build_gdelt_topic_queries(_watchlist(), max_queries=2)
    assert queries == ["Europe Russia defense budget", "NATO readiness Russia Europe"]


def test_collect_builds_fallback_context_core_queries() -> None:
    queries = build_gdelt_topic_queries(_watchlist(suggested_queries=[]), max_queries=3)
    assert queries == ["Europe defense budget", "Europe readiness", "Europe air defense"]


def test_query_builder_avoids_broad_queries_and_prioritizes_suggested() -> None:
    plan = build_gdelt_topic_query_plan(_europe_watchlist(), max_queries=3)
    queries = [item["query"] for item in plan]

    assert "Europe Russia" not in queries
    assert queries[0] in {
        "NATO Russia readiness eastern Europe",
        "Europe defense spending Russia threat",
        "Germany air defense procurement Russia",
    }
    assert all(len(q.split()) > 1 for q in queries)


def test_query_builder_prefers_context_core_pairs_without_suggested() -> None:
    plan = build_gdelt_topic_query_plan(_watchlist(suggested_queries=[]), max_queries=2)

    assert [item["source"] for item in plan] == ["generated_context_core", "generated_context_core"]
    assert [item["query"] for item in plan] == ["Europe defense budget", "Europe readiness"]


def test_collect_stops_after_first_gdelt_429(monkeypatch, temp_db_env: Path) -> None:
    calls = []

    def fake_fetch(*args, **kwargs):
        calls.append(args[0])
        return {}, "GDELT rate limited (HTTP 429) for query."

    monkeypatch.setattr("news_pipeline.collector.fetch_gdelt_query", fake_fetch)
    storage = Storage(temp_db_env)
    storage.init_db()
    result = collect_topic(
        storage,
        _watchlist(suggested_queries=["Europe defense budget", "NATO readiness Russia Europe", "Poland civil defense Russia"]),
        days=7,
        max_items=10,
        gdelt_config={
            "max_queries_per_topic": 3,
            "max_items_per_query": 10,
            "timeout_seconds": 1,
            "retry_count": 0,
            "backoff_seconds": 0,
            "cache_ttl_minutes": 60,
            "min_delay_between_queries_seconds": 0,
            "stop_on_first_rate_limit": True,
        },
        enrich=None,
        sleep_func=lambda _: None,
    )
    storage.close()

    assert len(calls) == 1
    assert "rate_limited_stop" in result["warnings"]
    assert [item["status"] for item in result["query_statuses"]] == [
        "rate_limited",
        "skipped_rate_limited",
        "skipped_rate_limited",
    ]


def test_collect_uses_fresh_cache_before_network(monkeypatch, temp_db_env: Path) -> None:
    monkeypatch.setattr("news_pipeline.collector.fetch_gdelt_query", lambda *args, **kwargs: pytest.fail("network should not be called"))
    storage = Storage(temp_db_env)
    storage.init_db()
    storage.set_gdelt_cache("Europe defense budget", datetime.now(timezone.utc).isoformat(), _articles_for(["https://apnews.com/article/cached"]))

    result = collect_topic(
        storage,
        _watchlist(suggested_queries=["Europe defense budget"]),
        days=7,
        max_items=1,
        gdelt_config={
            "max_queries_per_topic": 1,
            "max_items_per_query": 10,
            "timeout_seconds": 1,
            "retry_count": 0,
            "backoff_seconds": 0,
            "cache_ttl_minutes": 180,
            "min_delay_between_queries_seconds": 0,
            "stop_on_first_rate_limit": True,
        },
        enrich=None,
        use_cache_first=True,
    )
    storage.close()

    assert result["inserted_count"] == 1
    assert result["query_statuses"][0]["status"] == "cached"


def test_collect_dry_run_prints_queries_without_network(monkeypatch, capsys, temp_db_env: Path) -> None:
    monkeypatch.setattr("news_pipeline.collector.fetch_gdelt_query", lambda *args, **kwargs: pytest.fail("network should not be called"))

    rc = cmd_collect(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            days=7,
            max_items=50,
            source="gdelt",
            enrich="fundus",
            no_enrich=True,
            max_queries=2,
            dry_run_queries=True,
            use_cache_first=False,
        )
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "# Planned GDELT Queries: europe_ru_war_preparations" in out
    assert "Query count: 2" in out
    assert "Source: suggested_query" in out


def test_collect_max_queries_limits_executed_queries(monkeypatch, temp_db_env: Path) -> None:
    calls = []

    def fake_fetch(query, *args, **kwargs):
        calls.append(query)
        return _articles_for([f"https://apnews.com/article/{len(calls)}"]), None

    monkeypatch.setattr("news_pipeline.collector.fetch_gdelt_query", fake_fetch)

    rc = cmd_collect(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            days=7,
            max_items=10,
            source="gdelt",
            enrich="fundus",
            no_enrich=True,
            max_queries=1,
            dry_run_queries=False,
            use_cache_first=False,
        )
    )

    assert rc == 0
    assert len(calls) == 1


def test_europe_war_prep_high_confidence_direct_match() -> None:
    result = classify_watchlist_article(
        {
            "title": "Germany increases defense budget for air defense procurement amid Russia threat",
            "summary": "European readiness plans include procurement and defense spending.",
            "text": "NATO allies cite Russia threat and eastern flank readiness.",
        },
        _europe_watchlist(),
    )

    assert result["relevance_class"] == "direct_match"
    assert result["confidence"] == "high"


def test_europe_war_prep_medium_confidence_direct_match() -> None:
    result = classify_watchlist_article(
        {
            "title": "EU expands defense industrial support for ammunition production",
            "summary": "The package draws lessons from Ukraine and European defense needs.",
            "text": "Officials said the program could support readiness over time.",
        },
        _europe_watchlist(),
    )

    assert result["relevance_class"] == "direct_match"
    assert result["confidence"] == "medium"


def test_weapons_show_and_g7_summit_are_not_high_confidence() -> None:
    weapons = classify_watchlist_article(
        {
            "title": "France bans Israel from major weapons show",
            "summary": "The diplomatic dispute affected an arms fair.",
            "text": "No Russia readiness or procurement decision was announced.",
        },
        _europe_watchlist(),
    )
    summit = classify_watchlist_article(
        {
            "title": "Ukraine's Zelenskyy set to attend G7 summit in France",
            "summary": "Leaders will discuss diplomacy and aid.",
            "text": "The summit agenda did not include concrete readiness or procurement decisions.",
        },
        _europe_watchlist(),
    )

    assert weapons["relevance_class"] in {"near_miss", "direct_match"}
    assert weapons["confidence"] != "high"
    assert summit["relevance_class"] in {"near_miss", "direct_match"}
    assert summit["confidence"] != "high"


def test_sanctions_only_shadow_fleet_is_near_miss_not_high_confidence() -> None:
    result = classify_watchlist_article(
        {
            "title": "France seizes Russian shadow fleet tanker amid sanctions enforcement",
            "summary": "Sanctions enforcement operation at sea.",
            "text": "The story focused only on vessel seizure and legal sanctions.",
        },
        _europe_watchlist(),
    )

    assert result["relevance_class"] == "near_miss"
    assert result["confidence"] == "low"


def test_collect_handles_gdelt_timeout_no_results_and_parse_error(monkeypatch, capsys, temp_db_env: Path) -> None:
    warnings = iter(
        [
            ({}, "GDELT timeout after 1 attempt(s) for query."),
            ({"articles": []}, None),
        ]
    )
    monkeypatch.setattr("news_pipeline.collector.fetch_gdelt_query", lambda *args, **kwargs: next(warnings))
    monkeypatch.setattr("news_pipeline.cli.load_gdelt_config", _gdelt_test_config)

    rc = cmd_collect(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            days=7,
            max_items=10,
            source="gdelt",
            enrich="fundus",
            no_enrich=True,
            max_queries=2,
            dry_run_queries=False,
            use_cache_first=False,
        )
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Collect complete:" in out
    assert "timeout" in out
    assert "no results" in out.lower()


def test_collect_handles_gdelt_parse_error(monkeypatch, capsys, temp_db_env: Path) -> None:
    monkeypatch.setattr("news_pipeline.collector.fetch_gdelt_query", lambda *args, **kwargs: ({}, "GDELT response parse failed for query."))

    rc = cmd_collect(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            days=7,
            max_items=10,
            source="gdelt",
            enrich="fundus",
            no_enrich=True,
            max_queries=1,
            dry_run_queries=False,
            use_cache_first=False,
        )
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "parse failed" in out


def test_collect_stores_restricted_sources_as_metadata_only(monkeypatch, temp_db_env: Path) -> None:
    monkeypatch.setattr(
        "news_pipeline.collector.fetch_gdelt_query",
        lambda *args, **kwargs: (
            _articles_for(
                [
                    "https://www.reuters.com/world/test",
                    "https://www.bloomberg.com/news/test",
                    "https://www.ft.com/content/test",
                    "https://www.wsj.com/articles/test",
                ]
            ),
            None,
        ),
    )

    rc = cmd_collect(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            days=7,
            max_items=4,
            source="gdelt",
            enrich="fundus",
            no_enrich=True,
        )
    )
    assert rc == 0

    conn = sqlite3.connect(str(temp_db_env))
    rows = conn.execute(
        """
        SELECT a.source, m.access_mode
        FROM articles a
        JOIN article_sources_metadata m ON m.article_id = a.id
        ORDER BY a.source
        """
    ).fetchall()
    conn.close()

    assert rows
    assert all(row[1] == "metadata_only" for row in rows)
    assert {row[0] for row in rows} == {"Bloomberg", "Financial Times", "Reuters", "Wall Street Journal"}


def test_collect_stores_public_apnews_as_public(monkeypatch, temp_db_env: Path) -> None:
    monkeypatch.setattr(
        "news_pipeline.collector.fetch_gdelt_query",
        lambda *args, **kwargs: (_articles_for(["https://apnews.com/article/test"]), None),
    )

    rc = cmd_collect(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            days=7,
            max_items=1,
            source="gdelt",
            enrich="fundus",
            no_enrich=True,
        )
    )
    assert rc == 0

    conn = sqlite3.connect(str(temp_db_env))
    row = conn.execute(
        """
        SELECT a.source, m.access_mode
        FROM articles a
        JOIN article_sources_metadata m ON m.article_id = a.id
        """
    ).fetchone()
    conn.close()
    assert row == ("AP News", "public")


def test_fundus_missing_does_not_fail_collect(monkeypatch, capsys, temp_db_env: Path) -> None:
    monkeypatch.setattr("news_pipeline.collector.fetch_gdelt_query", lambda *args, **kwargs: (_articles_for(["https://apnews.com/article/test"]), None))
    monkeypatch.setattr(
        "news_pipeline.collector.fundus_status",
        lambda: {"adapter": "fundus", "available": False, "message": "missing"},
    )

    rc = cmd_collect(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            days=7,
            max_items=1,
            source="gdelt",
            enrich="fundus",
            no_enrich=False,
        )
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Fundus unavailable" in out


def test_enrich_marks_adapter_unavailable_when_fundus_missing(monkeypatch, temp_db_env: Path) -> None:
    monkeypatch.setattr("news_pipeline.collector.fetch_gdelt_query", lambda *args, **kwargs: (_articles_for(["https://apnews.com/article/test"]), None))
    cmd_collect(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            days=7,
            max_items=1,
            source="gdelt",
            enrich="fundus",
            no_enrich=True,
        )
    )
    monkeypatch.setattr(
        "news_pipeline.collector.fundus_status",
        lambda: {"adapter": "fundus", "available": False, "message": "missing"},
    )

    rc = cmd_enrich(argparse.Namespace(topic="europe_ru_war_preparations", days=7, adapter="fundus", max_items=10))
    assert rc == 0

    conn = sqlite3.connect(str(temp_db_env))
    status = conn.execute("SELECT enrichment_status FROM article_sources_metadata").fetchone()[0]
    conn.close()
    assert status == "adapter_unavailable"


def test_fundus_enrichment_skips_restricted_domains(monkeypatch, temp_db_env: Path) -> None:
    monkeypatch.setattr("news_pipeline.collector.fetch_gdelt_query", lambda *args, **kwargs: (_articles_for(["https://www.reuters.com/world/test"]), None))
    monkeypatch.setattr(
        "news_pipeline.collector.fundus_status",
        lambda: {"adapter": "fundus", "available": True, "message": "ok"},
    )

    rc = cmd_collect(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            days=7,
            max_items=1,
            source="gdelt",
            enrich="fundus",
            no_enrich=False,
        )
    )
    assert rc == 0

    conn = sqlite3.connect(str(temp_db_env))
    status = conn.execute("SELECT enrichment_status FROM article_sources_metadata").fetchone()[0]
    conn.close()
    assert status == "paywall_or_restricted"


def test_fundus_mocked_supported_extraction_marks_full_text(monkeypatch, temp_db_env: Path) -> None:
    monkeypatch.setattr("news_pipeline.collector.fetch_gdelt_query", lambda *args, **kwargs: (_articles_for(["https://apnews.com/article/test"]), None))
    monkeypatch.setattr(
        "news_pipeline.collector.fundus_status",
        lambda: {"adapter": "fundus", "available": True, "message": "ok"},
    )
    monkeypatch.setattr(
        "news_pipeline.collector.enrich_article_fundus",
        lambda article: {"status": "full_text_extracted", "summary": "enriched summary", "text": "enriched text"},
    )

    rc = cmd_collect(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            days=7,
            max_items=1,
            source="gdelt",
            enrich="fundus",
            no_enrich=False,
        )
    )
    assert rc == 0

    conn = sqlite3.connect(str(temp_db_env))
    row = conn.execute(
        """
        SELECT a.summary, a.text, m.enrichment_status
        FROM articles a
        JOIN article_sources_metadata m ON m.article_id = a.id
        """
    ).fetchone()
    conn.close()
    assert row == ("enriched summary", "enriched text", "full_text_extracted")


def test_enrich_url_blocks_restricted_domain(capsys) -> None:
    rc = cmd_enrich_url(argparse.Namespace(url="https://www.reuters.com/world/test", adapter="fundus"))
    out = capsys.readouterr().out

    assert rc == 0
    assert "restricted/paywalled decision: yes" in out
    assert "access_mode decision: metadata_only" in out
    assert "extraction status: paywall_or_restricted" in out


def test_enrich_url_reports_mocked_public_extraction(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "news_pipeline.cli.fundus_status",
        lambda: {"adapter": "fundus", "available": True, "message": "ok"},
    )
    monkeypatch.setattr(
        "news_pipeline.cli.enrich_article_fundus",
        lambda article: {
            "status": "full_text_extracted",
            "title": "Public article",
            "published_at": "2026-06-02T12:00:00+00:00",
            "text": "extracted text",
        },
    )

    rc = cmd_enrich_url(argparse.Namespace(url="https://apnews.com/article/test", adapter="fundus"))
    out = capsys.readouterr().out

    assert rc == 0
    assert "restricted/paywalled decision: no" in out
    assert "eligibility: eligible" in out
    assert "extraction status: full_text_extracted" in out
    assert "title: Public article" in out
    assert "text_length: 14" in out


def test_fundus_public_domain_allowlist_includes_existing_gdelt_sources() -> None:
    assert _publisher_for_domain("www.businessinsider.com") is not None
    assert _publisher_for_domain("www.taipeitimes.com") is not None
    assert _publisher_for_domain("www.dailymaverick.co.za") is not None
    assert _publisher_for_domain("www.lrt.lt") is not None
    assert _publisher_for_domain("www.newsweek.com") is None


def test_enrich_url_reports_fundus_missing(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "news_pipeline.cli.fundus_status",
        lambda: {"adapter": "fundus", "available": False, "message": "missing"},
    )

    rc = cmd_enrich_url(argparse.Namespace(url="https://apnews.com/article/test", adapter="fundus"))
    out = capsys.readouterr().out

    assert rc == 0
    assert "adapter availability: unavailable" in out
    assert "eligibility: not_eligible" in out
    assert "extraction status: adapter_unavailable" in out


def test_enrich_url_reports_failed_extraction(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "news_pipeline.cli.fundus_status",
        lambda: {"adapter": "fundus", "available": True, "message": "ok"},
    )
    monkeypatch.setattr(
        "news_pipeline.cli.enrich_article_fundus",
        lambda article: {"status": "failed", "reason": "parse failed"},
    )

    rc = cmd_enrich_url(argparse.Namespace(url="https://apnews.com/article/test", adapter="fundus"))
    out = capsys.readouterr().out

    assert rc == 0
    assert "extraction status: failed" in out
    assert "failure reason: parse failed" in out


def test_enrich_include_rss_enriches_matching_rss_article(monkeypatch, temp_db_env: Path) -> None:
    storage = Storage(temp_db_env)
    storage.init_db()
    storage.insert_article(
        {
            "id": "rss-direct",
            "source": "BBC",
            "title": "Germany increases defense budget for air defense procurement amid Russia threat",
            "url": "https://www.bbc.com/news/articles/test",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "author": "",
            "language": "en",
            "country": "UK",
            "summary": "Europe readiness procurement.",
            "text": "",
            "topics": [],
            "keywords_matched": [],
            "access_mode": "rss",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    storage.close()
    monkeypatch.setattr(
        "news_pipeline.collector.fundus_status",
        lambda: {"adapter": "fundus", "available": True, "message": "ok"},
    )
    monkeypatch.setattr(
        "news_pipeline.collector.enrich_article_fundus",
        lambda article: {
            "status": "full_text_extracted",
            "title": article["title"],
            "author": "Reporter",
            "published_at": article["published_at"],
            "text": "full extracted text",
        },
    )

    rc = cmd_enrich(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            days=30,
            adapter="fundus",
            max_items=10,
            include_rss=True,
        )
    )
    assert rc == 0

    conn = sqlite3.connect(str(temp_db_env))
    row = conn.execute(
        """
        SELECT a.text, m.discovery_source, m.enrichment_status
        FROM articles a JOIN article_sources_metadata m ON m.article_id = a.id
        WHERE a.id = 'rss-direct'
        """
    ).fetchone()
    conn.close()
    assert row == ("full extracted text", "RSS", "full_text_extracted")


def test_enrich_include_rss_excludes_restricted_domain(monkeypatch, capsys, temp_db_env: Path) -> None:
    storage = Storage(temp_db_env)
    storage.init_db()
    storage.insert_article(
        {
            "id": "restricted",
            "source": "Reuters",
            "title": "Germany defense budget Russia threat",
            "url": "https://www.reuters.com/world/test",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "author": "",
            "language": "en",
            "country": "US",
            "summary": "Europe readiness procurement.",
            "text": "",
            "topics": [],
            "keywords_matched": [],
            "access_mode": "metadata_only",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    storage.close()
    monkeypatch.setattr(
        "news_pipeline.collector.enrich_article_fundus",
        lambda article: pytest.fail("restricted article should not be enriched"),
    )

    rc = cmd_enrich(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            days=30,
            adapter="fundus",
            max_items=10,
            include_rss=True,
        )
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "restricted_paywall: 1" in out
    assert "Skipped examples:" in out


def test_digest_includes_collection_metadata(monkeypatch, capsys, temp_db_env: Path) -> None:
    monkeypatch.setattr("news_pipeline.collector.fetch_gdelt_query", lambda *args, **kwargs: (_articles_for(["https://www.reuters.com/world/test"]), None))
    cmd_collect(
        argparse.Namespace(
            topic="europe_ru_war_preparations",
            days=7,
            max_items=1,
            source="gdelt",
            enrich="fundus",
            no_enrich=True,
        )
    )

    rc = cmd_digest(argparse.Namespace(topic="europe_ru_war_preparations", days=7, source=None, limit=10))
    out = capsys.readouterr().out

    assert rc == 0
    assert "Access mode: metadata_only" in out
    assert "Discovery source: GDELT" in out
    assert "Enrichment: metadata_only" in out or "Enrichment: not_attempted" in out
    assert "Matched context terms:" in out
    assert "Matched core terms:" in out
