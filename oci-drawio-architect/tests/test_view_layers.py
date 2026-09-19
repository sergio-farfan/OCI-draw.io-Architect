"""Layout tests for the v1.5.0 view layers (C05): the post-pass may not move a pixel."""
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
import oci_layout as ol  # noqa: E402


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


MODEL = {
    "subject": "layers", "region": "us-ashburn-1", "region_label": "Ashburn",
    "hub": {"name": "On-premises", "items": [
        {"icon": "cpe", "label": "CPE", "address": "cpe"}]},
    "drgs": [{"name": "drg", "address": "drg", "label": "DRG",
              "route_table": [{"name": "drg-rt-vcn", "address": "drg.rt.vcn"}],
              "attachments": [{"type": "vcn", "vcn": "vcn-app", "address": "att-app",
                               "label": "VCN attachment\nvcn-app"},
                              {"type": "ipsec", "target": "cpe", "address": "att-vpn",
                               "label": "IPSec attachment"}]}],
    "vcns": [{
        "name": "vcn-app", "cidr": "10.0.0.0/16", "subnets": [
            {"name": "sn-web", "cidr": "10.0.1.0/24", "tier": "lb", "public": True,
             "route_table": "rt-web", "security_lists": ["sl-web"], "items": [
                 {"icon": "load_balancer", "label": "Web LB", "address": "lb",
                  "nsgs": ["nsg-lb"]}]},
            {"name": "sn-app", "cidr": "10.0.2.0/24", "tier": "app", "public": False,
             "route_table": "rt-app", "items": [
                 {"icon": "vm", "label": "App VM", "address": "app"}]}],
        "services": [{"icon": "logging", "label": "Logging", "address": "logs"}],
        "gateways": [{"icon": "service_gateway", "type": "sgw", "label": "Service\nGateway",
                      "address": "sgw"}],
    }],
    "edges": [
        {"source": "lb", "target": "app", "label": "8080", "kind": "data"},
        {"source": "app", "target": "sgw", "label": "OCI APIs", "kind": "control"},
        {"source": "lb", "target": "logs", "label": "", "kind": "association"},
    ],
}


def layer_cells(d):
    """{layer name: sorted cell ids parented to it}."""
    names = {cid: d._cells[cid]["label"] for cid in d.layer_ids() if cid != "1"}
    out = {name: [] for name in names.values()}
    for cid, e in d._cells.items():
        if e["parent"] in names:
            out[names[e["parent"]]].append(cid)
    return {k: sorted(v) for k, v in out.items()}


def abs_boxes(d):
    # A layer cell has no geometry of its own, and it only exists in the
    # layered build, so comparing it would make the invariance test trivially
    # fail rather than prove anything.
    return {cid: d.abs_bbox(cid) for cid, e in d._cells.items()
            if e["kind"] not in ("edge", "layer")}


class LayerCreationTests(unittest.TestCase):
    def test_layers_are_off_by_default_and_nothing_is_created(self):
        """V3 / A5."""
        d = quiet(ol.build_diagram, MODEL)
        self.assertEqual(d.layer_ids(), ["1"])
        self.assertEqual(d.layout_info["layers"], {"enabled": [], "hidden": [], "cells": {}})

    def test_auto_creates_every_layer_that_has_content_in_the_fixed_z_order(self):
        d = quiet(ol.build_diagram, MODEL, layers="auto")
        self.assertEqual([d._cells[cid]["label"] for cid in d.layer_ids()[1:]],
                         ["Routes", "Security", "Data flows", "Management paths", "Associations"])
        self.assertEqual(d.layout_info["layers"]["enabled"],
                         ["routes", "security", "dataflow", "management", "associations"])

    def test_the_base_layer_is_named_network_only_when_layers_are_on(self):
        d = quiet(ol.build_diagram, MODEL, layers="auto")
        base = [el for el in d.root if el.tag == "mxCell" and el.get("id") == "1"][0]
        self.assertEqual(base.get("value"), "Network")
        plain = quiet(ol.build_diagram, MODEL)
        base2 = [el for el in plain.root if el.tag == "mxCell" and el.get("id") == "1"][0]
        self.assertIsNone(base2.get("value"))

    def test_an_empty_layer_is_not_created(self):
        """6.2 step 4: the iam layer has no content while global_services is 'osn'."""
        d = quiet(ol.build_diagram, MODEL, layers="auto")
        self.assertNotIn("iam", d.layout_info["layers"]["enabled"])
        model = copy.deepcopy(MODEL)
        model["edges"] = [e for e in model["edges"] if e["kind"] != "association"]
        d2 = quiet(ol.build_diagram, model, layers="auto")
        self.assertNotIn("associations", d2.layout_info["layers"]["enabled"])

    def test_an_explicit_layer_list_creates_exactly_those(self):
        d = quiet(ol.build_diagram, MODEL, layers=["security", "dataflow"])
        self.assertEqual(d.layout_info["layers"]["enabled"], ["security", "dataflow"])

    def test_hidden_layers_carry_visible_zero_and_are_reported(self):
        d = quiet(ol.build_diagram, MODEL, layers="auto", hidden_layers=["routes"])
        # layer_ids()[0] is the base layer "1", which is not in _cells at all.
        lid = [cid for cid in d.layer_ids()[1:] if d._cells[cid]["label"] == "Routes"][0]
        el = [e for e in d.root if e.tag == "mxCell" and e.get("id") == lid][0]
        self.assertEqual(el.get("visible"), "0")
        self.assertEqual(d.layout_info["layers"]["hidden"], ["routes"])

    def test_the_layer_ids_are_deterministic(self):
        d = quiet(ol.build_diagram, MODEL, layers="auto")
        self.assertIn("layer-routes", d._cells)
        self.assertIn("layer-dataflow", d._cells)


class LayerMembershipTests(unittest.TestCase):
    def test_badges_move_to_routes_and_security(self):
        d = quiet(ol.build_diagram, MODEL, layers="auto")
        cells = layer_cells(d)
        # _new_id() slugs every key, so a subnet badge id is "subnet-<name>-rt".
        self.assertEqual(cells["Routes"], ["drg-rt", "subnet-sn-app-rt", "subnet-sn-web-rt"])
        self.assertEqual(cells["Security"], ["lb-nsg", "subnet-sn-web-sl"])

    def test_edges_take_the_layer_of_their_model_kind(self):
        d = quiet(ol.build_diagram, MODEL, layers="auto")
        cells = layer_cells(d)
        self.assertEqual(len(cells["Data flows"]), 1)
        self.assertEqual(len(cells["Management paths"]), 1)
        self.assertEqual(len(cells["Associations"]), 1)

    def test_attachment_connectors_and_containers_stay_on_the_base_layer(self):
        """V2 / 6.2: structure is the base layer; only annotation is layerable."""
        d = quiet(ol.build_diagram, MODEL, layers="auto")
        for cid in ("region", "vcn-vcn-app", "subnet-sn-web", "lb", "app", "sgw", "drg",
                    "att-app", "hub"):
            self.assertNotIn(d._cells[cid]["parent"], d.layer_ids()[1:], cid)
        attachment = [cid for cid, e in d._cells.items()
                      if e["kind"] == "edge" and cid.endswith("-osn")]
        self.assertTrue(attachment)
        for cid in attachment:
            self.assertEqual(d._cells[cid]["parent"] in d.layer_ids()[1:], False)

    def test_the_cell_counts_are_reported(self):
        info = quiet(ol.build_diagram, MODEL, layers="auto").layout_info["layers"]
        self.assertEqual(info["cells"], {"routes": 3, "security": 2, "dataflow": 1,
                                         "management": 1, "associations": 1})


class LayerInvarianceTests(unittest.TestCase):
    def test_enabling_layers_moves_no_cell(self):
        """V1: the post-pass only changes parents; reparent() preserves absolute position."""
        plain = quiet(ol.build_diagram, MODEL)
        layered = quiet(ol.build_diagram, MODEL, layers="auto")
        self.assertEqual(abs_boxes(plain), abs_boxes(layered))
        self.assertEqual((plain.page["width"], plain.page["height"]),
                         (layered.page["width"], layered.page["height"]))

    def test_the_routed_edges_follow_the_same_absolute_path(self):
        plain = quiet(ol.build_diagram, MODEL)
        layered = quiet(ol.build_diagram, MODEL, layers="auto")
        plain.route_edges()
        layered.route_edges()

        def paths(d):
            out = {}
            for cid, e in d._cells.items():
                if e["kind"] != "edge" or not e.get("points"):
                    continue
                ox, oy = d._origin(e["parent"])
                out[cid] = [(round(x + ox, 3), round(y + oy, 3)) for x, y in e["points"]]
            return out
        self.assertEqual(paths(plain), paths(layered))

    def test_a_layered_diagram_passes_the_strict_file_gate(self):
        """V10: the validator is layer-blind and validates everything, hidden or not."""
        with tempfile.TemporaryDirectory() as tmp:
            out = quiet(ol.write_diagram, MODEL, Path(tmp) / "layered.drawio",
                        layers="auto", hidden_layers=["routes", "security"])
            self.assertEqual(quiet(check_overlaps.main, ["--strict", str(out)]), 0)
            self.assertIn('value="Routes"', out.read_text(encoding="utf-8"))
            self.assertIn('visible="0"', out.read_text(encoding="utf-8"))


class EdgeLayerMapTests(unittest.TestCase):
    def test_every_model_edge_kind_maps_to_a_layer_or_to_the_base(self):
        self.assertEqual(sorted(ol.EDGE_LAYERS), sorted(ol.EDGE_KINDS))
        self.assertIsNone(ol.EDGE_LAYERS["attachment"])
        self.assertEqual(ol._edge_layer("analytics"), "dataflow")
        self.assertEqual(ol._edge_layer("datalake"), "dataflow")
        self.assertEqual(ol._edge_layer("management"), "management")
        self.assertIsNone(ol._edge_layer("attachment"))

    def test_an_unknown_kind_falls_back_to_the_dataflow_layer(self):
        self.assertEqual(ol._edge_layer("whatever"), "dataflow")
