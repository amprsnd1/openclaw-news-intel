# News Intelligence Skill
Use this skill to search, ingest, and summarize news through the local `news-intel` CLI.
This skill is for using the existing local news intelligence pipeline. It is not for modifying source code.
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
news-intel ingest --mode rss
news-intel ingest --mode all
news-intel search "<query>"
news-intel digest --topic "<topic>" --days <number>
```
## Core rules
- RSS is the core ingestion path.
- Fundus is optional.
- GDELT is optional.
- Do not bypass paywalls.
- Do not scrape subscription-only sources.
- Do not use browser automation to access restricted media.
- Reuters, Bloomberg, Financial Times, and Wall Street Journal are metadata-only unless licensed API access is configured.
- If Fundus or GDELT fails, continue with available data.
- Always include source, date, title, and URL when reporting article results.
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
news-intel stats
```
For a fresh digest, run:
```bash
news-intel ingest --mode rss
news-intel digest --topic "<topic>" --days <number>
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
