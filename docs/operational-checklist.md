# Operational Checklist

## Before Use

- `bash scripts/setup.sh`
- `bash scripts/smoke_test.sh`
- Confirm `news-intel sources` reports `rss: available`.

## Routine Run

- `news-intel ingest --mode rss --max-items 5`
- `news-intel stats`
- `news-intel search "<query>"`
- `news-intel digest --topic "<topic>" --days <n>`

## Strategic Digest Runs

- `news-intel digest --topic "europe_ru_war_preparations" --days 7`
- `news-intel digest --topic "china_taiwan_risk" --days 7`
- `news-intel digest --topic "iran_war_risk" --days 7`
- `news-intel digest --topic "migration_policy_europe" --days 7`
- `news-intel digest --topic "global_trade_and_country_flows" --days 7`

## Compliance Guardrails

- Do not bypass paywalls.
- Do not scrape restricted/subscription content.
- Keep Reuters/Bloomberg/FT/WSJ as metadata-only unless licensed APIs are configured.

## Failure Handling

- Fundus missing: acceptable unless explicitly running `--mode fundus`.
- GDELT unavailable/rate-limited: warn and proceed with RSS data.
- If RSS ingest fails, treat as blocking and investigate feed/network/runtime.
