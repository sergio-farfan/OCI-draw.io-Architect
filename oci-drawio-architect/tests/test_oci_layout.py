"""Layout tests for scripts/oci_layout.py (v1.4.0 placement enrichments; the v1.5.0 view controls have their own modules)."""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import drawio_builder as db  # noqa: E402
import oci_layout as ol  # noqa: E402


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def label_collisions(d):
    """(edge id, shape id) pairs where a connector label is drawn over a real shape.

    An endpoint icon's footprint hull is skipped (its side margins are empty
    canvas) but its glyph slot and caption are not, and an endpoint box - an
    attachment box, a table, a text block - counts in full: a label on top of
    the box it leaves is the defect this catches.
    """
    d.route_edges()
    hits = []
    for page_idx in range(len(d._pages)):
        _, obstacles = d._routing_shapes(page_idx)
        for cid, e in d._cells.items():
            if e["kind"] != "edge" or e["page"] != page_idx or not e.get("label_box"):
                continue
            lbox = db._Box(*e["label_box"])
            for oid, ob in obstacles.items():
                own_hull = (oid in (e["source"], e["target"])
                            and d._cells[oid]["kind"] == "icon")
                if oid.endswith("#label") or own_hull:
                    continue
                if ob.intersects(lbox):
                    hits.append((cid, oid))
    return hits


def docking_points(d):
    """(endpoint cell id, absolute docking point) for both ends of every edge.

    The point is where the router pinned the connector: the exit / entry
    fraction of the endpoint's own box, or the first / last waypoint for an
    edge the router left unpinned.
    """
    d.route_edges()
    out = []
    for cid, e in d._cells.items():
        if e["kind"] != "edge":
            continue
        tok = style_of(d, cid)
        poly = e.get("polyline") or []
        ends = (("source", tok.get("exitX"), tok.get("exitY"), poly[0] if poly else None),
                ("target", tok.get("entryX"), tok.get("entryY"), poly[-1] if poly else None))
        for end, fx, fy, fallback in ends:
            box = d._abs_cell(e[end]) if e[end] in d._cells else None
            if fx is not None and fy is not None and box is not None:
                x, y, w, h = box
                point = (round(x + w * float(fx), 1), round(y + h * float(fy), 1))
            elif fallback is not None:
                point = (round(fallback[0], 1), round(fallback[1], 1))
            else:
                continue
            out.append((cid, e[end], point))
    return out


def file_docking_points(path):
    """Same, read back from a written .drawio; endpoints are keyed per page."""
    out = []
    for page_idx, page in enumerate(ET.parse(str(path)).iter("diagram")):
        cells = {}
        for el in page.iter():
            if el.tag in ("object", "UserObject"):       # metadata / link wrapper
                inner = el.find("mxCell")
                if inner is not None and el.get("id"):
                    cells[el.get("id")] = inner
            elif el.tag == "mxCell" and el.get("id"):
                cells[el.get("id")] = el

        def abs_box(cid):
            x = y = w = h = 0.0
            cur, first, seen = cid, True, set()
            while cur in cells and cur not in seen:
                seen.add(cur)
                g = cells[cur].find("mxGeometry")
                if g is not None:
                    x += float(g.get("x") or 0)
                    y += float(g.get("y") or 0)
                    if first:
                        w, h = float(g.get("width") or 0), float(g.get("height") or 0)
                cur, first = cells[cur].get("parent"), False
            return x, y, w, h

        for cid, el in cells.items():
            if el.get("edge") != "1":
                continue
            tok = db._style_tokens(el.get("style", ""))
            for end, fx, fy in (("source", tok.get("exitX"), tok.get("exitY")),
                                ("target", tok.get("entryX"), tok.get("entryY"))):
                ref = el.get(end)
                if ref not in cells or fx is None or fy is None:
                    continue
                x, y, w, h = abs_box(ref)
                out.append((cid, (page_idx, ref),
                            (round(x + w * float(fx), 1), round(y + h * float(fy), 1))))
    return out


def shared_docking_points(entries):
    """{(cell, point): [edge ids]} for every point used by more than one edge."""
    seen = {}
    for edge_id, cell_id, point in entries:
        seen.setdefault((cell_id, point), []).append(edge_id)
    return {k: sorted(v) for k, v in seen.items() if len(v) > 1}


def errors_of(d):
    return [m for m in d.validate() if not db.is_warning(m)]


def style_of(d, cid):
    for el in d.root.iter("mxCell"):
        if el.get("id") == cid:
            return db._style_tokens(el.get("style", ""))
    raise KeyError(cid)


def gw(gtype, icon, label, address, **extra):
    g = {"type": gtype, "icon": icon, "label": label, "address": address}
    g.update(extra)
    return g


def simple_vcn(name, address=None, gateways=None, services=None, item="app"):
    return {"name": name, "address": address, "cidr": "10.0.0.0/16",
            "subnets": [{"name": f"sn-{name}", "cidr": "10.0.1.0/24", "tier": "app",
                         "items": [{"icon": "vm", "label": f"App {name}", "address": f"{item}-{name}"}]}],
            "services": services or [], "gateways": gateways or []}


def wide_vcn(name):
    """A taller / wider neighbour column, so an overflowing gateway would collide with it."""
    tiers = ("lb", "app", "mgmt", "data")
    return {"name": name, "cidr": "10.1.0.0/16", "services": [], "gateways": [],
            "subnets": [{"name": f"sn-{name}-{t}", "cidr": f"10.1.{i}.0/24", "tier": t,
                         "items": [{"icon": "vm", "label": f"VM {t} {name}", "address": f"{name}-{t}"}]}
                        for i, t in enumerate(tiers)]}


MODEL_GW = {
    "subject": "gw", "region": "us-ashburn-1", "locations": "nested",
    "vcns": [simple_vcn("a", gateways=[
        gw("igw", "internet_gateway", "Internet\nGateway", "igw"),
        gw("nat", "nat_gateway", "NAT\nGateway", "nat"),
        gw("sgw", "service_gateway", "Service\nGateway", "sgw")])],
    "edges": [{"source": "app-a", "target": "sgw", "label": "OCI APIs", "kind": "control"}],
}


class GatewayPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = quiet(ol.build_diagram, MODEL_GW)
        cls.vx, cls.vy, cls.vw, cls.vh = cls.d.abs_bbox("vcn-a")

    def test_gateways_are_region_children_with_address_ids(self):
        for cid in ("igw", "nat", "sgw"):
            self.assertEqual(self.d._cells[cid]["parent"], "region", cid)
        self.assertEqual(errors_of(self.d), [])

    def test_igw_and_nat_straddle_the_bottom_border(self):
        for i, cid in enumerate(("igw", "nat")):
            x, y, w, h = self.d.abs_bbox(cid)                       # 75x95 slot
            self.assertEqual(y + ol.GW_STRADDLE, self.vy + self.vh, cid)   # glyph centre on the border line
            self.assertEqual(x, self.vx + ol.PAD + i * ol.GW_PITCH, cid)

    def test_sgw_straddles_the_right_border_with_opaque_caption(self):
        x, y, w, h = self.d.abs_bbox("sgw")
        self.assertEqual(x + ol.GW_SIDE_DX, self.vx + self.vw)
        self.assertEqual(y, self.vy + ol.SIDE_GW_Y0)
        caption = self.d._cells["sgw"]["label_id"]
        self.assertEqual(style_of(self.d, caption)["fillColor"], db.COLORS["region_fill"])

    def test_vcn_keeps_clearance_from_straddling_glyphs(self):
        sx, sy, sw, sh = self.d.abs_bbox("subnet-sn-a")
        self.assertGreaterEqual(self.vy + self.vh - ol.GW_STRADDLE - (sy + sh), 20)      # bottom gateways
        self.assertGreaterEqual(self.vx + self.vw - ol.GW_SIDE_DX - (sx + sw), 20)       # right gateway

    def test_region_encloses_the_hanging_captions(self):
        rx, ry, rw, rh = self.d.abs_bbox("region")
        for cid in ("igw", "nat", "sgw"):
            fx, fy, fw, fh = self.d._abs_footprint(cid)
            self.assertLessEqual(fy + fh, ry + rh + 0.5, cid)
            self.assertLessEqual(fx + fw, rx + rw + 0.5, cid)

    def test_edge_to_a_gateway_still_resolves(self):
        edges = [e for e in self.d._cells.values() if e["kind"] == "edge" and e.get("target") == "sgw"]
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["source"], "app-a")

    def test_a_gateway_keeps_its_link(self):
        """A18: _place_edge_gateway must copy 'link' like _icon_items does."""
        model = {"subject": "link", "region": "us-ashburn-1", "vcns": [simple_vcn(
            "a", gateways=[gw("igw", "internet_gateway", "Internet\nGateway", "igw",
                              link="https://docs.oracle.com/iaas/")])]}
        with tempfile.TemporaryDirectory() as tmp:
            out = quiet(ol.write_diagram, model, Path(tmp) / "link.drawio")
            self.assertIn('link="https://docs.oracle.com/iaas/"', out.read_text(encoding="utf-8"))


class LpgSideTests(unittest.TestCase):
    def _model(self, peer_a="lpg-b", peer_b="lpg-a"):
        return {"subject": "peering", "region": "us-ashburn-1", "locations": "nested", "vcns": [
            simple_vcn("a", gateways=[gw("lpg", "remote_peering_gateway", "LPG\nlpg-a", "lpg-a", peer=peer_a)]),
            simple_vcn("b", gateways=[gw("lpg", "remote_peering_gateway", "LPG\nlpg-b", "lpg-b", peer=peer_b)])],
            "edges": [{"source": "lpg-a", "target": "lpg-b", "label": "Local Peering", "kind": "attachment"}]}

    def test_lpgs_face_their_peer_vcn(self):
        d = quiet(ol.build_diagram, self._model())
        ax, ay, aw, ah = d.abs_bbox("vcn-a")
        bx, by, bw, bh = d.abs_bbox("vcn-b")
        lx, ly, _, _ = d.abs_bbox("lpg-a")
        self.assertEqual(lx + ol.GW_SIDE_DX, ax + aw)                 # right border of a
        rx, ry, _, _ = d.abs_bbox("lpg-b")
        self.assertEqual(rx + ol.GW_SIDE_DX - 1, bx)                  # left border of b
        self.assertEqual(ry, by + ol.LEFT_GW_Y0)
        self.assertGreaterEqual(bx - (ax + aw), ol.VCN_COLUMN_GAP_GW)
        self.assertEqual(errors_of(d), [])
        edge = next(e for e in d._cells.values() if e["kind"] == "edge" and e.get("source") == "lpg-a")
        self.assertEqual(edge["target"], "lpg-b")

    def test_peer_may_be_a_vcn_name_and_unknown_peer_goes_to_the_bottom(self):
        d = quiet(ol.build_diagram, self._model(peer_a="b", peer_b="nowhere"))
        ax, ay, aw, ah = d.abs_bbox("vcn-a")
        lx, _, _, _ = d.abs_bbox("lpg-a")
        self.assertEqual(lx + ol.GW_SIDE_DX, ax + aw)
        bx, by, bw, bh = d.abs_bbox("vcn-b")
        _, ry, _, _ = d.abs_bbox("lpg-b")
        self.assertEqual(ry + ol.GW_STRADDLE, by + bh)
        self.assertEqual(ol._gateway_side(gw("lpg", "remote_peering_gateway", "x", "l", peer="nowhere"), 0, {}), "bottom")
        self.assertEqual(ol._gateway_side(gw("sgw", "service_gateway", "x", "s"), 0, {}), "right")
        self.assertEqual(ol._gateway_side(gw("igw", "internet_gateway", "x", "i"), 0, {}), "bottom")
        self.assertEqual(ol._gateway_side({"icon": "nat_gateway", "label": "n"}, 0, {}), "bottom")

    def test_a_one_sided_model_keeps_the_undeclared_lpg_on_the_bottom_border(self):
        """Spec 7.3: only a known peer moves an LPG to a side border.

        Terraform declares ``peer_id`` on the requestor only; parse_terraform
        mirrors it onto the acceptor, so a model that reaches the recipe with
        one side unset is hand-written - it keeps the documented fallback.
        """
        d = quiet(ol.build_diagram, self._model(peer_b=None))
        ax, ay, aw, ah = d.abs_bbox("vcn-a")
        lx, _, _, _ = d.abs_bbox("lpg-a")
        self.assertEqual(lx + ol.GW_SIDE_DX, ax + aw)                 # a still faces b
        bx, by, bw, bh = d.abs_bbox("vcn-b")
        _, ry, _, _ = d.abs_bbox("lpg-b")
        self.assertEqual(ry + ol.GW_STRADDLE, by + bh)                # b has no peer: bottom border
        self.assertEqual(errors_of(d), [])


class BottomGatewayWidthTests(unittest.TestCase):
    """A narrow VCN widens so 3+ bottom-border gateways stay on its own border (GW_PITCH = 180)."""

    def _model(self, n):
        gws = [gw("igw", "internet_gateway", "Internet\nGateway", "igw"),
               gw("nat", "nat_gateway", "NAT\nGateway", "nat"),
               gw("lpg", "remote_peering_gateway", "LPG\nno peer", "lpg"),
               gw("igw", "internet_gateway", "Internet\nGateway 2", "igw2")][:n]
        return {"subject": "gw-width", "region": "us-ashburn-1", "locations": "nested",
                "vcns": [simple_vcn("a", gateways=gws), wide_vcn("b")]}

    def test_three_bottom_gateways_widen_the_vcn_and_stay_inside_it(self):
        d = quiet(ol.build_diagram, self._model(3))
        vx, vy, vw, vh = d.abs_bbox("vcn-a")
        self.assertGreaterEqual(vw, ol.PAD + 2 * ol.GW_PITCH + db.ICON_W + ol.PAD)
        for cid in ("igw", "nat", "lpg"):
            fx, fy, fw, fh = d._abs_footprint(cid)
            self.assertGreaterEqual(fx, vx, cid)
            self.assertLessEqual(fx + fw, vx + vw, cid)          # icon + caption on its own border
        bx, by, bw, bh = d.abs_bbox("vcn-b")
        self.assertGreaterEqual(bx, vx + vw)                     # no reach into the next column
        self.assertEqual(errors_of(d), [])

    def test_a_fourth_bottom_gateway_widens_the_vcn_by_one_pitch(self):
        w3 = quiet(ol.build_diagram, self._model(3)).abs_bbox("vcn-a")[2]
        w4 = quiet(ol.build_diagram, self._model(4)).abs_bbox("vcn-a")[2]
        self.assertEqual(w4 - w3, ol.GW_PITCH)

    def test_the_guard_leaves_a_gateway_less_vcn_at_the_minimum_width(self):
        d = quiet(ol.build_diagram, {"subject": "plain", "region": "us-ashburn-1",
                                     "locations": "nested", "vcns": [simple_vcn("a")]})
        self.assertEqual(d.abs_bbox("vcn-a")[2], ol.VCN_MIN_W)

    def test_a_next_column_left_gateway_widens_the_previous_column_gap(self):
        """A17: the gap must hold the widest caption of either facing border."""
        model = {"subject": "peer", "region": "us-ashburn-1", "locations": "nested", "vcns": [
            simple_vcn("a"),
            simple_vcn("b", gateways=[gw("lpg", "remote_peering_gateway",
                                         "Local Peering\nGateway", "lpg-b", peer="a")])]}
        d = quiet(ol.build_diagram, model)
        ax, ay, aw, ah = d.abs_bbox("vcn-a")
        bx, by, bw, bh = d.abs_bbox("vcn-b")
        self.assertEqual(bx - (ax + aw), ol.VCN_COLUMN_GAP_GW)
        cap_x = d.abs_bbox(d._cells["lpg-b"]["label_id"])[0]
        self.assertGreaterEqual(cap_x, ax + aw)              # the caption clears VCN a entirely
        self.assertEqual(errors_of(d), [])


def svc(icon, address, **extra):
    s = {"icon": icon, "label": icon.replace("_", " ").title(), "address": address}
    s.update(extra)
    return s


class OsnPanelTests(unittest.TestCase):
    def test_regional_services_move_to_the_osn_panel_right_of_the_vcn(self):
        model = {"subject": "svc", "region": "us-ashburn-1", "locations": "nested", "vcns": [simple_vcn(
            "a", gateways=[gw("sgw", "service_gateway", "Service\nGateway", "sgw")],
            services=[svc("logging", "log"), svc("buckets", "bkt"), svc("file_storage", "fss")])]}
        d = quiet(ol.build_diagram, model)
        vx, vy, vw, vh = d.abs_bbox("vcn-a")
        ox, oy, _ow, oh = d.abs_bbox("osn")
        self.assertEqual(d._cells["osn"]["group_type"], "oracle_services_network")
        self.assertEqual(d._cells["osn"]["parent"], "region")
        self.assertEqual(style_of(d, "osn")["align"], "left")
        # a right-border SGW widens the last column gap so its caption clears the panel
        self.assertEqual(ox, vx + vw + ol.OSN_GAP + (ol.VCN_COLUMN_GAP_GW - ol.VCN_COLUMN_GAP))
        self.assertEqual((oy, oh), (vy, vh))                          # same vertical extent as the VCN
        self.assertEqual(d._cells["log"]["parent"], "osn")
        self.assertEqual(d._cells["bkt"]["parent"], "osn")
        self.assertEqual(d._cells["fss"]["parent"], "services-a")      # VCN-resident stays in the VCN panel
        self.assertEqual(d._cells["services-a"]["parent"], "vcn-a")
        osn_edges = [e for e in d._cells.values() if e["kind"] == "edge" and e.get("target") == "osn"]
        self.assertEqual([(e["source"], e["label"]) for e in osn_edges], [("sgw", "")])
        self.assertEqual(style_of(d, "sgw-osn")["endArrow"], "none")
        self.assertEqual(errors_of(d), [])

    def test_all_regional_means_no_vcn_services_panel_and_services_alias(self):
        model = {"subject": "svc", "region": "us-ashburn-1",
                 "vcns": [simple_vcn("a", services=[svc("logging", "log"), svc("alarms", "alarm")])],
                 "edges": [{"source": "app-a", "target": "services", "label": "logs", "kind": "control"}]}
        d = quiet(ol.build_diagram, model)
        self.assertNotIn("services-a", d._cells)
        edge = next(e for e in d._cells.values() if e["kind"] == "edge" and e.get("source") == "app-a")
        self.assertEqual(edge["target"], "osn")
        self.assertEqual(errors_of(d), [])

    def test_regional_override_and_top_level_services(self):
        model = {"subject": "svc", "region": "us-ashburn-1", "locations": "nested",
                 "vcns": [simple_vcn("a", services=[svc("logging", "log", regional=False)]),
                          simple_vcn("b", services=[])],
                 "services": [svc("vault", "vault"), svc("bastion", "bastion", regional=False)]}
        d = quiet(ol.build_diagram, model)
        self.assertEqual(d._cells["log"]["parent"], "services-a")
        self.assertEqual(d._cells["vault"]["parent"], "osn")
        self.assertEqual(d._cells["bastion"]["parent"], "services")     # region-level "OCI Services" panel (2 VCNs)
        bx, _, bw, _ = d.abs_bbox("vcn-b")
        sx, _, sw, _ = d.abs_bbox("services")
        ox, _, _, _ = d.abs_bbox("osn")
        self.assertGreater(sx, bx + bw)
        self.assertGreater(ox, sx + sw)
        self.assertEqual(errors_of(d), [])

    def test_services_colon_vcn_endpoint_resolves_to_the_osn_panel(self):
        model = {"subject": "svc", "region": "us-ashburn-1",
                 "vcns": [simple_vcn("a", services=[svc("logging", "log")]),
                          simple_vcn("b", services=[svc("bastion", "bastion", regional=False)])],
                 "edges": [{"source": "app-a", "target": "services:a", "kind": "control"},
                           {"source": "app-b", "target": "services:b", "kind": "control"}]}
        d = quiet(ol.build_diagram, model)
        self.assertNotIn("services-a", d._cells)
        targets = {e["source"]: e["target"] for e in d._cells.values()
                   if e["kind"] == "edge" and e.get("source") in ("app-a", "app-b")}
        self.assertEqual(targets["app-a"], "osn")            # the split left VCN a without a panel
        self.assertEqual(targets["app-b"], "services-b")     # VCN b keeps its own panel
        self.assertEqual(errors_of(d), [])

    def test_no_regional_services_means_no_osn_panel(self):
        d = quiet(ol.build_diagram, MODEL_GW)
        self.assertNotIn("osn", d._cells)
        self.assertEqual([e for e in d._cells.values() if e["kind"] == "edge" and e.get("target") == "osn"], [])

    def test_regional_services_from_two_vcns_share_one_osn_panel(self):
        """Spec D6: ONE Oracle Services Network panel, whichever VCN declared the service."""
        model = {"subject": "two", "region": "us-ashburn-1", "vcns": [
            simple_vcn("a", services=[svc("logging", "log-a")]),
            simple_vcn("b", services=[svc("buckets", "bkt-b")])]}
        d = quiet(ol.build_diagram, model)
        self.assertEqual(d._cells["log-a"]["parent"], "osn")
        self.assertEqual(d._cells["bkt-b"]["parent"], "osn")
        panels = [c for c, e in d._cells.items() if e.get("group_type") == "oracle_services_network"]
        self.assertEqual(panels, ["osn"])
        self.assertEqual(errors_of(d), [])

    def test_the_region_services_panel_matches_the_vcn_column_height(self):
        """A28: spec 7.2 - the legacy 'OCI Services' panel is height-matched like the OSN panel."""
        model = {"subject": "two", "region": "us-ashburn-1",
                 "vcns": [simple_vcn("a"), wide_vcn("b")],
                 "services": [svc("file_storage", "fss")]}
        d = quiet(ol.build_diagram, model)
        _, by, _, bh = d.abs_bbox("vcn-b")
        _, py, _, ph = d.abs_bbox("services")
        self.assertEqual((py, ph), (by, bh))
        self.assertEqual(errors_of(d), [])


HYBRID = {
    "subject": "Spoke", "region": "us-ashburn-1",
    "hub": {"name": "On-premises", "items": [{"icon": "cpe", "label": "CPE\nhq", "address": "cpe"}]},
    "drgs": [{"name": "drg", "address": "drg", "label": "DRG\ndrg", "attachments": [
        {"type": "vcn", "vcn": "Spoke", "address": "att-spoke", "label": "VCN attachment\nSpoke"}]}],
    "vcns": [simple_vcn("Spoke", gateways=[gw("sgw", "service_gateway", "Service\nGateway", "sgw")])],
    "edges": [{"source": "cpe", "target": "drg", "label": "IPSec VPN", "kind": "data"},
              {"source": "drg", "target": "app-Spoke", "label": "", "kind": "data"}],
}


class DrgColumnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = quiet(ol.build_diagram, HYBRID)

    def test_topology_and_style_recorded(self):
        self.assertEqual(self.d.layout_info["topology"]["kind"], "hybrid")
        self.assertEqual(self.d.layout_info["drg_style"], {"drg": "icon"})
        self.assertEqual(self.d.layout_info["warnings"], [])

    def test_drg_is_a_region_child_between_hub_and_vcn(self):
        d = self.d
        self.assertEqual(d._cells["drg"]["parent"], "region")
        hx, hy, hw, hh = d.abs_bbox("hub")
        vx, vy, vw, vh = d.abs_bbox("vcn-Spoke")
        dx, dy, dw, dh = d.abs_bbox("drg")
        self.assertGreaterEqual(dx, hx + hw + ol.HUB_GAP)
        self.assertLess(dx + dw, vx)
        self.assertAlmostEqual(dy + ol.GW_STRADDLE, vy + vh / 2, delta=ol.ATT_PITCH)   # centred on the VCN stack

    def test_attachment_box_sits_between_drg_and_vcn_and_connects_to_the_border(self):
        d = self.d
        bx, by, bw, bh = d.abs_bbox("att-spoke")
        dx, dy, dw, dh = d.abs_bbox("drg")
        vx, vy, vw, vh = d.abs_bbox("vcn-Spoke")
        self.assertEqual(d._cells["att-spoke"]["parent"], "region")
        self.assertEqual(bx, dx + ol.ICON_W + ol.ATT_GAP)
        self.assertEqual((bw, bh), (ol.ATT_W, ol.ATT_H))
        self.assertEqual(vx - (bx + bw), ol.DRG_GAP)
        e = d._cells["att-spoke-edge"]
        self.assertEqual((e["source"], e["target"]), ("att-spoke", "vcn-Spoke"))
        tok = style_of(d, "att-spoke-edge")
        self.assertEqual((tok["endArrow"], tok["strokeWidth"], tok["dashed"]), ("none", "1", "0"))

    def test_hub_holds_only_the_cpe_and_explicit_edges_resolve(self):
        d = self.d
        self.assertEqual([c for c, e in d._cells.items() if e["parent"] == "hub" and e["kind"] == "icon"], ["cpe"])
        pairs = {(e["source"], e["target"]) for e in d._cells.values() if e["kind"] == "edge" and e.get("source")}
        self.assertIn(("cpe", "drg"), pairs)
        self.assertIn(("drg", "app-Spoke"), pairs)
        self.assertEqual(errors_of(d), [])

    def test_a_bare_cluster_side_reserves_the_caption_overhang(self):
        """A23: the 105 px caption overhangs the 75 px slot by 15 px on a side with no box."""
        pad = (db.LABEL_W - db.ICON_W) // 2
        g = ol._drg_cluster_geometry({"name": "drg", "attachments": [
            {"type": "vcn", "vcn": "a", "address": "att-a"}]}, "icon")
        self.assertEqual(g["left_w"], pad)
        self.assertEqual(g["inner_w"], pad + db.ICON_W + ol.ATT_W + ol.ATT_GAP)
        box = ol._drg_cluster_geometry({"name": "drg", "attachments": [
            {"type": "vcn", "vcn": f"v{i}", "address": f"att-{i}"} for i in range(5)]}, "box")
        self.assertEqual(box["left_w"], 0)                 # box style pads with PAD already

    def test_the_drg_caption_starts_at_the_cluster_edge(self):
        d = quiet(ol.build_diagram, HYBRID)
        lx, _, _, _ = d.abs_bbox("drg-label")
        ax, _, aw, _ = d.abs_bbox("att-spoke")
        self.assertEqual(ax + aw - lx, ol._drg_column_width(HYBRID["drgs"], "auto"))

    def test_resolve_attachment_target_by_name_by_address_and_the_error_paths(self):
        """A24: VCN by name, VCN by address, unknown VCN, and an attachment with no target."""
        reg = ol._Registry()
        reg.containers["vcn:prod"] = "vcn-prod"
        reg.by_address["oci_core_vcn.prod"] = "vcn-prod"
        reg.by_address["cpe"] = "cpe-icon"
        self.assertEqual(ol._resolve_attachment_target(reg, {"source": "b", "vcn": "prod"}), "vcn-prod")
        self.assertEqual(ol._resolve_attachment_target(reg, {"source": "b", "vcn": "oci_core_vcn.prod"}),
                         "vcn-prod")
        self.assertEqual(ol._resolve_attachment_target(reg, {"source": "b", "target": "cpe"}), "cpe-icon")
        self.assertIsNone(ol._resolve_attachment_target(reg, {"source": "b"}))
        with self.assertRaises(ValueError) as ctx:
            ol._resolve_attachment_target(reg, {"source": "att-x", "vcn": "nope"})
        self.assertIn("VCN 'nope' is not in the model", str(ctx.exception))


class UnnamedDrgTests(unittest.TestCase):
    """A22: an unnamed DRG must never be called 'DRG' - two of them collided on the key drg:DRG."""

    def _model(self, *drgs):
        return {"subject": "unnamed", "region": "us-ashburn-1",
                "vcns": [simple_vcn("a"), simple_vcn("b")], "drgs": list(drgs)}

    def test_two_unnamed_drgs_take_their_names_from_the_second_label_line(self):
        d = quiet(ol.build_diagram, self._model(
            {"label": "DRG\nhub", "attachments": [{"type": "vcn", "vcn": "a", "address": "att-a"}]},
            {"label": "DRG\nspoke", "attachments": [{"type": "vcn", "vcn": "b", "address": "att-b"}]}))
        self.assertEqual(sorted(d.layout_info["drg_style"]), ["drg:hub", "drg:spoke"])
        self.assertIn("drg-hub", d._cells)                     # _slug() turns ':' into '-'
        self.assertIn("drg-spoke", d._cells)
        self.assertEqual(errors_of(d), [])

    def test_a_label_with_no_second_line_falls_back_to_the_address_then_the_index(self):
        d = quiet(ol.build_diagram, self._model(
            {"label": "DRG", "address": "drg-a", "attachments": [{"type": "vcn", "vcn": "a", "address": "att-a"}]},
            {"label": "DRG", "attachments": [{"type": "vcn", "vcn": "b", "address": "att-b"}]}))
        self.assertIn("drg-a", d._cells)                       # its own address is the cell key
        self.assertIn("drg-drg-2", d._cells)                   # second DRG, no name and no address
        self.assertEqual(errors_of(d), [])

    def test_a_named_drg_and_a_descriptive_label_are_unchanged(self):
        d = quiet(ol.build_diagram, self._model(
            {"name": "prod-hub", "address": "drg-prod", "label": "DRG\nprod",
             "attachments": [{"type": "vcn", "vcn": "a", "address": "att-a"}]},
            {"label": "Dynamic Routing\nGateway (DRG)",
             "attachments": [{"type": "vcn", "vcn": "b", "address": "att-b"}]}))
        self.assertEqual(sorted(d.layout_info["drg_style"]), ["drg-prod", "drg:Dynamic Routing"])


class EdgeKindTests(unittest.TestCase):
    """Model edge kinds map to the builder's connector styles (no DRG fixture needed)."""

    def test_edge_kinds_map_to_builder_kinds(self):
        model = copy.deepcopy(MODEL_GW)
        model["vcns"][0]["subnets"][0]["items"].append({"icon": "vault", "label": "Vault", "address": "vault-a"})
        model["edges"] = [
            {"source": "app-a", "target": "vault-a", "label": "secrets", "kind": "association", "address": "e-assoc"},
            {"source": "app-a", "target": "sgw", "label": "443", "kind": "control", "address": "e-ctl"},
            {"source": "app-a", "target": "igw", "label": "", "kind": "datalake", "address": "e-lake"},
            {"source": "app-a", "target": "nat", "label": "", "kind": "data", "dashed": True, "address": "e-dashed"},
        ]
        d = quiet(ol.build_diagram, model)
        self.assertEqual((style_of(d, "e-assoc")["dashPattern"], style_of(d, "e-assoc")["endArrow"]), ("1 3", "none"))
        self.assertEqual((style_of(d, "e-ctl")["dashed"], style_of(d, "e-ctl")["endArrow"]), ("1", "open"))
        self.assertEqual(style_of(d, "e-lake")["strokeColor"], db.COLORS["edge_purple"])
        self.assertEqual(style_of(d, "e-dashed")["endArrow"], "none")     # explicit dashed keeps the profile look


class AttachmentBoxTextTests(unittest.TestCase):
    """A parser-style display name must wrap inside its box instead of across the diagram."""

    LONG = "drg_attachment_vcn_prod_shared_services_hub"          # 43 chars, no break opportunity

    def _model(self, *labels):
        atts = [{"type": "vcn", "vcn": "Spoke", "address": f"att-{i}", "label": lab}
                for i, lab in enumerate(labels)]
        return {"subject": "Spoke", "region": "us-ashburn-1",
                "drgs": [{"name": "drg", "address": "drg", "label": "DRG\ndrg", "attachments": atts}],
                "vcns": [simple_vcn("Spoke")]}

    def test_long_label_gets_wrap_hints_and_a_taller_box(self):
        d = quiet(ol.build_diagram, self._model(self.LONG))
        text = d._cells["att-0"]["label"]
        self.assertIn(db.WRAP_HINT, text)
        self.assertEqual(text.replace(db.WRAP_HINT, ""), self.LONG)
        lines = db.label_lines(text, ol.ATT_W - 2 * ol.ATT_TEXT_PAD, ol.ATT_FONT_SIZE)
        self.assertGreater(lines, 3)
        _, _, bw, bh = d.abs_bbox("att-0")
        self.assertEqual(bw, ol.ATT_W)
        self.assertEqual(bh, lines * db.LABEL_LINE_H + 2 * ol.ATT_TEXT_PAD)
        self.assertGreater(bh, ol.ATT_H)
        self.assertEqual(errors_of(d), [])
        self.assertEqual(d.validate(strict=True), [], "the grown box holds its own label")
        # the plain label still resolves an edge and stays in the registry
        self.assertEqual(ol.attachment_label({"type": "vcn", "vcn": "Spoke", "label": self.LONG}), self.LONG)

    def test_short_label_keeps_the_default_box_and_no_hints(self):
        d = quiet(ol.build_diagram, self._model("VCN attachment\nSpoke"))
        self.assertEqual(d._cells["att-0"]["label"], "VCN attachment<br>Spoke")
        self.assertEqual(d.abs_bbox("att-0")[3], ol.ATT_H)

    def test_stacked_boxes_of_different_heights_keep_their_gap(self):
        d = quiet(ol.build_diagram, self._model(self.LONG, "VCN attachment\nSpoke", self.LONG))
        boxes = [d.abs_bbox(f"att-{i}") for i in range(3)]
        for (_, y0, _, h0), (_, y1, _, _) in zip(boxes, boxes[1:]):
            self.assertEqual(y1 - (y0 + h0), ol.ATT_VGAP)
        _, dy, _, _ = d.abs_bbox("drg")
        block = boxes[-1][1] + boxes[-1][3] - boxes[0][1]
        self.assertAlmostEqual(boxes[0][1] + block / 2, dy + ol.GW_STRADDLE, delta=1)  # centred on the DRG glyph
        self.assertEqual(d.validate(strict=True), [])


class DrgStyleTests(unittest.TestCase):
    def _hub_spoke(self, n=5):
        vcns = [simple_vcn(f"v{i}") for i in range(2)]
        atts = [{"type": "vcn", "vcn": f"v{i % 2}", "address": f"att-{i}"} for i in range(n)]
        return {"subject": "hs", "region": "us-ashburn-1", "vcns": vcns,
                "drgs": [{"name": "drg", "address": "drg", "label": "DRG\ndrg", "attachments": atts}]}

    def test_auto_picks_box_above_four_attachments(self):
        d = quiet(ol.build_diagram, self._hub_spoke(5))
        self.assertEqual(d.layout_info["topology"]["kind"], "hub_spoke")
        self.assertEqual(d.layout_info["drg_style"]["drg"], "box")
        self.assertEqual(d._cells["drgbox-drg"]["group_type"], "drg")
        self.assertEqual(d._cells["drgbox-drg"]["parent"], "region")
        self.assertEqual(d._cells["drg"]["parent"], "drgbox-drg")
        self.assertEqual(d._cells["att-0"]["parent"], "drgbox-drg")
        self.assertEqual(style_of(d, "drgbox-drg")["ociGroup"], "drg")
        self.assertEqual(errors_of(d), [])

    def test_auto_picks_icon_up_to_four_attachments(self):
        d = quiet(ol.build_diagram, self._hub_spoke(4))
        self.assertEqual(d.layout_info["drg_style"]["drg"], "icon")
        self.assertNotIn("drgbox-drg", d._cells)

    def test_the_call_argument_forces_the_box_style(self):
        d = quiet(ol.build_diagram, self._hub_spoke(2), drg_style="box")
        self.assertIn("drgbox-drg", d._cells)

    def test_the_model_field_forces_the_icon_style(self):
        model = self._hub_spoke(6)
        model["drg_style"] = "icon"
        d = quiet(ol.build_diagram, model)
        self.assertNotIn("drgbox-drg", d._cells)

    def test_an_unknown_drg_style_raises(self):
        with self.assertRaises(ValueError):
            quiet(ol.build_diagram, self._hub_spoke(6), drg_style="fancy")

    def test_onprem_attachments_sit_left_and_link_to_the_hub_item(self):
        model = self._hub_spoke(1)
        model["hub"] = {"name": "On-premises", "items": [{"icon": "cpe", "label": "CPE", "address": "cpe"},
                                                         {"icon": "rpg", "label": "RPC peer", "address": "rpc-peer"}]}
        model["drgs"][0]["attachments"] += [
            {"type": "ipsec", "target": "cpe", "address": "att-vpn", "label": "vpn-hq"},
            {"type": "rpc", "target": "rpc-peer", "address": "att-rpc"},
            {"type": "loopback", "address": "att-loop"}]
        d = quiet(ol.build_diagram, model)
        self.assertEqual(d.layout_info["topology"]["kind"], "hybrid")
        dx, _, _, _ = d.abs_bbox("drg")
        vx, _, _, _ = d.abs_bbox("att-vpn")
        self.assertEqual(vx + ol.ATT_W + ol.ATT_GAP, dx)
        self.assertEqual(d._cells["att-vpn-edge"]["target"], "cpe")
        self.assertEqual(d._cells["att-vpn-edge"]["label"], "Site-to-Site VPN")
        self.assertEqual(d._cells["att-rpc-edge"]["label"], "Remote Peering")
        self.assertEqual(d._cells["att-rpc"]["label"], "RPC attachment")
        self.assertNotIn("att-loop", d._cells)
        self.assertEqual(errors_of(d), [])


class HubKindTests(unittest.TestCase):
    def _model(self, hub):
        return {"subject": "hub", "region": "us-ashburn-1", "hub": hub, "vcns": [simple_vcn("a")]}

    def test_the_default_kind_titles_the_panel_on_premises(self):
        d = quiet(ol.build_diagram, self._model(
            {"items": [{"icon": "cpe", "label": "CPE", "address": "cpe"}]}))
        self.assertEqual(d._cells["hub"]["label"], "On-premises")
        self.assertEqual(d._cells["hub"]["group_type"], "onprem")

    def test_a_remote_region_hub_keeps_the_onprem_styling_and_changes_its_title(self):
        d = quiet(ol.build_diagram, self._model(
            {"kind": "remote_region", "items": [{"icon": "rpg", "label": "RPC", "address": "rpc"}]}))
        self.assertEqual(d._cells["hub"]["label"], "Remote region")
        self.assertEqual(d._cells["hub"]["group_type"], "onprem")

    def test_an_explicit_name_still_wins(self):
        d = quiet(ol.build_diagram, self._model(
            {"kind": "remote_region", "name": "Frankfurt", "items": [{"icon": "rpg", "label": "RPC", "address": "rpc"}]}))
        self.assertEqual(d._cells["hub"]["label"], "Frankfurt")


class LegacyModelTests(unittest.TestCase):
    LEGACY = {
        "subject": "Spoke", "region": "us-ashburn-1",
        "hub": {"name": "Hub Network", "link_label": "IPSec VPN",
                "items": [{"icon": "firewall", "label": "Corp VPN", "address": "cpe"},
                          {"icon": "drg", "label": "Dynamic Routing\nGateway (DRG)", "address": "drg"}]},
        "vcns": [simple_vcn("Spoke", gateways=[gw("sgw", "service_gateway", "Service\nGateway", "sgw")])],
        "edges": [{"source": "drg", "target": "app-Spoke", "label": "", "kind": "data"}],
    }

    def test_legacy_hub_drg_is_drawn_at_region_level_with_a_warning(self):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            d = ol.build_diagram(self.LEGACY)
        self.assertEqual(d._cells["drg"]["parent"], "region")
        self.assertEqual([c for c, e in d._cells.items() if e["parent"] == "hub" and e["kind"] == "icon"], ["cpe"])
        self.assertIn("drg-Spoke", d._cells)                      # implicit attachment drg@Spoke
        pairs = {(e["source"], e["target"]) for e in d._cells.values() if e["kind"] == "edge" and e.get("source")}
        self.assertIn(("cpe", "drg"), pairs)                      # link_label became an explicit edge
        self.assertIn(("drg", "app-Spoke"), pairs)
        self.assertTrue(d.layout_info["warnings"])
        self.assertIn("WARNING: legacy model: hub item 'drg' moved to drgs[]", err.getvalue())
        self.assertEqual(errors_of(d), [])


class CliTests(unittest.TestCase):
    def test_cli_drg_style_and_gate(self):
        import check_overlaps
        with tempfile.TemporaryDirectory() as tmp:
            mpath = Path(tmp) / "m.json"
            out = Path(tmp) / "o.drawio"
            mpath.write_text(json.dumps(HYBRID))
            self.assertEqual(quiet(ol.main, [str(mpath), "-o", str(out), "--drg-style", "box"]), 0)
            self.assertIn('id="drgbox-drg"', out.read_text(encoding="utf-8"))
            self.assertEqual(quiet(check_overlaps.main, [str(out)]), 0)
            self.assertEqual(quiet(ol.main, [str(mpath), "-o", str(out)]), 0)
            self.assertNotIn('id="drgbox-drg"', out.read_text(encoding="utf-8"))
            self.assertEqual(quiet(check_overlaps.main, [str(out)]), 0)

    def test_write_diagram_forwards_drg_style_and_legend(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = quiet(ol.write_diagram, HYBRID, Path(tmp) / "h.drawio", drg_style="box", legend=True)
            text = out.read_text(encoding="utf-8")
            self.assertIn('id="drgbox-drg"', text)
            self.assertIn("Attachment (structural)", text)

    def test_the_five_view_flags_reach_the_recipe(self):
        model = {"subject": "flags", "region": "us-ashburn-1", "vcns": [simple_vcn("a")]}
        with tempfile.TemporaryDirectory() as tmp:
            mp = Path(tmp) / "model.json"
            mp.write_text(json.dumps(model), encoding="utf-8")
            out = Path(tmp) / "flags.drawio"
            rc = quiet(ol.main, [str(mp), "-o", str(out), "--locations", "nested",
                                 "--gateway-edge", "bottom", "--subnet-label", "inline",
                                 "--attachment-style", "dotted", "--show-compartments"])
            self.assertEqual(rc, 0)
            self.assertIn("sn-a (10.0.1.0/24)", out.read_text(encoding="utf-8"))


class ExamplesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples_dir = str(TESTS_DIR.parent / "examples")
        sys.path.insert(0, cls.examples_dir)
        cls.addClassCleanup(sys.path.remove, cls.examples_dir)

    def test_reference_model_is_schema_2_and_passes_the_gate(self):
        import check_overlaps
        from generate_reference_layout import MODEL
        self.assertEqual([i["address"] for i in MODEL["hub"]["items"]], ["cpe"])
        self.assertEqual([a["type"] for a in MODEL["drgs"][0]["attachments"]], ["vcn"])
        self.assertIn({"source": "cpe", "target": "drg", "label": "IPSec VPN", "kind": "data"}, MODEL["edges"])
        d = quiet(ol.build_diagram, MODEL)
        self.assertEqual(d.layout_info["warnings"], [])
        self.assertEqual(d.layout_info["topology"]["kind"], "hybrid")
        self.assertEqual(d._cells["drg"]["parent"], "region")
        self.assertEqual(d._cells["sgw"]["parent"], "region")
        self.assertEqual(d._cells["logging"]["parent"], "osn")
        self.assertNotIn("services-Spoke-VCN-D", d._cells)
        with tempfile.TemporaryDirectory() as tmp:
            out = quiet(ol.write_diagram, MODEL, Path(tmp) / "ref.drawio")
            self.assertEqual(quiet(check_overlaps.main, [str(out)]), 0)

    def test_reference_model_renders_the_outside_canvas(self):
        """Spec section 9: the canonical sample ships the v1.4.0 default canvas."""
        from generate_reference_layout import MODEL
        self.assertEqual(MODEL["internet"], {"name": "Internet", "items": []})
        self.assertNotIn("locations", MODEL)                   # the default is "outside"
        d = quiet(ol.build_diagram, MODEL)
        # the location boxes are page-level siblings of the region, not its children
        for cid in ("hub", "internet"):
            self.assertEqual(d._cells[cid]["parent"], "1", cid)
        self.assertEqual(d._cells["region"]["parent"], "1")
        rx, _, _, _ = d.abs_bbox("region")
        hx, _, hw, _ = d.abs_bbox("hub")
        ix, _, _, _ = d.abs_bbox("internet")
        # the gutter holds the hybrid label AND the half slot the straddling CPE
        # pushes out of the On-Premises box (decision 5)
        self.assertEqual(rx - (hx + hw),
                         max(ol.LOC_GAP_MIN, ol._hub_gutter(MODEL["drgs"], d.profile["edge_font"]))
                         + db.ICON_W - ol.GW_SIDE_DX)
        self.assertGreater(ix, rx)                             # Internet on the right of the region
        # the CPE straddles the On-Premises box's region-facing border (decision 5).
        # The reference hub item is matched by its type `oci_core_cpe`, not by the
        # `firewall` icon it draws with.
        cx, _, cw, _ = d.abs_bbox("cpe")
        self.assertAlmostEqual(cx + cw / 2, hx + hw, delta=1.0)
        # the NAT faces the Internet box, the SGW faces the OSN band below the VCN
        vx, vy, vw, vh = d.abs_bbox("vcn-Spoke-VCN-D")
        nx, ny, _, _ = d.abs_bbox("nat")
        sx, sy, _, _ = d.abs_bbox("sgw")
        self.assertEqual(nx + ol.GW_SIDE_DX, vx + vw)
        self.assertEqual(sy + ol.GW_STRADDLE, vy + vh)
        ox, oy, _, _ = d.abs_bbox("osn")
        self.assertGreater(oy, vy + vh)                        # OSN is a band below the stack
        self.assertEqual(errors_of(d), [])

    def test_reference_model_draws_its_nsgs_as_badges(self):
        from generate_reference_layout import MODEL
        items = {i["address"]: i for s in MODEL["vcns"][0]["subnets"] for i in s["items"]}
        self.assertEqual([a for a, i in items.items()
                          if i["icon"] in ("nsg", "security_list", "route_table")], [])
        self.assertEqual({a: i["nsgs"] for a, i in items.items() if i.get("nsgs")},
                         {"lb": ["nsg-priv-lb"], "app-vm": ["nsg-priv-app"],
                          "worker-vm": ["nsg-priv-workers"], "adb": ["nsg-priv-data (21 rules)"]})
        d = quiet(ol.build_diagram, MODEL)
        self.assertEqual(sorted(c for c, e in d._cells.items() if e.get("badge")),
                         ["adb-nsg", "app-vm-nsg", "lb-nsg", "worker-vm-nsg"])

    def test_demo_builds_six_pages_and_passes_the_gate(self):
        import check_overlaps
        import generate_demo_diagram as demo
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "demo.drawio"
            quiet(demo.build, out)
            text = out.read_text(encoding="utf-8")
            # 1.5.0 added the executive and engineering view pages (spec 10)
            self.assertEqual(text.count("<diagram "), 6)
            self.assertIn('id="drgbox-drg"', text)                  # page 2: box style
            self.assertIn("Attachment (structural)", text)          # legend row
            self.assertIn("Oracle Services Network", text)
            self.assertIn('id="tenancy"', text)                     # page 3: compartments
            self.assertIn('id="compartment-Network"', text)         # _slug() turns ':' into '-'
            self.assertIn('id="oke-main-box"', text)                # page 3: the OKE cluster box
            self.assertIn('id="tier-app"', text)                    # page 3: the tier band
            self.assertIn('id="drg-lz-rt2"', text)                  # page 3: two DRG route tables
            self.assertEqual(quiet(check_overlaps.main, [str(out)]), 0)

    def test_demo_page_three_nests_its_vcns_in_compartments(self):
        """Spec 6.3: VCNs are children of their compartment, the DRG stays at region level."""
        import generate_demo_diagram as demo
        d = quiet(ol.build_diagram, demo.COMPARTMENT_MODEL)
        self.assertEqual(d._cells["vcn-vcn-net"]["parent"], "compartment-Network")
        self.assertEqual(d._cells["vcn-vcn-app"]["parent"], "compartment-App")
        self.assertEqual(d._cells["compartment-Network"]["parent"], "compartment-Enclosing")
        self.assertEqual(d._cells["compartment-Enclosing"]["parent"], "tenancy")
        self.assertEqual(d._cells["tenancy"]["parent"], "region")
        self.assertEqual(d._cells["drg-lz"]["parent"], "region")
        # the OKE box is a container whose members were re-parented into it
        for addr in ("oke-main", "np-a", "np-b"):
            self.assertEqual(d._cells[addr]["parent"], "oke-main-box")
        self.assertEqual(d._cells["oke-main-box"]["group_type"], "oke_cluster")
        self.assertEqual(d._cells["tier-app"]["group_type"], "tier")
        # an edge may terminate on a grouping box (G8)
        edges = [e for e in d._cells.values() if e["kind"] == "edge" and e.get("target") == "oke-main-box"]
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["source"], "edge-lb")
        self.assertEqual(errors_of(d), [])

    def test_connector_labels_are_not_drawn_over_shapes(self):
        """Spec section 2: the Site-to-Site VPN label sits on the line next to the
        on-premises item - not on top of the IPSec attachment box it leaves."""
        from generate_demo_diagram import DEMO_MODEL
        from generate_reference_layout import MODEL
        cases = (("reference", MODEL, {}),
                 ("demo icon", DEMO_MODEL, {"legend": True}),
                 ("demo box", DEMO_MODEL, {"legend": True, "drg_style": "box"}))
        for name, model, opts in cases:
            with self.subTest(diagram=name):
                d = quiet(ol.build_diagram, model, **opts)
                self.assertEqual(label_collisions(d), [])
                if "att-vpn" not in d._cells:
                    continue
                box = db._Box(*d._abs_cell("att-vpn"))
                label = db._Box(*d._cells["att-vpn-edge"]["label_box"])
                self.assertFalse(box.intersects(label))
                if d.layout_info.get("canvas", {}).get("left_w"):
                    # G3: the hybrid label lives in the gutter, outside the region
                    self.assertLess(label.x, d.abs_bbox("region")[0])
                else:
                    self.assertLessEqual(label.right, box.x)  # on the on-premises side

    def test_reference_gives_every_connector_its_own_docking_point(self):
        """_PORT_SHARE_COST must stay above a three-bend detour: two arrowheads
        on one point read as a single connector and the loser rides the glyph
        border. Checked on the model and on the committed sample."""
        from generate_reference_layout import MODEL
        d = quiet(ol.build_diagram, MODEL)
        shared = shared_docking_points(docking_points(d))
        self.assertEqual(shared, {}, f"connectors sharing a docking point: {shared}")
        committed = TESTS_DIR.parent.parent / "OCI_Architecture.drawio"
        if committed.exists():                                # not shipped in the plugin archive
            shared = shared_docking_points(file_docking_points(committed))
            self.assertEqual(shared, {}, f"committed sample shares docking points: {shared}")

    def test_committed_reference_diagram_is_not_stale(self):
        from generate_reference_layout import MODEL
        committed = TESTS_DIR.parent.parent / "OCI_Architecture.drawio"
        if not committed.exists():                            # not shipped in the plugin archive
            self.skipTest("OCI_Architecture.drawio is not part of this tree")
        with tempfile.TemporaryDirectory() as tmp:
            out = quiet(ol.write_diagram, MODEL, Path(tmp) / "ref.drawio")
            self.assertEqual(out.read_text(encoding="utf-8"),
                             committed.read_text(encoding="utf-8"),
                             "OCI_Architecture.drawio is stale; regenerate it with "
                             "examples/generate_reference_layout.py OCI_Architecture.drawio")


class EndToEndTests(unittest.TestCase):
    FIXTURES = TESTS_DIR / "fixtures"

    def _gate(self, model, name):
        import check_overlaps
        with tempfile.TemporaryDirectory() as tmp:
            out = quiet(ol.write_diagram, model, Path(tmp) / name)
            self.assertEqual(quiet(check_overlaps.main, [str(out)]), 0, name)
            return out.read_text(encoding="utf-8")

    def test_three_tier_terraform_model(self):
        import oci_topology as ot
        import parse_terraform as pt
        model = pt.parse_terraform_dir(self.FIXTURES / "terraform" / "three_tier")
        self.assertEqual(ot.classify_topology(model)["kind"], "hybrid")
        text = self._gate(model, "three_tier.drawio")
        self.assertIn('id="oci_core_drg.drg"', text)                 # DRG at region level (dots survive _slug)
        self.assertIn('id="oci_core_ipsec.vpn-oci_core_drg.drg"', text)   # IPSec attachment box (@ -> -)
        d = quiet(ol.build_diagram, model)
        self.assertEqual(d._cells["oci_core_drg.drg"]["parent"], "region")
        self.assertEqual(d._cells["oci_core_cpe.onprem"]["parent"], "hub")
        self.assertEqual(d.layout_info["warnings"], [])

    def test_hub_spoke_terraform_model(self):
        import oci_topology as ot
        import parse_terraform as pt
        model = pt.parse_terraform_dir(self.FIXTURES / "terraform" / "hub_spoke")
        self.assertEqual(ot.classify_topology(model)["kind"], "hybrid")
        text = self._gate(model, "hub_spoke.drawio")
        self.assertIn("Local Peering", text)
        self.assertIn("FastConnect", text)
        self.assertIn("Remote Peering", text)
        self.assertIn("Oracle Services Network", text)
        model["drg_style"] = "box"
        self._gate(model, "hub_spoke_box.drawio")

    def test_tenancy_bundle_model(self):
        import query_tenancy as qt
        bundle = qt.load_bundle(self.FIXTURES / "tenancy" / "topology_bundle.json")
        model = qt.build_model(bundle, "ocid1.compartment.oc1..aaaaaaaashopprod000001")
        self._gate(model, "tenancy.drawio")

    def test_three_tier_and_tenancy_models_draw_badges(self):
        import parse_terraform as pt
        import query_tenancy as qt
        model = pt.parse_terraform_dir(self.FIXTURES / "terraform" / "three_tier")
        text = self._gate(model, "three_tier_badges.drawio")
        self.assertEqual(text.count("ociRole=badge"), 5)          # rt + sl on sn-lb-public, NSG on lb, instance, adb
        self.assertIn('id="subnet-sn-lb-public-rt"', text)
        self.assertIn('id="oci_core_instance.app-nsg"', text)
        bundle = qt.load_bundle(self.FIXTURES / "tenancy" / "topology_bundle.json")
        text = self._gate(qt.build_model(bundle, "ocid1.compartment.oc1..aaaaaaaashopprod000001"), "tenancy_badges.drawio")
        self.assertEqual(text.count("ociRole=badge"), 4)          # rt + sl on sn-lb-public, NSG on the LB and the instance


BADGED = {
    "subject": "badges", "region": "us-ashburn-1",
    "vcns": [{"name": "a", "cidr": "10.0.0.0/16", "subnets": [
        {"name": "sn-lb", "cidr": "10.0.0.0/24", "tier": "lb", "public": True,
         "route_table": "rt-public", "security_lists": ["sl-lb", {"name": "sl-shared", "address": "sl-shared"}],
         "items": [{"icon": "load_balancer", "label": "Public LB", "address": "lb", "nsgs": ["nsg-lb"]}]},
        {"name": "sn-app", "cidr": "10.0.1.0/24", "tier": "app",
         "route_table": {"name": "rt-private", "address": "rt-private"},
         "items": [{"icon": "vm", "label": "App VM\n10.0.1.5", "address": "app",
                    "nsgs": [{"name": "nsg-app", "address": "nsg-app"}, "nsg-mgmt"]},
                   {"icon": "vault", "label": "Vault", "address": "vault"}]},
        {"name": "sn-db", "cidr": "10.0.2.0/24", "tier": "data", "security_lists": ["sl-db"],
         "items": [{"icon": "autonomous_db", "label": "ADB", "address": "adb", "nsgs": ["nsg-db"]}]}],
        "gateways": [gw("sgw", "service_gateway", "Service\nGateway", "sgw")]}],
    "edges": [{"source": "lb", "target": "app", "label": "8080", "kind": "data"},
              {"source": "app", "target": "adb", "label": "1522", "kind": "data"},
              {"source": "rt-private", "target": "sgw", "label": "OSN", "kind": "control"}],
}


def badge_style(d, cid):
    """Style tokens of any cell, including <object>-wrapped ones (badges carry tooltips)."""
    return db._style_tokens(db.build_cell_registry(d.root)[cid]["style"])


class BadgeLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = quiet(ol.build_diagram, BADGED)

    def test_route_table_badge_is_centred_on_the_subnet_top_right_corner(self):
        for name in ("sn-lb", "sn-app"):
            sx, sy, sw, sh = self.d.abs_bbox(f"subnet-{name}")
            bx, by, bw, bh = self.d.abs_bbox(f"subnet-{name}-rt")
            self.assertAlmostEqual(bx + bw / 2, sx + sw, delta=1.0, msg=name)
            self.assertAlmostEqual(by + bh / 2, sy, delta=1.0, msg=name)
            self.assertEqual((bw, bh), (ol.BADGE_SIZE, ol.BADGE_SIZE), name)
            self.assertEqual(self.d._cells[f"subnet-{name}-rt"]["parent"], f"subnet-{name}", name)

    def test_security_list_badge_sits_left_of_the_route_table_or_takes_the_corner(self):
        sx, sy, sw, sh = self.d.abs_bbox("subnet-sn-lb")
        bx, by, bw, bh = self.d.abs_bbox("subnet-sn-lb-sl")
        self.assertAlmostEqual(bx + bw / 2, sx + sw - ol.BADGE_SIZE - ol.BADGE_GAP, delta=1.0)
        self.assertAlmostEqual(by + bh / 2, sy, delta=1.0)
        dx, dy, dw, dh = self.d.abs_bbox("subnet-sn-db")                 # security lists, no route table
        cx, cy, cw, ch = self.d.abs_bbox("subnet-sn-db-sl")
        self.assertAlmostEqual(cx + cw / 2, dx + dw, delta=1.0)
        self.assertAlmostEqual(cy + ch / 2, dy, delta=1.0)
        self.assertNotIn("subnet-sn-db-rt", self.d._cells)
        self.assertNotIn("subnet-sn-app-sl", self.d._cells)

    def test_nsg_badge_sits_in_the_top_right_of_the_host_slot(self):
        for host in ("lb", "app", "adb"):
            hx, hy, hw, hh = self.d.abs_bbox(host)
            nx, ny, nw, nh = self.d.abs_bbox(f"{host}-nsg")
            self.assertEqual((nx + nw, ny, nw, nh), (hx + hw, hy, ol.BADGE_SIZE, ol.BADGE_SIZE), host)
            self.assertEqual(self.d._cells[f"{host}-nsg"]["parent"], self.d._cells[host]["parent"], host)
        self.assertNotIn("vault-nsg", self.d._cells)

    def test_badges_have_no_caption_and_carry_names_in_tooltips(self):
        tips = {el.get("id"): el.get("tooltip") for el in self.d.root if el.tag == "object" and el.get("tooltip")}
        self.assertEqual(tips["subnet-sn-lb-rt"], "Route table: rt-public")
        self.assertEqual(tips["subnet-sn-lb-sl"], "Security lists: sl-lb, sl-shared")
        self.assertEqual(tips["subnet-sn-db-sl"], "Security list: sl-db")
        self.assertEqual(tips["app-nsg"], "NSGs: nsg-app, nsg-mgmt")
        self.assertEqual(tips["lb-nsg"], "NSG: nsg-lb")
        meta = {el.get("id"): el for el in self.d.root if el.tag == "object"}
        self.assertEqual(meta["subnet-sn-lb-sl"].get("security_lists"), "sl-lb, sl-shared")
        self.assertEqual(meta["app-nsg"].get("nsgs"), "nsg-app, nsg-mgmt")
        for cid in ("subnet-sn-lb-rt", "subnet-sn-lb-sl", "app-nsg"):
            self.assertIsNone(self.d._cells[cid]["label_id"])
            self.assertEqual(badge_style(self.d, cid)["ociRole"], "badge")
        self.assertEqual(badge_style(self.d, "app-nsg")["ociHost"], "app")
        self.assertEqual(badge_style(self.d, "subnet-sn-lb-rt")["ociHost"], "subnet-sn-lb")

    def test_badge_addresses_resolve_as_edge_endpoints(self):
        edge = next(e for e in self.d._cells.values() if e["kind"] == "edge" and e.get("target") == "sgw")
        self.assertEqual(edge["source"], "subnet-sn-app-rt")

    def test_validates_and_passes_the_gate(self):
        import check_overlaps
        self.assertEqual(errors_of(self.d), [])
        with tempfile.TemporaryDirectory() as tmp:
            out = quiet(ol.write_diagram, BADGED, Path(tmp) / "badges.drawio")
            self.assertEqual(quiet(check_overlaps.main, [str(out)]), 0)
            text = out.read_text(encoding="utf-8")
            self.assertEqual(text.count("ociRole=badge"), 7)            # rt+sl, rt, sl + 3 NSG badges

    def test_models_without_the_fields_draw_no_badges(self):
        d = quiet(ol.build_diagram, MODEL_GW)
        self.assertEqual([c for c, e in d._cells.items() if e.get("badge")], [])
        self.assertEqual(ol._badge_refs(None), [])
        self.assertEqual(ol._badge_refs("rt"), [{"name": "rt", "address": None}])
        self.assertEqual(ol._badge_refs([{"name": "a", "address": "x"}, "b", {"label": "c"}, ""]),
                         [{"name": "a", "address": "x"}, {"name": "b", "address": None}, {"name": "c", "address": None}])
        self.assertEqual(ol._badge_tooltip("NSG", ol._badge_refs(["a", "b"])), "NSGs: a, b")


class DemoBadgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples_dir = str(TESTS_DIR.parent / "examples")
        sys.path.insert(0, cls.examples_dir)
        cls.addClassCleanup(sys.path.remove, cls.examples_dir)

    def test_demo_model_carries_badges_on_both_layout_pages(self):
        import check_overlaps
        import generate_demo_diagram as demo
        subnets = {s["name"]: s for v in demo.DEMO_MODEL["vcns"] for s in v["subnets"]}
        self.assertEqual(subnets["sn-public"]["route_table"], "rt-public")
        self.assertEqual(subnets["sn-app"]["security_lists"], ["sl-app"])
        items = {i["address"]: i for s in subnets.values() for i in s["items"]}
        self.assertEqual((items["lb"]["nsgs"], items["app"]["nsgs"], items["adb"]["nsgs"]),
                         (["nsg-lb"], ["nsg-app"], ["nsg-db"]))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "demo.drawio"
            quiet(demo.build, out)
            text = out.read_text(encoding="utf-8")
            # 7 subnet / NSG badges on each of the three pages that draw them
            # (1 Architecture, 2 DRG as a box, 5 Engineering detail), the 2 DRG
            # route-table badges on page 3, and the legend badge rows (3 on each
            # of those three pages, 1 on page 3): 21 + 2 + 10. Page 4 draws none -
            # the executive detail level gates the badges off.
            self.assertEqual(text.count("ociRole=badge"), 33)
            self.assertEqual(quiet(check_overlaps.main, [str(out)]), 0)


class NsgBadgeTests(unittest.TestCase):
    def test_nsg_badge_follows_a_custom_host_slot_width(self):
        """A01: the shield sits on the host slot's top-right corner, whatever its width."""
        d = db.DrawioBuilder()
        r = d.add_group("R", 0, 0, 600, 400, group_type="region", key="region")
        cid = d.add_icon("App", "vm", 40, 60, parent=r, w=120, key="app")
        bid = ol._add_nsg_badge(d, r, cid, {"nsgs": ["nsg-app"]})
        sx, sy, sw, _sh = d.bbox(cid)
        bx, by, bw, bh = d.bbox(bid)
        self.assertEqual((bx + bw / 2, by + bh / 2), (sx + sw - db.BADGE_SIZE / 2, sy + db.BADGE_SIZE / 2))

    def test_a_shared_route_table_resolves_to_the_first_badge(self):
        """A26: a construct shared by two subnets registers the first badge drawn."""
        rt = {"name": "rt-shared", "address": "rt-shared"}
        model = {"subject": "shared", "region": "us-ashburn-1", "vcns": [{
            "name": "a", "cidr": "10.0.0.0/16", "services": [], "gateways": [], "subnets": [
                {"name": "sn-one", "cidr": "10.0.1.0/24", "tier": "app", "route_table": rt,
                 "items": [{"icon": "vm", "label": "One", "address": "vm-one"}]},
                {"name": "sn-two", "cidr": "10.0.2.0/24", "tier": "mgmt", "route_table": rt,
                 "items": [{"icon": "vm", "label": "Two", "address": "vm-two"}]}]}],
            "edges": [{"source": "vm-one", "target": "rt-shared", "label": "", "kind": "association"}]}
        d = quiet(ol.build_diagram, model)
        edge = [e for e in d._cells.values() if e["kind"] == "edge" and e.get("source") == "vm-one"][0]
        self.assertEqual(edge["target"], "subnet-sn-one-rt")   # _slug() turns ':' into '-'

    def test_the_winning_shared_badge_follows_tier_order_not_list_order(self):
        """A26: "first drawn" is the layout's tier order, not the model's subnet list order."""
        rt = {"name": "rt-shared", "address": "rt-shared"}
        model = {"subject": "shared", "region": "us-ashburn-1", "vcns": [{
            "name": "a", "cidr": "10.0.0.0/16", "services": [], "gateways": [], "subnets": [
                {"name": "sn-two", "cidr": "10.0.2.0/24", "tier": "mgmt", "route_table": rt,
                 "items": [{"icon": "vm", "label": "Two", "address": "vm-two"}]},
                {"name": "sn-one", "cidr": "10.0.1.0/24", "tier": "app", "route_table": rt,
                 "items": [{"icon": "vm", "label": "One", "address": "vm-one"}]}]}],
            "edges": [{"source": "vm-one", "target": "rt-shared", "label": "", "kind": "association"}]}
        d = quiet(ol.build_diagram, model)
        edge = [e for e in d._cells.values() if e["kind"] == "edge" and e.get("source") == "vm-one"][0]
        self.assertEqual(edge["target"], "subnet-sn-one-rt")   # app row is laid out before mgmt

    def test_a_badged_subnet_reserves_title_width_for_its_badges(self):
        """A27: the recipe never emits a subnet whose title runs under its corner badges."""
        long_name = "sn-shared-services-management"
        model = {"subject": "reserve", "region": "us-ashburn-1", "vcns": [{
            "name": "a", "cidr": "10.0.0.0/16", "services": [], "gateways": [], "subnets": [
                {"name": long_name, "cidr": "10.0.240.0/24", "tier": "mgmt",
                 "route_table": "rt-mgmt", "security_lists": ["sl-mgmt"],
                 "items": [{"icon": "vm", "label": "Ops", "address": "ops"}]}]}]}
        d = quiet(ol.build_diagram, model)
        _, _, sw, _ = d.bbox(f"subnet-{long_name}")            # _slug() turns ':' into '-'
        title_w = ol._title_width(ol._subnet_title_lines(model["vcns"][0]["subnets"][0]), d.profile["subnet_font"])
        self.assertGreaterEqual(sw - db.BADGE_RESERVE, title_w)
        self.assertEqual([m for m in d.validate() if "its badges leave" in m], [])

class LabelModeTests(unittest.TestCase):
    PUB = {"name": "sn-web", "cidr": "10.0.1.0/24", "tier": "lb", "public": True, "items": []}
    PRIV = {"name": "sn-app", "cidr": "10.0.2.0/24", "tier": "app", "public": False, "items": []}
    BARE = {"name": "sn-mgmt", "cidr": "10.0.3.0/24", "tier": "mgmt", "items": []}

    def test_two_line_label_marks_public_and_private(self):
        self.assertEqual(ol._subnet_label(self.PUB),
                         'sn-web (Public)<br><font style="font-size: 10px; font-weight: normal"'
                         ' color="#312D2A">10.0.1.0/24</font>')
        self.assertIn("sn-app (Private)<br>", ol._subnet_label(self.PRIV))

    def test_a_subnet_without_a_public_key_carries_no_token(self):
        label = ol._subnet_label(self.BARE)
        self.assertTrue(label.startswith("sn-mgmt<br>"), label)
        self.assertNotIn("Public", label)
        self.assertNotIn("Private", label)

    def test_inline_mode_reproduces_the_130_string(self):
        self.assertEqual(ol._subnet_label(self.PUB, "inline"), "sn-web (10.0.1.0/24) - public")
        self.assertEqual(ol._subnet_label(self.PRIV, "inline"), "sn-app (10.0.2.0/24)")
        self.assertEqual(ol._vcn_label({"name": "hub", "cidr": "10.0.0.0/16"}, "inline"),
                         "VCN: hub (10.0.0.0/16)")

    def test_the_vcn_cidr_moves_to_line_2(self):
        self.assertEqual(ol._vcn_label({"name": "hub", "cidr": "10.0.0.0/16"}),
                         'VCN: hub<br><font style="font-size: 10px; font-weight: normal"'
                         ' color="#312D2A">10.0.0.0/16</font>')
        self.assertEqual(ol._vcn_label({"name": "hub"}), "VCN: hub")

    def test_a_badged_subnets_title_width_is_measured_per_line(self):
        """The two-line form is narrower than the inline one, so the subnet may be narrower."""
        d = db.DrawioBuilder()
        badged = dict(self.PUB, route_table="rt-web", security_lists=["sl-web"])
        self.assertLess(ol._subnet_min_w(badged, d), ol._subnet_min_w(badged, d, "inline"))
        self.assertEqual(ol._subnet_title_lines(badged), ["sn-web (Public)", "10.0.1.0/24"])
        self.assertEqual(ol._subnet_title_lines(badged, "inline"), ["sn-web (10.0.1.0/24) - public"])

    def test_the_two_line_title_is_emitted_as_html_and_validates(self):
        model = {"subject": "labels", "region": "us-ashburn-1", "locations": "nested",
                 "vcns": [{"name": "hub", "cidr": "10.0.0.0/16",
                           "subnets": [dict(self.PUB, route_table="rt-web", security_lists=["sl-web"],
                                            items=[{"icon": "load_balancer", "label": "LB", "address": "lb"}]),
                                       dict(self.PRIV, items=[{"icon": "vm", "label": "App", "address": "app"}])]}]}
        d = quiet(ol.build_diagram, model)
        self.assertIn("(Public)", d._cells["subnet-sn-web"]["label"])
        self.assertIn("<br>", d._cells["subnet-sn-web"]["label"])
        self.assertEqual(errors_of(d), [])
        self.assertEqual(quiet(d.check_overlaps, True), [])

    def test_the_inline_mode_flag_reaches_the_cells(self):
        model = {"subject": "labels", "region": "us-ashburn-1", "locations": "nested",
                 "subnet_label": "inline",
                 "vcns": [{"name": "hub", "cidr": "10.0.0.0/16", "subnets": [
                     dict(self.PRIV, items=[{"icon": "vm", "label": "App", "address": "app"}])]}]}
        d = quiet(ol.build_diagram, model)
        self.assertEqual(d._cells["subnet-sn-app"]["label"], "sn-app (10.0.2.0/24)")
        self.assertEqual(d._cells["vcn-hub"]["label"], "VCN: hub (10.0.0.0/16)")


class LegendRowTests(unittest.TestCase):
    MODEL = {"subject": "legend", "region": "us-ashburn-1", "locations": "nested",
             "vcns": [{"name": "a", "cidr": "10.0.0.0/16", "subnets": [
                 {"name": "sn-app", "cidr": "10.0.1.0/24", "tier": "app", "public": False,
                  "route_table": "rt-app", "security_lists": ["sl-app"],
                  "items": [{"icon": "vm", "label": "App", "address": "app", "nsgs": ["nsg-app"]}]}]}]}

    def _legend_texts(self, d):
        gid = next(cid for cid, e in d._cells.items()
                   if e["kind"] == "group" and e.get("label") == "Legend")
        return [e["label"] for cid, e in d._cells.items()
                if e["parent"] == gid and e["kind"] == "text"]

    def test_badge_rows_appear_only_for_the_badges_that_exist(self):
        d = quiet(ol.build_diagram, self.MODEL, legend=True)
        texts = self._legend_texts(d)
        self.assertEqual(texts[-3:], ["Route table", "Security list", "Network security group"])
        self.assertEqual(errors_of(d), [])

    def test_a_model_without_badges_keeps_the_eight_default_rows(self):
        model = copy.deepcopy(self.MODEL)
        sn = model["vcns"][0]["subnets"][0]
        sn.pop("route_table"), sn.pop("security_lists"), sn["items"][0].pop("nsgs")
        texts = self._legend_texts(quiet(ol.build_diagram, model, legend=True))
        self.assertEqual(len(texts), 8)
        self.assertEqual(texts[3], "Attachment (structural)")

    def test_the_attachment_row_names_the_active_form(self):
        d = quiet(ol.build_diagram, dict(self.MODEL, attachment_style="dotted"), legend=True)
        self.assertEqual(self._legend_texts(d)[3], "Attachment / association (structural)")
        self.assertEqual(d.attachment_style, "dotted")

    def test_attachment_edges_follow_the_models_attachment_style(self):
        model = dict(self.MODEL, attachment_style="dotted",
                     drgs=[{"name": "drg", "address": "drg", "label": "DRG\ndrg", "attachments": [
                         {"type": "vcn", "vcn": "a", "address": "att-a", "label": "VCN attachment\na"}]}])
        d = quiet(ol.build_diagram, model)
        edge = next(e for cid, e in d._cells.items() if e["kind"] == "edge" and e.get("source") == "att-a")
        style = next(el.get("style") for el in d.root.iter("mxCell")
                     if el.get("id") == next(cid for cid, e in d._cells.items() if e is edge))
        self.assertIn("dashPattern=1 3", style)
        self.assertIn("endArrow=none", style)

    def test_the_build_diagram_keyword_overrides_the_model(self):
        d = quiet(ol.build_diagram, self.MODEL, attachment_style="dotted")
        self.assertEqual(d.attachment_style, "dotted")
        self.assertEqual(quiet(ol.build_diagram, self.MODEL).attachment_style, "solid")


CANVAS_HYBRID = {
    "subject": "canvas", "region": "eu-frankfurt-1", "region_label": "Frankfurt",
    "hub": {"name": "On-Premises",
            "items": [{"icon": "cpe", "type": "oci_core_cpe", "label": "cpe-hq", "address": "cpe"}]},
    "drgs": [{"name": "drg", "address": "drg", "label": "DRG\ndrg", "attachments": [
        {"type": "vcn", "vcn": "hub", "address": "att-hub", "label": "VCN attachment\nhub"},
        {"type": "ipsec", "target": "cpe", "address": "att-vpn", "label": "IPSec attachment"}]}],
    "vcns": [{"name": "hub", "cidr": "10.0.0.0/16", "subnets": [
        {"name": "sn-lb", "cidr": "10.0.1.0/24", "tier": "lb", "public": True,
         "items": [{"icon": "load_balancer", "label": "LB", "address": "lb"}]},
        {"name": "sn-app", "cidr": "10.0.2.0/24", "tier": "app", "public": False,
         "items": [{"icon": "vm", "label": "App", "address": "app"}]}],
        "gateways": [gw("igw", "internet_gateway", "Internet\nGateway", "igw"),
                     gw("nat", "nat_gateway", "NAT\nGateway", "nat"),
                     gw("sgw", "service_gateway", "Service\nGateway", "sgw")],
        "services": [{"icon": "buckets", "label": "Object Storage", "address": "buckets"}]}],
}


class LocationCanvasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = quiet(ol.build_diagram, CANVAS_HYBRID)

    def test_the_location_boxes_are_page_level_siblings_of_the_region(self):
        for cid in ("hub", "internet", "region"):
            self.assertEqual(self.d._cells[cid]["parent"], "1", cid)
        self.assertEqual(errors_of(self.d), [])

    def test_the_region_is_shifted_right_by_the_left_column(self):
        rx, _ry, _rw, _rh = self.d.abs_bbox("region")
        hx, _hy, hw, _hh = self.d.abs_bbox("hub")
        self.assertEqual(hx, ol.REGION_XY[0])
        self.assertEqual(hw, ol.LOC_W)
        self.assertGreaterEqual(rx - (hx + hw), ol.LOC_GAP_MIN)

    def test_the_internet_box_hugs_the_regions_right_edge(self):
        rx, ry, rw, rh = self.d.abs_bbox("region")
        ix, iy, iw, ih = self.d.abs_bbox("internet")
        self.assertEqual(ix - (rx + rw), ol.LOC_GAP_RIGHT)
        self.assertEqual((iy, ih, iw), (ry, rh, ol.LOC_W))

    def test_the_right_column_splits_the_region_height_with_a_third_party_box(self):
        model = copy.deepcopy(CANVAS_HYBRID)
        model["third_party"] = [{"name": "3rd Party Cloud",
                                 "items": [{"icon": "cloud", "label": "Partner SaaS", "address": "saas"}]}]
        d = quiet(ol.build_diagram, model)
        _rx, ry, _rw, rh = d.abs_bbox("region")
        _ix, iy, _iw, ih = d.abs_bbox("internet")
        _tx, ty, _tw, th = d.abs_bbox("thirdparty-0")
        self.assertEqual(iy, ry)
        self.assertEqual(ty, iy + ih + ol.LOC_STACK_GAP)
        self.assertEqual(ih + ol.LOC_STACK_GAP + th, rh)
        self.assertEqual(ih, round((rh - ol.LOC_STACK_GAP) * ol.INTERNET_SPLIT))
        self.assertEqual(errors_of(d), [])

    def test_a_right_column_that_does_not_fit_grows_the_region_and_recentres_it(self):
        """Decision 6: the boxes are floored at their own minimum first, then the region grows
        and every region child moves down by half the growth, so the VCN stack stays centred.

        One 3rd Party box carries an item, so the floor path is exercised with content: a box
        with items needs HUB_ICON_Y0 + one icon footprint + PAD, not the bare LOC_MIN_H.
        """
        model = copy.deepcopy(CANVAS_HYBRID)
        model["third_party"] = [
            {"name": "3rd Party Cloud",
             "items": [{"icon": "cloud", "label": "Partner SaaS", "address": "saas"}]},
            {"name": "Partner Cloud", "items": []}]
        small = quiet(ol.build_diagram, CANVAS_HYBRID)
        d = quiet(ol.build_diagram, model)
        _rx, ry, _rw, rh = d.abs_bbox("region")
        with_items = ol.HUB_ICON_Y0 + db.ICON_FOOTPRINT_H + ol.PAD
        self.assertGreater(with_items, ol.LOC_MIN_H)
        mins = [ol.LOC_MIN_H, with_items, ol.LOC_MIN_H]
        need = sum(mins) + 2 * ol.LOC_STACK_GAP
        self.assertEqual(rh, max(need, small.abs_bbox("region")[3]))
        heights = [d.abs_bbox(cid)[3] for cid in ("internet", "thirdparty-0", "thirdparty-1")]
        self.assertTrue(all(h >= m for h, m in zip(heights, mins)), heights)
        self.assertEqual(sum(heights) + 2 * ol.LOC_STACK_GAP, rh)
        vy = d.abs_bbox("vcn-hub")[1] - ry
        self.assertEqual(vy, ol.VCN_Y + (rh - small.abs_bbox("region")[3]) // 2)
        self.assertEqual(errors_of(d), [])
        self.assertEqual(quiet(d.check_overlaps, True), [])

    def test_every_right_column_box_with_items_clears_its_own_content(self):
        """Regression: a box floored at LOC_MIN_H = 160 spilled a one-icon caption (bottom 212)
        outside itself, which validate() reports as a blocking containment error."""
        model = copy.deepcopy(CANVAS_HYBRID)
        model["internet"] = {"items": [{"icon": "user", "label": "Users", "address": "users"}]}
        model["third_party"] = [
            {"name": "3rd Party Cloud",
             "items": [{"icon": "cloud", "label": "Partner SaaS", "address": "saas"}]},
            {"name": "Partner Cloud",
             "items": [{"icon": "cloud", "label": "Other SaaS", "address": "other"}]}]
        d = quiet(ol.build_diagram, model)
        _rx, _ry, _rw, rh = d.abs_bbox("region")
        heights = [d.abs_bbox(cid)[3] for cid in ("internet", "thirdparty-0", "thirdparty-1")]
        floor = ol.HUB_ICON_Y0 + db.ICON_FOOTPRINT_H + ol.PAD
        self.assertTrue(all(h >= floor for h in heights), heights)
        self.assertEqual(sum(heights) + 2 * ol.LOC_STACK_GAP, rh)
        self.assertEqual(errors_of(d), [])
        self.assertEqual(quiet(d.check_overlaps, True), [])

    def test_the_cpe_straddles_the_on_premises_region_facing_border(self):
        """Decision 5 / toolkit Template 1: the CPE's glyph centre sits on the box's right edge."""
        hx, _hy, hw, _hh = self.d.abs_bbox("hub")
        cx, _cy, _cw, _ch = self.d.abs_bbox("cpe")
        self.assertEqual(cx + ol.GW_SIDE_DX, hx + hw)
        caption = self.d._cells["cpe"]["label_id"]
        self.assertEqual(style_of(self.d, caption)["fillColor"], db.COLORS["region_fill"])

    def test_a_non_on_premises_hub_item_keeps_the_centred_column(self):
        model = copy.deepcopy(CANVAS_HYBRID)
        model["hub"]["items"].append({"icon": "rpg", "label": "RPC peer", "address": "rpc"})
        d = quiet(ol.build_diagram, model)
        hx, _hy, hw, _hh = d.abs_bbox("hub")
        self.assertEqual(d.abs_bbox("rpc")[0] - hx, round((ol.LOC_W - db.ICON_W) / 2 / 10) * 10)
        self.assertEqual(d.abs_bbox("cpe")[0] + ol.GW_SIDE_DX, hx + hw)
        self.assertEqual(errors_of(d), [])

    def test_the_hybrid_label_edge_crosses_the_region_border(self):
        eid = next(cid for cid, e in self.d._cells.items()
                   if e["kind"] == "edge" and e.get("source") == "att-vpn")
        self.assertEqual(self.d._cells[eid]["label"], "Site-to-Site VPN")
        self.assertEqual(self.d._cells[eid]["target"], "cpe")
        self.assertEqual(self.d._cells[eid]["parent"], "1")       # common ancestor of region and hub

    def test_nested_mode_reproduces_the_130_canvas(self):
        d = quiet(ol.build_diagram, dict(CANVAS_HYBRID, locations="nested"))
        self.assertEqual(d._cells["hub"]["parent"], "region")
        self.assertEqual(d._cells["hub"]["x"], ol.HUB_X)
        self.assertNotIn("internet", d._cells)
        self.assertEqual(d.abs_bbox("region")[0], ol.REGION_XY[0])
        self.assertEqual(errors_of(d), [])

    def test_no_internet_box_without_an_igw(self):
        model = copy.deepcopy(CANVAS_HYBRID)
        model["vcns"][0]["gateways"] = [gw("sgw", "service_gateway", "Service\nGateway", "sgw")]
        d = quiet(ol.build_diagram, model)
        self.assertNotIn("internet", d._cells)
        # the gutter holds the hybrid label AND the half slot the straddling CPE
        # pushes out of the On-Premises box (decision 5)
        gap = (max(ol.LOC_GAP_MIN, ol._hub_gutter(model["drgs"], d.profile["edge_font"]))
               + db.ICON_W - ol.GW_SIDE_DX)
        self.assertEqual(d.abs_bbox("region")[0], ol.REGION_XY[0] + ol.LOC_W + gap)

    def test_the_canvas_passes_the_strict_gate(self):
        self.assertEqual(quiet(self.d.check_overlaps, True), [])


class GatewayEdgeTests(unittest.TestCase):
    def _model(self, **kw):
        model = copy.deepcopy(CANVAS_HYBRID)
        model.update(kw)
        return model

    def test_igw_over_nat_on_the_internet_facing_border(self):
        """G4 / B01: the right border faces the Internet box; IGW slot 0, NAT slot 1."""
        d = quiet(ol.build_diagram, CANVAS_HYBRID)
        vx, vy, vw, _vh = d.abs_bbox("vcn-hub")
        for slot, cid in enumerate(("igw", "nat")):
            x, y, _w, _h = d.abs_bbox(cid)
            self.assertEqual(x + ol.GW_SIDE_DX, vx + vw, cid)
            self.assertEqual(y, vy + ol.SIDE_GW_Y0 + slot * ol.SIDE_GW_PITCH, cid)
        self.assertEqual(errors_of(d), [])

    def test_the_service_gateway_faces_the_osn_band(self):
        """G5: with the OSN below the stack the SGW moves to the VCN's bottom border."""
        d = quiet(ol.build_diagram, CANVAS_HYBRID)
        vx, vy, _vw, vh = d.abs_bbox("vcn-hub")
        sx, sy, _sw, _sh = d.abs_bbox("sgw")
        self.assertEqual(sy + ol.GW_STRADDLE, vy + vh)
        self.assertEqual(sx, vx + ol.PAD)
        ox, oy, ow, _oh = d.abs_bbox("osn")
        self.assertGreaterEqual(oy, vy + vh + ol.OSN_BAND_GAP - 1)
        self.assertLessEqual(ox, vx)
        self.assertGreaterEqual(ox + ow, vx)            # the band spans the stack
        edges = [e for e in d._cells.values() if e["kind"] == "edge" and e.get("source") == "sgw"]
        self.assertEqual([e["target"] for e in edges], ["osn"])

    def test_gateway_edge_top_puts_the_igw_in_the_rightmost_top_slot(self):
        d = quiet(ol.build_diagram, self._model(gateway_edge="top"))
        vx, vy, vw, _vh = d.abs_bbox("vcn-hub")
        ix, iy, _iw, _ih = d.abs_bbox("igw")
        nx, ny, _nw, _nh = d.abs_bbox("nat")
        self.assertEqual(iy + ol.GW_STRADDLE, vy)
        self.assertEqual(ix, vx + vw - ol.TOP_GW_X0 - db.ICON_W)
        self.assertEqual(ny, iy)
        self.assertEqual(ix - nx, ol.GW_PITCH)
        caption = d._cells["igw"]["label_id"]
        self.assertLess(d._cells[caption]["y"], d._cells["igw"]["y"])
        self.assertEqual(style_of(d, caption)["fillColor"], db.COLORS["region_fill"])
        self.assertEqual(errors_of(d), [])
        self.assertEqual(quiet(d.check_overlaps, True), [])

    def test_a_top_border_gateway_never_covers_the_vcns_own_title(self):
        """Top slots are counted from the right edge, so the VCN must also be
        wide enough for its own title band: a container title is not a cell, so
        validate() cannot see a glyph sitting on top of it."""
        narrow = self._two_column_model()
        # the narrowest hub there is: one small subnet, no services panel, so
        # nothing but the reservation itself can widen the box
        narrow["vcns"][0]["subnets"] = narrow["vcns"][0]["subnets"][:1]
        narrow["vcns"][0].pop("services", None)
        for label, model in (("explicit", self._model(gateway_edge="top")),
                             ("auto", self._two_column_model()),
                             ("narrow", narrow)):
            d = quiet(ol.build_diagram, model)
            vcn = model["vcns"][0]
            vx, vy, _vw, _vh = d.abs_bbox("vcn-" + vcn["name"])
            title_right = vx + d.profile["spacing_left"] + ol._vcn_title_w(vcn, d)
            tops = [cid for cid in ("igw", "nat")
                    if abs(d.abs_bbox(cid)[1] + ol.GW_STRADDLE - vy) < 0.5]
            self.assertEqual(tops, ["igw", "nat"], label)
            for cid in tops:
                self.assertGreaterEqual(d.abs_bbox(cid)[0], title_right, (label, cid))
            self.assertEqual(errors_of(d), [], label)
            self.assertEqual(quiet(d.check_overlaps, True), [], label)

    def test_a_long_vcn_name_widens_the_vcn_under_its_top_gateways(self):
        """The reservation is measured, not a constant: a longer title pushes
        the top-border slots further right and the VCN box out with them."""
        short = quiet(ol.build_diagram, self._model(gateway_edge="top"))
        long_model = self._model(gateway_edge="top")
        long_model["vcns"][0]["name"] = "hub-with-a-very-long-display-name"
        long_d = quiet(ol.build_diagram, long_model)
        wide = long_d.abs_bbox("vcn-hub-with-a-very-long-display-name")[2]
        self.assertGreater(wide, short.abs_bbox("vcn-hub")[2])
        self.assertEqual(errors_of(long_d), [])

    def test_gateway_edge_bottom_restores_the_130_choice(self):
        d = quiet(ol.build_diagram, self._model(gateway_edge="bottom"))
        vx, vy, _vw, vh = d.abs_bbox("vcn-hub")
        for slot, cid in enumerate(("igw", "nat", "sgw")):
            x, y, _w, _h = d.abs_bbox(cid)
            self.assertEqual(y + ol.GW_STRADDLE, vy + vh, cid)
            self.assertEqual(x, vx + ol.PAD + slot * ol.GW_PITCH, cid)

    def test_a_per_gateway_side_wins(self):
        model = self._model()
        model["vcns"][0]["gateways"][0]["side"] = "left"
        d = quiet(ol.build_diagram, model)
        vx, vy, _vw, _vh = d.abs_bbox("vcn-hub")
        self.assertEqual(d.abs_bbox("igw")[0] + ol.GW_SIDE_DX - 1, vx)
        self.assertEqual(d.abs_bbox("nat")[1], vy + ol.SIDE_GW_Y0)      # NAT is now slot 0 on the right

    def test_an_unknown_side_raises(self):
        model = self._model()
        model["vcns"][0]["gateways"][0]["side"] = "sideways"
        with self.assertRaises(ValueError) as cm:
            quiet(ol.build_diagram, model)
        self.assertIn("side", str(cm.exception))

    def test_the_order_is_igw_nat_sgw_lpg_whatever_the_model_says(self):
        model = self._model(gateway_edge="bottom")
        model["vcns"][0]["gateways"] = list(reversed(model["vcns"][0]["gateways"]))
        d = quiet(ol.build_diagram, model)
        vx = d.abs_bbox("vcn-hub")[0]
        xs = [d.abs_bbox(cid)[0] - vx for cid in ("igw", "nat", "sgw")]
        self.assertEqual(xs, sorted(xs))
        self.assertEqual(xs[0], ol.PAD)

    def test_the_130_three_argument_call_is_unchanged(self):
        self.assertEqual(ol._gateway_side(gw("igw", "internet_gateway", "x", "i"), 0, {}), "bottom")
        self.assertEqual(ol._gateway_side(gw("sgw", "service_gateway", "x", "s"), 0, {}), "right")

    def _two_column_model(self):
        """The hub-and-spoke shape: the hub column's IGW / NAT take the top border."""
        model = self._model()
        model["vcns"].append({"name": "spoke", "cidr": "10.1.0.0/16", "subnets": [
            {"name": "sn-web", "cidr": "10.1.1.0/24", "tier": "lb", "public": True,
             "items": [{"icon": "vm", "label": "Web", "address": "web2"}]}],
            "gateways": [gw("igw", "internet_gateway", "Internet\nGateway", "igw2")]})
        return model

    def test_only_the_rightmost_column_faces_the_internet_box_on_its_right_border(self):
        """G4: a left-hand column's right border faces the next VCN, so its
        Internet-facing gateways take the top border instead."""
        model = self._two_column_model()
        d = quiet(ol.build_diagram, model)
        hx, hy, hw, _hh = d.abs_bbox("vcn-hub")
        sx, _sy, sw, _sh = d.abs_bbox("vcn-spoke")
        self.assertEqual(d.abs_bbox("igw")[1] + ol.GW_STRADDLE, hy)            # hub: top border
        self.assertEqual(d.abs_bbox("igw")[0], hx + hw - ol.TOP_GW_X0 - db.ICON_W)
        self.assertEqual(d.abs_bbox("nat")[1] + ol.GW_STRADDLE, hy)
        self.assertEqual(d.abs_bbox("igw2")[0] + ol.GW_SIDE_DX, sx + sw)       # spoke: right border
        self.assertEqual(errors_of(d), [])

    def test_the_igw_internet_connector_does_not_ride_a_vcn_border(self):
        """A top-border IGW's docking point sits exactly on the VCN border
        line, so the lattice offers a free lane along every other VCN's top
        border at the same y. The connector must leave that lane."""
        d = quiet(ol.build_diagram, self._two_column_model())
        d.validate()
        poly = d._cells["igw-internet"]["polyline"]
        self.assertTrue(poly)
        for cid in ("vcn-hub", "vcn-spoke"):
            vx, vy, vw, vh = d.abs_bbox(cid)
            for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
                if abs(y0 - y1) > 0.01:
                    continue                                    # vertical run
                rides = min(abs(y0 - vy), abs(y0 - (vy + vh))) <= db.STRADDLE_TOL
                overlaps = min(x0, x1) < vx + vw and max(x0, x1) > vx
                self.assertFalse(rides and overlaps,
                                 f"{(x0, y0)}->{(x1, y1)} rides a border of {cid}")

    def test_every_igw_is_tied_to_the_internet_box(self):
        """One attachment connector per IGW, mirroring SGW -> OSN."""
        d = quiet(ol.build_diagram, CANVAS_HYBRID)
        edges = [e for e in d._cells.values()
                 if e["kind"] == "edge" and e.get("source") == "igw"]
        self.assertEqual([e["target"] for e in edges], ["internet"])
        self.assertEqual([e["label"] for e in edges], [""])
        self.assertIn("igw-internet", d._cells)
        nested = quiet(ol.build_diagram, self._model(locations="nested"))
        self.assertEqual([e for e in nested._cells.values()
                          if e["kind"] == "edge" and e.get("source") == "igw"], [])

    def test_nested_mode_keeps_the_130_sides_and_the_osn_column(self):
        d = quiet(ol.build_diagram, self._model(locations="nested"))
        vx, vy, vw, vh = d.abs_bbox("vcn-hub")
        self.assertEqual(d.abs_bbox("igw")[1] + ol.GW_STRADDLE, vy + vh)
        self.assertEqual(d.abs_bbox("sgw")[0] + ol.GW_SIDE_DX, vx + vw)
        self.assertGreater(d.abs_bbox("osn")[0], vx + vw)
        self.assertEqual(errors_of(d), [])


class OsnBandClearanceTests(unittest.TestCase):
    """G5: the band clears every region child above it and never runs under the DRG column."""

    def _hub_model(self, attachments):
        return {"subject": "hub", "region": "us-ashburn-1",
                "drgs": [{"name": "hub-drg", "address": "drg", "attachments": [
                    {"type": "vcn", "vcn": "hub", "address": "att-%d" % i,
                     "label": "VCN attachment\nspoke%d" % i} for i in range(attachments)]}],
                "vcns": [{"name": "hub", "cidr": "10.0.0.0/16", "subnets": [
                    {"name": "sn-lb", "cidr": "10.0.1.0/24", "tier": "lb", "public": True,
                     "items": [{"icon": "load_balancer", "label": "LB", "address": "lb"}]}],
                    "gateways": [gw("igw", "internet_gateway", "Internet\nGateway", "igw"),
                                 gw("sgw", "service_gateway", "Service\nGateway", "sgw")]}],
                "services": [svc("object_storage", "os")]}

    def test_the_band_starts_at_the_vcn_stack_not_at_the_region_padding(self):
        d = quiet(ol.build_diagram, self._hub_model(8))
        vx, _vy, _vw, _vh = d.abs_bbox("vcn-hub")
        ox, _oy, _ow, _oh = d.abs_bbox("osn")
        self.assertEqual(ox, vx)                       # never under the DRG column on its left
        self.assertEqual(errors_of(d), [])

    def test_a_drg_column_taller_than_the_stack_pushes_the_band_down(self):
        """A DRG cluster deeper than the tallest VCN used to be overlapped by the band."""
        d = quiet(ol.build_diagram, self._hub_model(8))
        _dx, dy, _dw, dh = d.abs_bbox("drgbox-drg")    # 8 attachments -> the box DRG style
        _vx, vy, _vw, vh = d.abs_bbox("vcn-hub")
        _ox, oy, _ow, _oh = d.abs_bbox("osn")
        self.assertGreater(dy + dh, vy + vh)           # the DRG really is the deepest child
        self.assertGreaterEqual(oy, dy + dh + ol.OSN_BAND_GAP)
        self.assertEqual(errors_of(d), [])

    def test_a_tall_region_services_panel_pushes_the_band_down(self):
        model = {"subject": "two", "region": "us-ashburn-1",
                 "vcns": [simple_vcn("a"), simple_vcn("b")],
                 "services": [svc("buckets", "s%d" % i, regional=False) for i in range(8)]
                             + [svc("object_storage", "reg")]}
        d = quiet(ol.build_diagram, model)
        _sx, sy, _sw, sh = d.abs_bbox("services")
        _vx, vy, _vw, vh = d.abs_bbox("vcn-a")
        _ox, oy, _ow, _oh = d.abs_bbox("osn")
        self.assertGreater(sy + sh, vy + vh)           # the panel is deeper than the VCN stack
        self.assertGreaterEqual(oy, sy + sh + ol.OSN_BAND_GAP)
        self.assertEqual(errors_of(d), [])


LANDING_ZONE = {
    "subject": "landing-zone", "region": "eu-frankfurt-1", "tenancy_name": "example-tenancy",
    "show_compartments": True,
    "compartments": [{"name": "Enclosing"},
                     {"name": "Network", "parent": "Enclosing", "vcns": ["hub"]},
                     {"name": "App", "parent": "Enclosing"}],
    "drgs": [{"name": "drg", "address": "drg", "label": "DRG\ndrg", "attachments": [
        {"type": "vcn", "vcn": "hub", "address": "att-hub", "label": "VCN attachment\nhub"},
        {"type": "vcn", "vcn": "spoke", "address": "att-spoke", "label": "VCN attachment\nspoke"}]}],
    "vcns": [
        {"name": "hub", "cidr": "10.0.0.0/16", "subnets": [
            {"name": "sn-web", "cidr": "10.0.1.0/24", "tier": "lb", "public": True,
             "items": [{"icon": "load_balancer", "label": "LB", "address": "lb"}]}],
         "gateways": [gw("igw", "internet_gateway", "Internet\nGateway", "igw"),
                      gw("sgw", "service_gateway", "Service\nGateway", "sgw")],
         "services": [{"icon": "buckets", "label": "Object Storage", "address": "buckets"}]},
        {"name": "spoke", "cidr": "10.1.0.0/16", "compartment": "App", "subnets": [
            {"name": "sn-app", "cidr": "10.1.1.0/24", "tier": "app", "public": False,
             "items": [{"icon": "vm", "label": "App VM", "address": "app"}]}]},
    ],
}


class CompartmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = quiet(ol.build_diagram, LANDING_ZONE)

    def test_each_vcn_and_its_gateways_are_children_of_their_compartment(self):
        self.assertEqual(self.d._cells["vcn-hub"]["parent"], "compartment-Network")
        self.assertEqual(self.d._cells["igw"]["parent"], "compartment-Network")
        self.assertEqual(self.d._cells["sgw"]["parent"], "compartment-Network")
        self.assertEqual(self.d._cells["vcn-spoke"]["parent"], "compartment-App")

    def test_compartments_nest_through_parent_and_the_tenancy_wraps_them(self):
        self.assertEqual(self.d._cells["compartment-Network"]["parent"], "compartment-Enclosing")
        self.assertEqual(self.d._cells["compartment-App"]["parent"], "compartment-Enclosing")
        self.assertEqual(self.d._cells["compartment-Enclosing"]["parent"], "tenancy")
        self.assertEqual(self.d._cells["tenancy"]["parent"], "region")
        self.assertEqual(self.d._cells["tenancy"]["label"],
                         "Tenancy: example-tenancy (Root Compartment)")

    def test_the_drg_column_stays_at_region_level(self):
        """Spec 6.3: the DRG column is shared by VCNs in different compartments."""
        self.assertEqual(self.d._cells["drg"]["parent"], "region")
        self.assertEqual(self.d._cells["att-hub"]["parent"], "region")
        self.assertEqual(self.d._cells["osn"]["parent"], "region")

    def test_the_compartment_encloses_its_vcn_with_its_padding(self):
        cx, cy, cw, ch = self.d.abs_bbox("compartment-Network")
        vx, vy, vw, vh = self.d.abs_bbox("vcn-hub")
        self.assertLessEqual(cx, vx - ol.CMP_PAD + ol.GW_SIDE_DX)
        # hub is not the rightmost column, so G4 puts its IGW on the TOP border:
        # the compartment clears that caption as well as its own title band
        self.assertEqual(vy - cy, ol.CMP_TITLE_H + ol.GW_STRADDLE + db.LABEL_GAP + db.LABEL_H)
        self.assertGreaterEqual(cx + cw, vx + vw)
        self.assertGreaterEqual(cy + ch, vy + vh)
        # the App compartment's VCN has no gateways: its title band is exactly CMP_TITLE_H
        _ax, ay, _aw, _ah = self.d.abs_bbox("compartment-App")
        _sx, sy, _sw, _sh = self.d.abs_bbox("vcn-spoke")
        self.assertEqual(sy - ay, ol.CMP_TITLE_H)

    def test_the_diagram_validates_and_no_two_compartments_overlap(self):
        self.assertEqual(errors_of(self.d), [])
        self.assertEqual(quiet(self.d.check_overlaps, True), [])

    def test_a_vcn_naming_no_known_compartment_stays_a_region_child(self):
        model = copy.deepcopy(LANDING_ZONE)
        model["vcns"][1]["compartment"] = "Missing"
        d = quiet(ol.build_diagram, model)
        self.assertEqual(d._cells["vcn-spoke"]["parent"], "region")
        self.assertNotIn("compartment-App", d._cells)
        self.assertEqual(errors_of(d), [])

    def test_compartments_are_off_by_default(self):
        model = copy.deepcopy(LANDING_ZONE)
        model.pop("show_compartments")
        d = quiet(ol.build_diagram, model)
        self.assertEqual(d._cells["vcn-hub"]["parent"], "region")
        self.assertNotIn("tenancy", d._cells)
        self.assertNotIn("compartment-Network", d._cells)

    @staticmethod
    def _interleaved(compartments, members):
        """Three VCN columns whose model order interleaves two compartments (a1, b1, a2)."""
        vcns = []
        for name in ("a1", "b1", "a2"):
            vcn = {"name": name, "cidr": "10.0.0.0/16",
                   "subnets": [{"name": "sn-%s" % name, "cidr": "10.0.1.0/24", "tier": "app",
                                "items": [{"icon": "vm", "label": "VM %s" % name,
                                           "address": "vm-%s" % name}]}]}
            if members.get(name):
                vcn["compartment"] = members[name]
            vcns.append(vcn)
        return {"subject": "landing-zone", "region": "eu-frankfurt-1",
                "tenancy_name": "example-tenancy", "show_compartments": True,
                "compartments": compartments, "vcns": vcns}

    def test_interleaved_compartment_members_become_contiguous_columns(self):
        """Spec 6.3: compartments take the column order of their first member.

        Terraform's VCN order is orthogonal to compartment membership, so a
        compartment whose members are not contiguous would be fitted around -
        and would swallow - the columns in between.
        """
        model = self._interleaved([{"name": "CA"}, {"name": "CB"}],
                                  {"a1": "CA", "b1": "CB", "a2": "CA"})
        d = quiet(ol.build_diagram, model)
        self.assertEqual(d._cells["vcn-a1"]["parent"], "compartment-CA")
        self.assertEqual(d._cells["vcn-a2"]["parent"], "compartment-CA")
        self.assertEqual(d._cells["vcn-b1"]["parent"], "compartment-CB")
        xs = [d.abs_bbox("vcn-%s" % n)[0] for n in ("a1", "a2", "b1")]
        self.assertEqual(xs, sorted(xs))
        self.assertEqual(errors_of(d), [])
        self.assertEqual(quiet(d.check_overlaps, True), [])

    def test_a_nested_compartment_row_keeps_its_children_contiguous(self):
        """The enclosing compartment's two children must not be split by a sibling."""
        model = self._interleaved([{"name": "Enclosing"},
                                   {"name": "Network", "parent": "Enclosing"},
                                   {"name": "Other"},
                                   {"name": "App", "parent": "Enclosing"}],
                                  {"a1": "Network", "b1": "Other", "a2": "App"})
        d = quiet(ol.build_diagram, model)
        self.assertEqual(d._cells["compartment-Network"]["parent"], "compartment-Enclosing")
        self.assertEqual(d._cells["compartment-App"]["parent"], "compartment-Enclosing")
        self.assertEqual(d._cells["compartment-Other"]["parent"], "tenancy")
        xs = [d.abs_bbox("vcn-%s" % n)[0] for n in ("a1", "a2", "b1")]
        self.assertEqual(xs, sorted(xs))
        self.assertEqual(errors_of(d), [])
        self.assertEqual(quiet(d.check_overlaps, True), [])

    def test_a_compartment_less_vcn_trails_the_boxed_columns(self):
        """Spec 6.3: 'VCNs with no compartment go in a trailing unboxed group'."""
        model = self._interleaved([{"name": "CA"}], {"a1": "CA", "a2": "CA"})
        d = quiet(ol.build_diagram, model)
        self.assertEqual(d._cells["vcn-b1"]["parent"], "region")
        tx, _ty, tw, _th = d.abs_bbox("tenancy")
        self.assertGreaterEqual(d.abs_bbox("vcn-b1")[0], tx + tw)
        xs = [d.abs_bbox("vcn-%s" % n)[0] for n in ("a1", "a2", "b1")]
        self.assertEqual(xs, sorted(xs))
        self.assertEqual(errors_of(d), [])
        self.assertEqual(quiet(d.check_overlaps, True), [])

    def test_a_cycle_in_the_compartment_list_raises(self):
        model = copy.deepcopy(LANDING_ZONE)
        model["compartments"] = [{"name": "A", "parent": "B", "vcns": ["hub"]},
                                 {"name": "B", "parent": "A"}]
        with self.assertRaises(ValueError) as cm:
            quiet(ol.build_diagram, model)
        self.assertIn("cycle", str(cm.exception))


OKE_MODEL = {
    "subject": "oke", "region": "eu-frankfurt-1", "locations": "nested",
    "vcns": [{"name": "app", "cidr": "10.0.0.0/16",
              "groups": [{"type": "tier", "label": "Application Tier",
                          "subnets": ["sn-app", "sn-api"], "key": "tier-app"}],
              "subnets": [
                  {"name": "sn-lb", "cidr": "10.0.0.0/24", "tier": "lb", "public": True,
                   "items": [{"icon": "load_balancer", "label": "Public LB", "address": "lb"}]},
                  {"name": "sn-app", "cidr": "10.0.1.0/24", "tier": "app", "public": False,
                   "route_table": "rt-app",
                   "groups": [{"type": "oke_cluster",
                               "label": "Container Engine for Kubernetes Cluster",
                               "items": ["oke-main", "np-a", "np-b"], "key": "oke-main-box"}],
                   "items": [{"icon": "oke", "label": "oke-main", "address": "oke-main",
                              "nsgs": ["nsg-oke"]},
                             {"icon": "vm", "label": "Node pool A", "address": "np-a"},
                             {"icon": "vm", "label": "Node pool B", "address": "np-b"}]},
                  {"name": "sn-api", "cidr": "10.0.2.0/24", "tier": "app", "public": False,
                   "items": [{"icon": "api_gateway", "label": "API Gateway", "address": "api"}]}]}],
    "edges": [{"source": "lb", "target": "oke-main-box", "label": "443", "kind": "data"}],
}


class GroupBoxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = quiet(ol.build_diagram, OKE_MODEL)

    def test_a_non_contiguous_vcn_group_is_refused(self):
        """G8: a band drawn round rows 1 and 3 would swallow row 2; say so in the model's terms."""
        model = copy.deepcopy(OKE_MODEL)
        model["vcns"][0]["groups"][0]["subnets"] = ["sn-lb", "sn-api"]
        with self.assertRaises(ValueError) as cm:
            quiet(ol.build_diagram, model)
        self.assertIn("would enclose", str(cm.exception))
        self.assertIn("list its members contiguously", str(cm.exception))

    def test_the_oke_box_encloses_and_reparents_exactly_its_members(self):
        for cid in ("oke-main", "np-a", "np-b"):
            self.assertEqual(self.d._cells[cid]["parent"], "oke-main-box", cid)
            self.assertEqual(self.d._cells[self.d._cells[cid]["label_id"]]["parent"], "oke-main-box")
        self.assertEqual(self.d._cells["oke-main-box"]["parent"], "subnet-sn-app")
        self.assertEqual(self.d._cells["oke-main-nsg"]["parent"], "oke-main-box")   # the badge follows its host
        self.assertEqual(style_of(self.d, "oke-main-box")["ociGroup"], "oke_cluster")

    def test_the_box_starts_below_the_subnets_title_strip(self):
        """Decision 7: GRP_TITLE_H is measured from the subnet's title, not from ROW1_Y."""
        gx, gy, _gw, _gh = self.d.bbox("oke-main-box")
        self.assertEqual(gy, db.ROW1_Y)
        icon_y = self.d.bbox("oke-main")[1] + gy          # slot y in the box + the box's y
        self.assertEqual(icon_y, db.ROW1_Y + ol.GRP_TITLE_H)
        self.assertEqual(gx, ol.PAD - ol.GRP_PAD)

    def test_the_subnet_grew_around_the_box(self):
        sx, sy, sw, sh = self.d.bbox("subnet-sn-app")
        gx, gy, gw, gh = self.d.bbox("oke-main-box")
        self.assertGreaterEqual(gx, 0)
        self.assertGreaterEqual(sw, gx + gw)
        self.assertGreaterEqual(sh, gy + gh)
        self.assertEqual(errors_of(self.d), [])

    def test_a_vcn_group_bands_whole_subnet_rows(self):
        self.assertEqual(self.d._cells["tier-app"]["parent"], "vcn-app")
        for cid in ("subnet-sn-app", "subnet-sn-api"):
            self.assertEqual(self.d._cells[cid]["parent"], "tier-app", cid)
        self.assertEqual(self.d._cells["subnet-sn-lb"]["parent"], "vcn-app")
        self.assertEqual(style_of(self.d, "tier-app")["ociGroup"], "tier")

    def test_an_edge_may_terminate_on_a_group_box(self):
        """G8 / slide 32: the load balancer connects to the OKE box, not to an icon inside it."""
        edges = [e for e in self.d._cells.values() if e["kind"] == "edge" and e.get("source") == "lb"]
        self.assertEqual([e["target"] for e in edges], ["oke-main-box"])

    def test_the_router_treats_the_box_as_a_container(self):
        """Decision 9: it is in the lattice's group set with a centred title obstacle."""
        groups, obstacles = self.d._routing_shapes(0)
        self.assertIn("oke-main-box", groups)
        title = obstacles["oke-main-box#title"]
        box = groups["oke-main-box"]
        self.assertAlmostEqual(title.cx, box.cx, delta=1.0)

    def test_a_member_that_is_not_in_the_container_raises(self):
        model = copy.deepcopy(OKE_MODEL)
        model["vcns"][0]["subnets"][1]["groups"][0]["items"].append("api")
        with self.assertRaises(ValueError) as cm:
            quiet(ol.build_diagram, model)
        self.assertIn("'api'", str(cm.exception))
        self.assertIn("not a member", str(cm.exception))

    def test_two_interleaving_groups_raise(self):
        model = copy.deepcopy(OKE_MODEL)
        model["vcns"][0]["subnets"][1]["groups"].append(
            {"type": "tier", "label": "Workers", "items": ["np-b"]})
        with self.assertRaises(ValueError) as cm:
            quiet(ol.build_diagram, model)
        self.assertIn("may not overlap", str(cm.exception))

    def test_the_grouped_diagram_passes_the_strict_gate(self):
        self.assertEqual(quiet(self.d.check_overlaps, True), [])


class DrgRouteTableTests(unittest.TestCase):
    def _model(self, route_table, **kw):
        model = {"subject": "drg-rt", "region": "eu-frankfurt-1", "locations": "nested",
                 "drgs": [{"name": "drg", "address": "drg", "label": "DRG\ndrg",
                           "route_table": route_table, "attachments": [
                               {"type": "vcn", "vcn": "hub", "address": "att-hub",
                                "label": "VCN attachment\nhub"}]}],
                 "vcns": [simple_vcn("hub")]}
        model.update(kw)
        return model

    def _multi_drg_model(self, count, route_table):
        """``count`` DRGs, each with one attachment and the same route tables."""
        return {"subject": "drg-rt", "region": "eu-frankfurt-1", "locations": "nested",
                "drgs": [{"name": f"drg{i}", "address": f"drg{i}", "label": f"DRG\ndrg{i}",
                          "route_table": route_table,
                          "attachments": [{"type": "vcn", "vcn": "hub", "address": f"att{i}",
                                           "label": "VCN attachment\nhub"}]}
                         for i in range(count)],
                "vcns": [simple_vcn("hub")]}

    def test_one_route_table_is_one_badge_under_the_drg_caption(self):
        d = quiet(ol.build_diagram, self._model({"name": "drg-rt-vcn", "address": "drg-rt-vcn"}))
        bx, by, bw, bh = d.bbox("drg-rt")
        slot_x, slot_y = d._cells["drg"]["slot_x"], d._cells["drg"]["slot_y"]
        self.assertEqual((bw, bh), (db.BADGE_SIZE, db.BADGE_SIZE))
        self.assertEqual(bx + bw / 2, slot_x + db.ICON_W / 2)
        self.assertEqual(by + bh / 2, slot_y + db.ICON_FOOTPRINT_H + ol.DRG_RT_GAP + db.BADGE_SIZE / 2)
        self.assertEqual(badge_style(d, "drg-rt")["ociHost"], "drg")
        self.assertNotIn("drg-rt2", d._cells)
        self.assertEqual(errors_of(d), [])

    def test_two_route_tables_render_as_a_two_glyph_strip(self):
        """Decision 8: Oracle creates one table for VCN attachments and one for the rest."""
        d = quiet(ol.build_diagram, self._model([{"name": "drg-rt-vcn", "address": "rt1"},
                                                 {"name": "drg-rt-other", "address": "rt2"}]))
        first, second = d.bbox("drg-rt"), d.bbox("drg-rt2")
        self.assertEqual(second[0] - first[0], db.BADGE_SIZE + db.BADGE_GAP)
        self.assertEqual(first[1], second[1])
        strip_cx = (first[0] + second[0] + db.BADGE_SIZE) / 2
        self.assertEqual(strip_cx, d._cells["drg"]["slot_x"] + db.ICON_W / 2)
        self.assertEqual(errors_of(d), [])
        self.assertEqual(quiet(d.check_overlaps, True), [])

    def test_a_third_route_table_is_dropped_with_a_warning(self):
        d = quiet(ol.build_diagram, self._model(["a", "b", "c"]))
        self.assertNotIn("drg-rt3", d._cells)
        self.assertIn("WARNING: DRG 'drg' has 3 route tables; only the first 2 are drawn",
                      d.layout_info["warnings"])

    def test_a_dropped_route_table_is_named_in_the_first_badges_metadata(self):
        """Spec 6.6: the stderr warning is gone by the time anyone reads the .drawio."""
        d = quiet(ol.build_diagram, self._model(["a", "b", "c", "d"]))
        meta = {el.get("id"): el.attrib for el in d.root if el.tag == "object"}
        self.assertEqual(meta["drg-rt"].get("dropped_route_tables"), "c, d")
        self.assertEqual(meta["drg-rt"].get("drg_route_table"), "a")
        self.assertNotIn("dropped_route_tables", meta["drg-rt2"])

    def test_no_dropped_metadata_when_every_route_table_is_drawn(self):
        d = quiet(ol.build_diagram, self._model(["a", "b"]))
        meta = {el.get("id"): el.attrib for el in d.root if el.tag == "object"}
        self.assertNotIn("dropped_route_tables", meta["drg-rt"])
        self.assertNotIn("dropped_route_tables", meta["drg-rt2"])

    def test_the_region_is_floored_under_the_strip_of_the_lowest_drg(self):
        """With 2+ DRGs the DRG column is the region's tallest child; fit_to_children
        ignores badges, so the region has to reserve the strip's height itself."""
        for count in (2, 3):
            for style in ("icon", "box"):
                with self.subTest(drgs=count, drg_style=style):
                    d = quiet(ol.build_diagram,
                              self._multi_drg_model(count, [{"name": "rt-vcn", "address": "rtv"},
                                                            {"name": "rt-other", "address": "rto"}]),
                              drg_style=style)
                    rx, ry, rw, rh = d.abs_bbox("region")
                    for i in range(count):
                        for suffix in ("-rt", "-rt2"):
                            bx, by, bw, bh = d.abs_bbox(f"drg{i}{suffix}")
                            self.assertGreaterEqual(by, ry)
                            self.assertLessEqual(by + bh, ry + rh)
                            self.assertGreaterEqual(bx, rx)
                            self.assertLessEqual(bx + bw, rx + rw)
                    self.assertEqual(errors_of(d), [])
                    self.assertEqual(quiet(d.check_overlaps, True), [])

    def test_the_badge_is_hosted_by_the_drg_and_carries_the_names_in_its_tooltip(self):
        d = quiet(ol.build_diagram, self._model({"name": "drg-rt-vcn", "address": "drg-rt-vcn"}))
        self.assertEqual(d._cells["drg-rt"]["host"], "drg")
        # the registry does not copy the <object> wrapper's tooltip, so read it
        # off the wrapper itself (as BadgeLayoutTests does)
        tips = {el.get("id"): el.get("tooltip") for el in d.root
                if el.tag == "object" and el.get("tooltip")}
        self.assertIn("drg-rt-vcn", tips.get("drg-rt", ""))

    def test_the_legend_gains_a_drg_route_table_row(self):
        d = quiet(ol.build_diagram, self._model("drg-rt-vcn"), legend=True)
        gid = next(cid for cid, e in d._cells.items()
                   if e["kind"] == "group" and e.get("label") == "Legend")
        texts = [e["label"] for e in d._cells.values() if e["parent"] == gid and e["kind"] == "text"]
        self.assertEqual(texts[-1], "DRG route table")

    def test_the_box_style_keeps_the_badge_inside_the_drg_group(self):
        d = quiet(ol.build_diagram, self._model("drg-rt-vcn"), drg_style="box")
        self.assertEqual(d._cells["drg-rt"]["parent"], d._cells["drg"]["parent"])
        self.assertTrue(d._cells["drg"]["parent"].startswith("drgbox"))
        _bx, by, _bw, bh = d.bbox("drg-rt")
        _gx, _gy, _gw, gh = d.bbox(d._cells["drg"]["parent"])
        self.assertLessEqual(by + bh, gh)                  # the strip is inside the box
        self.assertEqual(errors_of(d), [])

    def test_the_cluster_grew_so_the_attachment_stack_stays_centred(self):
        without = ol._drg_cluster_geometry({"attachments": []}, "icon")
        with_rt = ol._drg_cluster_geometry({"attachments": [], "route_table": "rt"}, "icon")
        self.assertEqual(with_rt["cluster_h"] - without["cluster_h"], ol.DRG_RT_GAP + db.BADGE_SIZE)
        self.assertEqual(len(with_rt["rt"]), 1)


if __name__ == "__main__":
    unittest.main()
