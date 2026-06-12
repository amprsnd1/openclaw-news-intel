# News Intelligence Skill
Use this skill to search, ingest, and summarize news through the local `news-intel` CLI.
This skill is for using the existing local news intelligence pipeline. It is not for modifying source code.
## Canonical Project Path
Use the canonical project path:
`/path/to/news-intel`

The expected CLI path is:
`/path/to/news-intel/.venv/bin/news-intel`
## Tool
The local CLI command is:
```bash
news-intel
```
## Allowed commands
Only use the following commands:
```bash
news-intel sources
news-intel stats
news-intel source-groups
news-intel source-health
news-intel ingest --mode rss
news-intel ingest --mode all
news-intel scan --all-watchlists --since "<window>" --min-confidence medium --group-by-primary
news-intel scan --all-watchlists --since "<window>" --min-confidence medium --primary-only
news-intel scan --topic "<topic>" --since "<window>"
news-intel scan --topic "<topic>" --since "<window>" --source rss,google_news_rss
news-intel scan --topic "<topic>" --since "<window>" --source official_defense,official_eu,defense_specialist,european_local,google_news_rss --min-confidence medium
news-intel scan --topic "<topic>" --since "<window>" --source market_signals,google_news_rss --min-confidence medium
news-intel scan --query "<query>" --since "<window>"
news-intel scan --query "<query>" --since "<window>" --source market_signals,google_news_rss
news-intel scan --topic "<topic>" --since "<window>" --only-new
news-intel scan --topic "<topic>" --since "<window>" --min-confidence medium
news-intel scan --topic "<topic>" --since "<window>" --show-rejected
news-intel collect --topic "<topic>" --days <number> --max-items <number>
news-intel collect --topic "<topic>" --days <number> --max-items <number> --max-queries <number> --use-cache-first
news-intel collect --topic "<topic>" --days <number> --max-items <number> --dry-run-queries
news-intel collect --topic "<topic>" --days <number> --max-items <number> --no-enrich
news-intel collect --topic "<topic>" --days <number> --max-items <number> --enrich fundus
news-intel enrich --topic "<topic>" --days <number> --adapter fundus --max-items <number>
news-intel enrich --topic "<topic>" --days <number> --adapter fundus --max-items <number> --include-rss
news-intel enrich-url "<public_url>" --adapter fundus
news-intel search "<query>"
news-intel digest --topic "<topic>" --days <number>
news-intel digest --topic "<topic>" --days <number> --include-metadata-only
```
## Core rules
- GDELT is the primary strategic topic discovery source.
- RSS is fallback and remains the core safe ingestion path.
- For quick news monitoring, prefer `scan`.
- For morning scans across all topics, prefer `news-intel scan --all-watchlists --since "24h" --min-confidence medium --group-by-primary`.
- For single-topic quick monitoring, use `news-intel scan --topic "<topic>" --since "24h" --min-confidence medium` and let topic defaults choose source groups.
- Use explicit `--source` only when the user asks for a specific source group.
- For strategic defense/security topics, topic defaults include `defense_specialist`, `european_local`, `google_news_rss`, `official_defense`, and `official_eu`.
- For macro/trade/markets topics, topic defaults include `market_signals`, `official_financial`, and `google_news_rss`.
- For deeper research, use `collect -> enrich -> digest`.
- Fundus is not used by default in scan; enrich only after a signal needs deeper context.
- Fundus is optional enrichment only.
- Do not bypass paywalls.
- Do not scrape subscription-only sources.
- Do not use browser automation to access restricted media.
- Reuters, Bloomberg, Financial Times, and Wall Street Journal are metadata-only unless licensed API access is configured.
- If Fundus or GDELT fails, continue with available data.
- Use collect before digest for strategic topics.
- Prefer conservative GDELT query counts.
- Use `--dry-run-queries` if a topic returns poor results.
- Always report GDELT rate limits and cache usage.
- Always distinguish high, medium, low confidence direct matches, near misses, and gaps.
- For scan output, always distinguish high, medium, and low signals, then report source status and gaps.
- For morning scans, prefer group-by-primary output.
- Do not duplicate the same article across multiple watchlists.
- Use `--group-by-primary` for recall-safe morning scans; use `--primary-only` only for legacy strict filtering.
- Morning scan output should group repeated headlines into event clusters.
- Use primary, secondary, and spillover routing when summarizing all-watchlist scans.
- Use `--show-rejected` when the user asks why something appeared or did not appear.
- High-alert claims should mention source diversity.
- Always include markdown links with real URLs when available.
- Do not classify market-only Iran items as primary Iran war signals; route inflation, rates, oil, shipping, and commodity-flow items to `global_trade_and_country_flows` with `iran_war_risk` as secondary when relevant.
- Do not classify non-EU energy stories as `eu_energy_security`.
- Do not classify NATO Europe stories as `china_taiwan_risk` unless China, Taiwan, PLA, Pacific, or semiconductor geopolitical context is present.
- Do not classify generic defense tech as `europe_ru_war_preparations` unless it is linked to Europe, Russia, NATO, readiness, procurement, deployment, or infrastructure hardening.
- If Fundus returns enriched=0, report the eligibility breakdown and skipped examples.
- Always include source, date, title, and URL when reporting article results.
- Always disclose access_mode and enrichment_status when reporting collected topic results.
- Prefer recent articles.
- Return concise markdown reports.
- Do not modify source code.
- Do not run arbitrary shell commands.
- Do not install new dependencies unless the user explicitly asks.
## Strategic watchlists
Use these topic names with digest commands:
- `europe_ru_war_preparations`
- `china_taiwan_risk`
- `iran_war_risk`
- `migration_policy_europe`
- `global_trade_and_country_flows`

Examples:
```bash
news-intel digest --topic "europe_ru_war_preparations" --days 7
news-intel digest --topic "china_taiwan_risk" --days 7
news-intel digest --topic "iran_war_risk" --days 7
news-intel digest --topic "migration_policy_europe" --days 7
news-intel digest --topic "global_trade_and_country_flows" --days 7
```
## Recommended workflow
For a source health check, run:
```bash
news-intel sources
news-intel source-groups
news-intel source-health
news-intel stats
```
For morning watchlist coverage, run:
```bash
news-intel scan --all-watchlists --since "24h" --min-confidence medium --group-by-primary
```
For quick single-topic monitoring, run:
```bash
news-intel scan --topic "<topic>" --since "2h" --only-new --min-confidence medium
```
For defense/security monitoring, run:
```bash
news-intel scan --topic "europe_ru_war_preparations" --since "24h" --min-confidence medium
```
For macro/trade/markets monitoring, run:
```bash
news-intel scan --topic "global_trade_and_country_flows" --since "24h" --min-confidence medium
```
For Ukraine financing headline signals, run:
```bash
news-intel scan --topic "ukraine_financing" --since "24h" --min-confidence medium
```
Natural language mappings:
- "check the latest signals" -> `news-intel scan --topic "<topic>" --since "2h" --only-new --min-confidence medium`
- "morning headlines" -> `news-intel scan --all-watchlists --since "24h" --min-confidence medium --group-by-primary`
- "scan the last 2 hours" -> `news-intel scan --topic "<topic>" --since "2h" --only-new --min-confidence medium`
- "morning scan for Europe-Russia war prep" -> `news-intel scan --topic "europe_ru_war_preparations" --since "24h" --min-confidence medium`
- "market signal scan" -> `news-intel scan --topic "global_trade_and_country_flows" --since "24h" --min-confidence medium`
- "Ukraine financing headlines" -> `news-intel scan --topic "ukraine_financing" --since "24h" --min-confidence medium`
- "anything new on Europe-Russia war prep?" -> `news-intel scan --topic "europe_ru_war_preparations" --since "2h" --only-new --min-confidence medium`
For a fresh digest, run:
```bash
news-intel collect --topic "<topic>" --days 7 --max-items 50 --max-queries 1 --use-cache-first
news-intel enrich --topic "<topic>" --days 30 --adapter fundus --max-items 100 --include-rss
news-intel digest --topic "<topic>" --days <number> --include-metadata-only
```
To inspect planned GDELT queries without network calls, run:
```bash
news-intel collect --topic "<topic>" --days 7 --max-items 50 --dry-run-queries
```
For RSS fallback ingestion, run:
```bash
news-intel ingest --mode rss
```
For optional Fundus enrichment of already collected articles, run:
```bash
news-intel enrich --topic "<topic>" --days 7 --adapter fundus --max-items 50
```
For a Fundus URL diagnostic, run:
```bash
news-intel enrich-url "<public_url>" --adapter fundus
```
For a search task, run:
```bash
news-intel search "<query>"
```
## Output format
When generating a research briefing, use this structure:
```md
# Briefing
## Key Facts
- ...
## Source List
- Source, date, title, URL
## Inferences
- ...
## Gaps
- ...
## What to Monitor Next
- ...
```
## Safety note
Never attempt to bypass publisher restrictions. If a source is paywalled, restricted, unavailable, or metadata-only, clearly say so.
