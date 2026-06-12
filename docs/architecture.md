# Architecture

## Purpose

`news-intel` is a local headline signal scanner and news intelligence connector for OpenClaw agents. It helps an agent refresh public headline sources, detect watchlist signals, cluster related headlines, and return a compact briefing.

It is local-first. It is not a hosted news platform, licensed newswire replacement, or paywall bypass tool.

## Main flows

### Morning scan flow

```text
Sources -> scan -> watchlists -> routing -> clusters -> briefing
```

`news-intel morning-scan` refreshes RSS, scans all watchlists, assigns each headline to a primary topic, preserves secondary/spillover topics, clusters repeated headlines, and renders markdown for OpenClaw.

### Research flow

```text
collect -> enrich -> digest
```

Research mode is advanced. Use it after a signal appears or for weekly/deeper reviews. `collect` discovers metadata, `enrich` optionally extracts public article text with Fundus, and `digest` renders a longer source-backed briefing.

## Components

- CLI entrypoints: `news_pipeline/cli.py` exposes `morning-scan`, `scan`, `collect`, `enrich`, `digest`, `search`, `doctor`, and source diagnostics.
- Source adapters: RSS is the core safe path; Google News RSS and GDELT provide metadata/headline discovery; Fundus optionally enriches public supported articles.
- Scanner: `news_pipeline/scanner.py` handles fast headline matching, hard gates, primary/secondary routing, clustering, seen-state, and markdown output.
- Watchlists: `config/watchlists.yaml` defines topics, terms, hard gates, suggested queries, default scan sources, and briefing focus.
- Storage: SQLite stores normalized articles, source metadata, collection runs, GDELT cache, and scan seen-state.
- Research workflow: `collector.py`, `fundus_adapter.py`, `gdelt.py`, and `digest.py` support deeper topic collection and digest generation.
- OpenClaw skill: `openclaw-skills/news-intelligence/SKILL.md` tells OpenClaw which local commands are safe to run.

## Doctor states

`news-intel doctor` has three exit states:

- `0` / `Status: usable`: required local components are healthy.
- `1` / `Status: broken`: required core setup is broken, such as config, watchlists, source groups, database initialization, or RSS core setup.
- `2` / `Status: usable_but_degraded`: the system can still run, but an optional or external component is degraded.

Exit `2` is expected for cases such as recent GDELT HTTP 429, missing Fundus, missing OpenClaw runtime skill, disabled Google News RSS, or failed enabled non-core feeds. It is not a failed install if `morning-scan` can still run through RSS.

## Source access model

- RSS/public feeds: headline and public metadata.
- Google News RSS: metadata/headline discovery only.
- GDELT: metadata discovery and event/headline search; may rate-limit.
- Fundus: optional public article enrichment for supported publishers.
- Reuters, Bloomberg, FT, WSJ, and Dow Jones: metadata-only unless licensed API access is configured.

No component should bypass paywalls, logins, publisher restrictions, or subscription-only access.

## OpenClaw integration

OpenClaw does not scrape news directly. It calls the local `news-intel` CLI through the News Intelligence skill. The recommended OpenClaw workflow is:

```bash
news-intel morning-scan
```

For deeper context, OpenClaw can run the advanced sequence:

```bash
news-intel collect --topic "<topic>" --days 7 --max-items 30 --max-queries 1 --use-cache-first
news-intel enrich --topic "<topic>" --days 30 --adapter fundus --max-items 50 --include-rss
news-intel digest --topic "<topic>" --days 7 --include-metadata-only
```

## Local-first design

The project stores data locally in SQLite, uses local configuration files, and exposes a local CLI. Optional adapters should fail soft and preserve the core RSS scan path.

## Known limitations

- Not guaranteed realtime.
- Coverage depends on configured public feeds and metadata sources.
- GDELT and Google News RSS can rate-limit or cache responses.
- Fundus does not support every public publisher.
- Metadata-only restricted outlets cannot provide full article text without licensed access.
