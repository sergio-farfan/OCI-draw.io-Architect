---
name: drawio-architect
description: Generate an OCI architecture .drawio diagram (and PNG) from a Terraform directory, a terraform show -json file, a VCN name or a description, using the deterministic v1.5.0 layout recipe with purpose, detail-level, label-mode, layer and filter controls
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
purpose: "network"
logo_light: "logos/company_logo_dark.png"
terraform_dir: "terraform/environments/prod"
---

# OCI draw.io Architect Settings
Detected on YYYY-MM-DD by /drawio-architect. Edit values above; delete the file to re-detect.
```

5. The file may contain OCIDs: make sure the project `.gitignore` has the line `.claude/*.local.md` (`grep -qxF '.claude/*.local.md' .gitignore 2>/dev/null || echo '.claude/*.local.md' >> .gitignore`).
6. View choices are never *detected*, only answered. The canvas is `locations: "outside"` and the subnet labels are two lines unless the user asks otherwise. Offer `show_compartments` only when the tenancy has more than one compartment in play and the user asks "show the compartments" - a view with every compartment drawn is unreadable, which is why it is off by default. The v1.4.0 choices are flags on the layout CLI: `--locations`, `--gateway-edge`, `--subnet-label`, `--attachment-style`, `--show-compartments`.
7. **`purpose` is the one view choice that is remembered.** If the settings file has `purpose:`, use it and say so; otherwise Step 1 asks for it and you write it back into the settings file. Nothing else about the view is persisted: `detail`, `label_mode`, `label_fields`, `layers`, `filter`, `mode` and `global_services` are per-run choices, and a remembered filter that has gone stale silently produces a wrong diagram.

## Step 1 - Input and purpose

1. Classify `$ARGUMENTS`; if empty, ask one AskUserQuestion with these five options.
2. **Ask the diagram's purpose** with a second `AskUserQuestion` - unless `purpose:` is already in the settings file, in which case state which one is in force and move on. The six options, verbatim:

| Option | `--purpose` | Pick it when |
|--------|-------------|--------------|
| Network topology | `network` | The reader asks "how is this wired" - subnets, gateways, route tables, security lists. Today's default look |
| Application / data flow | `dataflow` | The reader follows a request through the system; only the participating resources, ports on every connector |
| Security architecture | `security` | The reader audits controls - NSGs and security lists in front, IAM and policies in their own tenancy bucket |
| Resource / inventory view | `inventory` | The reader wants what exists and where, not how it talks - no connectors, compartments drawn |
| Dependency / relationship view | `dependency` | The reader asks what depends on what, and wants to know how each relationship was discovered |
| Deployment / high-availability architecture | `ha` | The reader checks resiliency - availability and fault domains in every caption |

3. Write the answer back into `.claude/oci-drawio-architect.local.md` as `purpose: "<value>"`.

| Input | Recognise by | Model source (Step 2) |
|-------|--------------|-----------------------|
| Terraform directory | contains `*.tf` / `*.tfvars` | `parse_terraform.py TF_DIR` |
| Plan or state JSON | `terraform show -json` output (`planned_values` or `values` key) | `parse_terraform.py --plan-json FILE` or `--state-json FILE` |
| VCN name | matches `vcns` in settings or a `display_name` in `terraform_dir` | `parse_terraform.py TF_DIR --vcn NAME` |
| Free-form description | anything else ("hub-and-spoke with a firewall and two spokes") | MODEL written by hand |
| Live tenancy (experimental) | user asks for "as-built" / "what is deployed" and gives a compartment OCID | `query_tenancy.py` |

## Step 2 - Build the model

1. Terraform present: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/parse_terraform.py" [TF_DIR] [--plan-json FILE | --state-json FILE] [--vcn NAME] --out model.json`, then read `model.json`. Add `--no-inferred-edges` when you want only edges backed by explicit Terraform references. Scope it with `--filter EXPR` (repeatable), or its sugar `--tag K=V`, `--compartment NAME`, `--subnet NAME`, `--resource-type TYPE`. **`--mode` defaults to `all` here**: a Terraform configuration is already a curated set. Pass `--mode participating` to keep only what takes part in the architecture. A plan or state JSON also carries the private IPs, the lifecycle states and the tags that the label modes and the filters need - prefer it over bare HCL when it exists.
2. Live tenancy (EXPERIMENTAL, needs the OCI CLI): `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/query_tenancy.py" --compartment-id OCID [--vcn-id OCID] [--profile P] [--region R] [--from-json FILE] --out model.json`. Tell the user the mode is experimental and to verify resource counts. **`--mode` defaults to `participating` here**, because a tenancy dump is not curated; `--mode all` shows everything. Cut a live tenancy down **before the model is written** - with `--filter` / `--tag` / `--resource-type` / `--subnet-id` on this command, not by editing `model.json` afterwards - so the counts you report are the counts you drew.
3. Otherwise write the MODEL dict by hand (schema: SKILL.md section 2; template: `${CLAUDE_PLUGIN_ROOT}/examples/generate_reference_layout.py`).
4. Enrich every model, in this order:
   1. `subject` = VCN name for a single VCN, else the system name; `region`, `region_label`, `compartment`, `tenancy_name` from settings.
   2. Captions follow `"Role\nidentifier\nsize"`: max 3 lines of about 16 characters (`"App VM\n10.0.1.5\n4 OCPU / 32 GB"`, `"ADB prod\napp-db\n16 ECPU / 4 TB"`). Shorten with `...` instead of adding lines.
   3. `tier` per subnet: `lb`, `app`, `compute`, `mgmt`, `data` (`other` for the rest). Infer from names when Terraform gives none (lb/web/dmz/pub, app/api/worker, oke/node/compute, mgmt/bastion/ops, db/data/database).
   4. Item order inside a subnet: primary resource (LB, VM, DB) -> attached resources (block volume, certificate, WAF). NSGs are not items (2.4.10).
   5. Regional services (Logging, Monitoring / Alarms, Notifications, Events, Connector Hub, IAM / Identity, Vault / KMS, Certificates, Object Storage, OCIR, AI, Data Safe, Streaming, Queue, APM, DevOps, DNS zones) go to `vcn.services` or `model.services`; the recipe draws them in the region-level Oracle Services Network panel. VCN-resident services without a subnet (mount targets, file systems, private DNS resolvers) also go to `vcn.services` with `"regional": false` when the table would misclassify them. The `dns` icon reads as PUBLIC DNS, which `--global-services bucket` treats as tenancy-scoped: give a **private** DNS zone `"scope": "regional"` (the parser does this for any `oci_dns_zone` with `scope = "PRIVATE"` or a `view_id`).
   6. Gateways (IGW, NAT, SGW, LPG) go to `vcn.gateways` with `type` (`igw`, `nat`, `sgw`, `lpg`), two-line captions and, for LPGs, `peer`. Never put a DRG or a DRG attachment in `gateways`.
   7. DRGs go to `model.drgs` with one attachment per attached network (`type` `vcn` + `vcn` name, `ipsec` / `virtual_circuit` / `rpc` + `target` hub item address). CPE, IPSec endpoint, FastConnect virtual circuit, RPC peer and on-premises firewalls go to `model.hub`; set `kind` to `onprem` (title `On-premises`) or to `remote_region` (title `Remote region`) when the hub holds only an RPC peer, and set `name` only to override that title. Add an explicit `cpe -> drg` edge only when the model has no `ipsec` attachment. Choose `drg_style`: `icon` (default, architecture views) or `box` when the reader wants the attachments as a network detail (`auto` = box above 4 attachments).
   8. Give every item an `address`; edges use addresses (or `vcn:<name>`, `subnet:<name>`, `services`, `services:<vcn>`, `hub`, `region`, `osn`, `drg:<name>`, a DRG address or a DRG attachment address). Add an edge only where a route rule, security rule, LB backend set or DB connection justifies it; `label` = port(s) (`"443"`, `"1522"`, `"3000 / 8000"`); `kind` = `data` (traffic), `control` (management / API calls), `association` (a dependency or configuration relationship that carries no traffic - Database -> Data Safe, resource -> Vault key; dotted, no arrowhead - never `control` for these), `attachment` (a structural link the recipe does not draw itself, such as an LPG pair; DRG attachments and Service Gateway -> Oracle Services Network come from the recipe), `analytics` / `datalake` for those flows. Target 0.3-0.6 edges per icon.
   9. Keep OCIDs and shapes in item `metadata` and a one-line `tooltip`.
   10. Security constructs: put the subnet's route table in `subnet.route_table` and its security lists in `subnet.security_lists`, and the NSGs of a resource in that item's `nsgs` (names, or `{"name", "address"}` when you want the badge as an edge endpoint). The recipe draws them as badges on the subnet's top-right corner and on the resource's icon; never add `route_table`, `security_list` or `nsg` icons to a subnet.
   11. A DRG's route tables go in `drgs[].route_table` (a name, `{"name", "address"}`, or a list - Oracle creates one table for VCN attachments and one for everything else); the recipe draws up to two badges under the DRG glyph.
   12. Compartment names are already in `model.compartments` and `vcn.compartment` after parsing; add `"show_compartments": True` only when the user asked for them, and use the object form `{"name", "parent", "vcns"}` when the compartments nest.
   13. Grouping boxes are opt-in: add a `subnet.groups[]` entry of type `oke_cluster` around an OKE cluster and its node pools (the parser does this for you when they share a subnet), and `tier` / `user_group` boxes only when the user asks for them. Members must live in the container that owns the box.
   14. **Captions are rendered, not hand-written, since 1.5.0.** Put the display name in `label` and the rest in `metadata`: `private_ip`, `public_ip`, `fqdn`, `ports` (`"TCP/22, 8088"`), `compartment`, `availability_domain`, `fault_domain`, `lifecycle_state`, `shape`. The default `label_mode: "network"` renders name + private IP + ports; `minimal` renders the name alone and `detailed` adds AD / FD and the compartment. **An OCID is never rendered in a caption in any mode** - it belongs in `metadata` and the tooltip. A value that is already in the authored `label` is never repeated, so a hand-written caption keeps rendering exactly as written.
   15. Tags go in `item["tags"] = {"freeform": {...}, "defined": {"<ns>.<key>": ...}}`, never in `metadata` (which is scalars only). They are what `--filter tag:K=V`, `env=` and `app=` match on.
   16. The view keys go at the top level of the model: `purpose`, `detail`, `label_mode`, `label_fields`, `label_tag_keys`, `layers`, `hidden_layers`, `filter`, `mode`, `global_services`, `show_edges`. The equivalent layout-CLI flags are `--purpose`, `--detail`, `--label-mode`, `--label-fields`, `--label-tag-keys`, `--layers`, `--hidden-layers`, `--filter`, `--mode`, `--discovery`, `--annotate-discovery`, `--global-services`, `--no-edges`. An explicit key always beats the purpose.

## Step 3 - Generate `generate_<subject>_drawio.py`

1. The file MUST start with the plugin path insert and use `write_diagram`:

```python
import sys
sys.path.insert(0, "/ABSOLUTE/PATH/TO/oci-drawio-architect/scripts")   # ${CLAUDE_PLUGIN_ROOT}/scripts, resolved
from oci_layout import write_diagram

MODEL = {
    "subject": "app-prod", "region": "eu-frankfurt-1", "region_label": "Frankfurt", "compartment": "prod",
    "drg_style": "auto",
    "purpose": "network",            # default; also dataflow, security, inventory, dependency, ha
    "locations": "outside",          # default; "nested" reproduces the v1.3.x canvas
    "subnet_label": "twoline",       # default; "inline" reproduces the v1.3.x one-line label
    "label_mode": "network",         # default; also minimal, detailed
    "layers": "off",                 # default; "auto" turns on the layer set the purpose names
    "hub": {"kind": "onprem", "items": [{"icon": "cpe", "label": "Corp VPN\n(10.0.0.0/8)", "address": "cpe"}]},
    "internet": {"name": "Internet", "items": []},   # the box the IGW faces; drop it when there is no IGW
    "drgs": [{"name": "drg", "address": "drg", "label": "Dynamic Routing\nGateway (DRG)",
              "attachments": [{"type": "vcn", "vcn": "app-vcn", "address": "drg-att-app",
                               "label": "VCN attachment\napp-vcn"}]}],
    "vcns": [{"name": "app-vcn", "cidr": "10.0.0.0/16", "subnets": [
        {"name": "sn-lb", "cidr": "10.0.0.0/24", "tier": "lb", "public": True,     # -> "sn-lb (Public)" / "10.0.0.0/24"
         "items": [{"icon": "load_balancer", "label": "Load Balancer\n10.0.0.7", "address": "lb"}]},
        {"name": "sn-app", "cidr": "10.0.1.0/24", "tier": "app", "public": False,  # -> "sn-app (Private)" / "10.0.1.0/24"
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

2. Optional `write_diagram` kwargs: `style_profile="official"|"v1.0"`, `legend=True` (only when asked or with 3+ edge kinds), `logo=<settings logo_light>`, `strict=True` (crossings become errors), `drg_style="box"` (attachments as a dashed `DRG: <name>` group instead of loose boxes), and eight view keywords that each override the model key of the same name: the five v1.4.0 ones `locations`, `gateway_edge`, `subnet_label`, `attachment_style`, `show_compartments`, plus `label_mode`, `label_fields`, `label_tag_keys`. The rest of the view - `purpose`, `detail`, `layers`, `hidden_layers`, `filter`, `mode`, `global_services`, `show_edges` (item 16 above) - has no `write_diagram` kwarg and is read from the model only. A large `model.json` may be loaded with `json.load` instead of inlined.
3. `write_diagram` validates, refuses to write on errors (`SystemExit`), writes the file and renders the PNG when draw.io desktop is installed.
4. Custom layout ONLY when the recipe cannot express the architecture (availability/fault domains, nested compartments, several regions, third-party cloud, rule tables, extra pages). Then use `DrawioBuilder` from the same `scripts` directory with `place_icons` -> `fit_to_children` (innermost first) -> `fit_page` -> `validate` gate exactly as in SKILL.md section 7; never hand-compute container sizes.

## Step 4 - Run

`python3 generate_<subject>_drawio.py`. Expect `Wrote <file> (<n> bytes)` and either `Rendered <file>.png` or `draw.io desktop not found; render skipped`. Any `ERROR`/`OVERLAP` line means the file was not written: fix the model and rerun.

## Step 5 - Gate (mandatory)

1. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_overlaps.py" "<Subject>_Architecture.drawio"` must exit 0 (1 = errors, 2 = unreadable/unparsable file). Add `--strict` to make crossings blocking.
2. Fix every `ERROR`/`OVERLAP` line (table below). Read every `WARNING`: long caption -> shorten to 3 lines; estimated crossing -> look at the PNG, then reorder items, move the item to the right tier/panel, or (custom layouts) add `label_pos`/`route="direct"`; accept only when the PNG shows no real crossing.
3. If Step 4 did not render: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render_drawio.py" "<Subject>_Architecture.drawio" -f png` (exit 3 = draw.io absent -> skip and say so).
4. READ the PNG with the Read tool and check: **every caption carries the fields the label mode promises and no OCID**; when `layers` is on, the layers panel lists the expected layers with the expected visibility (open it with `Cmd+Shift+L` / `Ctrl+Shift+L`; a PNG export renders only the visible layers); all glyphs the same size; every caption legible, inside its container, not overlapping; edges run in gutters and cross no icon or caption; on-premises panel and DRG centred on the VCN stack; DRG outside every VCN, attachment boxes beside it; gateways centred on the VCN border; route table / security list badges on the subnets' top-right corners and NSG badges on the top-right of their icons, none of them drawn as captioned icons; no large empty areas. On the default outside canvas: the On-Premises, Internet and 3rd Party boxes are outside the region, the hybrid connection label sits in the gap between the On-Premises box and the region, the IGW and the NAT sit on the border facing the Internet box - the IGW directly above the NAT on the **right** border of the rightmost VCN column, the two side by side on the **top** border with their captions above the glyphs for every other column (`gateway_edge` / `gateways[].side` override both) - the Oracle Services Network is a band under the VCN stack, and subnet labels are two lines. With `locations: "nested"`: nothing but the title, notes and legend outside the region, and the OSN panel right of the VCNs. When a legend is drawn, it has one row per badge kind actually used.
5. Anything failing -> back to Step 2. At most 3 iterations.

## Step 6 - Report

- Output path and size (expect roughly 7-13 KB per icon; the 31-icon reference is 280 KB), page size (`pageWidth` x `pageHeight` in the file), counts (VCNs, subnets, icons, edges).
- Settings used (region, compartment, tenancy, profile, logo) and the gate line verbatim (`OK: no container overlaps ...`).
- **The resolved view**: the purpose, the detail level, the label mode, which layers were created and which are hidden, and the filter counts from `layout_info` (`N of M resources shown`, `K edge(s) dropped`, and what `--mode participating` pruned). Say how to toggle a layer in draw.io (`Cmd+Shift+L` / `Ctrl+Shift+L`, or *Extras > Edit Diagram*), and that hiding the base `Network` layer blanks the page.
- Assumptions: guessed icons and their fallbacks, inferred tiers, edges not backed by Terraform, resources left out.
- PNG path, or "render skipped: draw.io desktop not installed".
- Open the file in draw.io desktop; reopen if fonts look wrong (render cache).

## Diagram types

| Type | Model shape | Files |
|------|-------------|-------|
| Single VCN | one `vcns` entry, optional `hub`, services in `vcn.services` | one |
| Hub-and-spoke | `model.hub` (CPE) + `model.drgs` (one DRG, one attachment per spoke) + spoke VCN columns; regional services in the OSN panel | one while <= 3 VCNs and <= 40 icons |
| Multi-VCN overview | several VCNs, LPG pairs via `gateways[].peer`, edges between `vcn:<name>` endpoints | one |
| Service inventory | custom layout: `compartment` groups + `place_icons`, no subnets (SKILL.md section 7) | one |

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
| `purpose` | **answered in Step 1, never detected** | `--purpose` on every later run; the only remembered view choice |
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
| `WARNING: title ... its badges leave` | Widen the subnet (the recipe does this automatically) or shorten the subnet name / CIDR label |
| `WARNING: edge ... is estimated to cross` | Check the PNG; reorder items or change tier; custom: `route="direct"` or `label_pos` |
| `WARNING: content ... exceeds the page` | Call `fit_page()` last (custom layouts) |
| checker exit 2 | File missing, not XML, or the checker was moved away from `drawio_builder.py` |
| `label_fields: 'ocid' is never rendered in a caption` | Remove it; the OCID lives in `metadata` and the tooltip |
| `filter: '...' is not '[!]<dimension>[:<key>]<op><value>...'` | Use `=` (exact) or `~` (substring), e.g. `tag:Application=payments`, `!type=oci_core_nat_gateway` |
| A `tag:` filter matches nothing on a live tenancy | The search response carried no tags; the model has none. Re-run with `--mode all` and filter on `name` / `type` instead |
| The diagram is emptier than expected | `--mode participating` pruned it, or a `--filter` did; `layout_info["pruned"]` and `layout_info["filter"]` say how much. `--mode all` and an empty `--filter` restore everything |
| The layers panel is empty | `layers` defaults to `off`; pass `--layers auto` |
| Captions lost the shape line | 1.5.0 moved it to `metadata.shape`; `--label-mode minimal --label-fields display_name,shape` renders the exact 1.4 caption back |

## Prerequisites

- Python 3.9+ (standard library only); Pillow only for PNG/JPEG logos.
- draw.io desktop for PNG export and viewing (`/Applications/draw.io.app`, `drawio` on PATH or `DRAWIO_BIN`).
- OCI CLI (optional) for tenancy-name detection and the experimental `query_tenancy.py`; Terraform (optional) for `terraform show -json`.
- Icons ship in `${CLAUDE_PLUGIN_ROOT}/icons/` (159 SVGs); `OCI_SVG_DIR` overrides the location.
