# OCI draw.io Architect Plugin

Generate production-quality draw.io diagrams for Oracle Cloud Infrastructure architectures using Python, embedded SVG icons, and Oracle template styles.

## Installation

```bash
tar -xzf oci-drawio-architect-v1.0.0.tar.gz
./oci-drawio-architect/install.sh
```

Or manually place this directory at `~/.claude/plugins/oci-drawio-architect/`.

## Usage

### Slash Command

```
/drawio-architect
```

Interactive workflow that:
1. Auto-detects project settings (tenancy, region, logos) or loads from config
2. Asks what to diagram (Terraform path, VCN name, or description)
3. Reads Terraform configs to extract topology
4. Plans container hierarchy and grid layout
5. Generates a Python script using `DrawioBuilder`
6. Runs the script to produce a `.drawio` file

### Skill (Auto-Activated)

The `oci-drawio-architect` skill activates automatically when you mention:
- "draw.io OCI"
- "diagram this architecture"
- "drawio with OCI icons"

## Project Settings

On first run, `/drawio-architect` auto-detects settings from your Terraform configs and OCI CLI, then saves them to `.claude/oci-drawio-architect.local.md` (per-project, gitignored).

### Auto-Detection Sources

| Setting | Terraform | OCI CLI | OCI Config |
|---------|-----------|---------|------------|
| `region` | `provider.tf` | - | `~/.oci/config` |
| `oci_profile` | `provider.tf` | - | - |
| `tenancy_name` | - | `oci iam tenancy get` | - |
| `tenancy_ocid` | `*.tfvars` | - | `~/.oci/config` |
| `logo_light/dark` | File scan | - | - |

### Settings File Format

`.claude/oci-drawio-architect.local.md`:
```markdown
---
tenancy_name: "mytenancy"
tenancy_ocid: "ocid1.tenancy.oc1..aaaa..."
region: "eu-frankfurt-1"
region_label: "Frankfurt"
oci_profile: "DEFAULT"
compartment: "my-compartment"
logo_light: "logos/company_logo_dark.png"
logo_dark: "logos/company_logo_light.png"
terraform_dir: "terraform/environments/frankfurt"
---

# OCI draw.io Architect Settings
Auto-detected. Edit values above as needed.
```

To re-detect: delete the file and run `/drawio-architect` again.

### Manual Override

You can edit any field in the settings file. Common manual settings:
- `compartment` - not auto-detected, set for diagram scope
- `region_label` - override the display name
- `logo_light` / `logo_dark` - point to your organization's logos

## Diagram Types

| Type | Best For | Typical Size |
|------|----------|-------------|
| Single-VCN Topology | Application stacks (single VCN) | 1600x1100 |
| Hub-and-Spoke Network | Network overview with DRG | 2400x1400 |
| Service Inventory | Compartment-level resource view | 1800x1200 |
| Multi-VCN Overview | VCN interconnections via DRG | 2400x1600 |

## Prerequisites

- **Python 3.8+**
- **Pillow**: `pip install Pillow` (for PNG logo embedding)
- **draw.io desktop**: For viewing generated diagrams
- (Optional) **OCI CLI**: For auto-detecting tenancy name

OCI SVG icons (220 icons, 1.7MB) are bundled in `icons/`. No external icon dependency needed.

## Plugin Structure

```
oci-drawio-architect/
├── .claude-plugin/
│   └── plugin.json              # Plugin manifest
├── commands/
│   └── drawio-architect.md      # /drawio-architect slash command
├── skills/
│   └── oci-drawio-architect/
│       ├── SKILL.md             # Auto-activated skill
│       └── references/
│           ├── oracle-styles.md # Oracle template color/style reference
│           ├── icon-catalog.md  # ~160 OCI SVG icons across 14 categories
│           └── gotchas.md       # 11 battle-tested workarounds
├── scripts/
│   ├── drawio_builder.py        # DrawioBuilder Python class
│   └── detect_settings.py       # Auto-detection from Terraform/OCI CLI
├── icons/                        # Bundled OCI SVG icons (220 files, 14 categories)
├── install.sh                    # Installer script
├── pack.sh                       # Packaging script
└── README.md
```

## Phase 2 (Planned)

Future agents for autonomous Terraform-to-diagram generation:
- `diagram-planner` - Extracts VCN topology from `.auto.tfvars`
- `architecture-mapper` - Maps services to VCNs/subnets from `.tf` files
