# Security and Privacy Guardrails

This repository is intended to be shareable/public-safe.

## Never Commit

- Private keys (`*.pem`, `*.key`, `id_rsa`, `id_ed25519`)
- Tokens/API keys/passwords
- Personal local runtime state (`.openclaw/`, `.claude/`, `.codex/`)
- Local databases with operational data (`data/*.sqlite`)
- Any host-identifying paths, local machine details, or personal secrets

## Before Pushing

Run a quick local scan:

```bash
rg -n "BEGIN [A-Z ]*PRIVATE KEY|gho_|github_pat_|AKIA|AIza|xox[baprs]-|token|api[_-]?key|password|secret" -S --hidden --glob '!.git/*' .
```

If anything sensitive appears, remove it before commit/push.

## Reporting

If sensitive content is discovered in history, rotate affected credentials immediately and rewrite git history before pushing.
