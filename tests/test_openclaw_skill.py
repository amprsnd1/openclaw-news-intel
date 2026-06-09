from pathlib import Path


def test_openclaw_skill_includes_collect_and_enrich_commands() -> None:
    text = Path("openclaw-skills/news-intelligence/SKILL.md").read_text(encoding="utf-8")
    assert 'news-intel scan --topic "<topic>" --since "<window>"' in text
    assert 'news-intel scan --topic "<topic>" --since "<window>" --source rss,google_news_rss' in text
    assert 'news-intel scan --query "<query>" --since "<window>"' in text
    assert 'news-intel scan --topic "<topic>" --since "<window>" --only-new' in text
    assert 'news-intel scan --topic "<topic>" --since "<window>" --min-confidence medium' in text
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
    assert "Always disclose access_mode and enrichment_status" in text
    assert "Prefer conservative GDELT query counts." in text
    assert "Always distinguish high, medium, low confidence direct matches, near misses, and gaps." in text
    assert "If Fundus returns enriched=0, report the eligibility breakdown and skipped examples." in text
    assert "For quick news monitoring, prefer `scan`." in text
