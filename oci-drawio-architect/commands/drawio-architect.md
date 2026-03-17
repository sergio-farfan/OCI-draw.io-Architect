---
name: drawio-architect
description: Generate an OCI architecture draw.io diagram from Terraform configs or description
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent, AskUserQuestion
---

# /drawio-architect - OCI Architecture Diagram Generator

Generate a production-quality `.drawio` diagram for an OCI architecture using the DrawioBuilder Python class, embedded OCI SVG icons, and Oracle template styles.

## Workflow

### Step 0: Load Project Settings

Check for settings file at `.claude/oci-drawio-architect.local.md`.

**If the file exists:** Read it and parse the YAML frontmatter to get:
- `tenancy_name` - Tenancy display name (e.g., "mytenancy")
- `region` - OCI region identifier (e.g., "eu-frankfurt-1")
- `region_label` - Display name for titles (e.g., "Frankfurt")
- `compartment` - Default compartment name
- `logo_light` - Logo path for light backgrounds
- `logo_dark` - Logo path for dark backgrounds
- `oci_profile` - OCI CLI profile
- `terraform_dir` - Default Terraform directory

Use these values throughout the diagram (title, region container label, logo placement).

**If the file does NOT exist:** Run auto-detection:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/detect_settings.py" [terraform_dir_if_known]
```

This probes (in order):
1. **Terraform files** - `provider.tf` for region/profile, `*.tfvars` for tenancy_ocid
2. **OCI CLI** - `oci iam tenancy get` for tenancy name
3. **~/.oci/config** - fallback for tenancy OCID and region
4. **Logo files** - scans `logos/`, `assets/logos/`, `assets/images/`

Show the user what was detected and ask them to confirm or adjust. Then write the settings file:

```markdown
---
tenancy_name: "mytenancy"
tenancy_ocid: "ocid1.tenancy.oc1..aaaa..."
region: "eu-frankfurt-1"
region_label: "Frankfurt"
oci_profile: "DEFAULT"
compartment: ""
logo_light: "logos/company_logo_dark.png"
logo_dark: "logos/company_logo_light.png"
terraform_dir: "terraform/environments/frankfurt"
---

# OCI draw.io Architect Settings

Auto-detected on YYYY-MM-DD. Edit values above as needed.
Restart Claude Code after changes.
```

If auto-detection finds nothing, use AskUserQuestion to gather:
1. Tenancy name (for diagram title)
2. Region (for region container label)
3. Logo file path (optional)
4. Default compartment (optional)

### Step 1: Gather Requirements

Ask the user what to diagram. Accept one of:
- **Terraform path** (e.g., `terraform/environments/prod/`) - parse `.tf` files to extract topology
- **VCN name** (e.g., "prod-vcn") - look up in `VCN.auto.tfvars` and related service files
- **Free-form description** (e.g., "hub-and-spoke with firewall") - build from description

Use AskUserQuestion if the user didn't specify in the command invocation:
```
What OCI architecture would you like to diagram?

Options:
1. Provide a Terraform directory path (I'll parse the configs)
2. Name a VCN (I'll look it up in .auto.tfvars)
3. Describe the architecture in plain text
```

### Step 2: Read Terraform Configs

Based on the input, read relevant files to extract:
- **VCNs**: Name, CIDR, compartment from `VCN.auto.tfvars`
- **Subnets**: Name, CIDR, public/private, route targets
- **Services**: Compute, databases, LBs, functions, OKE from service `.tf` files
- **DRG**: Attachments, VPNs, FastConnect from `DRG.auto.tfvars`
- **NSGs/Security**: From `networking.tf` or port CSV files
- **Gateways**: IGW, NAT, SGW from VCN config

Build a mental model of the architecture:
- Container hierarchy (Region > VCN > Subnets > Services)
- Service-to-subnet placement
- Connection topology (LB->App, App->DB, DRG attachments)

### Step 3: Plan the Layout

Design the container hierarchy and grid constants before writing code.

**Container hierarchy pattern:**
```
Region ({region_label} - {region})     <-- from settings
  +-- Hub (left side, narrow) - for DRG, Firewall, VPN/CPE
  +-- VCN (right side, wide)
        +-- Subnet rows (each with service icons)
        +-- Services panel (cross-cutting: Vault, DevOps, Logging)
        +-- Gateways row (bottom: IGW, NAT, SGW)
```

**Title block** (from settings):
```python
# Title: "<b>{tenancy_name} - {diagram_subject}</b><br/><i>{region_label} ({region})</i>"
# Logo: d.add_image(settings["logo_light"], x=PAGE_W-170, y=8, w=148, h=39)
```

**Mandatory overlap prevention:**
1. Compute bounding boxes for every sibling container
2. Derive each row's y-position from the tallest sibling above + gap
3. Use named variables (ROW1_Y, ROW2_Y, GW_Y), never magic numbers
4. Account for icon label overflow: each icon uses ICON_H(95) + LABEL_GAP(2) + label_h(45) = 142px vertical

**Grid constants** (adjust per diagram):
```python
R1 = 50        # first icon row y (below container title)
R2 = 210       # second icon row y
COL = 130      # column gap between icons
SN_H = 380     # subnet height for 2 rows of icons
ICON_W = 75    # icon cell width
ICON_H = 95    # icon cell height
GAP = 20       # gap between containers
```

**Page dimensions:** Calculate from content. Typical: 1600x1100 for single-VCN, 2400x1400 for multi-VCN.

### Step 4: Copy DrawioBuilder

Copy the builder class from the plugin's scripts directory into the working directory:

```bash
cp "${CLAUDE_PLUGIN_ROOT}/scripts/drawio_builder.py" ./drawio_builder.py
```

If the file already exists in the working directory, skip the copy.

### Step 5: Generate the Diagram Script

Create a `generate_<name>_drawio.py` script that:

1. Imports `DrawioBuilder`, `add_icons_to_map`, `COLORS` from `drawio_builder`
2. Calls `add_icons_to_map()` for any icons not in the default ICON_MAP (check `${CLAUDE_PLUGIN_ROOT}/skills/oci-drawio-architect/references/icon-catalog.md` for available icons)
3. Defines a `build_diagram()` function that:
   - Creates a `DrawioBuilder` with appropriate page dimensions
   - Adds title text using `tenancy_name`, `region_label`, and `region` from settings
   - Adds logo via `d.add_image()` using `logo_light` path from settings (if set)
   - Builds the container hierarchy (Region > VCN > Subnets)
   - Places service icons inside their containers
   - Routes edges with explicit waypoints for cross-container connections
   - Writes the `.drawio` file

**Follow these rules from the skill:**
- URL-encode SVGs, never base64
- Use `container=1` on all group styles (handled by DrawioBuilder)
- Cross-container edges must use a common ancestor as parent
- Use `_next_id()` for all cell IDs (handled by DrawioBuilder)
- Derive row positions from computed bottoms, never hardcode

**Reference files for style details:**
- Oracle styles: `${CLAUDE_PLUGIN_ROOT}/skills/oci-drawio-architect/references/oracle-styles.md`
- Icon catalog: `${CLAUDE_PLUGIN_ROOT}/skills/oci-drawio-architect/references/icon-catalog.md`
- Gotchas: `${CLAUDE_PLUGIN_ROOT}/skills/oci-drawio-architect/references/gotchas.md`
- Full skill guide: `${CLAUDE_PLUGIN_ROOT}/skills/oci-drawio-architect/SKILL.md`

### Step 6: Run the Script

Execute the generated script:

```bash
python3 generate_<name>_drawio.py
```

Verify:
- Script runs without errors
- Output `.drawio` file exists and has reasonable size (typically 10-100KB)
- Report the output path and file size to the user

### Step 7: Report Results

Tell the user:
- Output file path
- File size
- What's in the diagram (VCNs, subnets, services, connections)
- Settings used (tenancy, region, logo)
- Suggest opening in draw.io desktop to verify rendering
- Note: close and reopen if fonts look wrong (draw.io caches renders)

## Diagram Types

This command can produce several diagram types:

### Single-VCN Topology
Best for application stacks (e.g., a single app VCN). Shows one VCN with all subnets, services, and connections.

### Hub-and-Spoke Network
Shows the hub VCN with DRG, Firewall, and spoke VCN connections.

### Service Inventory
Shows compartments with deployed services (compute, databases, etc.) without network details.

### Multi-VCN Overview
Shows multiple VCNs with their interconnections via DRG.

## Settings Reference

Settings are stored in `.claude/oci-drawio-architect.local.md` (per-project, gitignored).

| Setting | Source | Description |
|---------|--------|-------------|
| `tenancy_name` | OCI CLI / manual | Tenancy display name for title |
| `tenancy_ocid` | Terraform / OCI config | Tenancy OCID (used for CLI queries) |
| `region` | Terraform provider.tf | OCI region identifier |
| `region_label` | Auto-derived / manual | Human-readable region name |
| `oci_profile` | Terraform provider.tf | OCI CLI profile name |
| `compartment` | Manual | Default compartment for diagrams |
| `logo_light` | Auto-detected / manual | Logo path for light backgrounds |
| `logo_dark` | Auto-detected / manual | Logo path for dark backgrounds |
| `terraform_dir` | Auto-detected / manual | Default Terraform directory |

**Auto-detection script:** `${CLAUDE_PLUGIN_ROOT}/scripts/detect_settings.py`

To re-detect settings, delete `.claude/oci-drawio-architect.local.md` and run `/drawio-architect` again.

## Prerequisites

- Python 3.8+
- `Pillow` package (for PNG logo embedding): `pip install Pillow`
- OCI SVG icons are bundled in `${CLAUDE_PLUGIN_ROOT}/icons/` (no external dependency needed; override with `OCI_SVG_DIR` env var)
- draw.io desktop for viewing generated diagrams
- (Optional) OCI CLI configured for auto-detection of tenancy name
