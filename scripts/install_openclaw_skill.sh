#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_SKILL="$PROJECT_ROOT/openclaw-skills/news-intelligence/SKILL.md"
RUNTIME_DIR="$HOME/.openclaw/custom-skills/news-intelligence"
RUNTIME_SKILL="$RUNTIME_DIR/SKILL.md"
OPENCLAW_CONFIG="$HOME/.openclaw/openclaw.json"
CUSTOM_SKILLS_DIR="$HOME/.openclaw/custom-skills"
PROJECT_SKILLS_DIR="$PROJECT_ROOT/openclaw-skills"

if [ ! -f "$PROJECT_SKILL" ]; then
  echo "ERROR: project skill not found: $PROJECT_SKILL" >&2
  exit 1
fi

mkdir -p "$RUNTIME_DIR"

python3 - "$PROJECT_SKILL" "$RUNTIME_SKILL" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
text = source.read_text(encoding="utf-8")
front_matter = "---\nname: news-intelligence\ndescription: Safe local usage of the news-intel CLI for local headline signal scanning and news intelligence.\n---\n\n"
if not text.startswith("---\n"):
    text = front_matter + text
target.write_text(text, encoding="utf-8")
PY

echo "Installed runtime skill: $RUNTIME_SKILL"

mkdir -p "$(dirname "$OPENCLAW_CONFIG")"
python3 - "$OPENCLAW_CONFIG" "$CUSTOM_SKILLS_DIR" "$PROJECT_SKILLS_DIR" <<'PY'
from pathlib import Path
import json
import sys

config_path = Path(sys.argv[1])
extra_dirs = [str(Path(sys.argv[2]).expanduser()), str(Path(sys.argv[3]).expanduser())]
if config_path.exists():
    try:
        data = json.loads(config_path.read_text(encoding="utf-8") or "{}")
        if not isinstance(data, dict):
            data = {}
    except Exception:
        backup = config_path.with_suffix(config_path.suffix + ".bak")
        backup.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
        data = {}
else:
    data = {}

skills = data.setdefault("skills", {})
load = skills.setdefault("load", {})
current = load.get("extraDirs", [])
if isinstance(current, str):
    current = [current]
if not isinstance(current, list):
    current = []
for item in extra_dirs:
    if item not in current:
        current.append(item)
load["extraDirs"] = current
config_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

echo "Updated OpenClaw skills.load.extraDirs: $OPENCLAW_CONFIG"

if ! command -v openclaw >/dev/null 2>&1; then
  echo "WARNING: openclaw command not found. The skill files were installed, but OpenClaw registration could not be checked."
else
  echo "OpenClaw command detected. Next check: openclaw skills info news-intelligence"
fi

cat <<EOF2

Next steps:
  openclaw skills info news-intelligence
  openclaw stop
  openclaw start
EOF2
