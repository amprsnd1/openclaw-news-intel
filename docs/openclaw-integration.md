# OpenClaw Integration (Local CLI)

This project is prepared for OpenClaw to call `news-intel` as a local tool.
Canonical project path: `/path/to/news-intel`.

## Scope

- Local command execution only.
- No automatic code changes.
- No automatic wiring or daemon setup.

## Safe Command Set

- `news-intel sources`
- `news-intel stats`
- `news-intel source-groups`
- `news-intel source-health`
- `news-intel ingest --mode rss`
- `news-intel ingest --mode all`
- `news-intel scan --all-watchlists --since "<window>" --min-confidence medium --group-by-primary`
- `news-intel scan --topic "<topic>" --since "<window>"`
- `news-intel scan --topic "<topic>" --since "<window>" --source rss,google_news_rss`
- `news-intel scan --topic "<topic>" --since "<window>" --source official_defense,official_eu,defense_specialist,european_local,google_news_rss --min-confidence medium`
- `news-intel scan --topic "<topic>" --since "<window>" --source market_signals,google_news_rss --min-confidence medium`
- `news-intel scan --query "<query>" --since "<window>"`
- `news-intel scan --query "<query>" --since "<window>" --source market_signals,google_news_rss`
- `news-intel scan --topic "<topic>" --since "<window>" --only-new`
- `news-intel scan --topic "<topic>" --since "<window>" --min-confidence medium`
- `news-intel collect --topic "<topic>" --days <number> --max-items <number>`
- `news-intel collect --topic "<topic>" --days <number> --max-items <number> --max-queries <number> --use-cache-first`
- `news-intel collect --topic "<topic>" --days <number> --max-items <number> --dry-run-queries`
- `news-intel collect --topic "<topic>" --days <number> --max-items <number> --no-enrich`
- `news-intel collect --topic "<topic>" --days <number> --max-items <number> --enrich fundus`
- `news-intel enrich --topic "<topic>" --days <number> --adapter fundus --max-items <number>`
- `news-intel enrich --topic "<topic>" --days <number> --adapter fundus --max-items <number> --include-rss`
- `news-intel enrich-url "<public_url>" --adapter fundus`
- `news-intel search "<query>"`
- `news-intel digest --topic "<topic>" --days <number>`
- `news-intel digest --topic "<topic>" --days <number> --include-metadata-only`

## CLI Path Stability

- Expected CLI binary: `/path/to/news-intel/.venv/bin/news-intel`
- Recommended symlink for shell/OpenClaw compatibility:
  - `/opt/homebrew/bin/news-intel -> /path/to/news-intel/.venv/bin/news-intel`
- Do not rely on `PYTHONPATH` as the normal runtime path.

## Strategic Watchlist Topics

Use these topic names directly with `news-intel scan` for fast monitoring and `news-intel digest` for deeper research:

- `europe_ru_war_preparations`
- `china_taiwan_risk`
- `iran_war_risk`
- `migration_policy_europe`
- `global_trade_and_country_flows`

Example commands:

- `news-intel scan --topic "europe_ru_war_preparations" --since "2h" --only-new --min-confidence medium`
- `news-intel scan --topic "migration_policy_europe" --since "24h"`
- `news-intel scan --query "NATO troops eastern Europe" --since "24h"`
- `news-intel scan --topic "europe_ru_war_preparations" --since "6h" --source rss,google_news_rss`
- `news-intel scan --topic "europe_ru_war_preparations" --since "24h" --min-confidence medium`
- `news-intel scan --topic "global_trade_and_country_flows" --since "24h" --min-confidence medium`
- `news-intel scan --query "UK gilts debt issuance fiscal rules" --since "24h" --source market_signals,google_news_rss`
- `news-intel collect --topic "europe_ru_war_preparations" --days 7 --max-items 50 --max-queries 1 --use-cache-first`
- `news-intel enrich --topic "europe_ru_war_preparations" --days 30 --adapter fundus --max-items 100 --include-rss`
- `news-intel digest --topic "europe_ru_war_preparations" --days 7 --include-metadata-only`
- `news-intel enrich-url "<public_url>" --adapter fundus`
- `news-intel collect --topic "europe_ru_war_preparations" --days 7 --max-items 50 --dry-run-queries`
- `news-intel digest --topic "europe_ru_war_preparations" --days 7`
- `news-intel collect --topic "china_taiwan_risk" --days 7 --max-items 100 --no-enrich`
- `news-intel digest --topic "china_taiwan_risk" --days 7`
- `news-intel digest --topic "iran_war_risk" --days 7`
- `news-intel digest --topic "migration_policy_europe" --days 7`
- `news-intel digest --topic "global_trade_and_country_flows" --days 7`
- `news-intel enrich --topic "europe_ru_war_preparations" --days 7 --adapter fundus --max-items 25`

## Data Access Policy

- GDELT is the primary strategic topic discovery source.
- RSS-first ingestion remains available as a safe fallback.
- For quick news monitoring, prefer `scan`.
- For fast monitoring, use scan with source groups.
- For strategic defense/security topics, omit `--source` by default; topic defaults include `defense_specialist`, `european_local`, `google_news_rss`, `official_defense`, and `official_eu`.
- For macro/trade/markets topics, omit `--source` by default; topic defaults include `market_signals`, `official_financial`, and `google_news_rss`.
- For deeper research, use `collect -> enrich -> digest`.
- Fundus is not used by default in scan.
- Google News RSS is metadata/headline discovery only.
- Official sources are enabled only where stable public feeds are configured; otherwise they remain disabled roadmap placeholders.
- Fundus is optional enrichment only.
- No paywall bypassing.
- No scraping subscription-only content.
- Reuters, Bloomberg, FT, WSJ remain metadata-only unless licensed API integrations are added.
- Reports should disclose `access_mode` and `enrichment_status`.
- Strategic digest reports should distinguish high, medium, low confidence direct matches, near misses, and gaps.
- Signal scan reports should distinguish high, medium, and low signals, then source status and gaps.
- OpenClaw should report GDELT cache usage and rate-limit warnings.

## Recommended Fast Signal Workflow

- Run `news-intel scan --topic "<topic>" --since "2h" --only-new --min-confidence medium` for alert-style monitoring.
- Run `news-intel morning-scan` for morning headline checks.
- Explicit equivalent: `news-intel scan --all-watchlists --since "24h" --min-confidence medium --group-by-primary --fresh`.
- Run `news-intel scan --query "<query>" --since "24h"` for free-form monitoring.
- If RSS coverage looks thin, run `news-intel scan --topic "<topic>" --since "6h" --source rss,google_news_rss`.
- For defense/security topics, run `news-intel scan --topic "europe_ru_war_preparations" --since "24h" --min-confidence medium`.
- For macro/trade/markets topics, run `news-intel scan --topic "global_trade_and_country_flows" --since "24h" --min-confidence medium`.
- Only enrich after a signal needs deeper context.

Natural-language mapping examples:
- "check the latest signals" -> `news-intel scan --topic "<topic>" --since "2h" --only-new --min-confidence medium`
- "morning scan" -> `news-intel morning-scan`
- "morning headlines" -> `news-intel morning-scan`
- "watchlist scan" -> `news-intel morning-scan`
- "scan the last 24h" -> `news-intel morning-scan`
- "scan the last 2 hours" -> `news-intel scan --topic "<topic>" --since "2h" --only-new --min-confidence medium`
- "anything new on Europe-Russia war prep?" -> `news-intel scan --topic "europe_ru_war_preparations" --since "2h" --only-new --min-confidence medium`

## Recommended Strategic Workflow

- Run `news-intel collect --topic "<topic>" --days 7 --max-items 50 --max-queries 1 --use-cache-first`.
- Run `news-intel enrich --topic "<topic>" --days 30 --adapter fundus --max-items 100 --include-rss`.
- Run `news-intel digest --topic "<topic>" --days 7 --include-metadata-only`.
- If Fundus returns `enriched=0`, report the eligibility breakdown and skipped examples.
- If results look broad or weak, run `news-intel collect --topic "<topic>" --days 7 --max-items 50 --dry-run-queries` and inspect planned GDELT queries.
- Keep GDELT query counts conservative.

## Expected Behavior with Optional Adapter Failures

- RSS path should continue operating.
- Fundus missing: clear error only when fundus mode is explicitly requested.
- GDELT failure/rate-limit: warn and continue.


## Morning Scan Precision

Use `news-intel morning-scan` for broad morning monitoring. It runs fresh RSS ingest first, then runs `news-intel scan --all-watchlists --since "24h" --min-confidence medium --group-by-primary`. The explicit equivalent is `news-intel scan --all-watchlists --since "24h" --min-confidence medium --group-by-primary --fresh`. The scan groups repeated headlines into clusters, shows primary/secondary/spillover routing, and keeps each headline under one primary topic. Use `--show-rejected` on a single topic when investigating why a headline was excluded or demoted. High-alert summaries should mention source diversity. Market-only Iran headlines should route to trade/market with Iran as secondary; non-EU energy, NATO-Europe-as-China/Taiwan, and generic defense-tech war-prep false positives should be rejected or demoted.
