#!/usr/bin/env python3
"""Deterministic OCI diagram layout: normalized model dict -> .drawio.

This is the layout recipe the /drawio-architect workflow uses so that every
generated diagram has the same structure as the reference sample:

    Title block (bold subject, italic "Region label (region) - Compartment: X")
    Region (solid, label top-left)
      +-- On-premises panel (left, vertically centred on the VCN stack): CPE, virtual circuit, RPC peer
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
      "hub": {"name": "On-premises",      # on-premises side only: CPE, IPSec, virtual circuit, RPC peer
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
                          [--drg-style auto|icon|box]

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
    BADGE_GAP, BADGE_SIZE, CHAR_W_RATIO, COL_W, COLORS, GAP, ICON_FOOTPRINT_H, ICON_W,
    LABEL_FONT_SIZE, LABEL_LINE_H, PAD, ROW1_Y, ROW_H, DrawioBuilder, edge_label_extent,
    escape_label, label_lines, render, wrap_hints,
)
from oci_topology import (  # noqa: E402
    attachment_label, attachment_link_label, attachment_type, choose_drg_style, classify_topology,
    first_line, is_regional, migrate_legacy_model,
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
SUBNET_BOTTOM_PAD = 28
HUB_X = 15
HUB_W = 180
HUB_GAP = 45
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

OSN_GAP = 45                     # last VCN column -> Oracle Services Network panel
OSN_LABEL = "Oracle Services Network"

DRG_GAP = 45                     # DRG column -> first VCN column
ATT_W = 100                      # attachment box
ATT_H = 44                       # minimum height (a two-line label); grown to fit longer text
ATT_GAP = 15                     # DRG slot -> attachment boxes
ATT_PITCH = 56                   # vertical pitch of stacked ATT_H boxes
ATT_VGAP = ATT_PITCH - ATT_H     # gap between stacked attachment boxes, whatever their height
ATT_FONT_SIZE = LABEL_FONT_SIZE  # BOX_STYLE font size (label_lines / height estimate)
ATT_TEXT_PAD = 4                 # text inset each side of an attachment box
DRG_CLUSTER_GAP = 40             # between stacked DRG clusters

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


def _subnet_label(subnet: dict) -> str:
    name = subnet.get("name", "subnet")
    cidr = subnet.get("cidr")
    label = f"{name} ({cidr})" if cidr else name
    if subnet.get("public") and "public" not in label.lower():
        label += " - public"
    return label


def _vcn_label(vcn: dict) -> str:
    name = vcn.get("name", "vcn")
    cidr = vcn.get("cidr")
    return f"VCN: {name} ({cidr})" if cidr else f"VCN: {name}"


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


def _gateway_side(gw: dict, vcn_index: int, order: dict) -> str:
    """bottom (IGW, NAT, unknown), right (SGW; LPG whose peer is a later column), left (LPG, earlier peer)."""
    gtype = str(gw.get("type") or "").lower()
    icon = str(gw.get("icon") or "")
    if _is_sgw(gw):
        return "right"
    if gtype == "lpg" or (not gtype and icon in LPG_ICONS):
        peer = gw.get("peer")
        peer_idx = order.get(str(peer)) if peer is not None else None
        if peer_idx is None or peer_idx == vcn_index:
            return "bottom"
        return "right" if peer_idx > vcn_index else "left"
    return "bottom"


def _gateway_sides(vcn: dict, vcn_index: int, order: dict) -> dict:
    sides = {"left": [], "right": [], "bottom": []}
    for g in vcn.get("gateways") or []:
        sides[_gateway_side(g, vcn_index, order)].append(g)
    return sides


def _place_edge_gateway(d: DrawioBuilder, region_id, box, side: str, slot: int, gw: dict, reg) -> str:
    """One gateway icon centred on a VCN border; box = (x, y, w, h) of the VCN in region coordinates."""
    vx, vy, vw, vh = box
    if side == "bottom":
        x, y = vx + PAD + slot * GW_PITCH, vy + vh - GW_STRADDLE
    elif side == "right":
        x, y = vx + vw - GW_SIDE_DX, vy + SIDE_GW_Y0 + slot * SIDE_GW_PITCH
    else:
        x, y = vx - GW_SIDE_DX + 1, vy + LEFT_GW_Y0 + slot * SIDE_GW_PITCH
    spec = {"label": gw.get("label", ""), "icon": gw.get("icon", "service_gateway")}
    if gw.get("address"):
        spec["key"] = str(gw["address"])
    for k in ("metadata", "tooltip"):
        if gw.get(k):
            spec[k] = gw[k]
    ids, _ = d.place_icons(region_id, [spec], cols=1, x0=int(x), y0=int(y), label_fill=COLORS["region_fill"])
    reg.add_item(gw, ids[0])
    return ids[0]


def _split_services(items) -> tuple:
    """(regional, vcn-resident) using item['regional'] or the icon-key table."""
    items = list(items or [])
    return [s for s in items if is_regional(s)], [s for s in items if not is_regional(s)]


def _layout_osn(d: DrawioBuilder, region_id, items, x, y, min_h, reg) -> tuple:
    """Region-level Oracle Services Network panel; returns (id, w, h)."""
    rows_n, cols = _grid(len(items), 2)
    prov_w = cols * COL_W + SUBNET_EXTRA_W
    prov_h = ROW1_Y + (rows_n - 1) * ROW_H + ICON_FOOTPRINT_H + SUBNET_BOTTOM_PAD
    pid = d.add_group(OSN_LABEL, x, y, prov_w, prov_h, parent=region_id,
                      group_type="oracle_services_network", key="osn", label_position="left")
    reg.containers["osn"] = pid
    reg.containers.setdefault("services", pid)
    _icon_items(d, pid, items, cols, reg=reg)
    w, h = d.fit_to_children(pid, pad=PAD, min_w=prov_w, min_h=max(prov_h, min_h or 0))
    return pid, w, h


class _Registry:
    """address / reference -> cell id resolution for edges."""

    def __init__(self):
        self.by_address = {}
        self.by_caption = {}
        self.containers = {}

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


def _badge_refs(value) -> list:
    """Normalise ``str | dict | list[str | dict]`` into ``[{"name", "address"}]`` (empty for None)."""
    if value is None or value == "" or value == []:
        return []
    items = value if isinstance(value, (list, tuple)) else [value]
    out = []
    for it in items:
        if isinstance(it, dict):
            name = str(it.get("name") or it.get("label") or it.get("address") or "").strip()
            addr = it.get("address")
        else:
            name, addr = str(it).strip(), None
        if name:
            out.append({"name": name, "address": str(addr) if addr else None})
    return out


def _badge_tooltip(kind: str, refs: list) -> str:
    return f"{kind}{'s' if len(refs) > 1 else ''}: " + ", ".join(r["name"] for r in refs)


def _register_badge(reg, refs: list, bid: str) -> None:
    if reg is None:
        return
    for r in refs:
        if r["address"]:
            reg.by_address.setdefault(r["address"], bid)   # first badge wins: several subnets share a construct


def _add_subnet_badges(d: DrawioBuilder, sid: str, subnet: dict, width, reg) -> list:
    """Route-table / security-list badges straddling the subnet's top-right corner.

    Route table centred on the corner, security lists one badge to its left
    (toolkit slide 18: half-size icons used as labels of the subnet box).
    Returns the badge ids (0-2).
    """
    ids = []
    cx = width
    rt = _badge_refs(subnet.get("route_table"))
    if rt:
        bid = d.add_badge("route_table", cx, 0, parent=sid, host=sid, key=f"{sid}-rt",
                          tooltip=_badge_tooltip("Route table", rt),
                          metadata={"route_table": ", ".join(r["name"] for r in rt)})
        _register_badge(reg, rt, bid)
        ids.append(bid)
        cx -= BADGE_SIZE + BADGE_GAP
    sls = _badge_refs(subnet.get("security_lists"))
    if sls:
        bid = d.add_badge("security_list", cx, 0, parent=sid, host=sid, key=f"{sid}-sl",
                          tooltip=_badge_tooltip("Security list", sls),
                          metadata={"security_lists": ", ".join(r["name"] for r in sls)})
        _register_badge(reg, sls, bid)
        ids.append(bid)
    return ids


def _add_nsg_badge(d: DrawioBuilder, parent, cid: str, item: dict, reg=None):
    """NSG shield badge over the top-right of the host icon's slot; None when the item has no ``nsgs``."""
    nsgs = _badge_refs(item.get("nsgs"))
    if not nsgs:
        return None
    sx, sy, _sw, _sh = d.bbox(cid)
    bid = d.add_badge("nsg", sx + ICON_W - BADGE_SIZE / 2, sy + BADGE_SIZE / 2, parent=parent, host=cid,
                      key=f"{cid}-nsg", tooltip=_badge_tooltip("NSG", nsgs),
                      metadata={"nsgs": ", ".join(r["name"] for r in nsgs)})
    _register_badge(reg, nsgs, bid)
    return bid


def _icon_items(d: DrawioBuilder, parent, items, cols, x0=PAD, y0=ROW1_Y, reg=None):
    specs = []
    for it in items:
        spec = {"label": it.get("label", ""), "icon": it.get("icon", "vm")}
        for k in ("metadata", "tooltip", "link"):
            if it.get(k):
                spec[k] = it[k]
        if it.get("address"):
            spec["key"] = str(it["address"])
        specs.append(spec)
    ids, bbox = d.place_icons(parent, specs, cols=cols, x0=x0, y0=y0)
    for it, cid in zip(items, ids):
        _add_nsg_badge(d, parent, cid, it, reg)
    if reg is not None:
        for it, cid in zip(items, ids):
            reg.add_item(it, cid)
    return ids, bbox


def _layout_subnet(d: DrawioBuilder, vcn_id, subnet, x, y, max_cols, reg, min_w=None):
    items = subnet.get("items") or []
    rows, cols = _grid(len(items), max_cols)
    prov_w = cols * COL_W + SUBNET_EXTRA_W
    prov_h = ROW1_Y + (rows - 1) * ROW_H + ICON_FOOTPRINT_H + SUBNET_BOTTOM_PAD
    sid = d.add_group(_subnet_label(subnet), x, y, prov_w, prov_h, parent=vcn_id,
                      group_type="subnet",
                      key=f"subnet:{subnet.get('name', '')}" if subnet.get("name") else None,
                      metadata=subnet.get("metadata"), tooltip=subnet.get("tooltip"))
    reg.containers[f"subnet:{subnet.get('name', '')}"] = sid
    if subnet.get("address"):
        reg.by_address[str(subnet["address"])] = sid
    if items:
        _icon_items(d, sid, items, cols, reg=reg)
        w, h = d.fit_to_children(sid, pad=PAD, min_w=max(prov_w, min_w or 0), min_h=prov_h)
    else:
        w, h = prov_w, max(prov_h, 120)
        if min_w:
            w = max(w, min_w)
        d.resize(sid, w=w, h=h)
    _add_subnet_badges(d, sid, subnet, w, reg)       # after the final size: badges sit on the corner
    return sid, w, h


def _layout_vcn(d: DrawioBuilder, region_id, vcn: dict, x, y, reg, max_row_w=MAX_ROW_W,
                inset_left=0, right_pad=PAD, bottom_pad=VCN_BOTTOM_PAD, min_h=200,
                min_w=VCN_MIN_W):
    """Lay out one VCN box; min_h / min_w are the minimum FINAL height / width (borders
    included), so the caller can reserve room for the gateways that straddle the border."""
    vid = d.add_group(_vcn_label(vcn), x, y, 400, 300, parent=region_id, group_type="vcn",
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
        est_w = cols * COL_W + SUBNET_EXTRA_W
        if cur and cur_w + H_GAP + est_w > max_row_w:
            rows.append(cur)
            cur, cur_w = [], 0.0
        cur.append(s)
        cur_w += (H_GAP if cur_w else 0) + est_w
    if cur:
        rows.append(cur)

    cy = ROW1_Y
    row1_right = PAD + inset_left
    for row in rows:
        cx = PAD + inset_left
        bottoms = []
        for s in row:
            sid, w, h = _layout_subnet(d, vid, s, cx, cy, 2, reg)
            cx += w + H_GAP
            bottoms.append(cy + h)
        row1_right = max(row1_right, cx - H_GAP)
        cy = max(bottoms) + V_GAP if bottoms else cy

    # Services panel to the right of the first row
    services = list(vcn.get("services") or [])
    if services:
        rows_n, cols = _grid(len(services), 2)
        prov_w = cols * COL_W + SUBNET_EXTRA_W
        prov_h = ROW1_Y + (rows_n - 1) * ROW_H + ICON_FOOTPRINT_H + SUBNET_BOTTOM_PAD
        px = (row1_right + PANEL_GAP) if rows else PAD + inset_left
        pid = d.add_group(vcn.get("services_label", "OCI Services"), px, ROW1_Y, prov_w, prov_h,
                          parent=vid, group_type="services",
                          key=f"services:{vcn.get('name', '')}" if vcn.get("name") else None)
        reg.containers["services"] = pid
        reg.containers[f"services:{vcn.get('name', '')}"] = pid
        _icon_items(d, pid, services, cols, reg=reg)
        d.fit_to_children(pid, pad=PAD, min_w=prov_w, min_h=prov_h)

    # Data tier subnets, stretched to the width of the rows above
    row_w = max(row1_right - PAD - inset_left, 0)
    for s in data_subnets:
        n = len(s.get("items") or [])
        sid, w, h = _layout_subnet(d, vid, s, PAD + inset_left, cy, max(2, min(5, n or 2)), reg,
                                   min_w=row_w if row_w else None)
        cy += h + V_GAP

    w, h = d.fit_to_children(vid, pad=PAD, min_w=VCN_MIN_W, min_h=min_h)
    w = max(w + right_pad - PAD, min_w)
    h += bottom_pad - PAD
    d.resize(vid, w=w, h=h)
    return vid, w, h


def _layout_hub(d: DrawioBuilder, region_id, hub: dict, vcn_y, vcn_h, reg, explicit_pairs=frozenset()):
    items = list(hub.get("items") or [])
    n = max(1, len(items))
    hub_h = HUB_ICON_Y0 + (n - 1) * HUB_PITCH + ICON_FOOTPRINT_H + 30
    hub_y = max(VCN_Y, int(round((vcn_y + (vcn_h - hub_h) / 2) / 10.0) * 10))
    hid = d.add_group(hub.get("name", "On-Premises"), HUB_X, hub_y, HUB_W, hub_h,
                      parent=region_id, group_type="onprem", key="hub")
    reg.containers["hub"] = hid
    ids = []
    for i, it in enumerate(items):
        spec = {"label": it.get("label", ""), "icon": it.get("icon", "cpe")}
        if it.get("address"):
            spec["key"] = str(it["address"])
        for k in ("metadata", "tooltip"):
            if it.get(k):
                spec[k] = it[k]
        got, _ = d.place_icons(hid, [spec], cols=1,
                               x0=int(round((HUB_W - ICON_W) / 2 / 10.0) * 10),
                               y0=HUB_ICON_Y0 + i * HUB_PITCH)
        ids.extend(got)
        reg.add_item(it, got[0])
    d.fit_to_children(hid, pad=PAD, min_w=HUB_W, min_h=hub_h)
    if hub.get("link_label") is not None and len(ids) >= 2:
        for (ia, a), (ib, b) in zip(zip(items, ids), zip(items[1:], ids[1:])):
            pair = (str(ia.get("address")), str(ib.get("address")))
            if pair in explicit_pairs or pair[::-1] in explicit_pairs:
                continue  # the model already connects these two hub items
            d.add_edge(a, b, hub.get("link_label") or "", parent=hid)
    return hid


def _drg_attachments(drg: dict) -> list:
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


def _drg_cluster_geometry(drg: dict, style: str) -> dict:
    """Sizes of one DRG cluster: icon slot + attachment boxes (right = VCNs, left = on-prem / RPC)."""
    atts = _drg_attachments(drg)
    right = [a for a in atts if attachment_type(a) == "vcn"]
    left = [a for a in atts if attachment_type(a) != "vcn"]
    left_w = ATT_W + ATT_GAP if left else 0
    right_w = ATT_W + ATT_GAP if right else 0
    left_h, left_block = _att_block(left)
    right_h, right_block = _att_block(right)
    body_h = max(ICON_FOOTPRINT_H, left_block, right_block)
    inner_w = left_w + ICON_W + right_w
    cluster_h = body_h
    if style == "box":
        inner_w += 2 * PAD
        cluster_h += ROW1_Y + PAD
    return {"left": left, "right": right, "left_w": left_w, "inner_w": inner_w,
            "body_h": body_h, "cluster_h": cluster_h,
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


def _drg_column_width(drgs, requested: str) -> int:
    return max(_drg_cluster_geometry(drg, _drg_style_for(drg, requested))["inner_w"] for drg in drgs)


def _layout_drg_column(d: DrawioBuilder, region_id, drgs, col_x, stack_y, stack_h, requested, reg,
                       style_out) -> list:
    """DRG icon(s) with their attachment boxes at region level, centred on the VCN stack.

    Returns the pending attachment connectors: {"source", "vcn", "target", "label", "key"}.
    """
    clusters = [(drg, _drg_style_for(drg, requested)) for drg in drgs]
    geoms = [_drg_cluster_geometry(drg, style) for drg, style in clusters]
    total_h = sum(g["cluster_h"] for g in geoms) + DRG_CLUSTER_GAP * (len(geoms) - 1)
    y = max(VCN_Y, int(round((stack_y + (stack_h - total_h) / 2) / 10.0) * 10))
    pending = []
    for (drg, style), g in zip(clusters, geoms):
        name = drg.get("name") or first_line(drg.get("label")) or "DRG"
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
            d.fit_to_children(gid, pad=PAD)
        style_out[addr] = style
        y += g["cluster_h"] + DRG_CLUSTER_GAP
    return pending


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


def build_diagram(model: dict, style_profile="default", legend=False, logo=None,
                  page_name=None, title=True, max_row_w=MAX_ROW_W, drg_style=None) -> DrawioBuilder:
    """Lay out a normalized model and return the (unwritten) DrawioBuilder.

    Schema-1 models are migrated first (DRG hub items / drg gateways -> drgs[]);
    migration warnings go to stderr and to ``builder.layout_info["warnings"]``.
    ``drg_style`` (auto | icon | box) overrides ``model["drg_style"]``.
    """
    model, warnings = migrate_legacy_model(model)
    for w in warnings:
        print(w, file=sys.stderr)
    if not model.get("vcns") and not model.get("hub") and not model.get("drgs"):
        raise ValueError("model needs at least one VCN (model['vcns']), a hub or a DRG")
    requested = str(drg_style or model.get("drg_style") or "auto").lower()
    choose_drg_style(requested, 0)                     # validates the value early
    topo = classify_topology(model)
    subject = model.get("subject") or (model["vcns"][0].get("name") if model.get("vcns") else "Architecture")
    d = DrawioBuilder(page_name=page_name or f"{subject} Architecture", style_profile=style_profile)
    d.layout_info = {"topology": topo, "warnings": list(warnings), "drg_style": {}}
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

    # Column order: on-premises panel | DRG column | VCN columns | OCI Services | Oracle Services Network
    x = HUB_X + HUB_W + HUB_GAP if hub else PAD
    drg_col_x = x
    if drgs:
        if hub:
            drg_col_x = max(drg_col_x, HUB_X + HUB_W + _hub_gutter(drgs, d.profile["edge_font"]))
        x = drg_col_x + _drg_column_width(drgs, requested) + DRG_GAP

    order = _vcn_order(vcns)
    vcn_boxes = []
    edge_gateways = []          # (vcn index, side, gateway dict, icon id)
    for i, vcn in enumerate(vcns):
        sides = _gateway_sides(vcn, i, order)
        # Reserve the room the straddling gateways need: one bottom slot every GW_PITCH
        # from vx + PAD (the trailing PAD also covers the last caption's 15 px overhang),
        # and one side slot every SIDE_GW_PITCH from SIDE_GW_Y0 / LEFT_GW_Y0.
        need_w = max(
            VCN_MIN_W,
            (PAD + (len(sides["bottom"]) - 1) * GW_PITCH + ICON_W + PAD) if sides["bottom"] else 0,
        )
        need_h = max(
            200,
            (SIDE_GW_Y0 + (len(sides["right"]) - 1) * SIDE_GW_PITCH + ICON_FOOTPRINT_H + PAD) if sides["right"] else 0,
            (LEFT_GW_Y0 + (len(sides["left"]) - 1) * SIDE_GW_PITCH + ICON_FOOTPRINT_H + PAD) if sides["left"] else 0,
        )
        vid, w, h = _layout_vcn(d, rid, vcn, x, VCN_Y, reg, max_row_w=max_row_w,
                                inset_left=SIDE_INSET if sides["left"] else 0,
                                right_pad=VCN_SIDE_PAD if sides["right"] else PAD,
                                bottom_pad=VCN_BOTTOM_PAD_GW if sides["bottom"] else VCN_BOTTOM_PAD,
                                min_h=need_h, min_w=need_w)
        vcn_boxes.append((vid, x, VCN_Y, w, h))
        for side in ("bottom", "right", "left"):
            for slot, g in enumerate(sides[side]):
                gid = _place_edge_gateway(d, rid, (x, VCN_Y, w, h), side, slot, g, reg)
                edge_gateways.append((i, side, g, gid))
        x += w + (VCN_COLUMN_GAP_GW if sides["right"] else VCN_COLUMN_GAP)

    if top_services:
        rows_n, cols = _grid(len(top_services), 2)
        pid = d.add_group("OCI Services", x, VCN_Y, cols * COL_W + SUBNET_EXTRA_W,
                          ROW1_Y + (rows_n - 1) * ROW_H + ICON_FOOTPRINT_H + SUBNET_BOTTOM_PAD,
                          parent=rid, group_type="services", key="services")
        reg.containers["services"] = pid
        _icon_items(d, pid, top_services, cols, reg=reg)
        pw, _ = d.fit_to_children(pid, pad=PAD)
        x += pw + VCN_COLUMN_GAP

    ref_h = max((b[4] for b in vcn_boxes), default=400)
    osn_id = None
    if osn_items:
        # the VCN loop already added the trailing column gap: subtracting VCN_COLUMN_GAP
        # leaves last_right + OSN_GAP, plus the extra VCN_COLUMN_GAP_GW - VCN_COLUMN_GAP
        # when the last column has right-border gateways whose captions need the room.
        osn_x = (x - VCN_COLUMN_GAP + OSN_GAP) if (vcn_boxes or top_services) else x
        osn_id, _, _ = _layout_osn(d, rid, osn_items, osn_x, VCN_Y, ref_h, reg)
        # spec section 12: a schema-1 edge addressed to "services:<vcn>" must keep resolving
        # when the split left that VCN without a services panel of its own
        for _vcn in vcns:
            _name = str(_vcn.get("name") or "")
            if _name and not (_vcn.get("services") or []):
                reg.containers.setdefault("services:%s" % _name, osn_id)

    if hub:
        pairs = {(str(e.get("source")), str(e.get("target"))) for e in (model.get("edges") or [])}
        _layout_hub(d, rid, hub, VCN_Y, ref_h, reg, explicit_pairs=pairs)

    pending = []
    if drgs:
        pending = _layout_drg_column(d, rid, drgs, drg_col_x, VCN_Y, ref_h, requested, reg,
                                     d.layout_info["drg_style"])

    d.fit_to_children(rid, pad=PAD)

    if osn_id is not None:
        for _i, side, g, gid in edge_gateways:
            if side == "right" and _is_sgw(g):
                d.add_edge(gid, osn_id, "", kind="attachment",
                           key=f"{g['address']}-osn" if g.get("address") else None)

    if model.get("notes"):
        d.add_text(escape_label(model["notes"]), TITLE_BOX[0] + TITLE_BOX[2] + 20, TITLE_BOX[1],
                   400, TITLE_BOX[3], font_size=10, raw_html=True)

    for pe in pending:
        target = _resolve_attachment_target(reg, pe)
        if target is not None:
            d.add_edge(pe["source"], target, pe["label"], kind="attachment", key=pe["key"])

    for e in model.get("edges") or []:
        spec = EDGE_KINDS.get(str(e.get("kind") or "data").lower(), EDGE_KINDS["data"])
        kwargs = dict(color=e.get("color", spec["color"]), key=e.get("address"))
        if "dashed" in e:
            kwargs["dashed"] = e["dashed"]            # explicit override keeps the profile look
        else:
            kwargs["kind"] = spec["kind"]
        d.add_edge(reg.resolve(e["source"]), reg.resolve(e["target"]), e.get("label", ""), **kwargs)

    if legend:
        _, _, _, bottom = d.content_bbox()
        d.add_legend(REGION_XY[0], bottom + GAP)

    d.fit_page(margin=PAD)
    return d


def write_diagram(model: dict, out_path, strict=False, render_fmt=None, **opts) -> Path:
    """Build, validate (raising on errors) and write the diagram."""
    d = build_diagram(model, **opts)
    problems = d.validate(strict=strict)
    errors = [p for p in problems if not p.split("] ")[-1].startswith("WARNING")]
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
    args = ap.parse_args(argv)
    model = load_model(args.model)
    subject = model.get("subject") or "Architecture"
    out = Path(args.out) if args.out else Path(f"{subject.replace(' ', '_')}_Architecture.drawio")
    write_diagram(model, out, strict=args.strict, render_fmt=args.render,
                  style_profile=args.profile, legend=args.legend, logo=args.logo,
                  drg_style=args.drg_style)
    return 0


if __name__ == "__main__":
    sys.exit(main())
