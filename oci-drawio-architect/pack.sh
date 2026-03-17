#!/usr/bin/env bash
# ----------------------------------------------------------------------
# pack.sh - Package the oci-drawio-architect plugin for distribution
#
# Creates a self-contained .tar.gz archive that includes:
#   - Plugin manifest, commands, skills, scripts, references
#   - Bundled OCI SVG icons (220 files, 14 categories)
#   - The install.sh installer script
#
# Usage:
#   ./pack.sh                    # outputs to current directory
#   ./pack.sh /path/to/output    # outputs to specified directory
#
# Output: oci-drawio-architect-v<VERSION>.tar.gz
# ----------------------------------------------------------------------
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION=$(python3 -c "
import json, pathlib
p = pathlib.Path('${PLUGIN_DIR}/.claude-plugin/plugin.json')
print(json.loads(p.read_text())['version'])
")

OUT_DIR="${1:-.}"
mkdir -p "$OUT_DIR"
ARCHIVE="$OUT_DIR/oci-drawio-architect-v${VERSION}.tar.gz"

echo "Packing oci-drawio-architect v${VERSION}..."

# Build archive from plugin directory, preserving structure
tar -czf "$ARCHIVE" \
    -C "$(dirname "$PLUGIN_DIR")" \
    --exclude='.DS_Store' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    "$(basename "$PLUGIN_DIR")"

SIZE=$(du -h "$ARCHIVE" | cut -f1 | xargs)
FILE_COUNT=$(tar -tzf "$ARCHIVE" | wc -l | xargs)

echo ""
echo "Created: $ARCHIVE"
echo "Size:    $SIZE"
echo "Files:   $FILE_COUNT"

cat <<'INSTRUCTIONS'

================================================================
  INSTALLATION INSTRUCTIONS
================================================================

Prerequisites:
  - Claude Code (CLI) installed
  - Python 3.8+
  - draw.io desktop (for viewing diagrams)

Step 1 — Extract the archive:

    tar -xzf oci-drawio-architect-v1.0.0.tar.gz

Step 2 — Run the installer:

    ./oci-drawio-architect/install.sh

    This will:
    - Check prerequisites (installs Pillow if missing)
    - Create a local marketplace at ~/.claude/plugins/marketplaces/local/
    - Copy the plugin files into the marketplace

Step 3 — Register in Claude Code (run INSIDE a Claude Code session):

    /plugin marketplace add ~/.claude/plugins/marketplaces/local
    /plugin install oci-drawio-architect@local

Step 4 — Restart Claude Code (exit and reopen)

Step 5 — Test:

    /drawio-architect

================================================================
  UNINSTALL INSTRUCTIONS
================================================================

Step 1 — Remove files:

    ~/.claude/plugins/marketplaces/local/plugins/oci-drawio-architect/install.sh --uninstall

    Or if you still have the extracted archive:

    ./oci-drawio-architect/install.sh --uninstall

Step 2 — Inside Claude Code:

    /plugin uninstall oci-drawio-architect@local

Step 3 — Restart Claude Code

================================================================
INSTRUCTIONS
