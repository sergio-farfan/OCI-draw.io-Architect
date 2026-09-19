# Changelog

All notable changes to the oci-drawio-architect plugin are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [1.5.0] - 2026-09-19

View and detail controls: one discovered topology, several readable views. Captions become a rendered field list, the diagram can be emitted onto real draw.io layers, four detail levels and six purpose presets compose the whole view, one filter predicate is shared by the parser, the live-tenancy reader and the layout CLI, and IAM / Policies / Audit / Public DNS can go into a tenancy-scoped bucket. Schema stays 2 - every new key is optional and a 1.4.x model renders with identical geometry; only the caption text of a **parsed** model changes, and one key brings the old caption back. Design: `docs/superpowers/specs/2026-09-19-v1.5.0-view-and-detail-controls-design.md`.

### Added
- **Label modes** (`label_mode`, `label_fields`, `label_tag_keys`): `minimal`, `network` (the new default) and `detailed` over a documented field vocabulary - display name, resource type, private / public IP, CIDR, FQDN, port / protocol, compartment, AD / FD, lifecycle, tags. An **OCID is never rendered in a caption in any mode**. An authored caption is kept verbatim and a field whose value it already contains is skipped, so a hand-written model renders exactly as before. `LABEL_H_DETAILED = 88` and `LABEL_LINE_BUDGET` grow the caption box, never the slot or the column pitch. The exact 1.4.0 caption of a parsed model comes back with `--label-mode minimal --label-fields display_name,shape`.
- **View layers** (`layers`, `hidden_layers`, off by default): `routes`, `security`, `iam`, `dataflow`, `management` and `associations` become real draw.io layers over a base layer named `Network`, toggled with `Cmd/Ctrl+Shift+L`. The layer pass runs last and only re-parents cells, so enabling layers cannot move a pixel; a layer with no content is not created; a PNG export renders only the visible layers.
- **Detail levels** (`detail`): `executive`, `application`, `network` (the default, today's output - including the DRG route-table badge strip) and `engineering`, each a row of content gates plus defaults for the label mode and the layer set. A gate that removes content **hides its layer** when layers are on and drops the cells when they are off, for the two badge gates whose content is layer-borne; the DRG route-table strip consumes layout space, so it is never layer-gated.
- **Filtering** (`filter`, `--filter`, `--tag`, `--compartment`, `--subnet`, `--resource-type`): one predicate over tags, compartment, region, VCN, subnet, resource type, icon, name, address, environment and application, applied identically by `parse_terraform.py`, `query_tenancy.py` and `oci_layout.py`. Expressions AND across dimensions and OR within one; `!` excludes; `~` is a substring match; an empty include means everything. Structure survives unless an expression names it.
- **Participating mode** (`mode`): `all` (the default for Terraform) or `participating` (the default for a live tenancy) - the second keeps only what takes part in the architecture.
- **Relationship provenance** (`edges[].discovery`): `association`, `config`, `reachability`, `tag`, `observed`, `user` and the plugin's own `heuristic`. `inferred` is still written and derived from it. `--discovery` selects; `--annotate-discovery` puts the provenance in the connector's tooltip; it never changes a connector style. `--relationships FILE` merges a JSON sidecar as `user` edges. `--no-inferred-edges` is a documented alias.
- **Global-services bucket** (`global_services: "bucket"`, off by default): IAM, Policies, Audit and public DNS in a tenancy container below the region, with the compartment list when the compartment containers are not drawn.
- **Purpose presets** (`purpose`, `--purpose`): `network`, `dataflow`, `security`, `inventory`, `dependency`, `ha` - the six purposes the team's diagram guidelines name, each a composition of everything above, asked once in the command's Step 1 and remembered in `.claude/oci-drawio-architect.local.md`.
- **Tags and caption metadata in the parser**: `freeform_tags` and `defined_tags` are kept; `metadata` gains `private_ip`, `public_ip`, `fqdn`, `hostname_label`, `lifecycle_state`, `compartment` and `ports`. The live-tenancy reader propagates the VNIC's addresses to its host.
- New module `scripts/oci_view.py` (standard library only), new builder primitives `set_base_layer_name`, `layer_ids`, `icon_footprint_h`, `DrawioBuilder(max_label_lines=)`, `style_extra=` on `add_icon` / `add_badge`, `tooltip=` / `metadata=` on `add_edge`, and the legend row kinds `("layer", ...)` and `("note", ...)`.
- A `tagged_app` Terraform fixture (two applications, two environments, freeform and defined tags, an unresolvable tag value, a state JSON with a computed private IP).

### Changed
- **One default flip**: `label_mode` defaults to `network`, so a **parsed** model's captions change - the compute / database shape line moves out of the caption into `metadata.shape`, and a private IP and a port list appear when the input carries them. A hand-written model is unaffected. `--label-mode minimal --label-fields display_name,shape` renders the exact 1.4 caption back.
- `subnet_label` accepts a third value `name` (no CIDR), which the executive and application levels select automatically.
- `is_regional()` is now expressed over the three-valued `oci_topology.service_scope()`; it answers exactly as before for every 1.4.x input.
- The reference sample keeps its addresses and ports in `metadata` instead of baked into the captions. Two of its captions therefore gain a line that the `network` mode renders and the authored strings did not carry: the load balancer gains `HTTPS/443` and the Autonomous Database gains `1522`. Nothing else in the sample moves. The demo grows an "Executive overview" (page 4) and an "Engineering detail" (page 5) page, so `Security` becomes page 6.
- `validate_model()` accepts every new key and rejects an unknown `label_fields` entry, layer name, mode, purpose, detail level or `discovery` value; `summarise()` reports the filter and prune counts.

### Fixed
- Validator rule 7 no longer reports a badge moved onto a view layer as foreign to the subnet or icon it decorates: a leaf whose `ociHost` names the container, or a cell inside it, is exempt.
- `DrawioBuilder.validate()` finally passes `max_label_lines` to `validate_registry`, which has accepted the parameter since 1.2.0 and was never given it.
- `query_tenancy._route_edges` labelled route-derived edges as explicit associations; they are `discovery="reachability"` now.

## [1.4.0] - 2026-09-18

Placement enrichments: the location boxes leave the region, the gateways face what they connect to, compartments and grouping boxes become drawable, and the subnet label takes Oracle's two-line form. Schema stays 2 - every new key is optional and a 1.3.x model renders unchanged apart from the two documented default flips below, each reversible in one key. Design: `docs/superpowers/specs/2026-09-18-v1.4.0-placement-enrichments-design.md`.

### Added
- **Location canvas** (`locations`): On-Premises, Internet and 3rd Party Cloud are page-level siblings of the OCI Region - On-Premises left, Internet and 3rd Party stacked right - as the toolkit's Location Canvas (deck slide 12) defines. The hybrid connection label (`Site-to-Site VPN`, `FastConnect`, `Remote Peering`) sits in the gap between the on-premises box and the region, at least 70 px wide so the text fits. A CPE, IPSec endpoint or virtual circuit straddles the on-premises box's region-facing border the way a gateway straddles a VCN border. New model keys `internet` and `third_party`; new constants `LOC_W`, `LOC_GAP_MIN`, `LOC_GAP_RIGHT`, `LOC_STACK_GAP`, `LOC_MIN_H`, `INTERNET_SPLIT`.
- **Internet-facing gateway column** (`gateway_edge`, `gateways[].side`): the IGW takes slot 0 and the NAT slot 1 of the VCN border facing the Internet box - the **right** border for the **rightmost** VCN column, the **top** border (slots counted from the VCN's right edge, captions above the glyphs) for every other column, because a left-hand column's right border faces the next VCN; `gateway_edge: "top"` puts them on the top border everywhere with the caption above the glyph (`add_icon(caption_above=True)`, deck slide 31), `"bottom"` restores the 1.3.x side choice. Gateways are ordered `igw, nat, sgw, lpg` then by address on every border, in every mode.
- **Oracle Services Network band**: under the outside canvas the OSN is a full-width band below the VCN stack and the Service Gateway moves to the VCN's bottom border facing it (`OSN_BAND_GAP`). The Service Gateway's attachment connector to the panel is no longer tied to the right border, so it is drawn in both canvases.
- **Internet Gateway connector**: each IGW gets an attachment connector (thin, no arrowhead, no label) to the Internet box when the canvas drew one, mirroring the Service Gateway's connector to the Oracle Services Network.
- **Compartment containers** (`show_compartments`, off by default): each compartment wraps the VCNs it holds, nested through `compartments[].parent`, with an optional `Tenancy: <name> (Root Compartment)` wrapper. `compartments[]` now accepts objects `{"name", "parent", "vcns"}` alongside the plain names the parser emits. The DRG column, the on-premises panel and the OSN band stay direct children of the region.
- **Grouping boxes** (`vcn.groups[]`, `subnet.groups[]`): `oke_cluster` (dashed Sienna box inside a subnet, deck slide 32), `tier` and `user_group` (slide 18's "Other Grouping"). The three types join `GROUP_TYPES`. Members are re-parented into the box, so it is a container for the validator and the router, and an edge may terminate on its `key`. The Terraform parser emits an `oke_cluster` entry when a cluster and at least one of its node pools resolve to the same subnet.
- **DRG route-table badges**: `drgs[].route_table` (a name, `{"name", "address"}`, or a list) draws a strip of up to `DRG_RT_MAX = 2` badges under the DRG glyph - the pair Oracle creates by default. `oci_core_drg_route_table` is recognised by the parser and `drg_route_table_id` by the live-tenancy reader.
- **Badge legend rows**: `add_legend` accepts `("badge", <icon key>, text)` rows drawn at `LEGEND_BADGE_SIZE = 16`, and the recipe appends one per badge kind actually present.
- **`attachment_style`** (`"solid"` | `"dotted"`), settable per model, per `DrawioBuilder` and per style profile; the legend names the active form.
- CLI flags `--locations`, `--gateway-edge`, `--subnet-label`, `--attachment-style`, `--show-compartments` on `oci_layout.py`, and the matching `build_diagram` / `write_diagram` keywords.
- A `landing_zone` Terraform fixture (nested compartments, two VCNs, an OKE cluster with two node pools, a DRG with two route tables, public and private subnets) driving the parser and the end-to-end tests.

### Changed
- **Default flip 1**: `locations` defaults to `"outside"`. `locations: "nested"` (or `--locations nested`) restores the 1.3.x canvas exactly - the region is translated, not rebuilt, so no interior coordinate and no cell id changes between the two modes' shared parts.
- **Default flip 2**: `subnet_label` defaults to `"twoline"` - name with a `(Public)` / `(Private)` token on line 1, CIDR on line 2 (deck slide 18). `subnet_label: "inline"` restores the 1.3.x single-line label. The token appears only when `public` is present and a bool.
- The `compartment` container's label is now bold **Sienna** `#AE562C` instead of Bark, per slide 18; visible for the first time now that the recipe draws the container. `dashPattern=1 1` is kept as a recorded plugin choice.
- The reference sample and the README screenshots are regenerated on the outside canvas; the demo grows a fourth page (compartments, a tenancy wrapper, an OKE cluster box and a tier band).
- `validate_model()` covers every new key and both `compartments` element forms; `summarise()` reports the compartment and group-box counts. A `groups[]` member is checked inside its own container (subnet groups name items of that subnet, VCN groups name subnets of that VCN) and an edge may terminate on a `groups[].key`.

### Fixed
- A top-border gateway no longer covers the VCN's own title. Top slots are counted from the VCN's right edge inwards, but the width reserved for them was a constant, so on a narrow VCN - the usual hub column of a hub-and-spoke model - the leftmost slot landed on the container's top-left title band. The reservation now measures the title (each line at the size it is drawn in) and widens the VCN instead. A container title is not a cell, so `validate()` could not see the collision.
- The auto-router no longer travels ALONG a container border. A gateway glyph straddles the border, so its docking point sits exactly on the border line and the lattice offered a free lane down the whole of every other container's border at that y - the IGW -> Internet connector of a hub-and-spoke model ran the full width of the next VCN's dashed top edge. A segment within `STRADDLE_TOL` of a container's border now costs `_LANE_COST`, so connectors stay in the gutters and cross a border perpendicularly. The reference sample and the README screenshots are regenerated.
- Two OKE clusters with the same display name in different subnets no longer abort the build with `ValueError: Duplicate cell key 'oke:<name>'` - the same module instantiated twice is the ordinary case. The parser keys the box on the cluster's Terraform address (`oke:<address>`), and `validate_model()` gained the matching safety net: a `groups[].key` repeated, or shadowing an address, is now a violation rather than a crash at layout time.

### Known cosmetic limitations
- The location canvas top-aligns every box with the region and gives them its full height (`LOC_PAD_Y = 0`, toolkit Template 1), so a tall, near-empty On-Premises or Internet box has a lot of white space; likewise between the VCN stack and the Oracle Services Network band, and below or right of a compartment whose sibling is taller.
- The `Site-to-Site VPN` label is centred on the whole horizontal run of its connector, which starts inside the On-Premises box; in `drg_style: "box"` that can put it slightly past the region border. It never overlaps a shape. Centring it on the gap segment alone needs a router change.

## [1.3.1] - 2026-09-18

Patch release: the post-release review backlog. No schema change (one optional `hub.kind` field) and no new feature. Container geometry is unchanged apart from the two sizing fixes below; connector docking changes where the router now has a free side to use. Design: `docs/superpowers/specs/2026-09-18-v1.3.1-backlog-patch.md`.

### Fixed
- Two DRGs without a `name` no longer abort the build with `ValueError: Duplicate cell key 'drg:DRG'`: an unnamed DRG takes its name from the second line of its label, then its address, then its position, and never the bare word `DRG`.
- `parse_terraform.py` no longer invents a DRG attachment for an IPSec connection, a private virtual circuit or a remote peering connection that names no DRG. A declared but unresolvable reference still falls back to a single unambiguous DRG and now records `WARNING: <address>: <attr> does not resolve; attaching to the only DRG <name>`; warnings appear on stderr, in `model["warnings"]` and in the `summarise()` line.
- Validator rule 7: a DRG caption that lies inside a VCN whose border the glyph only straddles is reported (it was skipped unconditionally), and a leaf inside nested foreign containers is reported once, against the innermost one.
- The NSG badge is positioned from the host icon's actual slot width instead of the module constant `ICON_W`.
- A badged subnet reserves `2 * (BADGE_SIZE + BADGE_GAP)` of title width for its corner badges, and the validator warns when a badged container's title does not fit in what its badges leave. The rule counts only the lines the narrowed width forces, so a title deliberately broken over two lines (Oracle's name-over-CIDR subnet label) no longer fails `--strict` when both lines fit.
- The auto-router no longer charges an edge for the padding inside its own endpoints' icon slots. A glyph narrower or shorter than the 75x95 slot sits inside that padding, so every port of such an icon carried an obstacle penalty whose size depended on where the routing lattice happened to cut the padding - a pure translation of the diagram could flip a straight same-row connector to a three-bend detour. The band between a glyph and its caption stays closed to every connector, including its own.
- The auto-router charges `_PORT_SHARE_COST` for docking where another connector already docks, so two connectors on the same shape take different sides (the team's diagram guidelines: one docking point per connector). The penalty is calibrated above the cost of a three-bend detour, so a free side three bends away still wins over a shared point - otherwise two arrowheads coincide and the losing connector rides the glyph's border. `add_edge(route="auto")` records the chosen path's lattice cost in the edge cell's `route_cost`.
- The gap between two VCN columns is sized from both facing borders, so a left-border gateway in the next column no longer puts its caption inside the previous VCN.
- A DRG cluster with no attachment box on one side reserves the 15 px its caption overhangs the icon slot, restoring the documented 45 px gap.
- A gateway with a `link` keeps its hyperlink when it is placed on the VCN border.
- `choose_drg_style` raises `ValueError` instead of `AttributeError` for a non-string; `validate_model` returns violations instead of raising when `drgs` or `vcns` is not a list; `select_vcn` clears a `peer` pointing at a pruned LPG and `validate_model` now checks that `peer` resolves; service items merged from a dropped placeholder VCN carry `regional`; legacy hub DRG items are matched by identity rather than by value.
- One page-prefix-aware `is_warning()` replaces three WARNING/error splits, two of which promoted a warning whose label contained `"] "` to a blocking error.

### Changed
- `validate_model` accepts a hub without a `name`: section 6 declares it optional, `_layout_hub` falls back to `HUB_TITLES`, and the command's MODEL template emits `kind` and `items` only - so the template no longer reports `hub.name: expected str, got NoneType`.
- The hub panel carries an optional `hub.kind` (`onprem` | `remote_region`, default `onprem`) that selects its default title; the container keeps the `onprem` styling and an explicit `hub.name` still wins. The Terraform parser sets `remote_region` when the hub holds only RPC peers, and the skill and command no longer hard-code `On-premises`.
- The legend applies the profile's dashed-arrow suppression to every legacy alias that resolves to `control`, so `dashed` and `purple` render alike; the canonical kind name keeps the `EDGE_KIND_STYLES` arrow.
- The region-level `OCI Services` panel (2+ VCNs) is height-matched to the tallest VCN column like the Oracle Services Network panel.
- `attachment_type()`, `is_regional()` and the legacy single-DRG match warn once to stderr on an unknown attachment type, a non-boolean `regional` value and a name mismatch; `is_regional()` also accepts the JSON string forms `"true"` / `"false"`; `has_onprem` follows the spec's CPE / IPSec / virtual-circuit rule.
- `DrawioBuilder.layout_info` is declared and documented on the class instead of being attached by the recipe; `VNIC_ATTACHMENT_TYPES` drops `oci_core_vnic` (a data source, never a managed resource); `HUB_TYPES` is a `frozenset`.
- Docs: the builder module docstring lists the `drg` group type and `add_box()`; the command lists the `osn`, `drg:<name>` and attachment-address edge endpoints, and SKILL.md records the badge first-wins rule for a shared construct; SKILL.md, the command and `references/gotchas.md` document the new `WARNING: title ... its badges leave`.
- Tests: ~25 new cases (router docking on narrow glyphs at four page offsets, one docking point per connector, a free side three bends away beating a shared point, no two connectors of the reference sample sharing a docking point, no connector under its own glyph, legend aliases, pinned-route edge kinds, `add_box` error paths, the `FOREIGN_TOL` boundary, rule 6's badge exclusion, one OSN panel for two VCNs, `_resolve_attachment_target`, the topology helpers and exported tuples, `REGIONAL_TYPE_PREFIXES`, a reference-backed edge under `--no-inferred-edges`, indexed-instance VNIC NSG badges in plan JSON and a two-LPG tenancy fixture).

## [1.3.0] - 2026-09-17

Topology-aware placement. The layout recipe now follows how Oracle's Architecture Diagram Toolkit (v24.2, slides 19-22 and 27-32), Oracle's reference architectures and the team's diagram guidelines draw connectivity infrastructure: the DRG is a region-level element with its attachments beside it, gateways sit on the VCN border, regional services live in an Oracle Services Network panel, and connectors carry four semantics. Design: `docs/superpowers/specs/2026-09-17-topology-aware-placement-design.md`.

### Added
- **Model schema 2** (`parse_terraform.py`, `query_tenancy.py`, `oci_layout.py`): `drgs[]` with typed `attachments[]` (`vcn`, `ipsec`, `virtual_circuit`, `rpc`, `loopback`) carrying their own display names; `drg_style` (`auto` | `icon` | `box`); `services[].regional`; `gateways[].peer` for Local Peering Gateways; edge kinds `association` and `attachment`. The hub panel holds the on-premises side only (CPE, IPSec, FastConnect virtual circuit, RPC peer). Schema-1 models are migrated at build time with `WARNING: legacy model: ...` lines.
- `scripts/oci_topology.py`: `classify_topology()` (`single_vcn`, `multi_vcn`, `vcn_with_drg`, `hub_spoke`, `hybrid`), `migrate_legacy_model()`, `is_regional()`, `choose_drg_style()`, `REGIONAL_ICON_KEYS`.
- **Layout**: DRG column between the on-premises panel and the VCN columns, vertically centred on the VCN stack, one rounded attachment box per attachment (VCN attachments facing the VCNs, IPSec / FastConnect / RPC attachments facing the on-premises panel) connected with arrowhead-less `attachment` connectors labelled `Site-to-Site VPN` / `FastConnect` / `Remote Peering`; `drg_style="box"` wraps a DRG and its boxes in a dashed `DRG: <name>` group (`auto` picks it above 4 attachments). IGW and NAT straddle the VCN's bottom border, the Service Gateway its right border, LPGs the border facing their peer VCN. Regional services (Logging, Monitoring, Notifications, Events, IAM, Vault/KMS, Object Storage, OCIR, AI services, Data Safe, Streaming, Queue, APM, DevOps and others) are drawn in one region-level `Oracle Services Network` panel right of the VCN columns with an SGW -> panel connector; `"regional": false` keeps an item in the VCN. CLI `--drg-style {auto,icon,box}`; `build_diagram(..., drg_style=)`; `builder.layout_info` exposes the topology, warnings and the chosen style per DRG.
- **Builder**: `add_edge(kind="data"|"control"|"association"|"attachment")` and `EDGE_KIND_STYLES` (data = solid open arrow, control = dashed open arrow, association = dotted no arrowhead, attachment = thin solid no arrowhead); `add_legend()` rows for the four kinds plus region, VCN, subnet and OSN; `drg` container type; `add_box()` for labelled rounded markers; `add_icon(label_fill=)` for captions crossing a dashed border; `append_pages()`; `ociGroup=<type>` token on every container and `ociRole=drg` on DRG icons so `check_overlaps.py` recognises them in hand-written files.
- **Validator**: foreign-containment rule (`ERROR: '<label>' ... lies inside '<VCN or subnet>' ... but is not one of its children`), `ERROR: DRG '<label>' is inside VCN '<vcn>'` for a DRG box inside any VCN, and a straddle tolerance so border-centred gateways pass the containment check (`STRADDLE_TOL`, `FOREIGN_TOL`).
- **Security constructs as badges**: `subnet.route_table`, `subnet.security_lists` and `item.nsgs` (names or `{"name", "address"}`) draw 22 px caption-less badges - route table centred on the subnet's top-right corner, security lists one badge to its left, an NSG shield over the top-right of the protected resource's icon slot - with the names in the tooltip and metadata; never as workload icons (team diagram guidelines; toolkit slide 18 half-size labels and the v24.2 combination icon). `DrawioBuilder.add_badge()`, `BADGE_SIZE` / `BADGE_GAP`, style tokens `ociRole=badge;ociHost=<id>`; the validator lets a badge straddle its parent's corner and overlap its own host only. `parse_terraform.py` fills the fields from `route_table_id`, `security_list_ids`, `create_vnic_details.nsg_ids`, `network_security_group_ids`, `nsg_ids` and `oci_core_vnic_attachment`, resolving a subnet's route table and security lists through the managed and the `oci_core_default_*` resource types alike; `query_tenancy.py` from `routeTableId`, `securityListIds`, `nsgIds` and `networkSecurityGroupIds`. Design: `docs/superpowers/specs/2026-09-17-security-constructs-addendum.md`.
- Tests: `tests/test_oci_topology.py`, `tests/test_oci_layout.py`, the `tests/fixtures/terraform/hub_spoke` fixture (two VCNs, one DRG with four attachments - two VCN attachments, a FastConnect virtual circuit and a remote peering connection - an LPG pair and a regional log group).

### Changed
- `examples/generate_reference_layout.py`: the DRG moved from `hub.items` to `drgs[]` with one VCN attachment; the CPE stays in the hub with an explicit `cpe -> drg` edge labelled `IPSec VPN`; the eight services are regional and render in the OSN panel. The four captioned `nsg` items became `nsgs` badge fields on the resources they protect (load balancer, app VM, worker VM, ADB). `OCI_Architecture.drawio`, `screenshots/` and `Screens/` regenerated from it (`examples/make_screenshots.py`; the detail crop now follows the NAT gateway on the bottom border and the Service Gateway on the right border), so the sample and the README screenshots show the badges.
- `examples/generate_demo_diagram.py`: three pages built from one schema-2 model - icon style, box style and the NSG rule table; exercises the OSN panel, border gateways and the four connector kinds.
- The demo model carries route tables, security lists and NSGs on its subnets and resources; the skill and command no longer ask for an NSG as the last item of a subnet.
- `parse_terraform.py` no longer emits CPE -> DRG edges (the layout draws the attachment connectors) and emits one `Local Peering` edge per LPG pair; `GATEWAY_ICONS` has no `drg` entry; `summarise()` reports DRGs and attachments. `gateways[].peer` is set on **both** LPGs of a pair although only the requestor declares `peer_id`, so each gateway lands on the border facing its peer VCN; a virtual circuit with `type = "PUBLIC"` no longer becomes a DRG attachment (public peering has no DRG - it stays an on-premises item), and `query_tenancy.py` carries the circuit's `type` so the live path behaves the same.
- Attachment boxes size themselves: `ATT_H` (44) is now a minimum and a box grows by whole lines to hold its display name, with the stack gap `ATT_VGAP` instead of a fixed pitch. `drawio_builder.wrap_hints()` adds zero-width break opportunities after `_`, `-` and `.` (dotted numbers excluded) so a parser-style name such as `drg_attachment_vcn_prod_shared_services_hub` wraps inside its box instead of rendering as one line across the DRG glyph, the connector and the VCN border; `label_lines()` measures a wrap hint as a space.
- Validator rule 5 also covers labelled boxes (`add_box()`, kind `other`): `WARNING: label '...' needs ~N lines at 11px in 100px but its box is 44px tall`. Captions keep the `MAX_LABEL_LINES` threshold; a box is reported at any line count.
- `oracle_services_network` panels created by the recipe use a left-aligned label; `oracle-styles.md` records that the Rose look is the toolkit's "Optional" grouping spec while slide 19 specifies Neutral 3 2pt dashed for the OSN.
- Documentation (README, plugin README, SKILL.md, command, references, repo CLAUDE.md) rewritten for schema 2 and the new placement rules.

### Notes
- The plugin does not use draw.io's MCP connector (the hosted MCP server at `mcp.draw.io`): draw.io's built-in shape libraries carry no OCI icons, local generation keeps diagram content on the machine, and the connector's inline preview needs an MCP Apps host, which Claude Code is not. Rationale in the repository README ("Why not the draw.io MCP connector").

### Roadmap (not in this release)
- Diagram purpose selection, resource filtering (tag / compartment / region / VCN / subnet / type / environment), detail levels, label modes, draw.io view layers, a separate global-services bucket, all-resources versus participating mode, multi-region canvases.
- **Location boxes outside the region**: an Internet box, and On-Premises / 3rd Party Cloud as sibling location boxes next to the region instead of a panel nested inside it, with the Site-to-Site VPN / FastConnect label in the gap between the two locations (the toolkit's form). This release keeps the on-premises panel inside the region, so those labels sit inside the region box; the choice and its reason are recorded in section 14 of `docs/superpowers/specs/2026-09-17-topology-aware-placement-design.md`.

## [1.2.0] - 2026-09-12

This release implements the findings of the full code review and output-quality audit of 1.1.0 (2026-09-12; 141 verified findings plus 9 from a completeness pass). The five root causes of "new diagrams do not look like the sample" - a workflow that could not run as written, styles that drifted from the reference, edges routed through shapes, inconsistent icon sizes with ghost boxes, and under-specified prompts - are all addressed.

### Added
- `examples/make_screenshots.py`: regenerates `screenshots/` and `Screens/` from the reference layout example (full render plus data-subnet detail crop); the repository screenshots now show v1.2.0 output.

**Builder (`scripts/drawio_builder.py`)**
- Layout helpers: `place_icons()`, `fit_to_children()`, `resize()`, `fit_page()`, `add_title()`, `add_legend()`, `add_table()`, `add_page()` / `use_page()` / `add_layer()`.
- `key=` on every `add_*` call for deterministic cell ids; `link=` (emits a `UserObject`), in addition to `metadata=` / `tooltip=`.
- `render()` (module function and method) exporting PNG/SVG/PDF through the draw.io desktop CLI; `find_drawio_binary()` honours `DRAWIO_BIN`.
- `validate()` covering referential integrity (unknown `parent` / `source` / `target` ids, which made draw.io silently drop the whole diagram - review C001), any-two-container overlaps, containment, icon / caption / text collisions, captions exceeding three lines, estimated edge crossings, empty pages and content exceeding the page; `validate_file()` for the CLI inflates compressed pages and understands `<object>` / `<UserObject>` wrappers.
- Style profiles `default`, `official` (strict OCI Architecture Diagram Toolkit v24.2) and `v1.0` (byte-for-byte 1.0.0 sample; `sample` alias); `style_profile=` and `font_family=` constructor arguments.
- Container types `other`, `metro_or_realm`, `third_party_cloud`, `internet`; `ocean` (`#2C5967`), `neutral_4` (`#70736E`), `ivy` and `oracle_red` in `COLORS`.
- `set_icon_dir()`; every bundled SVG is registered by file stem at import time (159) on top of 206 short aliases in `ICON_ALIASES`.

**Scripts**
- `oci_layout.py` - deterministic layout recipe (model dict / JSON -> `.drawio`) reproducing the reference sample's structure: title block, region with hub panel, VCN columns with subnet rows in traffic order, OCI Services panel, data tier, gateway row, auto-routed edges, optional legend. CLI: `--profile`, `--legend`, `--logo`, `--strict`, `--render`.
- `render_drawio.py` - PNG/SVG/PDF/JPG export wrapper (exit 0 / 1 / 3 when draw.io desktop is missing).
- `build_icon_catalog.py` - regenerates `references/icon-catalog.md` from the SVGs and `ICON_ALIASES`; `--check` validates keys, viewBoxes, placeholders and alias targets.
- `smoke_test.sh` - demo diagram -> `check_overlaps.py` -> PNG export when draw.io desktop is available (`SMOKE_SKIP_PNG`, `SMOKE_OUT_DIR`).
- `parse_terraform.py` - Terraform HCL directory (comments stripped, brace-matched, `.terraform` never entered), `terraform show -json` plan (`--plan-json`) or state (`--state-json`) -> diagram model JSON (`schema_version` 1): subject, region, hub, VCNs with tiered subnets, services, controls and gateways, compartments and explicit / inferred edges; `--vcn` filter, `--out`, `--no-inferred-edges`; exit 0 / 1 / 2.
- `query_tenancy.py` (experimental) - live tenancy -> diagram model via the OCI CLI topology API.
- `check_overlaps.py`: `--strict` (warnings become errors), `--quiet`, `--version`; multiple files per invocation; exit 2 covers missing/unreadable files, unparsable XML and a missing sibling builder.
- `detect_settings.py`: `-h`, `--no-cli`; new keys `vcns`, `compartments`, `terraform_dirs`, `auth_tenancy_ocid`, `terraform_tenancy_ocid`, `oci_auth`, `subscribed_regions`, `home_region`, `compartment_ocid`.

**Examples, tests, packaging**
- `examples/generate_reference_layout.py` rebuilds the reference sample (`OCI_Architecture.drawio`) from a `MODEL` dict through `oci_layout.write_diagram()`.
- `examples/generate_demo_diagram.py` now has two pages ("Architecture" and a "Security" NSG rule table), exercises every container type, all three edge modes, metadata / tooltips, a legend and the validation gate; accepts `--render`.
- `tests/` - unittest suite: `test_builder.py` (styles, routing, validation, helpers), `test_detect_settings.py` (fixtures under `tests/fixtures/detect/*`) and `test_icons.py` (SVG integrity, viewBoxes, aliases, `ICON_MAP`). Run with `python3 -m unittest discover -s oci-drawio-architect/tests`.
- `LICENSE` inside the plugin directory and `icons/NOTICE` with Oracle's attribution; both are required by `pack.sh` and shipped in the archive.
- `references/templates/` holding the six composite `physical_example_*.svg` drawings (documentation only, no longer icon keys).
- `install.sh` post-install smoke test (demo diagram + overlap gate) as the eighth verification check.

### Changed

- **Workflow**: generated scripts import the builder in place (`sys.path.insert(0, "<plugin>/scripts")`); `drawio_builder.py` is no longer copied into the project. Icon resolution searches `$OCI_SVG_DIR`, `<plugin>/icons`, `<builder dir>/icons`, `$CLAUDE_PLUGIN_ROOT/icons` and the `~/.claude/plugins` marketplace / cache locations; the hard-coded personal fallback path is gone (review F001 / F087 / F111).
- **Workflow steps** are now settings -> input -> model -> generate -> run -> validate + render -> report; the mandatory gate runs `check_overlaps.py` and, when draw.io desktop exists, a PNG export for visual inspection.
- **Styles** restored to the reference look with the official 12px labels: region / on-premises / compartment labels top-left (`align=left;spacingLeft=5`), services panel charcoal `#312D2A` 1px dashed (was grey 2px - Oracle's "Metro Area or Realm" style), dashed edges with `dashPattern=6 3`, tenancy regular weight, Oracle Services Network Rose 1px dashed on Air fill, and the font stack `Oracle Sans,Arial,Helvetica,sans-serif` on every cell so viewers without Oracle Sans no longer fall back to a serif face (F081 / F082 / F083 / F085 / F128 / C002).
- **Icons**: `_load_svg()` strips the stencil export's caption-placeholder rectangle, crops the viewBox to the glyph and fits every glyph into a uniform 70x70 area at the top of the 75x95 slot, replacing the 1.1.0 aspect-derived widths that produced 21 different cell widths (52-98px) and off-centre glyphs (F002 / F008 / F130).
- **Edges**: `add_edge()` defaults to `route="auto"` - common-ancestor parent, docking sides and waypoints computed on a lattice of container margins and gutters so connectors avoid unrelated icons, captions and container titles; labels are positioned to avoid collisions. `route="direct"` keeps the 1.1.0 port-less orthogonal router and `route="pinned"` the 1.0.0 fixed ports / waypoints (selected automatically when pins or waypoints are passed) (F080 / F088 / F089).
- **Validation**: containment violations are now errors (were warnings with exit 0); icons and captions are checked; `check_overlaps()` returns only blocking problems while `validate()` returns everything (F004 / F040 / F047).
- **`write()`** accepts `str` as well as `Path` (the `str` crash from the review); labels are coerced with `str()`.
- **`detect_settings.py`** rewritten: `region = var.region` and other `var.` / `local.` references are resolved through `terraform.tfvars`, `*.auto.tfvars[.json]` and brace-matched `variable` defaults; comments are stripped; only the non-aliased `provider "oci"` block is read (`terraform {}` / `backend {}` blocks and other providers are ignored); `.terraform`, `.git`, `node_modules`, `.venv` and `__pycache__` are pruned during discovery; `~/.oci/config` keys inherit from `[DEFAULT]` and `$OCI_CLI_CONFIG_FILE` / `$OCI_CLI_PROFILE` are honoured; CLI calls are bounded by an 8 s timeout and use `--auth security_token` when a session token is configured; logo paths inside the project are stored relative; YAML output is escaped; `~/.oci/config` and CLI tenancy OCIDs are reconciled with the Terraform one.
- **`install.sh`**: uses `python3 -m pip install --user` (no bare `pip`), treats Pillow as optional (warns and continues, with PEP 668 hints), checks for `rsync` and falls back to `cp -R`, stages the copy and swaps it in atomically, upserts only the `oci-drawio-architect` entry of `marketplace.json` with `json` (other plugins and top-level fields preserved; invalid files are backed up to `.bak`), reads all inputs through environment variables, and runs 8 verification checks (icon threshold 150). Uninstall also removes the plugin cache and the `installed_plugins.json` entry, edits `marketplace.json` in place and removes the local marketplace only when it is empty (F036 / F037 / F038 / F044).
- **`pack.sh`**: reproducible archives (sorted file list, uid/gid 0, `gzip -n`, `SOURCE_DATE_EPOCH` mtimes with GNU tar, `COPYFILE_DISABLE`), excludes `logos/`, `*.tar.gz`, `__pycache__`, `*.pyc`, `.DS_Store`, `._*` and fixture `.drawio` files, verifies the archive contents and prints size, entry count, icon count and SHA256.
- `.gitignore` now ignores `.claude/*.local.md` (the settings file was documented as gitignored but was not - F049), `*.drawio.png`, `*.drawio.svg`, `/oci-drawio-architect/logos/` and `.venv/`.
- Documentation (`README.md`, plugin `README.md`, repo `CLAUDE.md`, command, skill and references) rewritten around the model-based workflow; stale counts (220 icons, 15 categories, 5 install checks, 10-100 KB files) corrected.

### Fixed

- 16 icons (`compute_*` x6: VM, Flex VM, Burstable VM, Functions, Autoscaling, Instance Pools; `storage_*` x10: Block Storage, Block Storage Cloning, Buckets, Object Storage, File Storage, Backup/Restore, Elastic Performance, Local Storage, Persistent Volume, Service Gateway) rendered a faint hollow rectangle under a shrunken glyph because of a leftover caption-placeholder path; the placeholder is removed from the files and stripped defensively at load time (F100 / F129).
- Four scrape-artifact filenames in `icons/general/` renamed: `analytics_and_ai_amp_nbsp_data_catalog.svg` -> `data_catalog.svg`, `..._data_flow.svg` -> `data_flow.svg`, `..._data_integration.svg` -> `data_integration.svg`, `observability_and_management_amp_nbsp_events.svg` -> `events.svg`.
- Region table: `eu-london-1` (not a real region) removed, `uk-london-1` added, the table completed to 55 commercial and government regions, and unknown identifiers get a derived label instead of the raw id (F022).
- Logo classification was inverted relative to the documented example: `*dark*` / `*black*` files are now `logo_light` (dark artwork for light backgrounds) and `*white*` / `*light*` files `logo_dark` (F023).
- `variables.tf` parsing no longer captures the next variable's default when a closing brace is indented (which reported a compartment OCID as `tenancy_ocid`) and one-line blocks match (F020); the first `region = "..."` in a backend block or a comment no longer wins (F019).
- `add_image()` accepts SVG logos without Pillow and gives an actionable error for PNG/JPEG when Pillow is missing (F024).
- `marketplace.json` could be produced as invalid JSON when the plugin description contained a double quote while the verifier still reported success (F037).
- The icon catalog omitted 74 files and listed keys that did not resolve; it is now generated from the SVGs and checked in CI-style by `build_icon_catalog.py --check` (F103).

### Removed

- 55 empty stencil shells that rendered as invisible cells up to 526px wide: all 34 files under `icons/logical/`, 20 connector / grouping / template files under `icons/physical/`, and `icons/general/unknown.svg` (F099). The six composite `physical_example_*.svg` drawings moved to `skills/oci-drawio-architect/references/templates/`. The icon set is now 159 SVGs in 12 categories (was 220 in 14).
- The hard-coded personal icon fallback path in `_resolve_icon_dir()`.
- The "copy `drawio_builder.py` into the working directory" step and the instruction to keep a pre-existing (possibly stale) copy.
- Fixed page sizes in the diagram-type guidance; pages are sized from content with `fit_page()`.

## [1.1.0] - 2026-07-03

### Added
- `scripts/check_overlaps.py` CLI and `DrawioBuilder.check_overlaps()` - sibling-container overlap detection, made a mandatory gate in the `/drawio-architect` workflow.
- Five container types: `tenancy`, `availability_domain`, `fault_domain`, `oracle_services_network`, `onprem` (`hub` became a deprecated alias of `onprem`).
- Optional `metadata=` / `tooltip=` on icons and containers (`<object>` wrappers visible in draw.io tooltips / Edit Data).
- `examples/generate_demo_diagram.py` demo / post-install smoke test; `examples/` shipped in the package.
- Optional plugin-local `logos/` directory as a fallback for logo detection.
- Friendlier errors: unknown icon keys get close-match suggestions; edge pin, icon dimension and metadata validation.

### Changed
- Aspect-correct icons: `imageAspect=1` with per-icon derived cell width at a fixed 95px height (pre-1.1.0 stretched every icon by roughly 15-20%).
- Official Oracle v24.2 container styles and palette.
- Edges default to draw.io's orthogonal router (port-less); explicit ports / waypoints remain supported as the legacy pinned mode.
- `.drawio` files are written with `compressed="false"`.
- Cell-registry parsing shared between `drawio_builder.py` and `check_overlaps.py`.
- `detect_settings.py`: bounded tenancy-OCID regex (no cross-variable false matches), deterministic Terraform-directory discovery, robust OCI CLI JSON handling.
- Command and skill require overlap validation and orthogonal-edge defaults; READMEs, install check and docs refreshed for 1.1.0.

## [1.0.0] - 2026-03-16

Initial release.

- `/drawio-architect` slash command and auto-activated `oci-drawio-architect` skill with `oracle-styles.md`, `icon-catalog.md` and `gotchas.md` references.
- `scripts/drawio_builder.py` - `DrawioBuilder` generating `.drawio` XML with URL-encoded embedded SVG icons, viewBox expansion for OCI SVG transforms, Oracle-style containers (region, compartment, vcn, subnet, services, hub) and pinned edges.
- `scripts/detect_settings.py` - settings auto-detection from Terraform, the OCI CLI and `~/.oci/config`, saved to `.claude/oci-drawio-architect.local.md`.
- 220 bundled OCI SVG icons in 14 categories.
- `install.sh` (local Claude Code marketplace) and `pack.sh` (release tarball); MIT license, README with badges, screenshots and release download link.

[1.2.0]: https://github.com/sergio-farfan/OCI-draw.io-Architect/releases/tag/v1.2.0
[1.1.0]: https://github.com/sergio-farfan/OCI-draw.io-Architect/releases/tag/v1.1.0
[1.0.0]: https://github.com/sergio-farfan/OCI-draw.io-Architect/releases/tag/v1.0.0
