"""Layout tests for the v1.5.0 detail levels (C03) and the V4 gate/layer interaction."""
from __future__ import annotations

import contextlib
import copy
import io
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import check_overlaps  # noqa: E402
import drawio_builder as db  # noqa: E402
import oci_layout as ol  # noqa: E402
import oci_view as ov  # noqa: E402

from test_view_layers import MODEL, quiet  # noqa: E402


def badge_ids(d):
    return sorted(cid for cid, e in d._cells.items() if e.get("badge"))


def edge_labels(d):
    return sorted(e["label"] for e in d._cells.values() if e["kind"] == "edge" and e["label"])


class DetailLevelTests(unittest.TestCase):
    def test_every_level_builds_and_passes_the_strict_gate(self):
        for level in ov.DETAIL_ORDER:
            d = quiet(ol.build_diagram, MODEL, detail=level)
            self.assertEqual([m for m in d.validate() if not db.is_warning(m)], [], level)
            self.assertEqual(d.check_overlaps(strict=True), [], level)
            self.assertEqual(d.layout_info["view"]["detail"], level)

    def test_the_network_level_is_the_1_4_output(self):
        default = quiet(ol.build_diagram, MODEL)
        network = quiet(ol.build_diagram, MODEL, detail="network")
        self.assertEqual({cid: default.abs_bbox(cid) for cid, e in default._cells.items()
                          if e["kind"] != "edge"},
                         {cid: network.abs_bbox(cid) for cid, e in network._cells.items()
                          if e["kind"] != "edge"})

    def test_the_executive_level_draws_no_badges_no_cidrs_and_no_edge_labels(self):
        d = quiet(ol.build_diagram, MODEL, detail="executive")
        self.assertEqual(badge_ids(d), [])
        self.assertEqual(edge_labels(d), [])
        # _new_id() slugs the key: the cell id is "subnet-sn-web".
        self.assertEqual(d._cells["subnet-sn-web"]["label"], "sn-web (Public)")
        self.assertNotIn("10.0.1.0/24", d._cells["subnet-sn-web"]["label"])

    def test_the_executive_level_connects_the_drg_straight_to_the_vcn(self):
        """6.4: no attachment boxes - the vcn_with_drg presentation."""
        d = quiet(ol.build_diagram, MODEL, detail="executive")
        self.assertNotIn("att-app", d._cells)
        self.assertNotIn("att-vpn", d._cells)
        sources = {e["source"] for e in d._cells.values() if e["kind"] == "edge"}
        self.assertIn("drg", sources)
        self.assertLess(ol._drg_column_width(MODEL["drgs"], "auto",
                                             ov.resolve_view({"detail": "executive"})),
                        ol._drg_column_width(MODEL["drgs"], "auto"))

    def test_an_attachment_named_by_caption_resolves_at_every_level(self):
        """The boxes-off branch registers the attachment by caption as well as by address.

        ``_Registry.resolve`` documents the caption as a supported endpoint
        form, so a 1.4.0 model that names an attachment by its caption has to
        degrade to the DRG glyph at ``executive``, not raise.
        """
        model = copy.deepcopy(MODEL)
        model["edges"] = list(model.get("edges") or []) + [
            {"source": "VCN attachment", "target": "app", "kind": "data", "address": "cap-edge"},
            {"source": "IPSec attachment", "target": "app", "kind": "data", "address": "cap2-edge"},
            {"source": "att-app", "target": "app", "kind": "data", "address": "addr-edge"},
        ]
        for level in ov.DETAIL_ORDER:
            d = quiet(ol.build_diagram, model, detail=level)
            for eid in ("cap-edge", "cap2-edge", "addr-edge"):
                self.assertIn(eid, d._cells, (level, eid))
        boxes = quiet(ol.build_diagram, model, detail="network")
        self.assertEqual(boxes._cells["cap-edge"]["source"], "att-app")
        self.assertEqual(boxes._cells["cap2-edge"]["source"], "att-vpn")
        no_boxes = quiet(ol.build_diagram, model, detail="executive")
        for eid in ("cap-edge", "cap2-edge", "addr-edge"):
            self.assertEqual(no_boxes._cells[eid]["source"], "drg", eid)

    def test_the_application_level_keeps_the_attachment_boxes_and_the_edge_labels(self):
        d = quiet(ol.build_diagram, MODEL, detail="application")
        self.assertIn("att-app", d._cells)
        self.assertEqual(badge_ids(d), [])
        self.assertIn("8080", edge_labels(d))

    def test_the_drg_route_table_is_dropped_below_the_network_level(self):
        """The default level keeps the 1.4.0 badge strip; executive and application drop it."""
        self.assertNotIn("drg-rt", quiet(ol.build_diagram, MODEL, detail="application")._cells)
        self.assertIn("drg-rt", quiet(ol.build_diagram, MODEL, detail="network")._cells)
        self.assertIn("drg-rt", quiet(ol.build_diagram, MODEL, detail="engineering")._cells)

    def test_the_engineering_level_uses_the_detailed_caption_mode(self):
        d = quiet(ol.build_diagram, MODEL, detail="engineering")
        self.assertEqual(d.layout_info["view"]["label_mode"], "detailed")
        self.assertEqual(d.max_label_lines, 5)

    def test_the_gate_table_keeps_gateways_and_the_osn_on_at_every_level(self):
        """6.4: the two rows exist for completeness; no 1.5.0 level drops them."""
        for level in ov.DETAIL_ORDER:
            self.assertTrue(ov.DETAIL_LEVELS[level]["gateways"], level)
            self.assertTrue(ov.DETAIL_LEVELS[level]["osn"], level)
            self.assertIn("sgw", quiet(ol.build_diagram, MODEL, detail=level)._cells, level)
            self.assertIn("osn", quiet(ol.build_diagram, MODEL, detail=level)._cells, level)


class GateAndLayerTests(unittest.TestCase):
    def test_a_gate_that_is_off_hides_its_layer_instead_of_dropping_the_cells(self):
        """V4: an explicit --layers routes,security,dataflow emits the badges, hidden."""
        d = quiet(ol.build_diagram, MODEL, detail="application",
                  layers=["routes", "security", "dataflow"])
        self.assertIn("subnet-sn-web-rt", d._cells)
        self.assertIn("lb-nsg", d._cells)
        self.assertEqual(sorted(d.layout_info["layers"]["hidden"]), ["routes", "security"])
        self.assertEqual(d._cells["subnet-sn-web-rt"]["parent"], "layer-routes")

    def test_layers_auto_at_an_elided_level_emits_the_badges_on_a_hidden_layer(self):
        """6.4 / spec 12: badges present but on a hidden layer at --detail application --layers auto."""
        d = quiet(ol.build_diagram, MODEL, detail="application", layers="auto")
        self.assertIn("subnet-sn-web-rt", d._cells)
        self.assertIn("lb-nsg", d._cells)
        self.assertEqual(d._cells["subnet-sn-web-rt"]["parent"], "layer-routes")
        self.assertEqual(d._cells["lb-nsg"]["parent"], "layer-security")
        hidden = d.layout_info["layers"]["hidden"]
        self.assertIn("routes", hidden)
        self.assertIn("security", hidden)
        self.assertNotIn("dataflow", hidden)

    def test_the_same_level_without_layers_drops_them(self):
        # The ids are slugged: "subnet-sn-web-rt", never "subnet:sn-web-rt".
        # Asserting the colon form would make this test a false green.
        d = quiet(ol.build_diagram, MODEL, detail="application")
        self.assertNotIn("subnet-sn-web-rt", d._cells)
        self.assertNotIn("lb-nsg", d._cells)

    def test_the_hidden_layer_still_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = quiet(ol.write_diagram, MODEL, Path(tmp) / "app.drawio",
                        detail="application", layers="auto")
            self.assertEqual(quiet(check_overlaps.main, ["--strict", str(out)]), 0)


class ShowEdgesTests(unittest.TestCase):
    def test_show_edges_false_draws_no_model_connector(self):
        d = quiet(ol.build_diagram, MODEL, show_edges=False)
        model_edges = [cid for cid, e in d._cells.items()
                       if e["kind"] == "edge" and not cid.endswith(("-osn", "-internet", "-edge"))]
        self.assertEqual(model_edges, [])

    def test_the_structural_connectors_survive_show_edges_false(self):
        d = quiet(ol.build_diagram, MODEL, show_edges=False)
        self.assertTrue([cid for cid in d._cells if cid.endswith("-osn")])
        self.assertTrue([cid for cid in d._cells if cid.endswith("-edge")])

    def test_show_edges_false_creates_no_edge_layer(self):
        d = quiet(ol.build_diagram, MODEL, show_edges=False, layers="auto")
        for name in ("dataflow", "management", "associations"):
            self.assertNotIn(name, d.layout_info["layers"]["enabled"], name)


class LegendTests(unittest.TestCase):
    def test_a_level_that_asks_for_a_legend_gets_one_without_the_caller_asking(self):
        self.assertIn("Legend", [e["label"] for e in
                                 quiet(ol.build_diagram, MODEL, detail="engineering")._cells.values()])

    def test_the_network_level_leaves_the_choice_to_the_caller(self):
        self.assertIsNone(ov.DETAIL_LEVELS["network"]["legend"])
        labels = [e["label"] for e in quiet(ol.build_diagram, MODEL)._cells.values()]
        self.assertNotIn("Legend", labels)

    def labels(self, **kwargs):
        return [e["label"] for e in quiet(ol.build_diagram, MODEL, **kwargs)._cells.values()]

    def test_an_explicit_legend_false_beats_the_level_that_asks_for_one(self):
        """6.1: CLI flag / kwarg -> model key -> detail -> purpose -> default."""
        self.assertNotIn("Legend", self.labels(detail="engineering", legend=False))
        self.assertIn("Legend", self.labels(detail="engineering", legend=True))

    def test_the_kwarg_beats_a_model_key_in_both_directions(self):
        model = dict(MODEL, legend=False)
        self.assertNotIn("Legend", [e["label"] for e in
                                    quiet(ol.build_diagram, model)._cells.values()])
        self.assertIn("Legend", [e["label"] for e in
                                 quiet(ol.build_diagram, model, legend=True)._cells.values()])
        model_on = dict(MODEL, legend=True)
        self.assertNotIn("Legend", [e["label"] for e in
                                    quiet(ol.build_diagram, model_on, legend=False)._cells.values()])

    def test_the_default_is_still_no_legend(self):
        self.assertNotIn("Legend", self.labels())
        self.assertIn("Legend", self.labels(legend=True))
