#!/usr/bin/env bash
# =============================================================================
# run_morning_scan.sh — Local news-intel morning scan wrapper
#
# Saves the raw markdown output to reports/morning/ for later summarization.
# Separates news collection (this script) from AI summarization (OpenClaw cron).
# =============================================================================

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$PROJECT_DIR/reports/morning"
TODAY="$(date +%F)"
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
OUT_FILE="$REPORT_DIR/$TODAY.md"
LATEST_FILE="$REPORT_DIR/latest.md"
ERROR_FILE="$REPORT_DIR/latest-error.log"

# Ensure report directory exists
mkdir -p "$REPORT_DIR"

# Change to project directory and activate venv
cd "$PROJECT_DIR"
# shellcheck source=/dev/null
source .venv/bin/activate

# Track whether news-intel itself failed
SCAN_FAILED=false

{
    echo "<!-- generated_at: $TIMESTAMP -->"
    echo "<!-- source: news-intel morning-scan -->"
    echo ""
    if ! news-intel morning-scan 2>&1; then
        SCAN_FAILED=true
    fi
} > "$OUT_FILE" 2>&1

# Copy to latest
cp "$OUT_FILE" "$LATEST_FILE"

# If news-intel failed, also write an error marker
if $SCAN_FAILED; then
    echo "news-intel morning-scan failed at $TIMESTAMP" > "$ERROR_FILE"
    echo "Output saved to: $OUT_FILE" >> "$ERROR_FILE"
    echo "Script exit: failure" >&2
    exit 1
fi

# Clear stale error file on success
rm -f "$ERROR_FILE"

echo "Morning scan saved:"
echo "  $OUT_FILE"
echo "  $LATEST_FILE"
