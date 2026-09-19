"""Layout tests for the v1.5.0 filter, participating mode and discovery provenance."""
from __future__ import annotations

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

from test_filter_model import model as TAGGED_MODEL  # noqa: E402
from test_view_layers import quiet  # noqa: E402


def icons(d):
    return {cid for cid, e in d._cells.items() if e["kind"] == "icon" and not e.get("badge")}


class LayoutFilterTests(unittest.TestCase):
    def test_no_filter_keeps_everything_and_reports_zeroes(self):
        d = quiet(ol.build_diagram, TAGGED_MODEL())
        self.assertEqual(d.layout_info["filter"]["items_dropped"], 0)
        self.assertEqual(d.layout_info["filter"]["include"], ())
        self.assertIn("batch", icons(d))

    def test_a_filter_is_applied_before_the_topology_is_classified(self):
        """8: migrate -> resolve the view -> filter and prune -> classify."""
        full = quiet(ol.build_diagram, TAGGED_MODEL())
        cut = quiet(ol.build_diagram, TAGGED_MODEL(), filter_spec=["vcn=vcn-app"])
        self.assertEqual(full.layout_info["topology"]["n_vcns"], 2)
        self.assertEqual(cut.layout_info["topology"]["n_vcns"], 1)
        self.assertEqual(cut.layout_info["topology"]["n_vcn_attachments"], 1)

    def test_a_tag_filter_drops_the_items_and_reports_the_counts(self):
        d = quiet(ol.build_diagram, TAGGED_MODEL(), filter_spec=["tag:Application=payments"])
        self.assertIn("broker", icons(d))
        self.assertNotIn("batch", icons(d))
        self.assertEqual(d.layout_info["filter"]["include"], ("tag:Application=payments",))
        self.assertGreater(d.layout_info["filter"]["items_dropped"], 0)

    def test_a_filter_model_key_is_honoured_without_a_flag(self):
        m = TAGGED_MODEL()
        m["filter"] = {"include": ["env=nonprod"]}
        self.assertNotIn("broker", icons(quiet(ol.build_diagram, m)))

    def test_the_flag_beats_the_model_key(self):
        m = TAGGED_MODEL()
        m["filter"] = {"include": ["env=nonprod"]}
        d = quiet(ol.build_diagram, m, filter_spec=["env=prod"])
        self.assertIn("broker", icons(d))
        self.assertNotIn("batch", icons(d))

    def test_an_edge_whose_endpoint_went_is_dropped_and_counted(self):
        d = quiet(ol.build_diagram, TAGGED_MODEL(), filter_spec=["vcn=vcn-app"])
        self.assertGreaterEqual(d.layout_info["filter"]["edges_dropped"], 1)
        self.assertNotIn("bastion", icons(d))

    def test_a_filtered_diagram_passes_the_strict_file_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = quiet(ol.write_diagram, TAGGED_MODEL(), Path(tmp) / "f.drawio",
                        filter_spec=["tag:Application=payments"])
            self.assertEqual(quiet(check_overlaps.main, ["--strict", str(out)]), 0)


class LayoutModeTests(unittest.TestCase):
    def test_all_is_the_default(self):
        d = quiet(ol.build_diagram, TAGGED_MODEL())
        self.assertEqual(d.layout_info["view"]["mode"], "all")
        self.assertEqual(d.layout_info["pruned"], {"items": 0, "services": 0})
        self.assertIn("logs", icons(d))

    def test_participating_prunes_the_unconnected_services_and_reports_it(self):
        d = quiet(ol.build_diagram, TAGGED_MODEL(), mode="participating")
        self.assertNotIn("logs", icons(d))
        self.assertNotIn("idcs", icons(d))
        self.assertIn("broker", icons(d))
        self.assertEqual(d.layout_info["pruned"]["services"], 3)

    def test_a_participating_diagram_still_validates(self):
        d = quiet(ol.build_diagram, TAGGED_MODEL(), mode="participating")
        self.assertEqual([m for m in d.validate() if not db.is_warning(m)], [])


class DiscoveryTests(unittest.TestCase):
    def test_the_discovery_mix_is_reported(self):
        d = quiet(ol.build_diagram, TAGGED_MODEL())
        self.assertEqual(d.layout_info["edges"], {"association": 1, "heuristic": 1})

    def test_a_discovery_selector_prunes_the_guesses(self):
        d = quiet(ol.build_diagram, TAGGED_MODEL(), discovery="association,config,user")
        self.assertEqual(d.layout_info["edges"], {"association": 1})
        self.assertEqual(d.layout_info["filter"]["edges_dropped"], 1)

    def test_discovery_never_changes_a_connector_style(self):
        """V8: the four line styles keep their four meanings."""
        base = quiet(ol.build_diagram, TAGGED_MODEL())
        annotated = quiet(ol.build_diagram, TAGGED_MODEL(), annotate_discovery=True)

        def styles(d):
            return {cid: [el.get("style") for el in d.root if el.get("id") == cid][0]
                    if [el for el in d.root if el.get("id") == cid and el.tag == "mxCell"]
                    else [el.find("mxCell").get("style") for el in d.root
                          if el.get("id") == cid][0]
                    for cid, e in d._cells.items() if e["kind"] == "edge"}
        self.assertEqual(sorted(styles(base).values()), sorted(styles(annotated).values()))

    def test_annotate_discovery_puts_the_provenance_in_the_edge_tooltip(self):
        d = quiet(ol.build_diagram, TAGGED_MODEL(), annotate_discovery=True)
        wrappers = [el for el in d.root if el.tag == "object" and el.get("tooltip")]
        self.assertTrue([w for w in wrappers if w.get("tooltip") == "Discovered by: association"])
        self.assertTrue([w for w in wrappers if w.get("tooltip") == "Discovered by: heuristic"])

    def test_without_the_flag_no_edge_is_wrapped(self):
        d = quiet(ol.build_diagram, TAGGED_MODEL())
        edge_ids = {cid for cid, e in d._cells.items() if e["kind"] == "edge"}
        self.assertEqual([el.get("id") for el in d.root
                          if el.tag == "object" and el.get("id") in edge_ids], [])


class CliTests(unittest.TestCase):
    def test_repeated_filter_flags_accumulate_into_include(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "m.json"
            src.write_text(json.dumps(TAGGED_MODEL()), encoding="utf-8")
            out = Path(tmp) / "out.drawio"
            rc = quiet(ol.main, [str(src), "-o", str(out),
                                 "--filter", "tag:Application=payments",
                                 "--filter", "!name=Web LB", "--mode", "participating"])
            self.assertEqual(rc, 0)
            text = out.read_text(encoding="utf-8")
            self.assertIn("App Broker VM", text)
            self.assertNotIn("Web LB", text)
