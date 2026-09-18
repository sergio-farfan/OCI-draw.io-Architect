#!/usr/bin/env python3
"""Deterministic OCI diagram layout: normalized model dict -> .drawio.

This is the layout recipe the /drawio-architect workflow uses so that every
generated diagram has the same structure as the reference sample:

    Title block (bold subject, italic "Region label (region) - Compartment: X")
    Region (solid, label top-left)
      +-- Hub / on-premises panel (left, vertically centred on the VCN)
      +-- VCN column(s)
            +-- row 1: lb -> app -> compute -> mgmt subnets (traffic order, 2 icon columns)
            +-- OCI Services panel (right of row 1; VCN-resident services)
            +-- data-tier subnets stretched to the row width
      +-- gateways centred on the VCN border (IGW / NAT bottom, SGW right,
          LPG facing its peer), parented to the region
      +-- Oracle Services Network panel (region level, right of the VCN columns;
          regional services, reached from the SGW by an attachment connector)
      edges auto-routed through the gutters; optional legend below the region.

Model schema (JSON-serialisable dict; every key optional except vcns/subject):

    {
      "subject": "Spoke-VCN-D",           # title: "<subject> - Architecture"
      "region": "us-ashburn-1", "region_label": "Ashburn",
      "compartment": "Spoke-VCN-D", "tenancy_name": null,
      "hub": {"name": "Hub Network\\nHub-Network\\n(Shared-Services)",
              "items": [{"icon": "firewall", "label": "Corp VPN\\n(10.0.0.0/8)", "address": "cpe"},
                        {"icon": "drg", "label": "Dynamic Routing\\nGateway (DRG)", "address": "drg"}],
              "link_label": "IPSec VPN"},
      "vcns": [{
         "name": "Spoke-VCN-D", "cidr": "10.0.0.0/16",
         "subnets": [{"name": "sn-priv-lb", "cidr": "10.0.0.0/24", "tier": "lb", "public": false,
                      "items": [{"icon": "load_balancer", "label": "Load Balancer\\n10.0.0.23",
                                 "address": "lb", "metadata": {"ocid": "..."}, "tooltip": "..."}]}],
         # regional services -> Oracle Services Network panel;
         # "regional": false keeps an item in the VCN panel
         "services": [{"icon": "devops", "label": "DevOps\\nProject + CI/CD", "address": "devops"}],
         "services_label": "OCI Services",
         "gateways": [{"icon": "service_gateway", "type": "sgw",
                       "label": "Service\\nGateway", "address": "sgw"}]
      }],
      "services": [ ... ],                  # regional -> Oracle Services Network panel; the rest
                                            # joins the VCN panel (single VCN) or a region panel
      "edges": [{"source": "lb", "target": "app-vm", "label": "3000 / 8000", "kind": "data"}],
      "notes": "optional free text placed under the title"
    }

Edge "kind": data (solid Bark, open arrow), control (dashed Bark, no arrow),
analytics (solid Sienna), datalake (dashed purple); or pass "dashed"/"color".
Edge source/target: an item "address", a container reference ("vcn:<name>",
"subnet:<name>", "hub", "services", "services:<vcn>", "osn") or a unique caption
first line. "services" / "services:<vcn>" fall back to the Oracle Services
Network panel when the split left no matching VCN services panel.

Usage (CLI):
    python3 oci_layout.py model.json -o out.drawio [--profile default|official|v1.0]
                          [--legend] [--logo file] [--strict] [--render png]

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
    COL_W, COLORS, GAP, ICON_FOOTPRINT_H, ICON_W, PAD, ROW1_Y, ROW_H, DrawioBuilder,
    escape_label, render,
)
from oci_topology import is_regional  # noqa: E402

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

EDGE_KINDS = {
    "data": dict(dashed=False, color=None),
    "control": dict(dashed=True, color=None),
    "management": dict(dashed=True, color=None),
    "analytics": dict(dashed=False, color=COLORS["edge_accent"]),
    "datalake": dict(dashed=True, color=COLORS["edge_purple"]),
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


def build_diagram(model: dict, style_profile="default", legend=False, logo=None,
                  page_name=None, title=True, max_row_w=MAX_ROW_W) -> DrawioBuilder:
    """Lay out a normalized model and return the (unwritten) DrawioBuilder."""
    if not model.get("vcns") and not model.get("hub"):
        raise ValueError("model needs at least one VCN (model['vcns']) or a hub")
    subject = model.get("subject") or (model["vcns"][0].get("name") if model.get("vcns") else "Architecture")
    d = DrawioBuilder(page_name=page_name or f"{subject} Architecture", style_profile=style_profile)
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
    vcn_x = HUB_X + HUB_W + HUB_GAP if hub else PAD
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

    order = _vcn_order(vcns)
    vcn_boxes = []
    edge_gateways = []          # (vcn index, side, gateway dict, icon id)
    x = vcn_x
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

    d.fit_to_children(rid, pad=PAD)

    if osn_id is not None:
        for _i, side, g, gid in edge_gateways:
            if side == "right" and _is_sgw(g):
                d.add_edge(gid, osn_id, "", kind="attachment",
                           key=f"{g['address']}-osn" if g.get("address") else None)

    if model.get("notes"):
        d.add_text(escape_label(model["notes"]), TITLE_BOX[0] + TITLE_BOX[2] + 20, TITLE_BOX[1],
                   400, TITLE_BOX[3], font_size=10, raw_html=True)

    for e in model.get("edges") or []:
        kind = EDGE_KINDS.get((e.get("kind") or "data").lower(), EDGE_KINDS["data"])
        d.add_edge(reg.resolve(e["source"]), reg.resolve(e["target"]), e.get("label", ""),
                   dashed=e.get("dashed", kind["dashed"]), color=e.get("color", kind["color"]),
                   key=e.get("address"))

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
    args = ap.parse_args(argv)
    model = load_model(args.model)
    subject = model.get("subject") or "Architecture"
    out = Path(args.out) if args.out else Path(f"{subject.replace(' ', '_')}_Architecture.drawio")
    write_diagram(model, out, strict=args.strict, render_fmt=args.render,
                  style_profile=args.profile, legend=args.legend, logo=args.logo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
