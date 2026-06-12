#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

bash scripts/setup.sh
# shellcheck disable=SC1091
source .venv/bin/activate

if ! CPPFLAGS="-I/opt/homebrew/include" LDFLAGS="-L/opt/homebrew/lib" python3 -m pip install -e ".[fundus]"; then
  cat >&2 <<'ERR'
Fundus optional install failed.

If this is a macOS native dependency error, install only the likely compression libraries, then retry:
  brew install lz4 xz zstd
  CPPFLAGS="-I/opt/homebrew/include" LDFLAGS="-L/opt/homebrew/lib" python3 -m pip install -e ".[fundus]"

The core news-intel pipeline works without Fundus.
ERR
  exit 1
fi

news-intel doctor || true
