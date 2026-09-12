#!/usr/bin/env bash
# ----------------------------------------------------------------------
# pack.sh - Package the oci-drawio-architect plugin for distribution
#
# Creates a self-contained, reproducible .tar.gz archive containing:
#   - Plugin manifest, commands, skills, scripts, references, examples
#   - Bundled OCI SVG icons plus icons/NOTICE, and the plugin LICENSE
#   - The install.sh installer script
#
# Excluded from the archive:
#   *.tar.gz, logos/ (optional private logos), __pycache__, *.pyc,
#   .DS_Store, macOS AppleDouble (._*) files, tests/fixtures/**/*.drawio
#
# Usage:
#   ./pack.sh                    # outputs to current directory
#   ./pack.sh /path/to/output    # outputs to specified directory
#
# Reproducibility:
#   - File order is fixed (sorted list fed to tar), owner/group are 0/0,
#     gzip runs with -n (no name/timestamp in the gzip header).
#   - With GNU tar the entry mtimes are pinned to SOURCE_DATE_EPOCH
#     (default: last git commit time, else "now"). bsdtar has no --mtime,
#     so entry mtimes follow the working tree there.
#   - COPYFILE_DISABLE=1 stops macOS from injecting ._* metadata files.
#
# Output: oci-drawio-architect-v<VERSION>.tar.gz
# ----------------------------------------------------------------------
set -euo pipefail

export COPYFILE_DISABLE=1   # macOS: never archive ._* AppleDouble metadata

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT_DIR="$(dirname "$PLUGIN_DIR")"
BASENAME="$(basename "$PLUGIN_DIR")"

fail() { echo "[FAIL]  $1" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || fail "python3 is required (reads the version from plugin.json)"
command -v gzip    >/dev/null 2>&1 || fail "gzip is required"

VERSION=$(PJ="$PLUGIN_DIR/.claude-plugin/plugin.json" python3 -c \
    'import json, os; print(json.load(open(os.environ["PJ"], encoding="utf-8"))["version"])') \
    || fail "Could not read version from $PLUGIN_DIR/.claude-plugin/plugin.json"
[[ -n "$VERSION" ]] || fail "Empty version in plugin.json"

# Files that must ship in every archive.
REQUIRED_FILES=(
    LICENSE
    icons/NOTICE
    install.sh
    .claude-plugin/plugin.json
    scripts/drawio_builder.py
    scripts/check_overlaps.py
)
for required in "${REQUIRED_FILES[@]}"; do
    [[ -e "$PLUGIN_DIR/$required" ]] || fail "Missing required file: $PLUGIN_DIR/$required"
done

OUT_DIR="${1:-.}"
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
ARCHIVE_NAME="oci-drawio-architect-v${VERSION}.tar.gz"
ARCHIVE="$OUT_DIR/$ARCHIVE_NAME"

echo "Packing oci-drawio-architect v${VERSION}..."

# --- Detect tar flavour and which reproducibility flags it supports ----
TAR_FLAVOR="other"
if tar --version 2>/dev/null | grep -qi 'gnu tar'; then
    TAR_FLAVOR="gnu"
elif tar --version 2>/dev/null | grep -qi 'bsdtar'; then
    TAR_FLAVOR="bsd"
fi

# Probe a flag set by running tar against an empty file list.
tar_supports() {
    tar "$@" -cf /dev/null -T /dev/null >/dev/null 2>&1
}

TAR_FLAGS=()
NO_RECURSE_FLAG="--no-recursion"
case "$TAR_FLAVOR" in
    gnu)
        SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "$PLUGIN_DIR" log -1 --format=%ct 2>/dev/null || date +%s)}"
        tar_supports --owner=0 --group=0 --numeric-owner && TAR_FLAGS+=(--owner=0 --group=0 --numeric-owner)
        tar_supports --sort=name                         && TAR_FLAGS+=(--sort=name)
        tar_supports --mtime="@${SOURCE_DATE_EPOCH}"     && TAR_FLAGS+=(--mtime="@${SOURCE_DATE_EPOCH}")
        ;;
    bsd)
        NO_RECURSE_FLAG="-n"
        tar_supports --uid 0 --gid 0 && TAR_FLAGS+=(--uid 0 --gid 0)
        ;;
    *)
        echo "[WARN]  Unrecognised tar flavour; packing without reproducibility flags" >&2
        tar_supports --no-recursion || NO_RECURSE_FLAG="-n"
        ;;
esac

# --- Build the (sorted) file list -------------------------------------
LIST_FILE="$(mktemp)"
trap 'rm -f "$LIST_FILE"' EXIT

(
    cd "$PARENT_DIR"
    find "$BASENAME" \
        \( -type d \( -name '__pycache__' -o -name '.git' -o -path "$BASENAME/logos" \) \) -prune -o \
        \( -type f -o -type d \) \
        ! -name '*.tar.gz' \
        ! -name '*.pyc' \
        ! -name '.DS_Store' \
        ! -name '._*' \
        ! \( -path "$BASENAME/tests/fixtures/*" -name '*.drawio' \) \
        -print
) | LC_ALL=C sort > "$LIST_FILE"

[[ -s "$LIST_FILE" ]] || fail "No files selected for packing"

# Writing into the plugin dir is tolerated only because *.tar.gz is
# excluded; refuse outright if the output would end up inside its own archive.
case "$OUT_DIR/" in
    "$PLUGIN_DIR"/*)
        REL_ARCHIVE="$BASENAME${OUT_DIR#"$PLUGIN_DIR"}/$ARCHIVE_NAME"
        if grep -qxF "$REL_ARCHIVE" "$LIST_FILE"; then
            fail "Refusing to pack: $ARCHIVE lies inside $PLUGIN_DIR and is not excluded"
        fi
        ;;
esac

# --- Create the archive -----------------------------------------------
tar -cf - -C "$PARENT_DIR" "${TAR_FLAGS[@]}" "$NO_RECURSE_FLAG" -T "$LIST_FILE" \
    | gzip -n -9 > "$ARCHIVE"

# --- Post-checks on the produced archive ------------------------------
CONTENTS="$(tar -tzf "$ARCHIVE")"
for required in LICENSE icons/NOTICE install.sh .claude-plugin/plugin.json; do
    grep -qxF "$BASENAME/$required" <<< "$CONTENTS" || fail "Archive is missing $BASENAME/$required"
done
if grep -q '/\._' <<< "$CONTENTS";               then fail "Archive contains AppleDouble ._* files"; fi
if grep -q '\.tar\.gz$' <<< "$CONTENTS";         then fail "Archive contains a nested *.tar.gz"; fi
if grep -q '__pycache__' <<< "$CONTENTS";        then fail "Archive contains __pycache__"; fi
if grep -q "^$BASENAME/logos/" <<< "$CONTENTS";  then fail "Archive contains logos/"; fi

SIZE=$(du -h "$ARCHIVE" | cut -f1 | tr -d '[:space:]')
FILE_COUNT=$(wc -l <<< "$CONTENTS" | tr -d '[:space:]')
ICON_COUNT=$(grep -c "^$BASENAME/icons/.*\.svg$" <<< "$CONTENTS" || true)
SHA256=""
if command -v shasum >/dev/null 2>&1; then
    SHA256=$(shasum -a 256 "$ARCHIVE" | cut -d' ' -f1)
elif command -v sha256sum >/dev/null 2>&1; then
    SHA256=$(sha256sum "$ARCHIVE" | cut -d' ' -f1)
fi

echo ""
echo "Created: $ARCHIVE"
echo "Size:    $SIZE"
echo "Entries: $FILE_COUNT ($ICON_COUNT SVG icons)"
echo "Tar:     $TAR_FLAVOR ${TAR_FLAGS[*]:-}"
[[ -n "$SHA256" ]] && echo "SHA256:  $SHA256"

cat <<INSTRUCTIONS

================================================================
  INSTALLATION INSTRUCTIONS
================================================================

Prerequisites:
  - Claude Code (CLI) installed
  - Python 3.9+
  - draw.io desktop (for viewing diagrams)
  - Pillow (optional, only for embedding PNG logos)

Step 1 — Extract the archive:

    tar -xzf ${ARCHIVE_NAME}

Step 2 — Run the installer:

    ./oci-drawio-architect/install.sh

    This will:
    - Check prerequisites (tries to install Pillow if missing; optional)
    - Create/update the local marketplace at ~/.claude/plugins/marketplaces/local/
    - Copy the plugin files into the marketplace
    - Run a post-install smoke test (demo diagram + overlap check)

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
    /plugin marketplace remove local        (only if the installer reported the marketplace is now empty)

Step 3 — Restart Claude Code

================================================================
INSTRUCTIONS
