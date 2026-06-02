# openclaw-news-intel

GDELT-first topic discovery and local news intelligence pipeline designed for OpenClaw workflows.

`news-intel` collects, normalizes, deduplicates, filters, and summarizes news from public/legal sources into a local SQLite database, then exposes search and digest commands for repeatable briefings.

## What This Project Does

- Collects strategic topic metadata from GDELT.
- Keeps public RSS ingestion as a safe fallback path.
- Supports optional Fundus enrichment for public supported articles.
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

- Strategic topic discovery: `gdelt`
- Safe fallback ingestion: `rss`
- Optional enrichment: `fundus` (extra dependency)
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

If native dependency errors occur on macOS, install only the required compression libraries and retry:

```bash
brew install lz4 xz zstd
CPPFLAGS="-I/opt/homebrew/include" LDFLAGS="-L/opt/homebrew/lib" python3 -m pip install -e ".[fundus]"
```

Fundus is only used for public supported publishers. Restricted outlets remain metadata-only unless licensed API access is configured.

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

### Topic collection

```bash
news-intel collect --topic "europe_ru_war_preparations" --days 7 --max-items 100
news-intel collect --topic "europe_ru_war_preparations" --days 7 --max-items 50 --max-queries 1 --use-cache-first
news-intel collect --topic "europe_ru_war_preparations" --days 7 --max-items 50 --dry-run-queries
news-intel collect --topic "china_taiwan_risk" --days 7 --max-items 100 --no-enrich
news-intel collect --topic "europe_ru_war_preparations" --days 7 --max-items 100 --enrich fundus
news-intel collect --topic "europe_ru_war_preparations" --days 7 --max-items 100 --source gdelt
news-intel collect --topic "europe_ru_war_preparations" --days 7 --max-items 100 --source gdelt,rss
```

Collection uses GDELT query discovery, stores metadata locally, classifies relevance against the watchlist, and optionally enriches public supported URLs with Fundus. GDELT failures are warnings, not hard failures.

Recommended strategic workflow:

```bash
news-intel collect --topic "<topic>" --days 7 --max-items 50 --max-queries 1 --use-cache-first
news-intel digest --topic "<topic>" --days 7
```

Current recommended workflow for strategic topics:

```bash
news-intel collect --topic "<topic>" --days 7 --max-items 50 --max-queries 1 --use-cache-first
news-intel enrich --topic "<topic>" --days 30 --adapter fundus --max-items 100 --include-rss
news-intel digest --topic "<topic>" --days 7 --include-metadata-only
```

Use `--dry-run-queries` to inspect planned GDELT queries without network calls. Conservative GDELT defaults reduce rate-limit risk:
- max queries per topic: `2`
- max items per query: `10`
- cache TTL: `180` minutes
- delay between live GDELT queries: `15` seconds
- stop further GDELT queries after first HTTP 429

### Enrichment

```bash
news-intel enrich --topic "europe_ru_war_preparations" --days 7 --adapter fundus --max-items 25
news-intel enrich --topic "europe_ru_war_preparations" --days 30 --adapter fundus --max-items 100 --include-rss
news-intel enrich-url "https://www.bbc.com/news/articles/example" --adapter fundus
```

Fundus is optional. Restricted/paywalled domains are skipped and remain metadata-only.
If `enriched=0`, the CLI prints an eligibility breakdown and skipped examples.

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
news-intel digest --topic "europe_ru_war_preparations" --days 7 --include-metadata-only
```

Strategic topic digests split direct matches by confidence:
- high confidence
- medium confidence
- low confidence

Digest items include access mode, discovery source, enrichment status, relevance class, confidence, reason, and matched watchlist terms.

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
news-intel collect --topic "europe_ru_war_preparations" --days 7 --max-items 50 --max-queries 1 --use-cache-first
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
