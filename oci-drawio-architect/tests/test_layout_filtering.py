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
import oci_view as ov  # noqa: E402

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

    def test_a_location_box_the_filter_empties_is_not_drawn(self):
        """An On-premises panel with no equipment in it misleads the reader."""
        full = quiet(ol.build_diagram, TAGGED_MODEL())
        self.assertIn("hub", full._cells)
        cut = quiet(ol.build_diagram, TAGGED_MODEL(), filter_spec=["vcn=vcn-app"])
        self.assertNotIn("hub", cut._cells)

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


class RecordedCutTests(unittest.TestCase):
    """6.5 / 5: the front end cut the model; the layout reports that cut too."""

    def cut(self, **kwargs):
        """What a front end writes out: an already-cut model plus its report."""
        model, report = ov.filter_model(TAGGED_MODEL(), **kwargs)
        model["mode"] = report["mode"]
        return ov.record_cut(model, report)

    def test_a_front_end_filter_is_reported_by_the_layout_that_redraws_it(self):
        d = quiet(ol.build_diagram, self.cut(spec=["tag:Application=payments"]))
        info = d.layout_info["filter"]
        self.assertEqual(info["include"], ("tag:Application=payments",))
        self.assertEqual(info["items_dropped"], 4)      # the parser's four, not this run's zero
        self.assertEqual(info["items_kept"], 4)
        self.assertEqual(info["edges_dropped"], 1)

    def test_a_front_end_prune_is_reported_by_the_layout_that_redraws_it(self):
        """A1: layout_info["pruned"] always reports what the mode removed."""
        d = quiet(ol.build_diagram, self.cut(mode="participating"))
        self.assertEqual(d.layout_info["pruned"], {"items": 1, "services": 3})
        self.assertEqual(d.layout_info["view"]["mode"], "participating")

    def test_a_further_cli_filter_adds_to_the_recorded_counts(self):
        model = self.cut(spec=["tag:Application=payments"])
        d = quiet(ol.build_diagram, model, filter_spec=["!name~Web LB"])
        self.assertEqual(d.layout_info["filter"]["items_dropped"], 5)   # 4 recorded + 1 here
        self.assertNotIn("lb", icons(d))

    def test_the_legend_note_uses_the_merged_totals(self):
        d = quiet(ol.build_diagram, self.cut(spec=["tag:Application=payments"]), legend=True)
        notes = [str(e.get("label")) for e in d._cells.values()
                 if "Filtered:" in str(e.get("label"))]
        self.assertTrue(notes, "no filter note in the legend")
        self.assertIn("4 of 8 resources", notes[0])


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


def oke_model(members=("broker", "batch")):
    """The tagged model with the OKE box ``parse_terraform`` emits for a cluster.

    ``parse_terraform._build_oke_groups`` keys the box on the cluster's address
    and lists the cluster plus its node pools, so any parsed model with OKE in
    it meets the filter in exactly this shape.
    """
    m = TAGGED_MODEL()
    m["vcns"][0]["subnets"][1]["groups"] = [
        {"type": "oke_cluster", "label": "OKE cluster", "key": "oke:cluster-1",
         "items": list(members)}]
    return m


def group_boxes(d):
    return {cid for cid, e in d._cells.items()
            if e["kind"] == "group" and e.get("group_type") == "oke_cluster"}


class GroupBoxRepairTests(unittest.TestCase):
    """A filter must cut a groups[] box down, not kill the diagram with it."""

    def test_a_box_whose_member_the_filter_removed_still_builds(self):
        d = quiet(ol.build_diagram, oke_model(), filter_spec=["tag:Application=payments"])
        self.assertIn("broker", icons(d))
        self.assertNotIn("batch", icons(d))
        self.assertEqual(len(group_boxes(d)), 1)
        self.assertEqual(d.layout_info["filter"]["groups_dropped"], 0)

    def test_a_vcn_box_over_a_dropped_subnet_still_builds(self):
        m = TAGGED_MODEL()
        m["vcns"][0]["groups"] = [{"type": "oke_cluster", "label": "Tiers",
                                   "subnets": ["sn-web", "sn-app"]}]
        d = quiet(ol.build_diagram, m, filter_spec=["subnet=sn-web"])
        self.assertEqual(len(group_boxes(d)), 1)
        self.assertEqual(d.layout_info["filter"]["groups_dropped"], 0)

    def test_a_box_that_loses_every_member_is_dropped_and_counted(self):
        d = quiet(ol.build_diagram, oke_model(members=("batch",)),
                  filter_spec=["tag:Application=payments"])
        self.assertEqual(group_boxes(d), set())
        self.assertEqual(d.layout_info["filter"]["groups_dropped"], 1)

    def test_an_edge_onto_a_box_that_went_is_dropped_with_it(self):
        m = oke_model(members=("batch",))
        m["edges"].append({"source": "lb", "target": "oke:cluster-1", "label": "443",
                           "kind": "data", "discovery": "association"})
        base = quiet(ol.build_diagram, TAGGED_MODEL(), filter_spec=["tag:Application=payments"])
        d = quiet(ol.build_diagram, m, filter_spec=["tag:Application=payments"])
        self.assertEqual(d.layout_info["filter"]["edges_dropped"],
                         base.layout_info["filter"]["edges_dropped"] + 1)

    def test_an_edge_onto_a_box_that_survived_is_kept(self):
        m = oke_model()
        m["edges"].append({"source": "lb", "target": "oke:cluster-1", "label": "443",
                           "kind": "data", "discovery": "association"})
        d = quiet(ol.build_diagram, m, filter_spec=["tag:Application=payments"])
        box = group_boxes(d).pop()
        self.assertTrue([e for e in d._cells.values()
                         if e["kind"] == "edge" and box in (e.get("source"), e.get("target"))])

    def test_a_member_the_model_never_had_still_raises(self):
        """Only a member the filter took away is repaired; a typo is a model error."""
        for spec in (None, ["tag:Application=payments"]):
            with self.assertRaises(ValueError) as ctx:
                quiet(ol.build_diagram, oke_model(members=("broker", "nope")), filter_spec=spec)
            self.assertIn("'nope' is not a member of this container", str(ctx.exception))

    def test_a_member_of_another_container_still_raises_once_the_filter_removes_it(self):
        """The whitelist is per container: only the box's OWN members are repaired."""
        with self.assertRaises(ValueError) as ctx:
            quiet(ol.build_diagram, oke_model(members=("broker", "bastion")),
                  filter_spec=["tag:Application=payments"])       # drops bastion, in vcn-ops
        self.assertIn("'bastion' is not a member of this container", str(ctx.exception))

    def test_a_repaired_box_passes_the_strict_file_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = quiet(ol.write_diagram, oke_model(), Path(tmp) / "g.drawio",
                        filter_spec=["tag:Application=payments"])
            self.assertEqual(quiet(check_overlaps.main, ["--strict", str(out)]), 0)

    def test_the_caller_s_model_keeps_its_members(self):
        m = oke_model()
        quiet(ol.build_diagram, m, filter_spec=["tag:Application=payments"])
        self.assertEqual(m["vcns"][0]["subnets"][1]["groups"][0]["items"], ["broker", "batch"])
