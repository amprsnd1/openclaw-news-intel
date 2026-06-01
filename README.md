# openclaw-news-intel

RSS-first, local news intelligence pipeline designed for OpenClaw workflows.

`news-intel` collects, normalizes, deduplicates, filters, and summarizes news from public/legal sources into a local SQLite database, then exposes search and digest commands for repeatable briefings.

## What This Project Does

- Ingests from public RSS feeds by default.
- Supports optional adapters for Fundus and GDELT metadata.
- Normalizes all items into a stable article schema.
- Deduplicates by canonical URL and near-duplicate title hash.
- Applies watchlists for topic monitoring.
- Generates markdown search results and digests for analyst workflows.
- Integrates with OpenClaw as a safe local CLI skill.

## What This Project Does Not Do

- No paywall bypassing.
- No scraping of subscription-only content.
- No brittle browser automation for Reuters/Bloomberg/FT/WSJ.
- Reuters, Bloomberg, Financial Times, and Wall Street Journal remain metadata-only unless licensed API access is configured.

## Core Architecture

- Core ingestion path: `rss`
- Optional adapter: `fundus` (extra dependency)
- Optional adapter: `gdelt` (metadata fallback, non-blocking)
- Storage: local SQLite (`data/news.sqlite`)
- CLI entrypoint: `news-intel`

## Project Structure

```text
news_pipeline/
  __init__.py
  __main__.py
  cli.py
  config.py
  ingest/
    rss.py
    fundus_adapter.py
    gdelt.py
  normalize.py
  dedupe.py
  filters.py
  storage.py
  digest.py
config/
  sources.yaml
  watchlists.yaml
data/
  news.sqlite
scripts/
  setup.sh
  smoke_test.sh
openclaw-skills/
  news-intelligence/SKILL.md
```

## Strategic Watchlists Included

- `europe_ru_war_preparations`
- `china_taiwan_risk`
- `iran_war_risk`
- `migration_policy_europe`
- `global_trade_and_country_flows`

Also includes baseline watchlists such as `ukraine_financing` and `eu_energy_security`.

## Installation

### Recommended (macOS/Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install -e .
```

### Optional Fundus adapter

```bash
python3 -m pip install -e ".[fundus]"
```

Fundus is optional and may require host/system libraries.

### One-command setup

```bash
bash scripts/setup.sh
```

## Configuration

- Sources: `config/sources.yaml`
- Watchlists: `config/watchlists.yaml`
- DB path override (optional):

```bash
export NEWS_PIPELINE_DB=data/news.sqlite
```

## CLI Usage

### Source health

```bash
news-intel sources
news-intel stats
```

### Ingestion

```bash
news-intel ingest
news-intel ingest --mode rss
news-intel ingest --mode all
news-intel ingest --mode fundus
news-intel ingest --mode gdelt
```

Behavior:
- Fundus missing: clear error only when Fundus mode is requested.
- GDELT unavailable/timeout/rate-limited: warning + continue.

### Search

```bash
news-intel search "Ukraine IMF loan"
news-intel search "Ukraine IMF loan" --mode precise
news-intel search "Ukraine IMF loan" --min-terms 2
news-intel search "Ukraine IMF loan" --mode precise --show-weak-matches
```

Search output includes:
- source
- date
- markdown title link
- matched terms
- missing terms
- relevance class (`direct_match`, `strong_partial_match`, `weak_partial_match`)

### Digest

```bash
news-intel digest --topic "ukraine_financing" --days 3
news-intel digest --topic "europe_ru_war_preparations" --days 7
news-intel digest --topic "china_taiwan_risk" --days 7
news-intel digest --topic "iran_war_risk" --days 7
news-intel digest --topic "migration_policy_europe" --days 7
news-intel digest --topic "global_trade_and_country_flows" --days 7
```

## OpenClaw Skill Integration

- Workspace skill: `openclaw-skills/news-intelligence/SKILL.md`
- Runtime skill: `~/.openclaw/custom-skills/news-intelligence/SKILL.md`

Allowed command set is intentionally narrow and safe for research-grade operation.

## Verification

Run tests:

```bash
pytest -q
```

Run smoke test:

```bash
bash scripts/smoke_test.sh
```

Typical sanity sequence:

```bash
news-intel sources
news-intel ingest --mode rss --max-items 5
news-intel stats
news-intel search "Ukraine"
news-intel digest --topic "ukraine_financing" --days 3
```

## Legal and Access Policy

This project is intentionally constrained to public/legal access paths.

- Keep RSS as the core ingestion path.
- Keep Fundus and GDELT optional.
- Do not bypass publisher restrictions.
- Treat restricted outlets as metadata-only unless licensed API access exists.

## Troubleshooting

- `news-intel: command not found`:
  activate `.venv` and reinstall editable package.
- `pip install -e .` fails:
  upgrade `pip setuptools wheel` first.
- `fundus` mode fails:
  install optional extra `.[fundus]` and required host libs.
- `gdelt` warnings:
  expected under timeout/rate-limit conditions; RSS path should still work.

## License

No license file is currently included. Add one if you plan to distribute outside private use.
