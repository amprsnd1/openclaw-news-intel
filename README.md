# openclaw-news-intel

Headline signal scanner and local news intelligence pipeline designed for OpenClaw workflows.

`news-intel` scans fresh public/legal headlines for watchlist signals, stores normalized metadata in SQLite, and can escalate from compact alert-style scans to deeper collection, enrichment, search, and digest workflows.

## Mental Model

`Sources -> Scan -> Watchlists -> Signals -> OpenClaw briefing`

RSS, Google News RSS, and GDELT discover fresh headlines and metadata. Watchlists define what to monitor. `scan` and `morning-scan` are for fast headline signals. `collect -> enrich -> digest` is for deeper research. Fundus optionally enriches public supported articles after a signal is found. Restricted outlets remain metadata-only unless licensed API access is configured.

## Quickstart

```bash
git clone <repo-url>
cd openclaw-news-intel
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

## What This Project Does

- Scans fresh RSS/metadata headlines for topic signals.
- Supports free-form headline scans.
- Collects strategic topic metadata from GDELT for deeper discovery.
- Keeps public RSS ingestion as a safe fallback path.
- Supports optional Fundus enrichment for public supported articles.
- Normalizes all items into a stable article schema.
- Deduplicates by canonical URL and near-duplicate title hash.
- Applies watchlists for topic monitoring.
- Generates compact signal scans, markdown search results, and research digests.
- Integrates with OpenClaw as a safe local CLI skill.

## What This Project Does Not Do

- No paywall bypassing.
- No scraping of subscription-only content.
- No brittle browser automation for Reuters/Bloomberg/FT/WSJ.
- Reuters, Bloomberg, Financial Times, and Wall Street Journal remain metadata-only unless licensed API access is configured.

## Core Architecture

- Fast signal mode: `rss` headline scanning by default
- Optional headline discovery: `google_news_rss`, `gdelt`
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
  scanner.py
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


## Which command should I use?

Morning headlines:

```bash
news-intel morning-scan
```

Scan one watchlist:

```bash
news-intel scan --topic "iran_war_risk" --since "24h"
```

Scan a free-form query:

```bash
news-intel scan --query "NATO troops eastern Europe" --since "24h"
```

Search local database:

```bash
news-intel search "Ukraine IMF loan" --mode precise
```

Deep research workflow:

```bash
news-intel collect --topic "<topic>" --days 7 --max-items 30 --max-queries 1 --use-cache-first
news-intel enrich --topic "<topic>" --days 30 --adapter fundus --max-items 50 --include-rss
news-intel digest --topic "<topic>" --days 7 --include-metadata-only
```

Check setup and sources:

```bash
news-intel doctor
news-intel sources
news-intel source-groups
news-intel source-health
```

## CLI Usage

### Source health

```bash
news-intel doctor
news-intel sources
news-intel source-groups
news-intel source-health
news-intel stats
```

### Fast Signal Mode

Use `scan` for quick monitoring, morning headlines, and alert-style checks. This is the preferred OpenClaw path for “anything new?” questions.

```bash
news-intel morning-scan
news-intel scan --topic "europe_ru_war_preparations" --since "2h"
news-intel scan --topic "china_taiwan_risk" --since "6h"
news-intel scan --topic "migration_policy_europe" --since "24h"
news-intel scan --query "NATO troops eastern Europe" --since "24h"
news-intel scan --all-watchlists --since "24h" --min-confidence medium --group-by-primary --fresh
news-intel scan --topic "europe_ru_war_preparations" --since "24h" --min-confidence medium
news-intel scan --topic "europe_ru_war_preparations" --since "24h" --only-new
```

Defaults:
- `source= rss`
- `since=6h`
- `max_items=50`
- `only_new=true`
- `format=markdown`

Optional headline discovery:

```bash
news-intel scan --query "NATO Russia readiness eastern Europe" --since "24h" --source google_news_rss
news-intel scan --topic "europe_ru_war_preparations" --since "6h" --source rss,google_news_rss
news-intel scan --topic "europe_ru_war_preparations" --since "6h" --source rss,gdelt --max-queries 1 --use-cache-first
news-intel scan --topic "europe_ru_war_preparations" --since "24h" --min-confidence medium
news-intel scan --topic "global_trade_and_country_flows" --since "24h" --min-confidence medium
news-intel scan --query "UK gilts debt issuance fiscal rules" --since "24h" --source market_signals,google_news_rss
```

Source groups:
- `news-intel source-health` reports configured/enabled/working sources and recent local item/signal counts without live network checks.
- `fast_headlines`: RSS plus Google News RSS for broad headline discovery.
- `official_defense`: public official NATO, military, and defense ministry feeds where stable; unstable official sources are disabled roadmap placeholders.
- `official_eu`: public EU institutional and foreign/security policy feeds.
- `official_financial`: public macro, fiscal, rates, debt, and statistical feeds.
- `defense_specialist`: public specialist defense/security media feeds.
- `european_local`: European local, national, and regional feeds useful for early signals.
- `market_signals`: public market, macro, rates, trade, and financial headline feeds.

Source policy:
- Google News RSS is headline/metadata discovery only and is stored as `public_metadata` or `metadata_only`.
- Official sources are only enabled when a stable public RSS/Atom feed is available.
- Public/partial sources are used only for headlines and metadata unless optional public Fundus enrichment succeeds.
- Restricted/paywalled sources are not scraped.

Scan behavior:
- `morning-scan` runs fresh RSS ingest with `--max-items 200`, then runs the all-watchlists signal scan.
- Use `news-intel scan --all-watchlists --since "24h" --min-confidence medium --group-by-primary --fresh` when you want the explicit equivalent.
- Morning all-watchlist scans use `--group-by-primary` to avoid duplicating the same headline across topics without suppressing valid signals.
- Morning all-watchlist scans group repeated headlines into event clusters and show primary, secondary, and spillover topic routing.
- Market-only Iran headlines route to `global_trade_and_country_flows` with `iran_war_risk` as secondary when relevant; non-EU energy headlines are rejected from `eu_energy_security`.
- China/Taiwan scans require China, Taiwan, PLA, Pacific, or semiconductor geopolitical context; NATO Europe-only stories do not qualify.
- Europe-Russia war-preparation scans require Europe/NATO/member-state context plus readiness, procurement, deployment, infrastructure, cyber, sabotage, or mobilization signals.
- Use `--show-rejected` to inspect rejected or demoted headlines and their reasons.
- Pulls headline/summary metadata first.
- Does not require full text.
- Does not run Fundus by default.
- Classifies matches as `high_signal`, `medium_signal`, `low_signal`, or `noise`.
- Hides previously shown scan items by default; use `--show-seen` to inspect older matches.
- Uses token-aware matching to avoid substring false positives.

Use optional Fundus enrichment only after a signal needs deeper context:

```bash
news-intel enrich --topic "<topic>" --days 1 --adapter fundus --max-items 10 --include-rss
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

### Research Digest Mode

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

Use research digest mode for longer briefings, weekly review, source diagnostics, and enriched context. Use scan mode first for fast headline monitoring.

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

## Example Output

See `docs/example-output.md` for a compact morning scan example with top alerts, clusters, source counts, watchlist summary, and source limits.

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


## Source Access Model

- RSS/public feeds: headline and public metadata.
- Google News RSS: metadata/headline discovery only.
- GDELT: metadata discovery; it can rate-limit and should be queried conservatively.
- Fundus: optional public article enrichment for supported publishers.
- Reuters, Bloomberg, FT, WSJ, and Dow Jones: metadata-only unless licensed API access is configured.

Paywall policy: This project does not bypass paywalls, logins, publisher restrictions, or subscription-only access. It is not a Reuters/Bloomberg scraper, a full-text news API, or a hosted production SaaS.

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

## License

No license file is currently included. Add one if you plan to distribute outside private use.
