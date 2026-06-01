from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pytest
import requests

from news_pipeline.cli import cmd_digest, cmd_ingest
from news_pipeline.normalize import utc_now_iso
from news_pipeline.storage import Storage
from news_pipeline.ingest.gdelt import fetch_gdelt_metadata


@pytest.fixture
def temp_db_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "news.sqlite"
    monkeypatch.setenv("NEWS_PIPELINE_DB", str(db_path))
    return db_path


def test_missing_fundus_dependency_mode_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], temp_db_env: Path
) -> None:
    monkeypatch.setattr(
        "news_pipeline.cli.fundus_status",
        lambda: {
            "adapter": "fundus",
            "available": False,
            "message": 'Fundus dependency missing. Install with: pip install "news-intel[fundus]"',
        },
    )

    rc = cmd_ingest(argparse.Namespace(mode="fundus", max_items=1))
    out = capsys.readouterr().out

    assert rc == 2
    assert "Fundus dependency missing" in out

    # DB remains readable and not corrupted.
    assert temp_db_env.exists()
    conn = sqlite3.connect(str(temp_db_env))
    try:
        ok = conn.execute("PRAGMA integrity_check;").fetchone()[0]
    finally:
        conn.close()
    assert ok == "ok"


def test_gdelt_timeout_returns_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    def _timeout(*args, **kwargs):
        raise requests.Timeout("timeout")

    monkeypatch.setattr(requests, "get", _timeout)

    items, warning = fetch_gdelt_metadata(
        {
            "name": "Reuters",
            "domains": ["reuters.com"],
            "gdelt_max_retries": 0,
            "gdelt_retry_wait_seconds": 0,
            "gdelt_timeout_seconds": 1,
        },
        max_items=5,
        timeout=1,
        max_retries=0,
        retry_wait_seconds=0,
    )

    assert items == []
    assert warning is not None
    assert "timeout" in warning.lower()


def test_gdelt_rate_limit_returns_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        status_code = 429

        def json(self):
            return {}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _Resp())

    items, warning = fetch_gdelt_metadata(
        {
            "name": "Reuters",
            "domains": ["reuters.com"],
            "gdelt_max_retries": 0,
            "gdelt_retry_wait_seconds": 0,
        },
        max_items=5,
        max_retries=0,
        retry_wait_seconds=0,
    )

    assert items == []
    assert warning is not None
    assert "rate limited" in warning.lower()


def test_digest_generation_without_optional_adapters(
    capsys: pytest.CaptureFixture[str], temp_db_env: Path
) -> None:
    storage = Storage(temp_db_env)
    storage.init_db()
    storage.insert_article(
        {
            "id": "a1",
            "source": "BBC",
            "title": "Ukraine financing update",
            "url": "https://example.com/ukraine-financing",
            "published_at": utc_now_iso(),
            "author": "",
            "language": "en",
            "country": "UK",
            "summary": "Ukraine discusses IMF loan financing options.",
            "text": "Ukraine IMF loan financing topic.",
            "topics": [],
            "keywords_matched": ["Ukraine", "IMF", "loan", "financing"],
            "access_mode": "rss",
            "created_at": utc_now_iso(),
        }
    )
    storage.close()

    rc = cmd_digest(
        argparse.Namespace(
            topic="ukraine_financing",
            days=3,
            source=None,
            limit=10,
        )
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Digest: ukraine_financing" in out
    assert "Ukraine financing update" in out
