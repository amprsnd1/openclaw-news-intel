# OpenClaw Quickstart

`news-intel` is a local headline signal scanner and news intelligence connector for OpenClaw agents.

OpenClaw does not scrape news directly. It calls the local `news-intel` CLI through the News Intelligence skill.

## Primary workflow

Use this for morning monitoring:

```bash
news-intel morning-scan
```

This refreshes RSS, scans watchlists, clusters related headlines, and returns a compact briefing.

## Install the local CLI

```bash
bash scripts/setup.sh
source .venv/bin/activate
news-intel doctor
news-intel morning-scan
```

## Install the OpenClaw skill

```bash
bash scripts/install_openclaw_skill.sh
openclaw skills info news-intelligence
```

If OpenClaw still does not see the skill, restart the gateway:

```bash
openclaw stop
openclaw start
openclaw skills info news-intelligence
```

## Example prompts

- Use News Intelligence. Run morning scan.
- Use News Intelligence. Scan Iran war risk for the last 24h.
- Use News Intelligence. Search local database for Ukraine IMF loan.
- Use News Intelligence. Run a deep digest for Europe-Russia war preparations.

## Advanced research prompt

Use research mode only when a deeper briefing is needed:

```text
Use News Intelligence. Run a deep digest for Europe-Russia war preparations.
```

OpenClaw should map that to `collect -> enrich -> digest`, not to the default morning scan.

## Troubleshooting

- OpenClaw does not see skill: run `bash scripts/install_openclaw_skill.sh`, then restart OpenClaw.
- `news-intel` not in PATH: activate `.venv` or point `/opt/homebrew/bin/news-intel` to `<repo>/.venv/bin/news-intel`.
- Runtime skill stale: rerun the install script to sync `openclaw-skills/news-intelligence/SKILL.md` to `~/.openclaw/custom-skills/news-intelligence/SKILL.md`.
- Gateway stale: run `openclaw stop` and `openclaw start`.
- Setup uncertainty: run `news-intel doctor` and follow the reported degraded or fatal issues.
- `news-intel doctor` exit `2`: treat as `usable_but_degraded`, not fatal. Continue with `news-intel morning-scan` if RSS/config/database are healthy; retry optional GDELT/Fundus/OpenClaw setup later as needed.
- Source health confusion: `disabled_roadmap` entries are intentionally inactive placeholders for sources without stable public feeds; only `failed_enabled` indicates a live enabled source problem.
