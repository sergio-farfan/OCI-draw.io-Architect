#!/usr/bin/env bash
# ----------------------------------------------------------------------
# install.sh - Install the oci-drawio-architect plugin for Claude Code
#
# What it does:
#   1. Pre-flight checks (Claude Code dir, Python 3, Pillow, copy tool).
#      Nothing is modified until every pre-flight check passes.
#   2. Copies the plugin into the local marketplace plugins/ directory
#      (staged, then atomically swapped in).
#   3. Upserts ONLY the oci-drawio-architect entry in marketplace.json;
#      other plugins and top-level fields are preserved.
#   4. Verifies the install and runs a post-install smoke test
#      (demo diagram + overlap checker).
#   5. Prints the commands to run inside Claude Code.
#
# Usage:
#   ./install.sh              # install for current user
#   ./install.sh --uninstall  # remove the plugin
#
# After running this script, open Claude Code and run:
#   /plugin marketplace add ~/.claude/plugins/marketplaces/local
#   /plugin install oci-drawio-architect@local
#
# Security note: every python3 helper below receives its inputs through
# environment variables - shell values are never spliced into Python
# source, so paths containing spaces or quotes are handled safely.
# ----------------------------------------------------------------------
set -euo pipefail

# --- Constants --------------------------------------------------------
PLUGIN_NAME="oci-drawio-architect"
PLUGIN_KEY="oci-drawio-architect@local"
MARKETPLACE_NAME="local"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGINS_DIR="$HOME/.claude/plugins"
MARKETPLACE_ROOT="$PLUGINS_DIR/marketplaces/$MARKETPLACE_NAME"
MARKETPLACE_PLUGIN_DIR="$MARKETPLACE_ROOT/plugins/$PLUGIN_NAME"
MARKETPLACE_JSON="$MARKETPLACE_ROOT/.claude-plugin/marketplace.json"
REGISTRY_JSON="$PLUGINS_DIR/installed_plugins.json"
CACHE_DIR="$PLUGINS_DIR/cache/$MARKETPLACE_NAME/$PLUGIN_NAME"
SOURCE_MANIFEST="$SOURCE_DIR/.claude-plugin/plugin.json"
SMOKE_DRAWIO="/tmp/oci-drawio-architect-smoke.drawio"
MIN_ICONS=150

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $1"; exit 1; }

# --- Helpers ----------------------------------------------------------

# Number of immediate subdirectories of $1 (0 when $1 is missing or empty;
# never aborts under set -e / pipefail).
count_subdirs() {
    local n=0
    if [[ -d "$1" ]]; then
        n=$(find "$1" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l) || n=0
    fi
    echo $((n))
}

# Number of regular files under $1 whose name matches glob $2.
count_files() {
    local n=0
    if [[ -d "$1" ]]; then
        n=$(find "$1" -type f -name "$2" 2>/dev/null | wc -l) || n=0
    fi
    echo $((n))
}

# Upsert (mode "upsert") or remove (mode "remove") our plugin entry in
# marketplace.json. Prints "<status> <remaining-entry-count>" where status
# is one of: upserted, removed, absent, invalid (-1 = file left untouched).
marketplace_edit() {
    MKT_MODE="$1" \
    MKT_JSON="$MARKETPLACE_JSON" \
    MKT_NAME="$MARKETPLACE_NAME" \
    MKT_OWNER="${USER:-$(id -un)}" \
    MKT_PLUGIN_NAME="$PLUGIN_NAME" \
    MKT_PLUGIN_JSON="$SOURCE_MANIFEST" \
    python3 - <<'PY'
import json
import os
import pathlib
import shutil
import sys

mode = os.environ["MKT_MODE"]
path = pathlib.Path(os.environ["MKT_JSON"])
name = os.environ["MKT_PLUGIN_NAME"]


def warn(msg):
    print(f"\033[1;33m[WARN]\033[0m  {msg}", file=sys.stderr)


def is_ours(entry):
    return isinstance(entry, dict) and entry.get("name") == name


data = None
if path.exists():
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top-level JSON value is not an object")
    except (ValueError, UnicodeDecodeError) as exc:
        if mode == "remove":
            warn(f"{path} is not valid JSON ({exc}); left untouched")
            print("invalid -1")
            sys.exit(0)
        backup = path.parent / (path.name + ".bak")
        shutil.copy2(path, backup)
        warn(f"{path} is not valid JSON ({exc}); backed up to {backup} and starting fresh")
        data = None

if data is None:
    if mode == "remove":
        print("absent 0")
        sys.exit(0)
    # Fresh marketplace: owner defaults to the current user.
    data = {
        "name": os.environ["MKT_NAME"],
        "description": "Local custom plugins",
        "owner": {"name": os.environ["MKT_OWNER"]},
        "plugins": [],
    }

plugins = data.get("plugins")
if not isinstance(plugins, list):
    if plugins is not None:
        warn("'plugins' in marketplace.json is not a list; resetting it to []")
    plugins = []
data["plugins"] = plugins

others = [p for p in plugins if not is_ours(p)]

if mode == "remove":
    if len(others) == len(plugins):
        print(f"absent {len(others)}")
        sys.exit(0)
    data["plugins"] = others
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"removed {len(others)}")
    sys.exit(0)

# --- upsert -----------------------------------------------------------
manifest = json.loads(pathlib.Path(os.environ["MKT_PLUGIN_JSON"]).read_text(encoding="utf-8"))
entry = next((p for p in plugins if is_ours(p)), None)
if entry is None:
    entry = {"name": name}
    plugins.append(entry)

fields = {
    "name": name,
    "description": manifest.get("description", ""),
    "version": manifest.get("version", "0.0.0"),
    "source": f"./plugins/{name}",
    "category": "productivity",
}
for key in ("author", "homepage", "license", "keywords"):
    if key in manifest:
        fields[key] = manifest[key]
entry.update(fields)  # other keys on our own entry (if any) are kept

path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print(f"upserted {len(plugins)}")
PY
}

# Remove our key from installed_plugins.json. Prints removed|absent|invalid.
registry_remove() {
    REG_JSON="$REGISTRY_JSON" REG_KEY="$PLUGIN_KEY" python3 - <<'PY'
import json
import os
import pathlib
import sys

path = pathlib.Path(os.environ["REG_JSON"])
key = os.environ["REG_KEY"]
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:
    print(f"\033[1;33m[WARN]\033[0m  Could not parse {path} ({exc}); left untouched", file=sys.stderr)
    print("invalid")
    sys.exit(0)

plugins = data.get("plugins") if isinstance(data, dict) else None
if isinstance(plugins, dict) and key in plugins:
    del plugins[key]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("removed")
else:
    print("absent")
PY
}

# Read a top-level string field ($2) from a JSON file ($1).
json_field() {
    JF_PATH="$1" JF_KEY="$2" python3 -c \
        'import json, os; print(json.load(open(os.environ["JF_PATH"], encoding="utf-8"))[os.environ["JF_KEY"]])'
}

# Copy the plugin tree $1 -> $2, skipping caches/metadata. Uses rsync when
# available and falls back to cp -R + cleanup otherwise.
copy_plugin() {
    local src="$1" dst="$2"
    if [[ "$COPY_TOOL" == "rsync" ]]; then
        rsync -a \
            --exclude='.DS_Store' \
            --exclude='__pycache__' \
            --exclude='*.pyc' \
            --exclude='*.tar.gz' \
            --exclude='._*' \
            "$src/" "$dst/"
    else
        cp -R "$src/." "$dst/"
        find "$dst" -type d -name '__pycache__' -prune -exec rm -rf {} +
        find "$dst" -type f \( -name '.DS_Store' -o -name '*.pyc' -o -name '*.tar.gz' -o -name '._*' \) -delete
    fi
}

# --- Uninstall --------------------------------------------------------
if [[ "${1:-}" == "--uninstall" ]]; then
    echo "Uninstalling $PLUGIN_NAME..."
    echo ""

    if [[ ! -d "$PLUGINS_DIR" ]]; then
        warn "$PLUGINS_DIR does not exist - nothing to uninstall."
        exit 0
    fi
    command -v python3 &>/dev/null || fail "python3 is required to edit Claude Code's JSON registries."

    # 1. Plugin files in the local marketplace
    if [[ -e "$MARKETPLACE_PLUGIN_DIR" ]]; then
        rm -rf "$MARKETPLACE_PLUGIN_DIR"
        info "Removed $MARKETPLACE_PLUGIN_DIR"
    else
        info "Plugin directory not present (already removed)"
    fi

    # 2. Plugin cache
    if [[ -d "$CACHE_DIR" ]]; then
        rm -rf "$CACHE_DIR"
        info "Removed cache $CACHE_DIR"
    fi

    # 3. installed_plugins.json
    if [[ -f "$REGISTRY_JSON" ]]; then
        case "$(registry_remove)" in
            removed) info "Removed $PLUGIN_KEY from installed_plugins.json" ;;
            absent)  info "Not present in installed_plugins.json (already clean)" ;;
            *)       warn "installed_plugins.json left untouched" ;;
        esac
    fi

    # 4. Our entry in marketplace.json (other plugins are preserved)
    MKT_STATUS="absent"
    REMAINING_ENTRIES=0
    if [[ -f "$MARKETPLACE_JSON" ]]; then
        read -r MKT_STATUS REMAINING_ENTRIES <<< "$(marketplace_edit remove)"
        case "$MKT_STATUS" in
            removed) info "Removed entry from marketplace.json ($REMAINING_ENTRIES other plugin(s) remain)" ;;
            absent)  info "Entry not present in marketplace.json ($REMAINING_ENTRIES other plugin(s) listed)" ;;
            *)       warn "marketplace.json could not be parsed; left untouched" ;;
        esac
    fi

    # 5. Drop the local marketplace entirely once nothing else lives in it
    MARKETPLACE_REMOVED=false
    REMAINING_DIRS=$(count_subdirs "$MARKETPLACE_ROOT/plugins")
    if [[ -d "$MARKETPLACE_ROOT" && "$REMAINING_DIRS" -eq 0 && "$REMAINING_ENTRIES" -eq 0 ]]; then
        rm -rf "$MARKETPLACE_ROOT"
        MARKETPLACE_REMOVED=true
        info "Removed empty local marketplace $MARKETPLACE_ROOT"
    fi

    echo ""
    echo -e "${BOLD}To finish, run inside Claude Code:${NC}"
    echo ""
    echo -e "  ${BOLD}/plugin uninstall $PLUGIN_KEY${NC}"
    if [[ "$MARKETPLACE_REMOVED" == true ]]; then
        echo -e "  ${BOLD}/plugin marketplace remove $MARKETPLACE_NAME${NC}"
    fi
    echo ""
    echo "Then restart Claude Code."
    exit 0
fi

# --- Pre-flight checks (read-only; nothing is modified yet) -----------
echo "Installing $PLUGIN_NAME..."
echo ""

[[ -d "$HOME/.claude" ]] || fail "$HOME/.claude not found. Is Claude Code installed?"

if command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1)
    info "Python: $PY_VER"
else
    fail "Python 3 not found. Install Python 3.9+ first."
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    warn "drawio_builder requires Python 3.9+. Detected: $PY_VER"
fi

# Pillow is optional: only add_image() (PNG logo embedding) needs it.
if python3 -c 'import PIL' 2>/dev/null; then
    PIL_VER=$(python3 -c 'from PIL import Image; print(Image.__version__)' 2>/dev/null || echo "installed")
    info "Pillow: $PIL_VER"
else
    warn "Pillow not installed (optional; needed only to embed PNG logos). Trying: python3 -m pip install --user Pillow"
    PIP_LOG=$(mktemp)
    if python3 -m pip install --user --quiet --disable-pip-version-check --retries 2 --timeout 30 Pillow >"$PIP_LOG" 2>&1 \
       && python3 -c 'import PIL' 2>/dev/null; then
        info "Pillow installed"
    else
        warn "Could not install Pillow automatically - continuing without it (PNG logo embedding disabled)."
        if [[ -s "$PIP_LOG" ]]; then
            tail -n 5 "$PIP_LOG" | sed 's/^/          /'
        fi
        echo "          To enable PNG logos later, run ONE of:"
        echo "            python3 -m pip install --user Pillow"
        echo "            python3 -m pip install --user --break-system-packages Pillow   # if pip reports 'externally-managed-environment' (PEP 668)"
        echo "            python3 -m venv .venv && . .venv/bin/activate && pip install Pillow   # or use pipx / a virtualenv"
    fi
    rm -f "$PIP_LOG"
fi

# Copy tool
if command -v rsync &>/dev/null; then
    COPY_TOOL="rsync"
else
    COPY_TOOL="cp"
    warn "rsync not found; falling back to cp -R"
fi

# Source tree sanity
[[ -f "$SOURCE_MANIFEST" ]] || fail "Invalid plugin source: missing .claude-plugin/plugin.json in $SOURCE_DIR"
python3 -m json.tool "$SOURCE_MANIFEST" >/dev/null 2>&1 || fail "Invalid JSON in $SOURCE_MANIFEST"
[[ -f "$SOURCE_DIR/scripts/drawio_builder.py" ]] || fail "Invalid plugin source: missing scripts/drawio_builder.py"
[[ -f "$SOURCE_DIR/scripts/check_overlaps.py" ]]  || fail "Invalid plugin source: missing scripts/check_overlaps.py"

VERSION=$(json_field "$SOURCE_MANIFEST" version) || fail "Could not read version from $SOURCE_MANIFEST"
echo ""
echo "Plugin version: $VERSION"

# --- Copy plugin into the local marketplace ---------------------------
mkdir -p "$PLUGINS_DIR" "$MARKETPLACE_ROOT/.claude-plugin" "$MARKETPLACE_ROOT/plugins"

# Stage next to the target so the final swap is an atomic rename; a failed
# copy never leaves a half-written plugin directory behind.
STAGE_DIR="$MARKETPLACE_ROOT/plugins/.$PLUGIN_NAME.staging.$$"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"
trap 'rm -rf "$STAGE_DIR"' EXIT

copy_plugin "$SOURCE_DIR" "$STAGE_DIR" || fail "Copying plugin files failed"
rm -rf "$MARKETPLACE_PLUGIN_DIR"
mv "$STAGE_DIR" "$MARKETPLACE_PLUGIN_DIR"
trap - EXIT
info "Plugin copied to $MARKETPLACE_PLUGIN_DIR"

# --- Register in marketplace.json (only after the copy succeeded) -----
read -r MKT_STATUS ENTRY_COUNT <<< "$(marketplace_edit upsert)"
[[ "$MKT_STATUS" == "upserted" ]] || fail "Could not update $MARKETPLACE_JSON"
info "Marketplace: $MARKETPLACE_JSON ($ENTRY_COUNT plugin(s) listed)"

# --- Verify -----------------------------------------------------------
echo ""
echo "Verifying..."

CHECKS_PASSED=0
CHECKS_TOTAL=8
pass() { info "$1"; CHECKS_PASSED=$((CHECKS_PASSED + 1)); }

if python3 -m json.tool "$MARKETPLACE_JSON" >/dev/null 2>&1; then
    pass "marketplace.json is valid JSON"
else
    warn "marketplace.json is missing or invalid"
fi

if python3 -m json.tool "$MARKETPLACE_PLUGIN_DIR/.claude-plugin/plugin.json" >/dev/null 2>&1; then
    pass "plugin.json is valid JSON"
else
    warn "plugin.json is missing or invalid"
fi

if [[ -f "$MARKETPLACE_PLUGIN_DIR/commands/drawio-architect.md" ]]; then
    pass "Command: /drawio-architect"
else
    warn "Missing commands/drawio-architect.md"
fi

if [[ -f "$MARKETPLACE_PLUGIN_DIR/skills/oci-drawio-architect/SKILL.md" ]]; then
    pass "Skill: oci-drawio-architect"
else
    warn "Missing skills/oci-drawio-architect/SKILL.md"
fi

if [[ -f "$MARKETPLACE_PLUGIN_DIR/scripts/drawio_builder.py" ]]; then
    pass "Script: drawio_builder.py"
else
    warn "Missing scripts/drawio_builder.py"
fi

if [[ -f "$MARKETPLACE_PLUGIN_DIR/scripts/check_overlaps.py" ]]; then
    pass "Script: check_overlaps.py"
else
    warn "Missing scripts/check_overlaps.py"
fi

ICON_COUNT=$(count_files "$MARKETPLACE_PLUGIN_DIR/icons" '*.svg')
if [[ "$ICON_COUNT" -ge "$MIN_ICONS" ]]; then
    pass "OCI icons: $ICON_COUNT SVGs"
else
    warn "Only $ICON_COUNT bundled icons found (expected >= $MIN_ICONS)"
fi

# Post-install smoke test: build the demo diagram from the installed copy
# and run the mandatory overlap gate on it. Failure warns but never aborts.
SMOKE_LOG=$(mktemp)
if python3 "$MARKETPLACE_PLUGIN_DIR/examples/generate_demo_diagram.py" "$SMOKE_DRAWIO" >"$SMOKE_LOG" 2>&1 \
   && python3 "$MARKETPLACE_PLUGIN_DIR/scripts/check_overlaps.py" "$SMOKE_DRAWIO" >>"$SMOKE_LOG" 2>&1; then
    pass "Smoke test: demo diagram generated and overlap-checked ($SMOKE_DRAWIO)"
else
    warn "Smoke test failed (install continues). Output tail:"
    tail -n 15 "$SMOKE_LOG" | sed 's/^/          /'
fi
rm -f "$SMOKE_LOG"

# --- Summary ----------------------------------------------------------
echo ""
if [[ "$CHECKS_PASSED" -eq "$CHECKS_TOTAL" ]]; then
    echo -e "${GREEN}Files ready! ($CHECKS_PASSED/$CHECKS_TOTAL checks passed)${NC}"
else
    echo -e "${YELLOW}Files ready with warnings ($CHECKS_PASSED/$CHECKS_TOTAL checks passed)${NC}"
fi

echo ""
echo -e "${BOLD}To complete installation, open Claude Code and run these two commands:${NC}"
echo ""
echo -e "  ${BOLD}/plugin marketplace add $MARKETPLACE_ROOT${NC}"
echo -e "  ${BOLD}/plugin install $PLUGIN_KEY${NC}"
echo ""
echo "Then restart Claude Code and run /drawio-architect to generate a diagram."
echo ""
echo "To uninstall later: $MARKETPLACE_PLUGIN_DIR/install.sh --uninstall"
