"""Unit tests for scripts/oci_topology.py (classification, regional services, legacy migration)."""
import copy
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import oci_topology as ot  # noqa: E402


def vcn(name, gateways=None):
    return {"name": name, "cidr": "10.0.0.0/16", "subnets": [], "gateways": gateways or []}


def drg(name="drg", attachments=None):
    return {"name": name, "address": name, "label": "DRG", "attachments": attachments or []}


class ClassifyTests(unittest.TestCase):
    def test_single_and_multi_vcn_without_drg(self):
        t = ot.classify_topology({"vcns": [vcn("a")]})
        self.assertEqual(t, {"kind": "single_vcn", "n_vcns": 1, "n_drgs": 0, "n_vcn_attachments": 0,
                             "has_onprem": False, "has_rpc": False, "has_lpg": False})
        t = ot.classify_topology({"vcns": [vcn("a"), vcn("b", [{"type": "lpg", "icon": "rpg", "label": "lpg"}])]})
        self.assertEqual((t["kind"], t["has_lpg"]), ("multi_vcn", True))

    def test_vcn_with_drg(self):
        t = ot.classify_topology({"vcns": [vcn("a")], "drgs": [drg(attachments=[{"type": "vcn", "vcn": "a"}])]})
        self.assertEqual((t["kind"], t["n_drgs"], t["n_vcn_attachments"]), ("vcn_with_drg", 1, 1))

    def test_hub_spoke(self):
        d = drg(attachments=[{"vcn": "a"}, {"type": "vcn", "vcn": "b"}])   # missing type defaults to vcn
        t = ot.classify_topology({"vcns": [vcn("a"), vcn("b")], "drgs": [d]})
        self.assertEqual((t["kind"], t["n_vcn_attachments"]), ("hub_spoke", 2))

    def test_hybrid_wins_over_hub_spoke(self):
        d = drg(attachments=[{"type": "vcn", "vcn": "a"}, {"type": "vcn", "vcn": "b"}, {"type": "ipsec", "target": "cpe"}])
        t = ot.classify_topology({"vcns": [vcn("a"), vcn("b")], "drgs": [d]})
        self.assertEqual((t["kind"], t["has_onprem"], t["has_rpc"]), ("hybrid", True, False))
        hub = {"name": "On-premises", "items": [{"icon": "cpe", "label": "CPE", "address": "cpe"}]}
        t = ot.classify_topology({"vcns": [vcn("a")], "hub": hub, "drgs": [drg(attachments=[{"vcn": "a"}])]})
        self.assertEqual((t["kind"], t["has_onprem"]), ("hybrid", True))

    def test_rpc_only_hub_is_hybrid_but_not_onprem(self):
        hub = {"name": "Remote region", "items": [{"icon": "rpg", "label": "RPC", "address": "rpc"}]}
        t = ot.classify_topology({"vcns": [vcn("a")], "hub": hub, "drgs": [drg(attachments=[{"vcn": "a"}])]})
        self.assertEqual((t["kind"], t["has_onprem"], t["has_rpc"]), ("hybrid", False, True))

    def test_choose_drg_style(self):
        self.assertEqual(ot.choose_drg_style("auto", 4), "icon")
        self.assertEqual(ot.choose_drg_style("auto", 5), "box")
        self.assertEqual(ot.choose_drg_style("box", 1), "box")
        self.assertEqual(ot.choose_drg_style("icon", 9), "icon")
        with self.assertRaises(ValueError):
            ot.choose_drg_style("fancy", 1)


class RegionalTests(unittest.TestCase):
    def test_table_and_override(self):
        self.assertTrue(ot.is_regional({"icon": "logging"}))
        self.assertTrue(ot.is_regional({"icon": "buckets"}))
        self.assertTrue(ot.is_regional({"icon": "iam"}))
        self.assertFalse(ot.is_regional({"icon": "load_balancer"}))
        self.assertFalse(ot.is_regional({"icon": "functions"}))
        self.assertFalse(ot.is_regional({"icon": "logging", "regional": False}))
        self.assertTrue(ot.is_regional({"icon": "vm", "regional": True}))
        self.assertFalse(ot.is_regional({"icon": "no_such_icon"}))
        for key in ("logging", "logging_analytics", "notifications", "events", "alarms", "iam", "identity",
                    "vault", "kms", "object_storage", "ocir", "generative_ai", "data_safe", "connector_hub"):
            self.assertIn(key, ot.REGIONAL_ICON_KEYS, key)

    def test_attachment_helpers(self):
        self.assertEqual(ot.attachment_type({"vcn": "a"}), "vcn")
        self.assertEqual(ot.attachment_type({"type": "IPSEC_TUNNEL"}), "ipsec")
        self.assertEqual(ot.attachment_type({"type": "VIRTUAL_CIRCUIT"}), "virtual_circuit")
        self.assertEqual(ot.attachment_type({"type": "REMOTE_PEERING_CONNECTION"}), "rpc")
        self.assertEqual(ot.attachment_label({"type": "vcn", "vcn": "spoke-a"}), "VCN attachment\nspoke-a")
        self.assertEqual(ot.attachment_label({"type": "vcn", "vcn": "spoke-a", "label": "att-a"}), "att-a")
        self.assertEqual(ot.attachment_label({"type": "ipsec"}), "IPSec attachment")
        self.assertEqual(ot.attachment_link_label({"type": "ipsec"}), "Site-to-Site VPN")
        self.assertEqual(ot.attachment_link_label({"type": "virtual_circuit"}), "FastConnect")
        self.assertEqual(ot.attachment_link_label({"type": "rpc"}), "Remote Peering")
        self.assertEqual(ot.attachment_link_label({"type": "vcn", "vcn": "a"}), "")


class MigrationTests(unittest.TestCase):
    LEGACY = {
        "subject": "Spoke", "vcns": [vcn("Spoke", [
            {"icon": "service_gateway", "label": "Service\nGateway", "address": "sgw"},
            {"icon": "drg", "type": "drg", "label": "drg-hub", "address": "att-spoke"}])],
        "hub": {"name": "Hub Network", "link_label": "IPSec VPN",
                "items": [{"icon": "firewall", "label": "Corp VPN", "address": "cpe"},
                          {"icon": "drg", "label": "Dynamic Routing\nGateway (DRG)", "address": "drg"}]},
        "edges": [{"source": "drg", "target": "sgw", "label": "", "kind": "data"}],
    }

    def test_hub_drg_and_gateway_drg_are_migrated(self):
        src = copy.deepcopy(self.LEGACY)
        m, warnings = ot.migrate_legacy_model(src)
        self.assertEqual(src, self.LEGACY, "input must not be mutated")
        self.assertEqual([i["address"] for i in m["hub"]["items"]], ["cpe"])
        self.assertEqual([g["address"] for g in m["vcns"][0]["gateways"]], ["sgw"])
        self.assertEqual(len(m["drgs"]), 1)
        d = m["drgs"][0]
        self.assertEqual((d["name"], d["address"], d["label"]), ("Dynamic Routing", "drg", "Dynamic Routing\nGateway (DRG)"))
        self.assertEqual(d["attachments"], [{"type": "vcn", "vcn": "Spoke", "address": "att-spoke",
                                             "label": "VCN attachment\nSpoke"}])
        # link_label between the CPE and the moved DRG becomes an explicit edge
        self.assertIn({"source": "cpe", "target": "drg", "label": "IPSec VPN", "kind": "data"}, m["edges"])
        self.assertEqual(len(m["edges"]), 2)
        self.assertTrue(all(w.startswith("WARNING: legacy model:") for w in warnings))
        self.assertEqual(len(warnings), 2)

    def test_hub_with_only_a_drg_is_removed(self):
        m, warnings = ot.migrate_legacy_model({"vcns": [vcn("a")], "hub": {"name": "Hub", "items": [
            {"icon": "drg", "label": "drg-x", "address": "drg-x"}]}})
        self.assertIsNone(m["hub"])
        self.assertEqual(m["drgs"][0]["address"], "drg-x")
        # no attachments given and a single VCN -> implicit attachment
        self.assertEqual(m["drgs"][0]["attachments"], [{"type": "vcn", "vcn": "a", "address": "drg-x@a",
                                                        "label": "VCN attachment\na"}])
        self.assertTrue(any(w.startswith("WARNING: model: DRG 'drg-x' has no attachments") for w in warnings))

    def test_gateway_only_legacy_creates_a_drg(self):
        m, warnings = ot.migrate_legacy_model({"vcns": [
            vcn("a", [{"icon": "drg", "label": "drg-shared", "address": "att-a"}]),
            vcn("b", [{"icon": "drg", "label": "drg-shared", "address": "att-b"}])]})
        self.assertEqual(len(m["drgs"]), 1)
        self.assertEqual(m["drgs"][0]["name"], "drg-shared")
        self.assertEqual([a["vcn"] for a in m["drgs"][0]["attachments"]], ["a", "b"])
        self.assertEqual(len(warnings), 2)

    def test_v2_model_is_untouched(self):
        v2 = {"vcns": [vcn("a")], "drgs": [drg(attachments=[{"type": "vcn", "vcn": "a", "address": "att"}])],
              "hub": {"name": "On-premises", "items": [{"icon": "cpe", "address": "cpe", "label": "CPE"}]}}
        m, warnings = ot.migrate_legacy_model(copy.deepcopy(v2))
        self.assertEqual(m, v2)
        self.assertEqual(warnings, [])

    def test_existing_edge_is_not_duplicated(self):
        legacy = copy.deepcopy(self.LEGACY)
        legacy["edges"].append({"source": "cpe", "target": "drg", "label": "IPSec VPN", "kind": "data"})
        m, _ = ot.migrate_legacy_model(legacy)
        self.assertEqual(sum(1 for e in m["edges"] if (e["source"], e["target"]) == ("cpe", "drg")), 1)


if __name__ == "__main__":
    unittest.main()
