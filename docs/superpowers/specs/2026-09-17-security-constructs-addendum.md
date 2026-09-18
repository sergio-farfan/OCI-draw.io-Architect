# Security Constructs as Badges (v1.3.0 addendum) - Design Specification

**Author:** Sergio Farfan
**Date:** 2026-09-17
**Plugin:** oci-drawio-architect 1.3.0 (addendum to `2026-09-17-topology-aware-placement-design.md`)
**Repository:** `OCI-draw.io-Architect` (public, MIT), branch `feature/v1.3.0-topology-aware-placement`
**Implementation plan:** `docs/superpowers/plans/2026-09-17-security-constructs-task14.md` (Tasks 14 and 15, executed after Tasks 1-13 of the main plan)

## 1. Goal

Draw route tables, security lists and network security groups (NSGs) the way Oracle's toolkit and the team's diagram guidelines draw them: **attached to the boundary or resource they govern**, never as captioned workload icons inside a subnet.

- A **route table** and the **security lists** of a subnet become one or two half-size badges straddling the subnet's **top-right corner** (route table centred on the corner, security lists one badge to its left); no caption, the display names live in the cell tooltip and metadata.
- An **NSG** becomes a small shield badge in the **top-right of the protected resource's icon slot**, visually distinct from the subnet badges; no caption, NSG names in the tooltip.
- The model carries the constructs as **fields** (`subnet.route_table`, `subnet.security_lists`, `item.nsgs`); `parse_terraform.py` and `query_tenancy.py` fill them from the Terraform / topology attributes; the validator accepts the badge geometry and still flags every other overlap.

Everything stays standard-library Python 3.9+, deterministic (`key=` ids) and gated by `check_overlaps.py`.

## 2. Sources of the rules

| Source | What it establishes | Where used |
|--------|---------------------|------------|
| The team's diagram guidelines, section 3 (bullets on route tables, security lists and NSGs) and the immediate reviewer feedback "attach route and security constructs visually to the resources or boundaries they govern" | Route tables and security lists belong to the subnet boundary; NSGs belong to the resource; none of them is a workload | B1, B2, B3 |
| OCI Architecture Diagram Toolkit style guide (`OCI_Icons.pptx`, v24.1, slide 18), verified in the local copy `oci-iconset/raw/OCI_Icons.pptx`: "VCN, routing table, and security list icons are used at half size as labels to differentiate the VCN and subnet. In complex diagrams omit them to reduce clutter in the diagram." | Half-size icons used as labels of the subnet box, not as content; the sample usage diagrams the slide points to place the label on the subnet's top-right corner | B1, B4 (`BADGE_SIZE`) |
| Toolkit v24.2 `.drawio`, page "Start here", changelog cell, verified in `oci-iconset/tools/drawio/OCI Architecture Diagram Toolkit v24.2.drawio`: "Add a combination icon for situations when both a route table and security list icon are needed." Page "Icons" lists the pair "Route Table" / "Security List" as one stacked shape; slide 36 of the PPTX lists "Route Table and Security List" in the networking set | Oracle draws both constructs together on the boundary. The plugin's bundled set (v24.2 SVG export) has the separate glyphs `networking_route_table.svg` and `identity_and_security_security_lists.svg` and no combined glyph, so the two badges are drawn side by side from the corner leftwards | B1 |
| Oracle landing-zone reference architecture (CIS OCI Foundations Benchmark), https://docs.oracle.com/en/solutions/cis-oci-benchmark/ | NSGs drawn as shield icons on the protected resources, distinct from the subnet route-table / security-list badge | B2 |
| OCI Python SDK model reference, `oci.core.models.Subnet` (https://docs.oracle.com/en-us/iaas/tools/python/latest/api/core/models/oci.core.models.Subnet.html): `route_table_id` "The OCID of the route table that the subnet uses"; `security_list_ids` "The OCIDs of the security list or lists that the subnet uses. Remember that security lists are associated with the subnet, but the rules are applied to the individual VNICs in the subnet." | Route table and security lists are subnet attributes -> subnet boundary badge | B1, B3, B7 |
| OCI Python SDK model reference, `oci.core.models.Vnic` (`.../oci.core.models.Vnic.html`): `nsg_ids` "A list of the OCIDs of the network security groups that the VNIC belongs to." | NSG membership is a VNIC (resource) attribute -> resource badge | B2, B3, B7 |
| OCI Python SDK model reference, `oci.core.models.Topology` (`.../oci.core.models.Topology.html`): `entities` "Lists entities comprising the virtual network topology." (`list[object]`), `relationships` "Lists relationships between entities in the virtual network topology." | Topology entities are the resource objects themselves, so `securityListIds` / `routeTableId` (Subnet) and `nsgIds` (Vnic) are present in `oci network vcn-topology get` output | B7 |
| Terraform provider `oracle/oci` resource docs (raw GitHub `website/docs/r/*.html.markdown`, master): `oci_core_subnet` `route_table_id` ("The OCID of the route table the subnet will use. If you don't provide a value, the subnet uses the VCN's default route table.") and `security_list_ids`; `oci_core_instance` `create_vnic_details.nsg_ids` ("A list of the OCIDs of the network security groups (NSGs) to add the VNIC to."); `oci_load_balancer_load_balancer` `network_security_group_ids` ("An array of NSG OCIDs associated with this load balancer."); `oci_network_load_balancer_network_load_balancer` `network_security_group_ids`; `oci_database_db_system` `nsg_ids` ("The list of OCIDs for the network security groups (NSGs) to which this resource belongs."); `oci_core_vnic_attachment` `instance_id` and `create_vnic_details.nsg_ids` | Exact attribute names the parser reads | B6 |

Not verified from a source and therefore not claimed: the exact pixel offset Oracle uses for the corner label. The plugin fixes it as "badge centre on the corner" (section 6).

## 3. Current behaviour (after Tasks 1-13) and gaps

| Area | Behaviour | Location | Gap |
|------|-----------|----------|-----|
| Parser | `oci_core_route_table`, `oci_core_security_list` and `oci_core_network_security_group` become items of `vcn.controls` (`CONTROL_TYPES`); the recipe never draws `controls`. Subnet `route_table_id` / `security_list_ids` and item `nsg_ids` / `network_security_group_ids` references are collected in `Res.refs` but not used | `parse_terraform.py` `CONTROL_TYPES`, `_build_items`, `_build_subnets` | Nothing tells the layout which subnet a route table or security list governs, or which resource an NSG protects |
| Skill guidance | Section 4 mapping table: `oci_core_network_security_group` -> `nsg` -> "last item of its subnet"; `oci_core_security_list` / `oci_core_route_table` -> "omit (or `add_table` on page 2)"; section 1 item 6 and command step 2.4.4 end with "NSG last" | `SKILL.md`, `commands/drawio-architect.md` | Generators draw NSGs as captioned workload icons - the pattern the team's guidelines reject |
| Builder | `add_icon()` always reserves a 75x95 slot and a caption; explicit `w`/`h` sizing exists but has no notion of a decorated host | `drawio_builder.py` `add_icon` | No caption-less, half-size, host-aware primitive |
| Validator | Rule 3 accepts an icon whose glyph centre lies within `STRADDLE_TOL` of its parent's border (Task 3); rule 4 flags any two overlapping leaves; rule 6 counts every leaf as an obstacle for edges it does not terminate | `validate_registry` | A shield over its own host icon is a rule-4 error; a badge over an endpoint's slot creates spurious rule-6 warnings |
| Tenancy | `_REF_FIELDS` lacks `security_list_ids`, `nsg_ids`, `network_security_group_ids`; the VNIC -> host relationship copies only `subnet_id` | `query_tenancy.py` | Live models cannot carry the fields |
| Demo | Page 3 shows an NSG rule table; no diagram shows a route table, security list or NSG on the topology | `examples/generate_demo_diagram.py` | The smoke test does not exercise the badges |

## 4. Design decisions (fixed)

- **B1** Route tables and security lists are drawn as badges on the **subnet boundary**, parented to the subnet: the route-table badge is centred on the subnet's top-right corner; the security-list badge is centred `BADGE_SIZE + BADGE_GAP` (26 px) to its left on the same top border (it takes the corner when the subnet has no route table). One badge per construct kind: several security lists share one badge whose tooltip lists them all. Badges have no caption; names go to the tooltip (`Route table: rt-public`, `Security lists: sl-lb, sl-shared`) and to metadata (`route_table` / `security_lists`, comma-separated). Cell ids: `<subnet id>-rt`, `<subnet id>-sl`.
- **B2** NSGs are drawn as a badge on the **protected resource**: a `BADGE_SIZE` (22 px) square whose top-right corner coincides with the top-right corner of the host's 75x95 slot (slot-local box `(53, 0, 22, 22)`, over the 70x70 glyph area, clear of neighbouring slots and of the caption band that starts at y = 97). Parent = the host icon's parent; id `<host id>-nsg`; tooltip `NSG: nsg-app` / `NSGs: nsg-app, nsg-mgmt`; metadata `nsgs`. The glyph is the toolkit NSG shield (`identity_and_security_nsg.svg`, key `nsg`).
- **B3** Model fields (schema 2, all optional): `subnet.route_table` = `str | {"name", "address"} | null`; `subnet.security_lists` = `[str | {"name", "address"}]`; any icon item may carry `nsgs` = `[str | {"name", "address"}]`. When an entry has an `address`, the badge is registered as an edge endpoint for that address (first drawn badge wins when several subnets or items share a construct). `vcn.controls` stays in the parser output as the inventory of these resources (unchanged shape, still not drawn). Hand-placed `nsg` / `security_list` / `route_table` icon keys remain legal item icons, but the skill and command tell the generator to prefer the badge fields.
- **B4** Builder primitive `DrawioBuilder.add_badge(icon_key, cx, cy, parent="1", host=None, size=BADGE_SIZE, key=None, metadata=None, tooltip=None) -> str`: a caption-less image cell centred on `(cx, cy)` in parent coordinates, style `shape=image;...;ociRole=badge;ociHost=<host id>;image=...`, registered as kind `icon` with `slot_* = cell`, `label_id=None`, `badge=True`, `host=<id or None>`. `fit_to_children()` ignores badge children (a badge never grows its host). Routing: a badge hosted by an icon is not a separate obstacle (the host footprint already covers it); a badge hosted by a container is an obstacle so connectors leave the corner alone. Constants `BADGE_SIZE = 22`, `BADGE_GAP = 4` (exported).
- **B5** Validator: rule 3 needs no new code - a badge is an `icon` whose centre lies on its parent's border, which the Task 3 branch `_centre_within(pbox, local, STRADDLE_TOL)` accepts (tests pin this). Rule 4 skips a pair when one leaf is a badge whose `ociHost` is the other leaf (a badge over any other leaf is still `ERROR: ... overlaps ...`). Rule 6 skips a badge obstacle when its host is an endpoint of the edge. `_attach_captions` never attaches a caption to a badge. Rule 7 (foreign containment) is unaffected: a badge shares its host's ancestor chain. All of this reads the style tokens, so `validate_file()` / `check_overlaps.py` apply the same rules to written files.
- **B6** Parser (`parse_terraform.py`): `_build_subnets` fills `route_table` from `route_table_id -> oci_core_route_table` and `security_lists` from `security_list_ids -> oci_core_security_list`; `_build_items` fills `item.nsgs` from `nsg_ids` / `network_security_group_ids` resolving to `oci_core_network_security_group` (covers `oci_core_instance.create_vnic_details.nsg_ids`, `oci_load_balancer_load_balancer.network_security_group_ids`, `oci_network_load_balancer_network_load_balancer.network_security_group_ids`, `oci_database_db_system.nsg_ids`, `oci_mysql_mysql_db_system` and any other item type carrying those attributes); a new `_build_vnic_nsgs` pass merges `oci_core_vnic_attachment.create_vnic_details.nsg_ids` into the attached instance's `nsgs` (by `instance_id`). Entry shape `badge_ref(name, address) -> {"name", "address"}` with `name = display_name or resource name or default`. HCL, plan-JSON and state-JSON modes all work through the existing `Res.refs` machinery (`_collect_attrs` flattens nested blocks; `_flatten_values` / `_walk_expressions` flatten nested JSON). `validate_model` checks the three fields. The parser never emitted these resources as subnet items (`_build_items` places by `subnet_id`, which they lack), so nothing is removed.
- **B7** Tenancy (`query_tenancy.py`): `_REF_FIELDS` gains `security_list_ids`, `nsg_ids`, `network_security_group_ids`; the VNIC -> host relationship copies `nsg_ids` as well as `subnet_id`, so instances get their NSGs through their VNICs. Everything else flows through the shared `ModelBuilder`. Documented gap: NSGs of a resource whose VNIC is not returned by the topology (for example a DB system whose `nsg_ids` is only on the resource object) are captured only when the entity itself carries the field.
- **B8** Documentation: SKILL.md (schema fields, mapping rows, acceptance item, API row, worked example), `commands/drawio-architect.md` (enrichment step 2.4.10, gate checklist, template), `oracle-styles.md` (provenance and `add_badge()` style), `gotchas.md` item 21, `check_overlaps.py` docstring, CHANGELOG 1.3.0 bullets, README "What's new in 1.3.0" bullets (root and plugin), repo `CLAUDE.md` API row and layout paragraph.
- **B9** The demo model exercises the badges (both layout pages); `smoke_test.sh` therefore gates them. The reference sample (`examples/generate_reference_layout.py`, `OCI_Architecture.drawio`) and the README screenshots are **not** changed by this addendum: they are regenerated by Task 11 for the topology changes, and a second regeneration for badges is not worth the churn in this release. Recorded as a deliberate choice.
- **B10** Stdlib-only Python 3.9+, deterministic ids, no icon-set change (the three glyphs are already bundled and aliased: `route_table`, `security_list`, `nsg`), conventional commits, no AI attribution.

## 5. Model schema v2 delta

```json
{
  "vcns": [{
    "name": "vcn-shop",
    "subnets": [{
      "name": "sn-lb-public", "cidr": "10.0.0.0/24", "tier": "lb", "public": true,
      "route_table": {"name": "rt-public", "address": "oci_core_route_table.public"},
      "security_lists": [{"name": "sl-app", "address": "oci_core_security_list.app"}, "sl-shared"],
      "items": [{
        "icon": "load_balancer", "label": "lb-shop", "type": "oci_load_balancer_load_balancer",
        "address": "oci_load_balancer_load_balancer.public", "metadata": {},
        "nsgs": [{"name": "nsg-lb", "address": "oci_core_network_security_group.lb"}]
      }]
    }, {
      "name": "sn-app", "cidr": "10.0.1.0/24", "tier": "app", "public": false,
      "route_table": "rt-private",
      "security_lists": [],
      "items": [{"icon": "vm", "label": "app-server", "type": "oci_core_instance", "address": "oci_core_instance.app",
                 "metadata": {}, "nsgs": ["nsg-app", "nsg-mgmt"]}]
    }],
    "controls": [{"icon": "route_table", "label": "rt-public", "type": "oci_core_route_table",
                  "address": "oci_core_route_table.public", "metadata": {}}]
  }],
  "edges": [{"source": "oci_core_route_table.public", "target": "oci_core_internet_gateway.igw",
             "label": "0.0.0.0/0", "kind": "control", "inferred": false}]
}
```

Rules:
- `route_table`: a string (display name), an object `{"name": str, "address": str | null}`, or `null` / absent. `security_lists` and `nsgs`: lists of the same two forms, `[]` or absent. Parser output always writes `route_table` and `security_lists` on every subnet and writes `nsgs` only on items that have at least one NSG.
- A string entry has no address and cannot be an edge endpoint; an object entry with an `address` registers the badge under that address (first badge drawn wins). Addresses are not required to be unique across badge fields, and `model_addresses()` does not yield them (the same addresses already appear in `vcn.controls`).
- `hub.items`, `drgs[]` and `gateways[]` entries ignore `nsgs` (they are placed by `place_icons` directly, not by `_icon_items`).
- Backward compatibility: models without the fields draw exactly as before; the fields are additive.

## 6. Geometry

Constants (`drawio_builder.py`): `BADGE_SIZE = 22` (half of the 45 px caption height and roughly a third of the 70 px glyph - the toolkit's "half size" relative to its 40-50 px icons), `BADGE_GAP = 4`.

Subnet-local coordinates, subnet width `w` after `fit_to_children()`:

| Badge | Centre | Box (x, y, w, h) | Parent | Id |
|-------|--------|------------------|--------|----|
| route table | `(w, 0)` | `(w - 11, -11, 22, 22)` | subnet | `<subnet id>-rt` |
| security lists (with a route table) | `(w - 26, 0)` | `(w - 37, -11, 22, 22)` | subnet | `<subnet id>-sl` |
| security lists (no route table) | `(w, 0)` | `(w - 11, -11, 22, 22)` | subnet | `<subnet id>-sl` |

Icon-slot-local coordinates, slot `(x, y, 75, 95)`, glyph cell `(x+2, y+5, 70, 70)` for a square glyph, caption from `y + 97`:

| Badge | Centre | Box | Parent | Id |
|-------|--------|-----|--------|----|
| NSG | `(x + 64, y + 11)` | `(x + 53, y, 22, 22)` | the host's parent | `<host id>-nsg` |

```
VCN: a (10.0.0.0/16)  (Sienna 2px dashed)
+-----------------------------------------------------------------------------+
|                                        ROW1_Y = 50                          |
|                                             [SL][RT]      <- centres (w-26,0) and (w,0),
|   sn-app (10.0.1.0/24)  (Sienna 1px dashed)  --+--+--       22x22 each, straddling the
|   +------------------------------------------ +  +--+       subnet's top border, RT on the corner
|   |                                              |  |
|   |   slot 75x95         slot 75x95             |  |
|   |   +--------[N]       +---------+            |    <- [N] = NSG badge, box (53, 0, 22, 22)
|   |   |  glyph   |       |  glyph  |            |       inside the host slot, over the glyph
|   |   |  70x70   |       |  70x70  |            |       area, clear of the caption band
|   |   +----------+       +---------+            |
|   |    App VM              Vault               |    <- captions from slot y + 97
|   |    10.0.1.5                                |
|   +------------------------------------------------+
|       H_GAP = 20 -> next subnet: 9 px clearance from the RT badge's 11 px overhang
+-----------------------------------------------------------------------------+
```

Clearances that keep the validator clean without new tolerances: the 11 px overhang above the subnet lies inside the VCN's 50 px title band (`ROW1_Y`); the overhang to the right lies inside the VCN's right padding (`PAD` = 20, `VCN_SIDE_PAD` = 60 when a right-border gateway exists, which puts the Service Gateway **slot** 11 px right of the badge - and its 70 px glyph cell, the box the validator compares, 13 px right of it) or inside the 20 px `H_GAP` before the next subnet; a data-tier subnet's badge sits 29 px below the row above (`V_GAP` = 40). The NSG badge never leaves its slot, so `COL_W` = 130 keeps it 55 px from the next slot, and the caption band starting at `slot y + 97` is 75 px below the badge.

Residual risk, accepted and recorded (not a new tolerance): a side gateway's caption is `LABEL_W` = 105 px wide and centred on its 75 px slot, so it starts 15 px **left** of the slot - 4 px inside the corner badge's x range. Only the vertical offset separates them: the caption of the gateway in side slot `k` occupies VCN-local `y` = `147 + 160k` to `192 + 160k` (`SIDE_GW_Y0 + k * SIDE_GW_PITCH + ICON_H + LABEL_GAP`, height `LABEL_H`), while a badge occupies its subnet's top edge +/- 11 px. Row 1 (`y` = 50) is clear of slot 0; a collision needs a second subnet row or a stretched data-tier subnet whose top edge falls in a caption band (`y` within 11 px of `147 + 160k`) **and** two or more right-border gateways, so `k >= 1`. The demo model, the reference sample and both fixtures are clear of it (the spoke VCN has a single right-border gateway). If a user model hits it the symptom is `ERROR: '<gateway label>' [abs ...] overlaps '(unlabelled)' [abs ...]`; the remedy is a layout change (side-gateway caption width or `VCN_SIDE_PAD`), which is out of scope here - see section 12.

## 7. Builder and validator changes (`scripts/drawio_builder.py`, `scripts/check_overlaps.py`)

- Constants `BADGE_SIZE`, `BADGE_GAP`; helper `_badge_host(entry) -> str | None` (the `ociHost` token when `ociRole=badge`, else `None`; `""` for a badge without host).
- `DrawioBuilder.add_badge(...)` as in B4. Errors: unknown parent (`ValueError`, via `_check_parent`), `size <= 0` (`ValueError`), unknown icon key (`ValueError` from `resolve_icon_path`).
- `fit_to_children`: skips children with `badge=True`.
- `_routing_shapes`: badge hosted by an `icon` -> skipped; other badges -> obstacle under their own id (absolute slot box).
- `_attach_captions`: skips badge icons.
- `validate_registry`: rule 4 skips `(a, b)` when `_badge_host(a) == b` or `_badge_host(b) == a`; rule 6 skips an obstacle whose `_badge_host` is the edge's source or target. Rule 3 unchanged (Task 3 straddle branch).
- `__all__` adds `BADGE_SIZE`, `BADGE_GAP`.
- `check_overlaps.py` docstring: one line noting that badges (`ociRole=badge`) may straddle their subnet's corner and cover their own host icon.

## 8. Layout changes (`scripts/oci_layout.py`)

- Imports `BADGE_GAP`, `BADGE_SIZE` from `drawio_builder`.
- Helpers: `_badge_refs(value) -> list[dict]` (normalises `str | dict | list` to `[{"name", "address"}]`, dropping empty names; a dict's name falls back to `label` then `address`), `_badge_tooltip(kind, refs) -> str` (`"NSG: a"`, `"NSGs: a, b"`), `_register_badge(reg, refs, bid)` (`reg.by_address.setdefault(address, bid)`), `_add_subnet_badges(d, sid, subnet, width, reg) -> list[str]`, `_add_nsg_badge(d, parent, cid, item, reg=None) -> str | None`.
- `_layout_subnet`: after the subnet's final size is known (both the `fit_to_children` and the empty-subnet `resize` branches) it calls `_add_subnet_badges(d, sid, subnet, w, reg)` and returns the unchanged `(sid, w, h)`.
- `_icon_items`: after `place_icons` it calls `_add_nsg_badge` for every `(item, id)` pair, then registers the items as before. This covers subnet items, the VCN-resident services panel, the region-level OCI Services panel and the OSN panel; hub items, DRGs and gateways are placed by `place_icons` directly and carry no badges.
- Docstring schema block gains the three fields.
- `examples/generate_demo_diagram.py` `DEMO_MODEL`: `sn-public` and `sn-app` get `route_table` and `security_lists`; `lb`, `app` and `adb` get `nsgs` (7 badges per layout page, 14 in the three-page file).

## 9. Parser and tenancy changes

`scripts/parse_terraform.py`:
- Constants `ROUTE_TABLE_TYPE`, `SECURITY_LIST_TYPE`, `NSG_TYPE`, `NSG_ATTRS = ("nsg_ids", "network_security_group_ids")`, `VNIC_ATTACHMENT_TYPES = frozenset({"oci_core_vnic_attachment", "oci_core_vnic"})`.
- `new_subnet()` returns `"route_table": None, "security_lists": []` in addition to the existing keys (`_loose_subnets` inherits them).
- `badge_ref(name, address=None) -> dict`.
- `ModelBuilder._badge_ref(res, default)`, `_nsg_refs(res)`, `_build_vnic_nsgs()`; `_build_subnets` and `_build_items` fill the fields; `build()` calls `_build_vnic_nsgs()` right after `_build_items()`.
- `_validate_badge_refs(errors, value, path, single=False)`; `_validate_item` checks `nsgs` when present; the subnet loop checks `route_table` (single) and `security_lists`.
- Module docstring documents the fields.

`scripts/query_tenancy.py`:
- `_REF_FIELDS` gains `("security_list_ids", "security_list_ids")`, `("nsg_ids", "nsg_ids")`, `("network_security_group_ids", "network_security_group_ids")`.
- `apply_relationships`: the VNIC -> host copy loops over `("subnet_id", "nsg_ids")`.
- Docstring sentence on the badge fields and the documented gap (B7).
- Fixture `tests/fixtures/tenancy/topology_bundle.json`: `security-list-ids` on `sn-lb-public`, `nsgIds` on the VNIC, `network-security-group-ids` on the load balancer, two `NetworkSecurityGroup` entities (`nsg-app`, `nsg-lb`).

## 10. Documentation

- `SKILL.md`: section 1 item 6 (icon order) loses "NSG last" and a new item describes the badges; section 2 schema example and a new rule 8; section 3 order of operations and the constants row `BADGE_SIZE` / `BADGE_GAP`; section 4 rows for `oci_core_network_security_group`, `oci_core_security_list` / `oci_core_route_table`; section 6 API row for `add_badge` and one `add_badge` line in the worked example; section 7 item 4 acceptance text "route tables and security lists as subnet-corner badges, NSGs as resource badges, never as workload icons"; section 8 row for a badge overlapping a foreign icon.
- `commands/drawio-architect.md`: step 2.4.4 (item order) and new step 2.4.10 (security constructs); step 3 template fields; step 5.4 checklist.
- `references/oracle-styles.md`: section 1 provenance bullet (slide 18 half-size labels, v24.2 changelog combination icon, bundled glyphs side by side); section 4 `### subnet` note; section 5 `### add_badge()` with the style string.
- `references/gotchas.md`: `## 21. Security constructs are badges, not workload icons`.
- `CHANGELOG.md` `[1.3.0]`: "Added" bullets for the badges, the fields, the parser / tenancy extraction and the validator rules; "Changed" bullet for the demo and the skill guidance.
- `README.md` (root) and `oci-drawio-architect/README.md`: one bullet each in "What's new in 1.3.0".
- Repo `CLAUDE.md`: API table row for `add_badge`; one sentence in the `oci_layout.py` paragraph.

## 11. Testing strategy

- `tests/test_builder.py` `TestBadges`: corner badges centre on the subnet's top-right corner within 1 px and validate clean in memory and after `validate_file()`; style tokens, geometry, wrapper attributes, no caption; NSG badge inside the host slot, overlapping the glyph, clean; badge over a foreign icon is one `overlaps` error; two corner badges do not collide and `fit_to_children()` returns the same size; routing obstacles (corner badge in, NSG badge out); error cases and exports.
- `tests/test_oci_layout.py` `BadgeLayoutTests`: a model with string, dict and list forms; route-table badge centre = subnet top-right corner (two subnets); security-list badge 26 px left, or on the corner when no route table; NSG badge box = top-right 22x22 of the host slot for three hosts, parented like the host; tooltips and `ociRole=badge`; a badge address resolves as an edge endpoint; `errors_of() == []`, `check_overlaps.main == 0`, `ociRole=badge` appears 7 times; a model without the fields has no badges. `DemoBadgeTests`: the demo file contains 14 badges and still passes the gate.
- `tests/test_parse_terraform.py`: `three_tier` subnet fields (`sn-lb-public` route table `rt-public`, security list `sl-app`; `sn-app` none), item `nsgs` for the load balancer (`nsg-lb`), the instance (`nsg-app` from `create_vnic_details`, `nsg-mgmt` from the `oci_core_vnic_attachment`) and the Autonomous Database (`nsg-app`); no `nsg` / `security_list` / `route_table` item icons; JSON-shaped `Res` objects (NLB `network_security_group_ids`, DB system `nsg_ids`, two security lists, one without a display name); `validate_model` violations for wrong types.
- `tests/test_query_tenancy.py`: bundle fields (`rt-public`, `sl-app`, `nsg-app` via the VNIC, `nsg-lb` on the load balancer); `normalise_entity` maps `nsg-ids`; the controls set gains the NSG type.
- End-to-end: `parse_terraform_dir(three_tier)` -> `write_diagram` -> `check_overlaps.main == 0` with 5 badges in the file; the tenancy bundle -> `write_diagram` -> gate 0.
- Fixture `tests/fixtures/terraform/three_tier`: `compute.tf` gains `network_security_group_ids` on the load balancer and an `oci_core_vnic_attachment`; `network.tf` gains the NSGs `nsg-lb` and `nsg-mgmt`. No existing assertion counts resources or summary text for this fixture.

## 12. Out of scope

- Route rule tables and security rule tables beyond the existing demo NSG page (`add_table` on an extra page remains the way to show rules).
- Badge legend rows, badge labels or captions, per-rule connectors from a route table to a gateway (the tenancy `ROUTES_TO` edges keep their subnet -> gateway form).
- VCN-level badges (default route table / default security list of the VCN), DNS resolver or DHCP options badges.
- Exadata backup-network NSGs (`backup_network_nsg_ids`), VLAN NSGs, NSGs on gateways, hub items, DRGs or attachment boxes.
- Changing the icon set (no combined route-table/security-list glyph is added) and regenerating the reference sample or the README screenshots.
- Re-tuning the side-gateway geometry (`VCN_SIDE_PAD`, side caption width) for the residual corner-badge / side-caption overlap described at the end of section 6: it needs two or more right-border gateways plus a second subnet row, no shipped model hits it, and the fix belongs to the gateway layout rather than to the badges.

## 13. Compatibility

- Models without the new fields render byte-for-byte as before (no badge cells, unchanged ids).
- Parser output gains two keys on every subnet and `nsgs` on some items; consumers that compare whole subnet dicts must add them (none exist in the repository).
- Validator: files written by 1.2.0 / 1.3.0 without badges are checked exactly as before; the new exclusions only apply to cells carrying `ociRole=badge`.
- `vcn.controls` keeps its shape and remains undrawn.
