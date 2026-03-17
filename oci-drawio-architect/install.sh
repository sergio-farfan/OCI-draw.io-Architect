#!/usr/bin/env bash
# ----------------------------------------------------------------------
# install.sh - Install the oci-drawio-architect plugin for Claude Code
#
# What it does:
#   1. Checks prerequisites (Claude Code, Python 3, Pillow)
#   2. Creates a local marketplace with marketplace.json
#   3. Copies plugin to marketplace plugins/ directory
#   4. Prints commands for the user to run inside Claude Code
#
# Usage:
#   ./install.sh              # install for current user
#   ./install.sh --uninstall  # remove the plugin
#
# After running this script, open Claude Code and run:
#   /plugin marketplace add ~/.claude/plugins/marketplaces/local
#   /plugin install oci-drawio-architect@local
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

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $1"; exit 1; }

# --- Uninstall --------------------------------------------------------
if [[ "${1:-}" == "--uninstall" ]]; then
    echo "Uninstalling $PLUGIN_NAME..."

    # Remove plugin from marketplace
    if [[ -e "$MARKETPLACE_PLUGIN_DIR" ]]; then
        rm -rf "$MARKETPLACE_PLUGIN_DIR"
        info "Removed from local marketplace"
    fi

    # Remove cache
    CACHE_DIR="$PLUGINS_DIR/cache/$MARKETPLACE_NAME/$PLUGIN_NAME"
    if [[ -d "$CACHE_DIR" ]]; then
        rm -rf "$CACHE_DIR"
        info "Removed cache"
    fi

    # Remove from installed_plugins.json
    REGISTRY="$PLUGINS_DIR/installed_plugins.json"
    if [[ -f "$REGISTRY" ]]; then
        python3 -c "
import json, pathlib
reg = pathlib.Path('$REGISTRY')
data = json.loads(reg.read_text())
if '$PLUGIN_KEY' in data.get('plugins', {}):
    del data['plugins']['$PLUGIN_KEY']
    reg.write_text(json.dumps(data, indent=2) + '\n')
    print('Removed from registry')
else:
    print('Not found in registry (already clean)')
"
        info "Registry updated"
    fi

    # Clean up marketplace if empty
    REMAINING=$(find "$MARKETPLACE_ROOT/plugins" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | xargs)
    if [[ "$REMAINING" -eq 0 ]] && [[ -d "$MARKETPLACE_ROOT" ]]; then
        rm -rf "$MARKETPLACE_ROOT"
        info "Removed empty local marketplace"
    fi

    echo ""
    info "Uninstalled. Restart Claude Code to complete."
    exit 0
fi

# --- Pre-flight checks ------------------------------------------------
echo "Installing $PLUGIN_NAME..."
echo ""

# Check Claude Code directory exists
if [[ ! -d "$HOME/.claude" ]]; then
    fail "~/.claude not found. Is Claude Code installed?"
fi

# Ensure plugins directory exists
mkdir -p "$PLUGINS_DIR"

# Check Python 3
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1)
    info "Python: $PY_VER"
else
    fail "Python 3 not found. Install Python 3.8+ first."
fi

# Check Pillow
if python3 -c "import PIL" 2>/dev/null; then
    PIL_VER=$(python3 -c "from PIL import Image; print(Image.__version__)" 2>/dev/null || echo "installed")
    info "Pillow: $PIL_VER"
else
    warn "Pillow not installed. Installing now..."
    pip install Pillow --quiet && info "Pillow installed" || fail "Failed to install Pillow. Run: pip install Pillow"
fi

# Check source has the expected structure
if [[ ! -f "$SOURCE_DIR/.claude-plugin/plugin.json" ]]; then
    fail "Invalid plugin source: missing .claude-plugin/plugin.json in $SOURCE_DIR"
fi

# --- Read version from manifest ---------------------------------------
VERSION=$(python3 -c "
import json, pathlib
p = pathlib.Path('$SOURCE_DIR/.claude-plugin/plugin.json')
print(json.loads(p.read_text())['version'])
")
echo ""
echo "Plugin version: $VERSION"

# --- Create local marketplace ----------------------------------------
mkdir -p "$MARKETPLACE_ROOT/.claude-plugin"
mkdir -p "$MARKETPLACE_ROOT/plugins"

# Write marketplace.json
cat > "$MARKETPLACE_JSON" <<MKJSON
{
  "\$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
  "name": "$MARKETPLACE_NAME",
  "description": "Local custom plugins",
  "owner": {
    "name": "$(whoami)"
  },
  "plugins": [
MKJSON

# Build plugins array from all plugins in the marketplace
FIRST=true
for PDIR in "$MARKETPLACE_ROOT/plugins"/*/; do
    PNAME=$(basename "$PDIR")
    PJSON="$PDIR/.claude-plugin/plugin.json"
    if [[ -f "$PJSON" ]] && [[ "$PNAME" != "$PLUGIN_NAME" ]]; then
        PDESC=$(python3 -c "import json; print(json.load(open('$PJSON')).get('description',''))" 2>/dev/null || echo "")
        PVER=$(python3 -c "import json; print(json.load(open('$PJSON')).get('version','1.0.0'))" 2>/dev/null || echo "1.0.0")
        if [[ "$FIRST" == true ]]; then FIRST=false; else echo "," >> "$MARKETPLACE_JSON"; fi
        cat >> "$MARKETPLACE_JSON" <<ENTRY
    {
      "name": "$PNAME",
      "description": "$PDESC",
      "version": "$PVER",
      "source": "./plugins/$PNAME"
    }
ENTRY
    fi
done

# Add our plugin entry
DESC=$(python3 -c "import json; print(json.load(open('$SOURCE_DIR/.claude-plugin/plugin.json')).get('description',''))")
if [[ "$FIRST" == true ]]; then FIRST=false; else echo "," >> "$MARKETPLACE_JSON"; fi
cat >> "$MARKETPLACE_JSON" <<ENTRY
    {
      "name": "$PLUGIN_NAME",
      "description": "$DESC",
      "version": "$VERSION",
      "source": "./plugins/$PLUGIN_NAME"
    }
ENTRY

cat >> "$MARKETPLACE_JSON" <<MKEND
  ]
}
MKEND

info "Marketplace: $MARKETPLACE_JSON"

# --- Copy plugin into marketplace ------------------------------------
if [[ -e "$MARKETPLACE_PLUGIN_DIR" ]]; then
    rm -rf "$MARKETPLACE_PLUGIN_DIR"
fi
mkdir -p "$MARKETPLACE_PLUGIN_DIR"
rsync -a \
    --exclude='.DS_Store' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    "$SOURCE_DIR/" "$MARKETPLACE_PLUGIN_DIR/"

info "Plugin copied to $MARKETPLACE_PLUGIN_DIR"

# --- Verify -----------------------------------------------------------
echo ""
echo "Verifying..."

CHECKS_PASSED=0
CHECKS_TOTAL=5

[[ -f "$MARKETPLACE_JSON" ]] && { info "marketplace.json"; CHECKS_PASSED=$((CHECKS_PASSED + 1)); } || warn "Missing marketplace.json"
[[ -f "$MARKETPLACE_PLUGIN_DIR/.claude-plugin/plugin.json" ]] && { info "plugin.json"; CHECKS_PASSED=$((CHECKS_PASSED + 1)); } || warn "Missing plugin.json"
[[ -f "$MARKETPLACE_PLUGIN_DIR/commands/drawio-architect.md" ]] && { info "Command: /drawio-architect"; CHECKS_PASSED=$((CHECKS_PASSED + 1)); } || warn "Missing command"
[[ -f "$MARKETPLACE_PLUGIN_DIR/skills/oci-drawio-architect/SKILL.md" ]] && { info "Skill: oci-drawio-architect"; CHECKS_PASSED=$((CHECKS_PASSED + 1)); } || warn "Missing skill"

ICON_COUNT=$(find "$MARKETPLACE_PLUGIN_DIR/icons" -name "*.svg" 2>/dev/null | wc -l | xargs)
if [[ "$ICON_COUNT" -gt 0 ]]; then
    info "OCI icons: $ICON_COUNT SVGs"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    warn "No bundled icons found"
fi

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
echo -e "  ${BOLD}/plugin marketplace add ~/.claude/plugins/marketplaces/local${NC}"
echo -e "  ${BOLD}/plugin install oci-drawio-architect@local${NC}"
echo ""
echo "Then run /drawio-architect to generate a diagram."
echo ""
echo "To uninstall later: $(basename "$0") --uninstall"
