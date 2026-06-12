# OpenClaw Quickstart

`news-intel` is a local headline signal scanner and news intelligence connector for OpenClaw agents.

## Install the Local CLI

```bash
bash scripts/setup.sh
source .venv/bin/activate
news-intel doctor
news-intel morning-scan
```

## Install the OpenClaw Skill

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

## Example Prompts

- Use News Intelligence. Run morning scan.
- Use News Intelligence. Scan Iran war risk for the last 24h.
- Use News Intelligence. Search local database for Ukraine IMF loan.
- Use News Intelligence. Run a deep digest for Europe-Russia war preparations.

## Troubleshooting

- OpenClaw does not see skill: run `bash scripts/install_openclaw_skill.sh`, then restart OpenClaw.
- `news-intel` not in PATH: activate `.venv` or point `/opt/homebrew/bin/news-intel` to `/path/to/news-intel/.venv/bin/news-intel`.
- Runtime skill stale: rerun the install script to sync `openclaw-skills/news-intelligence/SKILL.md` to `~/.openclaw/custom-skills/news-intelligence/SKILL.md`.
- Gateway stale: run `openclaw stop` and `openclaw start`.
- Setup uncertainty: run `news-intel doctor` and follow the reported degraded or fatal issues.
