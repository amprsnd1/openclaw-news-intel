# OpenClaw Prompt Examples

## 1) 3-day Ukraine financing digest

"Run `news-intel ingest --mode rss` then `news-intel digest --topic \"ukraine_financing\" --days 3`. Return concise markdown with source, date, title, and URL."

## 2) Source health check

"Run `news-intel sources` and `news-intel stats`. Summarize adapter availability, enabled source counts, and any ingestion risks."

## 3) Topic search

"Run `news-intel search \"Ukraine IMF loan\"` and summarize top matches with matched terms."

## 4) Europe Russia war preparations digest

"Run `news-intel collect --topic \"europe_ru_war_preparations\" --days 7 --max-items 50 --max-queries 1 --use-cache-first`, then `news-intel enrich --topic \"europe_ru_war_preparations\" --days 30 --adapter fundus --max-items 100 --include-rss`, then `news-intel digest --topic \"europe_ru_war_preparations\" --days 7 --include-metadata-only`. Return a concise briefing with source-linked items, access mode, enrichment status, confidence tier, and escalation-readiness signals. Report any GDELT cache usage, rate limits, and Fundus eligibility breakdown if enriched=0."

## 5) China Taiwan risk digest

"Run `news-intel collect --topic \"china_taiwan_risk\" --days 7 --max-items 100 --no-enrich` then `news-intel digest --topic \"china_taiwan_risk\" --days 7`. Focus on military pressure, blockade risk, and semiconductor supply-chain signals."

## 6) Iran war risk digest

"Run `news-intel ingest --mode rss` then `news-intel digest --topic \"iran_war_risk\" --days 7`. Focus on escalation indicators, shipping disruption, and energy-market implications."

## 7) Migration policy Europe digest

"Run `news-intel ingest --mode rss` then `news-intel digest --topic \"migration_policy_europe\" --days 7`. Summarize asylum, border-control, deportation, visa, and EU pact policy changes."

## 8) Global trade and country flows digest

"Run `news-intel ingest --mode rss` then `news-intel digest --topic \"global_trade_and_country_flows\" --days 7`. Focus on tariffs, export controls, shipping routes, and trade-flow disruptions."

## 9) Weekly macro briefing

"Run RSS ingest, then produce a 7-day briefing for macro-relevant developments using `news-intel search` and `news-intel digest`. Keep output concise and source-linked."

## 10) Optional Fundus enrichment

"Run `news-intel enrich --topic \"europe_ru_war_preparations\" --days 7 --adapter fundus --max-items 25`, then generate the digest again. Treat Fundus as optional and do not bypass publisher restrictions."

## 10a) Fundus URL diagnostic

"Run `news-intel enrich-url \"<public_url>\" --adapter fundus`. Report domain, eligibility, extraction status, text length, and failure reason. Do not use restricted outlets."

## 11) Restricted-source metadata disclaimer

"Include a disclaimer that Reuters, Bloomberg, FT, and WSJ are metadata-only unless licensed API access is configured."

## 12) Dry-run GDELT query inspection

"Run `news-intel collect --topic \"europe_ru_war_preparations\" --days 7 --max-items 50 --dry-run-queries`. Return the planned queries and identify whether they look too broad before running live collection."
