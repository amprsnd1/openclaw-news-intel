from pathlib import Path

LOCAL_REPO_PATH = "/".join(["", "Users", "nick", "news-intel"])


def test_openclaw_skill_includes_collect_and_enrich_commands() -> None:
    text = Path("openclaw-skills/news-intelligence/SKILL.md").read_text(encoding="utf-8")
    assert "news-intel source-groups" in text
    assert "news-intel source-health" in text
    assert "news-intel morning-scan" in text
    assert "`<repo>`" in text
    assert "`<repo>/.venv/bin/news-intel`" in text
    assert LOCAL_REPO_PATH not in text
    assert 'news-intel scan --all-watchlists --since "<window>" --min-confidence medium --group-by-primary' in text
    assert 'news-intel scan --all-watchlists --since "<window>" --min-confidence medium --group-by-primary --fresh' in text
    assert 'news-intel scan --all-watchlists --since "<window>" --min-confidence medium --primary-only' in text
    assert 'news-intel scan --topic "<topic>" --since "<window>"' in text
    assert 'news-intel scan --topic "<topic>" --since "<window>" --source rss,google_news_rss' in text
    assert 'news-intel scan --topic "<topic>" --since "<window>" --source official_defense,official_eu,defense_specialist,european_local,google_news_rss --min-confidence medium' in text
    assert 'news-intel scan --topic "<topic>" --since "<window>" --source market_signals,google_news_rss --min-confidence medium' in text
    assert 'news-intel scan --query "<query>" --since "<window>"' in text
    assert 'news-intel scan --query "<query>" --since "<window>" --source market_signals,google_news_rss' in text
    assert 'news-intel scan --topic "<topic>" --since "<window>" --only-new' in text
    assert 'news-intel scan --topic "<topic>" --since "<window>" --min-confidence medium' in text
    assert 'news-intel scan --topic "<topic>" --since "<window>" --show-rejected' in text
    assert 'news-intel collect --topic "<topic>" --days <number> --max-items <number>' in text
    assert 'news-intel collect --topic "<topic>" --days <number> --max-items <number> --max-queries <number> --use-cache-first' in text
    assert 'news-intel collect --topic "<topic>" --days <number> --max-items <number> --dry-run-queries' in text
    assert 'news-intel collect --topic "<topic>" --days <number> --max-items <number> --no-enrich' in text
    assert 'news-intel collect --topic "<topic>" --days <number> --max-items <number> --enrich fundus' in text
    assert 'news-intel enrich --topic "<topic>" --days <number> --adapter fundus --max-items <number>' in text
    assert 'news-intel enrich --topic "<topic>" --days <number> --adapter fundus --max-items <number> --include-rss' in text
    assert 'news-intel enrich-url "<public_url>" --adapter fundus' in text
    assert 'news-intel digest --topic "<topic>" --days <number> --include-metadata-only' in text
    assert "GDELT is the primary strategic topic discovery source." in text
    assert "`news-intel doctor` exit codes: `0` means usable, `1` means broken required component, `2` means usable but degraded." in text
    assert "If `news-intel doctor` exits `2`, treat it as non-fatal" in text
    assert "If doctor reports GDELT rate-limited, continue using `news-intel morning-scan`" in text
    assert "Always disclose access_mode and enrichment_status" in text
    assert "Prefer conservative GDELT query counts." in text
    assert "Always distinguish high, medium, low confidence direct matches, near misses, and gaps." in text
    assert "If Fundus returns enriched=0, report the eligibility breakdown and skipped examples." in text
    assert "For quick news monitoring, prefer `scan`." in text
    assert "Always refresh RSS before a morning scan." in text
    assert 'For morning scans across all topics, prefer `news-intel morning-scan`.' in text
    assert 'let topic defaults choose source groups' in text
    assert "Use explicit `--source` only when the user asks for a specific source group." in text
    assert "For morning scans, prefer group-by-primary output." in text
    assert "Use `--group-by-primary` for recall-safe morning scans" in text
    assert '"morning scan" -> `news-intel morning-scan`' in text
    assert '"scan the last 24h" -> `news-intel morning-scan`' in text
    assert "Do not duplicate the same article across multiple watchlists." in text
    assert "High-alert claims should mention source diversity." in text
    assert "Always include markdown links with real URLs when available." in text
    assert "Morning scan output should group repeated headlines into event clusters." in text
    assert "Use primary, secondary, and spillover routing" in text
    assert "Do not classify market-only Iran items as primary Iran war signals" in text
    assert "Do not classify non-EU energy stories as `eu_energy_security`." in text
    assert "Do not classify NATO Europe stories as `china_taiwan_risk`" in text
    assert "Do not classify generic defense tech as `europe_ru_war_preparations`" in text
