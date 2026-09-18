---
name: oci-drawio-architect
description: Generate deterministic draw.io diagrams of Oracle Cloud Infrastructure architectures (Redwood container styles, embedded OCI icons, auto-routed edges) from Terraform or a description. Use when the user says "draw.io OCI", "diagram this architecture", "drawio with OCI icons", "OCI architecture diagram" or "Terraform to draw.io".
---

# OCI draw.io Architect (plugin v1.3.0)

Diagrams are data: a MODEL dict laid out by `scripts/oci_layout.py` on top of `scripts/drawio_builder.py` (DrawioBuilder v1.3.0). The `/drawio-architect` command is the workflow; this skill holds the conventions, the schema and the API. Always `sys.path.insert(0, "<abs>/oci-drawio-architect/scripts")` and import from the plugin - never copy `drawio_builder.py` into a project (the copy loses the icon directory and drifts from the plugin).

## 1. Target look (the reference sample, `examples/generate_reference_layout.py`)

1. Title (`add_title`): bold `<Subject> - Architecture`, italic second line `<Region label> (<region>) - Compartment: <compartment>`; with a tenancy the first line is `<tenancy> - <Subject> - Architecture`. Optional logo top-right (148x39).
2. Region: solid Neutral-3 border, Neutral-1 fill, label = bare region id (`us-ashburn-1`) bold, top-left. Only title, notes and legend sit outside it.
3. On-premises panel (`onprem`): left of the DRG column, 180 px wide, vertically centred on the VCN stack, label `On-premises` (or the hub network name), one icon per row (pitch 200): CPE, FastConnect virtual circuit, RPC peer. Never the DRG.
4. DRG column (`drgs[]`): region-level DRG icon between the on-premises panel and the VCN columns, centred on the VCN stack; one rounded attachment box (100 px wide, 44 px tall minimum, Ivy border; taller when the display name needs more lines, which also widens the stacking pitch) per attachment beside it - VCN attachments on the side facing the VCNs, IPSec / FastConnect / RPC attachments on the side facing the on-premises panel - each linked to its target by an arrowhead-less `attachment` connector (`Site-to-Site VPN`, `FastConnect`, `Remote Peering`). `drg_style` `icon` (default) or `box` (dashed `DRG: <name>` group); `auto` picks `box` above 4 attachments.
5. VCN: label `VCN: <name> (<cidr>)`, Sienna dashed 2 px. Several VCNs are columns left to right, 45 px apart.
6. Subnet: label `<name> (<cidr>)` (+ ` - public` when `public`), Sienna dashed 1 px. Row 1 holds lb -> app -> compute -> mgmt -> other subnets in traffic order, 2 icon columns each, wrapping to a new row past 1000 px; data-tier subnets are stretched under the rows (up to 5 columns).
7. Icon order inside a subnet: primary resource (LB, VM, DB) -> attached resources (block volume, certificate, WAF). Route tables, security lists and NSGs are never icons in a subnet (item 11).
8. Caption convention: `Role\nidentifier\nsize` - at most 3 lines of about 16 characters at 11 px, centred under a 75x95 slot; every glyph is fitted to 70x70 so all icons look the same size.
9. OCI Services panel (`services`): inside the VCN, right of row 1, only for VCN-resident services without a subnet. Regional services (Logging, Logging Analytics, Monitoring / Alarms, Notifications, Events, Connector Hub, IAM / Identity, Vault / KMS, Certificates, Object Storage, OCIR, AI services, Data Safe, Data Science, Analytics, Streaming, Queue, APM, DevOps, DNS zones, WAF policies; full list `oci_topology.REGIONAL_ICON_KEYS`) go to ONE region-level `Oracle Services Network` panel right of the VCN columns, height matched to the tallest VCN, fed by an `attachment` connector from the Service Gateway. `"regional": false` on an item keeps it in the VCN panel.
10. Gateways straddle the VCN border (glyph centre on the line, caption with an opaque region-fill background, parent = region): IGW and NAT on the bottom border (pitch 180), the Service Gateway on the right border facing the OSN panel, LPGs on the border facing their peer VCN (`peer` = peer LPG address or VCN name, set on both sides of a pair; unknown peer -> bottom) linked by a `Local Peering` attachment connector.
11. Security constructs are badges: a subnet's route table and security lists are half-size (22 px) caption-less icons straddling the subnet's top-right corner (route table centred on the corner, security lists one badge to its left; toolkit slide 18 uses the icons at half size as labels of the subnet box); an NSG is a 22 px shield badge in the top-right of the protected resource's 75x95 slot. Names go to the tooltip and metadata. Model fields: `subnet.route_table`, `subnet.security_lists`, `item.nsgs`.
12. Edges: `data` solid Bark open arrow (label = protocol / port); `control` dashed Bark open arrow (management / administrative); `association` dotted, no arrowhead (dependency, configuration relationship); `attachment` thin solid, no arrowhead (structural: DRG attachments, LPG pairs, SGW -> OSN); `analytics` solid Sienna and `datalake` dashed purple remain. Routed automatically through the gutters.
13. No legend by default (`legend=True` only on request or with 3+ edge kinds); `notes` text appears right of the title only when set.
14. Page = content + 20 px margin rounded up to 10 (`fit_page`), white background, `default` style profile, Oracle Sans font stack.

## 2. Model schema (`oci_layout.py` docstring)

Every key is optional except `subject` and `vcns` (or `hub`). JSON-serialisable.

```python
MODEL = {
  "subject": "Spoke-VCN-D", "region": "us-ashburn-1", "region_label": "Ashburn",
  "compartment": "Spoke-VCN-D", "tenancy_name": None,
  "drg_style": "auto",                # auto | icon | box (CLI --drg-style overrides)
  "hub": {"name": "On-premises",      # on-premises side only: CPE, IPSec, virtual circuit, RPC peer
          "items": [{"icon": "cpe", "label": "Corp VPN\n(10.0.0.0/8)", "address": "cpe"}],
          "link_label": None},
  "drgs": [{"name": "drg", "address": "drg", "label": "Dynamic Routing\nGateway (DRG)",
            "attachments": [{"type": "vcn", "vcn": "Spoke-VCN-D", "address": "drg-att-spoke",
                             "label": "VCN attachment\nSpoke-VCN-D"},
                            {"type": "ipsec", "target": "cpe", "address": "vpn@drg", "label": "vpn-hq"}]}],
  "vcns": [{
     "name": "Spoke-VCN-D", "cidr": "10.0.0.0/16",
     "subnets": [{"name": "sn-priv-lb", "cidr": "10.0.0.0/24", "tier": "lb", "public": False,
                  "items": [{"icon": "load_balancer", "label": "Load Balancer\n10.0.0.23",
                             "address": "lb", "metadata": {"ocid": "..."}, "tooltip": "...",
                             "nsgs": ["nsg-lb"]}],
                  "route_table": "rt-lb", "security_lists": ["sl-lb"]}],
     "services": [{"icon": "logging", "label": "Logging", "address": "logs", "regional": True}],
     "services_label": "OCI Services",
     "gateways": [{"icon": "service_gateway", "type": "sgw", "label": "Service\nGateway", "address": "sgw"},
                  {"icon": "remote_peering_gateway", "type": "lpg", "label": "LPG", "address": "lpg-a",
                   "peer": "lpg-b"}]
  }],
  "services": [],                                 # more regional services; join the OSN panel
  "edges": [{"source": "lb", "target": "app-vm", "label": "3000 / 8000", "kind": "data"}],
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

## 3. Layout recipe (`build_diagram`)

`build_diagram(model, style_profile="default", legend=False, logo=None, page_name=None, title=True, max_row_w=MAX_ROW_W, drg_style=None) -> DrawioBuilder` and `write_diagram(model, out_path, strict=False, render_fmt=None, **opts) -> Path` (build + `validate` + `write`, optional draw.io export). CLI: `python3 oci_layout.py model.json -o out.drawio [--profile default|official|v1.0] [--legend] [--logo FILE] [--strict] [--render png|svg|pdf] [--drg-style auto|icon|box]`.

Order of operations: migrate legacy model -> classify topology -> title -> region -> for each VCN: subnet rows (each subnet: icons with their NSG badges -> `fit_to_children(subnet)` -> route table / security list badges on the subnet's top-right corner) -> VCN-resident services panel -> data subnets -> `fit_to_children(vcn)` -> border gateways (region children) -> optional region-level OCI Services panel -> Oracle Services Network panel -> on-premises panel -> DRG column -> `fit_to_children(region)` -> SGW -> OSN connectors -> attachment connectors -> model edges -> optional legend -> `fit_page()`.

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
| `BADGE_RESERVE` (title width the corner badges reserve) | 52 | | |

## 4. Icon selection

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
| `oci_containerengine_cluster` / `_node_pool` | `oke` | compute subnet |
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
| `oci_identity_compartment` / `_policy` / `_dynamic_group` / `_user` | (container `compartment`) / `policy` / `user_group` / `user` | custom layouts only |
| `oci_cloud_guard_*` / `oci_data_safe_*` / `oci_vulnerability_scanning_*` | `cloud_guard` / `data_safe` / `vuln_scanning` | `services` (`regional: true`, OSN panel) |
| `oci_core_public_ip` / `oci_core_vtap` / `oci_*_private_endpoint` | `ip_pools` / `vtap` / `private_endpoint` | lb subnet / mgmt / data |

## 5. Style rules

| Profile | Use when | Differences |
|---------|----------|-------------|
| `default` | always, unless asked otherwise | reference look: 12 px container labels, 11 px subnet labels, 1.5 px rounded edges, dash pattern `6 3`, dashed edges without arrowheads |
| `official` | the customer wants strict OCI Architecture Diagram Toolkit v24.2 fidelity | 12 px everywhere, 1 px square edges, 10.5 px edge labels, dashed edges keep the open arrow, AD/FD arcs 8/7 |
| `v1.0` (`sample` alias) | regenerating diagrams made with plugin v1.0.x without a visual diff | 13 px VCN label, `spacingLeft=3` |

1. Fonts: `Oracle Sans,Arial,Helvetica,sans-serif` for everything (title 18 px bold + italic line, captions 11 px, edge labels 12 px). Override with `DrawioBuilder(font_family=...)` only on request.
2. Colours come from `drawio_builder.COLORS`; full table and every container style string in `references/oracle-styles.md`. The ones you will meet: Bark `#312D2A` (text, edges, services border), Sienna `#AE562C` (VCN/subnet/compartment borders, analytics edges), Neutral 3 `#9E9892` (region/tenancy/AD/FD borders), Neutral 1 `#F5F4F2` (region/onprem fill), Rose `#A36472` (Oracle Services Network), `#7B61FF` (datalake edges, project extension).
3. Never restyle cells by hand (`style_extra` is for one-off tweaks such as `fontStyle=2`); container looks are fixed per `group_type`.

## 6. Custom layouts with DrawioBuilder

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

Multi-page: `d.add_page("Security", 800, 400)` makes the new page current (`use_page(0)` to return); call `add_title`/`fit_page` per page; `validate()` covers all pages. Legend: `_, _, _, bottom = d.content_bbox(); d.add_legend(PAD, bottom + GAP)` before `fit_page()`. Table: `d.add_table([["Direction", "Source", "Ports"], ["Ingress", "0.0.0.0/0", "443"]], PAD, 75, col_widths=[80, 170, 60], title="nsg-app (1 rule)")`. Demonstration of the recipe on a two-VCN hybrid model (both `drg_style` options, all four edge kinds, legend) plus a third page built with the custom API (`add_table` for an NSG rule list): `examples/generate_demo_diagram.py`.

## 7. Acceptance criteria (all mandatory)

1. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_overlaps.py" <file>.drawio` exits 0 and prints `OK: no container overlaps or layout errors (...)`.
2. Zero `ERROR:`/`OVERLAP:` lines (unknown parents or endpoints, intersecting containers, shapes outside their parent, icon/caption collisions).
3. Every `WARNING:` line was read and either fixed (caption > 3 lines; estimated crossing; content exceeds page) or confirmed harmless in the PNG.
4. PNG self-review (`render_drawio.py <file> -f png`, then Read the PNG): glyphs uniform; captions legible, 3 lines max, inside their container, no overlaps; edges in gutters, none across icons or captions, labels readable; on-premises panel and DRG column centred on the VCN stack; DRG outside every VCN with its attachment boxes beside it; gateways centred on the VCN border; regional services in the Oracle Services Network panel right of the VCNs; route tables and security lists as badges on the subnets' top-right corners and NSGs as shield badges on their resources, never as workload icons; nothing outside the region; no large empty area; title and region label follow section 1.
5. The generated script imports from the plugin `scripts` directory and contains no copied builder code; file size is roughly 7-13 KB per icon (the 31-icon reference is 280 KB).

## 8. Failure handling

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

## 9. Key references

- Command workflow: `${CLAUDE_PLUGIN_ROOT}/commands/drawio-architect.md`
- Layout recipe and MODEL schema: `${CLAUDE_PLUGIN_ROOT}/scripts/oci_layout.py`
- Builder API: `${CLAUDE_PLUGIN_ROOT}/scripts/drawio_builder.py` (v1.3.0, standard library only)
- Model producers: `${CLAUDE_PLUGIN_ROOT}/scripts/parse_terraform.py` (Terraform dir / plan / state -> model.json), `${CLAUDE_PLUGIN_ROOT}/scripts/query_tenancy.py` (experimental as-built via OCI CLI)
- Topology helpers: `${CLAUDE_PLUGIN_ROOT}/scripts/oci_topology.py`
- Gate and tools: `${CLAUDE_PLUGIN_ROOT}/scripts/check_overlaps.py`, `${CLAUDE_PLUGIN_ROOT}/scripts/render_drawio.py`, `${CLAUDE_PLUGIN_ROOT}/scripts/detect_settings.py`, `${CLAUDE_PLUGIN_ROOT}/scripts/smoke_test.sh`
- Examples: `${CLAUDE_PLUGIN_ROOT}/examples/generate_reference_layout.py` (MODEL -> `write_diagram`, reproduces the reference), `${CLAUDE_PLUGIN_ROOT}/examples/generate_demo_diagram.py` (recipe on a hybrid model in both `drg_style`s, four edge kinds, legend, plus a custom-API NSG table page)
- Icons: `${CLAUDE_PLUGIN_ROOT}/icons/` - 159 SVGs in 12 categories, 206 aliases; catalog `${CLAUDE_PLUGIN_ROOT}/skills/oci-drawio-architect/references/icon-catalog.md`
- Styles: `${CLAUDE_PLUGIN_ROOT}/skills/oci-drawio-architect/references/oracle-styles.md`; pitfalls: `${CLAUDE_PLUGIN_ROOT}/skills/oci-drawio-architect/references/gotchas.md`
