"""Layout tests for scripts/oci_layout.py (v1.3.0 topology-aware placement)."""
import contextlib
import io
import sys
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


if __name__ == "__main__":
    unittest.main()
