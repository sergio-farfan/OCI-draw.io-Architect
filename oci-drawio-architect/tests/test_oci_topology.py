"""Unit tests for scripts/oci_topology.py (classification, regional services, legacy migration)."""
import contextlib
import copy
import io
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


def stderr_of(fn, *args, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        result = fn(*args, **kwargs)
    return result, buf.getvalue()


class InputToleranceTests(unittest.TestCase):
    def setUp(self):
        ot._WARNED.clear()

    def test_regional_accepts_the_json_string_and_integer_forms(self):
        self.assertTrue(ot.is_regional({"icon": "vm", "regional": "true"}))
        self.assertTrue(ot.is_regional({"icon": "vm", "regional": "TRUE"}))
        self.assertFalse(ot.is_regional({"icon": "logging", "regional": "false"}))
        self.assertTrue(ot.is_regional({"icon": "vm", "regional": 1}))
        self.assertFalse(ot.is_regional({"icon": "logging", "regional": 0}))

    def test_an_empty_regional_value_falls_back_silently(self):
        (value, err) = stderr_of(ot.is_regional, {"icon": "logging", "regional": ""})
        self.assertTrue(value)                                  # falls back to the icon table
        self.assertEqual(err, "")

    def test_regional_warns_once_for_a_value_it_cannot_read(self):
        (value, err) = stderr_of(ot.is_regional, {"icon": "logging", "regional": "maybe"})
        self.assertTrue(value)                                  # falls back to the icon table
        self.assertIn("is not a boolean", err)
        (_, again) = stderr_of(ot.is_regional, {"icon": "logging", "regional": "maybe"})
        self.assertEqual(again, "")                             # deduplicated

    def test_unknown_attachment_type_warns(self):
        (atype, err) = stderr_of(ot.attachment_type, {"type": "ipsec-tunnel"})
        self.assertEqual(atype, "ipsec-tunnel")
        self.assertIn("ipsec-tunnel", err)
        (_, clean) = stderr_of(ot.attachment_type, {"type": "rpc"})
        self.assertEqual(clean, "")

    def test_choose_drg_style_rejects_a_non_string(self):
        with self.assertRaises(ValueError):
            ot.choose_drg_style(7, 1)
        with self.assertRaises(ValueError):
            ot.choose_drg_style("fancy", 1)


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

    def test_has_onprem_follows_the_cpe_ipsec_virtual_circuit_rule(self):
        """A34: spec 7.1 - only a CPE, an IPSec endpoint or a virtual circuit is on-premises."""
        hub = {"name": "Hub", "items": [{"icon": "firewall", "label": "Corp FW", "address": "fw"}]}
        t = ot.classify_topology({"vcns": [vcn("a"), vcn("b")], "hub": hub,
                                  "drgs": [drg(attachments=[{"vcn": "a"}, {"vcn": "b"}])]})
        self.assertEqual((t["kind"], t["has_onprem"]), ("hub_spoke", False))
        hub["items"].append({"icon": "cpe", "label": "CPE", "address": "cpe"})
        t = ot.classify_topology({"vcns": [vcn("a"), vcn("b")], "hub": hub,
                                  "drgs": [drg(attachments=[{"vcn": "a"}, {"vcn": "b"}])]})
        self.assertEqual((t["kind"], t["has_onprem"]), ("hybrid", True))


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

    def test_dns_resolver_is_vcn_resident_despite_dns_icon(self):
        # spec section 6: "oci_dns_resolver is VCN-resident; the dns icon alone is regional"
        self.assertFalse(ot.is_regional({"icon": "dns", "type": "oci_dns_resolver"}))
        self.assertTrue(ot.is_regional({"icon": "dns", "type": "oci_dns_zone"}))
        self.assertTrue(ot.is_regional({"icon": "dns"}))
        # an explicit override still wins over the type-based carve-out
        self.assertTrue(ot.is_regional({"icon": "dns", "type": "oci_dns_resolver", "regional": True}))

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
    def setUp(self):
        ot._WARNED.clear()

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
        # the VCN's legacy drg-gateway ("drg-hub") and the hub item's own DRG name
        # ("Dynamic Routing") differ, so the single-DRG shortcut also warns (A33)
        self.assertIn("WARNING: legacy model: gateway 'drg-hub' merged into the only DRG 'Dynamic Routing'",
                      warnings)
        self.assertEqual(len(warnings), 3)

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

    def test_duplicate_attachment_address_is_warned(self):
        # spec section 5: "attachments[].address must be unique in the model" - migrate_legacy_model
        # defensively flags this for hand-authored (schema-1 or schema-2) input before it ever
        # reaches the builder, where a duplicate key would otherwise raise a bare ValueError.
        v2 = {"vcns": [vcn("a"), vcn("b")],
              "drgs": [drg(attachments=[{"type": "vcn", "vcn": "a", "address": "att"},
                                        {"type": "vcn", "vcn": "b", "address": "att"}])]}
        m, warnings = ot.migrate_legacy_model(v2)
        self.assertTrue(any(w == "WARNING: model: attachments[].address duplicate: 'att'" for w in warnings), warnings)

    def test_no_duplicate_warning_for_unique_addresses(self):
        v2 = {"vcns": [vcn("a")], "drgs": [drg(attachments=[{"type": "vcn", "vcn": "a", "address": "att"}])]}
        _, warnings = ot.migrate_legacy_model(v2)
        self.assertEqual(warnings, [])

    def test_single_drg_shortcut_warns_when_the_names_differ(self):
        model = {"vcns": [{"name": "a", "subnets": [], "services": [],
                           "gateways": [{"type": "drg", "icon": "drg", "label": "drg-old", "address": "gw-drg"}]}],
                 "drgs": [{"name": "drg-new", "address": "drg-new", "label": "DRG\ndrg-new", "attachments": []}]}
        _, warnings = ot.migrate_legacy_model(model)
        self.assertTrue(any("merged into the only DRG" in w and "drg-new" in w for w in warnings), warnings)

    def test_two_drgs_are_matched_by_name(self):
        drgs = [{"name": "hub", "address": "hub", "label": "DRG\nhub", "attachments": []},
                {"name": "spoke", "address": "spoke", "label": "DRG\nspoke", "attachments": []}]
        self.assertIs(ot._match_drg(drgs, {"label": "spoke"}), drgs[1])
        self.assertIsNone(ot._match_drg(drgs, {"label": "neither"}))

    def test_two_identical_hub_drg_items_are_indexed_by_identity(self):
        """A35: items.index() matched by value, so the second DRG reused the first one's neighbours."""
        item = {"icon": "drg", "label": "DRG", "address": "drg"}
        model = {"vcns": [vcn("a")], "hub": {"name": "Hub", "link_label": "IPSec VPN", "items": [
            dict(item), {"icon": "cpe", "label": "CPE", "address": "cpe"},
            dict(item), {"icon": "cpe", "label": "CPE 2", "address": "cpe2"}]}}
        m, warnings = ot.migrate_legacy_model(model)
        self.assertEqual([d["address"] for d in m["drgs"]], ["drg", "drg"])
        pairs = {(e["source"], e["target"]) for e in m["edges"]}
        self.assertIn(("cpe", "drg"), pairs)
        self.assertIn(("cpe2", "drg"), pairs)


if __name__ == "__main__":
    unittest.main()
