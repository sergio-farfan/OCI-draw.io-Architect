#!/usr/bin/env python3
"""Deterministic OCI diagram layout: normalized model dict -> .drawio.

This is the layout recipe the /drawio-architect workflow uses so that every
generated diagram has the same structure as the reference sample:

    Title block (bold subject, italic "Region label (region) - Compartment: X")
    Region (solid, label top-left)
      +-- Hub panel (On-premises / Remote region; left, vertically centred on the VCN stack):
      |   CPE, virtual circuit, RPC peer
      +-- DRG column (region level, centred on the VCN stack): DRG icon with one attachment
      |   box per attachment beside it, each grown to hold its own display name (VCN
      |   attachments facing the VCNs, on-prem / RPC attachments facing the on-premises
      |   panel, whose gutter widens to fit the Site-to-Site VPN / FastConnect /
      |   Remote Peering label on the line); drg_style "box" wraps them in a dashed group
      +-- VCN column(s)
      |     +-- row 1: lb -> app -> compute -> mgmt subnets (traffic order, 2 icon columns)
      |     +-- OCI Services panel (right of row 1) only for VCN-resident services without a subnet
      |     +-- data-tier subnets stretched to the row width
      |     gateways centred on the VCN border: IGW / NAT bottom, SGW right, LPG facing its peer
      +-- Oracle Services Network panel (right of the VCN columns, regional services, fed by the SGW)
      edges auto-routed through the gutters; optional legend below the region.

Model schema v2 (JSON-serialisable dict; every key optional except vcns/subject):

    {
      "subject": "Spoke-VCN-D", "region": "us-ashburn-1", "region_label": "Ashburn",
      "compartment": "Spoke-VCN-D", "tenancy_name": null,
      "drg_style": "auto",                # auto | icon | box (CLI --drg-style overrides)
      "locations": "outside",             # outside (default) | nested - CLI --locations
      "gateway_edge": "auto",             # auto | internet | top | bottom
      "subnet_label": "twoline",          # twoline (default; name + (Public)/(Private), CIDR
                                          # on line 2) | inline (the v1.3.0 single line)
      "attachment_style": "solid",        # solid (default) | dotted
      "show_compartments": false,         # draw each compartment as a container
      "hub": {"kind": "onprem",           # onprem (default) | remote_region - selects the default title
              "name": "On-premises",      # optional override; on-prem side only: CPE, IPSec, VC, RPC peer
              "items": [{"icon": "cpe", "label": "Corp VPN\\n(10.0.0.0/8)", "address": "cpe"}],
              "link_label": null},
      "drgs": [{"name": "drg", "address": "drg", "label": "Dynamic Routing\\nGateway (DRG)",
                "attachments": [{"type": "vcn", "vcn": "Spoke-VCN-D", "address": "drg-att-spoke",
                                 "label": "VCN attachment\\nSpoke-VCN-D"},
                                {"type": "ipsec", "target": "cpe", "address": "vpn@drg", "label": "vpn-hq"}]}],
      "vcns": [{
         "name": "Spoke-VCN-D", "cidr": "10.0.0.0/16",
         "subnets": [{"name": "sn-priv-lb", "cidr": "10.0.0.0/24", "tier": "lb", "public": false,
                      "items": [{"icon": "load_balancer", "label": "Load Balancer\\n10.0.0.23",
                                 "address": "lb", "metadata": {"ocid": "..."}, "tooltip": "...",
                                 "nsgs": ["nsg-lb"]}],
                      "route_table": "rt-lb", "security_lists": ["sl-lb"]}],
         "services": [{"icon": "logging", "label": "Logging", "address": "logs", "regional": true}],
         "services_label": "OCI Services",
         "gateways": [{"icon": "service_gateway", "type": "sgw", "label": "Service\\nGateway", "address": "sgw"},
                      {"icon": "remote_peering_gateway", "type": "lpg", "label": "LPG", "address": "lpg-a",
                       "peer": "lpg-b"}]
      }],
      "services": [ ... ],                  # more services; regional ones join the OSN panel
      "edges": [{"source": "lb", "target": "app-vm", "label": "3000 / 8000", "kind": "data"}],
      "notes": "optional free text placed under the title"
    }

Attachment "type": vcn (target = that VCN's border), ipsec / virtual_circuit (target = the
on-premises item, connector labelled "Site-to-Site VPN" / "FastConnect"), rpc (target = the
remote peer item, "Remote Peering"), loopback (not drawn). Services are regional (Oracle
Services Network panel) when "regional" is true or the icon is in
oci_topology.REGIONAL_ICON_KEYS; VCN-resident ones stay in the VCN.
Edge "kind": data (solid, open arrow), control / management (dashed, open arrow),
association (dotted, no arrowhead), attachment (thin solid, no arrowhead), analytics
(solid Sienna), datalake (dashed purple); or pass "dashed"/"color" directly.
Schema-1 models (DRG in hub.items or as a "drg" gateway) are migrated with a WARNING.

Security constructs are badges, never workload icons: "route_table" (str or {"name", "address"})
and "security_lists" ([str or {"name", "address"}]) on a subnet draw half-size icons straddling
the subnet's top-right corner (route table on the corner, security lists to its left); "nsgs"
([str or {"name", "address"}]) on any item draws a shield badge over the top-right of that
item's icon slot. Badges have no caption; names go to the tooltip and metadata. An entry with an
"address" can be an edge endpoint.

Usage (CLI):
    python3 oci_layout.py model.json -o out.drawio [--profile default|official|v1.0]
                          [--legend] [--logo file] [--strict] [--render png|svg|pdf]
                          [--drg-style auto|icon|box] [--locations outside|nested]
                          [--gateway-edge auto|internet|top|bottom]
                          [--subnet-label twoline|inline|name] [--attachment-style solid|dotted]
                          [--show-compartments]
                          [--label-mode minimal|network|detailed] [--label-fields F,F]
                          [--label-tag-keys K,K] [--layers off|auto|L,L] [--hidden-layers L,L]
                          [--detail executive|application|network|engineering] [--no-edges]
                          [--filter EXPR ...] [--mode all|participating] [--discovery K,K]
                          [--annotate-discovery]

Usage (Python):
    from oci_layout import build_diagram, write_diagram
    d = build_diagram(model)              # DrawioBuilder, not yet written
    write_diagram(model, "out.drawio")    # build + validate + write (+ optional render)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from drawio_builder import (  # noqa: E402
    BADGE_GAP, BADGE_RESERVE, BADGE_SIZE, CHAR_W_RATIO, COL_W, COLORS, GAP, ICON_FOOTPRINT_H, ICON_W,
    LABEL_FONT_SIZE, LABEL_H, LABEL_H_DETAILED, LABEL_LINE_BUDGET, LABEL_LINE_H, LABEL_W, PAD,
    ROW1_Y, ROW_H, DrawioBuilder, edge_label_extent,
    escape_label, icon_footprint_h, is_warning, label_lines, render, wrap_hints,
)
import oci_view as ov  # noqa: E402
from oci_topology import (  # noqa: E402
    ATTACHMENT_STYLE_MODES, GATEWAY_EDGES, GATEWAY_SIDES, GROUP_BOX_TYPES, HUB_TITLES,
    LOCATION_MODES,
    SUBNET_LABEL_MODES, attachment_label, attachment_link_label, attachment_style_of,
    attachment_type, badge_refs, choose_drg_style, classify_topology, compartment_tree,
    drg_route_tables, gateway_edge_mode, hub_kind, is_onprem_item, is_regional, label_parts,
    locations_mode, migrate_legacy_model, normalise_groups,
)

# ---------------------------------------------------------------------------
# Layout constants (values reproduce the reference sample's geometry)
# ---------------------------------------------------------------------------
TITLE_BOX = (20, 8, 600, 55)
REGION_XY = (20, 75)
VCN_Y = 40
VCN_BOTTOM_PAD = 40
H_GAP = 20            # between subnets in a row
V_GAP = 40            # between subnet rows
PANEL_GAP = 40        # between row 1 and the services panel
GW_PITCH = 180        # gateway icon pitch
SUBNET_EXTRA_W = 50   # 2 cols -> 310 wide like the sample
SUBNET_TITLE_PAD = 10  # spacingLeft + right inset of a container title
TITLE_LINE2_FONT = 10  # second (CIDR) line of a two-line container title
SUBNET_BOTTOM_PAD = 28
HUB_X = 15
HUB_W = 180
HUB_GAP = 45
# L1 / G1-G2: the Location Canvas. On-Premises is a page-level sibling of the
# region, LOC_W wide and the region's height; the left gutter has to hold the
# Site-to-Site VPN / FastConnect label (slide 27: 68.2 pt), the right one is
# the toolkit's 10 px. Internet takes 45% of the right column when a 3rd Party
# Cloud box shares it (toolkit Template 1: 210 / 250).
LOC_W = HUB_W
LOC_GAP_MIN = 70
LOC_GAP_RIGHT = 10
LOC_STACK_GAP = 10
LOC_MIN_H = 160
INTERNET_SPLIT = 0.45
HUB_ATT_LABEL_PAD = 12           # clearance each side of a hub-side attachment label in the gutter
HUB_ICON_Y0 = 70
HUB_PITCH = 200
VCN_COLUMN_GAP = 45
VCN_MIN_W = 300       # narrowest VCN box (one subnet column)
MAX_ROW_W = 1000
ROW_TIERS = ("lb", "app", "compute", "mgmt", "other")
DATA_TIERS = ("data",)

# Gateways straddle the VCN border (glyph centre on the line); parent = region.
GW_STRADDLE = 40                 # slot top -> glyph centre (GLYPH_TOP + GLYPH_H / 2)
GW_SIDE_DX = 38                  # slot left offset from a side border (round(ICON_W / 2))
SIDE_GW_Y0 = ROW1_Y              # first right-border slot
LEFT_GW_Y0 = SIDE_GW_Y0          # first left-border slot: same y series as the right-border slots (spec 7.3)
SIDE_GW_PITCH = ROW_H
VCN_BOTTOM_PAD_GW = 60           # VCN bottom padding when bottom-border gateways exist
VCN_SIDE_PAD = 60                # VCN right padding when right-border gateways exist
SIDE_INSET = 40                  # extra left inset of the VCN content when left-border gateways exist
VCN_COLUMN_GAP_GW = 110          # column gap after a VCN with right-border gateways: two 105 px
                                 # captions on facing borders must not touch (>= LABEL_W + 1)
SGW_ICONS = ("service_gateway", "sgw", "networking_service_gateway")
LPG_ICONS = ("remote_peering_gateway", "rpg", "networking_remote_peering_gateway")
# Icon key -> gateway type, for models that give an icon but no "type".
GW_ICON_TYPES = {
    "internet_gateway": "igw", "igw": "igw", "networking_internet_gateway": "igw",
    "nat_gateway": "nat", "nat": "nat", "networking_nat_gateway": "nat",
    "service_gateway": "sgw", "sgw": "sgw", "networking_service_gateway": "sgw",
    "remote_peering_gateway": "lpg", "rpg": "lpg", "networking_remote_peering_gateway": "lpg",
}

OSN_GAP = 45                     # last VCN column -> Oracle Services Network panel (nested canvas)
OSN_BAND_GAP = 45                # VCN stack bottom -> OSN band top (Location Canvas, G5)
OSN_LABEL = "Oracle Services Network"
TOP_GW_X0 = 50                   # first top-border slot, measured from the VCN's RIGHT edge inwards
VCN_TOP_PAD_GW = 60              # VCN top padding when top-border gateways exist
VCN_Y_TOP_GW = 110               # region-local VCN y when any VCN carries top-border gateways.
                                 # The caption hangs above the glyph, whose slot starts
                                 # GW_STRADDLE above the VCN, so the caption's top sits at
                                 # vcn_y - (GW_STRADDLE + LABEL_GAP + LABEL_H) = vcn_y - 87;
                                 # PAD + 87 = 107, rounded up to the 10 px grid.
GW_SORT_ORDER = ("igw", "nat", "sgw", "lpg")   # B01: deterministic slot order on every side

DRG_GAP = 45                     # DRG column -> first VCN column
ATT_W = 100                      # attachment box
ATT_H = 44                       # minimum height (a two-line label); grown to fit longer text
ATT_GAP = 15                     # DRG slot -> attachment boxes
ATT_PITCH = 56                   # vertical pitch of stacked ATT_H boxes
ATT_VGAP = ATT_PITCH - ATT_H     # gap between stacked attachment boxes, whatever their height
ATT_FONT_SIZE = LABEL_FONT_SIZE  # BOX_STYLE font size (label_lines / height estimate)
ATT_TEXT_PAD = 4                 # text inset each side of an attachment box
DRG_CLUSTER_GAP = 40             # between stacked DRG clusters
DRG_RT_GAP = 6                   # DRG caption bottom -> route-table badge strip
DRG_RT_MAX = 2                   # Oracle creates two default DRG route tables (managingDRGs.htm)

# B05 / B06 / G6: one grouping mechanism - a box around named items in a
# subnet (the slide-32 OKE cluster) or around whole subnet rows in a VCN.
GRP_PAD = 15                     # padding left / right / below the members
GRP_TITLE_H = 30                 # title band above them (top-centre label)

# B04 / L2: compartment containers (opt-in) and the tenancy wrapper.
CMP_PAD = 30                     # compartment inner padding around its VCN columns
CMP_TITLE_H = 40                 # compartment title band above the first VCN
CMP_GAP = 40                     # between sibling compartment containers
TEN_PAD = 25                     # tenancy container padding around the compartment row
TEN_TITLE_H = 40                 # tenancy title band

# 6.2: which view layer a cell belongs to. A layer is a child of the root and a
# cell belongs to the layer of its TOP-LEVEL ancestor (V2), so only page-level
# annotation can be layered: the badges (which are reparented after the whole
# recipe has run, keeping their absolute position) and the model's own edges.
# Containers, icons, gateways, the DRG cluster, the attachment boxes, the
# attachment connectors, the title, the notes and the legend stay on the base
# "Network" layer.
LAYER_BADGE_KINDS = {"routes": ("route_table", "drg_route_table"),
                     "security": ("security_list", "nsg")}
EDGE_LAYERS = {"data": "dataflow", "control": "management", "management": "management",
               "association": "associations", "attachment": None,
               "analytics": "dataflow", "datalake": "dataflow"}


def _edge_layer(kind) -> "str | None":
    """View layer of one MODEL edge kind (not the builder kind): 6.2's table.

    ``attachment`` is structure, so it stays on the base layer. An unknown kind
    follows ``EDGE_KINDS``, which reads it as ``data``.
    """
    return EDGE_LAYERS.get(str(kind or "data").lower(), "dataflow")


# model edge kind -> builder kind (+ colour). analytics / datalake are project
# extensions kept for compatibility; management is an alias of control.
EDGE_KINDS = {
    "data": dict(kind="data", color=None),
    "control": dict(kind="control", color=None),
    "management": dict(kind="control", color=None),
    "association": dict(kind="association", color=None),
    "attachment": dict(kind="attachment", color=None),
    "analytics": dict(kind="data", color=COLORS["edge_accent"]),
    "datalake": dict(kind="control", color=COLORS["edge_purple"]),
}


def load_model(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _gateway_type(gw: dict) -> str:
    """``igw`` | ``nat`` | ``sgw`` | ``lpg`` | ``""`` - the declared type wins over the icon."""
    gtype = str(gw.get("type") or "").strip().lower()
    return gtype or GW_ICON_TYPES.get(str(gw.get("icon") or ""), "")


# Every helper below takes an optional ``view``; this is what it falls back to,
# so a 1.4.0 call site (and a test that calls a helper directly) keeps working.
_DEFAULT_VIEW = ov.resolve_view({})
_TYPE_LABELS = None


def _type_labels() -> dict:
    """Human resource-type labels for ``render_caption``'s ``resource_type`` field.

    ``oci_view`` may not import the parser (V9), and the parser's
    ``RESOURCE_ICONS`` is where Oracle's own wording lives, so the recipe - which
    already depends on both - is the place that joins them. Imported lazily and
    cached: a hand-written model that never asks for ``resource_type`` never
    pays for it.
    """
    global _TYPE_LABELS
    if _TYPE_LABELS is None:
        try:
            from parse_terraform import RESOURCE_ICONS
            _TYPE_LABELS = {k: v[1] for k, v in RESOURCE_ICONS.items()}
        except ImportError:                      # pragma: no cover - defensive
            _TYPE_LABELS = {}
    return _TYPE_LABELS


def _label_h(view: dict) -> int:
    """V6: the caption BOX height for a view. ICON_W / LABEL_W / COL_W never change.

    A budget of up to three lines keeps ``LABEL_H``, which is what makes the
    default output byte-identical to 1.4.0; above that the box is grown with
    ``add_icon``'s own per-line arithmetic and floored at ``LABEL_H_DETAILED``
    (88 px = six lines), so the four-field detailed preset - which routinely
    renders five or six lines once ``Compartment: ...`` wraps - still clears
    rule 5's ``n * LABEL_FONT_SIZE * 1.25`` height escape.

    The budget is a FIELD count, not a wrapped-line count: a long custom
    ``label_fields`` / ``label_tag_keys`` value can still wrap past the box and
    raise a rule-5 WARNING (only ``--strict`` fails on it).
    """
    budget = int((view or {}).get("line_budget") or LABEL_LINE_BUDGET["network"])
    if budget <= LABEL_LINE_BUDGET["network"]:
        return LABEL_H
    return max(LABEL_H_DETAILED, budget * LABEL_LINE_H + 4)


def _row_h(view: dict) -> int:
    """Icon row pitch for a view: ROW_H plus whatever the caption box grew by."""
    return ROW_H + max(0, _label_h(view) - LABEL_H)


def _icon_kwargs(view: dict) -> dict:
    """``place_icons`` keywords for a view.

    ``label_h`` is passed ONLY when the mode needs a taller box: leaving it
    unset keeps ``add_icon``'s 1.4.0 auto-sizing, under which an authored
    four-line caption still gets a 60 px box instead of being clipped.
    """
    label_h = _label_h(view)
    kwargs = {"row_h": _row_h(view)}
    if label_h > LABEL_H:
        kwargs["label_h"] = label_h
    return kwargs


def _edge_label(text, view: dict) -> str:
    """Connector labels follow the resolved view's ``edge_labels`` gate, only.

    6.3's "the minimal label mode drops connector labels" is applied once, in
    ``oci_view.resolve_view``, which sets ``edge_labels`` False as a default for
    an explicitly chosen minimal mode; 6.4's executive level sets the same gate
    from its own table. Testing the label mode here as well would give two
    places that can disagree, and would silently ignore an explicit
    ``edge_labels`` model key.
    """
    view = view or _DEFAULT_VIEW
    if not view.get("edge_labels", True):
        return ""
    return str(text or "")


def _view_ctx(model: dict, locations=None, gateway_edge=None, subnet_label=None,
              attachment_style=None, show_compartments=None,
              label_mode=None, label_fields=None, label_tag_keys=None,
              layers=None, hidden_layers=None, detail=None, show_edges=None,
              view=None) -> dict:
    """The view choices of one diagram: model keys, with the build_diagram kwargs winning.

    ``internet`` is synthesised with no items when the canvas is the Location
    Canvas and some VCN has an Internet Gateway, so the IGW always has
    something to face (spec section 5).
    """
    m = dict(model or {})
    for key, value in (("locations", locations), ("gateway_edge", gateway_edge),
                       ("subnet_label", subnet_label), ("attachment_style", attachment_style)):
        if value is not None:
            m[key] = value
    if show_compartments is not None:
        m["show_compartments"] = bool(show_compartments)
    mode = locations_mode(m)
    internet = m.get("internet")
    has_igw = any(_gateway_type(g) == "igw"
                  for v in (m.get("vcns") or []) for g in (v.get("gateways") or []))
    if internet is None and mode == "outside" and has_igw:
        internet = {"name": "Internet", "items": []}
    # 6.1: one resolution order for every view key. The v1.4.0 keys the recipe
    # already owned stay where they are; everything the label modes, the layers,
    # the detail levels, the filter and the purposes need comes out of
    # oci_view.resolve_view, whose answers for subnet_label reproduce
    # oci_topology.subnet_label_mode exactly for every 1.4.0 value.
    # 8: build_diagram resolves the view BEFORE it filters (the filter is part of
    # the view) and hands the result back in, so the Internet box below is
    # synthesised from the VCNs that actually survived.
    if view is None:
        view = ov.resolve_view(m, label_mode=label_mode, label_fields=label_fields,
                               label_tag_keys=label_tag_keys, layers=layers,
                               hidden_layers=hidden_layers, detail=detail,
                               show_edges=show_edges)
        for note in view["notes"]:
            print(note, file=sys.stderr)
    return {"locations": mode,
            "gateway_edge": gateway_edge_mode(m),
            "subnet_label": view["subnet_label"],
            "attachment_style": attachment_style_of(m),
            # Both of these used to be read straight off the model; taking them
            # from the resolved view keeps ctx and view from ever diverging and
            # is what lets a detail level or a purpose set them (6.1).
            "show_compartments": view["show_compartments"],
            "internet": internet,
            "third_party": list(m.get("third_party") or []),
            "has_internet": bool(internet),
            "view": view}


def _tier(subnet: dict) -> str:
    t = (subnet.get("tier") or "").lower()
    if t in ROW_TIERS or t in DATA_TIERS:
        return t
    name = (subnet.get("name") or "").lower()
    for key, tier in (("lb", "lb"), ("web", "lb"), ("dmz", "lb"), ("pub", "lb"),
                      ("app", "app"), ("api", "app"), ("worker", "app"),
                      ("oke", "compute"), ("node", "compute"), ("compute", "compute"),
                      ("mgmt", "mgmt"), ("bastion", "mgmt"), ("ops", "mgmt"),
                      ("db", "data"), ("data", "data"), ("database", "data")):
        if key in name:
            return tier
    return "other"


def _grid(n: int, max_cols: int):
    if n <= 0:
        return 1, 1
    cols = min(max_cols, n)
    rows = int(math.ceil(n / cols))
    return rows, cols


def _two_line(line1: str, line2: str) -> str:
    """Oracle's two-line container title (slide 18): bold name, light Bark CIDR below it."""
    top = escape_label(line1)
    if not line2:
        return top
    # font-weight: normal is required, not cosmetic: the enclosing vcn / subnet
    # container style carries fontStyle=1, and the nested <font> would inherit
    # bold, so slide 18's "Text2: 9pt, light" line would render bold.
    return (f'{top}<br><font style="font-size: {TITLE_LINE2_FONT}px; font-weight: normal" '
            f'color="{COLORS["text_primary"]}">{escape_label(line2)}</font>')


def _subnet_title_lines(subnet: dict, mode: str = "twoline") -> list:
    """The subnet title as plain text lines - what the width estimate measures."""
    name = subnet.get("name", "subnet")
    cidr = subnet.get("cidr")
    if mode == "inline":
        label = f"{name} ({cidr})" if cidr else name
        if subnet.get("public") and "public" not in label.lower():
            label += " - public"
        return [label]
    line1, line2 = label_parts(name, cidr, subnet.get("public"), with_cidr=(mode != "name"))
    return [ln for ln in (line1, line2) if ln]


def _title_width(lines, font_size: float) -> float:
    return max((edge_label_extent(ln, font_size)[0] for ln in lines), default=0.0)


def _subnet_label(subnet: dict, mode: str = "twoline") -> str:
    """B08 / L4: name (+ Public/Private token) on line 1, CIDR on line 2. HTML in both modes."""
    lines = _subnet_title_lines(subnet, mode)
    if mode == "inline":
        return escape_label(lines[0])
    return _two_line(lines[0], lines[1] if len(lines) > 1 else "")


def _vcn_title_lines(vcn: dict, mode: str = "twoline") -> list:
    """The VCN title as plain text lines - what the width estimate measures."""
    name = vcn.get("name", "vcn")
    cidr = vcn.get("cidr")
    if mode == "inline":
        return [f"VCN: {name} ({cidr})" if cidr else f"VCN: {name}"]
    line1, line2 = label_parts(f"VCN: {name}", cidr, with_cidr=(mode != "name"))
    return [ln for ln in (line1, line2) if ln]


def _vcn_label(vcn: dict, mode: str = "twoline") -> str:
    lines = _vcn_title_lines(vcn, mode)
    if mode == "inline":
        return escape_label(lines[0])
    return _two_line(lines[0], lines[1] if len(lines) > 1 else "")


def _vcn_title_w(vcn: dict, d: DrawioBuilder, mode: str = "twoline") -> float:
    """Widest line of the VCN's own title, each line at the size it is drawn in."""
    lines = _vcn_title_lines(vcn, mode)
    if not lines:
        return 0.0
    sizes = [d.profile["vcn_font"]] + [TITLE_LINE2_FONT] * (len(lines) - 1)
    return max(edge_label_extent(ln, sz)[0] for ln, sz in zip(lines, sizes))


def _top_gw_min_w(vcn: dict, d: DrawioBuilder, n_top: int, mode: str = "twoline") -> int:
    """VCN width that keeps the last top-border gateway slot clear of the VCN title.

    Top slots are counted from the VCN's RIGHT edge inwards, so the leftmost of
    them - slot ``n_top - 1`` - is the one that can reach the container's own
    top-left title band. The title is not a cell, so ``validate()`` cannot see
    the collision (drawio_builder keeps it as a routing obstacle only): the room
    has to be reserved here instead.
    """
    if n_top <= 0:
        return 0
    need = (_vcn_title_w(vcn, d, mode) + SUBNET_TITLE_PAD + PAD
            + TOP_GW_X0 + ICON_W + (n_top - 1) * GW_PITCH)
    return int(math.ceil(need))


def _vcn_order(vcns) -> dict:
    """VCN name / address / 'vcn:<name>' / gateway address -> column index (for LPG peers)."""
    order = {}
    for i, v in enumerate(vcns):
        for key in (v.get("name"), v.get("address"), f"vcn:{v.get('name')}"):
            if key:
                order.setdefault(str(key), i)
        for g in v.get("gateways") or []:
            if g.get("address"):
                order.setdefault(str(g["address"]), i)
    return order


def _is_sgw(gw: dict) -> bool:
    """Service Gateway: the declared type wins; the icon key decides when no type is given."""
    gtype = str(gw.get("type") or "").lower()
    return gtype == "sgw" or (not gtype and str(gw.get("icon") or "") in SGW_ICONS)


def _gateway_side(gw: dict, vcn_index: int, order: dict, ctx=None) -> str:
    """Which VCN border a gateway straddles (G4, G5).

    ``gateways[].side`` wins over everything. Otherwise: the Internet-facing
    gateways (IGW, NAT) take the border facing the Internet box - the right one
    under the Location Canvas for the rightmost VCN column, the top one for
    every other column, the bottom one in the 1.3.0 nested canvas - and
    the Service Gateway takes the border facing the Oracle Services Network:
    bottom when the OSN is a band under the stack, right when it is a column.
    An LPG faces its peer's column. Called with three arguments (no ``ctx``)
    this reproduces the 1.3.0 choice exactly.
    """
    side = str(gw.get("side") or "").strip().lower()
    if side:
        if side not in GATEWAY_SIDES:
            raise ValueError(f"gateways[].side must be one of {GATEWAY_SIDES}, not {gw.get('side')!r}")
        return side
    gtype = _gateway_type(gw)
    outside = bool(ctx) and ctx.get("locations") == "outside"
    edge = (ctx or {}).get("gateway_edge") or "bottom"
    if edge == "auto":
        edge = "internet" if (outside and ctx.get("has_internet")) else "bottom"
    if gtype == "sgw":
        return "bottom" if outside else "right"
    if gtype == "lpg":
        peer = gw.get("peer")
        peer_idx = order.get(str(peer)) if peer is not None else None
        if peer_idx is None or peer_idx == vcn_index:
            return "bottom"
        return "right" if peer_idx > vcn_index else "left"
    if gtype in ("igw", "nat"):
        if edge != "internet":
            return {"top": "top", "bottom": "bottom"}[edge]
        # G4: only the rightmost VCN column's right border faces the Internet
        # box - every other column's right border faces the next VCN - so the
        # Internet-facing gateways of the other columns take the top border,
        # which faces the Internet box's row (deck slide 31).
        last_index = max(order.values()) if order else 0
        return "right" if vcn_index >= last_index else "top"
    return "bottom"


def _gateway_sort_key(gw: dict) -> tuple:
    """B01: IGW, NAT, SGW, LPG, then address - never the model's list order."""
    gtype = _gateway_type(gw)
    rank = GW_SORT_ORDER.index(gtype) if gtype in GW_SORT_ORDER else len(GW_SORT_ORDER)
    return (rank, str(gw.get("address") or gw.get("label") or ""))


def _gateway_sides(vcn: dict, vcn_index: int, order: dict, ctx=None) -> dict:
    sides = {"top": [], "left": [], "right": [], "bottom": []}
    for g in sorted(vcn.get("gateways") or [], key=_gateway_sort_key):
        sides[_gateway_side(g, vcn_index, order, ctx)].append(g)
    return sides


def _place_edge_gateway(d: DrawioBuilder, parent_id, box, side: str, slot: int, gw: dict, reg,
                        caption_above=False, view=None) -> str:
    """One gateway icon centred on a VCN border; box = (x, y, w, h) of the VCN in the parent's space.

    Top-border slots are counted from the VCN's RIGHT edge inwards, because
    deck slide 31 puts the Internet Gateway at the right end of the top border,
    nearest the Internet box.
    """
    vx, vy, vw, vh = box
    if side == "bottom":
        x, y = vx + PAD + slot * GW_PITCH, vy + vh - GW_STRADDLE
    elif side == "top":
        x, y = vx + vw - TOP_GW_X0 - ICON_W - slot * GW_PITCH, vy - GW_STRADDLE
    elif side == "right":
        x, y = vx + vw - GW_SIDE_DX, vy + SIDE_GW_Y0 + slot * SIDE_GW_PITCH
    else:
        x, y = vx - GW_SIDE_DX + 1, vy + LEFT_GW_Y0 + slot * SIDE_GW_PITCH
    # 6.3: a gateway caption is width-critical (it straddles a border and carries
    # label_fill), so the renderer only ever adds the resource type, and only in
    # the detailed mode.
    spec = {"label": ov.render_caption(gw, view or _DEFAULT_VIEW, kind="gateway",
                                       type_labels=_type_labels()),
            "icon": gw.get("icon", "service_gateway")}
    if gw.get("address"):
        spec["key"] = str(gw["address"])
    for k in ("metadata", "tooltip", "link"):
        if gw.get(k):
            spec[k] = gw[k]
    ids, _ = d.place_icons(parent_id, [spec], cols=1, x0=int(x), y0=int(y),
                           label_fill=COLORS["region_fill"], caption_above=caption_above)
    reg.add_item(gw, ids[0])
    return ids[0]


def _split_services(items) -> tuple:
    """(regional, vcn-resident) using item['regional'] or the icon-key table."""
    items = list(items or [])
    return [s for s in items if is_regional(s)], [s for s in items if not is_regional(s)]


def _layout_osn(d: DrawioBuilder, region_id, items, x, y, min_h, reg, min_w=None, cols=None,
                view=None) -> tuple:
    """Region-level Oracle Services Network panel; returns (id, w, h).

    A right-hand column (2 icon columns, the 1.3.0 nested canvas) or, under the
    Location Canvas, a full-width band below the VCN stack (G5) - then the
    caller passes the stack's width and the number of columns that fits it.
    """
    view = view or _DEFAULT_VIEW
    rows_n, cols = _grid(len(items), cols or 2)
    prov_w = max(cols * COL_W + SUBNET_EXTRA_W, int(min_w or 0))
    prov_h = (ROW1_Y + (rows_n - 1) * _row_h(view) + ICON_FOOTPRINT_H
              + (_label_h(view) - LABEL_H) + SUBNET_BOTTOM_PAD)
    pid = d.add_group(OSN_LABEL, x, y, prov_w, prov_h, parent=region_id,
                      group_type="oracle_services_network", key="osn", label_position="left")
    reg.containers["osn"] = pid
    reg.containers.setdefault("services", pid)
    _icon_items(d, pid, items, cols, reg=reg, view=view)
    w, h = d.fit_to_children(pid, pad=PAD, min_w=max(prov_w, int(min_w or 0)),
                             min_h=max(prov_h, min_h or 0))
    return pid, w, h


def _children_bottom(d: DrawioBuilder, cid) -> float:
    """Bottom edge, in ``cid``'s own coordinates, of everything already inside it.

    Mirrors ``DrawioBuilder.fit_to_children``: an icon counts with its caption,
    and a badge straddles its host's border on purpose so it never counts.
    Used to floor the Oracle Services Network band under every region child
    placed above it, not merely under the tallest VCN.
    """
    bottom = 0.0
    for kid, ke in d._cells.items():
        if ke["parent"] != cid or ke["kind"] in ("edge", "layer") or ke.get("badge"):
            continue
        if ke["kind"] == "icon":
            _x, y, _w, h = d.footprint(kid)
        else:
            y, h = ke["y"], ke["h"]
        bottom = max(bottom, y + h)
    return bottom


class _Registry:
    """address / reference -> cell id resolution for edges."""

    def __init__(self):
        self.by_address = {}
        self.by_caption = {}
        self.containers = {}
        self.badge_kinds = set()      # B07: legend rows only for the badges actually drawn
        # 6.2: layer name -> the cell ids the post-pass reparents onto it.
        self.layer_cells = {}

    def add_item(self, item: dict, cid: str):
        addr = item.get("address")
        if addr:
            self.by_address[str(addr)] = cid
        first = str(item.get("label", "")).split("\n")[0].strip().lower()
        if first:
            self.by_caption.setdefault(first, []).append(cid)

    def resolve(self, ref) -> str:
        ref = str(ref)
        if ref in self.by_address:
            return self.by_address[ref]
        if ref in self.containers:
            return self.containers[ref]
        hits = self.by_caption.get(ref.strip().lower(), [])
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ValueError(f"edge endpoint {ref!r} matches {len(hits)} items; use an 'address'")
        raise ValueError(f"edge endpoint {ref!r} not found (known addresses: "
                         f"{', '.join(sorted(self.by_address)[:12])}...)")


# The implementation lives in oci_topology so parse_terraform can validate the
# same shapes without importing the builder; the module-local name stays.
_badge_refs = badge_refs


def _badge_tooltip(kind: str, refs: list, detailed: bool = False) -> str:
    """6.3: badges never gain a caption; the label mode reaches them through the tooltip."""
    def one(ref):
        if detailed and ref.get("address"):
            return f"{ref['name']} ({ref['address']})"
        return ref["name"]
    return f"{kind}{'s' if len(refs) > 1 else ''}: " + ", ".join(one(r) for r in refs)


def _register_badge(reg, refs: list, bid: str) -> None:
    if reg is None:
        return
    for r in refs:
        if r["address"]:
            reg.by_address.setdefault(r["address"], bid)   # first badge wins: several subnets share a construct


def _add_subnet_badges(d: DrawioBuilder, sid: str, subnet: dict, width, reg, view=None) -> list:
    """Route-table / security-list badges straddling the subnet's top-right corner.

    Route table centred on the corner, security lists one badge to its left
    (toolkit slide 18: half-size icons used as labels of the subnet box).
    Returns the badge ids (0-2).
    """
    ids = []
    cx = width
    view = view or _DEFAULT_VIEW
    detailed = view.get("label_mode") == "detailed"
    # 6.4 / V4: a gate that is off still draws when its layer is enabled - the
    # layer then carries the visibility, which is the whole point of the feature.
    rt = _badge_refs(subnet.get("route_table")) if ov.draws(view, "badges_routes") else []
    if rt:
        bid = d.add_badge("route_table", cx, 0, parent=sid, host=sid, key=f"{sid}-rt",
                          tooltip=_badge_tooltip("Route table", rt, detailed),
                          metadata={"route_table": ", ".join(r["name"] for r in rt)})
        _register_badge(reg, rt, bid)
        reg.badge_kinds.add("route_table")
        reg.layer_cells.setdefault("routes", []).append(bid)
        ids.append(bid)
        cx -= BADGE_SIZE + BADGE_GAP
    sls = _badge_refs(subnet.get("security_lists")) if ov.draws(view, "badges_security") else []
    if sls:
        bid = d.add_badge("security_list", cx, 0, parent=sid, host=sid, key=f"{sid}-sl",
                          tooltip=_badge_tooltip("Security list", sls, detailed),
                          metadata={"security_lists": ", ".join(r["name"] for r in sls)})
        _register_badge(reg, sls, bid)
        reg.badge_kinds.add("security_list")
        reg.layer_cells.setdefault("security", []).append(bid)
        ids.append(bid)
    return ids


def _add_nsg_badge(d: DrawioBuilder, parent, cid: str, item: dict, reg=None, view=None):
    """NSG shield badge over the top-right of the host icon's slot.

    None when the item has no ``nsgs`` and when the view's ``badges_security``
    gate is off with no ``security`` layer to carry it (6.4 / V4).
    """
    if not ov.draws(view or _DEFAULT_VIEW, "badges_security"):
        return None
    nsgs = _badge_refs(item.get("nsgs"))
    if not nsgs:
        return None
    sx, sy, sw, _sh = d.bbox(cid)
    bid = d.add_badge("nsg", sx + sw - BADGE_SIZE / 2, sy + BADGE_SIZE / 2, parent=parent, host=cid,
                      key=f"{cid}-nsg",
                      tooltip=_badge_tooltip("NSG", nsgs,
                                             (view or _DEFAULT_VIEW).get("label_mode") == "detailed"),
                      metadata={"nsgs": ", ".join(r["name"] for r in nsgs)})
    _register_badge(reg, nsgs, bid)
    if reg is not None:
        reg.badge_kinds.add("nsg")
        reg.layer_cells.setdefault("security", []).append(bid)
    return bid


def _icon_items(d: DrawioBuilder, parent, items, cols, x0=PAD, y0=ROW1_Y, reg=None, view=None):
    view = view or _DEFAULT_VIEW
    types = _type_labels()
    specs = []
    for it in items:
        # 6.3 / V5: the caption is the authored label followed by the mode's
        # extra fields, each skipped when its value already appears in the text.
        spec = {"label": ov.render_caption(it, view, type_labels=types),
                "icon": it.get("icon", "vm")}
        for k in ("metadata", "tooltip", "link"):
            if it.get(k):
                spec[k] = it[k]
        if it.get("address"):
            spec["key"] = str(it["address"])
        specs.append(spec)
    ids, bbox = d.place_icons(parent, specs, cols=cols, x0=x0, y0=y0, **_icon_kwargs(view))
    for it, cid in zip(items, ids):
        _add_nsg_badge(d, parent, cid, it, reg, view)
    if reg is not None:
        for it, cid in zip(items, ids):
            reg.add_item(it, cid)
    return ids, bbox


def _subnet_min_w(subnet: dict, d: DrawioBuilder, mode: str = "twoline") -> int:
    """Minimum subnet width so a badged subnet's title does not run under its corner badges.

    Measured per title LINE: the two-line form (B08) puts the CIDR on its own
    line, so the same subnet needs less width than the 1.3.0 inline form.
    """
    if not (_badge_refs(subnet.get("route_table")) or _badge_refs(subnet.get("security_lists"))):
        return 0
    tw = _title_width(_subnet_title_lines(subnet, mode), d.profile["subnet_font"])
    return int(math.ceil((tw + SUBNET_TITLE_PAD + BADGE_RESERVE) / 10.0) * 10)


def _layout_group_boxes(d: DrawioBuilder, parent_id, entries, members: dict, reg) -> list:
    """G6 / G8: one container per ``groups[]`` entry, fitted to its members.

    The members are re-parented into the box (with the badges that decorate
    them), so the validator walks the true chain and the lattice router meets
    the box exactly as it meets a VCN or a subnet (decision 9). The box's id is
    the entry's ``key``, so an edge may terminate on it (slide 32: the load
    balancer connects to the OKE box, not to an icon inside it).
    """
    out = []
    for entry in entries:
        ids = []
        for name in entry["members"]:
            cid = members.get(str(name))
            if cid is None:
                raise ValueError(
                    f"groups[] box {entry['label']!r}: {str(name)!r} is not a member of this "
                    f"container (known: {', '.join(sorted(members)) or 'none'})")
            ids.append(cid)
        x0, y0, x1, y1 = _union_box(d, ids)
        # G8: members listed non-contiguously would draw a box straight over the
        # sibling between them. The gate would report that as a sibling OVERLAP
        # far from its cause, so refuse it here with the model-level reason.
        bx0, by0, bx1, by1 = x0 - GRP_PAD, y0 - GRP_TITLE_H, x1 + GRP_PAD, y1 + GRP_PAD
        for oid, oe in d._cells.items():
            if (oid in ids or oe.get("badge") or oe["parent"] != parent_id
                    or oe["kind"] not in ("group", "icon", "box")):
                continue          # a badge follows its host; only real siblings count
            ox, oy, ow, oh = d.footprint(oid) if oe["kind"] == "icon" else d.bbox(oid)
            if ox < bx1 and ox + ow > bx0 and oy < by1 and oy + oh > by0:
                raise ValueError(
                    f"groups[] box {entry['label']!r} would enclose {oid!r}, which is not one of "
                    f"its members; list its members contiguously")
        gid = d.add_group(entry["label"], x0 - GRP_PAD, y0 - GRP_TITLE_H,
                          (x1 - x0) + 2 * GRP_PAD, (y1 - y0) + GRP_TITLE_H + GRP_PAD,
                          parent=parent_id, group_type=entry["type"], key=entry["key"])
        for cid in ids:
            old_parent = d._cells[cid]["parent"]
            d.reparent(cid, gid)
            for bid, be in list(d._cells.items()):
                # only a badge drawn ALONGSIDE the member follows it; a subnet's
                # own corner badges are its children and stay inside it
                if be.get("badge") and be.get("host") == cid and be["parent"] == old_parent:
                    d.reparent(bid, gid)
        reg.containers[entry["key"]] = gid
        out.append(gid)
    return out


def _layout_subnet(d: DrawioBuilder, vcn_id, subnet, x, y, max_cols, reg, min_w=None,
                   label_mode="twoline", view=None):
    view = view or _DEFAULT_VIEW
    items = subnet.get("items") or []
    rows, cols = _grid(len(items), max_cols)
    min_w = max(min_w or 0, _subnet_min_w(subnet, d, label_mode))
    key = f"subnet:{subnet.get('name', '')}"
    groups = normalise_groups(subnet, "subnet", key)
    # Decision 7: the clearance is measured from the subnet's own title strip -
    # the grid drops by GRP_TITLE_H, so a group box's top lands exactly on
    # ROW1_Y and its title band never overlaps the subnet's.
    grp_top = GRP_TITLE_H if groups else 0
    # _union_box takes an icon's FOOTPRINT, whose caption overhangs the slot by
    # (LABEL_W - ICON_W) / 2 on each side, so a grid that starts at PAD would
    # put the box at PAD - GRP_PAD - 15 = -10, outside the subnet - and
    # fit_to_children only ever grows. Inset the grid by GRP_PAD instead.
    grp_side = GRP_PAD if groups else 0
    prov_w = max(cols * COL_W + SUBNET_EXTRA_W + 2 * grp_side, min_w)
    prov_h = (ROW1_Y + grp_top + (rows - 1) * _row_h(view) + ICON_FOOTPRINT_H
              + (_label_h(view) - LABEL_H) + SUBNET_BOTTOM_PAD + grp_side)
    sid = d.add_group(_subnet_label(subnet, label_mode), x, y, prov_w, prov_h, parent=vcn_id,
                      group_type="subnet", raw_html=True,
                      key=f"subnet:{subnet.get('name', '')}" if subnet.get("name") else None,
                      metadata=subnet.get("metadata"), tooltip=subnet.get("tooltip"))
    reg.containers[f"subnet:{subnet.get('name', '')}"] = sid
    if subnet.get("address"):
        reg.by_address[str(subnet["address"])] = sid
    if items:
        item_ids, _ = _icon_items(d, sid, items, cols, x0=PAD + grp_side,
                                  y0=ROW1_Y + grp_top, reg=reg, view=view)
        if groups:
            by_address = {str(it["address"]): cid for it, cid in zip(items, item_ids)
                          if it.get("address")}
            _layout_group_boxes(d, sid, groups, by_address, reg)
        w, h = d.fit_to_children(sid, pad=PAD, min_w=max(prov_w, min_w or 0), min_h=prov_h)
    else:
        if groups:
            _layout_group_boxes(d, sid, groups, {}, reg)      # raises: no member can exist
        w, h = prov_w, max(prov_h, 120)
        if min_w:
            w = max(w, min_w)
        d.resize(sid, w=w, h=h)
    _add_subnet_badges(d, sid, subnet, w, reg, view)  # after the final size: badges sit on the corner
    return sid, w, h


def _layout_vcn(d: DrawioBuilder, region_id, vcn: dict, x, y, reg, max_row_w=MAX_ROW_W,
                inset_left=0, right_pad=PAD, bottom_pad=VCN_BOTTOM_PAD, min_h=200,
                min_w=VCN_MIN_W, label_mode="twoline", top_pad=PAD, view=None):
    """Lay out one VCN box; min_h / min_w are the minimum FINAL height / width (borders
    included), so the caller can reserve room for the gateways that straddle the border."""
    view = view or _DEFAULT_VIEW
    vid = d.add_group(_vcn_label(vcn, label_mode), x, y, 400, 300, parent=region_id,
                      group_type="vcn", raw_html=True,
                      key=f"vcn:{vcn.get('name', '')}" if vcn.get("name") else None,
                      metadata=vcn.get("metadata"), tooltip=vcn.get("tooltip"))
    reg.containers[f"vcn:{vcn.get('name', '')}"] = vid
    if vcn.get("address"):
        reg.by_address[str(vcn["address"])] = vid
    subnets = list(vcn.get("subnets") or [])
    row_subnets = [s for s in subnets if _tier(s) in ROW_TIERS]
    row_subnets.sort(key=lambda s: ROW_TIERS.index(_tier(s)))
    data_subnets = [s for s in subnets if _tier(s) in DATA_TIERS]

    # Row packing (traffic order, wrap when the row budget is exceeded)
    rows, cur, cur_w = [], [], 0.0
    for s in row_subnets:
        n = len(s.get("items") or [])
        _, cols = _grid(n, 2)
        est_w = max(cols * COL_W + SUBNET_EXTRA_W, _subnet_min_w(s, d, label_mode))
        if cur and cur_w + H_GAP + est_w > max_row_w:
            rows.append(cur)
            cur, cur_w = [], 0.0
        cur.append(s)
        cur_w += (H_GAP if cur_w else 0) + est_w
    if cur:
        rows.append(cur)

    vcn_key = f"vcn:{vcn.get('name', '')}"
    vcn_groups = normalise_groups(vcn, "vcn", vcn_key)
    inset_top = max(0, top_pad - PAD) + (GRP_TITLE_H if vcn_groups else 0)
    cy = ROW1_Y + inset_top
    row1_right = PAD + inset_left
    subnet_ids = {}
    for row in rows:
        cx = PAD + inset_left
        bottoms = []
        for s in row:
            sid, w, h = _layout_subnet(d, vid, s, cx, cy, 2, reg, label_mode=label_mode, view=view)
            for k in (s.get("name"), s.get("address")):
                if k:
                    subnet_ids[str(k)] = sid
            cx += w + H_GAP
            bottoms.append(cy + h)
        row1_right = max(row1_right, cx - H_GAP)
        cy = max(bottoms) + V_GAP if bottoms else cy

    # Services panel to the right of the first row
    services = list(vcn.get("services") or [])
    if services:
        rows_n, cols = _grid(len(services), 2)
        prov_w = cols * COL_W + SUBNET_EXTRA_W
        prov_h = (ROW1_Y + (rows_n - 1) * _row_h(view) + ICON_FOOTPRINT_H
                  + (_label_h(view) - LABEL_H) + SUBNET_BOTTOM_PAD)
        px = (row1_right + PANEL_GAP) if rows else PAD + inset_left
        pid = d.add_group(vcn.get("services_label", "OCI Services"), px, ROW1_Y + inset_top,
                          prov_w, prov_h,
                          parent=vid, group_type="services",
                          key=f"services:{vcn.get('name', '')}" if vcn.get("name") else None)
        reg.containers["services"] = pid
        reg.containers[f"services:{vcn.get('name', '')}"] = pid
        _icon_items(d, pid, services, cols, reg=reg, view=view)
        d.fit_to_children(pid, pad=PAD, min_w=prov_w, min_h=prov_h)

    # Data tier subnets, stretched to the width of the rows above
    row_w = max(row1_right - PAD - inset_left, 0)
    for s in data_subnets:
        n = len(s.get("items") or [])
        sid, w, h = _layout_subnet(d, vid, s, PAD + inset_left, cy, max(2, min(5, n or 2)), reg,
                                   min_w=row_w if row_w else None, label_mode=label_mode,
                                   view=view)
        for k in (s.get("name"), s.get("address")):
            if k:
                subnet_ids[str(k)] = sid
        cy += h + V_GAP

    if vcn_groups:
        _layout_group_boxes(d, vid, vcn_groups, subnet_ids, reg)

    w, h = d.fit_to_children(vid, pad=PAD, min_w=VCN_MIN_W, min_h=min_h)
    w = max(w + right_pad - PAD, min_w)
    h += bottom_pad - PAD
    d.resize(vid, w=w, h=h)
    return vid, w, h


def _recentre(d: DrawioBuilder, ids, dy: int) -> None:
    """Translate the given cells vertically. Their children follow for free."""
    if not dy:
        return
    for cid in ids:
        if cid in d._cells:
            d.move(cid, dy=dy)


def _region_children(d: DrawioBuilder, rid: str) -> list:
    """Every non-edge cell parented directly on the region, in insertion order."""
    return [cid for cid, e in d._cells.items()
            if e["parent"] == rid and e["kind"] not in ("edge", "layer")]


def _split_evenly(total: int, n: int) -> list:
    """``n`` integer heights summing to exactly ``total`` (the remainder goes to the first)."""
    if n <= 0:
        return []
    base, extra = divmod(int(total), n)
    return [base + (1 if i < extra else 0) for i in range(n)]


def _hub_item_x(item: dict, straddle: bool, box_w: int) -> int:
    """Slot x of one on-premises item inside its box.

    Decision 5 (toolkit Template 1: the CPE's centre is exactly the box's right
    edge): under the Location Canvas a CPE / IPSec endpoint / virtual circuit
    straddles the region-facing border, mirroring the DRG on the VCN border.
    Everything else (an RPC peer, a firewall, a generic box) keeps the centred
    interior column.
    """
    if straddle and is_onprem_item(item):
        return box_w - GW_SIDE_DX
    return int(round((box_w - ICON_W) / 2 / 10.0) * 10)


def _place_hub_items(d: DrawioBuilder, hid, items, y0, reg, straddle=False, box_w=HUB_W,
                     view=None) -> list:
    # 6.3 "Per element" lists hub items with the workloads and the services, so
    # an on-premises / Internet / 3rd-party icon is captioned from the label
    # mode's field list exactly as a subnet item is - this is also the only
    # place the private_ip field's metadata.ip_address fallback is ever reached.
    view = view or _DEFAULT_VIEW
    types = _type_labels()
    ids = []
    for i, it in enumerate(items):
        spec = {"label": ov.render_caption(it, view, type_labels=types),
                "icon": it.get("icon", "cpe")}
        if it.get("address"):
            spec["key"] = str(it["address"])
        for k in ("metadata", "tooltip"):
            if it.get(k):
                spec[k] = it[k]
        kwargs = _icon_kwargs(view)
        if straddle and is_onprem_item(it):
            kwargs["label_fill"] = COLORS["region_fill"]      # the caption crosses the border
        got, _ = d.place_icons(hid, [spec], cols=1, x0=_hub_item_x(it, straddle, box_w),
                               y0=y0 + i * HUB_PITCH, **kwargs)
        ids.extend(got)
        reg.add_item(it, got[0])
    return ids


def _hub_links(d: DrawioBuilder, hid, hub: dict, items, ids, explicit_pairs, view=None) -> None:
    if hub.get("link_label") is None or len(ids) < 2:
        return
    for (ia, a), (ib, b) in zip(zip(items, ids), zip(items[1:], ids[1:])):
        pair = (str(ia.get("address")), str(ib.get("address")))
        if pair in explicit_pairs or pair[::-1] in explicit_pairs:
            continue  # the model already connects these two hub items
        # 6.3: the edge itself is structural and always drawn; only its label
        # follows the view's edge_labels gate.
        d.add_edge(a, b, _edge_label(hub.get("link_label") or "", view), parent=hid)


def _union_box(d: DrawioBuilder, ids) -> tuple:
    """(x0, y0, x1, y1) covering the given cells in their shared parent's space."""
    x0 = y0 = None
    x1 = y1 = None
    for cid in ids:
        e = d._cells[cid]
        x, y, w, h = d.footprint(cid) if e["kind"] == "icon" else d.bbox(cid)
        x0 = x if x0 is None else min(x0, x)
        y0 = y if y0 is None else min(y0, y)
        x1 = (x + w) if x1 is None else max(x1, x + w)
        y1 = (y + h) if y1 is None else max(y1, y + h)
    return (x0 or 0, y0 or 0, x1 or 0, y1 or 0)


def _compartment_chain(tree, vcn_name: str) -> list:
    """The compartment names enclosing one VCN, outermost first ([] when it is in none)."""
    def walk(nodes, prefix):
        for node in nodes:
            chain = prefix + [node["name"]]
            if vcn_name in node["vcns"]:
                return chain
            hit = walk(node["children"], chain)
            if hit:
                return hit
        return []
    return walk(tree, [])


def _compartment_depth(tree) -> int:
    return max((1 + _compartment_depth(n["children"]) for n in tree), default=0)


def _compartment_gap(chain_a: list, chain_b: list) -> int:
    """Extra column gap between two VCNs: the borders that close and open between them."""
    if chain_a == chain_b:
        return 0
    common = 0
    for a, b in zip(chain_a, chain_b):
        if a != b:
            break
        common += 1
    closing = len(chain_a) - common
    opening = len(chain_b) - common
    return (closing + opening) * CMP_PAD + CMP_GAP


def _compartment_column_order(tree, vcns) -> list:
    """Spec 6.3: the VCN columns grouped by compartment, each compartment taking the
    column order of its first member, with the compartment-less VCNs in a trailing group.

    A compartment container is fitted around the columns its own VCNs occupy, so
    members that are not contiguous would make its box swallow the columns in
    between - an unrelated compartment, or a VCN that is in none - and every such
    diagram would fail ``check_overlaps``. Terraform lists VCNs in an order that has
    nothing to do with compartment membership, so the columns are regrouped here,
    before anything is placed. The relative order of the VCNs inside one compartment,
    and of the compartment-less ones, is preserved.
    """
    first = {}
    for i, v in enumerate(vcns):
        name = str(v.get("name") or "")
        if name:
            first.setdefault(name, i)

    def subtree(node) -> list:
        """The column indices of one compartment and its children, in first-member order."""
        blocks = [(first[n], [first[n]]) for n in node["vcns"] if n in first]
        for child in node["children"]:
            kids = subtree(child)
            if kids:
                blocks.append((min(kids), kids))
        blocks.sort(key=lambda b: b[0])
        return [i for _key, block in blocks for i in block]

    ordered, seen = [], set()
    for node in tree:
        for i in subtree(node):
            if i not in seen:
                seen.add(i)
                ordered.append(i)
    ordered.extend(i for i in range(len(vcns)) if i not in seen)
    return [vcns[i] for i in ordered]


def _layout_hub(d: DrawioBuilder, region_id, hub: dict, vcn_y, vcn_h, reg,
                explicit_pairs=frozenset(), view=None):
    """The v1.3.0 nested on-premises panel: a child of the region, left of the DRG column."""
    view = view or _DEFAULT_VIEW
    items = list(hub.get("items") or [])
    n = max(1, len(items))
    hub_h = int(HUB_ICON_Y0 + (n - 1) * HUB_PITCH + icon_footprint_h(_label_h(view)) + 30)
    hub_y = max(vcn_y, int(round((vcn_y + (vcn_h - hub_h) / 2) / 10.0) * 10))
    title = hub.get("name") or HUB_TITLES[hub_kind(hub)]
    hid = d.add_group(title, HUB_X, hub_y, HUB_W, hub_h,
                      parent=region_id, group_type="onprem", key="hub")
    reg.containers["hub"] = hid
    ids = _place_hub_items(d, hid, items, HUB_ICON_Y0, reg, view=view)
    d.fit_to_children(hid, pad=PAD, min_w=HUB_W, min_h=hub_h)
    _hub_links(d, hid, hub, items, ids, explicit_pairs, view)
    return hid


def _hub_block_h(items, view=None) -> int:
    """Height of the on-premises item column (icons plus their captions).

    V6: the caption box grows with the label mode, so the block a location box
    has to clear grows with it too; HUB_PITCH (200) still exceeds the tallest
    footprint (95 + 2 + LABEL_H_DETAILED = 185), so the pitch itself is fixed.
    """
    return int((max(1, len(items)) - 1) * HUB_PITCH
               + icon_footprint_h(_label_h(view or _DEFAULT_VIEW)))


def _layout_location_hub(d: DrawioBuilder, hub: dict, x, y, w, h, centre_y, reg,
                         explicit_pairs=frozenset(), view=None) -> str:
    """L1: On-Premises as a page-level sibling of the region, its items centred on the VCN stack."""
    view = view or _DEFAULT_VIEW
    items = list(hub.get("items") or [])
    title = hub.get("name") or HUB_TITLES[hub_kind(hub)]
    hid = d.add_group(title, x, y, w, h, parent="1", group_type="onprem", key="hub")
    reg.containers["hub"] = hid
    y0 = max(HUB_ICON_Y0,
             int(round((centre_y - y - _hub_block_h(items, view) / 2) / 10.0) * 10))
    ids = _place_hub_items(d, hid, items, y0, reg, straddle=True, box_w=w, view=view)
    _hub_links(d, hid, hub, items, ids, explicit_pairs, view)
    return hid


def _loc_boxes(ctx: dict) -> list:
    """The right column's boxes, top to bottom: ``(cell key, spec, group type)``."""
    boxes = []
    if ctx["internet"]:
        boxes.append(("internet", ctx["internet"], "internet"))
    for i, tp in enumerate(ctx["third_party"]):
        boxes.append((f"thirdparty:{i}", tp, "third_party_cloud"))
    return boxes


def _loc_box_min_h(spec: dict, view=None) -> int:
    """Minimum height of one right-column box.

    LOC_MIN_H is the empty box's floor; a box that holds items has to be tall
    enough for the whole icon block below the title (``HUB_ICON_Y0``) plus the
    bottom pad, or the caption spills outside the box and ``validate()`` calls
    it a blocking containment error.
    """
    items = list((spec or {}).get("items") or [])
    if not items:
        return LOC_MIN_H
    return max(LOC_MIN_H, HUB_ICON_Y0 + _hub_block_h(items, view) + PAD)


def _fit_min_heights(heights, mins, total: int) -> list:
    """Raise every height to its minimum, taking the difference from the boxes with slack.

    The caller has already grown the region to ``_right_column_min_h()``, so
    ``sum(mins) <= total`` and the repair always converges on heights that sum
    to exactly ``total``.
    """
    hs = [max(int(h), int(m)) for h, m in zip(heights, mins)]
    over = sum(hs) - int(total)
    while over > 0:
        slack = [i for i, (hv, m) in enumerate(zip(hs, mins)) if hv > m]
        if not slack:
            break                      # cannot fit; the boxes keep their minimum
        i = max(slack, key=lambda j: hs[j] - mins[j])
        take = min(over, hs[i] - mins[i])
        hs[i] -= take
        over -= take
    return hs


def _layout_right_column(d: DrawioBuilder, ctx: dict, x, y, h, reg, view=None) -> list:
    """G1: Internet on top, one 3rd Party Cloud box per entry below it, together as tall as
    the region (toolkit Template 1: 210 + 10 + 250 = 470 = the region's height)."""
    boxes = _loc_boxes(ctx)
    if not boxes:
        return []
    n = len(boxes)
    gaps = LOC_STACK_GAP * (n - 1)
    avail = int(h) - gaps
    mins = [_loc_box_min_h(spec, view) for _key, spec, _gtype in boxes]
    if n == 1:
        heights = [int(h)]
    else:
        first = int(round(avail * INTERNET_SPLIT))
        heights = [first] + _split_evenly(avail - first, n - 1)
    # Decision 6: every box is floored at its own minimum and the column still
    # sums to the region's height.
    heights = _fit_min_heights(heights, mins, avail)
    ids = []
    top = y
    for (key, spec, gtype), bh in zip(boxes, heights):
        name = spec.get("name") or ("Internet" if gtype == "internet" else "3rd Party Cloud")
        bid = d.add_group(name, x, top, LOC_W, bh, parent="1", group_type=gtype, key=key)
        reg.containers[key] = bid
        items = list(spec.get("items") or [])
        if items:
            y0 = max(HUB_ICON_Y0,
                     int(round((bh - _hub_block_h(items, view)) / 2 / 10.0) * 10))
            _place_hub_items(d, bid, items, y0, reg, box_w=LOC_W, view=view)
        ids.append(bid)
        top += bh + LOC_STACK_GAP
    return ids


def _right_column_min_h(ctx: dict, view=None) -> int:
    """Height the region needs so every right-column box clears its own content."""
    boxes = _loc_boxes(ctx)
    if not boxes:
        return 0
    return (sum(_loc_box_min_h(spec, view) for _key, spec, _gtype in boxes)
            + LOC_STACK_GAP * (len(boxes) - 1))


def _layout_locations(d: DrawioBuilder, rid, ctx: dict, hub, drgs, stack_y, stack_h, reg,
                      explicit_pairs=frozenset(), view=None) -> dict:
    """B03: translate the fitted region and emit the sibling location boxes.

    Runs after ``fit_to_children(region)`` and before every edge that is routed
    from cell ids, so the translation is invisible to the router (spec 6.2).
    Step 6: the right column is floored at LOC_MIN_H first; only if the floor
    still does not fit does the region grow, and then every region child moves
    down by half the growth so the VCN stack - and the DRG column and the
    on-premises items centred on it - stays centred (decision 6).
    """
    view = view or ctx.get("view") or _DEFAULT_VIEW
    out = {"left_w": 0, "right_w": 0, "dy": 0, "hub": None, "internet": None, "third_party": []}
    if ctx["locations"] != "outside":
        return out
    rx, ry, rw, rh = d.bbox(rid)
    left_gap = max(LOC_GAP_MIN, _hub_gutter(drgs, d.profile["edge_font"])) if drgs else LOC_GAP_MIN
    # Decision 5 puts a straddling item's glyph centre ON the region-facing
    # border, so the half slot that used to sit inside the panel now eats into
    # the gutter _hub_gutter sized for the hybrid label. Give that width back.
    if hub and any(is_onprem_item(it) for it in (hub.get("items") or [])):
        left_gap += ICON_W - GW_SIDE_DX
    left_w = (LOC_W + left_gap) if hub else 0
    right_w = (LOC_W + LOC_GAP_RIGHT) if (ctx["internet"] or ctx["third_party"]) else 0
    need_h = max(_right_column_min_h(ctx, view),
                 (HUB_ICON_Y0 + _hub_block_h(list((hub or {}).get("items") or []), view) + PAD)
                 if hub else 0)
    dy = 0
    if need_h > rh:
        dy = int((need_h - rh) // 2)
        d.resize(rid, h=need_h)
        _recentre(d, _region_children(d, rid), dy)
        rh = need_h
    d.resize(rid, x=rx + left_w)
    centre_y = ry + stack_y + dy + stack_h / 2
    if hub:
        out["hub"] = _layout_location_hub(d, hub, rx, ry, LOC_W, rh, centre_y, reg,
                                          explicit_pairs, view)
    if right_w:
        ids = _layout_right_column(d, ctx, rx + left_w + rw + LOC_GAP_RIGHT, ry, rh, reg,
                                   view=view)
        out["internet"] = ids[0] if ctx["internet"] else None
        out["third_party"] = ids[1:] if ctx["internet"] else ids
    out.update(left_w=left_w, right_w=right_w, dy=dy)
    return out


def _drg_attachments(drg: dict, view=None) -> list:
    """The attachments this view draws as boxes; empty when the level hides them (6.4).

    ``_drg_style_for`` deliberately calls this WITHOUT a view: the icon-or-box
    choice is about how many attachments the DRG has, not about how many this
    view happens to draw.
    """
    if view is not None and not ov.draws(view, "drg_attachments"):
        return []
    return [a for a in (drg.get("attachments") or []) if attachment_type(a) != "loopback"]


def _drg_style_for(drg: dict, requested: str) -> str:
    return choose_drg_style(requested, len(_drg_attachments(drg)))


def _att_box_text(att: dict) -> str:
    """Box text of one attachment: zero-width break hints only when a word cannot fit.

    A parser-style display name is one unbreakable word (underscores are no
    break opportunity), so without hints it renders as a single line straight
    across the DRG glyph and the VCN border. Labels whose words already fit the
    box are left exactly as the model spells them.
    """
    text = attachment_label(att)
    max_chars = max(1, int((ATT_W - 2 * ATT_TEXT_PAD) / (ATT_FONT_SIZE * CHAR_W_RATIO)))
    if any(len(word) > max_chars for line in text.split("\n") for word in line.split()):
        return wrap_hints(text)
    return text


def _att_box_h(text: str) -> int:
    """Height an attachment box needs for its text (ATT_H when it fits in two lines)."""
    lines = label_lines(text, ATT_W - 2 * ATT_TEXT_PAD, ATT_FONT_SIZE)
    return max(ATT_H, lines * LABEL_LINE_H + 2 * ATT_TEXT_PAD)


def _att_block(atts: list) -> tuple:
    """(heights, block height) of a stack of attachment boxes, ATT_VGAP apart."""
    heights = [_att_box_h(_att_box_text(a)) for a in atts]
    return heights, (sum(heights) + ATT_VGAP * (len(heights) - 1) if heights else 0)


def _drg_cluster_geometry(drg: dict, style: str, view=None) -> dict:
    """Sizes of one DRG cluster: icon slot + attachment boxes (right = VCNs, left = on-prem / RPC)."""
    atts = _drg_attachments(drg, view)
    right = [a for a in atts if attachment_type(a) == "vcn"]
    left = [a for a in atts if attachment_type(a) != "vcn"]
    # A bare side still carries the 105 px caption, 15 px wider than the 75 px
    # slot on each side; an attachment block absorbs it, the box style pads with
    # PAD already (spec A23).
    caption_pad = 0 if style == "box" else (LABEL_W - ICON_W) // 2
    left_w = ATT_W + ATT_GAP if left else caption_pad
    right_w = ATT_W + ATT_GAP if right else caption_pad
    left_h, left_block = _att_block(left)
    right_h, right_block = _att_block(right)
    # B09: the route-table badge strip hangs under the DRG caption, so the icon
    # side of the cluster is that much taller and the attachment stacks stay
    # centred on the same axis.
    rt = drg_route_tables(drg) if ov.draws(view or _DEFAULT_VIEW, "drg_route_table") else []
    rt_h = (DRG_RT_GAP + BADGE_SIZE) if rt else 0
    body_h = max(ICON_FOOTPRINT_H + rt_h, left_block, right_block)
    inner_w = left_w + ICON_W + right_w
    cluster_h = body_h
    if style == "box":
        inner_w += 2 * PAD
        cluster_h += ROW1_Y + PAD
        if rt:
            # the glyph is centred on body_h, so its slot starts below ROW1_Y;
            # the badge strip under its caption must still fit inside the box.
            # cluster_h is also what centres the whole column, so it has to be
            # right here rather than grown by fit_to_children afterwards.
            slot_y = int(round(ROW1_Y + body_h / 2 - GW_STRADDLE))
            cluster_h = max(cluster_h, slot_y + ICON_FOOTPRINT_H + rt_h + PAD)
    return {"left": left, "right": right, "left_w": left_w, "inner_w": inner_w,
            "body_h": body_h, "cluster_h": cluster_h, "rt": rt,
            "heights": {"left": left_h, "right": right_h},
            "blocks": {"left": left_block, "right": right_block}}


def _hub_gutter(drgs, edge_font: float) -> int:
    """Gap between the on-premises panel and the DRG column.

    Spec section 2 (A-Team `topo1-2`, deck slides 21-22): the Site-to-Site VPN /
    FastConnect / Remote Peering label sits on the line next to the on-premises
    item, so the gutter has to hold the widest of those labels - otherwise the
    router has nowhere to put the text and lands it on the attachment box.
    """
    widest = max((edge_label_extent(attachment_link_label(att), edge_font)[0]
                  for drg in drgs for att in _drg_attachments(drg)
                  if attachment_type(att) != "vcn" and attachment_link_label(att)), default=0.0)
    if not widest:
        return HUB_GAP
    need = int(math.ceil((widest + 2 * HUB_ATT_LABEL_PAD) / 10.0) * 10)
    return max(HUB_GAP, need)


def _drg_column_width(drgs, requested: str, view=None) -> int:
    return max(_drg_cluster_geometry(drg, _drg_style_for(drg, requested), view)["inner_w"]
               for drg in drgs)


def _drg_display_name(drg: dict, index: int) -> str:
    """Name of a DRG for its box title and its ``drg:<name>`` alias.

    The first line of the canonical ``"DRG\\n<name>"`` label is the bare word
    "DRG", which is neither a name nor unique (two unnamed DRGs collided on the
    cell key ``drg:DRG``). Fall back to the second label line, the address and
    finally the position.
    """
    name = str(drg.get("name") or "").strip()
    if name:
        return name
    lines = [ln.strip() for ln in str(drg.get("label") or "").split("\n") if ln.strip()]
    if lines and lines[0].upper() != "DRG":
        return lines[0]
    if len(lines) > 1:
        return lines[1]
    return str(drg.get("address") or "").strip() or f"drg-{index + 1}"


def _drg_route_table_badges(d: DrawioBuilder, parent, did, name: str, refs: list,
                            slot_x, slot_y, key: str, reg, warnings: list, view=None) -> list:
    """B09 / decision 8: up to DRG_RT_MAX route-table glyphs as one strip under the DRG caption.

    Oracle creates two default DRG route tables - one for VCN attachments and
    one for every other attachment (managingDRGs.htm) - and a hub-and-spoke
    diagram routinely shows both. A third is dropped with a warning and named
    in the first badge's ``dropped_route_tables`` metadata (spec 6.6), so the
    loss is still visible in the .drawio long after the stderr line is gone.
    """
    if not refs:
        return []
    drawn = refs[:DRG_RT_MAX]
    dropped = [r["name"] for r in refs[DRG_RT_MAX:]]
    if dropped:
        message = (f"WARNING: DRG {name!r} has {len(refs)} route tables; "
                   f"only the first {DRG_RT_MAX} are drawn")
        if message not in warnings:
            warnings.append(message)
            print(message, file=sys.stderr)
    strip_w = len(drawn) * BADGE_SIZE + (len(drawn) - 1) * BADGE_GAP
    cx0 = slot_x + ICON_W / 2 - strip_w / 2 + BADGE_SIZE / 2
    cy = slot_y + ICON_FOOTPRINT_H + DRG_RT_GAP + BADGE_SIZE / 2
    ids = []
    for i, ref in enumerate(drawn):
        meta = {"drg_route_table": ref["name"]}
        if i == 0 and dropped:
            meta["dropped_route_tables"] = ", ".join(dropped)
        bid = d.add_badge("route_table", cx0 + i * (BADGE_SIZE + BADGE_GAP), cy, parent=parent,
                          host=did, key=f"{key}-rt" if i == 0 else f"{key}-rt{i + 1}",
                          tooltip=_badge_tooltip(
                              "DRG route table", [ref],
                              (view or _DEFAULT_VIEW).get("label_mode") == "detailed"),
                          metadata=meta)
        _register_badge(reg, [ref], bid)
        reg.badge_kinds.add("drg_route_table")
        reg.layer_cells.setdefault("routes", []).append(bid)
        ids.append(bid)
    return ids


def _layout_drg_column(d: DrawioBuilder, region_id, drgs, col_x, stack_y, stack_h, requested, reg,
                       style_out, warnings=None, view=None) -> list:
    """DRG icon(s) with their attachment boxes at region level, centred on the VCN stack.

    Returns ``(pending, rt_bottom)``: the pending attachment connectors
    ({"source", "vcn", "target", "label", "key"}) and the bottom edge, in the
    region's own coordinates, of the lowest route-table badge strip (0.0 when
    no DRG declares one). ``fit_to_children`` ignores badges on purpose, so the
    caller has to floor the region under the strip itself.
    """
    view = view or _DEFAULT_VIEW
    boxes_on = ov.draws(view, "drg_attachments")
    clusters = [(drg, _drg_style_for(drg, requested)) for drg in drgs]
    geoms = [_drg_cluster_geometry(drg, style, view) for drg, style in clusters]
    total_h = sum(g["cluster_h"] for g in geoms) + DRG_CLUSTER_GAP * (len(geoms) - 1)
    y = max(stack_y, int(round((stack_y + (stack_h - total_h) / 2) / 10.0) * 10))
    pending = []
    rt_bottom = 0.0
    for idx, ((drg, style), g) in enumerate(zip(clusters, geoms)):
        name = _drg_display_name(drg, idx)
        addr = str(drg.get("address") or f"drg:{name}")
        label = drg.get("label") or f"DRG\n{name}"
        if style == "box":
            gid = d.add_group(f"DRG: {name}", col_x, y, g["inner_w"], g["cluster_h"], parent=region_id,
                              group_type="drg", key=f"drgbox:{addr}")
            parent, x0, y0 = gid, PAD, ROW1_Y
        else:
            parent, x0, y0 = region_id, col_x, y
        cy = y0 + g["body_h"] / 2
        slot_x = x0 + g["left_w"]
        slot_y = int(round(cy - GW_STRADDLE))
        spec = {"label": label, "icon": drg.get("icon") or "drg", "key": addr}
        for k in ("metadata", "tooltip"):
            if drg.get(k):
                spec[k] = drg[k]
        (did,), _ = d.place_icons(parent, [spec], cols=1, x0=slot_x, y0=slot_y)
        reg.add_item({"address": addr, "label": label}, did)
        reg.containers[f"drg:{name}"] = did
        _drg_route_table_badges(d, parent, did, name, g["rt"], slot_x, slot_y, addr, reg,
                                warnings if warnings is not None else [], view=view)
        if g["rt"]:
            # slot_y is relative to the box group in box style, to the region otherwise
            rt_bottom = max(rt_bottom, (y if style == "box" else 0) + slot_y
                            + ICON_FOOTPRINT_H + DRG_RT_GAP + BADGE_SIZE)
        if not boxes_on:
            # 6.4: the executive level draws no attachment box; the DRG glyph
            # itself connects straight to the VCN border (the vcn_with_drg
            # presentation the classifier already knows). The attachment is
            # registered exactly as the box branch registers it - by address
            # AND by caption, both onto the DRG glyph - so a model edge that
            # names it either way keeps working at every level.
            for att in _drg_attachments(drg):
                akey = str(att["address"]) if att.get("address") else None
                reg.add_item({"address": att.get("address"),
                              "label": attachment_label(att)}, did)
                is_vcn = attachment_type(att) == "vcn"
                pending.append({"source": did,
                                "vcn": att.get("vcn") if is_vcn else None,
                                "target": att.get("target") if not is_vcn else None,
                                "label": attachment_link_label(att),
                                "key": f"{akey}-edge" if akey else None})
        for side, atts in (("right", g["right"]), ("left", g["left"])):
            if not atts:
                continue
            bx = slot_x + ICON_W + ATT_GAP if side == "right" else x0
            by = int(round(cy - g["blocks"][side] / 2))
            for i, att in enumerate(atts):
                akey = str(att["address"]) if att.get("address") else None
                text = _att_box_text(att)
                box_h = g["heights"][side][i]
                bid = d.add_box(text, bx, by, ATT_W, box_h, parent=parent, key=akey,
                                metadata=att.get("metadata"), tooltip=att.get("tooltip"))
                by += box_h + ATT_VGAP
                reg.add_item({"address": att.get("address"), "label": attachment_label(att)}, bid)
                pending.append({"source": bid,
                                "vcn": att.get("vcn") if side == "right" else None,
                                "target": att.get("target") if side == "left" else None,
                                "label": attachment_link_label(att),
                                "key": f"{akey}-edge" if akey else None})
        if style == "box":
            # badges are skipped by fit_to_children, so the strip's height has to
            # be reserved explicitly - it hangs DRG_RT_GAP + BADGE_SIZE below the
            # DRG icon's own footprint, whose top is slot_y
            rt_h = (DRG_RT_GAP + BADGE_SIZE) if g["rt"] else 0
            need_h = slot_y + ICON_FOOTPRINT_H + rt_h + PAD
            _w, box_h = d.fit_to_children(gid, pad=PAD, min_h=max(g["cluster_h"], need_h))
            g["cluster_h"] = max(g["cluster_h"], box_h)   # keep the stack pitch honest
        style_out[addr] = style
        y += g["cluster_h"] + DRG_CLUSTER_GAP
    return pending, rt_bottom


def _layout_compartments(d: DrawioBuilder, rid, model: dict, member_cells: dict, reg) -> dict:
    """B04: wrap each compartment's VCN cells - and their border gateways - in a container.

    Runs after the VCN columns and their gateways are placed and before
    ``fit_to_children(region)``: each container is fitted to the cells it
    claims and they are re-parented into it, innermost first. The DRG column,
    the on-premises panel and the OSN band stay region children, because the
    DRG column is shared by VCNs that may sit in different compartments
    (spec 6.3).
    """
    tree = compartment_tree(model)
    ids = {}

    def place(node, parent_id):
        own = [cid for cid in (place(child, parent_id) for child in node["children"]) if cid]
        for vname in node["vcns"]:
            own.extend(member_cells.get(vname, []))
        if not own:
            return None
        x0, y0, x1, y1 = _union_box(d, own)
        gid = d.add_group(node["name"], x0 - CMP_PAD, y0 - CMP_TITLE_H,
                          (x1 - x0) + 2 * CMP_PAD, (y1 - y0) + CMP_TITLE_H + CMP_PAD,
                          parent=parent_id, group_type="compartment",
                          key=f"compartment:{node['name']}")
        for cid in own:
            d.reparent(cid, gid)
        reg.containers[f"compartment:{node['name']}"] = gid
        ids[node["name"]] = gid
        return gid

    roots = [cid for cid in (place(n, rid) for n in tree) if cid]
    if roots and model.get("tenancy_name"):
        x0, y0, x1, y1 = _union_box(d, roots)
        tid = d.add_group(f"Tenancy: {model['tenancy_name']} (Root Compartment)",
                          x0 - TEN_PAD, y0 - TEN_TITLE_H,
                          (x1 - x0) + 2 * TEN_PAD, (y1 - y0) + TEN_TITLE_H + TEN_PAD,
                          parent=rid, group_type="tenancy", key="tenancy")
        for cid in roots:
            d.reparent(cid, tid)
        reg.containers["tenancy"] = tid
        ids["__tenancy__"] = tid
    return ids


def _planned_layers(view: dict, reg: _Registry, model: dict) -> list:
    """The enabled layers that will actually hold a cell, in VIEW_LAYERS order (6.2 step 4)."""
    enabled = list(view.get("layers") or ())
    if not enabled:
        return []
    have_edges = set()
    if view.get("show_edges", True):
        for e in model.get("edges") or []:
            layer = _edge_layer(e.get("kind"))
            if layer:
                have_edges.add(layer)
    planned = []
    for name in ov.VIEW_LAYERS:
        if name not in enabled:
            continue
        if name in LAYER_BADGE_KINDS:
            if any(k in reg.badge_kinds for k in LAYER_BADGE_KINDS[name]):
                planned.append(name)
        elif name == "iam":
            if reg.layer_cells.get("iam"):
                planned.append(name)
        elif name in have_edges:
            planned.append(name)
    return planned


def _create_layers(d: DrawioBuilder, view: dict, planned: list) -> dict:
    """Name the base layer and add one layer per planned name; returns {name: cell id}.

    The order is the z-order: every view layer renders above the base layer,
    which is what the badges and the connectors need (6.2 step 2).
    """
    if not planned:
        return {}
    d.set_base_layer_name(view.get("base_layer_name") or ov.BASE_LAYER_NAME)
    hidden = set(view.get("hidden_layers") or ())
    return {name: d.add_layer(ov.LAYER_TITLES[name], visible=name not in hidden,
                              key=f"layer-{name}")
            for name in planned}


def _apply_layers(d: DrawioBuilder, layers: dict, view: dict, reg: _Registry) -> dict:
    """V1: move the layer-eligible cells onto their layer. Not one pixel moves.

    ``reparent()`` keeps a cell's absolute position, and the edges were given
    their layer as ``parent`` when they were added (an edge's route is computed
    from absolute boxes, so the parent only selects the frame its waypoints are
    stored in). Runs after ``fit_page()``.
    """
    counts = {}
    for name, lid in layers.items():
        moved = 0
        for cid in reg.layer_cells.get(name, []):
            if cid in d._cells:
                d.reparent(cid, lid)
                moved += 1
        counts[name] = moved
    for cid, e in d._cells.items():
        if e["kind"] == "edge" and e["parent"] in layers.values():
            for name, lid in layers.items():
                if e["parent"] == lid:
                    counts[name] = counts.get(name, 0) + 1
    hidden = [n for n in layers if n in set(view.get("hidden_layers") or ())]
    return {"enabled": list(layers), "hidden": hidden, "cells": counts}


def _resolve_attachment_target(reg: _Registry, pe: dict):
    """Cell the attachment box connects to: its VCN's border, a hub item, or nothing."""
    if pe.get("vcn") is not None:
        for ref in (f"vcn:{pe['vcn']}", str(pe["vcn"])):
            try:
                return reg.resolve(ref)
            except ValueError:
                continue
        raise ValueError(f"DRG attachment {pe['source']!r}: VCN {pe['vcn']!r} is not in the model")
    if pe.get("target"):
        return reg.resolve(pe["target"])
    return None


# B07: badge legend rows, in the order the badges are drawn. The DRG route
# table reuses the route-table glyph with its own text (Task 9 fills the kind).
LEGEND_BADGE_ROWS = (("route_table", "route_table", "Route table"),
                     ("security_list", "security_list", "Security list"),
                     ("nsg", "nsg", "Network security group"),
                     ("drg_route_table", "route_table", "DRG route table"))


def _legend_entries(d: DrawioBuilder, reg: _Registry) -> list:
    """The eight default rows, with the attachment row named after the active form (L3),
    plus one badge row per badge kind the diagram actually drew."""
    attachment = ("Attachment / association (structural)" if d.attachment_style == "dotted"
                  else "Attachment (structural)")
    rows = [("edge", "data", "Data flow (protocol / port)"),
            ("edge", "control", "Management / administrative traffic"),
            ("edge", "association", "Association / dependency"),
            ("edge", "attachment", attachment),
            ("group", "region", "Region / on-premises"),
            ("group", "vcn", "VCN"),
            ("group", "subnet", "Subnet"),
            ("group", "oracle_services_network", "Oracle Services Network")]
    rows.extend(("badge", icon, text) for kind, icon, text in LEGEND_BADGE_ROWS
                if kind in reg.badge_kinds)
    return rows


def build_diagram(model: dict, style_profile="default", legend=False, logo=None,
                  page_name=None, title=True, max_row_w=MAX_ROW_W, drg_style=None,
                  locations=None, gateway_edge=None, subnet_label=None, attachment_style=None,
                  show_compartments=None, label_mode=None, label_fields=None,
                  label_tag_keys=None, layers=None, hidden_layers=None,
                  detail=None, show_edges=None, filter_spec=None, mode=None,
                  discovery=None, annotate_discovery=None) -> DrawioBuilder:
    """Lay out a normalized model and return the (unwritten) DrawioBuilder.

    Schema-1 models are migrated first (DRG hub items / drg gateways -> drgs[]);
    migration warnings go to stderr and to ``builder.layout_info["warnings"]``.
    ``drg_style`` (auto | icon | box) overrides ``model["drg_style"]``.
    """
    model, warnings = migrate_legacy_model(model)
    for w in warnings:
        print(w, file=sys.stderr)
    # 8, phase 1: migrate -> resolve the view -> filter and prune -> classify.
    # The view is resolved from the pre-filter model (a filter is part of the
    # view, not of the infrastructure) and then reused, so the Internet box and
    # the topology are both derived from what actually survived.
    view = ov.resolve_view(model, label_mode=label_mode, label_fields=label_fields,
                           label_tag_keys=label_tag_keys, layers=layers,
                           hidden_layers=hidden_layers, detail=detail, show_edges=show_edges,
                           subnet_label=subnet_label, show_compartments=show_compartments,
                           filter=filter_spec, mode=mode, discovery=discovery,
                           annotate_discovery=annotate_discovery)
    for note in view["notes"]:
        print(note, file=sys.stderr)
    model, filter_report = ov.filter_model(model, view["filter"], mode=view["mode"],
                                           discovery=view["discovery"])
    for w in filter_report["warnings"]:
        warnings.append(w)
        print(w, file=sys.stderr)
    if not model.get("vcns") and not model.get("hub") and not model.get("drgs"):
        raise ValueError("model needs at least one VCN (model['vcns']), a hub or a DRG")
    requested = str(drg_style or model.get("drg_style") or "auto").lower()
    choose_drg_style(requested, 0)                     # validates the value early
    topo = classify_topology(model)
    subject = model.get("subject") or (model["vcns"][0].get("name") if model.get("vcns") else "Architecture")
    ctx = _view_ctx(model, locations=locations, gateway_edge=gateway_edge, subnet_label=subnet_label,
                    attachment_style=attachment_style, show_compartments=show_compartments,
                    view=view)
    # 6.4: a level that asks for a legend gets one; "network" leaves the choice
    # to the caller (its table entry is None).
    if view["legend"] is not None:
        legend = bool(view["legend"])
    d = DrawioBuilder(page_name=page_name or f"{subject} Architecture", style_profile=style_profile,
                      attachment_style=ctx["attachment_style"],
                      max_label_lines=view["line_budget"])
    edge_mix = {}
    for e in model.get("edges") or []:
        kind = str(e.get("discovery") or "association")
        edge_mix[kind] = edge_mix.get(kind, 0) + 1
    d.layout_info = {"topology": topo, "warnings": list(warnings), "drg_style": {},
                     "locations": ctx["locations"], "view": view,
                     "layers": {"enabled": [], "hidden": [], "cells": {}},
                     "filter": {k: filter_report[k] for k in
                                ("include", "exclude", "items_kept", "items_dropped",
                                 "edges_dropped", "containers_dropped", "groups_dropped")},
                     "pruned": {"items": filter_report["pruned_items"],
                                "services": filter_report["pruned_services"]},
                     "edges": edge_mix}
    reg = _Registry()

    if title:
        d.add_title(f"{subject} - Architecture", region_label=model.get("region_label"),
                    region=model.get("region"), compartment=model.get("compartment"),
                    tenancy=model.get("tenancy_name"), x=TITLE_BOX[0], y=TITLE_BOX[1],
                    w=TITLE_BOX[2], h=TITLE_BOX[3], logo=logo, page_w=None)

    region_label = model.get("region") or model.get("region_label") or "Region"
    rid = d.add_group(region_label, REGION_XY[0], REGION_XY[1], 800, 600, group_type="region",
                      key="region")
    reg.containers["region"] = rid

    hub = model.get("hub")
    drgs = list(model.get("drgs") or [])
    vcns = [dict(v) for v in (model.get("vcns") or [])]
    osn_items = []
    for vcn in vcns:
        regional, local = _split_services(vcn.get("services"))
        osn_items.extend(regional)
        vcn["services"] = local
    regional, top_services = _split_services(model.get("services"))
    osn_items.extend(regional)
    if top_services and len(vcns) == 1:
        vcns[0]["services"] = list(vcns[0].get("services") or []) + top_services
        top_services = []

    # Column order inside the region: [nested on-premises panel] | DRG column | VCN columns |
    # OCI Services | Oracle Services Network. Under the Location Canvas (L1) the on-premises
    # panel is not a region child at all, so the region starts at PAD.
    nested_hub = hub if ctx["locations"] == "nested" else None
    x = HUB_X + HUB_W + HUB_GAP if nested_hub else PAD
    drg_col_x = x
    if drgs:
        if nested_hub:
            drg_col_x = max(drg_col_x, HUB_X + HUB_W + _hub_gutter(drgs, d.profile["edge_font"]))
        x = drg_col_x + _drg_column_width(drgs, requested, view) + DRG_GAP
    stack_left = x              # first VCN column; the OSN band never runs left of it

    # B04 / spec 6.3: regroup the columns by compartment before anything is placed,
    # so each compartment's members are contiguous and the compartment-less VCNs
    # trail the boxed ones. Column indices (LPG peer sides, the rightmost-column
    # rule of G4) are derived from the regrouped list.
    cmp_tree = compartment_tree(model) if ctx["show_compartments"] else []
    if cmp_tree:
        vcns = _compartment_column_order(cmp_tree, vcns)

    order = _vcn_order(vcns)
    all_sides = [_gateway_sides(v, i, order, ctx) for i, v in enumerate(vcns)]
    # A top-border gateway hangs its caption above the VCN: the stack starts
    # lower so the caption stays inside the region's padding.
    vcn_y = VCN_Y_TOP_GW if any(s["top"] for s in all_sides) else VCN_Y
    # B04: every compartment level adds a title band above and a padding left of
    # the stack; the containers are drawn after the columns, so the room has to
    # be reserved now.
    cmp_depth = _compartment_depth(cmp_tree)
    cmp_chains = [_compartment_chain(cmp_tree, v.get("name") or "") for v in vcns]
    tenancy_wrap = bool(cmp_tree) and bool(model.get("tenancy_name"))
    if cmp_depth:
        vcn_y += cmp_depth * CMP_TITLE_H + (TEN_TITLE_H + TEN_PAD if tenancy_wrap else 0)
        x += cmp_depth * CMP_PAD + (TEN_PAD if tenancy_wrap else 0)
    vcn_boxes = []
    member_cells = {}           # VCN name -> the cells its compartment claims
    edge_gateways = []          # (vcn index, side, gateway dict, icon id)
    for i, vcn in enumerate(vcns):
        sides = all_sides[i]
        # Reserve the room the straddling gateways need: one bottom slot every GW_PITCH
        # from vx + PAD (the trailing PAD also covers the last caption's 15 px overhang),
        # and one side slot every SIDE_GW_PITCH from SIDE_GW_Y0 / LEFT_GW_Y0.
        need_w = max(
            VCN_MIN_W,
            (PAD + (len(sides["bottom"]) - 1) * GW_PITCH + ICON_W + PAD) if sides["bottom"] else 0,
        )
        # A top-border slot is measured from the VCN's right edge, so the room
        # reserved must also clear the VCN's own title band on the left.
        need_w = max(need_w, _top_gw_min_w(vcn, d, len(sides["top"]), ctx["subnet_label"]))
        need_h = max(
            200,
            (SIDE_GW_Y0 + (len(sides["right"]) - 1) * SIDE_GW_PITCH + ICON_FOOTPRINT_H + PAD) if sides["right"] else 0,
            (LEFT_GW_Y0 + (len(sides["left"]) - 1) * SIDE_GW_PITCH + ICON_FOOTPRINT_H + PAD) if sides["left"] else 0,
        )
        vid, w, h = _layout_vcn(d, rid, vcn, x, vcn_y, reg, max_row_w=max_row_w,
                                inset_left=SIDE_INSET if sides["left"] else 0,
                                right_pad=VCN_SIDE_PAD if sides["right"] else PAD,
                                bottom_pad=VCN_BOTTOM_PAD_GW if sides["bottom"] else VCN_BOTTOM_PAD,
                                top_pad=VCN_TOP_PAD_GW if sides["top"] else PAD,
                                min_h=need_h, min_w=need_w, label_mode=ctx["subnet_label"],
                                view=view)
        vcn_boxes.append((vid, x, vcn_y, w, h))
        claimed = [vid]
        for side in ("bottom", "top", "right", "left"):
            for slot, g in enumerate(sides[side]):
                gid = _place_edge_gateway(d, rid, (x, vcn_y, w, h), side, slot, g, reg,
                                          caption_above=(side == "top"), view=view)
                edge_gateways.append((i, side, g, gid))
                claimed.append(gid)
        member_cells[vcn.get("name") or ""] = claimed
        # The gap must clear the captions of both facing borders: this column's
        # right-side gateways and the next column's left-side ones (spec A17),
        # plus the compartment borders that close and open between the columns.
        next_left = all_sides[i + 1]["left"] if i + 1 < len(all_sides) else []
        x += w + (VCN_COLUMN_GAP_GW if (sides["right"] or next_left) else VCN_COLUMN_GAP)
        if cmp_depth and i + 1 < len(vcns):
            x += _compartment_gap(cmp_chains[i], cmp_chains[i + 1])
            # leaving the boxed group for the trailing unboxed one also closes
            # the tenancy wrapper, which pads the compartment row by TEN_PAD
            if tenancy_wrap and bool(cmp_chains[i]) != bool(cmp_chains[i + 1]):
                x += TEN_PAD

    ref_h = max((b[4] for b in vcn_boxes), default=400)
    # B04: the compartment / tenancy borders close to the right of the last VCN
    # column and below the stack; without this the OSN band and the region-level
    # OCI Services panel would be drawn straight over them.
    cmp_edge = (cmp_depth * CMP_PAD + (TEN_PAD if tenancy_wrap else 0)) if cmp_depth else 0
    x += cmp_edge
    if top_services:
        rows_n, cols = _grid(len(top_services), 2)
        prov_h = ROW1_Y + (rows_n - 1) * ROW_H + ICON_FOOTPRINT_H + SUBNET_BOTTOM_PAD
        pid = d.add_group("OCI Services", x, vcn_y, cols * COL_W + SUBNET_EXTRA_W, prov_h,
                          parent=rid, group_type="services", key="services")
        reg.containers["services"] = pid
        _icon_items(d, pid, top_services, cols, reg=reg, view=view)
        # spec 7.2: height-matched to the tallest VCN column, like the OSN panel
        pw, _ = d.fit_to_children(pid, pad=PAD, min_h=max(prov_h, ref_h))
        x += pw + VCN_COLUMN_GAP

    pairs = {(str(e.get("source")), str(e.get("target"))) for e in (model.get("edges") or [])}
    if nested_hub:
        _layout_hub(d, rid, nested_hub, vcn_y, ref_h, reg, explicit_pairs=pairs, view=view)

    pending = []
    drg_rt_bottom = 0.0
    if drgs:
        pending, drg_rt_bottom = _layout_drg_column(
            d, rid, drgs, drg_col_x, vcn_y, ref_h, requested, reg,
            d.layout_info["drg_style"], d.layout_info["warnings"], view=view)

    # The Oracle Services Network panel is emitted after every other region child:
    # under the Location Canvas it is a band that has to clear all of them.
    osn_id = None
    if osn_items:
        if ctx["locations"] == "outside":
            # G5: a band below the VCN stack, so the IGW / NAT connectors to the
            # Internet box never have to cross it. The Service Gateway is on the
            # bottom border facing it (_gateway_side). The band spans the stack and
            # nothing else: it starts at the first VCN column, so it never runs under
            # the DRG column, and its top clears the deepest region child already
            # placed above it - a VCN with its bottom-border gateway captions, a DRG
            # cluster taller than the stack, or a region-level "OCI Services" panel.
            stack_right = (x - VCN_COLUMN_GAP) if (vcn_boxes or top_services) else (stack_left + VCN_MIN_W)
            band_w = max(VCN_MIN_W, stack_right - stack_left)
            band_cols = max(1, min(len(osn_items), int((band_w - 2 * PAD) // COL_W) or 1))
            band_y = int(max(vcn_y + ref_h, _children_bottom(d, rid))
                         + OSN_BAND_GAP + cmp_edge)
            osn_id, _, _ = _layout_osn(d, rid, osn_items, stack_left, band_y, 0, reg,
                                       min_w=band_w, cols=band_cols, view=view)
        else:
            # the VCN loop already added the trailing column gap: subtracting VCN_COLUMN_GAP
            # leaves last_right + OSN_GAP, plus the extra VCN_COLUMN_GAP_GW - VCN_COLUMN_GAP
            # when the last column has right-border gateways whose captions need the room.
            osn_x = (x - VCN_COLUMN_GAP + OSN_GAP) if (vcn_boxes or top_services) else x
            osn_id, _, _ = _layout_osn(d, rid, osn_items, osn_x, vcn_y, ref_h, reg, view=view)
        # spec section 12: a schema-1 edge addressed to "services:<vcn>" must keep resolving
        # when the split left that VCN without a services panel of its own
        for _vcn in vcns:
            _name = str(_vcn.get("name") or "")
            if _name and not (_vcn.get("services") or []):
                reg.containers.setdefault("services:%s" % _name, osn_id)

    if cmp_depth:
        d.layout_info["compartments"] = _layout_compartments(d, rid, model, member_cells, reg)

    # B09: the DRG route-table strip is a badge, and fit_to_children ignores
    # badges, so a DRG column that is the region's tallest child would leave the
    # strip hanging across the region border. Floor the region under it.
    d.fit_to_children(rid, pad=PAD,
                      min_h=(drg_rt_bottom + PAD) if drg_rt_bottom else None)
    canvas = _layout_locations(d, rid, ctx, hub if not nested_hub else None, drgs, vcn_y, ref_h,
                               reg, explicit_pairs=pairs, view=view)
    d.layout_info["canvas"] = canvas

    # 6.2 steps 1-2: the layers exist before the first edge that belongs on one,
    # because an edge takes its layer as ``parent`` at add_edge time. The badges
    # are moved in the post-pass after fit_page().
    layer_ids = _create_layers(d, view, _planned_layers(view, reg, model))

    if osn_id is not None:
        for _i, side, g, gid in edge_gateways:
            if _is_sgw(g):     # G5: the SGW faces the OSN on whichever border it took
                d.add_edge(gid, osn_id, "", kind="attachment",
                           key=f"{g['address']}-osn" if g.get("address") else None)

    internet_id = canvas.get("internet")
    if internet_id:
        # Every Internet Gateway is tied to the Internet box exactly as the
        # Service Gateway is tied to the OSN: an attachment connector, no
        # arrowhead, no label. Nothing is drawn when there is no Internet box
        # (the nested canvas, or a model without an IGW).
        for _i, _side, g, gid in edge_gateways:
            if _gateway_type(g) == "igw":
                d.add_edge(gid, internet_id, "", kind="attachment",
                           key=f"{g['address']}-internet" if g.get("address") else None)

    if model.get("notes"):
        d.add_text(escape_label(model["notes"]), TITLE_BOX[0] + TITLE_BOX[2] + 20, TITLE_BOX[1],
                   400, TITLE_BOX[3], font_size=10, raw_html=True)

    for pe in pending:
        target = _resolve_attachment_target(reg, pe)
        if target is not None:
            # ATTACHMENT_LINK_LABELS is real text ("Site-to-Site VPN", "FastConnect",
            # "Remote Peering"), so it goes through the same 6.3 edge-label gate.
            d.add_edge(pe["source"], target, _edge_label(pe["label"], view), kind="attachment",
                       key=pe["key"])

    for e in (model.get("edges") or []) if view["show_edges"] else []:
        spec = EDGE_KINDS.get(str(e.get("kind") or "data").lower(), EDGE_KINDS["data"])
        kwargs = dict(color=e.get("color", spec["color"]), key=e.get("address"))
        layer_name = _edge_layer(e.get("kind"))
        if layer_name in layer_ids:
            kwargs["parent"] = layer_ids[layer_name]
        if view["annotate_discovery"]:
            # V8: never a style. The provenance goes in the tooltip only, so the
            # four line styles keep the four meanings the guidelines give them.
            kwargs["tooltip"] = f"Discovered by: {e.get('discovery') or 'association'}"
        if "dashed" in e:
            kwargs["dashed"] = e["dashed"]            # explicit override keeps the profile look
        else:
            kwargs["kind"] = spec["kind"]
        d.add_edge(reg.resolve(e["source"]), reg.resolve(e["target"]),
                   _edge_label(e.get("label", ""), view), **kwargs)

    if legend:
        _, _, _, bottom = d.content_bbox()
        d.add_legend(REGION_XY[0], bottom + GAP, entries=_legend_entries(d, reg))

    d.fit_page(margin=PAD)
    # 6.2 steps 3-4 (V1): the layer pass runs last and only changes parents.
    d.layout_info["layers"] = _apply_layers(d, layer_ids, view, reg)
    return d


def write_diagram(model: dict, out_path, strict=False, render_fmt=None, **opts) -> Path:
    """Build, validate (raising on errors) and write the diagram."""
    d = build_diagram(model, **opts)
    problems = d.validate(strict=strict)
    errors = [p for p in problems if not is_warning(p)]
    for p in problems:
        print(p, file=sys.stderr)
    if errors:
        raise SystemExit(f"{len(errors)} layout error(s); diagram not written")
    out = d.write(out_path)
    if render_fmt:
        try:
            png = render(out, fmt=render_fmt)
            print(f"Rendered {png}" if png else "draw.io desktop not found; render skipped", file=sys.stderr)
        except RuntimeError as exc:
            print(f"WARNING: render failed: {exc}", file=sys.stderr)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Lay out a normalized OCI model as a .drawio diagram")
    ap.add_argument("model", help="model JSON file")
    ap.add_argument("-o", "--out", default=None, help="output .drawio (default: <subject>_Architecture.drawio)")
    ap.add_argument("--profile", default="default", choices=("default", "official", "v1.0"))
    ap.add_argument("--legend", action="store_true")
    ap.add_argument("--logo", default=None)
    ap.add_argument("--strict", action="store_true", help="estimated edge crossings are errors")
    ap.add_argument("--render", default=None, choices=("png", "svg", "pdf"),
                    help="also export with draw.io desktop when available")
    ap.add_argument("--drg-style", default=None, choices=("auto", "icon", "box"),
                    help="DRG presentation: icon (DRG icon with attachment boxes beside it) or box "
                         "(dashed 'DRG: <name>' group holding them); auto = icon unless a DRG has more "
                         "than 4 attachments (overrides model['drg_style'])")
    ap.add_argument("--locations", default=None, choices=LOCATION_MODES,
                    help="canvas: outside (default; On-Premises / Internet / 3rd Party Cloud as "
                         "page-level siblings of the region) or nested (the v1.3.0 on-premises panel "
                         "inside the region)")
    ap.add_argument("--gateway-edge", default=None, choices=GATEWAY_EDGES,
                    help="which VCN border the Internet-facing gateways take (default auto: the "
                         "border facing the Internet box, else the bottom)")
    ap.add_argument("--subnet-label", default=None, choices=SUBNET_LABEL_MODES,
                    help="subnet / VCN titles: twoline (default; name + Public/Private over the CIDR), "
                         "inline (the v1.3.0 single line) or name (the name and its "
                         "Public/Private token with no CIDR; chosen automatically by the "
                         "executive and application detail levels)")
    ap.add_argument("--attachment-style", default=None, choices=ATTACHMENT_STYLE_MODES,
                    help="attachment connectors: solid (default) or dotted")
    ap.add_argument("--show-compartments", action="store_true", default=None,
                    help="draw each compartment as a container around its VCNs")
    ap.add_argument("--label-mode", default=None, choices=ov.LABEL_MODE_ORDER,
                    help="icon captions: minimal (name only), network (default; name, private IP, "
                         "port / protocol) or detailed (name, private IP, AD / FD, compartment)")
    ap.add_argument("--label-fields", default=None, metavar="F,F",
                    help=f"explicit caption field list, overriding --label-mode; "
                         f"choose from {','.join(ov.LABEL_FIELDS)} (an OCID is never rendered)")
    ap.add_argument("--label-tag-keys", default=None, metavar="K,K",
                    help="which tag keys the 'tags' caption field renders, in this order")
    ap.add_argument("--layers", default=None, metavar="off|auto|L,L",
                    help=f"emit the diagram onto draw.io layers: off (default), auto (every layer "
                         f"with content) or a list from {','.join(ov.VIEW_LAYERS)}; "
                         f"'ips' and 'ports' are rewritten to caption fields")
    ap.add_argument("--hidden-layers", default=None, metavar="L,L",
                    help="layers created with visible=0 (toggle them in draw.io with Cmd/Ctrl+Shift+L)")
    ap.add_argument("--detail", default=None, choices=ov.DETAIL_ORDER,
                    help="level of detail: executive (no badges, no CIDRs, no attachment boxes, no "
                         "connector labels), application, network (default) or engineering")
    ap.add_argument("--no-edges", dest="show_edges", action="store_false", default=None,
                    help="draw no model connectors at all (the inventory view)")
    ap.add_argument("--filter", action="append", default=None, metavar="EXPR",
                    help="keep only what matches: '[!]<dimension>[:<key>]<op><value>[,<value>]' "
                         f"over {','.join(ov.FILTER_DIMENSIONS)}, with <op> '=' (exact) or "
                         "'~' (substring). Repeatable; a leading '!' excludes; expressions AND "
                         "across dimensions and OR within one")
    ap.add_argument("--mode", default=None, choices=ov.MODES,
                    help="all (default here) or participating (only what takes part in the "
                         "architecture)")
    ap.add_argument("--discovery", default=None, metavar="K,K",
                    help=f"keep only edges discovered this way: {','.join(ov.DISCOVERY_KINDS)}")
    ap.add_argument("--annotate-discovery", action="store_true", default=None,
                    help="put each connector's discovery method in its tooltip (never in its style)")
    args = ap.parse_args(argv)
    model = load_model(args.model)
    subject = model.get("subject") or "Architecture"
    out = Path(args.out) if args.out else Path(f"{subject.replace(' ', '_')}_Architecture.drawio")
    write_diagram(model, out, strict=args.strict, render_fmt=args.render,
                  style_profile=args.profile, legend=args.legend, logo=args.logo,
                  drg_style=args.drg_style, locations=args.locations,
                  gateway_edge=args.gateway_edge, subnet_label=args.subnet_label,
                  attachment_style=args.attachment_style, show_compartments=args.show_compartments,
                  label_mode=args.label_mode, label_fields=args.label_fields,
                  label_tag_keys=args.label_tag_keys, layers=args.layers,
                  hidden_layers=args.hidden_layers, detail=args.detail,
                  show_edges=args.show_edges, filter_spec=args.filter, mode=args.mode,
                  discovery=args.discovery, annotate_discovery=args.annotate_discovery)
    return 0


if __name__ == "__main__":
    sys.exit(main())
