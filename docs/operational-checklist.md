# Operational Checklist

## Before Use

- `bash scripts/install_openclaw_skill.sh` if OpenClaw should use the skill.
- `bash scripts/setup.sh`
- `bash scripts/smoke_test.sh`
- `news-intel doctor`
- Confirm `news-intel sources` reports `rss: available`.

## Routine Run

- `news-intel morning-scan`
- `news-intel scan --topic "<topic>" --since "2h" --only-new --min-confidence medium`
- `news-intel source-groups`
- `news-intel source-health`
- `news-intel ingest --mode rss --max-items 5`
- `news-intel collect --topic "<topic>" --days 7 --max-items 50 --max-queries 1 --use-cache-first`
- `news-intel enrich --topic "<topic>" --days 30 --adapter fundus --max-items 100 --include-rss`
- `news-intel stats`
- `news-intel search "<query>"`
- `news-intel digest --topic "<topic>" --days <n>`

## Fast Signal Runs

- `news-intel morning-scan`
- Explicit equivalent: `news-intel scan --all-watchlists --since "24h" --min-confidence medium --group-by-primary --fresh`
- Confirm all-watchlists output includes clusters, markdown links, primary/secondary/spillover routing, source diversity, and watchlist summary.
- Use `--show-rejected` for noisy topics before changing watchlist terms.

- `news-intel scan --topic "europe_ru_war_preparations" --since "2h" --only-new --min-confidence medium`
- `news-intel scan --topic "europe_ru_war_preparations" --since "24h" --min-confidence medium`
- `news-intel scan --topic "china_taiwan_risk" --since "6h"`
- `news-intel scan --topic "migration_policy_europe" --since "24h"`
- `news-intel scan --topic "global_trade_and_country_flows" --since "24h" --min-confidence medium`
- `news-intel scan --query "NATO troops eastern Europe" --since "24h"`
- `news-intel scan --query "UK gilts debt issuance fiscal rules" --since "24h" --source market_signals,google_news_rss`
- `news-intel scan --topic "europe_ru_war_preparations" --since "6h" --source rss,google_news_rss`

Use scan for headlines, alerts, quick monitoring, and early signal detection. Use collect/enrich/digest for deeper research and weekly review.

## Strategic Digest Runs (Advanced)

Use this after a signal appears or for a weekly/deep research briefing. It is not the default morning workflow.


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

## Compliance Guardrails

- Do not bypass paywalls.
- Do not scrape restricted/subscription content.
- Treat Google News RSS as headline metadata only.
- Enable official sources only when stable public RSS/Atom feeds exist.
- Keep Reuters/Bloomberg/FT/WSJ as metadata-only unless licensed APIs are configured.

## Failure Handling

- Fundus missing: acceptable unless explicitly running `--mode fundus`.
- To enable Fundus on macOS after native header errors: `brew install lz4 xz zstd`, then retry with `CPPFLAGS="-I/opt/homebrew/include" LDFLAGS="-L/opt/homebrew/lib" python3 -m pip install -e ".[fundus]"`.
- Fundus is only for public supported publishers; restricted outlets remain metadata-only unless licensed API access is configured.
- Fundus is not used by default in scan; enrich only after a signal needs deeper context.
- If Fundus returns `enriched=0`, review the printed eligibility breakdown and skipped examples.
- GDELT unavailable/rate-limited: warn and proceed with RSS data.
- After HTTP 429, stop further GDELT queries for that run and rely on cache/RSS fallback.
- If topic results are weak, inspect planned GDELT queries with `--dry-run-queries`.
- Digest confidence tiers should separate high, medium, low direct matches and near misses.
- If RSS ingest fails, treat as blocking and investigate feed/network/runtime.
