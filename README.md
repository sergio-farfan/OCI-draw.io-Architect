# OCI draw.io Architect — Claude Code Plugin

**A Claude Code plugin that generates production-quality draw.io architecture diagrams for Oracle Cloud Infrastructure (OCI) — from Terraform configurations or free-form descriptions.**

---

**Author:** Sergio Farfan
**Contact:** sergio.farfan@gmail.com
**Version:** 1.0.0

---

Generate production-quality draw.io diagrams for Oracle Cloud Infrastructure architectures using Python, embedded OCI SVG icons, and Oracle template styles.

**Archive:** `oci-drawio-architect-v1.0.0.tar.gz` (424KB, self-contained)

---

## Prerequisites

- **Claude Code** (CLI) installed and working
- **Python 3.8+**
- **draw.io desktop** for viewing generated `.drawio` files

The plugin bundles 220 OCI SVG icons and auto-installs Pillow (Python imaging library) if missing.

---

## Installation

### Step 1 - Extract the archive

```bash
tar -xzf oci-drawio-architect-v1.0.0.tar.gz
```

### Step 2 - Run the installer

```bash
./oci-drawio-architect/install.sh
```

This will:
- Check prerequisites (Python 3, Pillow)
- Install Pillow automatically if missing
- Create a local marketplace at `~/.claude/plugins/marketplaces/local/`
- Copy the plugin files into the marketplace
- Verify all components (5 checks)

### Step 3 - Register in Claude Code

Open Claude Code and run these two commands:

```
/plugin marketplace add ~/.claude/plugins/marketplaces/local
/plugin install oci-drawio-architect@local
```

### Step 4 - Restart Claude Code

Exit Claude Code and reopen it for the plugin to load.

### Step 5 - Verify

Run inside Claude Code:

```
/drawio-architect
```

The command should prompt you for what to diagram.

---

## Uninstall

### Step 1 - Remove files

```bash
~/.claude/plugins/marketplaces/local/plugins/oci-drawio-architect/install.sh --uninstall
```

### Step 2 - Unregister in Claude Code

Open Claude Code and run:

```
/plugin uninstall oci-drawio-architect@local
```

### Step 3 - Restart Claude Code

---

## Usage

### `/drawio-architect` command

Interactive workflow that generates a `.drawio` file:

1. **Auto-detects project settings** on first run (tenancy name, region, logos) from Terraform configs and OCI CLI, saves to `.claude/oci-drawio-architect.local.md`
2. **Asks what to diagram** - provide a Terraform directory path, VCN name, or free-form description
3. **Reads Terraform configs** to extract VCNs, subnets, services, DRG topology
4. **Plans the layout** with container hierarchy and grid calculations
5. **Generates a Python script** using the bundled `DrawioBuilder` class
6. **Runs the script** to produce the `.drawio` file
7. **Reports results** with file path, size, and viewing instructions

### Auto-detected settings

On first run, the plugin detects and saves these settings:

| Setting | Source | Description |
|---------|--------|-------------|
| `tenancy_name` | OCI CLI | Tenancy display name (for diagram title) |
| `region` | Terraform `provider.tf` | OCI region identifier |
| `region_label` | Auto-derived | Human-readable region name (e.g., "Frankfurt") |
| `oci_profile` | Terraform `provider.tf` | OCI CLI profile name |
| `logo_light` | File scan | Logo for light backgrounds |
| `logo_dark` | File scan | Logo for dark backgrounds |
| `compartment` | Manual | Set this yourself for diagram scope |

Settings are stored in `.claude/oci-drawio-architect.local.md` (per-project, gitignored). Edit the file directly to change values. Delete the file and re-run `/drawio-architect` to re-detect.

### Skill auto-activation

The plugin also activates automatically when you mention in conversation:
- "draw.io OCI"
- "diagram this architecture"
- "drawio with OCI icons"

### Diagram types

| Type | Best For | Typical Page Size |
|------|----------|-------------------|
| Single-VCN Topology | Application stacks | 1600 x 1100 |
| Hub-and-Spoke Network | Network overview with DRG | 2400 x 1400 |
| Service Inventory | Compartment-level resource view | 1800 x 1200 |
| Multi-VCN Overview | VCN interconnections via DRG | 2400 x 1600 |

### Viewing diagrams

Open the generated `.drawio` file in draw.io desktop. If fonts look wrong, close and reopen the file (draw.io caches renders).

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `/drawio-architect` not found | Restart Claude Code after plugin install |
| `ModuleNotFoundError: PIL` | Run `pip install Pillow` |
| Icons appear blank in diagram | Plugin bundles icons - check `icons/` dir has SVG files |
| Settings not detected | Ensure `provider.tf` exists in your Terraform directory |
| Want to re-detect settings | Delete `.claude/oci-drawio-architect.local.md` and re-run |
| Tenancy name missing | Install and configure OCI CLI (`brew install oci-cli`) |
