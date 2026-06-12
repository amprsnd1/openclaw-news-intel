from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest

from news_pipeline import cli
from news_pipeline.storage import Storage

LOCAL_REPO_PATH = "/".join(["", "Users", "nick", "news-intel"])


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


def test_doctor_does_not_degrade_for_disabled_roadmap_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_doctor(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli,
        "load_sources",
        lambda: [
            {"name": "BBC", "adapter": "rss", "enabled": True, "url": "https://example.com/rss"},
            {
                "name": "Roadmap Defense Source",
                "adapter": "rss",
                "enabled": False,
                "url": "roadmap-no-stable-feed",
                "status": "roadmap_no_stable_feed",
            },
        ],
    )
    monkeypatch.setattr(
        cli,
        "load_source_groups",
        lambda: {"official_defense": {"sources": ["Roadmap Defense Source"]}, "fast_headlines": {"sources": ["rss"]}},
    )

    rc = cli.cmd_doctor(argparse.Namespace())

    output = capsys.readouterr().out
    assert rc == 0
    assert "Roadmap Defense Source" not in output
    assert "Status: usable" in output


def test_doctor_returns_degraded_when_fundus_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _configure_doctor(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "fundus_status", lambda: {"adapter": "fundus", "available": False, "message": "not installed"})

    rc = cli.cmd_doctor(argparse.Namespace())

    output = capsys.readouterr().out
    assert rc == 2
    assert "Fundus: unavailable" in output
    assert "Fundus unavailable" in output
    assert "Status: usable_but_degraded" in output
    assert "Degraded components:" in output
    assert "Why this is not fatal:" in output
    assert "Recommended action:" in output


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
    assert "Status: usable_but_degraded" in output
    assert "Why this is not fatal:" in output
    assert "morning-scan still works" in output
    assert "Retry GDELT later" in output


def test_doctor_reports_openclaw_skill_missing_as_degraded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _configure_doctor(monkeypatch, tmp_path, runtime_skill=False)
    monkeypatch.setattr(cli, "_detect_openclaw_registration", lambda: "not detected")

    rc = cli.cmd_doctor(argparse.Namespace())

    output = capsys.readouterr().out
    assert rc == 2
    assert "Runtime skill: missing" in output
    assert "OpenClaw runtime skill missing" in output
    assert "OpenClaw skill registration not detected" in output
    assert "Status: usable_but_degraded" in output


def test_doctor_returns_broken_when_config_cannot_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_doctor(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "load_sources", lambda: (_ for _ in ()).throw(RuntimeError("bad sources yaml")))

    rc = cli.cmd_doctor(argparse.Namespace())

    output = capsys.readouterr().out
    assert rc == 1
    assert "config load failed: bad sources yaml" in output
    assert "Status: broken" in output


def test_doctor_returns_broken_when_watchlists_cannot_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_doctor(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "load_watchlists", lambda: (_ for _ in ()).throw(RuntimeError("bad watchlists yaml")))

    rc = cli.cmd_doctor(argparse.Namespace())

    output = capsys.readouterr().out
    assert rc == 1
    assert "config load failed: bad watchlists yaml" in output
    assert "Status: broken" in output


def test_doctor_returns_broken_when_database_initialization_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_doctor(monkeypatch, tmp_path)

    def fail_init(self: Storage) -> None:
        raise RuntimeError("sqlite locked")

    monkeypatch.setattr(Storage, "init_db", fail_init)

    rc = cli.cmd_doctor(argparse.Namespace())

    output = capsys.readouterr().out
    assert rc == 1
    assert "database check failed: sqlite locked" in output
    assert "Status: broken" in output


def test_doctor_returns_degraded_when_enabled_non_core_source_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_doctor(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli,
        "load_sources",
        lambda: [
            {"name": "BBC", "adapter": "rss", "enabled": True, "url": "https://example.com/rss"},
            {
                "id": "bad_optional",
                "name": "Bad Optional",
                "adapter": "rss",
                "enabled": True,
                "url": "https://example.com/bad.rss",
                "status": "fetch_error",
            },
        ],
    )

    rc = cli.cmd_doctor(argparse.Namespace())

    output = capsys.readouterr().out
    assert rc == 2
    assert "enabled source failures: bad_optional" in output
    assert "Status: usable_but_degraded" in output


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
    assert text.startswith("# news-intel")
    assert "Local headline signal scanner and news intelligence connector for OpenClaw agents." in text
    assert "## Quickstart" in text
    assert "cd openclaw-news-intel" in text
    assert "## Path convention" in text
    assert "export NEWS_INTEL_HOME=/path/to/news-intel" in text
    assert "news-intel doctor" in text
    assert "news-intel morning-scan" in text
    assert "## Which command should I use?" in text
    assert "## Doctor exit codes" in text
    assert "0 | `usable`" in text
    assert "1 | `broken`" in text
    assert "2 | `usable_but_degraded`" in text
    assert "## Source access model" in text
    assert "This project does not bypass paywalls" in text
    assert "## Research mode, advanced" in text
    assert "Research mode is the advanced workflow" in text
    assert "It is not the default morning workflow." in text
    assert "| Daily morning briefing | `news-intel morning-scan` |" in text
    assert LOCAL_REPO_PATH not in text


def test_openclaw_docs_include_morning_scan_usage() -> None:
    text = Path("docs/openclaw-quickstart.md").read_text(encoding="utf-8")
    assert "bash scripts/install_openclaw_skill.sh" in text
    assert "news-intel doctor" in text
    assert "exit `2`" in text
    assert "usable_but_degraded" in text
    assert "Use News Intelligence. Run morning scan." in text
    assert "OpenClaw does not scrape news directly." in text
    assert "<repo>/.venv/bin/news-intel" in text
    assert LOCAL_REPO_PATH not in text


def test_docs_explain_doctor_exit_codes() -> None:
    operational = Path("docs/operational-checklist.md").read_text(encoding="utf-8")
    integration = Path("docs/openclaw-integration.md").read_text(encoding="utf-8")
    assert "`0`: `Status: usable`" in operational
    assert "`1`: `Status: broken`" in operational
    assert "`2`: `Status: usable_but_degraded`" in operational
    assert "`0`: usable." in integration
    assert "`1`: broken required component." in integration
    assert "`2`: usable but degraded." in integration
    assert LOCAL_REPO_PATH not in integration


def test_architecture_doc_exists_and_describes_main_flows() -> None:
    text = Path("docs/architecture.md").read_text(encoding="utf-8")
    assert "# Architecture" in text
    assert "Sources -> scan -> watchlists -> routing -> clusters -> briefing" in text
    assert "collect -> enrich -> digest" in text
    assert "Status: usable_but_degraded" in text
    assert "OpenClaw does not scrape news directly." in text
    assert "No component should bypass paywalls" in text
