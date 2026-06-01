#!/usr/bin/env bash
set -euo pipefail

if [ ! -f ".venv/bin/activate" ]; then
  echo "ERROR: .venv is missing. Run: bash scripts/setup.sh" >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

run_cmd() {
  local name="$1"
  shift
  echo "==> ${name}"
  local out
  if ! out="$($@ 2>&1)"; then
    echo "ERROR: command failed: $*" >&2
    echo "$out" >&2
    exit 1
  fi
  echo "$out"
  echo
  printf '%s' "$out"
}

sources_out="$(run_cmd "sources" news-intel sources)"
if [[ "$sources_out" != *"rss: available"* ]]; then
  echo "ERROR: RSS adapter is not reported as available." >&2
  exit 1
fi

ingest_out="$(run_cmd "ingest rss" news-intel ingest --mode rss --max-items 5)"
if [[ "$ingest_out" != *"Ingest complete:"* ]]; then
  echo "ERROR: RSS ingest did not complete successfully." >&2
  exit 1
fi

stats_out="$(run_cmd "stats" news-intel stats)"
if [[ "$stats_out" != *"Total articles:"* ]]; then
  echo "ERROR: stats output missing total articles." >&2
  exit 1
fi

search_out="$(run_cmd "search" news-intel search "Ukraine")"
if [[ "$search_out" != *"# Search Results: Ukraine"* ]]; then
  echo "ERROR: search output is malformed." >&2
  exit 1
fi

digest_out="$(run_cmd "digest" news-intel digest --topic "ukraine_financing" --days 3)"
if [[ "$digest_out" != *"# Digest: ukraine_financing (last 3 day(s))"* ]]; then
  echo "ERROR: digest output is malformed." >&2
  exit 1
fi

echo "Smoke test passed: RSS core path, storage, search, and digest are operational."
