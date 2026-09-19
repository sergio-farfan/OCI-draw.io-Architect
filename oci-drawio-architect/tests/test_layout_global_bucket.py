"""Layout tests for the v1.5.0 tenancy-scoped global-services bucket (C06)."""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import check_overlaps  # noqa: E402
import oci_layout as ol  # noqa: E402

from test_view_layers import quiet  # noqa: E402

MODEL = {
    "subject": "global", "region": "us-ashburn-1", "region_label": "Ashburn",
    "tenancy_name": "example-tenancy",
    "compartments": ["Network", "App", "Security"],
    "vcns": [{
        "name": "vcn-app", "cidr": "10.0.0.0/16", "subnets": [
            {"name": "sn-app", "cidr": "10.0.2.0/24", "tier": "app", "public": False, "items": [
                {"icon": "vm", "label": "App VM", "address": "app"}]}],
        "services": [{"icon": "logging", "label": "Logging", "address": "logs"},
                     {"icon": "iam", "label": "Identity Domain", "address": "idcs"}],
        "gateways": [{"icon": "service_gateway", "type": "sgw", "label": "Service\nGateway",
                      "address": "sgw"}],
    }],
    "services": [{"icon": "auditing", "label": "Audit", "address": "audit"},
                 {"icon": "policies", "label": "Policies", "address": "policies"},
                 {"icon": "vault", "label": "Vault", "address": "vault"}],
    "edges": [],
}


class DefaultOsnTests(unittest.TestCase):
    def test_the_default_keeps_the_global_services_in_the_osn(self):
        """A2 / V7: Oracle's slides 29-31 draw IAM, Audit and Policies in the OSN."""
        d = quiet(ol.build_diagram, MODEL)
        self.assertNotIn("global", d._cells)
        for cid in ("idcs", "audit", "policies", "logs", "vault"):
            self.assertEqual(d._cells[cid]["parent"], "osn", cid)
        self.assertEqual(d.layout_info["global_services"], "osn")

    def test_split_services_is_two_valued_until_the_bucket_is_asked_for(self):
        items = MODEL["services"]
        regional, local, global_items = ol._split_services(items)
        self.assertEqual([i["address"] for i in regional], ["audit", "policies", "vault"])
        self.assertEqual(local, [])
        self.assertEqual(global_items, [])


class BucketTests(unittest.TestCase):
    def build(self, model=None, **over):
        return quiet(ol.build_diagram, model or MODEL, global_services="bucket", **over)

    def test_split_services_carves_the_global_ones_out(self):
        regional, local, global_items = ol._split_services(MODEL["services"], bucket=True)
        self.assertEqual([i["address"] for i in regional], ["vault"])
        self.assertEqual([i["address"] for i in global_items], ["audit", "policies"])
        self.assertEqual(local, [])

    def test_the_bucket_is_a_page_level_sibling_of_the_region(self):
        """6.7: tenancy scope is above region scope, and page level makes the iam layer possible."""
        d = self.build()
        self.assertEqual(d._cells["global"]["parent"], "1")
        self.assertEqual(d._cells["region"]["parent"], "1")

    def test_the_bucket_sits_below_the_region_left_aligned_with_it(self):
        d = self.build()
        rx, ry, _rw, rh = d.abs_bbox("region")
        gx, gy, _gw, _gh = d.abs_bbox("global")
        self.assertEqual(gx, rx)
        self.assertEqual(gy, ry + rh + ol.GLOBAL_BAND_GAP)

    def test_the_bucket_is_a_tenancy_container_titled_after_the_tenancy(self):
        d = self.build()
        self.assertEqual(d._cells["global"]["group_type"], "tenancy")
        self.assertEqual(d._cells["global"]["label"],
                         "Global services (Tenancy: example-tenancy)")
        model = copy.deepcopy(MODEL)
        model.pop("tenancy_name")
        self.assertEqual(self.build(model)._cells["global"]["label"], "Global services")

    def test_the_key_global_never_collides_with_the_compartment_wrapper(self):
        model = copy.deepcopy(MODEL)
        model["show_compartments"] = True
        model["vcns"][0]["compartment"] = "App"
        d = self.build(model)
        self.assertIn("global", d._cells)
        self.assertIn("tenancy", d._cells)
        self.assertNotEqual(d._cells["global"]["parent"], d._cells["tenancy"]["parent"])

    def test_the_global_icons_move_out_of_the_osn_into_the_bucket(self):
        d = self.build()
        for cid in ("idcs", "audit", "policies"):
            self.assertEqual(d._cells[cid]["parent"], "global", cid)
        for cid in ("logs", "vault"):
            self.assertEqual(d._cells[cid]["parent"], "osn", cid)

    def test_the_compartment_list_is_a_text_cell_when_compartments_are_not_drawn(self):
        d = self.build()
        self.assertIn("global-compartments", d._cells)
        self.assertIn("Network", d._cells["global-compartments"]["label"])
        self.assertIn("Security", d._cells["global-compartments"]["label"])

    def test_the_compartment_list_is_omitted_when_the_containers_are_drawn(self):
        model = copy.deepcopy(MODEL)
        model["show_compartments"] = True
        model["vcns"][0]["compartment"] = "App"
        self.assertNotIn("global-compartments", self.build(model)._cells)

    def test_a_long_compartment_list_is_elided(self):
        model = copy.deepcopy(MODEL)
        model["compartments"] = [f"c{i}" for i in range(20)]
        text = self.build(model)._cells["global-compartments"]["label"]
        self.assertIn("+8 more", text)
        self.assertIn("c11", text)
        self.assertNotIn("c12", text)

    def test_no_connector_is_drawn_to_the_bucket(self):
        """6.7: a global service is not reached through the Service Gateway."""
        d = self.build()
        for e in d._cells.values():
            if e["kind"] == "edge":
                self.assertNotIn("global", (e.get("source"), e.get("target")))

    def test_the_bucket_holds_the_iam_layer_when_layers_are_on(self):
        d = self.build(layers="auto")
        self.assertIn("iam", d.layout_info["layers"]["enabled"])
        self.assertEqual(d._cells["global"]["parent"], "layer-iam")
        self.assertEqual(d._cells["idcs"]["parent"], "global")

    def test_there_is_no_iam_layer_without_the_bucket(self):
        d = quiet(ol.build_diagram, MODEL, layers="auto")
        self.assertNotIn("iam", d.layout_info["layers"]["enabled"])

    def test_the_bucket_passes_the_strict_file_gate_in_both_canvases(self):
        for locations in ("outside", "nested"):
            with tempfile.TemporaryDirectory() as tmp:
                out = quiet(ol.write_diagram, MODEL, Path(tmp) / f"{locations}.drawio",
                            global_services="bucket", locations=locations)
                self.assertEqual(quiet(check_overlaps.main, ["--strict", str(out)]), 0, locations)

    def test_the_bucket_does_not_move_the_region(self):
        plain = quiet(ol.build_diagram, MODEL)
        bucket = self.build()
        self.assertEqual(plain.abs_bbox("region")[:2], bucket.abs_bbox("region")[:2])
