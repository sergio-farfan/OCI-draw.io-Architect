"""Layout tests for the v1.5.0 purpose presets (C01) and the legend's new rows."""
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
import oci_view as ov  # noqa: E402

from test_layout_global_bucket import MODEL as GLOBAL_MODEL  # noqa: E402
from test_view_layers import MODEL, quiet  # noqa: E402


class PurposeTests(unittest.TestCase):
    def test_every_purpose_builds_and_passes_the_strict_gate(self):
        for name in ov.PURPOSES_ORDER:
            d = quiet(ol.build_diagram, MODEL, purpose=name)
            self.assertEqual([m for m in d.validate() if not db.is_warning(m)], [], name)
            self.assertEqual(d.check_overlaps(strict=True), [], name)
            self.assertEqual(d.layout_info["view"]["purpose"], name)

    def test_every_purpose_writes_a_file_that_passes_the_file_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ov.PURPOSES_ORDER:
                out = quiet(ol.write_diagram, MODEL, Path(tmp) / f"{name}.drawio",
                            purpose=name, layers="auto")
                self.assertEqual(quiet(check_overlaps.main, ["--strict", str(out)]), 0, name)

    def test_network_is_todays_look(self):
        d = quiet(ol.build_diagram, MODEL, purpose="network")
        base = quiet(ol.build_diagram, MODEL)
        self.assertEqual({cid: d.abs_bbox(cid) for cid, e in d._cells.items() if e["kind"] != "edge"},
                         {cid: base.abs_bbox(cid) for cid, e in base._cells.items()
                          if e["kind"] != "edge"})

    def test_dataflow_prunes_to_the_participants_and_keeps_the_port_labels(self):
        d = quiet(ol.build_diagram, MODEL, purpose="dataflow")
        view = d.layout_info["view"]
        self.assertEqual((view["detail"], view["mode"]), ("application", "participating"))
        self.assertEqual(view["label_fields"], ("display_name", "port_protocol"))
        self.assertIn("8080", [e["label"] for e in d._cells.values() if e["kind"] == "edge"])

    def test_security_switches_the_bucket_on_and_asks_for_a_legend(self):
        d = quiet(ol.build_diagram, GLOBAL_MODEL, purpose="security")
        self.assertEqual(d.layout_info["global_services"], "bucket")
        self.assertIn("global", d._cells)
        self.assertIn("Legend", [e["label"] for e in d._cells.values()])
        self.assertEqual(d.layout_info["view"]["label_fields"], ("display_name", "private_ip"))

    def test_inventory_draws_no_connectors_and_shows_the_compartments(self):
        d = quiet(ol.build_diagram, GLOBAL_MODEL, purpose="inventory")
        view = d.layout_info["view"]
        self.assertIs(view["show_edges"], False)
        self.assertIs(view["show_compartments"], True)
        self.assertEqual(view["global_services"], "bucket")

    def test_dependency_annotates_the_discovery_provenance(self):
        d = quiet(ol.build_diagram, MODEL, purpose="dependency")
        self.assertIs(d.layout_info["view"]["annotate_discovery"], True)
        self.assertTrue([el for el in d.root if el.tag == "object" and el.get("tooltip")])

    def test_ha_puts_the_ad_fd_pair_in_the_caption(self):
        self.assertEqual(quiet(ol.build_diagram, MODEL, purpose="ha").layout_info["view"]
                         ["label_fields"], ("display_name", "ad_fd"))

    def test_an_explicit_flag_still_beats_the_purpose(self):
        d = quiet(ol.build_diagram, MODEL, purpose="inventory", show_edges=True)
        self.assertIs(d.layout_info["view"]["show_edges"], True)

    def test_a_purpose_alone_never_turns_layers_on(self):
        """A5: layers stay opt-in; the purpose only names the set and the hidden set."""
        for name in ov.PURPOSES_ORDER:
            self.assertEqual(quiet(ol.build_diagram, MODEL, purpose=name)
                             .layout_info["layers"]["enabled"], [], name)

    def test_a_purpose_plus_layers_auto_uses_the_purposes_set(self):
        for name in ov.PURPOSES_ORDER:
            d = quiet(ol.build_diagram, MODEL, purpose=name, layers="auto")
            wanted = [n for n in ov.VIEW_LAYERS if n in ov.PURPOSES[name]["layers"]]
            enabled = d.layout_info["layers"]["enabled"]
            self.assertEqual(enabled, [n for n in wanted if n in enabled], name)
            self.assertEqual(set(enabled) - set(wanted), set(), name)
            self.assertEqual(set(d.layout_info["layers"]["hidden"]),
                             set(ov.PURPOSES[name]["hidden_layers"]) & set(enabled), name)
        d = quiet(ol.build_diagram, MODEL, purpose="dataflow", layers="auto")
        self.assertEqual(d.layout_info["layers"]["enabled"],
                         ["routes", "security", "dataflow", "management"])
        self.assertEqual(sorted(d.layout_info["layers"]["hidden"]), ["routes", "security"])

    def test_the_purpose_travels_in_the_model_too(self):
        model = dict(MODEL, purpose="ha")
        self.assertEqual(quiet(ol.build_diagram, model).layout_info["view"]["purpose"], "ha")

    def test_a_model_key_beats_the_purpose_it_travels_with(self):
        """6.1: an explicit key always wins over the preset that would have set it."""
        view = quiet(ol.build_diagram,
                     dict(MODEL, purpose="security", label_mode="detailed")).layout_info["view"]
        self.assertEqual(view["label_mode"], "detailed")
        self.assertEqual(view["label_fields"], ("display_name", "private_ip"))


class LegendRowTests(unittest.TestCase):
    def texts(self, d):
        gid = [cid for cid, e in d._cells.items() if e["label"] == "Legend"][0]
        return [e["label"] for cid, e in d._cells.items()
                if e["parent"] == gid and e["kind"] == "text"]

    def test_an_enabled_layer_gets_a_legend_row_naming_its_visibility(self):
        d = quiet(ol.build_diagram, MODEL, legend=True, layers="auto",
                  hidden_layers=["routes"])
        texts = self.texts(d)
        self.assertIn("Layer: Routes (hidden)", texts)
        self.assertIn("Layer: Security", texts)

    def test_no_layer_rows_when_layers_are_off(self):
        self.assertEqual([t for t in self.texts(quiet(ol.build_diagram, MODEL, legend=True))
                          if t.startswith("Layer: ")], [])

    def test_a_filtered_diagram_says_so_in_a_note_row(self):
        from test_filter_model import model as TAGGED_MODEL
        d = quiet(ol.build_diagram, TAGGED_MODEL(), legend=True,
                  filter_spec=["tag:Application=payments"])
        self.assertIn("Filtered: tag:Application=payments (4 of 8 resources)", self.texts(d))

    def test_participating_mode_says_what_it_pruned(self):
        from test_filter_model import model as TAGGED_MODEL
        d = quiet(ol.build_diagram, TAGGED_MODEL(), legend=True, mode="participating")
        # logs, vault and idcs (services) plus the batch VM (no edge, no badge,
        # not the sole item of its subnet) = 4.
        self.assertIn("Participating mode: 4 resource(s) not shown", self.texts(d))

    def test_an_unfiltered_legend_is_the_1_4_legend(self):
        d = quiet(ol.build_diagram, MODEL, legend=True)
        self.assertEqual([t for t in self.texts(d) if t.startswith(("Layer: ", "Filtered: ",
                                                                    "Participating"))], [])


class CliTests(unittest.TestCase):
    def test_the_purpose_flag_offers_the_six_names(self):
        import argparse
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit):
                ol.main(["--help"])
        text = buf.getvalue()
        for name in ov.PURPOSES_ORDER:
            self.assertIn(name, text, name)
        self.assertTrue(argparse)

    def test_purpose_from_the_cli_reaches_the_diagram(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "m.json"
            src.write_text(json.dumps(MODEL), encoding="utf-8")
            out = Path(tmp) / "o.drawio"
            self.assertEqual(quiet(ol.main, [str(src), "-o", str(out), "--purpose", "inventory",
                                             "--global-services", "osn"]), 0)
            self.assertTrue(out.exists())
