"""Builder tests for the v1.5.0 view primitives: layers, caption geometry, legend rows.

Kept in its own module so the layer work and the v1.4.0 builder suite never
touch the same file (the release plan runs these tasks in parallel worktrees).
"""
from __future__ import annotations

import contextlib
import io
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import drawio_builder as db  # noqa: E402
from drawio_builder import DrawioBuilder  # noqa: E402


def cell(root, cid):
    for el in root:
        if el.tag == "mxCell" and el.get("id") == cid:
            return el
        if el.tag in ("object", "UserObject") and el.get("id") == cid:
            return el.find("mxCell")
    raise KeyError(f"no cell {cid!r}")


def tokens(style):
    out = {}
    for tok in (style or "").split(";"):
        if not tok:
            continue
        k, _, v = tok.partition("=")
        out[k] = v if _ else None
    return out


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def only_errors(messages):
    return [m for m in messages if not db.is_warning(m)]


class CaptionGeometryTests(unittest.TestCase):
    def test_the_detailed_caption_box_holds_six_lines_at_the_label_font(self):
        """V6: 6 * LABEL_LINE_H + 4 = 88 px, which clears rule 5's 6 * 11 * 1.25 escape."""
        self.assertEqual(db.LABEL_H_DETAILED, 88)
        self.assertEqual(db.LABEL_H_DETAILED, 6 * db.LABEL_LINE_H + 4)
        self.assertGreater(db.LABEL_H_DETAILED, 6 * db.LABEL_FONT_SIZE * 1.25)

    def test_the_line_budget_names_the_three_label_modes(self):
        self.assertEqual(db.LABEL_LINE_BUDGET, {"minimal": 2, "network": 3, "detailed": 5})

    def test_icon_footprint_h_defaults_to_the_1_4_footprint(self):
        self.assertEqual(db.icon_footprint_h(), db.ICON_FOOTPRINT_H)
        self.assertEqual(db.icon_footprint_h(db.LABEL_H), 142)
        self.assertEqual(db.icon_footprint_h(db.LABEL_H_DETAILED),
                         db.ICON_H + db.LABEL_GAP + db.LABEL_H_DETAILED)

    def test_a_detailed_caption_box_passes_rule_5_under_the_default_ceiling(self):
        """V6: the file-level gate needs no mode knowledge."""
        d = DrawioBuilder()
        d.add_icon("App Broker VM\n10.0.2.47\nAD-1 / FD-2\nCompartment: app-prod",
                   "vm", 40, 40, label_h=db.LABEL_H_DETAILED)
        self.assertEqual(only_errors(d.validate()), [])
        self.assertEqual([m for m in d.validate() if "needs ~" in m], [])


class LayerPrimitiveTests(unittest.TestCase):
    def test_the_base_layer_starts_unnamed_and_can_be_named(self):
        d = DrawioBuilder()
        self.assertEqual(cell(d.root, "1").get("value"), None)
        self.assertEqual(d.set_base_layer_name("Network"), "1")
        self.assertEqual(cell(d.root, "1").get("value"), "Network")

    def test_layer_ids_reads_the_page_layers_list(self):
        d = DrawioBuilder()
        self.assertEqual(d.layer_ids(), ["1"])
        rid = d.add_layer("Routes", key="layer-routes")
        self.assertEqual(rid, "layer-routes")
        self.assertEqual(d.layer_ids(), ["1", "layer-routes"])
        d.add_page("Second")
        self.assertEqual(d.layer_ids(), ["1"])

    def test_a_hidden_layer_carries_visible_zero(self):
        d = DrawioBuilder()
        d.add_layer("Routes", visible=False, key="layer-routes")
        self.assertEqual(cell(d.root, "layer-routes").get("visible"), "0")
        self.assertEqual(cell(d.root, "layer-routes").get("parent"), "0")

    def test_a_badge_reparented_onto_a_layer_keeps_its_absolute_position(self):
        """V1: the layer pass only changes a parent; it cannot move a pixel."""
        d = DrawioBuilder()
        sn = d.add_group("sn-app", 100, 80, 300, 200, group_type="subnet")
        bid = d.add_badge("route_table", 300, 0, parent=sn, host=sn, key="sn-app-rt")
        before = d.abs_bbox(bid)
        lid = d.add_layer("Routes", key="layer-routes")
        d.reparent(bid, lid)
        self.assertEqual(d.abs_bbox(bid), before)
        self.assertEqual(d._cells[bid]["parent"], "layer-routes")

    def test_an_icon_reparented_onto_a_layer_takes_its_caption_with_it(self):
        d = DrawioBuilder()
        grp = d.add_group("Region", 0, 0, 600, 400, group_type="region")
        cid = d.add_icon("Identity Domain", "iam", 60, 60, parent=grp, key="idcs")
        lid = d.add_layer("IAM", key="layer-iam")
        icon_box, label_box = d.abs_bbox(cid), d.abs_bbox(d._cells[cid]["label_id"])
        d.reparent(cid, lid)
        self.assertEqual(d.abs_bbox(cid), icon_box)
        self.assertEqual(d.abs_bbox(d._cells[cid]["label_id"]), label_box)
        self.assertEqual(d._cells[d._cells[cid]["label_id"]]["parent"], "layer-iam")

    def test_an_edge_parented_to_a_layer_routes_to_the_same_absolute_path(self):
        """6.2 step 3: the parent only selects the coordinate frame of the waypoints."""
        def build(parent_is_layer):
            d = DrawioBuilder()
            rid = d.add_group("Region", 0, 0, 900, 500, group_type="region")
            a = d.add_icon("A", "vm", 60, 60, parent=rid, key="a")
            b = d.add_icon("B", "vm", 600, 300, parent=rid, key="b")
            lid = d.add_layer("Data flows", key="layer-dataflow") if parent_is_layer else None
            d.add_edge(a, b, "443", parent=lid, kind="data", key="e1")
            d.route_edges()
            ox, oy = d._origin(d._cells["e1"]["parent"])
            return [(round(x + ox, 3), round(y + oy, 3)) for x, y in d._cells["e1"]["points"]]
        self.assertEqual(build(True), build(False))

    def test_the_validator_still_checks_a_hidden_layer(self):
        """V10: no rule reads visible; a hidden layer must be clean when shown."""
        d = DrawioBuilder()
        rid = d.add_group("Region", 0, 0, 600, 400, group_type="region")
        lid = d.add_layer("Routes", visible=False, key="layer-routes")
        d.add_icon("A", "vm", 60, 60, parent=lid, key="a")
        d.add_icon("B", "vm", 60, 60, parent=lid, key="b")
        self.assertTrue([m for m in d.validate() if "overlaps" in m],
                        "a collision on a hidden layer must still be reported")
        self.assertTrue(rid)


class MaxLabelLinesTests(unittest.TestCase):
    FOUR_LINES = "App Broker VM\n10.0.2.47\nAD-1 / FD-2\nCompartment: app-prod"

    def test_the_default_ceiling_is_the_module_constant(self):
        self.assertEqual(DrawioBuilder().max_label_lines, db.MAX_LABEL_LINES)

    def test_a_four_line_caption_in_a_45px_box_warns_at_the_default_ceiling(self):
        d = DrawioBuilder()
        d.add_icon(self.FOUR_LINES, "vm", 40, 40, label_h=db.LABEL_H)
        self.assertTrue([m for m in d.validate() if "needs ~5 lines" in m])

    def test_raising_the_ceiling_silences_the_warning_for_this_document_only(self):
        """6.3: the in-memory path matches the mode; the file gate keeps the default."""
        d = DrawioBuilder(max_label_lines=5)
        d.add_icon(self.FOUR_LINES, "vm", 40, 40, label_h=db.LABEL_H)
        self.assertEqual([m for m in d.validate() if "needs ~" in m], [])
        self.assertEqual(only_errors(d.validate()), [])


class BadgeHostExemptionTests(unittest.TestCase):
    """6.2: a badge moved onto a layer is no longer a descendant of its host."""

    def _diagram(self, move_badge_to_layer):
        d = DrawioBuilder()
        vcn = d.add_group("VCN: vcn-app", 0, 0, 600, 400, group_type="vcn")
        sn = d.add_group("sn-app", 40, 60, 400, 280, parent=vcn, group_type="subnet")
        bid = d.add_badge("route_table", 400, 0, parent=sn, host=sn, key="sn-app-rt")
        if move_badge_to_layer:
            d.reparent(bid, d.add_layer("Routes", key="layer-routes"))
        return d, bid

    def test_a_subnet_badge_on_a_layer_is_not_foreign_to_its_own_subnet(self):
        d, _ = self._diagram(True)
        self.assertEqual(only_errors(d.validate()), [])

    def test_the_same_badge_as_a_child_of_its_subnet_is_still_clean(self):
        d, _ = self._diagram(False)
        self.assertEqual(only_errors(d.validate()), [])

    def test_a_badge_whose_host_is_elsewhere_is_still_reported(self):
        """The exemption is narrow: only the container that holds the host."""
        d = DrawioBuilder()
        sn_a = d.add_group("sn-a", 0, 0, 300, 200, group_type="subnet")
        sn_b = d.add_group("sn-b", 340, 0, 300, 200, group_type="subnet")
        host = d.add_icon("App VM", "vm", 20, 60, parent=sn_a, key="app")
        lid = d.add_layer("Security", key="layer-security")
        d.add_badge("nsg", 480, 100, parent=lid, host=host, key="app-nsg")
        errors = only_errors(d.validate())
        self.assertTrue([e for e in errors if "lies inside 'sn-b'" in e], errors)
        self.assertTrue(sn_b)


class StyleExtraTests(unittest.TestCase):
    def test_add_icon_accepts_style_extra(self):
        d = DrawioBuilder()
        cid = d.add_icon("App VM", "vm", 0, 0, style_extra="ociKind=workload;")
        tok = tokens(cell(d.root, cid).get("style"))
        self.assertEqual(tok["ociKind"], "workload")
        self.assertEqual(tok["shape"], "image")
        self.assertTrue(tok["image"].startswith("data:image/svg+xml,"))

    def test_add_badge_accepts_style_extra_and_keeps_its_role_tokens(self):
        d = DrawioBuilder()
        sn = d.add_group("sn-app", 0, 0, 300, 200, group_type="subnet")
        bid = d.add_badge("route_table", 300, 0, parent=sn, host=sn, style_extra="ociLayer=routes;")
        tok = tokens(cell(d.root, bid).get("style"))
        self.assertEqual((tok["ociRole"], tok["ociHost"], tok["ociLayer"]), ("badge", sn, "routes"))


class LegendRowTests(unittest.TestCase):
    def test_a_layer_row_draws_a_swatch_and_the_layer_name(self):
        d = DrawioBuilder()
        gid = d.add_legend(0, 0, entries=[("layer", "routes", "Routes (hidden)")])
        kids = [(cid, e) for cid, e in d._cells.items() if e["parent"] == gid]
        swatches = [e for _cid, e in kids if e["label"] == "layer swatch"]
        texts = [e["label"] for _cid, e in kids if e["kind"] == "text"]
        self.assertEqual(len(swatches), 1)
        self.assertEqual((swatches[0]["w"], swatches[0]["h"]), (36.0, 16.0))
        self.assertIn("Routes (hidden)", texts)

    def test_a_note_row_is_a_full_width_line_with_no_swatch(self):
        d = DrawioBuilder()
        gid = d.add_legend(0, 0, width=230,
                           entries=[("note", "", "Filtered: Application=payments (18 of 43 resources)")])
        kids = [e for e in d._cells.values() if e["parent"] == gid]
        self.assertEqual([e["label"] for e in kids if e["kind"] == "text"],
                         ["Filtered: Application=payments (18 of 43 resources)"])
        note = [e for e in kids if e["kind"] == "text"][0]
        self.assertEqual((note["x"], note["w"]), (14.0, 210.0))
        self.assertEqual([e for e in kids if e["label"] == "layer swatch"], [])

    def test_a_long_note_row_grows_its_own_height_and_the_legend_box(self):
        """7.7: four filter expressions wrap; a fixed 22 px row would print over the next one."""
        text = ("Filtered: tag:Application=payments, tag:Environment=prod, "
                "compartment=app-prod, !type=oci_core_nat_gateway (18 of 43 resources)")
        d = DrawioBuilder()
        gid = d.add_legend(0, 0, width=230, entries=[("group", "vcn", "VCN"),
                                                     ("note", "", text),
                                                     ("group", "subnet", "Subnet")])
        kids = {e["label"]: e for e in d._cells.values() if e["parent"] == gid}
        note = kids[text]
        self.assertGreater(note["h"], 22.0)
        self.assertGreater(kids["Subnet"]["y"], note["y"] + note["h"] - 0.01)
        self.assertGreaterEqual(d._cells[gid]["h"], kids["Subnet"]["y"] + 22 + 8)
        self.assertEqual(only_errors(d.validate()), [])
        self.assertEqual([m for m in d.validate() if "needs ~" in m], [])

    def test_the_legend_still_validates_with_every_row_kind(self):
        d = DrawioBuilder()
        d.add_legend(0, 0, entries=[("edge", "data", "Data flow"),
                                    ("group", "vcn", "VCN"),
                                    ("badge", "route_table", "Route table"),
                                    ("layer", "security", "Security"),
                                    ("note", "", "18 of 43 resources")])
        d.fit_page()
        self.assertEqual(only_errors(d.validate()), [])


class EdgeTooltipTests(unittest.TestCase):
    """6.8: --annotate-discovery puts the provenance in the edge tooltip."""

    def _diagram(self, **kwargs):
        d = DrawioBuilder()
        rid = d.add_group("Region", 0, 0, 800, 500, group_type="region")
        a = d.add_icon("A", "vm", 60, 60, parent=rid, key="a")
        b = d.add_icon("B", "vm", 500, 300, parent=rid, key="b")
        d.add_edge(a, b, "443", kind="data", key="e1", **kwargs)
        return d

    def test_an_edge_without_a_tooltip_is_a_plain_mxcell(self):
        d = self._diagram()
        self.assertEqual([el.tag for el in d.root if el.get("id") == "e1"], ["mxCell"])

    def test_a_tooltip_wraps_the_edge_in_an_object_and_keeps_its_ends(self):
        d = self._diagram(tooltip="Discovered by: config")
        wrap = [el for el in d.root if el.get("id") == "e1"][0]
        self.assertEqual(wrap.tag, "object")
        self.assertEqual(wrap.get("tooltip"), "Discovered by: config")
        self.assertEqual(wrap.get("label"), "443")
        inner = wrap.find("mxCell")
        self.assertEqual((inner.get("edge"), inner.get("source"), inner.get("target")),
                         ("1", "a", "b"))

    def test_metadata_on_an_edge_becomes_object_attributes(self):
        d = self._diagram(metadata={"discovery": "config"})
        wrap = [el for el in d.root if el.get("id") == "e1"][0]
        self.assertEqual(wrap.get("discovery"), "config")

    def test_a_wrapped_edge_routes_and_validates_exactly_as_a_plain_one(self):
        plain, wrapped = self._diagram(), self._diagram(tooltip="x")
        plain.route_edges()
        wrapped.route_edges()
        self.assertEqual(plain._cells["e1"]["points"], wrapped._cells["e1"]["points"])
        self.assertEqual(only_errors(wrapped.validate()), [])


if __name__ == "__main__":
    unittest.main()
