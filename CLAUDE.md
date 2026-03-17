# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**oci-drawio-architect** is a Claude Code plugin (v1.0.0) that generates production-quality `.drawio` architecture diagrams for Oracle Cloud Infrastructure (OCI) from Terraform configs or free-form descriptions. The plugin is distributed as a self-contained archive (`oci-drawio-architect-v1.0.0.tar.gz`, 424KB).

**Author:** Sergio Farfan

## Repository Contents

This directory is the **distribution root**. The plugin source lives inside the archive:

```
OCI-Diagrams/
├── README.md                          # Installation & usage guide
└── oci-drawio-architect-v1.0.0.tar.gz # Self-contained plugin archive
```

To inspect or modify the plugin, extract the archive:

```bash
tar -xzf oci-drawio-architect-v1.0.0.tar.gz
```

Plugin source layout inside the archive:

```
oci-drawio-architect/
├── .claude-plugin/plugin.json         # Plugin metadata
├── scripts/
│   ├── drawio_builder.py              # Core XML builder class
│   └── detect_settings.py            # OCI settings auto-detection
├── commands/drawio-architect.md       # /drawio-architect command
├── skills/oci-drawio-architect/
│   ├── SKILL.md                       # Full skill workflow
│   └── references/
│       ├── oracle-styles.md           # Container/color style reference
│       ├── icon-catalog.md            # All 220 icon keys
│       └── gotchas.md                 # Common pitfalls
├── icons/                             # 220 OCI SVG icons (15 categories)
├── install.sh                         # Install/uninstall script
└── pack.sh                            # Packaging script
```

## Commands

### Package the plugin

```bash
cd oci-drawio-architect   # after extracting
./pack.sh                 # outputs oci-drawio-architect-v<VERSION>.tar.gz to current dir
./pack.sh /path/to/output # outputs to specified directory
```

Version is auto-read from `.claude-plugin/plugin.json`.

### Install the plugin

```bash
tar -xzf oci-drawio-architect-v1.0.0.tar.gz
./oci-drawio-architect/install.sh
# Then inside a Claude Code session:
# /plugin marketplace add ~/.claude/plugins/marketplaces/local
# /plugin install oci-drawio-architect@local
# Restart Claude Code
```

### Uninstall

```bash
~/.claude/plugins/marketplaces/local/plugins/oci-drawio-architect/install.sh --uninstall
# Then inside Claude Code: /plugin uninstall oci-drawio-architect@local
# Restart Claude Code
```

## Architecture

### `drawio_builder.py` — Core XML Builder

The `DrawioBuilder` class programmatically generates draw.io `.drawio` XML files. It is copied into the user's working directory at diagram generation time (it must be local to the generated script).

Key design decisions:
- **URL-encoding**: SVG data URIs must use `urllib.parse.quote()`, NOT base64. draw.io silently ignores base64-encoded images.
- **viewBox fix**: OCI SVGs have `translate+scale` transforms that push content outside the declared viewBox. `drawio_builder.py` automatically expands the viewBox to fit actual content bounds.
- **Container hierarchy**: `add_group()` returns a cell ID used as the `parent` for child elements. Edge `parent` must be the **common ancestor** of source and target, or edges won't render correctly.
- **Overlap prevention**: Container positions must be computed from actual bounding boxes — hardcoding row Y positions leads to overlapping containers when content height varies. Use named variables (`ROW1_Y`, `ROW2_Y`) derived from computed bottoms.

API summary:

| Method | Purpose |
|--------|---------|
| `add_group(label, x, y, w, h, group_type)` | Container rectangle (region/compartment/vcn/subnet/services/hub) |
| `add_icon(label, icon_key, x, y, parent)` | OCI SVG icon + label (icon 75×95, label 105×45) |
| `add_image(image_path, x, y, w, h)` | PNG logo embedded via SVG wrapper |
| `add_text(label, x, y, w, h)` | Text-only label |
| `add_edge(source, target, label, parent, exit_x, exit_y, entry_x, entry_y, waypoints)` | Connection with explicit ports |
| `add_icons_to_map(dict)` | Extend ICON_MAP with custom icon keys |
| `write(path)` | Output `.drawio` XML file |

Standard icon dimensions: `ICON_W=75`, `ICON_H=95`, label height=45, `LABEL_GAP=2` → total vertical space per icon = **142px**.

### `detect_settings.py` — OCI Environment Probe

Auto-detects project settings in priority order:
1. Terraform files (`provider.tf`, `*.tfvars`, `variables.tf`)
2. OCI CLI (`oci iam tenancy get`, region subscriptions)
3. `~/.oci/config`
4. File system scan for logos

Detected settings are saved to `.claude/oci-drawio-architect.local.md` (per-project, gitignored). Delete that file to re-trigger auto-detection.

### `/drawio-architect` Command — 7-Step Workflow

0. Load settings from `.claude/oci-drawio-architect.local.md` (or auto-detect)
1. Ask what to diagram (Terraform path, VCN name, or description)
2. Parse Terraform configs for VCNs, subnets, services, gateways, DRG topology
3. Plan container layout with grid constants
4. Copy `drawio_builder.py` to working directory
5. Generate `generate_<name>_drawio.py`
6. Execute the script to produce `.drawio`
7. Report file path, size, and viewing instructions

## OCI Color Palette

| Token | Hex | Use |
|-------|-----|-----|
| `region_fill` | `#F5F4F2` | Region/compartment/hub background |
| `region_stroke` | `#9E9892` | Region/compartment borders |
| `vcn_stroke` / `vcn_label` | `#AE562C` | VCN/subnet borders and labels (Oracle orange) |
| `text_primary` | `#312D2A` | General text, service borders (charcoal) |
| `edge_accent` | `#AE562C` | Highlighted edges |
| `edge_purple` | `#7B61FF` | Special connection type |

## Dependencies

- Python 3.8+ (for running generated diagram scripts)
- Pillow (`pip install Pillow`) — required for `add_image()` (PNG logos)
- draw.io desktop — for viewing generated `.drawio` files
- OCI CLI (optional) — for tenancy name auto-detection
