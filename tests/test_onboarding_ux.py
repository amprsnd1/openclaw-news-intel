from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest

from news_pipeline import cli
from news_pipeline.storage import Storage


def _configure_doctor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, runtime_skill: bool = True) -> Path:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "sources.yaml").write_text("sources: []\n", encoding="utf-8")
    (root / "config" / "watchlists.yaml").write_text("watchlists: []\n", encoding="utf-8")
    project_skill = root / "openclaw-skills" / "news-intelligence" / "SKILL.md"
    project_skill.parent.mkdir(parents=True)
    project_skill.write_text("# skill\n", encoding="utf-8")
    runtime = tmp_path / ".openclaw" / "custom-skills" / "news-intelligence" / "SKILL.md"
    if runtime_skill:
        runtime.parent.mkdir(parents=True)
        runtime.write_text("# runtime\n", encoding="utf-8")

    db_path = tmp_path / "news.sqlite"
    monkeypatch.setenv("NEWS_PIPELINE_DB", str(db_path))
    monkeypatch.setattr(cli, "_project_root", lambda: root)
    monkeypatch.setattr(
        cli,
        "_openclaw_paths",
        lambda: {
            "project_skill": project_skill,
            "runtime_skill": runtime,
            "config": tmp_path / ".openclaw" / "openclaw.json",
        },
    )
    monkeypatch.setattr(cli, "_detect_openclaw_registration", lambda: "detected")
    monkeypatch.setattr(
        cli,
        "load_sources",
        lambda: [{"name": "BBC", "adapter": "rss", "enabled": True, "url": "https://example.com/rss"}],
    )
    monkeypatch.setattr(cli, "load_watchlists", lambda: [{"name": "iran_war_risk", "topic": "iran_war_risk"}])
    monkeypatch.setattr(cli, "load_source_groups", lambda: {"fast_headlines": {"sources": ["rss"]}})
    monkeypatch.setattr(cli, "load_google_news_config", lambda: {"enabled": True})
    monkeypatch.setattr(cli, "gdelt_status", lambda: {"adapter": "gdelt", "available": True, "message": "ok"})
    monkeypatch.setattr(cli, "fundus_status", lambda: {"adapter": "fundus", "available": True, "message": "ok"})
    return db_path


def test_doctor_returns_usable_status_with_core_components(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _configure_doctor(monkeypatch, tmp_path)

    rc = cli.cmd_doctor(argparse.Namespace())

    output = capsys.readouterr().out
    assert rc == 0
    assert "Core:" in output
    assert "CLI: ok" in output
    assert "Config: ok" in output
    assert "Database: ok" in output
    assert "Watchlists: ok" in output
    assert "Source groups: ok" in output
    assert "Fundus: available" in output
    assert "Registration: detected" in output
    assert "Status: usable" in output


def test_doctor_returns_degraded_when_fundus_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _configure_doctor(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "fundus_status", lambda: {"adapter": "fundus", "available": False, "message": "not installed"})

    rc = cli.cmd_doctor(argparse.Namespace())

    output = capsys.readouterr().out
    assert rc == 2
    assert "Fundus: unavailable" in output
    assert "Fundus unavailable" in output
    assert "Status: degraded" in output


def test_doctor_returns_degraded_when_gdelt_has_recent_429(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _configure_doctor(monkeypatch, tmp_path)

    def fake_stats(self: Storage) -> dict:
        return {
            "gdelt_runtime": {
                "latest_run": None,
                "last_429_time": "2026-06-12 08:20:00",
                "cache_entries": 0,
                "fresh_cache_entries": 0,
            }
        }

    monkeypatch.setattr(Storage, "stats", fake_stats)

    rc = cli.cmd_doctor(argparse.Namespace())

    output = capsys.readouterr().out
    assert rc == 2
    assert "last 429: 2026-06-12 08:20:00" in output
    assert "GDELT recently rate-limited" in output
    assert "Status: degraded" in output


def test_doctor_reports_openclaw_skill_missing_as_degraded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _configure_doctor(monkeypatch, tmp_path, runtime_skill=False)
    monkeypatch.setattr(cli, "_detect_openclaw_registration", lambda: "not detected")

    rc = cli.cmd_doctor(argparse.Namespace())

    output = capsys.readouterr().out
    assert rc == 2
    assert "Runtime skill: missing" in output
    assert "OpenClaw runtime skill missing" in output
    assert "OpenClaw skill registration not detected" in output
    assert "Status: degraded" in output


def test_setup_scripts_are_present_and_executable() -> None:
    for rel in ["scripts/setup.sh", "scripts/setup_with_fundus.sh", "scripts/install_openclaw_skill.sh"]:
        path = Path(rel)
        assert path.exists()
        assert os.access(path, os.X_OK)


def test_install_openclaw_skill_script_uses_valid_extra_dirs_schema() -> None:
    text = Path("scripts/install_openclaw_skill.sh").read_text(encoding="utf-8")
    assert 'skills = data.setdefault("skills", {})' in text
    assert 'load = skills.setdefault("load", {})' in text
    assert 'data.setdefault("skill", {})' not in text


def test_readme_includes_quickstart_command_map_and_source_access_model() -> None:
    text = Path("README.md").read_text(encoding="utf-8")
    assert "## Quickstart" in text
    assert "news-intel doctor" in text
    assert "news-intel morning-scan" in text
    assert "## Which command should I use?" in text
    assert "## Source Access Model" in text
    assert "This project does not bypass paywalls" in text


def test_openclaw_docs_include_morning_scan_usage() -> None:
    text = Path("docs/openclaw-quickstart.md").read_text(encoding="utf-8")
    assert "bash scripts/install_openclaw_skill.sh" in text
    assert "news-intel doctor" in text
    assert "Use News Intelligence. Run morning scan." in text
