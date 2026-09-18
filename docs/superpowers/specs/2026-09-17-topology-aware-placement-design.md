# Topology-Aware Placement (v1.3.0) - Design Specification

**Author:** Sergio Farfan
**Date:** 2026-09-17
**Plugin:** oci-drawio-architect 1.2.0 -> 1.3.0
**Repository:** `OCI-draw.io-Architect` (public, MIT), branch `feature/v1.3.0-topology-aware-placement`

## 1. Goal

Make the layout recipe (`scripts/oci_layout.py`) topology-aware so that generated diagrams follow how Oracle and the team's diagram guidelines draw connectivity infrastructure:

- the Dynamic Routing Gateway (DRG) is a **region-level element** with its **attachments drawn next to it**, never inside a VCN box or the on-premises panel;
- Internet, NAT, Service and Local Peering gateways **straddle the VCN border** on the side facing what they connect to, instead of sitting in a row inside the VCN;
- regional Oracle services are drawn in **one region-level Oracle Services Network panel** reached through the Service Gateway, instead of a services panel nested inside the VCN;
- connectors carry **four visual semantics** (data, control, association, attachment) with a matching legend;
- the validator **refuses** a DRG drawn inside a VCN and any icon that lies inside a VCN or subnet it does not belong to.

Everything stays standard-library Python 3.9+, deterministic (`key=` ids) and gated by `check_overlaps.py`.

## 2. Sources of the rules

| Source | What it establishes | Where used |
|--------|---------------------|------------|
| OCI Architecture Diagram Toolkit v24.2 deck, slide 7 | A box asserts location: what is drawn inside a location group resides there | D1, D8 |
| Deck slides 10 and 20 | Connectors are Bark 1pt; open arrowhead = directional flow; plain line = undirected relationship | D7 |
| Deck slide 18 | VCN / subnet / compartment / region grouping styles | unchanged |
| Deck slide 19 | Oracle Services Network is a network grouping, a peer of the VCN, label top-left | D6 |
| Deck slides 21 and 22 | Special connections: Site-to-Site VPN and FastConnect always connect a DRG to a CPE; Local Peering is LPG-to-LPG, text label only, 1:1; Remote Peering is DRG-to-DRG across regions; connector icons are half size and sit on the line | D2, D5 |
| Deck slides 27-31 (templates and samples) | DRG centred on the VCN border facing on-premises; Service Gateway centred on the VCN border facing the OSN; Internet Gateway on the VCN border; one DRG per region fanning out to several VCNs (slide 31) | D4, D5 |
| Deck slides 29-32 | OSN drawn inside the region, outside the VCN, adjacent to it, holding IAM, Auditing, Object Storage, Logging, Policies, Container Registry | D6 |
| Oracle A-Team, "IPSec over FastConnect in a hub-and-spoke architecture", https://www.ateam-oracle.com/ipsec-over-fastconnect-in-a-hub-and-spoke-architecture (figure `topo1-2`) | Target form: DRG icon at region level between the VCNs; each attachment as its own small rounded box ("VCN Attachment", "FC VC Attachment", "IPSec Attachment") clustered around the DRG; the VCN attachment sits between the DRG and that VCN's border; FastConnect / Site-to-Site VPN label on the line outside the region next to the CPE; on-premises box at the far left | D2, D3, D4 |
| https://docs.oracle.com/en-us/iaas/Content/Network/Tasks/managingDRGs.htm | "A DRG acts as a virtual router"; attachment types VCN, VIRTUAL_CIRCUIT, IPSEC_TUNNEL, REMOTE_PEERING_CONNECTION, LOOPBACK; a VCN attaches to exactly one DRG; the DRG lives in its own compartment | D1, D2, D9 |
| https://docs.oracle.com/en-us/iaas/Content/Network/Tasks/transitrouting.htm | "the DRG is a standalone resource ... The attachment itself identifies which VCN" | D2 |
| https://docs.oracle.com/en-us/iaas/Content/Network/Tasks/servicegateway.htm | Service gateway is VCN-scoped, one per VCN, the VCN's path to the Oracle Services Network; the OSN is "a conceptual network ... reserved for Oracle services" | D5, D6 |
| https://docs.oracle.com/en-us/iaas/Content/Network/Tasks/managingIGs.htm, NATgateway.htm | IGW / NAT are VCN-scoped, at most one per VCN, drawn on the VCN border | D5 |
| https://docs.oracle.com/en-us/iaas/Content/Network/Tasks/localVCNpeering.htm | "A local peering gateway (LPG) is a component on a VCN"; LPGs on both VCN borders paired by a Local Peering line | D5 |
| https://docs.oracle.com/en-us/iaas/Content/Network/Tasks/overviewIPsec.htm, fastconnectoverview.htm | Hybrid traffic "goes through the DRG"; on-premises links terminate on the DRG | D2 |
| https://docs.oracle.com/en/solutions/hub-spoke-network-drg/index.html, oci-best-practices-networking, cis-oci-benchmark | Reference architectures: DRG outside all VCNs, vertically centred on the VCN column, one connector or attachment marker per VCN; IGW / NAT / SGW straddle VCN borders; OSN outside every VCN | D4, D5, D6 |
| The team's diagram guidelines (internal review document) | Connector table: solid arrow = application/data flow, dashed = management/administrative, dotted = association/dependency, no arrowhead = attachment/structural, label = protocol/port or relationship name; gateways on the VCN edge; OSN at regional level with the path VCN -> SGW -> OSN -> service; regional services (Logging, Logging Analytics, Notifications, IAM/Identity Domain, Vault, Generative AI) outside the VCN; the DRG is connectivity infrastructure, chain VCN - attachment - DRG - remote network explicit | D2, D5, D6, D7 |
| Reviewer feedback on the current output | "DRG as its own box with attachments in it" is a valid presentation for network audiences; the lighter icon form is preferred for architecture-level views | D3 |

Deviation kept on purpose: the `oracle_services_network` container keeps the plugin's Rose 1px dashed / Air fill look (decision D6); slide 19 specifies Neutral 3 2pt dashed with a Bark label for the OSN and assigns Rose to the "Optional" other-grouping. The label is now left-aligned (slide 19 "Top/Left"). `oracle-styles.md` records the provenance correction.

## 3. Current behaviour (1.2.0) and gaps

Verified on the built reference (`examples/generate_reference_layout.py`, cells dumped with `build_cell_registry`):

| Area | 1.2.0 behaviour | Location | Gap |
|------|-----------------|----------|-----|
| Gateways | Bare icons in the VCN's bottom row, parent = VCN cell (`sgw`, `nat` at abs y=1000 inside `vcn-Spoke-VCN-D`) | `oci_layout.py:279-296`, docstring line 14 | Team guideline: gateways on the VCN edge |
| DRG | A `hub.items` entry drawn inside the on-premises panel (`drg` parent=`hub`), and/or a `vcns[].gateways` entry drawn inside the VCN as "DRG attachment" | `oci_layout.py:299-327`, `parse_terraform.py:1165-1208` | DRG is regional infrastructure; attachments belong next to it |
| Services | `vcn.services` panel nested in the VCN (`services-Spoke-VCN-D` parent=`vcn-Spoke-VCN-D`); `model.services` region panel only with 2+ VCNs | `oci_layout.py:254-269, 366-373` | Regional services are not VCN-resident; OSN must be a regional construct |
| Edge kinds | `data` solid open arrow, `control` dashed no arrow, `analytics` solid Sienna, `datalake` dashed purple | `oci_layout.py:94-100`, `drawio_builder.py:1835-1858` | No association / attachment semantics; legend has two line kinds |
| Validator | Rules 1-6: references, container overlaps, own-parent containment, leaf collisions, long captions, crossings. A region-parented DRG icon fully inside a VCN validates clean (probe A); a VCN-parented icon straddling the VCN border fails rule 3 with `ERROR: 'Internet Gateway' [...] extends outside its parent 'VCN'` (probe B) | `drawio_builder.py:1049-1162` | No foreign-containment rule; no straddle tolerance |
| Schema | `schema_version` 1: DRG reported once per attached VCN in `gateways` and once in `hub.items`; attachment display names discarded | `parse_terraform.py:17-66, 1165-1184` | Needs `drgs[]` with typed `attachments[]` |

## 4. Design decisions (fixed)

- **D1** The DRG is a region-level element. Its cell parent is always the region container, never a VCN, subnet or the on-premises panel. Violation is a hard validator error.
- **D2** Attachments are drawn adjacent to the DRG: one small labelled rounded box per attachment (label = attachment display name, fallback `VCN attachment <vcn>`), on the DRG side facing its target; a connector of kind `attachment` (no arrowhead) from the box to the target. Targets: VCN attachment -> that VCN's border; RPC attachment -> the remote peer item in the hub panel; IPSec and virtual-circuit attachments -> the on-premises item (CPE / virtual circuit) with the connector labelled `Site-to-Site VPN` / `FastConnect` (the bundle has no VPN or FastConnect glyph, so text labels are used; `Remote Peering` for RPC).
- **D3** Two presentation styles: `drg_style` `icon` (default, A-Team form) and `box` (a `drg` group styled like the toolkit "Other Group", dashed, labelled `DRG: <name>`, containing the DRG icon and the attachment boxes). Model key `drg_style`, CLI flag `--drg-style {auto,icon,box}`, `build_diagram(drg_style=...)` kwarg. `auto` = `icon` unless a DRG has more than 4 attachments, then `box`.
- **D4** Topology awareness via `classify_topology(model)`; layout per class in section 7.
- **D5** IGW, NAT, SGW and LPG straddle the VCN border (glyph centre on the border line): IGW and NAT on the bottom border; SGW on the right border facing the OSN panel; LPG on the border facing its peer VCN (right when the peer is a later column, left when earlier, bottom when unknown) with a `Local Peering` attachment-kind connector between the two LPG icons. Edge gateways are children of the region in the recipe; the validator tolerates border-centred icons whichever parent they have.
- **D6** Regional services go to ONE region-level `oracle_services_network` panel labelled `Oracle Services Network`, right of the VCN columns, height matched to the tallest VCN; the SGW straddles the VCN's right border and an attachment-kind connector runs SGW -> panel. VCN-resident services stay in subnets. Classification table in section 6, overridable per item with `"regional": true|false`.
- **D7** Connector semantics: `data` = solid, open arrowhead; `control` = dashed, open arrowhead; `association` = dotted (`dashPattern=1 3`), no arrowhead; `attachment` = solid 1px, no arrowhead. `analytics` (solid Sienna, data semantics) and `datalake` (dashed purple, control semantics) keep working. Legend rows: the four kinds plus region, VCN, subnet and OSN swatches.
- **D8** Validator rule "foreign containment": an icon, caption or box whose ancestor chain does not include container X must not lie inside X when X is a `vcn` or `subnet` (tolerance `FOREIGN_TOL = ICON_W / 4 = 18.75 px`: a leaf sticking out by more than that is not "inside"; a border-centred icon sticks out 35-37 px). DRG icons produce `ERROR: DRG '<label>' is inside VCN '<vcn>'` even when parented correctly.
- **D9** Backward compatibility: models without `drgs` but with `drg`-typed gateways or `drg` hub items are migrated at build time into a synthesised `drgs[]` entry with `WARNING: legacy model: ...` lines on stderr. `parse_terraform.py` emits `schema_version` 2. The hub panel holds on-premises items only (CPE, IPSec, FastConnect virtual circuit, RPC peer).
- **D10** Availability / fault domain boxes are only drawn by custom layouts that ask for them (already the case; no work).
- **D11** Version 1.3.0 everywhere; CHANGELOG entry; README, SKILL.md, command, oracle-styles.md, gotchas.md updated; reference model migrated (DRG out of `hub.items` into `drgs`, CPE stays in the hub with an explicit `cpe -> drg` edge labelled `IPSec VPN`); `OCI_Architecture.drawio` and screenshots regenerated; demo exercises both DRG styles, the OSN panel and the four connector kinds.
- **D12** Stdlib-only Python 3.9+, deterministic ids, `check_overlaps.py` passes on every example output, all 244 existing tests keep passing (fixtures updated where the schema requires).

## 5. Model schema v2 (delta)

Every key stays optional except `subject` and `vcns` (or `hub`/`drgs`). New or changed keys:

```json
{
  "schema_version": 2,
  "drg_style": "auto",
  "drgs": [
    {
      "name": "drg-shop",
      "address": "oci_core_drg.drg",
      "label": "DRG\ndrg-shop",
      "attachments": [
        {"type": "vcn", "vcn": "vcn-shop", "address": "oci_core_drg_attachment.vcn", "label": "drg-att-shop"},
        {"type": "ipsec", "target": "oci_core_cpe.onprem", "address": "oci_core_ipsec.vpn@oci_core_drg.drg", "label": "vpn-hq"},
        {"type": "virtual_circuit", "target": "oci_core_virtual_circuit.fc", "address": "oci_core_virtual_circuit.fc@oci_core_drg.drg", "label": "fc-hq"},
        {"type": "rpc", "target": "oci_core_remote_peering_connection.dr", "address": "oci_core_remote_peering_connection.dr@oci_core_drg.drg", "label": "rpc-dr"}
      ]
    }
  ],
  "hub": {"name": "On-premises", "items": [{"icon": "cpe", "label": "cpe-hq", "type": "oci_core_cpe", "address": "oci_core_cpe.onprem"}], "link_label": null},
  "vcns": [{
    "name": "vcn-shop", "address": "oci_core_vcn.main", "cidr": "10.0.0.0/16",
    "services": [{"icon": "logging", "label": "Log group", "type": "oci_logging_log_group", "address": "oci_logging_log_group.app", "metadata": {}, "regional": true}],
    "gateways": [
      {"icon": "internet_gateway", "type": "igw", "label": "igw-shop", "address": "oci_core_internet_gateway.igw"},
      {"icon": "service_gateway", "type": "sgw", "label": "sgw-shop", "address": "oci_core_service_gateway.sgw"},
      {"icon": "remote_peering_gateway", "type": "lpg", "label": "lpg-hub", "address": "oci_core_local_peering_gateway.hub", "peer": "oci_core_local_peering_gateway.spoke"}
    ]
  }],
  "edges": [
    {"source": "oci_core_local_peering_gateway.hub", "target": "oci_core_local_peering_gateway.spoke", "label": "Local Peering", "kind": "attachment", "inferred": false},
    {"source": "oci_core_instance.app", "target": "oci_database_autonomous_database.shop", "label": "1522", "kind": "data", "inferred": true}
  ]
}
```

Rules:
- `drgs[].attachments[].type` in `vcn | ipsec | virtual_circuit | rpc | loopback` (`loopback` is accepted and not drawn). `vcn` holds a VCN name or address; `target` holds a hub item address (or `null`, then the box has no connector).
- `attachments[].address` must be unique in the model (parser convention: the attachment resource address for VCN attachments, `<connection address>@<drg address>` for IPSec, virtual-circuit and RPC attachments; `<drg address>@<vcn address>` for an implicit single-VCN attachment).
- `edges[].kind` in `data | control | association | attachment` for parser output; the layout additionally accepts `management` (= control), `analytics`, `datalake`.
- `vcn.gateways[].type` in `igw | nat | sgw | lpg` (no `drg`); `lpg` entries may carry `peer` (peer LPG address or peer VCN name).
- `services[].regional` (bool, optional) overrides the classification table.
- `hub.link_label` is kept for hand-written models (edges between consecutive hub items); parser output sets it to `null`.
- Legacy schema-1 input is accepted by the layout through the migration in D9.

## 6. Regional service classification (D6)

An item found in `vcn.services` or `model.services` is **regional** (drawn in the OSN panel) when `item["regional"]` is true, or when it is absent and the icon key is in `REGIONAL_ICON_KEYS`. Items placed in a subnet are never moved. Items that are not regional stay in the per-VCN `OCI Services` panel (which now only exists when such items remain).

| Regional (OSN panel) | Icon keys / Terraform types |
|----------------------|-----------------------------|
| Logging, Logging Analytics | `logging`, `logging_analytics` / `oci_logging_log_group` |
| Monitoring, Alarms, Notifications, Events, Connector Hub | `monitoring`, `alarms`, `notifications`, `ons`, `events`, `service_connector_hub`, `connector_hub` / `oci_monitoring_alarm`, `oci_ons_notification_topic`, `oci_events_rule`, `oci_sch_service_connector` |
| IAM, Identity domain, Policies, Audit, Cloud Guard, Vulnerability Scanning, Threat Intelligence | `iam`, `identity`, `policies`, `policy`, `auditing`, `audit`, `cloud_guard`, `vulnerability_scanning`, `vuln_scanning`, `threat_intelligence`, `threat_intel` |
| Vault / KMS, Certificates | `vault`, `key_vault`, `key_management`, `kms`, `encryption`, `certificates` / `oci_kms_vault`, `oci_kms_key`, `oci_certificates_management_certificate` |
| Object Storage, OCIR | `buckets`, `object_storage`, `container_registry`, `ocir` / `oci_objectstorage_bucket`, `oci_artifacts_container_repository` |
| Generative AI / AI services, Data Safe, Data Science, Analytics, Data Integration / Flow / Catalog | `ai`, `generative_ai`, `data_safe`, `data_science`, `big_data`, `analytics`, `machine_learning`, `ml`, `digital_assistant`, `oda`, `data_integration`, `data_flow`, `data_catalog` / `oci_generative_ai_*`, `oci_ai_*`, `oci_datascience_project`, `oci_analytics_analytics_instance` |
| Streaming, Queue, APM, Email, DNS zones, DevOps, Resource Manager, Health Checks, WAF policies | `streaming`, `queue`, `queuing`, `apm`, `email_delivery`, `email`, `dns`, `devops`, `resource_manager`, `health_checks`, `waf` / `oci_streaming_stream`, `oci_queue_queue`, `oci_apm_apm_domain`, `oci_dns_zone`, `oci_devops_project`, `oci_waf_web_app_firewall` |

| VCN-resident (subnet or per-VCN panel) | Examples |
|----------------------------------------|----------|
| Load balancers, compute, OKE, instance pools, Functions applications, API gateways | `load_balancer`, `vm`, `oke`, `instance_pool`, `functions`, `api_gateway` |
| DB systems, Autonomous DB (private endpoint), MySQL, NoSQL/Redis in a subnet | `db_system`, `autonomous_db`, `mysql`, `nosql` |
| File storage mount targets and file systems, block volumes | `file_storage`, `block_storage` |
| Bastion, network firewall, NSG, security list, route table, DNS resolver | `bastion`, `firewall`, `nsg`, `security_list`, `route_table`, `dns` resolver (`oci_dns_resolver` is VCN-resident; the `dns` icon alone is regional) |

Functions applications and API gateways require a subnet in OCI and therefore stay VCN-resident.

## 7. Topology classification and layout geometry

### 7.1 `classify_topology(model) -> dict`

Pure function in the new module `scripts/oci_topology.py`, applied after `migrate_legacy_model`:

```python
{"kind": "single_vcn" | "multi_vcn" | "vcn_with_drg" | "hub_spoke" | "hybrid",
 "n_vcns": int, "n_drgs": int, "n_vcn_attachments": int,
 "has_onprem": bool, "has_rpc": bool, "has_lpg": bool}
```

- `n_vcn_attachments` counts attachments of type `vcn` over all DRGs.
- `has_onprem` = hub has at least one item whose type/icon is CPE, IPSec or virtual circuit, or any attachment is `ipsec` / `virtual_circuit`.
- `has_rpc` = any `rpc` attachment or a hub item with icon `remote_peering_gateway`/`rpg` or type `oci_core_remote_peering_connection`.
- `has_lpg` = any VCN gateway of type `lpg`.
- `kind`: no DRG -> `single_vcn` (n_vcns <= 1) or `multi_vcn`; DRG and (`has_onprem` or `has_rpc`) -> `hybrid`; DRG and `n_vcn_attachments >= 2` -> `hub_spoke`; otherwise `vcn_with_drg`.

`choose_drg_style(requested, n_attachments) -> "icon" | "box"`: `requested` in `icon`/`box` wins; `auto` -> `box` when `n_attachments > DRG_BOX_THRESHOLD (4)`, else `icon`.

### 7.2 Column order and constants

Region-local x order (left to right): on-premises panel (`HUB_X=15`, `HUB_W=180`) -> `HUB_GAP=45` -> DRG column (width computed, see 7.4) -> `DRG_GAP=45` -> VCN columns (`VCN_COLUMN_GAP=45`) -> `OSN_GAP=45` -> OSN panel. Absent elements take no space. The on-premises panel, the DRG column and the OSN panel are all vertically aligned on the VCN stack: hub centred on the tallest VCN (existing), DRG clusters centred on `VCN_Y + ref_h / 2`, OSN panel `min_h = ref_h`.

New constants in `oci_layout.py`:

| Constant | Value | Meaning |
|----------|-------|---------|
| `DRG_GAP` | 45 | DRG column -> first VCN |
| `ATT_W`, `ATT_H` | 100, 44 | attachment box |
| `ATT_GAP` | 15 | DRG slot -> attachment boxes |
| `ATT_PITCH` | 56 | vertical pitch of stacked boxes |
| `DRG_CLUSTER_GAP` | 40 | between stacked DRG clusters |
| `OSN_GAP` | 45 | last VCN -> OSN panel |
| `OSN_LABEL` | `"Oracle Services Network"` | panel label |
| `GW_STRADDLE` | 40 | slot top -> glyph centre (`GLYPH_TOP + GLYPH_H / 2`) |
| `GW_SIDE_DX` | 38 | slot left offset from a side border (`round(ICON_W / 2)`) |
| `SIDE_GW_Y0`, `SIDE_GW_PITCH` | 50, 160 | side-border gateway slots |
| `VCN_BOTTOM_PAD_GW` | 60 | VCN bottom padding when bottom gateways exist |
| `VCN_SIDE_PAD` | 60 | VCN right padding when right-border gateways exist |
| `SIDE_INSET` | 40 | extra left inset of VCN content when left-border gateways exist |

### 7.3 Gateways on the VCN edge (D5)

Edge gateways are placed after `fit_to_children(vcn)`, as children of the region, from the VCN's region-local box `(vx, vy, vw, vh)`:

- bottom (`igw`, `nat`, `lpg` without a known peer): slot `x = vx + PAD + i * GW_PITCH`, `y = vy + vh - GW_STRADDLE`
- right (`sgw`, `lpg` whose peer VCN is a later column): slot `x = vx + vw - GW_SIDE_DX`, `y = vy + SIDE_GW_Y0 + i * SIDE_GW_PITCH`
- left (`lpg` whose peer VCN is an earlier column): slot `x = vx - GW_SIDE_DX + 1`, same y series

Captions get an opaque region-fill background (`label_fill=COLORS["region_fill"]`, toolkit convention) because side captions cross the dashed border. The VCN gets `VCN_BOTTOM_PAD_GW` / `VCN_SIDE_PAD` / `SIDE_INSET` so content keeps >= 20 px clearance from a straddling glyph. If side gateways need more height than the VCN has, the VCN is resized taller.

### 7.4 DRG column (D2, D3, D4)

Per DRG cluster (icon style), region-local, `cy` = cluster centre:

```
left_w  = ATT_W + ATT_GAP  if on-prem / RPC attachments else 0
right_w = ATT_W + ATT_GAP  if VCN attachments else 0
col_w   = left_w + ICON_W + right_w
DRG slot: x = col_x + left_w, y = cy - GW_STRADDLE            (glyph centre on cy)
right boxes: x = col_x + left_w + ICON_W + ATT_GAP, block centred on cy, pitch ATT_PITCH
left boxes:  x = col_x, same vertical rule
cluster_h = max(ICON_FOOTPRINT_H, n_side_max * ATT_PITCH - (ATT_PITCH - ATT_H))
```

Several DRGs stack with `DRG_CLUSTER_GAP`; the stack is centred on the VCN stack centre. Box style wraps each cluster in a `drg` group (`DRG: <name>`), children offset by `PAD` / `ROW1_Y`, then `fit_to_children`. Connectors (kind `attachment`, key `<attachment address>-edge`): right box -> `vcn:<name>` container (no label), left box -> hub item (`Site-to-Site VPN` / `FastConnect` / `Remote Peering`). `loopback` attachments are skipped. Registry: `drg:<name>` and the DRG address resolve to the DRG icon; attachment addresses resolve to their boxes.

### 7.5 Sketches

`single_vcn` (no DRG, no hub; IGW/NAT bottom, SGW right, OSN right):
```
+ region ---------------------------------------------------+
| + VCN --------------------------+   + Oracle Services --+ |
| | [sn-lb] [sn-app]              |   |  Network          | |
| |                             (SGW)---  logging  ocir   | |
| | [sn-data ................ ]   |   |  buckets  apm     | |
| +-----(IGW)-----(NAT)-----------+   +-------------------+ |
+-----------------------------------------------------------+
```

`multi_vcn` with LPG pair (no DRG):
```
+ region -----------------------------------------------------------+
| + VCN hub ---------+        + VCN spoke -------+   + OSN -------+ |
| | [sn-web]        (LPG)-Local Peering-(LPG)      |   | ...       | |
| |                  |        |   [sn-app]       (SGW)--           | |
| +---(IGW)----------+        +------------------+   +-----------+ |
+-------------------------------------------------------------------+
```

`vcn_with_drg` (one VCN attachment, no on-prem):
```
+ region ------------------------------------------------------+
|  (DRG)[VCN attachment]---+ VCN ----------------+  + OSN ---+  |
|   drg                    |  [sn-lb] [sn-app]  (SGW)--       |  |
|                          +-------(IGW)---------+  +--------+  |
+--------------------------------------------------------------+
```

`hybrid` (reference model: CPE in the hub, explicit `cpe -> drg` edge, one VCN attachment):
```
+ region ------------------------------------------------------------------+
| + On-prem -+                                                              |
| |  (CPE)   |--IPSec VPN--(DRG)[VCN attachment]---+ VCN ---------+ + OSN + |
| |          |              drg                    | ...        (SGW)--   | |
| +----------+                                     +----(NAT)-----+ +-----+ |
+--------------------------------------------------------------------------+
```

`hub_spoke` / `hybrid` with two VCN attachments and an IPSec attachment (icon style):
```
+ region -----------------------------------------------------------------------+
| + On-prem -+   [IPSec attachment]           +-- VCN A -----+  +-- VCN B ----+  |
| |  (CPE)   |--Site-to-Site VPN-(DRG)[VCN attachment A]------|             |  |            |  |
| |          |                    drg [VCN attachment B]------+-------------+--|            |  |
| +----------+                                +--------------+  +------------+  |
+-------------------------------------------------------------------------------+
```
With `drg_style: box` the DRG icon and the boxes sit inside a dashed `DRG: <name>` group at the same position.

## 8. Builder changes (`scripts/drawio_builder.py`)

- `__version__ = "1.3.0"`.
- `EDGE_KIND_STYLES`: `data` (dashed 0, arrow open), `control` (dashed 1, arrow open, profile dash pattern), `association` (dashed 1, `dashPattern=1 3`, arrow none), `attachment` (dashed 0, arrow none, `strokeWidth=1`). `add_edge(..., kind=None)` applies them; `dashed=`/`arrow=`/`color=` still work when `kind` is not given. `_arrow_fragment(dashed, arrow=None, dash_pattern=None)` and `_edge_base_style(color, dashed, style_extra, orthogonal, arrow=None, width=None, dash_pattern=None)` gain the two overrides.
- `add_legend`: edge entry styles `solid`, `dashed`, `accent`, `purple` plus `dotted`, `thin` and the kind names `data`, `control`, `association`, `attachment`; new default entries (four connector kinds, region, VCN, subnet, OSN).
- `GROUP_TYPES` gains `drg`; style = toolkit "Other Group" look (rounded `arcSize=10`, Bark 1px dashed, no fill) with a **left-aligned** bold 11px label. Every container style carries an `ociGroup=<group_type>;` token so validators can tell VCNs and subnets apart in written files. `oracle_services_network` keeps its look; the recipe passes `label_position="left"`.
- `add_icon(..., label_fill=None)`: caption `fillColor` (used for border-straddling gateways). DRG icons (resolved SVG stem `networking_dynamic_routing_gateway_drg`) carry an `ociRole=drg;` style token.
- `add_box(label, x, y, w, h, parent="1", key=None, style_extra="", metadata=None, tooltip=None) -> str`: a labelled rounded rectangle (`rounded=1;arcSize=12;whiteSpace=wrap;html=1;strokeColor=<ivy>;fillColor=#FFFFFF;fontSize=11;align=center;verticalAlign=middle`), registered as kind `other` so it is a routing obstacle, a leaf in collision checks and a valid edge endpoint.
- Validator (`validate_registry`):
  - rule 3 straddle tolerance: an icon passes containment when its box fits the parent (tol 1) **or** its centre lies within the parent box expanded by `STRADDLE_TOL = 4` px; a caption passes when its owner icon passes (`_attach_captions` now records `owner` on the caption entry).
  - new rule 7 "foreign containment": for every container X whose group type is `vcn` or `subnet` (token `ociGroup`, fallback heuristic: Sienna `#AE562C` dashed stroke without `dashPattern=1 1`) and every leaf L (icon, caption, text, other) whose ancestors do not include X: if `X.contains(L, tol=FOREIGN_TOL)` -> `ERROR: '<L>' [abs ...] lies inside '<X>' [abs ...] but is not one of its children`. When L is a DRG icon (token `ociRole=drg`, fallback caption matching `\bDRG\b|Dynamic Routing`) and X is a VCN the message is `ERROR: DRG '<label>' is inside VCN '<vcn label>'`; this fires for any VCN that contains the DRG box, including its own parent chain.
- `__all__` exports `EDGE_KIND_STYLES`, `STRADDLE_TOL`, `FOREIGN_TOL`.

## 9. Parser and tenancy-query changes

`scripts/parse_terraform.py` (`SCHEMA_VERSION = 2`):
- `EDGE_KINDS = ("data", "control", "association", "attachment")`; `GATEWAY_ICONS` drops `drg`; `REGIONAL_TYPES` (section 6) and `ATTACHMENT_TYPES`.
- `new_model()` adds `"drgs": []` and `"drg_style": "auto"`; factories `new_drg(name, address, label) -> dict` and `new_attachment(atype, address, label, vcn=None, target=None) -> dict`.
- `_build_drgs()`: one `drgs[]` entry per `oci_core_drg`; each `oci_core_drg_attachment` becomes a `vcn` attachment with its own display name; a DRG without attachments and a single VCN gets an implicit attachment (`<drg>@<vcn>`, label `VCN attachment <vcn>`); IPSec / virtual circuit / RPC resources referencing the DRG become `ipsec` / `virtual_circuit` / `rpc` attachments (address `<resource>@<drg>`, `target` = the on-prem hub item: CPE for IPSec when present, else the resource itself). No DRG item is appended to VCN gateways or hub items.
- `_build_hub()`: on-premises items only; name `On-premises` when a CPE / IPSec / VC exists, `Remote region` when only RPCs exist; `link_label` = `null`.
- `_build_gateways()`: LPG gateways carry `peer` (resolved `peer_id`); `_build_edges()` emits one `Local Peering` attachment-kind edge per LPG pair (lower address first) and no longer emits CPE -> DRG edges (the layout draws attachment connectors from `drgs[]`).
- `_build_items()`: services get `regional = rtype in REGIONAL_TYPES`.
- `model_addresses()` yields DRG and attachment addresses; `select_vcn()` drops VCN attachments of removed VCNs; `validate_model()` checks `drgs`, `attachments`, `peer`, `regional`, `drg_style`; `summarise()` reports DRGs and attachments.

`scripts/query_tenancy.py`: `_REF_FIELDS` gains `peer_id`; docstring updated; synthetic `drgattachment` entities already flow into `_build_drgs()`. Tests updated for the v2 shape (hub = CPE only, gateways `{igw, nat, sgw}`, `drgs[0].attachments`).

## 10. Documentation and examples (D11)

- `examples/generate_reference_layout.py`: `hub` keeps the CPE (`Corp VPN`), `drgs = [{"name": "drg", "address": "drg", "label": "Dynamic Routing\nGateway (DRG)", "attachments": [{"type": "vcn", "vcn": "Spoke-VCN-D", "address": "drg-att-spoke", "label": "VCN attachment\nSpoke-VCN-D"}]}]`, edge `cpe -> drg` `IPSec VPN` (kind data); `services` items become regional automatically; `OCI_Architecture.drawio` regenerated from it.
- `examples/generate_demo_diagram.py`: page 1 built through `oci_layout.build_diagram` from a two-VCN hybrid model with an IPSec attachment and the four connector kinds (`drg_style="icon"`); page 2 the same model with `drg_style="box"`; page 3 the NSG rule table. The `smoke_test.sh` gate runs unchanged.
- `examples/make_screenshots.py`: detail crop follows the SGW / bottom gateways of the new geometry; requires draw.io desktop (not installed on the build machine at the time of writing: the regeneration step is documented and skipped when the binary is absent).
- SKILL.md: sections 1 (items 3, 8, 9, 10), 2 (schema v2, `drgs`, `drg_style`, `regional`, `peer`), 3 (constants, order of operations), 4 (mapping table rows for DRG, attachments, LPG, RPC, CPE), 6 (worked example: DRG at region level), 7 (acceptance criteria: "DRG outside every VCN, attachments adjacent, gateways on the VCN edge, OSN panel right of the VCNs").
- `commands/drawio-architect.md`: Step 2.4.5-2.4.7 routing rules, Step 3 template (`drgs`), Step 5.4 checklist, "Diagram types" table, description version.
- `references/oracle-styles.md`: `drg` style, `ociGroup` token, `add_box` style, edge kind table, legend defaults, OSN provenance note; `references/gotchas.md`: new items for DRG placement / foreign containment / straddle tolerance and the schema-2 migration; item 5 example rewritten.
- READMEs (root and plugin), repo `CLAUDE.md`, `CHANGELOG.md` `[1.3.0]`; version strings in `plugin.json`, `drawio_builder.py`, SKILL.md, command, references, READMEs, `CLAUDE.md`, demo docstring and `tests/test_builder.py`.

## 11. Testing strategy

- `tests/test_builder.py`: edge kinds (style tokens per kind and per profile), legend entries, `drg` group style and `ociGroup` token, `add_box`, `label_fill`, `ociRole=drg`, rule 3 straddle tolerance (probe B becomes clean), rule 7 foreign containment (region-parented icon inside a VCN -> error; border-centred -> clean; DRG message text; hand-written XML with heuristics).
- `tests/test_oci_topology.py` (new): `classify_topology` for every class, `choose_drg_style`, `is_regional` (override, table, unknown), `migrate_legacy_model` (hub DRG, gateway DRG, link_label -> edge, implicit attachment, warnings, idempotent on v2 input, input not mutated).
- `tests/test_oci_layout.py` (new): builds models through `build_diagram` and asserts parent ids and geometry: DRG parent = region; attachment boxes adjacent (x/y relations) and their edges have `endArrow=none`; gateways parented to the region with glyph centre on the border line; OSN panel right of the last VCN with the regional items and no VCN services panel; SGW -> OSN edge; LPG side selection; box style group type `drg`; legacy model migration warnings; CLI `--drg-style`; `validate()` returns no errors for each model.
- `tests/test_parse_terraform.py` / `tests/test_query_tenancy.py`: updated expectations plus a new `hub_spoke` HCL fixture (two VCNs, DRG with two attachments, LPG pair, RPC, virtual circuit, regional services).
- End-to-end (`tests/test_oci_layout.py::EndToEndTests`): parse the `three_tier` and `hub_spoke` fixtures -> `build_diagram` -> write -> `check_overlaps.main([...]) == 0`; the reference `MODEL` and the demo generator go through the same gate.
- Final gate: `python3 -m unittest discover -s oci-drawio-architect/tests`, `check_overlaps.py` on the reference, demo and `OCI_Architecture.drawio`, `smoke_test.sh` with `SMOKE_SKIP_PNG=1`, `pack.sh` dry run into a temp directory.

## 12. Migration and compatibility

- Schema-1 models keep working: the layout migrates them (D9) and prints warnings; `hub.link_label` still links consecutive hub items; edges addressed to a migrated DRG (`"source": "drg"`) resolve to the DRG icon; `services`/`services:<vcn>` endpoints resolve to the OSN panel when no per-VCN services panel remains.
- Cell ids of unchanged items are stable (`key=` from addresses); DRG and attachment ids follow the addresses; gateways keep their address ids but change parent (region).
- Style output changes: containers carry an `ociGroup` token; DRG icons an `ociRole` token; dashed edges drawn with `kind="control"` gain an open arrowhead (plain `dashed=True` keeps the profile behaviour). The `v1.0` profile keeps its geometry and colours; the added tokens do not change rendering.
- `parse_terraform.py --vcn NAME` keeps DRG entries and prunes attachments of dropped VCNs.
- Existing generated scripts that call `write_diagram(MODEL, path)` need no change.

## 13. Roadmap, not in v1.3.0

- Diagram purpose selection (network / data flow / security / inventory / dependency / HA).
- Resource filtering by tag, compartment, region, VCN, subnet, resource type or environment.
- Selectable detail levels (executive / application / network / engineering).
- Label modes Minimal / Network / Detailed and configurable caption fields.
- draw.io view layers (application, network, routes, security, IAM, observability, ...).
- A separate global-services bucket (IAM, policies, compartments, public DNS, audit) distinct from the OSN panel.
- "All resources" versus "participating resources" mode.
- Multi-region canvases and cross-region Remote Peering between two region boxes.
- An Internet location box outside the region with the IGW on the facing border.
- Any draw.io MCP connector integration.

## 14. Open questions

None blocking. Two choices recorded for transparency: (1) VCN columns stay side by side (Oracle stacks VCNs vertically in slide 31; connectors from the DRG column to the second and later VCNs route around the first through the region gutters - acceptable for <= 3 VCNs, which is the documented split threshold); (2) the OSN panel keeps the Rose look per D6 with a provenance note rather than adopting the slide-19 Neutral 3 spec.
