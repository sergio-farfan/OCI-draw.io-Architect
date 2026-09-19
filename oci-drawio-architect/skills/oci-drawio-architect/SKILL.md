---
name: oci-drawio-architect
description: Generate deterministic draw.io diagrams of Oracle Cloud Infrastructure architectures (Redwood container styles, embedded OCI icons, auto-routed edges) from Terraform or a description. Use when the user says "draw.io OCI", "diagram this architecture", "drawio with OCI icons", "OCI architecture diagram" or "Terraform to draw.io".
---

# OCI draw.io Architect (plugin v1.5.0)

Diagrams are data: a MODEL dict laid out by `scripts/oci_layout.py` on top of `scripts/drawio_builder.py` (DrawioBuilder v1.5.0). The `/drawio-architect` command is the workflow; this skill holds the conventions, the schema and the API. Always `sys.path.insert(0, "<abs>/oci-drawio-architect/scripts")` and import from the plugin - never copy `drawio_builder.py` into a project (the copy loses the icon directory and drifts from the plugin).

## 1. Target look (the reference sample, `examples/generate_reference_layout.py`)

1. Title (`add_title`): bold `<Subject> - Architecture`, italic second line `<Region label> (<region>) - Compartment: <compartment>`; with a tenancy the first line is `<tenancy> - <Subject> - Architecture`. Optional logo top-right (148x39).
2. Region: solid Neutral-3 border, Neutral-1 fill, label = bare region id (`us-ashburn-1`) bold, top-left. Outside it sit the title, the notes, the legend and - under the default `locations: "outside"` canvas - the location boxes: On-Premises left of the region, Internet and 3rd Party Cloud stacked in a narrow column to its right (toolkit Location Canvas, deck slide 12). `locations: "nested"` restores the 1.3.0 canvas, where the on-premises panel is a child of the region and no Internet box is drawn.
3. Hub panel (`onprem` styling): 180 px wide (`LOC_W`), vertically centred on the VCN stack, one icon per row (pitch 200): CPE, FastConnect virtual circuit, RPC peer. Never the DRG. Its title is `hub.name` when set, else `On-premises` for `hub.kind: "onprem"` (the default) and `Remote region` for `hub.kind: "remote_region"` - the parser picks `remote_region` when the hub holds only an RPC peer. Under `locations: "outside"` it is a page-level sibling of the region, at least 70 px (`LOC_GAP_MIN`) to its left so the `Site-to-Site VPN` / `FastConnect` / `Remote Peering` label fits in the gap (deck slide 21), and a CPE / IPSec / virtual-circuit item straddles its region-facing border the way a gateway straddles a VCN border; under `locations: "nested"` it is a child of the region at `HUB_X = 15` with every item in a centred interior column.
4. DRG column (`drgs[]`): region-level DRG icon between the on-premises panel and the VCN columns, centred on the VCN stack; one rounded attachment box (100 px wide, 44 px tall minimum, Ivy border; taller when the display name needs more lines, which also widens the stacking pitch) per attachment beside it - VCN attachments on the side facing the VCNs, IPSec / FastConnect / RPC attachments on the side facing the on-premises panel - each linked to its target by an arrowhead-less `attachment` connector (`Site-to-Site VPN`, `FastConnect`, `Remote Peering`). `drg_style` `icon` (default) or `box` (dashed `DRG: <name>` group); `auto` picks `box` above 4 attachments.
5. VCN: label `VCN: <name> (<cidr>)`, Sienna dashed 2 px. Several VCNs are columns left to right, 45 px apart.
6. Subnet: two-line label - `<name> (Public)` / `<name> (Private)` on line 1, `<cidr>` on line 2 (toolkit slide 18's Subnet spec; the Public / Private token is a plugin convention and appears only when `public` is present and a bool) - Sienna dashed 1 px. `subnet_label: "inline"` restores the 1.3.0 single line `<name> (<cidr>)` + ` - public`. Row 1 holds lb -> app -> compute -> mgmt -> other subnets in traffic order, 2 icon columns each, wrapping to a new row past 1000 px; data-tier subnets are stretched under the rows (up to 5 columns).
7. Icon order inside a subnet: primary resource (LB, VM, DB) -> attached resources (block volume, certificate, WAF). Route tables, security lists and NSGs are never icons in a subnet (item 11).
8. Caption convention: `Role\nidentifier\nsize` - at most 3 lines of about 16 characters at 11 px, centred under a 75x95 slot; every glyph is fitted to 70x70 so all icons look the same size.
9. OCI Services panel (`services`): inside the VCN, right of row 1, only for VCN-resident services without a subnet. Regional services (Logging, Logging Analytics, Monitoring / Alarms, Notifications, Events, Connector Hub, IAM / Identity, Vault / KMS, Certificates, Object Storage, OCIR, AI services, Data Safe, Data Science, Analytics, Streaming, Queue, APM, DevOps, DNS zones, WAF policies; full list `oci_topology.REGIONAL_ICON_KEYS`) go to ONE region-level `Oracle Services Network` panel - a full-width band below the VCN stack under the default `outside` canvas, a right-hand column height-matched to the tallest VCN under `locations: "nested"` - fed by an `attachment` connector from the Service Gateway. `"regional": false` on an item keeps it in the VCN panel.
10. Gateways straddle the VCN border (glyph centre on the line, caption with an opaque region-fill background, parent = the VCN's container): they face what they connect to. Under `locations: "outside"` the IGW takes slot 0 and the NAT slot 1 of the border facing the Internet box - the **right** border for the **rightmost** VCN column, the **top** border for every other column (a left-hand column's right border faces the next VCN), where the slots are counted from the VCN's right edge inwards and the caption hangs above the glyph - and the Service Gateway the **bottom** border, facing the Oracle Services Network band drawn full width under the VCN stack; under `locations: "nested"` IGW and NAT are on the bottom border (pitch 180) and the SGW on the right border facing the OSN column. LPGs take the border facing their peer VCN (`peer` = peer LPG address or VCN name, set on both sides of a pair; unknown peer -> bottom) linked by a `Local Peering` attachment connector. Within a side the order is always `igw, nat, sgw, lpg` then by address, never model order. `gateway_edge: "top"` moves the Internet-facing pair to the top border with the caption above the glyph (deck slide 31), `gateway_edge: "bottom"` restores the 1.3.0 side choice, and `gateways[].side` overrides one gateway.
11. Security constructs are badges: a subnet's route table and security lists are half-size (22 px) caption-less icons straddling the subnet's top-right corner (route table centred on the corner, security lists one badge to its left; toolkit slide 18 uses the icons at half size as labels of the subnet box); an NSG is a 22 px shield badge in the top-right of the protected resource's 75x95 slot. Names go to the tooltip and metadata. Model fields: `subnet.route_table`, `subnet.security_lists`, `item.nsgs`.
12. Edges: `data` solid Bark open arrow (label = protocol / port); `control` dashed Bark open arrow (management / administrative); `association` dotted, no arrowhead (dependency, configuration relationship); `attachment` thin solid, no arrowhead (structural: DRG attachments, LPG pairs, SGW -> OSN); `analytics` solid Sienna and `datalake` dashed purple remain. Routed automatically through the gutters.
13. No legend by default (`legend=True` only on request or with 3+ edge kinds); when it is drawn it also explains the badges actually present (route table, security list, NSG, DRG route table) and names the active attachment form. `notes` text appears right of the title only when set.
14. Page = content + 20 px margin rounded up to 10 (`fit_page`), white background, `default` style profile, Oracle Sans font stack.
15. Compartments are off by default. `show_compartments: true` wraps each compartment's VCNs in a `compartment` container (dotted Sienna, bold Sienna label top-left) laid out in the column order of its first VCN, nested through `compartments[].parent`, and - with a `tenancy_name` - wraps the whole row in one `Tenancy: <name> (Root Compartment)` container. The DRG column, the on-premises panel and the OSN band stay direct children of the region: a DRG may serve VCNs in different compartments.
16. Grouping boxes are opt-in (`vcn.groups[]`, `subnet.groups[]`), never emitted by default. `oke_cluster` is a dashed Sienna box inside a subnet around a cluster and its node pools, title top-centre (deck slide 32); `tier` and `user_group` are Oracle's "Other Grouping" boxes (slide 18). A box is a real container: its members are re-parented into it and an edge may terminate on it by its `key`.

## 2. Model schema (`oci_layout.py` docstring)

Every key is optional except `subject` and `vcns` (or `hub`). JSON-serialisable.

```python
MODEL = {
  "subject": "Spoke-VCN-D", "region": "us-ashburn-1", "region_label": "Ashburn",
  "compartment": "Spoke-VCN-D", "tenancy_name": None,
  "drg_style": "auto",                # auto | icon | box (CLI --drg-style overrides)
  "locations": "outside",             # outside (default) | nested - where the location boxes go
  "gateway_edge": "auto",             # auto | internet | top | bottom - Internet-facing gateway border
  "subnet_label": "twoline",          # twoline (default) | inline | name (no CIDR)
  "purpose": None,                    # network|dataflow|security|inventory|dependency|ha - sets the defaults below
  "detail": "network",                # executive | application | network (default) | engineering
  "label_mode": "network",            # minimal | network (default) | detailed - caption field list
  "label_fields": None,               # explicit field list (see section 4); wins over label_mode
  "label_tag_keys": [],               # which tag keys the "tags" caption field renders, in order
  "layers": "off",                    # off (default) | auto | [layer name, ...] - real draw.io layers
  "hidden_layers": [],                # layers created with visible="0"
  "filter": {},                       # {"include": [expr], "exclude": [expr], "keep_empty": False,
                                      #  "report": {...}} - the front ends add "report" with what THEY cut
  "mode": "all",                      # all (default) | participating - keep only what takes part
  "pruned": None,                     # {"items": n, "services": n} written by a front end that pruned
  "global_services": "osn",           # osn (default) | bucket - IAM/Policies/Audit/DNS in a tenancy box
  "show_edges": True,                 # False draws no model connectors (the inventory purpose)
  "attachment_style": "solid",        # solid (default) | dotted - DRG attachment connectors
  "show_compartments": False,         # draw compartment containers around the VCNs
  "compartments": ["Network"],        # names, or [{"name", "parent", "vcns"}] for explicit nesting
  "internet": {"name": "Internet", "items": []},        # synthesised by the parser when a VCN has an IGW
  "third_party": [],                  # [{"name": "3rd Party Cloud", "items": [...]}] - authored only
  "hub": {"kind": "onprem",           # onprem (default) | remote_region - selects the default title
          "name": "On-premises",      # optional override; on-prem side only: CPE, IPSec, VC, RPC peer
          "items": [{"icon": "cpe", "label": "Corp VPN\n(10.0.0.0/8)", "address": "cpe"}],
          "link_label": None},
  "drgs": [{"name": "drg", "address": "drg", "label": "Dynamic Routing\nGateway (DRG)",
            "route_table": ["drg-rt-vcn", "drg-rt-other"],   # str | {"name","address"} | a list; 2 badges max
            "attachments": [{"type": "vcn", "vcn": "Spoke-VCN-D", "address": "drg-att-spoke",
                             "label": "VCN attachment\nSpoke-VCN-D"},
                            {"type": "ipsec", "target": "cpe", "address": "vpn@drg", "label": "vpn-hq"}]}],
  "vcns": [{
     "name": "Spoke-VCN-D", "cidr": "10.0.0.0/16", "compartment": "Network",
     "groups": [{"type": "tier", "label": "Application Tier", "subnets": ["sn-priv-app"], "key": "tier-app"}],
     "subnets": [{"name": "sn-priv-lb", "cidr": "10.0.0.0/24", "tier": "lb", "public": False,
                  "items": [{"icon": "load_balancer", "label": "Load Balancer\n10.0.0.23",
                             "address": "lb", "metadata": {"ocid": "...", "private_ip": "10.0.0.23",
                             "public_ip": "203.0.113.10", "fqdn": "lb.sub.oraclevcn.com",
                             "ports": "HTTPS/443", "compartment": "app-prod",
                             "availability_domain": "Uocm:PHX-AD-1", "fault_domain": "FAULT-DOMAIN-2",
                             "lifecycle_state": "AVAILABLE"},
                             "tooltip": "...", "nsgs": ["nsg-lb"],
                             "tags": {"freeform": {"Environment": "prod"},
                                      "defined": {"Operations": {"CostCenter": "cc-1"}}}}],
                  "groups": [{"type": "oke_cluster", "label": "Container Engine for Kubernetes Cluster",
                              "items": ["oke-main", "np-a"], "key": "oke-main-box"}],
                  "route_table": "rt-lb", "security_lists": ["sl-lb"]}],
     "services": [{"icon": "logging", "label": "Logging", "address": "logs", "regional": True}],
     "services_label": "OCI Services",
     "gateways": [{"icon": "service_gateway", "type": "sgw", "label": "Service\nGateway", "address": "sgw",
                   "side": None},      # top | right | bottom | left - overrides gateway_edge
                  {"icon": "remote_peering_gateway", "type": "lpg", "label": "LPG", "address": "lpg-a",
                   "peer": "lpg-b"}]
  }],
  "services": [],                                 # more regional services; join the OSN panel
  "edges": [{"source": "lb", "target": "app-vm", "label": "3000 / 8000", "kind": "data",
             "discovery": "association"}],         # association|config|reachability|tag|observed|user|heuristic
  "notes": None,                                  # free text placed right of the title
}
```

Rules:
1. `tier` in `lb, app, compute, mgmt, other` (row 1) or `data` (stretched row). Missing tier is inferred from the name: lb/web/dmz/pub -> lb; app/api/worker -> app; oke/node/compute -> compute; mgmt/bastion/ops -> mgmt; db/data/database -> data; else other.
2. Item keys: `icon` (catalog key), `label` (caption, `\n` = line break, HTML-escaped), `address` (unique id, also the cell id), optional `metadata` (dict of str), `tooltip`, `link`. Subnets and VCNs also accept `metadata`/`tooltip`.
3. Edge `kind`: `data`, `control`/`management`, `association`, `attachment`, `analytics`, `datalake`; or pass `dashed`/`color` directly (an explicit `dashed` keeps the profile look).
4. Edge endpoints: an item `address`; `vcn:<name>`, `subnet:<name>`, `services`, `services:<vcn>`, `hub`, `region`; or a unique caption first line. Ambiguous or unknown endpoints raise `ValueError`.
5. Escape nothing yourself: labels are plain text, `\n` becomes `<br>`.
6. DRGs: never inside `hub.items` or `vcn.gateways`; `drgs[].attachments[].type` in `vcn | ipsec | virtual_circuit | rpc | loopback`, `vcn` = VCN name, `target` = hub item address. Schema-1 models are migrated with a `WARNING: legacy model:` line - move the DRG to `drgs` to silence it.
7. Edge endpoints also accept `drg:<name>`, a DRG address, an attachment address and `osn`.
8. Security constructs: `subnet.route_table` (str or `{"name", "address"}`), `subnet.security_lists` and `item.nsgs` (lists of the same forms) draw badges; never add `route_table`, `security_list` or `nsg` items to a subnet. An entry with an `address` can be an edge endpoint (`{"source": "rt-private", "target": "sgw"}`); when several subnets or items share one address, the **first** badge drawn is the one edges resolve to - for subnets that is the layout's tier order (lb, app, compute, mgmt, other, then data), not the model's list order.
9. View keys are authored, never parsed: `locations`, `gateway_edge`, `subnet_label`, `attachment_style` and `show_compartments` are choices about the drawing, not facts about the Terraform, so `parse_terraform.py` never sets them. Every one of them has a `build_diagram(...)` keyword and an `oci_layout.py` flag of the same name that overrides the model.
10. Compartments: `compartments[]` accepts plain names (what the parser emits) and objects `{"name", "parent", "vcns"}`, mixed in one list; an object wins over a string of the same name. Membership is `compartments[].vcns` first, then `vcn.compartment`; a VCN naming no known compartment is drawn beside the boxes, not in one. An unknown `parent` or a cycle raises `ValueError`. Nothing is drawn unless `show_compartments` is true.
11. Grouping boxes: `vcn.groups[]` bands whole subnet rows (`subnets`), `subnet.groups[]` encloses items (`items`); `type` in `oke_cluster | tier | user_group | other`, optional `key` (else `group:<parent>:<type>:<slug>`). Members must belong to the same container and two entries in one container may not interleave - both raise `ValueError` from `build_diagram`. The box is a container: its members are re-parented into it, and its `key` is a valid edge endpoint (deck slide 32 connects the load balancer to the OKE box, not to an icon inside it).
12. View keys added in v1.5.0 - `purpose`, `detail`, `label_mode`, `label_fields`, `label_tag_keys`, `layers`, `hidden_layers`, `filter`, `mode`, `global_services`, `show_edges` - are resolved exactly like the v1.4.0 view keys of rule 9 (CLI flag / `build_diagram` kwarg beats the model key), with two preset layers of their own beneath the model; see section 4 for the full order, the purpose table, the label-field vocabulary and the layer table.
13. `item["tags"]` (and the same key on a subnet or VCN): `{"freeform": {k: v}, "defined": {namespace: {k: v}}}`, both optional; the `tags` caption field renders `label_tag_keys` from either bucket. New `metadata` keys the parser and the live-tenancy reader write: `private_ip`, `public_ip`, `fqdn`, `hostname_label`, `lifecycle_state`, `compartment`, `ports`, plus the already-existing `shape` (no longer folded into `label`) and `availability_domain`/`fault_domain`. `edges[].discovery` (`association | config | reachability | tag | observed | user | heuristic`) replaces the old `inferred` boolean as the source of truth; `inferred` is still written (`True` only for `heuristic`) for anything that still reads it. An OCID (`metadata["ocid"]` / an `address` from a live tenancy) is never rendered in a caption, in any label mode - it stays in the tooltip and the metadata.

## 3. Layout recipe (`build_diagram`)

`build_diagram(model, style_profile="default", legend=False, logo=None, page_name=None, title=True, max_row_w=MAX_ROW_W, drg_style=None, locations=None, gateway_edge=None, subnet_label=None, attachment_style=None, show_compartments=None) -> DrawioBuilder` and `write_diagram(model, out_path, strict=False, render_fmt=None, **opts) -> Path` (build + `validate` + `write`, optional draw.io export; `**opts` are the `build_diagram` keywords). Each of the five view keywords defaults to `None` = take the model's value, which itself defaults to the value in section 2. CLI: `python3 oci_layout.py model.json -o out.drawio [--profile default|official|v1.0] [--legend] [--logo FILE] [--strict] [--render png|svg|pdf] [--drg-style auto|icon|box] [--locations outside|nested] [--gateway-edge auto|internet|top|bottom] [--subnet-label twoline|inline] [--attachment-style solid|dotted] [--show-compartments]`.

Order of operations: migrate legacy model -> **resolve the view** (`_view_ctx` -> `oci_view.resolve_view`, section 4) -> **filter and prune the model** (`oci_view.filter_model`, section 4) -> classify topology -> title -> region -> compartment / tenancy containers (only with `show_compartments`) -> for each VCN: subnet rows (each subnet: icons with their NSG badges -> `subnet.groups[]` boxes around their members -> `fit_to_children(subnet)` -> route table / security list badges on the subnet's top-right corner) -> VCN-resident services panel -> data subnets -> `vcn.groups[]` bands -> `fit_to_children(vcn)` -> border gateways (children of the VCN's container) -> optional region-level OCI Services panel -> Oracle Services Network panel (right column under `locations: "nested"`, full-width band below the VCN stack under `outside`) -> on-premises panel (region child only under `nested`) -> DRG column with its route-table badge strip -> `fit_to_children(region)` -> **page-level location pass** (translate the region right, emit the On-Premises / Internet / 3rd Party sibling boxes, then re-centre the DRG clusters and the on-premises items on the VCN stack) -> **global-services bucket** (only with `global_services: "bucket"`) -> SGW -> OSN connectors -> attachment connectors -> model edges (each on its layer) -> optional legend -> `fit_page()` -> **layer pass** (assign the enabled layers over the base layer `Network`, re-parent badges onto them; edges were already parented to their layer when added). Nothing inside the region is recomputed by the location pass: the region is *translated* with `resize(rid, x=...)` and every descendant moves with it. Every view key is resolved in one fixed order, most specific first: **explicit CLI flag -> `build_diagram` kwarg -> explicit model key -> the `detail` preset -> the `purpose` preset -> the `detail` preset the purpose selected -> hard default** - so a generating agent can predict which setting wins when several are given at once.

| Constant | Value | Constant | Value |
|----------|-------|----------|-------|
| `ICON_W` x `ICON_H` (slot) | 75 x 95 | `GLYPH_W` x `GLYPH_H` | 70 x 70 |
| `LABEL_W` x `LABEL_H` (min) | 105 x 45 | `LABEL_FONT_SIZE` / `LABEL_LINE_H` | 11 / 14 |
| `ICON_FOOTPRINT_H` | 142 | `MAX_LABEL_LINES` | 3 |
| `PAD` / `GAP` | 20 / 20 | `ROW1_Y` | 50 |
| `COL_W` / `ROW_H` (icon pitch) | 130 / 160 | `TITLE_BOX` / `REGION_XY` | (20, 8, 600, 55) / (20, 75) |
| `VCN_Y` / `VCN_BOTTOM_PAD` | 40 / 40 | `H_GAP` / `V_GAP` (subnets) | 20 / 40 |
| `PANEL_GAP` / `GW_PITCH` | 40 / 180 | `SUBNET_EXTRA_W` / `SUBNET_BOTTOM_PAD` | 50 / 28 |
| `HUB_X` / `HUB_W` / `HUB_GAP` | 15 / 180 / 45 | `HUB_ICON_Y0` / `HUB_PITCH` | 70 / 200 |
| `VCN_COLUMN_GAP` | 45 | `MAX_ROW_W` | 1000 |
| `DRG_GAP` | 45 | `ATT_W` x `ATT_H` (min) | 100 x 44 |
| `ATT_GAP` / `ATT_PITCH` / `ATT_VGAP` | 15 / 56 / 12 | `DRG_CLUSTER_GAP` | 40 |
| `OSN_GAP` | 45 | `GW_STRADDLE` / `GW_SIDE_DX` | 40 / 38 |
| `SIDE_GW_Y0` / `LEFT_GW_Y0` / `SIDE_GW_PITCH` | 50 / 50 / 160 | `VCN_BOTTOM_PAD_GW` / `VCN_SIDE_PAD` / `SIDE_INSET` | 60 / 60 / 40 |
| `VCN_COLUMN_GAP_GW` | 110 | | |
| `BADGE_SIZE` (badge side) | 22 | `BADGE_GAP` (route table -> security list badge) | 4 |
| `BADGE_RESERVE` (title width the corner badges reserve) | 52 | `LEGEND_BADGE_SIZE` (badge glyph in a legend row) | 16 |
| `LOC_W` (location box width) | 180 | `LOC_GAP_MIN` / `LOC_GAP_RIGHT` / `LOC_STACK_GAP` | 70 / 10 / 10 |
| `LOC_MIN_H` | 160 | `INTERNET_SPLIT` (Internet share of the right column) | 0.45 |
| `OSN_BAND_GAP` (VCN stack -> OSN band) | 45 | `VCN_TOP_PAD_GW` / `TOP_GW_X0` | 60 / 50 |
| `CMP_PAD` / `CMP_TITLE_H` / `CMP_GAP` | 30 / 40 / 40 | `TEN_PAD` / `TEN_TITLE_H` | 25 / 40 |
| `GRP_PAD` / `GRP_TITLE_H` | 15 / 30 | `DRG_RT_GAP` / `DRG_RT_MAX` | 6 / 2 |

## 4. Views: purposes, label fields and layers (`oci_view.py`)

`oci_view.py` is the one place every view key is resolved (`resolve_view`), a caption is rendered
(`render_caption`) and the model is filtered (`filter_model`). It imports nothing from the plugin,
mirroring `oci_topology.py`. The resolution order of section 3 - CLI flag > `build_diagram` kwarg >
explicit model key > the `detail` preset > the `purpose` preset > the `detail` preset the purpose
selected > hard default - is what lets a generating agent pass `--purpose network` and still
override one field (say `--label-mode detailed`) without fighting the preset.

### 4.1 Purpose presets (`PURPOSES`)

A purpose is a named composition asked once, in the command's Step 1, with the six titles verbatim
from the team's diagram guidelines; `--purpose` / `purpose` / `build_diagram(purpose=)` produce the
identical result to setting the individual keys by hand.

| Purpose | Guideline title | `detail` | Label fields | Layers: visible / hidden | `mode` | Other | Pick it when |
|---|---|---|---|---|---|---|---|
| `network` | Network topology | `network` | `network` mode (name, private IP, port/protocol) | routes, security, dataflow, management / - | `all` | today's default look | the ask is "show me the architecture" with no other qualifier |
| `dataflow` | Application / data flow | `application` | `display_name, port_protocol` | dataflow, management / routes, security | `participating` | edge labels on | the ask is about what talks to what, not the network plumbing |
| `security` | Security architecture | `network` | `display_name, private_ip` | security, routes, iam, management / dataflow | `all` | `global_services: "bucket"`, `legend: true` | the ask centres on NSGs, security lists, IAM or the audit surface |
| `inventory` | Resource / inventory view | `executive` | `display_name, resource_type, compartment` | iam / - | `all` | `show_edges: false`, `show_compartments: true`, `global_services: "bucket"` | the ask is "what do we have and where", not how it connects |
| `dependency` | Dependency / relationship view | `application` | `display_name` | dataflow, management, associations / routes, security | `participating` | `--annotate-discovery` on | the ask is about relationships and their provenance, e.g. before a change |
| `ha` | Deployment / high-availability architecture | `network` | `display_name, ad_fd` | routes / security | `all` | AD/FD as caption fields only - AD/FD **containers** are out of scope | the ask is about resiliency placement, not full network detail |

No purpose sets a `filter`: a filter is about *this* tenancy, a purpose is about *this* diagram. A
purpose only ever sets **defaults** - any explicit key, CLI flag or `detail` override still wins.

**A purpose's `hidden_layers` is a no-op unless `--layers auto` (or an explicit layer list) is also
given.** Layers default to `"off"` (A5) - the base `Network` layer plus whatever content the gates
draw, no cell-layer split at all - so with layers off a "hidden" layer's content is simply **not
drawn**, not emitted-and-hidden. `--purpose security` alone draws the security purpose's content
with layers off; `--purpose security --layers auto` is what actually produces a toggleable
`dataflow` layer that starts hidden.

### 4.2 Label-field vocabulary (`LABEL_FIELDS`, section 2 rule 12)

| Field | Renders as | Model source |
|---|---|---|
| `display_name` | line 1, the item's authored `label` verbatim (V5 dedupe against later fields) | `item["label"]` |
| `resource_type` | `Instance` - the human default from `RESOURCE_ICONS[type][1]`; for a gateway, its human short-type name (`Service gateway`, not `Sgw`) | `item["type"]` |
| `shape` | `VM.Standard.E5.Flex` - the line the 1.4.0 parser used to append to the caption itself | `metadata["shape"]` |
| `private_ip` | `10.0.2.47` | `metadata["private_ip"]`, else `metadata["ip_address"]` |
| `public_ip` | `203.0.113.10` | `metadata["public_ip"]` |
| `cidr` | `10.0.2.0/24` | containers only (subnet / VCN title, not an icon caption) |
| `fqdn` | `broker.sub01...` (elided to the caption width) | `metadata["fqdn"]` |
| `port_protocol` | `HTTPS/443` | `metadata["ports"]` |
| `compartment` | `Compartment: app-prod` | `metadata["compartment"]` |
| `ad_fd` | `AD-1 / FD-2` - reduced to the trailing `AD-n` / `FD-n` | `metadata["availability_domain"]`, `metadata["fault_domain"]` |
| `lifecycle` | `AVAILABLE` (only when it is not the healthy state) | `metadata["lifecycle_state"]` |
| `tags` | `Environment=prod` per key in `label_tag_keys`, in that order | `item["tags"]["freeform"]` / `["defined"][ns]` |
| `ocid` | **never rendered in a caption, in any mode** - tooltip and metadata only | `item["address"]` under `query_tenancy.py` |

`label_mode` presets: `minimal` = `[display_name]`; `network` (default) = `[display_name,
private_ip, port_protocol]`; `detailed` = `[display_name, private_ip, ad_fd, compartment]`.
`label_fields` overrides the preset outright; an unknown field name raises `ValueError`. A field
with no value is skipped silently, and a field whose text already occurs in the caption rendered so
far is skipped too (V5) - a hand-written `"Load Balancer\n10.0.0.23"` caption still renders as
written in every mode. The exact 1.4.0 caption of a **parsed** model comes back with
`label_mode="minimal", label_fields=["display_name", "shape"]` (`shape` is a field of its own).

### 4.3 View layers (`VIEW_LAYERS`, section 1 item 2 revisited)

A draw.io layer is a child of the root and a cell belongs to the layer of its top-level ancestor
(`gotchas.md` #24), so only six of the team's twelve guideline layers can be real cell layers; the
rest are the base layer, a label field (4.2) or build-time content gated by `detail` / `filter` /
`mode`.

| Guideline layer | Mechanism | What it is in 1.5.0 | Default visibility |
|---|---|---|---|
| Network | base layer | Cell `"1"`, renamed `Network`: region, location boxes, every container and icon, gateways, the DRG cluster and attachment boxes, attachment connectors, title, notes, legend | visible (hiding it blanks the page) |
| Application resources | build-time | Workload icons, children of their subnet; gated by `detail`, `filter` and `mode` | - |
| Routes | cell layer `routes` | Subnet route-table badges, DRG route-table badges | visible |
| Security | cell layer `security` | Security-list badges, NSG badges (WAF / bastion / firewall stay build-time icons) | visible |
| IAM | cell layer `iam` | The global-services bucket (4.4) and its icons; not created when `global_services: "osn"` | visible |
| Observability | build-time | Logging / Monitoring / Notifications icons, children of the OSN panel | - |
| Data flows | cell layer `dataflow` | Edges of kind `data`, `analytics`, `datalake` | visible |
| Management paths | cell layer `management` | Edges of kind `control` | visible |
| Associations (plugin addition beyond the guidelines' twelve) | cell layer `associations` | Edges of kind `association`; `attachment` edges stay on the base layer - they are structure | visible |
| Compartments | build-time | A compartment container holds the VCNs, so it cannot move to another layer; `show_compartments` is the toggle | off |
| AD / FD | out of scope | No AD / FD containers exist in this release | - |
| Resource IPs | label field | `private_ip` / `public_ip` in `label_fields`; `--layers ips` is accepted and rewritten to that field, with a note on stderr | per label mode |
| Ports and protocols | label field | `port_protocol` in `label_fields`, plus the connector labels, which travel with the edge's own layer | per label mode |

Fixed z-order when layers are enabled, all above the base layer: `routes, security, iam, dataflow,
management, associations`. `layers: "auto"` turns on every layer a resource actually populates;
an explicit `[layer, ...]` list turns on exactly those; a layer nothing populates is never created,
even if named. `hidden_layers` marks a created layer `visible="0"` without removing its content.

Under `auto` the `detail` level chooses which of those layers start **visible** - `executive`: data
flows; `application`: data flows and management paths; `network` and `engineering`: all of them -
and the rest are created hidden. That is why `--detail application --layers auto` still **emits**
the route-table and security badges and lets the reader switch them on, while the same level with
layers off drops those cells altogether. A `purpose` names the layer set itself, and then its own
`hidden_layers` carries the visibility.

### 4.4 Global-services bucket (`global_services`)

`"osn"` (default) keeps IAM, Policies, Audit and public DNS in the regional Oracle Services Network
panel, as Oracle's own deck slides 29-31 draw them (`oracle-styles.md` conflict **V7**). `"bucket"`
draws them instead in a `tenancy`-styled container below the region (cell id `global`), with the
compartment list (`global-compartments`) when compartment containers are not drawn - the layout the
team's diagram guidelines ask for. The bucket is page-level, so its icons sit on the `iam` layer
when layers are on; no connector is ever drawn to it, because a global service is not reached
through the regional network path.

**The `dns` icon means PUBLIC DNS unless the item says otherwise.** Classification reads
`services[].scope` (`global` | `regional` | `vcn`) first, then the legacy `regional` boolean, then
the VCN-resident type list (`oci_dns_resolver`), then the icon tables - so a **private** DNS zone
must carry `"scope": "regional"` (or `"vcn"`), or the bucket view presents a VCN-scoped zone as a
tenancy-wide service. `parse_terraform.py` and `query_tenancy.py` write that scope themselves: an
`oci_dns_zone` whose `scope` is `PRIVATE` or which names a `view_id` is `regional`, every other
zone is `global`. Nothing moves under the default `"osn"`, where a global service is drawn in the
Oracle Services Network panel like any other regional one.

## 5. Icon selection

1. Keys are either a short alias (206, `drawio_builder.ICON_ALIASES`) or an SVG file stem (159, e.g. `compute_virtual_machine_vm`); both forms are listed in `references/icon-catalog.md`. Unknown keys raise `Unknown icon_key ... Did you mean ...` - use the suggestion, never invent a key.
2. Fallback: the closest catalog key by service family (compute -> `vm`, database -> `generic_database`, networking -> `vcn`, storage -> `block_storage`, anything else -> `cloud`) and say so in the report.
3. No dedicated glyph exists for Generative AI (`ai`; `generative_ai` is an alias of the same glyph), OCI Cache / Redis (`nosql`), VPN / IPSec (`cpe`), FastConnect (`backbone`), LPG (`rpg`), Network Load Balancer (`load_balancer`), PostgreSQL (`generic_database`), Container Instances (`container`), Dedicated VM Host (`bare_metal`).
4. To search: `python3 -c "import sys; sys.path.insert(0,'<abs>/scripts'); import drawio_builder as d; print(sorted(k for k in d.ICON_MAP if 'gateway' in k))"`.

| Terraform resource | Icon key | Model placement |
|--------------------|----------|-----------------|
| `oci_core_vcn` / `oci_core_subnet` | (containers) | `vcns[]` / `subnets[]` |
| `oci_core_internet_gateway` / `_nat_gateway` / `_service_gateway` | `internet_gateway` / `nat_gateway` / `service_gateway` | `gateways` |
| `oci_core_drg` | `drg` | `drgs[]` |
| `oci_core_drg_attachment` | (box) | `drgs[].attachments` (`type: vcn`) |
| `oci_core_local_peering_gateway` | `rpg` | `gateways` (`type: lpg`, `peer` on both sides of the pair) |
| `oci_core_remote_peering_connection` | `rpg` | `hub.items` + `drgs[].attachments` (`type: rpc`) |
| `oci_core_cpe` / `oci_core_ipsec` / `oci_core_virtual_circuit` | `cpe` / (attachment `ipsec`) / `cpe` | `hub.items` / `drgs[].attachments` / `hub.items` + attachment `virtual_circuit` (private circuits only: a `PUBLIC` circuit peers with Oracle public services and gets no DRG attachment) |
| `oci_network_firewall_network_firewall` | `firewall` | subnet (hub VCN) |
| `oci_core_network_security_group` | `nsg` (badge) | `items[].nsgs` of the protected resources - never an item |
| `oci_core_security_list` / `oci_core_route_table` (and the `oci_core_default_*` pair) | `security_list` / `route_table` (badges) | `subnets[].security_lists` / `subnets[].route_table`; rule tables via `add_table` on page 2 |
| `oci_load_balancer_load_balancer` / `oci_network_load_balancer_*` | `load_balancer` (`flexible_lb`) | lb subnet |
| `oci_apigateway_gateway` / `oci_waf_web_app_firewall` / `oci_certificates_management_certificate` | `api_gateway` / `waf` / `certificates` | lb subnet |
| `oci_core_instance` (shape `BM.*` -> `bare_metal`) | `vm` | app / compute / mgmt subnet |
| `oci_core_instance_pool` / `oci_autoscaling_auto_scaling_configuration` | `instance_pool` / `autoscaling` | app subnet |
| `oci_containerengine_cluster` / `_node_pool` | `oke` / `vm` | compute subnet; a cluster and the node pools in the same subnet also emit one `subnet.groups[]` entry of type `oke_cluster` (deck slide 32) |
| `oci_core_drg_route_table` | `route_table` (badge) | `drgs[].route_table` - a strip of up to 2 badges under the DRG glyph |
| `oci_container_instances_container_instance` / `oci_functions_*` | `container` / `functions` | app subnet or `services` |
| `oci_bastion_bastion` | `bastion` | mgmt subnet |
| `oci_database_autonomous_database` (`db_workload` DW -> `adw`, OLTP -> `atp`) | `autonomous_db` | data subnet |
| `oci_database_db_system` / `oci_database_cloud_exadata_infrastructure` | `db_system` / `exadata` | data subnet |
| `oci_mysql_mysql_db_system` / `oci_psql_db_system` / `oci_nosql_table` | `mysql` / `generic_database` / `nosql` | data subnet |
| `oci_redis_redis_cluster` / `oci_opensearch_opensearch_cluster` | `nosql` / `opensearch` | data subnet |
| `oci_core_volume` / `oci_core_boot_volume` / `oci_file_storage_*` | `block_storage` / `block_storage` / `file_storage` | next to the VM |
| `oci_objectstorage_bucket` | `buckets` | `services` (`regional: true`, OSN panel) |
| `oci_kms_vault` / `oci_vault_secret` / `oci_kms_key` | `vault` / `vault` / `kms` | `services` (`regional: true`, OSN panel) |
| `oci_logging_log_group` / `oci_monitoring_alarm` / `oci_ons_notification_topic` | `logging` / `alarms` / `notifications` | `services` (`regional: true`, OSN panel) |
| `oci_apm_apm_domain` / `oci_streaming_stream` / `oci_queue_queue` / `oci_dns_*` | `apm` / `streaming` / `queuing` / `dns` | `services` (`regional: true`, OSN panel) |
| `oci_artifacts_container_repository` / `oci_devops_project` | `container_registry` / `devops` | `services` (`regional: true`, OSN panel) |
| `oci_sch_service_connector` / `oci_events_rule` / `oci_resourcemanager_stack` | `service_connector_hub` / `events` / `resource_manager` | `services` (`regional: true`, OSN panel) |
| `oci_datascience_*` / `oci_generative_ai_*` / `oci_analytics_analytics_instance` | `data_science` / `ai` / `analytics` | data subnet or `services` (`regional: true`, OSN panel) |
| `oci_dataintegration_workspace` / `oci_dataflow_application` / `oci_datacatalog_catalog` | `data_integration` / `data_flow` / `data_catalog` | `services` (`regional: true`, OSN panel) |
| `oci_integration_integration_instance` / `oci_goldengate_deployment` | `oic` / `goldengate` | `services` |
| `oci_identity_compartment` / `_policy` / `_dynamic_group` / `_user` | (container `compartment`) / `policy` / `user_group` / `user` | `compartments[]` + `vcn.compartment`; drawn as containers only with `show_compartments` |
| `oci_identity_group` | - | **not mapped.** An IAM group is a tenancy principal, not a location; the `user_group` grouping box stays available to hand-written models, and Oracle's samples draw users as icons inside On-Premises or Internet |
| (no resource) | (container `tier`) | `vcn.groups[]` / `subnet.groups[]` of type `tier` are authored only - `infer_tier` keeps feeding `subnet.tier` for row order and never emits a box |
| `oci_cloud_guard_*` / `oci_data_safe_*` / `oci_vulnerability_scanning_*` | `cloud_guard` / `data_safe` / `vuln_scanning` | `services` (`regional: true`, OSN panel) |
| `oci_core_public_ip` / `oci_core_vtap` / `oci_*_private_endpoint` | `ip_pools` / `vtap` / `private_endpoint` | lb subnet / mgmt / data |

## 6. Style rules

| Profile | Use when | Differences |
|---------|----------|-------------|
| `default` | always, unless asked otherwise | reference look: 12 px container labels, 11 px subnet labels, 1.5 px rounded edges, dash pattern `6 3`, dashed edges without arrowheads |
| `official` | the customer wants strict OCI Architecture Diagram Toolkit v24.2 fidelity | 12 px everywhere, 1 px square edges, 10.5 px edge labels, dashed edges keep the open arrow, AD/FD arcs 8/7 |
| `v1.0` (`sample` alias) | regenerating diagrams made with plugin v1.0.x without a visual diff | 13 px VCN label, `spacingLeft=3` |

1. Fonts: `Oracle Sans,Arial,Helvetica,sans-serif` for everything (title 18 px bold + italic line, captions 11 px, edge labels 12 px). Override with `DrawioBuilder(font_family=...)` only on request.
2. Colours come from `drawio_builder.COLORS`; full table and every container style string in `references/oracle-styles.md`. The ones you will meet: Bark `#312D2A` (text, edges, services border), Sienna `#AE562C` (VCN/subnet/compartment borders, analytics edges), Neutral 3 `#9E9892` (region/tenancy/AD/FD borders), Neutral 1 `#F5F4F2` (region/onprem fill), Rose `#A36472` (Oracle Services Network), `#7B61FF` (datalake edges, project extension).
3. Never restyle cells by hand (`style_extra` is for one-off tweaks such as `fontStyle=2`); container looks are fixed per `group_type`.

## 7. Custom layouts with DrawioBuilder

Use only when the recipe cannot express the architecture (availability/fault domains, nested compartments, several regions, third-party cloud, tables, extra pages). Order: containers with provisional sizes -> `place_icons` -> `fit_to_children` innermost first -> position siblings from `bbox()` + `GAP` -> edges -> `fit_page` -> `validate` gate -> `write`.

| Method (exact signature) | Notes |
|--------------------------|-------|
| `DrawioBuilder(page_name="Architecture", width=1600, height=1100, style_profile="default", font_family=None)` | first page is created |
| `add_page(name, width=1600, height=1100) -> int`; `use_page(index_or_name) -> int`; `add_layer(name, visible=True, key=None) -> str` | edges cannot cross pages |
| `add_group(label, x, y, w, h, parent="1", group_type="region", metadata=None, tooltip=None, label_position=None, style_extra="", key=None, link=None, raw_html=False) -> str` | types: region, tenancy, availability_domain, fault_domain, compartment, vcn, subnet, services, oracle_services_network, onprem (`hub` alias), other, metro_or_realm, third_party_cloud, internet, drg; `label_position` "left"/"center" |
| `add_icon(label, icon_key, x, y, parent="1", w=None, h=None, metadata=None, tooltip=None, key=None, label_w=None, label_h=None, raw_html=False, font_size=None, link=None, label_fill=None) -> str` | (x, y) = top-left of the 75x95 slot; caption auto-height; `raw_html=True` passes markup unescaped; `label_fill` gives the caption an opaque background for icons straddling a dashed border |
| `add_box(label, x, y, w, h, parent="1", key=None, style_extra="", metadata=None, tooltip=None) -> str` | small labelled rounded rectangle (DRG attachment marker, note); a routing obstacle and valid edge endpoint |
| `place_icons(parent, items, cols, x0=20, y0=50, col_w=130, row_h=160, **icon_kwargs) -> (ids, (x, y, right, bottom))` | items: `(label, icon)` tuples or dicts with label, icon, metadata, tooltip, key, link |
| `add_badge(icon_key, cx, cy, parent="1", host=None, size=22, key=None, metadata=None, tooltip=None) -> str` | caption-less half-size icon centred on (cx, cy) in parent coordinates; `host` = the subnet or icon it decorates (may be overlapped by the badge, ignored by `fit_to_children`); style `ociRole=badge;ociHost=<id>` |
| `fit_to_children(cid, pad=20, min_w=None, min_h=None) -> (w, h)`; `resize(cid, w=None, h=None, x=None, y=None)` | fit after children exist; x/y unchanged |
| `bbox(cid)` / `abs_bbox(cid)` / `footprint(cid) -> (x, y, w, h)`; `content_bbox(page_idx=None) -> (x, y, right, bottom)`; `fit_page(margin=20) -> (w, h)` | footprint = slot + caption |
| `add_title(subject, region_label=None, region=None, compartment=None, tenancy=None, x=20, y=8, w=600, h=55, font_size=18, font_family=None, logo=None, logo_w=148, logo_h=39, page_w=None, key="title") -> {"title", "logo"}` | missing Pillow/logo file prints a warning, does not fail |
| `add_image(image_path, x, y, w, h, parent="1", key=None) -> str`; `add_text(label, x, y, w=200, h=30, parent="1", font_size=10, font_style=0, align="left", font_color=None, font_family=None, key=None, vertical_align="middle", raw_html=True, style_extra="") -> str` | SVG embedded directly, PNG/JPEG via Pillow |
| `add_table(rows, x, y, parent="1", col_widths=None, header=True, font_size=10, row_h=18, title=None, key=None) -> str` | rows = list of string lists; first row = header |
| `add_legend(x, y, parent="1", entries=None, title="Legend", width=230, key=None) -> str` | entries `("edge", <style>, text)` with style `data`, `control`, `association`, `attachment` (or legacy alias `solid`, `dashed`, `accent`, `purple`, `dotted`, `thin`), or `("group", <group_type>, text)`; default entries when None |
| `add_edge(source, target, label="", parent=None, dashed=False, color=None, style_extra="", exit_x=None, exit_y=None, entry_x=None, entry_y=None, waypoints=None, orthogonal=None, route=None, label_pos=None, arrow=None, key=None, raw_html=False, kind=None) -> str` | parent defaults to the common ancestor; `label_pos` -1..1; `kind` `data`\|`control`\|`association`\|`attachment` applies `EDGE_KIND_STYLES` (explicit `arrow=` still wins) |
| `append_pages(other)` | appends every page of another `DrawioBuilder` as read-only pages (deep-copied; `other` stays usable) |
| `validate(strict=False) -> list[str]`; `check_overlaps(strict=False) -> list[str]`; `write(path) -> Path` | messages start with `ERROR:`, `OVERLAP:` or `WARNING:` (prefixed `[page: X]` on multi-page files); `check_overlaps` returns blocking ones only; `write` accepts str or Path |
| module: `render(drawio_path, fmt="png", out=None, scale=1.0, timeout=120) -> Path or None`, `find_drawio_binary()`, `validate_file(path, strict=False)`, `set_icon_dir(path)`, `add_icons_to_map({key: "category/file.svg"})`, `escape_label(text)`, constants `PAD, GAP, ROW1_Y, COL_W, ROW_H, ICON_W, ICON_H, ICON_FOOTPRINT_H, COLORS` | |

Worked example (runs as-is once the path is replaced; produces `hub_spoke.drawio`, gate clean):

```python
import sys
sys.path.insert(0, "/ABSOLUTE/PATH/TO/oci-drawio-architect/scripts")
from drawio_builder import DrawioBuilder, PAD, ROW1_Y, GAP, ICON_W

d = DrawioBuilder(page_name="Hub-and-Spoke")
d.add_title("Hub-and-Spoke - Architecture", region_label="Frankfurt", region="eu-frankfurt-1", compartment="network")
region = d.add_group("eu-frankfurt-1", PAD, 75, 900, 400, group_type="region", key="region")
(drg,), _ = d.place_icons(region, [{"label": "DRG\nhub-drg", "icon": "drg", "key": "drg"}], cols=1, x0=PAD, y0=150)
att = d.add_box("VCN attachment\nspoke-a", PAD + ICON_W + 15, 190, 100, 44, parent=region, key="att-spoke-a")
spoke = d.add_group("VCN: spoke-a (10.1.0.0/16)", PAD + ICON_W + 15 + 100 + 45, 40, 300, 200,
                    parent=region, group_type="vcn", key="vcn-spoke-a")
sn = d.add_group("sn-app (10.1.1.0/24)", PAD, ROW1_Y, 200, 150, parent=spoke, group_type="subnet", key="sn-app")
(vm,), _ = d.place_icons(sn, [{"label": "App VM\n10.1.1.5", "icon": "vm", "key": "app-vm",
                               "metadata": {"ocid": "ocid1.instance.oc1..x"}, "tooltip": "primary app node"}], cols=1)
d.add_badge("nsg", PAD + ICON_W - 11, ROW1_Y + 11, parent=sn, host=vm, key="app-vm-nsg", tooltip="NSG: nsg-app")   # shield on the VM's slot
for cid in (sn, spoke, region):
    d.fit_to_children(cid)
d.add_edge(att, spoke, "", kind="attachment")        # structural: box -> VCN border, no arrowhead
d.add_edge(drg, vm, "443", kind="data")              # traffic: solid, open arrow
d.fit_page()
problems = d.validate()
print("\n".join(problems))
if any(not p.split("] ")[-1].startswith("WARNING") for p in problems):
    raise SystemExit("layout errors; diagram not written")
d.write("hub_spoke.drawio")
```

Edge routing modes (`route=`):
1. `"auto"` (default when no ports/waypoints): common-ancestor parent, docking sides and gutter waypoints computed from all cells at `validate()`/`write()` time; add edges in any order. Use this.
2. `"direct"` (or `orthogonal=True` without pins): draw.io's orthogonal router, no fixed ports - the v1.1.0 behaviour; may cross icons (the checker warns).
3. `"pinned"`: fixed `exit_x/exit_y/entry_x/entry_y` (0.5,0 top; 0.5,1 bottom; 0,0.5 left; 1,0.5 right) and `waypoints` in the parent's coordinates; selected automatically when any pin or waypoint is passed. `orthogonal=True` plus pins keeps the router with docked sides. Use only to route around a specific obstacle.
4. `dashed=True` -> control; `color=COLORS["edge_accent"]` -> analytics; `color=COLORS["edge_purple"], dashed=True` -> datalake; `arrow="none"|"open"|"block"|"classic"` overrides the profile arrowhead; `label_pos` moves the label along the edge.

Metadata, tooltips, links: `metadata={"ocid": "...", "shape": "VM.Standard.E5.Flex"}` (keys `^[A-Za-z_][A-Za-z0-9_-]*$`, not id/label/placeholders/tooltip/link) and `tooltip="..."` wrap the cell in an `<object>` (`<UserObject>` when `link=` is given) so the data survives draw.io round-trips and shows in Edit Data. `key="app-vm"` gives a stable cell id (slugged: other characters become `-`).

Multi-page: `d.add_page("Security", 800, 400)` makes the new page current (`use_page(0)` to return); call `add_title`/`fit_page` per page; `validate()` covers all pages. Legend: `_, _, _, bottom = d.content_bbox(); d.add_legend(PAD, bottom + GAP)` before `fit_page()`. Table: `d.add_table([["Direction", "Source", "Ports"], ["Ingress", "0.0.0.0/0", "443"]], PAD, 75, col_widths=[80, 170, 60], title="nsg-app (1 rule)")`. Demonstration of the recipe on a two-VCN hybrid model (the outside canvas with the badge legend, then the same model with `locations="nested"` and `drg_style="box"`), a third page with compartments, a tenancy wrapper, an OKE cluster box and a tier band, and a fourth built with the custom API (`add_table` for an NSG rule list): `examples/generate_demo_diagram.py`.

## 8. Acceptance criteria (all mandatory)

1. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_overlaps.py" <file>.drawio` exits 0 and prints `OK: no container overlaps or layout errors (...)`.
2. Zero `ERROR:`/`OVERLAP:` lines (unknown parents or endpoints, intersecting containers, shapes outside their parent, icon/caption collisions).
3. Every `WARNING:` line was read and either fixed (caption > 3 lines; estimated crossing; content exceeds page) or confirmed harmless in the PNG.
4. PNG self-review (`render_drawio.py <file> -f png`, then Read the PNG): glyphs uniform; captions legible, 3 lines max, inside their container, no overlaps; edges in gutters, none across icons or captions, labels readable; on-premises panel and DRG column centred on the VCN stack; DRG outside every VCN with its attachment boxes beside it; gateways centred on the VCN border; route tables and security lists as badges on the subnets' top-right corners and NSGs as shield badges on their resources, never as workload icons; no large empty area; title and region label follow section 1. Under the default `locations: "outside"` canvas also: the On-Premises, Internet and 3rd Party Cloud boxes sit **outside** the region, the hybrid connection label (`Site-to-Site VPN` / `FastConnect` / `Remote Peering`) sits in the gap between the On-Premises box and the region, the IGW and the NAT straddle the VCN border facing the Internet box - the IGW above the NAT on the **right** border of the rightmost VCN column, the two side by side on the **top** border with their captions above the glyphs for every other column (`gateway_edge` / `gateways[].side` override both) - the Oracle Services Network is a full-width band under the VCN stack fed by a bottom-border Service Gateway, and every subnet label is two lines (name + Public/Private, then the CIDR). Under `locations: "nested"` the 1.3.0 checks apply instead (on-premises panel inside the region, OSN panel right of the VCNs). Nothing but the title, the notes, the legend and the location boxes is outside the region.
5. The generated script imports from the plugin `scripts` directory and contains no copied builder code; file size is roughly 7-13 KB per icon (the 31-icon reference is 280 KB).
6. No caption contains an OCID, in any label mode.
7. Every layer the file creates is non-empty, and the base layer is named `Network` whenever layers are on.

## 9. Failure handling

| Message | Fix |
|---------|-----|
| `Unknown icon_key 'x'. Did you mean a, b?` | take the suggestion or look the key up in `references/icon-catalog.md` |
| `OCI icon directory not found ... Searched: ...` | fix `sys.path.insert` to the plugin `scripts` dir, or `export OCI_SVG_DIR=<plugin>/icons` / `set_icon_dir()` |
| `Pillow is required for PNG/JPEG logos` | SVG logo, `python3 -m pip install --user Pillow`, or drop the logo |
| `edge endpoint 'x' not found` / `matches N items; use an 'address'` | give the item an `address` and reference it |
| `Unknown group_type` / `unknown source id` / `is on another page` | use the listed type; pass returned ids; keep edge ends on one page |
| `OVERLAP` / `extends outside its parent` / `overlaps` | recipe: split the VCN or move items; custom: `fit_to_children` innermost first, siblings at `bbox()` + `GAP`, icon pitch `COL_W`/`ROW_H` |
| `ERROR: DRG '...' is inside VCN '...'` | move the DRG to `drgs[]` (recipe) or parent it to the region outside every VCN box (custom) |
| `ERROR: '...' lies inside '...' but is not one of its children` | the icon's box overlaps a VCN / subnet it does not belong to; move it or make it a child of that container |
| `ERROR: 'X' [abs ...] overlaps '(unlabelled)' [abs ...]` where the unlabelled cell is a badge | the badge covers an icon that is not its host: pass `host=<that icon id>` to `add_badge` (recipe: move the `nsgs` field to that item) |
| `WARNING: caption ... needs ~N lines` | rewrite as `Role\nidentifier\nsize` |
| `WARNING: title ... its badges leave` | widen the subnet (the recipe does this automatically) or shorten the subnet name / CIDR label |
| `WARNING: edge ... is estimated to cross` | reorder items / change tier; custom: `route="direct"` or explicit `waypoints`; accept only if the PNG is clean |
| `draw.io desktop not found` (render exit 3) | skip the PNG and say so; `DRAWIO_BIN=/path/to/drawio` overrides discovery |
| `detect_settings.py` slow / `cli_warning` | rerun with `--no-cli` |

## 10. Key references

- Command workflow: `${CLAUDE_PLUGIN_ROOT}/commands/drawio-architect.md`
- Layout recipe and MODEL schema: `${CLAUDE_PLUGIN_ROOT}/scripts/oci_layout.py`
- Builder API: `${CLAUDE_PLUGIN_ROOT}/scripts/drawio_builder.py` (v1.5.0, standard library only)
- Model producers: `${CLAUDE_PLUGIN_ROOT}/scripts/parse_terraform.py` (Terraform dir / plan / state -> model.json), `${CLAUDE_PLUGIN_ROOT}/scripts/query_tenancy.py` (experimental as-built via OCI CLI)
- Topology helpers: `${CLAUDE_PLUGIN_ROOT}/scripts/oci_topology.py`
- Gate and tools: `${CLAUDE_PLUGIN_ROOT}/scripts/check_overlaps.py`, `${CLAUDE_PLUGIN_ROOT}/scripts/render_drawio.py`, `${CLAUDE_PLUGIN_ROOT}/scripts/detect_settings.py`, `${CLAUDE_PLUGIN_ROOT}/scripts/smoke_test.sh`
- Examples: `${CLAUDE_PLUGIN_ROOT}/examples/generate_reference_layout.py` (MODEL -> `write_diagram`, reproduces the reference on the outside canvas), `${CLAUDE_PLUGIN_ROOT}/examples/generate_demo_diagram.py` (four pages: the outside canvas with the badge legend, the nested 1.3.0 canvas with `drg_style="box"`, compartments with an OKE cluster and a tier band, and a custom-API NSG table)
- Icons: `${CLAUDE_PLUGIN_ROOT}/icons/` - 159 SVGs in 12 categories, 206 aliases; catalog `${CLAUDE_PLUGIN_ROOT}/skills/oci-drawio-architect/references/icon-catalog.md`
- Styles: `${CLAUDE_PLUGIN_ROOT}/skills/oci-drawio-architect/references/oracle-styles.md`; pitfalls: `${CLAUDE_PLUGIN_ROOT}/skills/oci-drawio-architect/references/gotchas.md`
