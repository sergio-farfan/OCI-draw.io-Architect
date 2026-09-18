"""Layout tests for scripts/oci_layout.py (v1.3.0 topology-aware placement)."""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
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


def errors_of(d):
    return [m for m in d.validate() if not m.split("] ")[-1].startswith("WARNING")]


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
    "subject": "gw", "region": "us-ashburn-1",
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


class LpgSideTests(unittest.TestCase):
    def _model(self, peer_a="lpg-b", peer_b="lpg-a"):
        return {"subject": "peering", "region": "us-ashburn-1", "vcns": [
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


class BottomGatewayWidthTests(unittest.TestCase):
    """A narrow VCN widens so 3+ bottom-border gateways stay on its own border (GW_PITCH = 180)."""

    def _model(self, n):
        gws = [gw("igw", "internet_gateway", "Internet\nGateway", "igw"),
               gw("nat", "nat_gateway", "NAT\nGateway", "nat"),
               gw("lpg", "remote_peering_gateway", "LPG\nno peer", "lpg"),
               gw("igw", "internet_gateway", "Internet\nGateway 2", "igw2")][:n]
        return {"subject": "gw-width", "region": "us-ashburn-1",
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
                                     "vcns": [simple_vcn("a")]})
        self.assertEqual(d.abs_bbox("vcn-a")[2], ol.VCN_MIN_W)


def svc(icon, address, **extra):
    s = {"icon": icon, "label": icon.replace("_", " ").title(), "address": address}
    s.update(extra)
    return s


class OsnPanelTests(unittest.TestCase):
    def test_regional_services_move_to_the_osn_panel_right_of_the_vcn(self):
        model = {"subject": "svc", "region": "us-ashburn-1", "vcns": [simple_vcn(
            "a", gateways=[gw("sgw", "service_gateway", "Service\nGateway", "sgw")],
            services=[svc("logging", "log"), svc("buckets", "bkt"), svc("file_storage", "fss")])]}
        d = quiet(ol.build_diagram, model)
        vx, vy, vw, vh = d.abs_bbox("vcn-a")
        ox, oy, ow, oh = d.abs_bbox("osn")
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
        model = {"subject": "svc", "region": "us-ashburn-1",
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

    def test_auto_picks_icon_up_to_four_and_overrides_apply(self):
        d = quiet(ol.build_diagram, self._hub_spoke(4))
        self.assertEqual(d.layout_info["drg_style"]["drg"], "icon")
        self.assertNotIn("drgbox-drg", d._cells)
        d = quiet(ol.build_diagram, self._hub_spoke(2), drg_style="box")
        self.assertIn("drgbox-drg", d._cells)
        model = self._hub_spoke(6)
        model["drg_style"] = "icon"
        d = quiet(ol.build_diagram, model)
        self.assertNotIn("drgbox-drg", d._cells)
        with self.assertRaises(ValueError):
            quiet(ol.build_diagram, model, drg_style="fancy")

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


class ExamplesTests(unittest.TestCase):
    def test_reference_model_is_schema_2_and_passes_the_gate(self):
        import check_overlaps
        sys.path.insert(0, str(TESTS_DIR.parent / "examples"))
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

    def test_demo_builds_three_pages_and_passes_the_gate(self):
        import check_overlaps
        sys.path.insert(0, str(TESTS_DIR.parent / "examples"))
        import generate_demo_diagram as demo
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "demo.drawio"
            quiet(demo.build, out)
            text = out.read_text(encoding="utf-8")
            self.assertEqual(text.count("<diagram "), 3)
            self.assertIn('id="drgbox-drg"', text)                  # page 2: box style
            self.assertIn("Attachment (structural)", text)          # legend row
            self.assertIn("Oracle Services Network", text)
            self.assertEqual(quiet(check_overlaps.main, [str(out)]), 0)

    def test_connector_labels_are_not_drawn_over_shapes(self):
        """Spec section 2: the Site-to-Site VPN label sits on the line next to the
        on-premises item - not on top of the IPSec attachment box it leaves."""
        sys.path.insert(0, str(TESTS_DIR.parent / "examples"))
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
                self.assertLessEqual(label.right, box.x)      # on the on-premises side

    def test_committed_reference_diagram_is_not_stale(self):
        sys.path.insert(0, str(TESTS_DIR.parent / "examples"))
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


if __name__ == "__main__":
    unittest.main()
