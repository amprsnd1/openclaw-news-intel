#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required but not found in PATH." >&2
  exit 1
fi

if [ -d ".venv" ]; then
  # Recreate moved/broken virtualenvs (common after folder rename/move).
  if [ ! -x ".venv/bin/python3" ]; then
    rm -rf .venv
  else
    expected_prefix="$(cd .venv && pwd)"
    current_prefix="$(.venv/bin/python3 -c 'import pathlib,sys; print(pathlib.Path(sys.prefix).resolve())' 2>/dev/null || true)"
    activate_prefix="$(sed -n 's/^VIRTUAL_ENV=\"\\(.*\\)\"$/\\1/p' .venv/bin/activate | head -n 1)"
    if [ "$current_prefix" != "$expected_prefix" ] || [ "$activate_prefix" != "$expected_prefix" ]; then
      rm -rf .venv
    fi
  fi
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install -e .

echo "Setup complete. Next run: bash scripts/smoke_test.sh"
