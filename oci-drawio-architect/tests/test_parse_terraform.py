"""Unit tests for scripts/parse_terraform.py.

Run with:
    python3 -m unittest discover -s oci-drawio-architect/tests

Fixtures live under tests/fixtures/terraform/:
    three_tier/   HCL project: one VCN, lb/app/data subnets, instance, ADB, LB, IGW/NAT/SGW,
                  DRG + IPSec, bucket and vault (variables, locals, cidrsubnet(), heredocs).
    tfvars_map/   for_each-driven VCNs whose names/CIDRs only exist in *.auto.tfvars.
    hub_spoke/    two VCNs, one DRG with VCN / FastConnect / RPC attachments, an LPG pair
                  and a regional log group with no single VCN to attach it to.
    plan.json     hand-written 'terraform show -json tfplan' with unknown values resolved
                  through configuration references, OCID links and nested modules.
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
FIXTURES = TESTS_DIR / "fixtures" / "terraform"
SCRIPT = SCRIPTS_DIR / "parse_terraform.py"

sys.path.insert(0, str(SCRIPTS_DIR))
import detect_settings as ds  # noqa: E402
import drawio_builder as db  # noqa: E402
import parse_terraform as pt  # noqa: E402

BUILDER_ICONS = set(db.ICON_ALIASES) | set(db.ICON_MAP)


def model_icons(model):
    for item in (model.get("hub") or {}).get("items") or []:
        yield item["icon"]
    for vcn in model["vcns"]:
        for sn in vcn["subnets"]:
            for item in sn["items"]:
                yield item["icon"]
        for coll in ("services", "controls", "gateways"):
            for item in vcn[coll]:
                yield item["icon"]
    for item in model["services"]:
        yield item["icon"]


def find_subnet(vcn, name):
    for sn in vcn["subnets"]:
        if sn["name"] == name:
            return sn
    raise AssertionError(f"subnet {name!r} not found in {[s['name'] for s in vcn['subnets']]}")


def items_by_type(coll):
    return {item["type"]: item for item in coll}


# ---------------------------------------------------------------------------
# HCL mode: three-tier fixture
# ---------------------------------------------------------------------------

class HclThreeTierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = pt.parse_terraform_dir(FIXTURES / "three_tier")
        cls.vcn = cls.model["vcns"][0]

    def test_validates_against_schema_and_builder_icons(self):
        self.assertEqual(pt.validate_model(self.model, BUILDER_ICONS), [])
        for icon in model_icons(self.model):
            self.assertIn(icon, BUILDER_ICONS)

    def test_header_fields(self):
        m = self.model
        self.assertEqual(m["schema_version"], pt.SCHEMA_VERSION)
        self.assertEqual(m["subject"], "vcn-shop")
        self.assertEqual(m["region"], "eu-frankfurt-1")
        self.assertEqual(m["region_label"], "Frankfurt")
        self.assertEqual(m["compartment"], "shop-prod")
        self.assertEqual(m["compartments"], ["shop-prod"])
        self.assertIsNone(m["tenancy_name"])
        self.assertEqual(m["source"]["mode"], "hcl")
        self.assertTrue(m["source"]["path"].endswith("three_tier"))

    def test_single_vcn_with_resolved_name_cidr_and_compartment(self):
        self.assertEqual(len(self.model["vcns"]), 1)
        self.assertEqual(self.vcn["name"], "vcn-shop")          # var.vcn_name via terraform.tfvars
        self.assertEqual(self.vcn["address"], "oci_core_vcn.main")
        self.assertEqual(self.vcn["cidr"], "10.0.0.0/16")       # cidr_blocks = [var.vcn_cidr]
        self.assertEqual(self.vcn["compartment"], "shop-prod")  # oci_identity_compartment.app.id

    def test_subnets_keep_definition_order_with_cidr_tier_and_public(self):
        subnets = self.vcn["subnets"]
        self.assertEqual([s["name"] for s in subnets], ["sn-lb-public", "sn-app", "sn-database"])
        self.assertEqual([s["address"] for s in subnets],
                         ["oci_core_subnet.lb", "oci_core_subnet.app", "oci_core_subnet.db"])
        # local.subnet_cidrs["lb"] / .app are cidrsubnet(var.vcn_cidr, 8, n); "db" is a literal.
        self.assertEqual([s["cidr"] for s in subnets], ["10.0.0.0/24", "10.0.1.0/24", "10.0.2.0/24"])
        self.assertEqual([s["tier"] for s in subnets], ["lb", "app", "data"])
        self.assertEqual([s["public"] for s in subnets], [True, False, False])

    def test_items_are_placed_in_their_subnets(self):
        lb = find_subnet(self.vcn, "sn-lb-public")["items"]
        app = find_subnet(self.vcn, "sn-app")["items"]
        data = find_subnet(self.vcn, "sn-database")["items"]
        self.assertEqual([(i["icon"], i["label"], i["address"]) for i in lb],
                         [("load_balancer", "lb-shop", "oci_load_balancer_load_balancer.public")])
        self.assertEqual(len(app), 1)
        inst = app[0]
        self.assertEqual(inst["icon"], "vm")
        self.assertEqual(inst["label"], "app-server\nVM.Standard.E4.Flex")   # display_name + shape (var.app_shape)
        self.assertEqual(inst["address"], "oci_core_instance.app")           # base address, count kept as metadata
        self.assertEqual(inst["metadata"]["count"], 2)
        self.assertEqual(inst["metadata"]["ocpus"], 2)                       # nested shape_config block
        self.assertEqual([(i["icon"], i["label"]) for i in data], [("autonomous_db", "adb-shop")])
        self.assertEqual(data[0]["metadata"]["db_workload"], "OLTP")

    def test_gateways(self):
        gws = {g["type"]: g for g in self.vcn["gateways"]}
        self.assertEqual(set(gws), {"igw", "nat", "sgw"})          # the DRG is no longer a VCN gateway
        self.assertEqual(gws["igw"]["label"], "igw-shop")
        self.assertEqual(gws["igw"]["icon"], "internet_gateway")
        self.assertEqual(gws["nat"]["icon"], "nat_gateway")
        self.assertEqual(gws["sgw"]["icon"], "service_gateway")
        self.assertNotIn("peer", gws["sgw"])

    def test_hub_holds_only_the_on_premises_side(self):
        hub = self.model["hub"]
        self.assertEqual(hub["name"], "On-premises")
        self.assertIsNone(hub["link_label"])
        self.assertEqual([(i["icon"], i["label"], i["address"]) for i in hub["items"]],
                         [("cpe", "cpe-hq", "oci_core_cpe.onprem")])

    def test_drgs_and_attachments(self):
        m = self.model
        self.assertEqual(m["schema_version"], 2)
        self.assertEqual(m["drg_style"], "auto")
        self.assertEqual(m["drgs"], [{
            "name": "drg-shop", "address": "oci_core_drg.drg", "label": "DRG\ndrg-shop",
            "attachments": [
                {"type": "vcn", "address": "oci_core_drg_attachment.vcn", "label": "drg-att-shop",
                 "vcn": "vcn-shop", "target": None},
                {"type": "ipsec", "address": "oci_core_ipsec.vpn@oci_core_drg.drg", "label": "vpn-hq",
                 "vcn": None, "target": "oci_core_cpe.onprem"},
            ]}])
        self.assertIn("oci_core_drg.drg", list(pt.model_addresses(m)))
        self.assertIn("oci_core_ipsec.vpn@oci_core_drg.drg", list(pt.model_addresses(m)))

    def test_regional_services_attach_to_the_single_vcn(self):
        svc = items_by_type(self.vcn["services"])
        self.assertEqual(set(svc), {"oci_objectstorage_bucket", "oci_kms_vault"})
        self.assertEqual(svc["oci_objectstorage_bucket"]["icon"], "buckets")
        self.assertEqual(svc["oci_objectstorage_bucket"]["label"], "shop-assets")   # name attr
        self.assertEqual(svc["oci_kms_vault"]["icon"], "vault")
        self.assertTrue(svc["oci_objectstorage_bucket"]["regional"])
        self.assertTrue(svc["oci_kms_vault"]["regional"])
        self.assertEqual(self.model["services"], [])

    def test_network_controls_are_separated(self):
        ctl = items_by_type(self.vcn["controls"])
        self.assertEqual(set(ctl), {"oci_core_route_table", "oci_core_security_list",
                                    "oci_core_network_security_group"})
        self.assertEqual(ctl["oci_core_network_security_group"]["icon"], "nsg")

    def test_edges(self):
        edges = {(e["source"], e["target"]): e for e in self.model["edges"]}
        self.assertNotIn(("oci_core_cpe.onprem", "oci_core_drg.drg"), edges)   # drawn from drgs[] by the layout
        app_db = edges[("oci_core_instance.app", "oci_database_autonomous_database.shop")]
        self.assertEqual((app_db["label"], app_db["kind"], app_db["inferred"]), ("1522", "data", True))
        lb_app = edges[("oci_load_balancer_load_balancer.public", "oci_core_instance.app")]
        self.assertEqual((lb_app["label"], lb_app["inferred"]), ("443", True))
        self.assertEqual(len(edges), 2)

    def test_no_inferred_edges_keeps_only_reference_backed_ones(self):
        model = pt.parse_terraform_dir(FIXTURES / "three_tier", inferred_edges=False)
        self.assertEqual(model["edges"], [])

    def test_dot_terraform_data_blocks_and_lb_children_are_ignored(self):
        dump = json.dumps(self.model)
        self.assertNotIn("must-not-appear", dump)          # .terraform/modules/... is never read
        self.assertNotIn('"data.', dump)                   # data sources are not resources
        for bad in ("oci_load_balancer_listener", "oci_load_balancer_backend_set"):
            self.assertNotIn(bad, dump)


# ---------------------------------------------------------------------------
# HCL mode: tfvars-driven VCN map
# ---------------------------------------------------------------------------

class HclTfvarsMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = pt.parse_terraform_dir(FIXTURES / "tfvars_map")

    def test_valid(self):
        self.assertEqual(pt.validate_model(self.model, BUILDER_ICONS), [])

    def test_vcns_and_subnets_come_from_the_tfvars_map(self):
        vcns = {v["name"]: v for v in self.model["vcns"]}
        self.assertEqual(set(vcns), {"vcn-hub", "vcn-spoke-app"})
        self.assertNotIn("this", vcns)                                       # for_each placeholder dropped
        self.assertEqual(vcns["vcn-hub"]["cidr"], "10.10.0.0/16")
        self.assertEqual(vcns["vcn-spoke-app"]["cidr"], "10.20.0.0/16")
        hub = vcns["vcn-hub"]["subnets"]
        self.assertEqual([(s["name"], s["cidr"], s["tier"], s["public"]) for s in hub],
                         [("sn-mgmt", "10.10.0.0/24", "mgmt", False), ("sn-web", "10.10.1.0/24", "lb", True)])
        spoke = vcns["vcn-spoke-app"]["subnets"]
        self.assertEqual([(s["name"], s["tier"]) for s in spoke], [("sn-app", "app")])
        self.assertEqual(self.model["subject"], "tfvars_map")               # several VCNs -> directory name

    def test_unplaceable_item_goes_to_top_level_services(self):
        self.assertEqual([(i["icon"], i["label"]) for i in self.model["services"]], [("bastion", "bastion-ops")])
        self.assertEqual(self.model["hub"], None)


# ---------------------------------------------------------------------------
# HCL mode: hub-and-spoke with a region-level DRG
# ---------------------------------------------------------------------------

class HclHubSpokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = pt.parse_terraform_dir(FIXTURES / "hub_spoke")
        cls.vcns = {v["name"]: v for v in cls.model["vcns"]}

    def test_valid(self):
        self.assertEqual(pt.validate_model(self.model, BUILDER_ICONS), [])
        self.assertEqual(set(self.vcns), {"vcn-hub", "vcn-spoke"})
        self.assertEqual(self.model["subject"], "hub_spoke")

    def test_drg_with_four_typed_attachments(self):
        drgs = self.model["drgs"]
        self.assertEqual(len(drgs), 1)
        d = drgs[0]
        self.assertEqual((d["name"], d["address"]), ("drg-core", "oci_core_drg.core"))
        atts = {a["address"]: a for a in d["attachments"]}
        self.assertEqual([a["type"] for a in d["attachments"]], ["vcn", "vcn", "virtual_circuit", "rpc"])
        self.assertEqual((atts["oci_core_drg_attachment.hub"]["vcn"], atts["oci_core_drg_attachment.hub"]["label"]),
                         ("vcn-hub", "att-hub"))
        self.assertEqual(atts["oci_core_drg_attachment.spoke"]["vcn"], "vcn-spoke")
        fc = atts["oci_core_virtual_circuit.fc@oci_core_drg.core"]
        self.assertEqual((fc["label"], fc["target"]), ("fc-hq", "oci_core_virtual_circuit.fc"))
        rpc = atts["oci_core_remote_peering_connection.dr@oci_core_drg.core"]
        self.assertEqual((rpc["label"], rpc["target"]), ("rpc-dr", "oci_core_remote_peering_connection.dr"))

    def test_hub_has_the_virtual_circuit_and_the_rpc_peer(self):
        hub = self.model["hub"]
        self.assertEqual(hub["name"], "On-premises")
        self.assertEqual([(i["icon"], i["label"]) for i in hub["items"]],
                         [("cpe", "fc-hq"), ("remote_peering_gateway", "rpc-dr")])
        self.assertNotIn("drg", [i["icon"] for i in hub["items"]])

    def test_lpg_pair_and_local_peering_edge(self):
        hub_gws = {g["type"]: g for g in self.vcns["vcn-hub"]["gateways"]}
        spoke_gws = {g["type"]: g for g in self.vcns["vcn-spoke"]["gateways"]}
        # only the requestor declares peer_id; both sides must carry the peer so each
        # LPG lands on the border facing the other VCN
        self.assertEqual(hub_gws["lpg"]["peer"], "oci_core_local_peering_gateway.spoke")
        self.assertEqual(spoke_gws["lpg"]["peer"], "oci_core_local_peering_gateway.hub")
        self.assertEqual(set(spoke_gws), {"sgw", "lpg"})
        peering = [e for e in self.model["edges"] if e["label"] == "Local Peering"]
        self.assertEqual(peering, [pt.new_edge("oci_core_local_peering_gateway.hub",
                                               "oci_core_local_peering_gateway.spoke",
                                               "Local Peering", "attachment", False)])

    def test_regional_service_without_a_single_vcn_goes_to_model_services(self):
        self.assertEqual([(i["icon"], i["label"], i["regional"]) for i in self.model["services"]],
                         [("logging", "lg-app", True)])

    def test_select_vcn_prunes_attachments_of_dropped_vcns(self):
        model = pt.parse_terraform_dir(FIXTURES / "hub_spoke")
        self.assertTrue(pt.select_vcn(model, "vcn-spoke"))
        atts = model["drgs"][0]["attachments"]
        self.assertEqual([a["type"] for a in atts], ["vcn", "virtual_circuit", "rpc"])
        self.assertEqual(atts[0]["vcn"], "vcn-spoke")
        self.assertEqual(pt.validate_model(model, BUILDER_ICONS), [])
        self.assertEqual([e["label"] for e in model["edges"]], [])      # the peering edge lost an endpoint

    def test_summary_mentions_drgs(self):
        self.assertIn("1 DRG(s) / 4 attachment(s)", pt.summarise(self.model))


# ---------------------------------------------------------------------------
# HCL mode: a DRG attachment pointing at a for_each VCN whose name lives in tfvars
# ---------------------------------------------------------------------------

DRG_FOR_EACH_MAIN_TF = """
variable "compartment_ocid" {
  type = string
}

variable "vcns" {
  type = any
}

resource "oci_core_vcn" "this" {
  for_each       = var.vcns
  compartment_id = var.compartment_ocid
  display_name   = each.value.display_name
  cidr_blocks    = [each.value.cidr]
}

resource "oci_core_drg" "core" {
  compartment_id = var.compartment_ocid
  display_name   = "drg-core"
}

%s"""

DRG_FOR_EACH_ATTACHMENT = """
resource "oci_core_drg_attachment" "hub" {
  drg_id       = oci_core_drg.core.id
  display_name = "att-hub"
  network_details {
    id   = oci_core_vcn.this["hub"].id
    type = "VCN"
  }
}
"""

DRG_FOR_EACH_TFVARS = """
compartment_ocid = "ocid1.compartment.oc1..aaaamap"

vcns = {
%s}
"""

VCN_ENTRY = """  %s = {
    display_name = "%s"
    cidr         = "%s"
    subnets = {
      mgmt = { name = "sn-%s", cidr = "%s", is_public = false }
    }
  }
"""


class PublicVirtualCircuitTests(unittest.TestCase):
    """A public FastConnect circuit peers with Oracle's public services, not with a DRG."""

    MAIN_TF = """
provider "oci" {
  region = "eu-frankfurt-1"
}

variable "drg_ocid" {
  type = string
}

resource "oci_core_vcn" "a" {
  display_name = "vcn-a"
  cidr_blocks  = ["10.0.0.0/16"]
}

resource "oci_core_drg" "core" {
  display_name = "drg-core"
}

resource "oci_core_drg_attachment" "a" {
  drg_id       = oci_core_drg.core.id
  display_name = "att-a"
  network_details {
    id   = oci_core_vcn.a.id
    type = "VCN"
  }
}

resource "oci_core_virtual_circuit" "public" {
  display_name = "fc-public"
  type         = "PUBLIC"
}

resource "oci_core_virtual_circuit" "private" {
  display_name = "fc-private"
  type         = "PRIVATE"
  gateway_id   = var.drg_ocid
}
"""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "main.tf").write_text(cls.MAIN_TF)
            cls.model = pt.parse_terraform_dir(Path(tmp))

    def test_only_the_private_circuit_becomes_a_drg_attachment(self):
        atts = self.model["drgs"][0]["attachments"]
        self.assertEqual([(a["type"], a["label"]) for a in atts],
                         [("vcn", "att-a"), ("virtual_circuit", "fc-private")])
        self.assertNotIn("oci_core_virtual_circuit.public@oci_core_drg.core", [a["address"] for a in atts])
        self.assertEqual(pt.validate_model(self.model, BUILDER_ICONS), [])

    def test_both_circuits_stay_on_premises_items(self):
        self.assertEqual([i["label"] for i in self.model["hub"]["items"]], ["fc-public", "fc-private"])

    def test_the_diagram_of_that_model_validates(self):
        import oci_layout as ol
        with contextlib.redirect_stderr(io.StringIO()):
            d = ol.build_diagram(self.model)
        self.assertEqual([m for m in d.validate(strict=True)
                          if not m.split("] ")[-1].startswith("WARNING")], [])


class LpgPeerMirrorTests(unittest.TestCase):
    """``peer`` is symmetric even though only the requestor declares ``peer_id``."""

    @staticmethod
    def _gw(model, address):
        return next(g for v in model["vcns"] for g in v["gateways"] if g["address"] == address)

    def parse(self, peer_a="peer_id     = oci_core_local_peering_gateway.b.id", peer_b=""):
        body = """
provider "oci" {
  region = "eu-frankfurt-1"
}

resource "oci_core_vcn" "a" {
  display_name = "vcn-a"
  cidr_blocks  = ["10.0.0.0/16"]
}

resource "oci_core_vcn" "b" {
  display_name = "vcn-b"
  cidr_blocks  = ["10.1.0.0/16"]
}

resource "oci_core_local_peering_gateway" "a" {
  vcn_id       = oci_core_vcn.a.id
  display_name = "lpg-a"
  %s
}

resource "oci_core_local_peering_gateway" "b" {
  vcn_id       = oci_core_vcn.b.id
  display_name = "lpg-b"
  %s
}
""" % (peer_a, peer_b)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "main.tf").write_text(body)
            return pt.parse_terraform_dir(Path(tmp))

    def test_the_acceptor_gets_the_peer_of_the_requestor(self):
        model = self.parse()
        self.assertEqual(self._gw(model, "oci_core_local_peering_gateway.a")["peer"],
                         "oci_core_local_peering_gateway.b")
        self.assertEqual(self._gw(model, "oci_core_local_peering_gateway.b")["peer"],
                         "oci_core_local_peering_gateway.a")
        self.assertEqual([e["label"] for e in model["edges"] if e["label"] == "Local Peering"], ["Local Peering"])
        self.assertEqual(pt.validate_model(model, BUILDER_ICONS), [])

    def test_both_sides_declaring_peer_id_are_left_alone(self):
        model = self.parse(peer_b="peer_id     = oci_core_local_peering_gateway.a.id")
        self.assertEqual(self._gw(model, "oci_core_local_peering_gateway.a")["peer"],
                         "oci_core_local_peering_gateway.b")
        self.assertEqual(self._gw(model, "oci_core_local_peering_gateway.b")["peer"],
                         "oci_core_local_peering_gateway.a")

    def test_an_unpaired_lpg_keeps_a_null_peer(self):
        model = self.parse(peer_a="")
        for address in ("oci_core_local_peering_gateway.a", "oci_core_local_peering_gateway.b"):
            self.assertIsNone(self._gw(model, address)["peer"], address)
        self.assertEqual([e for e in model["edges"] if e["label"] == "Local Peering"], [])


class DrgAttachmentTfvarsVcnTests(unittest.TestCase):
    """``_build_drgs()`` runs before ``_merge_loose()``; the VCN back-reference must survive it."""

    HUB = VCN_ENTRY % ("hub", "vcn-hub", "10.10.0.0/16", "mgmt", "10.10.0.0/24")
    SPOKE = VCN_ENTRY % ("spoke", "vcn-spoke", "10.20.0.0/16", "app", "10.20.1.0/24")

    @staticmethod
    def write(tmp, entries, attachment=DRG_FOR_EACH_ATTACHMENT):
        (Path(tmp) / "main.tf").write_text(DRG_FOR_EACH_MAIN_TF % attachment)
        (Path(tmp) / "vcns.auto.tfvars").write_text(DRG_FOR_EACH_TFVARS % "".join(entries))
        return Path(tmp)

    def parse(self, entries, attachment=DRG_FOR_EACH_ATTACHMENT):
        with tempfile.TemporaryDirectory() as tmp:
            return pt.parse_terraform_dir(self.write(tmp, entries, attachment))

    def test_renamed_placeholder_vcn_keeps_the_attachment(self):
        model = self.parse([self.HUB])
        self.assertEqual([v["name"] for v in model["vcns"]], ["vcn-hub"])
        self.assertEqual(model["drgs"][0]["attachments"],
                         [pt.new_attachment("vcn", "oci_core_drg_attachment.hub", "att-hub", vcn="vcn-hub")])
        self.assertEqual(pt.validate_model(model, BUILDER_ICONS), [])

    def test_implicit_attachment_label_follows_the_renamed_vcn(self):
        model = self.parse([self.HUB], attachment="")            # no attachment resource -> implicit one
        self.assertEqual(model["drgs"][0]["attachments"],
                         [pt.new_attachment("vcn", "oci_core_drg.core@oci_core_vcn.this",
                                            "VCN attachment\nvcn-hub", vcn="vcn-hub")])
        self.assertEqual(pt.validate_model(model, BUILDER_ICONS), [])

    def test_dropped_placeholder_vcn_drops_its_attachment(self):
        model = self.parse([self.HUB, self.SPOKE])                          # placeholder dropped, not renamed
        self.assertEqual([v["name"] for v in model["vcns"]], ["vcn-hub", "vcn-spoke"])
        self.assertEqual(model["drgs"][0]["attachments"], [])               # the VCN it pointed at is gone
        self.assertEqual(pt.validate_model(model, BUILDER_ICONS), [])

    def test_cli_exits_zero_for_the_renamed_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, [self.HUB])
            proc = subprocess.run([sys.executable, str(SCRIPT), tmp], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["drgs"][0]["attachments"][0]["vcn"], "vcn-hub")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class HelperTests(unittest.TestCase):
    def test_infer_tier(self):
        cases = [("sn-lb-public", "lb"), ("web_subnet", "lb"), ("dmz", "lb"), ("frontend", "lb"),
                 ("sn-app", "app"), ("api-private", "app"), ("worker-sn", "app"), ("public-app", "app"),
                 ("oke-nodes", "compute"), ("compute", "compute"), ("k8s", "compute"),
                 ("mgmt", "mgmt"), ("bastion-sn", "mgmt"), ("ops", "mgmt"),
                 ("sn-database", "data"), ("db", "data"), ("appdb", "data"), ("adb-private", "data"),
                 ("misc", "other"), ("", "other")]
        for name, tier in cases:
            with self.subTest(name=name):
                self.assertEqual(pt.infer_tier(name), tier)
        self.assertTrue(set(t for _, t in cases) <= set(pt.TIERS))

    def test_infer_public(self):
        self.assertFalse(pt.infer_public("sn-lb-public", prohibit_public_ip=True))   # explicit attr wins
        self.assertTrue(pt.infer_public("sn-app", prohibit_public_ip=False))
        self.assertTrue(pt.infer_public("sn-lb-public"))
        self.assertTrue(pt.infer_public("web"))
        self.assertFalse(pt.infer_public("public-private"))                           # private token wins
        self.assertFalse(pt.infer_public("sn-app"))

    def test_cidr_resolution_with_variables_lists_and_cidrsubnet(self):
        ctx = ds.TerraformContext(FIXTURES / "three_tier")
        self.assertEqual(pt._cidr_from(ctx, "[var.vcn_cidr]"), "10.0.0.0/16")
        self.assertEqual(pt._cidr_from(ctx, "cidrsubnet(var.vcn_cidr, 8, 3)"), "10.0.3.0/24")
        self.assertEqual(pt._cidr_from(ctx, 'local.subnet_cidrs["app"]'), "10.0.1.0/24")
        self.assertEqual(pt._cidr_from(ctx, "local.subnet_cidrs.db"), "10.0.2.0/24")
        self.assertEqual(pt._cidr_from(ctx, 'cidrsubnet("192.168.0.0/16", 4, 2)'), "192.168.32.0/20")
        self.assertIsNone(pt._cidr_from(ctx, "each.value.cidr"))
        self.assertIsNone(pt._cidr_from(ctx, None))

    def test_refs_in(self):
        self.assertEqual(pt._refs_in("oci_core_subnet.app.id"), ["oci_core_subnet.app"])
        self.assertEqual(pt._refs_in("[oci_core_subnet.a.id, oci_core_subnet.b.id]"),
                         ["oci_core_subnet.a", "oci_core_subnet.b"])
        self.assertEqual(pt._refs_in("data.oci_core_subnets.x.subnets[0].id"), [])
        self.assertEqual(pt._refs_in('module.net.subnet_ids["app"]'), ["module.net"])
        self.assertEqual(pt._refs_in('oci_core_subnet.this["hub-mgmt"].id'), ['oci_core_subnet.this["hub-mgmt"]'])
        self.assertEqual(pt._refs_in("oci_core_instance.app[count.index].private_ip"), ["oci_core_instance.app"])
        self.assertEqual(pt._refs_in("module.net.oci_core_vcn.main.id"), ["module.net.oci_core_vcn.main"])

    def test_address_helpers(self):
        self.assertEqual(pt.base_address('module.a[0].oci_core_subnet.app["x"]'), "module.a.oci_core_subnet.app")
        self.assertEqual(pt.index_key('oci_core_subnet.app["x"]'), "x")
        self.assertEqual(pt.index_key("oci_core_subnet.app[3]"), "3")
        self.assertIsNone(pt.index_key("oci_core_subnet.app"))

    def test_every_mapped_icon_exists_in_drawio_builder(self):
        for rtype, (icon, label) in pt.RESOURCE_ICONS.items():
            with self.subTest(rtype=rtype):
                self.assertIn(icon, BUILDER_ICONS)
                self.assertTrue(label)
        for _prefix, (icon, _label) in pt.RESOURCE_ICON_PREFIXES:
            self.assertIn(icon, BUILDER_ICONS)
        for icon in pt.GATEWAY_ICONS.values():
            self.assertIn(icon, BUILDER_ICONS)
        for rtype in list(pt.GATEWAY_TYPES) + list(pt.HUB_TYPES) + [pt.DRG_TYPE] + sorted(pt.CONTROL_TYPES):
            self.assertIn(rtype, pt.RESOURCE_ICONS, rtype)

    def test_icon_for_type_prefixes(self):
        self.assertEqual(pt.icon_for_type("oci_generative_ai_agent_agent")[0], "ai")
        self.assertEqual(pt.icon_for_type("oci_ai_language_project")[0], "ai")
        self.assertEqual(pt.icon_for_type("oci_core_instance"), ("vm", "Instance"))
        self.assertIsNone(pt.icon_for_type("oci_identity_policy"))

    def test_required_mappings_from_spec(self):
        expected = {
            "oci_core_volume": "block_storage", "oci_file_storage_file_system": "file_storage",
            "oci_objectstorage_bucket": "buckets", "oci_load_balancer_load_balancer": "load_balancer",
            "oci_load_balancer": "load_balancer", "oci_network_load_balancer_network_load_balancer": "load_balancer",
            "oci_functions_application": "functions", "oci_containerengine_cluster": "oke",
            "oci_containerengine_node_pool": "vm", "oci_database_autonomous_database": "autonomous_db",
            "oci_database_db_system": "db_system", "oci_mysql_mysql_db_system": "mysql", "oci_nosql_table": "nosql",
            "oci_redis_redis_cluster": "nosql", "oci_kms_vault": "vault", "oci_kms_key": "key_management",
            "oci_certificates_management_certificate": "certificates", "oci_waf_web_app_firewall": "waf",
            "oci_network_firewall_network_firewall": "firewall", "oci_bastion_bastion": "bastion",
            "oci_core_network_security_group": "nsg", "oci_core_security_list": "security_list",
            "oci_core_route_table": "route_table", "oci_core_internet_gateway": "internet_gateway",
            "oci_core_nat_gateway": "nat_gateway", "oci_core_service_gateway": "service_gateway",
            "oci_core_drg": "drg", "oci_core_local_peering_gateway": "remote_peering_gateway",
            "oci_core_remote_peering_connection": "remote_peering_gateway", "oci_core_cpe": "cpe",
            "oci_core_ipsec": "cpe", "oci_dns_zone": "dns", "oci_dns_resolver": "dns",
            "oci_logging_log_group": "logging", "oci_monitoring_alarm": "alarms", "oci_apm_apm_domain": "apm",
            "oci_streaming_stream": "streaming", "oci_queue_queue": "queuing", "oci_events_rule": "events",
            "oci_sch_service_connector": "service_connector_hub", "oci_datascience_project": "data_science",
            "oci_analytics_analytics_instance": "big_data", "oci_apigateway_gateway": "api_gateway",
            "oci_devops_project": "devops", "oci_artifacts_container_repository": "container_registry",
            "oci_ons_notification_topic": "notifications",
        }
        for rtype, icon in expected.items():
            with self.subTest(rtype=rtype):
                self.assertEqual(pt.RESOURCE_ICONS[rtype][0], icon)

    def test_select_vcn(self):
        model = pt.parse_terraform_dir(FIXTURES / "tfvars_map")
        self.assertFalse(pt.select_vcn(dict(model), "nope"))
        self.assertTrue(pt.select_vcn(model, "VCN-HUB"))
        self.assertEqual([v["name"] for v in model["vcns"]], ["vcn-hub"])
        self.assertEqual(model["subject"], "vcn-hub")
        model = pt.parse_terraform_dir(FIXTURES / "tfvars_map")
        self.assertTrue(pt.select_vcn(model, "spoke"))                       # unique substring
        self.assertEqual(model["subject"], "vcn-spoke-app")

    def test_validate_model_reports_violations(self):
        model = pt.parse_terraform_dir(FIXTURES / "three_tier")
        self.assertEqual(pt.validate_model(model), [])
        model["vcns"][0]["subnets"][0]["tier"] = "frontend"
        model["edges"].append(pt.new_edge("nope", "oci_core_drg.drg", "", "data"))
        model["edges"].append(pt.new_edge("oci_core_drg.drg", "oci_core_cpe.onprem", "", "sideways"))
        model["services"].append(pt.new_item("no_such_icon", "x", "t", "oci_core_drg.drg"))
        model["drgs"][0]["attachments"][0]["type"] = "tunnel"
        model["drgs"][0]["attachments"].append(pt.new_attachment("vcn", "att-x", "x", vcn="no-such-vcn"))
        model["drg_style"] = "fancy"
        problems = pt.validate_model(model, BUILDER_ICONS)
        joined = "\n".join(problems)
        self.assertIn("tier", joined)
        self.assertIn("'nope' is not an address", joined)
        self.assertIn("kind", joined)
        self.assertIn("unknown icon key", joined)
        self.assertIn("appears 2 times", joined)
        self.assertIn("attachments[0].type", joined)
        self.assertIn("is not a VCN name", joined)
        self.assertIn("drg_style", joined)
        self.assertEqual(pt.validate_model([]), ["model: expected dict, got list"])

    def test_model_is_empty(self):
        self.assertTrue(pt.model_is_empty(pt.new_model()))
        self.assertFalse(pt.model_is_empty(pt.parse_terraform_dir(FIXTURES / "three_tier")))


# ---------------------------------------------------------------------------
# Plan / state JSON mode
# ---------------------------------------------------------------------------

class PlanJsonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = pt.parse_show_json(FIXTURES / "plan.json", "plan")
        cls.vcn = cls.model["vcns"][0]

    def test_valid_and_header(self):
        self.assertEqual(pt.validate_model(self.model, BUILDER_ICONS), [])
        self.assertEqual(self.model["source"]["mode"], "plan")
        self.assertEqual(self.model["region"], "uk-london-1")          # provider region -> var.region -> variables
        self.assertEqual(self.model["region_label"], "London")
        self.assertEqual(self.model["subject"], "vcn-plan")
        self.assertEqual(len(self.model["vcns"]), 1)
        self.assertEqual(self.vcn["cidr"], "10.1.0.0/16")

    def test_subnets_resolved_via_configuration_and_ocids(self):
        subnets = {s["name"]: s for s in self.vcn["subnets"]}
        self.assertEqual(set(subnets), {"sn-web", "sn-app", "sn-data"})   # vcn_id unknown -> configuration refs
        self.assertEqual((subnets["sn-web"]["tier"], subnets["sn-web"]["public"]), ("lb", True))
        self.assertEqual((subnets["sn-app"]["tier"], subnets["sn-app"]["public"]), ("app", False))
        self.assertEqual(subnets["sn-data"]["tier"], "data")                # vcn_id known as OCID -> id index

    def test_items_with_indexed_addresses(self):
        app = find_subnet(self.vcn, "sn-app")["items"]
        self.assertEqual([i["address"] for i in app], ["oci_core_instance.app[0]", "oci_core_instance.app[1]"])
        self.assertEqual(app[0]["label"], "app-0\nVM.Standard.E4.Flex")
        self.assertEqual(app[0]["metadata"]["availability_domain"], "AD-1")
        web = find_subnet(self.vcn, "sn-web")["items"]
        self.assertEqual([(i["icon"], i["address"]) for i in web],
                         [("load_balancer", "oci_load_balancer_load_balancer.web")])   # subnet_ids via configuration
        data = find_subnet(self.vcn, "sn-data")["items"]
        self.assertEqual([(i["icon"], i["label"]) for i in data], [("mysql", "mysql-app\nMySQL.VM.Standard.E4.1.8GB")])

    def test_module_resources_and_gateway(self):
        svc = {i["address"]: i for i in self.vcn["services"]}
        self.assertEqual(set(svc), {"module.storage.oci_objectstorage_bucket.logs",
                                    "module.storage.module.nested.oci_kms_vault.main"})
        self.assertEqual(svc["module.storage.oci_objectstorage_bucket.logs"]["label"], "plan-logs")
        self.assertEqual([(g["type"], g["label"]) for g in self.vcn["gateways"]], [("igw", "igw-plan")])

    def test_explicit_backend_edges_use_index_matching(self):
        edges = {(e["source"], e["target"]): e for e in self.model["edges"]}
        for idx in (0, 1):
            e = edges[("oci_load_balancer_load_balancer.web", f"oci_core_instance.app[{idx}]")]
            self.assertEqual((e["label"], e["kind"], e["inferred"]), ("8080", "data", False))
            e = edges[(f"oci_core_instance.app[{idx}]", "oci_mysql_mysql_db_system.db")]
            self.assertEqual((e["label"], e["inferred"]), ("3306", True))
        self.assertEqual(len(edges), 4)

    def test_tags_and_data_sources_do_not_leak(self):
        dump = json.dumps(self.model)
        self.assertNotIn("tag-must-not-leak", dump)
        self.assertNotIn("oci_identity_availability_domains", dump)

    def test_state_mode_uses_values_root_module(self):
        plan = json.loads((FIXTURES / "plan.json").read_text())
        state = {"format_version": "1.0", "values": plan["planned_values"]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps(state))
            model = pt.parse_show_json(path)                                 # mode auto-detected
        self.assertEqual(model["source"]["mode"], "state")
        self.assertIsNone(model["region"])                                   # no configuration block in state
        self.assertEqual(model["vcns"][0]["name"], "vcn-plan")
        # without configuration refs only the OCID-linked subnet stays attached; the others fall back to the single VCN
        self.assertEqual({s["name"] for s in model["vcns"][0]["subnets"]}, {"sn-web", "sn-app", "sn-data"})
        self.assertEqual(pt.validate_model(model, BUILDER_ICONS), [])

    def test_invalid_json_raises_input_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json")
            with self.assertRaises(pt.InputError):
                pt.parse_show_json(path)
            path.write_text("[1, 2]")
            with self.assertRaises(pt.InputError):
                pt.parse_show_json(path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class CliTests(unittest.TestCase):
    def run_cli(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                              cwd=str(cwd or FIXTURES), timeout=60)

    def test_help(self):
        proc = self.run_cli("-h")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("usage", proc.stdout.lower())

    def test_hcl_dir_prints_model_json(self):
        proc = self.run_cli(str(FIXTURES / "three_tier"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        model = json.loads(proc.stdout)
        self.assertEqual(model["subject"], "vcn-shop")
        self.assertIn("vcn-shop: 1 VCN(s), 3 subnet(s)", proc.stderr)

    def test_plan_json_flag(self):
        proc = self.run_cli("--plan-json", str(FIXTURES / "plan.json"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["source"]["mode"], "plan")

    def test_state_json_with_tf_dir_for_region(self):
        plan = json.loads((FIXTURES / "plan.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps({"values": plan["planned_values"]}))
            proc = self.run_cli(str(FIXTURES / "three_tier"), "--state-json", str(path))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        model = json.loads(proc.stdout)
        self.assertEqual(model["source"]["mode"], "state")
        self.assertEqual(model["region"], "eu-frankfurt-1")                  # from the HCL provider block

    def test_out_writes_file_and_keeps_stdout_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "model.json"
            proc = self.run_cli(str(FIXTURES / "three_tier"), "--out", str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout, "")
            self.assertEqual(json.loads(out.read_text())["subject"], "vcn-shop")
        self.assertIn("Wrote", proc.stderr)

    def test_vcn_filter(self):
        proc = self.run_cli(str(FIXTURES / "tfvars_map"), "--vcn", "VCN-HUB")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        model = json.loads(proc.stdout)
        self.assertEqual([v["name"] for v in model["vcns"]], ["vcn-hub"])
        proc = self.run_cli(str(FIXTURES / "tfvars_map"), "--vcn", "nope")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertIn("Available: vcn-hub, vcn-spoke-app", proc.stderr)

    def test_no_inferred_edges_flag(self):
        proc = self.run_cli(str(FIXTURES / "three_tier"), "--no-inferred-edges")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["edges"], [])

    def test_bad_paths_exit_2(self):
        proc = self.run_cli(str(FIXTURES / "does_not_exist"))
        self.assertEqual((proc.returncode, proc.stdout), (2, ""))
        self.assertIn("does not exist", proc.stderr)
        proc = self.run_cli("--plan-json", str(FIXTURES / "missing.json"))
        self.assertEqual(proc.returncode, 2)
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("nope")
            proc = self.run_cli("--plan-json", str(bad))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot read", proc.stderr)

    def test_nothing_recognised_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "main.tf").write_text('provider "oci" {\n  region = "us-ashburn-1"\n}\n')
            proc = self.run_cli(tmp, cwd=tmp)
        self.assertEqual((proc.returncode, proc.stdout), (1, ""))
        self.assertIn("No OCI resources recognised", proc.stderr)

    def test_main_in_process(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = pt.main([str(FIXTURES / "three_tier")])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue())["vcns"][0]["name"], "vcn-shop")


if __name__ == "__main__":
    unittest.main()
