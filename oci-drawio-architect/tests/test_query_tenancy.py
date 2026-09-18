"""Unit tests for scripts/query_tenancy.py (EXPERIMENTAL live-tenancy mode).

Run with:
    python3 -m unittest discover -s oci-drawio-architect/tests

No test talks to a tenancy: the model is built from tests/fixtures/tenancy/topology_bundle.json
and the CLI path is exercised with ``shutil.which`` / ``subprocess.run`` monkeypatched.
"""

import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
FIXTURE = TESTS_DIR / "fixtures" / "tenancy" / "topology_bundle.json"
SCRIPT = SCRIPTS_DIR / "query_tenancy.py"

sys.path.insert(0, str(SCRIPTS_DIR))
import drawio_builder as db  # noqa: E402
import parse_terraform as pt  # noqa: E402
import query_tenancy as qt  # noqa: E402

BUILDER_ICONS = set(db.ICON_ALIASES) | set(db.ICON_MAP)
COMP = "ocid1.compartment.oc1..aaaaaaaashopprod000001"
VCN = "ocid1.vcn.oc1.eu-frankfurt-1.amaaaaaavcnshop000001"
INSTANCE = "ocid1.instance.oc1.eu-frankfurt-1.anaaaaaaappsrv000001"
# A complete OCID (type.realm.region.hash); the 12-char truncated form "ocid1.vcn.oc..." never matches.
LONG_OCID_RE = re.compile(r"ocid1\.[a-z0-9]+\.[a-z0-9]+\.[a-z0-9-]*\.[a-z0-9]+")


def subnet(vcn, name):
    for sn in vcn["subnets"]:
        if sn["name"] == name:
            return sn
    raise AssertionError(f"subnet {name!r} not found")


class BundleModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = qt.load_bundle(FIXTURE)
        cls.model = qt.build_model(cls.bundle, COMP, None, None, True, str(FIXTURE))
        cls.vcn = cls.model["vcns"][0]

    def test_validates_and_icons_exist(self):
        self.assertEqual(pt.validate_model(self.model, BUILDER_ICONS), [])

    def test_header(self):
        m = self.model
        self.assertEqual(m["source"]["mode"], "tenancy")
        self.assertEqual(m["region"], "eu-frankfurt-1")            # derived from the OCIDs
        self.assertEqual(m["region_label"], "Frankfurt")
        self.assertEqual(m["compartment"], "shop-prod")            # search item of type Compartment
        self.assertEqual(m["compartments"], ["shop-prod"])
        self.assertEqual(m["subject"], "vcn-shop")

    def test_vcn_and_subnets(self):
        self.assertEqual(len(self.model["vcns"]), 1)
        self.assertEqual((self.vcn["name"], self.vcn["address"], self.vcn["cidr"], self.vcn["compartment"]),
                         ("vcn-shop", VCN, "10.0.0.0/16", "shop-prod"))
        rows = [(s["name"], s["cidr"], s["tier"], s["public"]) for s in self.vcn["subnets"]]
        self.assertEqual(rows, [("sn-lb-public", "10.0.0.0/24", "lb", True),
                                ("sn-app", "10.0.1.0/24", "app", False),          # camelCase entity
                                ("sn-database", "10.0.2.0/24", "data", False)])
        for s in self.vcn["subnets"]:
            self.assertTrue(s["address"].startswith("ocid1.subnet."))

    def test_items_placed_by_subnet_id_and_vnic_association(self):
        app = subnet(self.vcn, "sn-app")["items"]
        self.assertEqual([(i["icon"], i["label"], i["address"]) for i in app],
                         [("vm", "app-server-1\nVM.Standard.E4.Flex", INSTANCE)])   # via Vnic ASSOCIATED_WITH
        lb = subnet(self.vcn, "sn-lb-public")["items"]
        self.assertEqual([(i["icon"], i["label"]) for i in lb], [("load_balancer", "lb-shop")])   # subnet-ids[0]
        data = subnet(self.vcn, "sn-database")["items"]
        self.assertEqual([(i["icon"], i["label"]) for i in data], [("autonomous_db", "adb-shop")])

    def test_gateways_including_ocid_derived_type(self):
        gws = {g["type"]: g for g in self.vcn["gateways"]}
        self.assertEqual(set(gws), {"igw", "nat", "sgw"})
        self.assertEqual(gws["nat"]["label"], "nat-shop")                        # entity without 'type' key
        self.assertTrue(gws["nat"]["address"].startswith("ocid1.natgateway."))

    def test_drg_attachments_from_topology(self):
        drgs = self.model["drgs"]
        self.assertEqual([(d["name"], d["address"][:9]) for d in drgs], [("drg-shop", "ocid1.drg")])
        atts = drgs[0]["attachments"]
        self.assertEqual([a["type"] for a in atts], ["vcn", "ipsec"])
        self.assertTrue(atts[0]["address"].startswith("ocid1.drgattachment."))
        self.assertEqual((atts[0]["label"], atts[0]["vcn"]), ("drg-att-shop", "vcn-shop"))
        cpe = self.model["hub"]["items"][0]["address"]
        self.assertEqual((atts[1]["label"], atts[1]["target"]), ("vpn-hq", cpe))
        self.assertTrue(atts[1]["address"].startswith("ocid1.ipsecconnection."))

    def test_hub(self):
        hub = self.model["hub"]
        self.assertEqual(hub["name"], "On-premises")
        self.assertIsNone(hub["link_label"])
        self.assertEqual([(i["icon"], i["label"]) for i in hub["items"]], [("cpe", "cpe-hq")])

    def test_search_items_become_services_dead_and_helper_entities_are_dropped(self):
        svc = {i["type"]: i["label"] for i in self.vcn["services"]}
        self.assertEqual(svc, {"oci_objectstorage_bucket": "shop-assets", "oci_kms_vault": "vault-shop",
                               "oci_streaming_stream": "orders"})
        ctl = {i["type"] for i in self.vcn["controls"]}
        self.assertEqual(ctl, {"oci_core_route_table", "oci_core_security_list"})
        dump = json.dumps(self.model)
        self.assertNotIn("old-server", dump)                                     # TERMINATED
        self.assertNotIn("custom-image", dump)                                   # unmapped resource-type
        self.assertNotIn("ocid1.vnic.", dump)
        self.assertNotIn("ocid1.privateip.", dump)
        self.assertEqual(self.model["services"], [])

    def test_edges(self):
        edges = {(e["source"], e["target"]): e for e in self.model["edges"]}
        lb_sn = subnet(self.vcn, "sn-lb-public")["address"]
        app_sn = subnet(self.vcn, "sn-app")["address"]
        igw = next(g["address"] for g in self.vcn["gateways"] if g["type"] == "igw")
        nat = next(g["address"] for g in self.vcn["gateways"] if g["type"] == "nat")
        # ROUTES_TO from a route table (mapped to the subnet through route-table-id) and from a subnet directly
        self.assertEqual((edges[(lb_sn, igw)]["label"], edges[(lb_sn, igw)]["kind"], edges[(lb_sn, igw)]["inferred"]),
                         ("0.0.0.0/0", "control", False))
        self.assertEqual(edges[(app_sn, nat)]["label"], "0.0.0.0/0")             # camelCase routeRuleDetails
        lb = subnet(self.vcn, "sn-lb-public")["items"][0]["address"]
        self.assertTrue(edges[(lb, INSTANCE)]["inferred"])
        adb = subnet(self.vcn, "sn-database")["items"][0]["address"]
        self.assertEqual(edges[(INSTANCE, adb)]["label"], "1522")
        self.assertEqual(len(edges), 4)

    def test_vcn_filter(self):
        model = qt.build_model(self.bundle, COMP, VCN)
        self.assertEqual([v["address"] for v in model["vcns"]], [VCN])
        self.assertIsNone(qt.build_model(self.bundle, COMP, "ocid1.vcn.oc1..nope"))

    def test_no_inferred_edges(self):
        model = qt.build_model(self.bundle, COMP, None, None, False)
        self.assertTrue(all(not e["inferred"] for e in model["edges"]))
        self.assertEqual(len(model["edges"]), 2)


class HelperTests(unittest.TestCase):
    def test_short_ocid(self):
        text = f"failed for {VCN} and {COMP}"
        out = qt.short_ocid(text)
        self.assertNotIn(VCN, out)
        self.assertIn(VCN[:12] + "...", out)
        self.assertIn(COMP[:12] + "...", out)
        self.assertEqual(qt.short_ocid("no ids here"), "no ids here")
        self.assertIsNone(LONG_OCID_RE.search(out))

    def test_get_tolerates_key_styles(self):
        self.assertEqual(qt.get({"display-name": "a"}, "display_name"), "a")
        self.assertEqual(qt.get({"displayName": "b"}, "display_name"), "b")
        self.assertEqual(qt.get({"display_name": "c"}, "display_name"), "c")
        self.assertEqual(qt.get({"x": None}, "x", default="d"), "d")
        self.assertEqual(qt.get({"identifier": "i"}, "id", "identifier"), "i")

    def test_entity_kind(self):
        self.assertEqual(qt.entity_kind({"type": "InternetGateway"}), "internetgateway")
        self.assertEqual(qt.entity_kind({"resource-type": "AutonomousDatabase"}), "autonomousdatabase")
        self.assertEqual(qt.entity_kind({"id": "ocid1.natgateway.oc1.eu-frankfurt-1.abc"}), "natgateway")
        self.assertEqual(qt.entity_kind({"identifier": "ocid1.bucket.oc1.iad.abc"}), "bucket")
        self.assertEqual(qt.entity_kind({}), "")

    def test_region_from_ocid(self):
        self.assertEqual(qt.region_from_ocid(VCN), "eu-frankfurt-1")
        self.assertEqual(qt.region_from_ocid("ocid1.instance.oc1.iad.abc"), "us-ashburn-1")
        self.assertIsNone(qt.region_from_ocid(COMP))
        self.assertIsNone(qt.region_from_ocid("garbage"))

    def test_classify_response_and_load_bundle_single_response(self):
        bundle = json.loads(FIXTURE.read_text())
        self.assertEqual(qt.classify_response(bundle["vcn_topology"]), "vcn_topology")
        self.assertEqual(qt.classify_response(bundle["networking_topology"]), "networking_topology")
        self.assertEqual(qt.classify_response(bundle["search"]), "search")
        self.assertIsNone(qt.classify_response({"data": {"x": 1}}))
        with tempfile.TemporaryDirectory() as tmp:
            single = Path(tmp) / "vcn.json"
            single.write_text(json.dumps(bundle["vcn_topology"]))
            loaded = qt.load_bundle(single)
            self.assertEqual(len(loaded["vcn_topology"]), 1)
            self.assertEqual(loaded["search"], [])
            model = qt.build_model(loaded, COMP)
            self.assertEqual(model["vcns"][0]["name"], "vcn-shop")
            # CPE/IPSec live in networking-topology; the VCN topology alone yields a DRG with its VCN attachment
            self.assertIsNone(model["hub"])
            self.assertEqual([d["name"] for d in model["drgs"]], ["drg-shop"])
            self.assertEqual([a["type"] for a in model["drgs"][0]["attachments"]], ["vcn"])
            bad = Path(tmp) / "bad.json"
            bad.write_text("{}")
            with self.assertRaises(pt.InputError):
                qt.load_bundle(bad)
            bad.write_text("not json")
            with self.assertRaises(pt.InputError):
                qt.load_bundle(bad)

    def test_peer_id_is_a_reference_field(self):
        norm = qt.normalise_entity({"type": "LocalPeeringGateway", "id": "ocid1.localpeeringgateway.oc1.eu-frankfurt-1.a",
                                    "peer-id": "ocid1.localpeeringgateway.oc1.eu-frankfurt-1.b"})
        self.assertEqual(norm["refs"]["peer_id"], ["ocid1.localpeeringgateway.oc1.eu-frankfurt-1.b"])

    def test_every_entity_type_maps_to_a_known_resource_type(self):
        containers = {pt.VCN_TYPE, pt.SUBNET_TYPE, pt.COMPARTMENT_TYPE, pt.DRG_ATTACHMENT_TYPE}
        for kind, rtype in qt.ENTITY_TF_TYPES.items():
            with self.subTest(kind=kind):
                self.assertTrue(rtype in pt.RESOURCE_ICONS or rtype in containers, rtype)


class FakeProc:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


class LiveModeTests(unittest.TestCase):
    """The CLI path with ``oci`` faked: command construction, timeouts and failure handling."""

    def setUp(self):
        self.bundle = json.loads(FIXTURE.read_text())
        self.calls = []
        self._stack = contextlib.ExitStack()
        self._stack.enter_context(mock.patch.object(qt.shutil, "which", return_value="/fake/bin/oci"))
        self.addCleanup(self._stack.close)

    def fake_run(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if "vcn-topology" in cmd:
            return FakeProc(json.dumps(self.bundle["vcn_topology"]))
        if "networking-topology" in cmd:
            return FakeProc(json.dumps(self.bundle["networking_topology"]))
        if "structured-search" in cmd:
            return FakeProc(json.dumps(self.bundle["search"]))
        return FakeProc("", 1, "unexpected")

    def test_commands_and_model(self):
        buf, err = io.StringIO(), io.StringIO()
        with mock.patch.object(qt.subprocess, "run", side_effect=self.fake_run), \
                contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            rc = qt.main(["--compartment-id", COMP, "--vcn-id", VCN, "--profile", "TEST", "--region", "eu-frankfurt-1"])
        self.assertEqual(rc, 0, err.getvalue())
        self.assertEqual(len(self.calls), 3)
        for cmd, kwargs in self.calls:
            self.assertEqual(cmd[0], "/fake/bin/oci")
            self.assertEqual(cmd[cmd.index("--output") + 1], "json")
            self.assertEqual(cmd[cmd.index("--profile") + 1], "TEST")
            self.assertEqual(cmd[cmd.index("--region") + 1], "eu-frankfurt-1")
            self.assertEqual(kwargs["timeout"], qt.CLI_TIMEOUT)
            self.assertEqual(qt.CLI_TIMEOUT, 30.0)
        first = self.calls[0][0]
        self.assertEqual(first[1:4], ["network", "vcn-topology", "get"])
        self.assertEqual(first[first.index("--vcn-id") + 1], VCN)
        search = self.calls[2][0]
        self.assertIn(f"query all resources where compartmentId = '{COMP}'", search)
        model = json.loads(buf.getvalue())
        self.assertEqual(model["vcns"][0]["name"], "vcn-shop")
        self.assertEqual(model["source"]["mode"], "tenancy")
        self.assertTrue(model["source"]["path"].startswith("oci-cli:ocid1.compar..."))
        self.assertIsNone(LONG_OCID_RE.search(err.getvalue()), err.getvalue())

    def test_save_raw_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(qt.subprocess, "run", side_effect=self.fake_run), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            raw = Path(tmp) / "raw.json"
            rc = qt.main(["--compartment-id", COMP, "--save-raw", str(raw), "--out", str(Path(tmp) / "m.json")])
            self.assertEqual(rc, 0)
            saved = qt.load_bundle(raw)
            self.assertEqual(len(saved["networking_topology"]), 1)
            self.assertEqual(saved["vcn_topology"], [])                      # no --vcn-id -> not queried

    def test_cli_failures_are_warnings_and_exit_1_when_nothing_returned(self):
        err = io.StringIO()
        with mock.patch.object(qt.subprocess, "run", return_value=FakeProc("", 1, f"ServiceError for {COMP}")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = qt.main(["--compartment-id", COMP])
        self.assertEqual(rc, 1)
        self.assertIn("exited 1", err.getvalue())
        self.assertIn("No data returned", err.getvalue())
        self.assertIsNone(LONG_OCID_RE.search(err.getvalue()), err.getvalue())

    def test_timeout_is_reported(self):
        err = io.StringIO()
        with mock.patch.object(qt.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(cmd="oci", timeout=30)), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = qt.main(["--compartment-id", COMP])
        self.assertEqual(rc, 1)
        self.assertIn("timed out after 30s", err.getvalue())

    def test_missing_cli_exits_1_without_running_anything(self):
        err = io.StringIO()
        with mock.patch.object(qt.shutil, "which", return_value=None), \
                mock.patch.object(qt.subprocess, "run", side_effect=AssertionError("must not run")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = qt.main(["--compartment-id", COMP])
        self.assertEqual(rc, 1)
        self.assertIn("oci CLI not found on PATH", err.getvalue())


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=60)

    def test_help_mentions_experimental(self):
        proc = self.run_cli("-h")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("EXPERIMENTAL", proc.stdout)

    def test_from_json_prints_model_and_truncates_ocids_on_stderr(self):
        proc = self.run_cli("--compartment-id", COMP, "--from-json", str(FIXTURE))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        model = json.loads(proc.stdout)
        self.assertEqual(model["subject"], "vcn-shop")
        self.assertIn("vcn-shop: 1 VCN(s)", proc.stderr)
        self.assertIsNone(LONG_OCID_RE.search(proc.stderr), proc.stderr)

    def test_out_and_vcn_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "model.json"
            proc = self.run_cli("--compartment-id", COMP, "--vcn-id", VCN, "--from-json", str(FIXTURE),
                                "--out", str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout, "")
            self.assertEqual(json.loads(out.read_text())["vcns"][0]["address"], VCN)
        proc = self.run_cli("--compartment-id", COMP, "--vcn-id", "ocid1.vcn.oc1..nope", "--from-json", str(FIXTURE))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("No VCN matches ocid1.vcn.oc...", proc.stderr)

    def test_bad_paths_exit_2(self):
        proc = self.run_cli("--compartment-id", COMP, "--from-json", str(FIXTURE.parent / "missing.json"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("does not exist", proc.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{}")
            proc = self.run_cli("--compartment-id", COMP, "--from-json", str(bad))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no topology or search response", proc.stderr)

    def test_compartment_id_is_required(self):
        proc = self.run_cli("--from-json", str(FIXTURE))
        self.assertEqual(proc.returncode, 2)             # argparse usage error
        self.assertIn("--compartment-id", proc.stderr)


if __name__ == "__main__":
    unittest.main()
