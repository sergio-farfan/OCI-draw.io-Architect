---
name: drawio-architect
description: Generate an OCI architecture .drawio diagram (and PNG) from a Terraform directory, a terraform show -json file, a VCN name or a description, using the deterministic v1.3.0 layout recipe
argument-hint: [terraform-dir | plan.json | vcn-name | "description"]
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, AskUserQuestion
---

# /drawio-architect

Produce `<Subject>_Architecture.drawio` (+ `.png`) that matches the plugin's reference look. The layout is computed by `scripts/oci_layout.py` from a model dict; your job is to fill the model correctly and pass the gate. Conventions, schema and the custom-layout API are in `${CLAUDE_PLUGIN_ROOT}/skills/oci-drawio-architect/SKILL.md`.

Global rules:
1. NEVER copy `drawio_builder.py` (or any script) into the project. Generated scripts import from the plugin: `sys.path.insert(0, "<abs>/scripts")`. Resolve the absolute path first with `echo "$CLAUDE_PLUGIN_ROOT"` and paste it literally (the user runs the script outside Claude Code).
2. Use the recipe (`oci_layout.write_diagram`) unless the architecture cannot be expressed by it (see Step 3.4).
3. Never report success while Step 5's gate fails. Iterate at most 3 times, then report the remaining problems verbatim.
4. Input is `$ARGUMENTS`; if empty, ask (Step 1).

## Step 0 - Settings

1. If `.claude/oci-drawio-architect.local.md` exists, read its YAML frontmatter and use the keys below.
2. Else run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/detect_settings.py" [terraform_dir]` (add `--no-cli` when the OCI CLI is absent, unconfigured or hangs; each CLI call is bounded to 8 s). Exit 1 = nothing detected; exit 2 = the directory does not exist. Stdout is the frontmatter; stderr is the summary.
3. Required values: `region` (settings) and `subject` (Step 1). Ask with AskUserQuestion ONLY for values that are still missing. Do not ask about logos, tenancy or compartment; use them when present, omit them otherwise.
4. Write the settings file from this template, keeping only detected/answered keys (values are JSON-quoted scalars; lists as JSON):

```markdown
---
tenancy_name: "mytenancy"
tenancy_ocid: "ocid1.tenancy.oc1..aaaa"
region: "eu-frankfurt-1"
region_label: "Frankfurt"
oci_profile: "DEFAULT"
compartment: "prod"
vcns: [{"name": "app-vcn", "cidr": "10.0.0.0/16"}]
logo_light: "logos/company_logo_dark.png"
terraform_dir: "terraform/environments/prod"
---

# OCI draw.io Architect Settings
Detected on YYYY-MM-DD by /drawio-architect. Edit values above; delete the file to re-detect.
```

5. The file may contain OCIDs: make sure the project `.gitignore` has the line `.claude/*.local.md` (`grep -qxF '.claude/*.local.md' .gitignore 2>/dev/null || echo '.claude/*.local.md' >> .gitignore`).

## Step 1 - Input

Classify `$ARGUMENTS`; if empty, ask one AskUserQuestion with these five options.

| Input | Recognise by | Model source (Step 2) |
|-------|--------------|-----------------------|
| Terraform directory | contains `*.tf` / `*.tfvars` | `parse_terraform.py TF_DIR` |
| Plan or state JSON | `terraform show -json` output (`planned_values` or `values` key) | `parse_terraform.py --plan-json FILE` or `--state-json FILE` |
| VCN name | matches `vcns` in settings or a `display_name` in `terraform_dir` | `parse_terraform.py TF_DIR --vcn NAME` |
| Free-form description | anything else ("hub-and-spoke with a firewall and two spokes") | MODEL written by hand |
| Live tenancy (experimental) | user asks for "as-built" / "what is deployed" and gives a compartment OCID | `query_tenancy.py` |

## Step 2 - Build the model

1. Terraform present: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/parse_terraform.py" [TF_DIR] [--plan-json FILE | --state-json FILE] [--vcn NAME] --out model.json`, then read `model.json`. Add `--no-inferred-edges` when you want only edges backed by explicit Terraform references.
2. Live tenancy (EXPERIMENTAL, needs the OCI CLI): `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/query_tenancy.py" --compartment-id OCID [--vcn-id OCID] [--profile P] [--region R] [--from-json FILE] --out model.json`. Tell the user the mode is experimental and to verify resource counts.
3. Otherwise write the MODEL dict by hand (schema: SKILL.md section 2; template: `${CLAUDE_PLUGIN_ROOT}/examples/generate_reference_layout.py`).
4. Enrich every model, in this order:
   1. `subject` = VCN name for a single VCN, else the system name; `region`, `region_label`, `compartment`, `tenancy_name` from settings.
   2. Captions follow `"Role\nidentifier\nsize"`: max 3 lines of about 16 characters (`"App VM\n10.0.1.5\n4 OCPU / 32 GB"`, `"ADB prod\napp-db\n16 ECPU / 4 TB"`). Shorten with `...` instead of adding lines.
   3. `tier` per subnet: `lb`, `app`, `compute`, `mgmt`, `data` (`other` for the rest). Infer from names when Terraform gives none (lb/web/dmz/pub, app/api/worker, oke/node/compute, mgmt/bastion/ops, db/data/database).
   4. Item order inside a subnet: primary resource (LB, VM, DB) -> attached resources (block volume, certificate, WAF). NSGs are not items (2.4.10).
   5. Regional services (Logging, Monitoring / Alarms, Notifications, Events, Connector Hub, IAM / Identity, Vault / KMS, Certificates, Object Storage, OCIR, AI, Data Safe, Streaming, Queue, APM, DevOps, DNS zones) go to `vcn.services` or `model.services`; the recipe draws them in the region-level Oracle Services Network panel. VCN-resident services without a subnet (mount targets, file systems, private DNS resolvers) also go to `vcn.services` with `"regional": false` when the table would misclassify them.
   6. Gateways (IGW, NAT, SGW, LPG) go to `vcn.gateways` with `type` (`igw`, `nat`, `sgw`, `lpg`), two-line captions and, for LPGs, `peer`. Never put a DRG or a DRG attachment in `gateways`.
   7. DRGs go to `model.drgs` with one attachment per attached network (`type` `vcn` + `vcn` name, `ipsec` / `virtual_circuit` / `rpc` + `target` hub item address). CPE, IPSec endpoint, FastConnect virtual circuit, RPC peer and on-premises firewalls go to `model.hub` (`name = "On-premises"`). Add an explicit `cpe -> drg` edge only when the model has no `ipsec` attachment. Choose `drg_style`: `icon` (default, architecture views) or `box` when the reader wants the attachments as a network detail (`auto` = box above 4 attachments).
   8. Give every item an `address`; edges use addresses (or `vcn:<name>`, `subnet:<name>`, `hub`, `services`). Add an edge only where a route rule, security rule, LB backend set or DB connection justifies it; `label` = port(s) (`"443"`, `"1522"`, `"3000 / 8000"`); `kind` = `data` for traffic, `control` for management/API calls, `analytics`/`datalake` for those flows. Target 0.3-0.6 edges per icon.
   9. Keep OCIDs and shapes in item `metadata` and a one-line `tooltip`.
   10. Security constructs: put the subnet's route table in `subnet.route_table` and its security lists in `subnet.security_lists`, and the NSGs of a resource in that item's `nsgs` (names, or `{"name", "address"}` when you want the badge as an edge endpoint). The recipe draws them as badges on the subnet's top-right corner and on the resource's icon; never add `route_table`, `security_list` or `nsg` icons to a subnet.

## Step 3 - Generate `generate_<subject>_drawio.py`

1. The file MUST start with the plugin path insert and use `write_diagram`:

```python
import sys
sys.path.insert(0, "/ABSOLUTE/PATH/TO/oci-drawio-architect/scripts")   # ${CLAUDE_PLUGIN_ROOT}/scripts, resolved
from oci_layout import write_diagram

MODEL = {
    "subject": "app-prod", "region": "eu-frankfurt-1", "region_label": "Frankfurt", "compartment": "prod",
    "drg_style": "auto",
    "hub": {"name": "On-premises", "items": [{"icon": "cpe", "label": "Corp VPN\n(10.0.0.0/8)", "address": "cpe"}]},
    "drgs": [{"name": "drg", "address": "drg", "label": "Dynamic Routing\nGateway (DRG)",
              "attachments": [{"type": "vcn", "vcn": "app-vcn", "address": "drg-att-app",
                               "label": "VCN attachment\napp-vcn"}]}],
    "vcns": [{"name": "app-vcn", "cidr": "10.0.0.0/16", "subnets": [
        {"name": "sn-lb", "cidr": "10.0.0.0/24", "tier": "lb", "public": True,
         "items": [{"icon": "load_balancer", "label": "Load Balancer\n10.0.0.7", "address": "lb"}]},
        {"name": "sn-app", "cidr": "10.0.1.0/24", "tier": "app",
         "route_table": "rt-app", "security_lists": ["sl-app"],
         "items": [{"icon": "vm", "label": "App VM\n10.0.1.5\n4 OCPU / 32 GB", "address": "app",
                    "nsgs": ["nsg-app"]}]},
        {"name": "sn-db", "cidr": "10.0.2.0/24", "tier": "data",
         "items": [{"icon": "autonomous_db", "label": "ADB prod\napp-db\n4 ECPU / 1 TB", "address": "adb"}]}],
        "services": [{"icon": "logging", "label": "Logging", "address": "logging", "regional": True}],
        "gateways": [{"icon": "internet_gateway", "type": "igw", "label": "Internet\nGateway", "address": "igw"},
                     {"icon": "service_gateway", "type": "sgw", "label": "Service\nGateway", "address": "sgw"}]}],
    "edges": [{"source": "igw", "target": "lb", "label": "443", "kind": "data"},
              {"source": "lb", "target": "app", "label": "8080", "kind": "data"},
              {"source": "app", "target": "adb", "label": "1522", "kind": "data"},
              {"source": "app", "target": "sgw", "label": "OCI APIs", "kind": "control"}],
}

write_diagram(MODEL, "app-prod_Architecture.drawio", render_fmt="png")
```

2. Optional `write_diagram` kwargs: `style_profile="official"|"v1.0"`, `legend=True` (only when asked or with 3+ edge kinds), `logo=<settings logo_light>`, `strict=True` (crossings become errors), `drg_style="box"` (attachments as a dashed `DRG: <name>` group instead of loose boxes). A large `model.json` may be loaded with `json.load` instead of inlined.
3. `write_diagram` validates, refuses to write on errors (`SystemExit`), writes the file and renders the PNG when draw.io desktop is installed.
4. Custom layout ONLY when the recipe cannot express the architecture (availability/fault domains, nested compartments, several regions, third-party cloud, rule tables, extra pages). Then use `DrawioBuilder` from the same `scripts` directory with `place_icons` -> `fit_to_children` (innermost first) -> `fit_page` -> `validate` gate exactly as in SKILL.md section 6; never hand-compute container sizes.

## Step 4 - Run

`python3 generate_<subject>_drawio.py`. Expect `Wrote <file> (<n> bytes)` and either `Rendered <file>.png` or `draw.io desktop not found; render skipped`. Any `ERROR`/`OVERLAP` line means the file was not written: fix the model and rerun.

## Step 5 - Gate (mandatory)

1. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_overlaps.py" "<Subject>_Architecture.drawio"` must exit 0 (1 = errors, 2 = unreadable/unparsable file). Add `--strict` to make crossings blocking.
2. Fix every `ERROR`/`OVERLAP` line (table below). Read every `WARNING`: long caption -> shorten to 3 lines; estimated crossing -> look at the PNG, then reorder items, move the item to the right tier/panel, or (custom layouts) add `label_pos`/`route="direct"`; accept only when the PNG shows no real crossing.
3. If Step 4 did not render: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render_drawio.py" "<Subject>_Architecture.drawio" -f png` (exit 3 = draw.io absent -> skip and say so).
4. READ the PNG with the Read tool and check: all glyphs the same size; every caption legible, inside its container, not overlapping; edges run in gutters and cross no icon or caption; on-premises panel and DRG centred on the VCN stack; DRG outside every VCN, attachment boxes beside it; gateways centred on the VCN border; Oracle Services Network panel right of the VCNs; route table / security list badges on the subnets' top-right corners and NSG badges on the top-right of their icons, none of them drawn as captioned icons; nothing outside the region; no large empty areas.
5. Anything failing -> back to Step 2. At most 3 iterations.

## Step 6 - Report

- Output path and size (expect roughly 7-13 KB per icon; the 31-icon reference is 280 KB), page size (`pageWidth` x `pageHeight` in the file), counts (VCNs, subnets, icons, edges).
- Settings used (region, compartment, tenancy, profile, logo) and the gate line verbatim (`OK: no container overlaps ...`).
- Assumptions: guessed icons and their fallbacks, inferred tiers, edges not backed by Terraform, resources left out.
- PNG path, or "render skipped: draw.io desktop not installed".
- Open the file in draw.io desktop; reopen if fonts look wrong (render cache).

## Diagram types

| Type | Model shape | Files |
|------|-------------|-------|
| Single VCN | one `vcns` entry, optional `hub`, services in `vcn.services` | one |
| Hub-and-spoke | `model.hub` (CPE) + `model.drgs` (one DRG, one attachment per spoke) + spoke VCN columns; regional services in the OSN panel | one while <= 3 VCNs and <= 40 icons |
| Multi-VCN overview | several VCNs, LPG pairs via `gateways[].peer`, edges between `vcn:<name>` endpoints | one |
| Service inventory | custom layout: `compartment` groups + `place_icons`, no subnets (SKILL.md section 6) | one |

Split when there are more than 3 VCNs or 45 icons, or when row 1 wraps to a third row (row budget 1000 px): one file per VCN plus an overview, or extra pages via `add_page()` in a custom layout (rule tables on page 2).

## Settings reference (`.claude/oci-drawio-architect.local.md`)

| Key | Source | Used for |
|-----|--------|----------|
| `tenancy_name` | `oci iam tenancy get` / manual | title prefix (`model.tenancy_name`) |
| `tenancy_ocid`, `auth_tenancy_ocid`, `terraform_tenancy_ocid` | Terraform provider / `~/.oci/config` | CLI queries; `auth_*` set when the config identity differs from Terraform's |
| `region`, `region_label` | provider `region` / `~/.oci/config`; label derived | region container label, title |
| `home_region`, `subscribed_regions` | `oci iam region-subscription list` | choosing a region when several are in play |
| `oci_profile`, `oci_auth` | `config_file_profile` / config (`security_token`) | `query_tenancy.py --profile` |
| `compartment`, `compartment_ocid`, `compartments` | `oci_identity_compartment` resources / vars | title `Compartment:` line, `query_tenancy.py --compartment-id` |
| `vcns` | `oci_core_vcn` resources / tfvars (`[{"name","cidr"}]`) | VCN-name lookup, subject default |
| `logo_light`, `logo_dark` | file scan (`*dark*`/`*black*` -> `logo_light`; `*white*`/`*light*` -> `logo_dark`) | `write_diagram(..., logo=logo_light)` on the white page |
| `terraform_dir`, `terraform_dirs` | shallowest dir with `provider "oci"`; ties listed | default Terraform input |

Delete the file to re-detect.

## Failure handling

| Symptom | Action |
|---------|--------|
| `Unknown icon_key '...'. Did you mean ...` | Use the suggestion or look the key up in `references/icon-catalog.md` (aliases or file stems); never invent keys |
| `OCI icon directory not found ... Searched:` | Import path wrong (copied builder?) - fix `sys.path.insert` to the plugin `scripts` dir, or `export OCI_SVG_DIR="${CLAUDE_PLUGIN_ROOT}/icons"` |
| `Pillow is required for PNG/JPEG logos` | Use an SVG logo, or `python3 -m pip install --user Pillow`, or drop `logo=` |
| `detect_settings.py` hangs or prints `cli_warning` | Rerun with `--no-cli`; fill `tenancy_name` by hand |
| `draw.io desktop not found` / render exit 3 | Skip the PNG step, report it; `DRAWIO_BIN=/path/to/drawio` overrides discovery |
| `edge endpoint 'x' not found` / `matches N items` | Use the item's `address` (or `vcn:`/`subnet:`/`hub`/`services`) as endpoint |
| `OVERLAP: 'A' intersects 'B'` | Recipe: split the VCN or move items between subnets. Custom: call `fit_to_children` innermost-first and place siblings from `bbox()` + `GAP` |
| `ERROR: '...' extends outside its parent` | Custom layout: `fit_to_children(parent)` after adding children; never hardcode container sizes |
| `ERROR: '...' overlaps '...'` (icons/captions) | Use `place_icons` pitches (`COL_W` 130, `ROW_H` 160); shorten captions to 3 lines |
| `ERROR: ... unknown parent id` / `source id does not exist` | Pass ids returned by `add_group`/`add_icon`; edges only between cells on the same page |
| `ERROR: DRG '...' is inside VCN '...'` | Move the DRG to `drgs[]` (recipe) or parent it to the region outside every VCN box (custom) |
| `ERROR: '...' lies inside '...' but is not one of its children` | The icon's box overlaps a VCN / subnet it does not belong to; move it or make it a child of that container |
| `WARNING: legacy model: ...` | The model still uses schema 1; move the DRG into `drgs[]` |
| `WARNING: caption ... needs ~N lines` | Rewrite the caption as Role / identifier / size, 3 lines max |
| `WARNING: edge ... is estimated to cross` | Check the PNG; reorder items or change tier; custom: `route="direct"` or `label_pos` |
| `WARNING: content ... exceeds the page` | Call `fit_page()` last (custom layouts) |
| checker exit 2 | File missing, not XML, or the checker was moved away from `drawio_builder.py` |

## Prerequisites

- Python 3.9+ (standard library only); Pillow only for PNG/JPEG logos.
- draw.io desktop for PNG export and viewing (`/Applications/draw.io.app`, `drawio` on PATH or `DRAWIO_BIN`).
- OCI CLI (optional) for tenancy-name detection and the experimental `query_tenancy.py`; Terraform (optional) for `terraform show -json`.
- Icons ship in `${CLAUDE_PLUGIN_ROOT}/icons/` (159 SVGs); `OCI_SVG_DIR` overrides the location.
