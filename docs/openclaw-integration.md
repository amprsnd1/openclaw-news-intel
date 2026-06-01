# OpenClaw Integration (Local CLI)

This project is prepared for OpenClaw to call `news-intel` as a local tool.

## Scope

- Local command execution only.
- No automatic code changes.
- No automatic wiring or daemon setup.

## Safe Command Set

- `news-intel sources`
- `news-intel stats`
- `news-intel ingest --mode rss`
- `news-intel ingest --mode all`
- `news-intel search "<query>"`
- `news-intel digest --topic "<topic>" --days <number>`

## Strategic Watchlist Topics

Use these topic names directly with `news-intel digest`:

- `europe_ru_war_preparations`
- `china_taiwan_risk`
- `iran_war_risk`
- `migration_policy_europe`
- `global_trade_and_country_flows`

Example commands:

- `news-intel digest --topic "europe_ru_war_preparations" --days 7`
- `news-intel digest --topic "china_taiwan_risk" --days 7`
- `news-intel digest --topic "iran_war_risk" --days 7`
- `news-intel digest --topic "migration_policy_europe" --days 7`
- `news-intel digest --topic "global_trade_and_country_flows" --days 7`

## Data Access Policy

- RSS-first architecture is retained.
- Fundus and GDELT are optional.
- No paywall bypassing.
- No scraping subscription-only content.
- Reuters, Bloomberg, FT, WSJ remain metadata-only unless licensed API integrations are added.

## Expected Behavior with Optional Adapter Failures

- RSS path should continue operating.
- Fundus missing: clear error only when fundus mode is explicitly requested.
- GDELT failure/rate-limit: warn and continue.
