#!/usr/bin/env bash
# ----------------------------------------------------------------------
# smoke_test.sh - End-to-end smoke test for the oci-drawio-architect plugin
#
# Steps:
#   1. Run examples/generate_demo_diagram.py into a temp directory
#   2. Run scripts/check_overlaps.py on the result (mandatory gate)
#   3. If a draw.io binary is available, export a PNG next to the .drawio
#      (/Applications/draw.io.app/Contents/MacOS/draw.io, `drawio` on PATH,
#      or $DRAWIO_BIN). Set SMOKE_SKIP_PNG=1 to skip this step.
#
# Usage:
#   scripts/smoke_test.sh [plugin_dir]
#
# Defaults to the plugin directory containing this script. Output files are
# kept (paths are printed) so they can be opened for inspection; set
# SMOKE_OUT_DIR to control where they go. Exits non-zero on any failure.
# ----------------------------------------------------------------------
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $1" >&2; exit 1; }

# --- Locate the plugin ------------------------------------------------
if [[ -n "${1:-}" ]]; then
    [[ -d "$1" ]] || fail "Plugin directory not found: $1"
    PLUGIN_DIR="$(cd "$1" && pwd)"
else
    PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fi

GENERATOR="$PLUGIN_DIR/examples/generate_demo_diagram.py"
CHECKER="$PLUGIN_DIR/scripts/check_overlaps.py"
BUILDER="$PLUGIN_DIR/scripts/drawio_builder.py"

command -v python3 >/dev/null 2>&1 || fail "python3 not found on PATH"
[[ -f "$GENERATOR" ]] || fail "Missing $GENERATOR"
[[ -f "$CHECKER" ]]   || fail "Missing $CHECKER"
[[ -f "$BUILDER" ]]   || fail "Missing $BUILDER"

echo "Smoke-testing plugin at $PLUGIN_DIR"
echo ""

# --- Output location ---------------------------------------------------
if [[ -n "${SMOKE_OUT_DIR:-}" ]]; then
    mkdir -p "$SMOKE_OUT_DIR"
    OUT_DIR="$(cd "$SMOKE_OUT_DIR" && pwd)"
else
    TMP_BASE="${TMPDIR:-/tmp}"
    OUT_DIR="$(mktemp -d "${TMP_BASE%/}/oci-drawio-smoke.XXXXXX")"
fi
DRAWIO_FILE="$OUT_DIR/oci-drawio-architect-smoke.drawio"
PNG_FILE="${DRAWIO_FILE%.drawio}.png"

# --- 1. Generate the demo diagram -------------------------------------
if ! python3 "$GENERATOR" "$DRAWIO_FILE"; then
    fail "Demo generator failed"
fi
[[ -s "$DRAWIO_FILE" ]] || fail "Demo generator produced no output at $DRAWIO_FILE"
info "Generated $DRAWIO_FILE"

# --- 2. Overlap gate --------------------------------------------------
if ! python3 "$CHECKER" "$DRAWIO_FILE"; then
    fail "Overlap check failed for $DRAWIO_FILE"
fi
info "Overlap check passed"

# --- 3. Optional PNG export via draw.io -------------------------------
if [[ "${SMOKE_SKIP_PNG:-0}" == "1" ]]; then
    warn "PNG export skipped (SMOKE_SKIP_PNG=1)"
else
    DRAWIO_BIN="${DRAWIO_BIN:-}"
    if [[ -n "$DRAWIO_BIN" && -x "$DRAWIO_BIN" ]]; then
        :   # explicit override via $DRAWIO_BIN
    elif [[ -x /Applications/draw.io.app/Contents/MacOS/draw.io ]]; then
        DRAWIO_BIN=/Applications/draw.io.app/Contents/MacOS/draw.io
    elif command -v drawio >/dev/null 2>&1; then
        DRAWIO_BIN="$(command -v drawio)"
    fi

    if [[ -z "$DRAWIO_BIN" ]]; then
        warn "draw.io not found (looked for /Applications/draw.io.app and 'drawio' on PATH); PNG export skipped"
    else
        # Electron apps chatter on stderr; keep it but only show it on failure.
        EXPORT_LOG="$(mktemp)"
        if "$DRAWIO_BIN" -x -f png -o "$PNG_FILE" "$DRAWIO_FILE" >"$EXPORT_LOG" 2>&1 && [[ -s "$PNG_FILE" ]]; then
            info "Exported PNG $PNG_FILE"
        else
            tail -n 20 "$EXPORT_LOG" >&2
            rm -f "$EXPORT_LOG"
            fail "PNG export failed using $DRAWIO_BIN"
        fi
        rm -f "$EXPORT_LOG"
    fi
fi

echo ""
echo "Smoke test passed."
echo "  drawio: $DRAWIO_FILE"
[[ -s "$PNG_FILE" ]] && echo "  png:    $PNG_FILE"
exit 0
