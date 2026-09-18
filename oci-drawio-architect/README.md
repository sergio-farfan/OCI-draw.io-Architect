# OCI draw.io Architect Plugin

Generate production-quality draw.io diagrams for Oracle Cloud Infrastructure architectures using Python, embedded SVG icons, and Oracle template styles.

## What's new in 1.3.0

Topology-aware placement: the layout recipe now follows how the team's diagram guidelines and Oracle's own reference architectures draw connectivity infrastructure (full list in [CHANGELOG.md](CHANGELOG.md)):

- **The DRG is a region-level element.** It sits between the on-premises panel and the VCN columns with one rounded attachment box per attachment beside it (VCN, IPSec, FastConnect, remote peering); `drg_style` `icon` (default) or `box` groups the boxes under a dashed `DRG: <name>` frame.
- **Gateways sit on the VCN border**, not in a bottom row: IGW and NAT straddle the bottom, the Service Gateway the right border facing the services panel, LPGs the border facing their peer VCN.
- **Regional services get their own Oracle Services Network panel**, right of the VCN columns, fed by the Service Gateway; VCN-resident services without a subnet stay in the VCN.
- **Four connector kinds and a legend**: `data` (solid, open arrow), `control` (dashed, open arrow), `association` (dotted, no arrowhead) and `attachment` (thin solid, no arrowhead), plus `add_legend()` rows for all four.
- **New validator rules** catch a DRG box parented inside a VCN and any leaf sitting inside a VCN/subnet it does not belong to, with tolerances so border-straddling gateways still pass.
- **Model schema 2** (`drgs[]` with typed attachments, `services[].regional`, `gateways[].peer`) with automatic migration and a warning for schema-1 models.
- **Route tables, security lists and NSGs are badges, not icons.** `subnet.route_table` / `subnet.security_lists` draw half-size badges on the subnet's top-right corner and `item.nsgs` a shield on the protected resource's icon (names in the tooltip); `parse_terraform.py` and `query_tenancy.py` fill the fields from the Terraform and topology attributes.

## What was new in 1.2.0

Driven by the full code review and output-quality audit of 1.1.0. Highlights (full list in [CHANGELOG.md](CHANGELOG.md)):

- **Workflow runs as written**: generated scripts import the builder from the plugin (`sys.path.insert(0, "<plugin>/scripts")`) instead of copying `drawio_builder.py`; icons resolve via `$OCI_SVG_DIR`, the plugin `icons/`, `$CLAUDE_PLUGIN_ROOT/icons` and the `~/.claude/plugins` install locations
- **Reference look restored**: 12px top-left region / on-prem / compartment labels, charcoal 1px dashed services panel, dashed edges `dashPattern=6 3`, font stack `Oracle Sans,Arial,Helvetica,sans-serif`; style profiles `default` / `official` / `v1.0`; new container types `other`, `metro_or_realm`, `third_party_cloud`, `internet`; `ocean` and `neutral_4` added to `COLORS`
- **Icons**: 16 icons lost their ghost placeholder rectangle, every viewBox is cropped to the glyph, every glyph is fitted into a uniform 70x70 area of the 75x95 slot; 55 empty stencil shells deleted, 4 scrape-artifact files renamed; 159 icons in 12 categories, all addressable by file stem plus 206 short aliases
- **Self-routing edges**: `add_edge()` defaults to the common-ancestor parent and routes through container margins and gutters, avoiding icons, captions and titles; `route="direct"` / `route="pinned"` keep the old behaviours
- **Stronger validation**: any-two-container overlaps, containment, icon/caption collisions, unknown `parent` / `source` / `target` ids, long captions, estimated edge crossings; compressed pages and `UserObject` wrappers handled
- **Helpers**: `place_icons`, `fit_to_children`, `resize`, `fit_page`, `add_title`, `add_legend`, `add_table`, `add_page` / `use_page` / `add_layer`, `key=` for deterministic ids, `metadata` / `tooltip` / `link`, `write()` accepts `str`, `render()`
- **New scripts**: `oci_layout.py` (model -> diagram), `render_drawio.py`, `build_icon_catalog.py`, `smoke_test.sh`, `parse_terraform.py` (HCL dir / `--plan-json` / `--state-json` -> model), experimental `query_tenancy.py` (live tenancy -> model); `examples/generate_reference_layout.py`; `tests/` (builder, settings detection, icon set)
- **detect_settings rewritten**: `var.region` resolution, comment stripping, provider-block scoping, brace-matched variables, `.terraform` pruning, complete region table, `[DEFAULT]` inheritance, CLI timeouts and `security_token` auth, fixed logo classification, relative logo paths; new keys `vcns`, `compartments`, `terraform_dirs`, `auth_tenancy_ocid`, `oci_auth`, `subscribed_regions`, `home_region`
- **Installer / packager**: `python3 -m pip --user`, Pillow optional, `rsync` or `cp`, JSON upsert of `marketplace.json`, 8 verification checks incl. smoke test, better uninstall; reproducible `pack.sh` with `LICENSE` + `icons/NOTICE`, SHA256 printed

## Installation

```bash
tar -xzf oci-drawio-architect-v1.3.0.tar.gz
./oci-drawio-architect/install.sh
```

Then, inside Claude Code: `/plugin marketplace add ~/.claude/plugins/marketplaces/local`, `/plugin install oci-drawio-architect@local`, restart. `install.sh --uninstall` reverses everything.

## Usage

### Slash Command

```
/drawio-architect
```

Interactive workflow:
1. **Settings** - load `.claude/oci-drawio-architect.local.md` or auto-detect (tenancy, region, VCNs, compartments, logos)
2. **Input** - Terraform path, VCN name, or free-form description
3. **Model** - normalize the input into the diagram model (VCNs, subnets, services with their regional / VCN-resident class, gateways, DRGs with attachments, on-premises side, edges)
4. **Generate** - write `generate_<name>_drawio.py` on top of `DrawioBuilder` / `oci_layout`
5. **Run** - execute it to produce the `.drawio`
6. **Validate + render** - `scripts/check_overlaps.py` must exit 0; `scripts/render_drawio.py` exports a PNG when draw.io desktop is installed
7. **Report** - path, size, contents, settings used

### Skill (Auto-Activated)

The `oci-drawio-architect` skill activates automatically when you mention:
- "draw.io OCI"
- "diagram this architecture"
- "drawio with OCI icons"

## Project Settings

On first run, `/drawio-architect` runs `scripts/detect_settings.py` and saves the result to `.claude/oci-drawio-architect.local.md` (per-project, gitignored via `.claude/*.local.md`).

```bash
python3 scripts/detect_settings.py [-h] [--no-cli] [terraform_dir]   # exit 0 ok, 1 nothing found, 2 bad dir
```

### Auto-Detection Sources

| Setting | Terraform | OCI CLI | `~/.oci/config` |
|---------|-----------|---------|-----------------|
| `region`, `region_label` | non-aliased `provider "oci"` block; `var.` / `local.` resolved via `terraform.tfvars`, `*.auto.tfvars[.json]`, variable defaults | - | profile region (fallback) |
| `oci_profile`, `oci_auth` | `config_file_profile`, `auth` | - | `security_token_file` -> `security_token` |
| `tenancy_ocid`, `auth_tenancy_ocid` | provider block / tfvars (`^ocid1.tenancy.`) | corrected from `oci iam tenancy get` | profile tenancy |
| `tenancy_name` | - | `oci iam tenancy get` | - |
| `home_region`, `subscribed_regions` | - | `oci iam region-subscription list` | - |
| `compartment`, `compartment_ocid`, `compartments` | `oci_identity_compartment` resources, `compartment_ocid` / `compartment_id` | - | - |
| `vcns` | `oci_core_vcn` resources, `vcns = {...}` tfvars maps | - | - |
| `terraform_dir`, `terraform_dirs` | shallowest dir with a `provider "oci"` block (else tfvars); ties reported | - | - |
| `logo_light`, `logo_dark` | file scan (see below) | - | - |

Comments are stripped before parsing, `terraform {}` / `backend {}` blocks and non-OCI providers are ignored, `.terraform`, `.git`, `node_modules`, `.venv` and `__pycache__` are pruned. `~/.oci/config` (or `$OCI_CLI_CONFIG_FILE`) keys inherit from `[DEFAULT]`. CLI calls time out after 8 s and use `--auth security_token` when session auth is configured; `--no-cli` skips them. The region table has 55 entries (`uk-london-1` is London; `eu-london-1` does not exist) and unknown regions get a derived label.

Logo scan: `logos/`, `assets/logos/`, `assets/images/`, `docs/logos/` (stored as project-relative paths), then the optional plugin-local `logos/` directory (absolute paths) - drop your own PNG/SVG files there for a default logo. Files named `*dark*` / `*black*` become `logo_light` (dark artwork for light backgrounds); `*white*` / `*light*` become `logo_dark`.

### Settings File Format

`.claude/oci-drawio-architect.local.md`:
```markdown
---
tenancy_name: "mytenancy"
tenancy_ocid: "ocid1.tenancy.oc1..aaaa..."
region: "uk-london-1"
region_label: "London"
home_region: "uk-london-1"
subscribed_regions: ["uk-london-1", "eu-frankfurt-1"]
oci_profile: "DEFAULT"
compartment: "my-compartment"
compartment_ocid: "ocid1.compartment.oc1..aaaa..."
vcns: [{"name": "hub-vcn", "cidr": "10.0.0.0/16"}, {"name": "spoke-vcn", "cidr": "10.1.0.0/16"}]
logo_light: "logos/company_logo_dark.png"
logo_dark: "logos/company_logo_light.png"
terraform_dir: "terraform/environments/london"
---

# OCI draw.io Architect Settings
Auto-detected. Edit values above as needed.
```

To re-detect: delete the file and run `/drawio-architect` again. Any field can be edited by hand; `compartment`, `region_label` and the logo paths are the usual overrides.

## Diagram Types

All types share one model schema (see `scripts/oci_layout.py`) and the page is sized from the content with `fit_page()`.

| Type | Best For | Layout |
|------|----------|--------|
| Single-VCN Topology | Application stacks (single VCN) | Region > optional on-premises panel + DRG column + one VCN column: subnet rows in traffic order, data tier, gateways on the VCN border, Oracle Services Network panel |
| Hub-and-Spoke Network | Network overview with DRG | On-premises panel (CPE), region-level DRG with one attachment box per spoke, spoke VCN columns, OSN panel; attachment connectors without arrowheads |
| Service Inventory | Compartment-level resource view | Compartment / services panels via `place_icons()` + `fit_to_children()`, rule lists via `add_table()` |
| Multi-VCN Overview | VCN interconnections via DRG | Several VCN columns, LPG pairs on facing borders, OSN panel, cross-VCN edges |

## Prerequisites

- **Python 3.9+** (standard library only)
- **draw.io desktop**: for viewing generated diagrams and for the optional PNG/SVG/PDF export
- (Optional) **Pillow**: `python3 -m pip install --user Pillow` - only for embedding PNG/JPEG logos with `add_image()`
- (Optional) **OCI CLI**: for auto-detecting tenancy name and region subscriptions

OCI SVG icons (159 files, 12 categories, about 1.4 MB) are bundled in `icons/`; no external icon dependency is needed. Override the location with `OCI_SVG_DIR`.

## Plugin Structure

```
oci-drawio-architect/
├── .claude-plugin/
│   └── plugin.json                    # Plugin manifest (version 1.3.0)
├── commands/
│   └── drawio-architect.md            # /drawio-architect slash command
├── skills/
│   └── oci-drawio-architect/
│       ├── SKILL.md                   # Auto-activated skill
│       └── references/
│           ├── oracle-styles.md       # Container / edge / colour reference
│           ├── icon-catalog.md        # Generated: 159 icons, 206 aliases
│           ├── gotchas.md             # Known pitfalls and workarounds
│           └── templates/             # physical_example_*.svg composites (docs only)
├── scripts/
│   ├── drawio_builder.py              # DrawioBuilder (v1.3.0): icons, styles, routing, validation
│   ├── oci_layout.py                  # Model dict/JSON -> .drawio layout recipe (CLI + API)
│   ├── check_overlaps.py              # Validator CLI: --strict, --quiet; exit 0/1/2
│   ├── render_drawio.py               # PNG/SVG/PDF export via draw.io desktop; exit 0/1/3
│   ├── detect_settings.py             # Settings probe: Terraform, ~/.oci/config, OCI CLI
│   ├── parse_terraform.py             # HCL dir / plan JSON / state JSON -> model (--vcn, --out)
│   ├── query_tenancy.py               # Experimental: live tenancy -> model via OCI CLI
│   ├── oci_topology.py                # Topology classification, legacy-model migration, DRG-style choice
│   ├── build_icon_catalog.py          # Regenerate / --check references/icon-catalog.md
│   └── smoke_test.sh                  # Demo -> overlap gate -> PNG (if draw.io present)
├── examples/
│   ├── generate_demo_diagram.py       # Three-page demo: recipe on a hybrid model, both DRG styles, all four edge kinds, legend, plus a custom-API NSG table page
│   ├── generate_reference_layout.py   # Rebuilds the reference sample from a MODEL dict
│   └── make_screenshots.py            # Regenerates the README screenshots from the reference example
├── tests/
│   ├── test_builder.py                # DrawioBuilder: styles, routing, validation, helpers
│   ├── test_oci_layout.py             # Layout recipe: DRG column, border gateways, OSN panel, edge kinds
│   ├── test_oci_topology.py           # classify_topology, migrate_legacy_model, is_regional, choose_drg_style
│   ├── test_detect_settings.py        # Settings probe over tests/fixtures/detect/*
│   ├── test_icons.py                  # SVG integrity, viewBox, aliases, ICON_MAP
│   └── fixtures/
│       └── terraform/hub_spoke/       # Two VCNs, one DRG with four attachments, an LPG pair, a regional log group
├── icons/                             # 159 OCI SVG icons in 12 category dirs + NOTICE
├── LICENSE                            # MIT (plugin code)
├── install.sh                         # Installer / --uninstall
├── pack.sh                            # Reproducible release tarball
├── CHANGELOG.md
└── README.md
```

## Development

```bash
python3 -m unittest discover -s tests          # builder, settings detection, icons
scripts/smoke_test.sh                          # demo -> check_overlaps -> PNG (SMOKE_SKIP_PNG=1 to skip)
python3 examples/generate_reference_layout.py out.drawio --render
python3 scripts/parse_terraform.py <tf_dir> [--vcn NAME] [--plan-json F | --state-json F] --out model.json
python3 scripts/check_overlaps.py --strict out.drawio
python3 scripts/oci_layout.py model.json -o out.drawio [--profile default|official|v1.0] [--legend] [--logo f] [--render png] [--drg-style auto|icon|box]
python3 scripts/build_icon_catalog.py --check   # after touching icons/
./pack.sh [/output/dir]                         # oci-drawio-architect-v1.3.0.tar.gz + SHA256
```

Generated files weigh roughly 7-13 KB per embedded icon (the three-page demo with 26 icons is about 300 KB; the reference sample with 31 icons about 280 KB).

## Icon licensing

The plugin code is MIT (see `LICENSE`). The SVGs under `icons/` are Oracle Cloud Infrastructure architecture icons, Copyright (c) Oracle and/or its affiliates, from the [OCI Architecture Diagram Toolkit](https://docs.oracle.com/en-us/iaas/Content/General/Reference/graphicsfordiagrams.htm). They are not covered by the MIT license and are bundled only to document OCI architectures - see `icons/NOTICE`.
