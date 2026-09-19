"""Live-tenancy reader tests for the v1.5.0 metadata, provenance and filter flags."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import oci_view as ov  # noqa: E402,F401
import query_tenancy as qt  # noqa: E402


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


VCN = "ocid1.vcn.oc1..aaaavcn"
SUBNET = "ocid1.subnet.oc1..aaaasubnet"
INSTANCE = "ocid1.instance.oc1..aaaainstance"
VNIC = "ocid1.vnic.oc1..aaaavnic"
RT = "ocid1.routetable.oc1..aaaart"
NAT = "ocid1.natgateway.oc1..aaaanat"
BUCKET = "ocid1.bucket.oc1..aaaabucket"


def bundle():
    return {"networking_topology": [{"data": {"type": "NETWORKING", "entities": [
        {"id": VCN, "type": "Vcn", "display-name": "vcn-app", "cidr-block": "10.0.0.0/16",
         "lifecycle-state": "AVAILABLE"},
        {"id": SUBNET, "type": "Subnet", "display-name": "sn-app", "cidr-block": "10.0.2.0/24",
         "vcn-id": VCN, "route-table-id": RT, "lifecycle-state": "AVAILABLE"},
        {"id": INSTANCE, "type": "Instance", "display-name": "App VM", "shape": "VM.Standard.E5.Flex",
         "availability-domain": "Uocm:PHX-AD-1", "fault-domain": "FAULT-DOMAIN-2",
         "lifecycle-state": "RUNNING"},
        {"id": VNIC, "type": "Vnic", "subnet-id": SUBNET, "private-ip": "10.0.2.47",
         "public-ip": "203.0.113.10", "hostname-label": "appvm", "lifecycle-state": "AVAILABLE"},
        {"id": RT, "type": "RouteTable", "display-name": "rt-app", "vcn-id": VCN,
         "lifecycle-state": "AVAILABLE"},
        {"id": NAT, "type": "NatGateway", "display-name": "NAT", "vcn-id": VCN,
         "lifecycle-state": "AVAILABLE"}],
        "relationships": [
            {"type": "CONTAINS", "id1": VCN, "id2": SUBNET},
            {"type": "ASSOCIATED_WITH", "id1": VNIC, "id2": INSTANCE},
            {"type": "ASSOCIATED_WITH", "id1": SUBNET, "id2": RT},
            {"type": "ROUTES_TO", "id1": RT, "id2": NAT,
             "route-rule-details": {"destination": "0.0.0.0/0"}}]}}],
        "search": [{"data": {"items": [
            {"resource-type": "Bucket", "identifier": BUCKET, "display-name": "logs-bucket",
             "lifecycle-state": "ACTIVE"}]}}]}


def item(model, address):
    for vcn in model["vcns"]:
        for sn in vcn["subnets"]:
            for it in sn["items"]:
                if it["address"] == address:
                    return it
        for coll in ("services", "controls"):
            for it in vcn[coll]:
                if it["address"] == address:
                    return it
    for it in model["services"]:
        if it["address"] == address:
            return it
    raise KeyError(address)


class VnicPropagationTests(unittest.TestCase):
    def test_the_vnic_ip_reaches_its_host(self):
        """9: this is where a live tenancy's private IPs actually come from."""
        model = quiet(qt.build_model, bundle(), mode="all")
        meta = item(model, INSTANCE)["metadata"]
        self.assertEqual(meta["private_ip"], "10.0.2.47")
        self.assertEqual(meta["public_ip"], "203.0.113.10")
        self.assertEqual(meta["hostname_label"], "appvm")

    def test_the_lifecycle_state_is_surfaced_into_the_metadata(self):
        model = quiet(qt.build_model, bundle(), mode="all")
        self.assertEqual(item(model, INSTANCE)["metadata"]["lifecycle_state"], "RUNNING")

    def test_a_host_without_a_vnic_simply_has_no_ip(self):
        raw = bundle()
        entities = raw["networking_topology"][0]["data"]["entities"]
        raw["networking_topology"][0]["data"]["entities"] = [e for e in entities
                                                             if e["id"] != VNIC]
        raw["networking_topology"][0]["data"]["relationships"].append(
            {"type": "CONTAINS", "id1": SUBNET, "id2": INSTANCE})
        model = quiet(qt.build_model, raw, mode="all")
        self.assertNotIn("private_ip", item(model, INSTANCE)["metadata"])


class DiscoveryTests(unittest.TestCase):
    def test_a_route_derived_edge_is_reachability_not_an_association(self):
        model = quiet(qt.build_model, bundle(), mode="all")
        routes = [e for e in model["edges"] if e["target"] == NAT]
        self.assertTrue(routes)
        for e in routes:
            self.assertEqual(e["discovery"], "reachability")
            # INFERRED_DISCOVERY is ("heuristic",): a route-derived edge is a
            # fact, so inferred stays False exactly as it was in 1.4.0.
            self.assertIs(e["inferred"], False)

    def test_a_discovery_selector_drops_them(self):
        model = quiet(qt.build_model, bundle(), mode="all", discovery=("association", "config"))
        self.assertEqual([e for e in model["edges"] if e["discovery"] == "reachability"], [])


class ModeTests(unittest.TestCase):
    def test_the_default_mode_is_participating(self):
        """A1: a tenancy dump is not a curated set."""
        self.assertEqual(qt.DEFAULT_MODE, "participating")
        model = quiet(qt.build_model, bundle())
        self.assertEqual(model["mode"], "participating")
        with self.assertRaises(KeyError):
            item(model, BUCKET)              # a regional service with no edge

    def test_mode_all_keeps_it(self):
        self.assertTrue(item(quiet(qt.build_model, bundle(), mode="all"), BUCKET))


class FilterTests(unittest.TestCase):
    def test_a_client_side_filter_is_applied_to_a_saved_bundle(self):
        model = quiet(qt.build_model, bundle(), mode="all", filter_spec=["name=App VM"])
        self.assertTrue(item(model, INSTANCE))
        with self.assertRaises(KeyError):
            item(model, BUCKET)

    def test_a_tag_filter_with_no_tags_in_the_response_warns_and_matches_nothing(self):
        model = quiet(qt.build_model, bundle(), mode="all", filter_spec=["tag:Application=x"])
        self.assertEqual([v for v in model["vcns"] if v["subnets"]], [])
        self.assertTrue([w for w in model.get("warnings") or [] if "tag" in w.lower()],
                        model.get("warnings"))

    def test_tags_are_captured_when_the_response_carries_them(self):
        raw = bundle()
        for ent in raw["networking_topology"][0]["data"]["entities"]:
            if ent["id"] == INSTANCE:
                ent["freeform-tags"] = {"Application": "payments"}
        model = quiet(qt.build_model, raw, mode="all")
        self.assertEqual(item(model, INSTANCE)["tags"]["freeform"], {"Application": "payments"})


class DocstringTests(unittest.TestCase):
    def test_the_search_finding_is_recorded_not_left_as_a_placeholder(self):
        """Step 1's lookup must reach the module docstring with its source URL."""
        self.assertIn("docs.oracle.com", qt.__doc__)
        self.assertNotIn("<finding", qt.__doc__)


class CliTests(unittest.TestCase):
    def test_the_saved_bundle_path_accepts_every_new_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "bundle.json"
            src.write_text(json.dumps(bundle()), encoding="utf-8")
            out = Path(tmp) / "model.json"
            rc = quiet(qt.main, ["--compartment-id", "ocid1.compartment.oc1..aaaac",
                                 "--from-json", str(src), "--out", str(out),
                                 "--mode", "all", "--filter", "type=oci_core_instance",
                                 "--discovery", "association,config,reachability"])
            self.assertEqual(rc, 0)
            model = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(model["mode"], "all")
            self.assertEqual(model["filter"]["include"], ["type=oci_core_instance"])

    def test_a_tag_filter_that_empties_the_model_still_reports_why(self):
        """9: the warning naming the reason must reach the user, not be swallowed
        by the 'nothing recognisable' exit the filter itself caused."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "bundle.json"
            src.write_text(json.dumps(bundle()), encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                rc = qt.main(["--compartment-id", "ocid1.compartment.oc1..aaaac",
                              "--from-json", str(src), "--mode", "all",
                              "--tag", "Application=payments"])
            self.assertEqual(rc, 1)
            self.assertIn("tag filter", err.getvalue())
