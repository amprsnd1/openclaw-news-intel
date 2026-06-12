# news-intel

Local headline signal scanner and news intelligence connector for OpenClaw agents.

`news-intel` is a local-first CLI that refreshes public headline sources, matches them against watchlists, groups related headlines into signal clusters, and returns compact markdown briefings that OpenClaw can use directly.

The main UX is intentionally simple:

```bash
news-intel morning-scan
```

Research mode still exists, but it is the advanced deep-dive path after a signal appears. It is not the default morning workflow.

## Status

Private beta / local-first MVP.

## What it does

- Scans headline sources for watchlist-related signals.
- Groups related headlines into clusters.
- Routes headlines to primary and secondary topics.
- Shows source limits and rejected/noisy matches when requested.
- Works locally through a CLI and SQLite database.
- Can be used by OpenClaw as a safe local skill.
- Supports advanced collection, enrichment, search, and digest workflows for deeper research.

## What it does not do

- Does not bypass paywalls.
- Does not scrape Reuters, Bloomberg, FT, WSJ, or Dow Jones full text.
- Does not provide guaranteed realtime news.
- Does not replace licensed newswire access.
- Does not run as hosted SaaS.
- Does not scrape subscription-only content or use browser automation for restricted outlets.

## Mental model

```text
Sources
  -> Fast Scan
  -> Watchlists
  -> Signals / Clusters
  -> OpenClaw briefing
```

Advanced mode:

```text
Signal found
  -> Collect
  -> Enrich
  -> Digest
  -> Deep research briefing
```

RSS, Google News RSS, and GDELT discover headlines and metadata. Watchlists define what to monitor. `morning-scan` and `scan` are for fast headline signals. `collect -> enrich -> digest` is for deeper research. Fundus optionally enriches public supported articles after a signal is found. Restricted outlets remain metadata-only unless licensed API access is configured.

## Quickstart

```bash
git clone <repo-url>
cd news-intel
bash scripts/setup.sh
source .venv/bin/activate
news-intel doctor
news-intel morning-scan
```

Optional OpenClaw setup:

```bash
bash scripts/install_openclaw_skill.sh
openclaw skills info news-intelligence
```

Then ask OpenClaw:

```text
Use News Intelligence. Run morning scan.
```

## Main command

```bash
news-intel morning-scan
```

Use this for daily headline monitoring, fast signal detection, watchlist alerts, and OpenClaw morning briefings.

`morning-scan` runs fresh RSS ingest first, then scans all watchlists for the last 24 hours, groups repeated headlines into clusters, routes each headline to one primary topic, and returns concise markdown.

## Which command should I use?

| Goal | Command |
|---|---|
| Daily morning briefing | `news-intel morning-scan` |
| Scan one topic | `news-intel scan --topic "iran_war_risk" --since "24h"` |
| Scan free-form query | `news-intel scan --query "NATO troops eastern Europe" --since "24h"` |
| Search local database | `news-intel search "Ukraine IMF loan" --mode precise` |
| Deep research | `collect -> enrich -> digest` |
| Check setup | `news-intel doctor` |
| Check sources | `news-intel source-health` |

## OpenClaw setup

OpenClaw does not scrape news directly. OpenClaw calls the local `news-intel` CLI through the News Intelligence skill.

Install or refresh the skill:

```bash
bash scripts/install_openclaw_skill.sh
openclaw skills info news-intelligence
```

Recommended OpenClaw command:

```bash
news-intel morning-scan
```

Example prompts:

- Use News Intelligence. Run morning scan.
- Use News Intelligence. Scan Iran war risk for the last 24h.
- Use News Intelligence. Search local database for Ukraine IMF loan.
- Use News Intelligence. Run a deep digest for Europe-Russia war preparations.

## Watchlists

Strategic watchlists included:

- `europe_ru_war_preparations`
- `china_taiwan_risk`
- `iran_war_risk`
- `migration_policy_europe`
- `global_trade_and_country_flows`

Baseline watchlists also include:

- `ukraine_financing`
- `eu_energy_security`

Watchlists live in `config/watchlists.yaml`. They define context terms, core terms, suggested queries, default scan source groups, hard gates, and briefing focus.

## Source access model

- RSS/public feeds: headline and public metadata.
- Google News RSS: metadata/headline discovery.
- GDELT: metadata discovery; may rate-limit.
- Fundus: optional enrichment for public supported articles.
- Reuters/Bloomberg/FT/WSJ/Dow Jones: metadata-only unless licensed API access is configured.

This project does not bypass paywalls, logins, publisher restrictions, or subscription-only access.

## Morning scan mode

Primary user flow:

```bash
news-intel morning-scan
```

Use for:

- Daily headline monitoring.
- Fast signal detection.
- Watchlist alerts.
- OpenClaw morning briefing.

Equivalent explicit command:

```bash
news-intel scan --all-watchlists --since "24h" --min-confidence medium --group-by-primary --fresh
```

Morning scan output includes:

- Fresh ingest status.
- Top alerts.
- Signal clusters.
- Primary, secondary, and spillover topic routing.
- Source diversity notes.
- Watchlist summary.
- Source limits.

Use `--show-seen` to include previously shown items. Use `--show-rejected` when debugging why headlines were excluded or demoted.

## Topic scan mode

Focused scan:

```bash
news-intel scan --topic "iran_war_risk" --since "24h"
```

Use for:

- Checking one topic.
- Running a focused scan.
- Debugging watchlist behavior.
- Inspecting rejected/noisy matches with `--show-rejected`.

Free-form query scan:

```bash
news-intel scan --query "NATO troops eastern Europe" --since "24h"
```

Source groups can be specified when needed:

```bash
news-intel scan --topic "global_trade_and_country_flows" --since "24h" --source market_signals,google_news_rss --min-confidence medium
```

## Research mode, advanced

Research mode is the advanced workflow for deeper context after a signal appears. It is not the default morning workflow.

```bash
news-intel collect --topic "<topic>" --days 7 --max-items 30 --max-queries 1 --use-cache-first
news-intel enrich --topic "<topic>" --days 30 --adapter fundus --max-items 50 --include-rss
news-intel digest --topic "<topic>" --days 7 --include-metadata-only
```

Use for:

- Deep dive after a signal appears.
- Context gathering.
- Public article enrichment.
- Weekly research digest.
- Source diagnostics and metadata-only disclosure.

Research mode uses GDELT conservatively for topic discovery, Fundus optionally for public article enrichment, and digest rendering for longer briefings. GDELT and Fundus failures should degrade to warnings rather than breaking the core RSS scan path.

## Troubleshooting

- `news-intel: command not found`: activate `.venv`, run `python3 -m pip install -e .`, or check `which news-intel`.
- `news-intel doctor` reports degraded: read the degraded issue list. Fundus unavailable, GDELT 429, and missing OpenClaw registration are non-fatal for local scans.
- Fundus unavailable: install the optional extra with `python3 -m pip install -e ".[fundus]"`; on macOS native dependency errors, run `brew install lz4 xz zstd` and retry with Homebrew include/library flags.
- GDELT HTTP 429: wait and retry later with `--max-queries 1 --use-cache-first`; RSS and Google News RSS scans should still work.
- `morning-scan` returns zero signals: zero can be normal when no high/medium signals are present. To inspect more, run `news-intel morning-scan --show-seen` or `news-intel scan --all-watchlists --since "24h" --min-confidence low --group-by-primary --show-rejected --show-seen`.
- OpenClaw skill not visible: run `bash scripts/install_openclaw_skill.sh`, then `openclaw skills info news-intelligence`; restart with `openclaw stop` and `openclaw start` if stale.
- OpenClaw uses a stale skill: compare `openclaw-skills/news-intelligence/SKILL.md` with `~/.openclaw/custom-skills/news-intelligence/SKILL.md`, then rerun the install script.
- Google News RSS cache only: cached metadata is acceptable for scans; rerun later if query feeds return no new entries.
- No URLs in output: scan output uses markdown links when URLs are available; URL-less source records are shown as unavailable rather than fabricated.

## Development

Project structure:

```text
news_pipeline/
  cli.py              # CLI entrypoints
  scanner.py          # fast scan, routing, clustering, signal output
  collector.py        # GDELT/topic collection and enrichment orchestration
  digest.py           # search and digest markdown rendering
  storage.py          # SQLite storage
  config.py           # sources/watchlists configuration loading
  ingest/             # RSS, GDELT, Fundus adapters
config/
  sources.yaml
  watchlists.yaml
openclaw-skills/
  news-intelligence/SKILL.md
scripts/
  setup.sh
  install_openclaw_skill.sh
  setup_with_fundus.sh
  smoke_test.sh
```

Setup:

```bash
bash scripts/setup.sh
source .venv/bin/activate
```

Verification:

```bash
pytest -q
bash scripts/smoke_test.sh
news-intel doctor
news-intel morning-scan
```

Local runtime files are intentionally ignored: `.venv/`, `data/*.sqlite`, logs, caches, and local OpenClaw runtime config.

## License

No license file is currently included. Add one before public distribution.
