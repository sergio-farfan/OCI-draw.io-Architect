"""Tests for the v1.5.0 shared filter predicate, participating mode and dangling pruning."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import oci_view as ov  # noqa: E402


def model():
    """Two applications and two environments in one region, two VCNs, one DRG."""
    return {
        "subject": "tagged-app", "region": "us-ashburn-1", "compartment": "app-prod",
        "hub": {"name": "On-premises", "items": [
            {"icon": "cpe", "label": "CPE", "type": "oci_core_cpe", "address": "cpe"}]},
        "drgs": [{"name": "drg", "address": "drg", "label": "DRG", "attachments": [
            {"type": "vcn", "vcn": "vcn-app", "address": "att-app", "label": "VCN attachment"},
            {"type": "vcn", "vcn": "vcn-ops", "address": "att-ops", "label": "VCN attachment"},
            {"type": "ipsec", "target": "cpe", "address": "att-vpn", "label": "IPSec"}]}],
        "vcns": [
            {"name": "vcn-app", "address": "vcn.app", "cidr": "10.0.0.0/16",
             "compartment": "app-prod",
             "tags": {"freeform": {"Application": "payments"}, "defined": {}},
             "subnets": [
                 {"name": "sn-web", "address": "sn.web", "cidr": "10.0.1.0/24", "tier": "lb",
                  "public": True, "route_table": "rt-web", "items": [
                      {"icon": "load_balancer", "label": "Web LB", "type": "oci_load_balancer",
                       "address": "lb", "nsgs": ["nsg-lb"],
                       "tags": {"freeform": {"Application": "payments", "Environment": "prod"},
                                "defined": {}}}]},
                 {"name": "sn-app", "address": "sn.app", "cidr": "10.0.2.0/24", "tier": "app",
                  "public": False, "items": [
                      {"icon": "vm", "label": "App Broker VM", "type": "oci_core_instance",
                       "address": "broker", "metadata": {"private_ip": "10.0.2.47",
                                                         "compartment": "app-prod"},
                       "tags": {"freeform": {"Application": "payments", "Environment": "prod"},
                                "defined": {"Ops.Tier": "gold"}}},
                      {"icon": "vm", "label": "Batch VM", "type": "oci_core_instance",
                       "address": "batch",
                       "tags": {"freeform": {"Application": "reporting", "Environment": "nonprod"},
                                "defined": {}}}]}],
             "services": [{"icon": "logging", "label": "Logging", "address": "logs"},
                          {"icon": "vault", "label": "Vault", "address": "vault"}],
             "gateways": [{"icon": "nat_gateway", "type": "nat", "label": "NAT", "address": "nat"}]},
            {"name": "vcn-ops", "address": "vcn.ops", "cidr": "10.9.0.0/16",
             "compartment": "ops",
             "tags": {"freeform": {"Application": "shared"}, "defined": {}},
             "subnets": [
                 {"name": "sn-mgmt", "address": "sn.mgmt", "cidr": "10.9.1.0/24", "tier": "mgmt",
                  "public": False, "items": [
                      {"icon": "bastion", "label": "Bastion", "type": "oci_bastion_bastion",
                       "address": "bastion",
                       "tags": {"freeform": {"Application": "shared"}, "defined": {}}}]}],
             "services": [], "gateways": []},
        ],
        "services": [{"icon": "iam", "label": "Identity Domain", "address": "idcs"}],
        "edges": [
            {"source": "lb", "target": "broker", "label": "8088", "kind": "data",
             "discovery": "association", "inferred": False},
            {"source": "bastion", "target": "broker", "label": "22", "kind": "control",
             "discovery": "heuristic", "inferred": False},
        ],
    }


class ParseFilterTests(unittest.TestCase):
    def test_a_bare_expression_parses_into_its_four_parts(self):
        spec = ov.parse_filter(["tag:Application=payments"])
        self.assertEqual(spec["exclude"], [])
        self.assertEqual(spec["include"][0]["dim"], "tag")
        self.assertEqual(spec["include"][0]["key"], "Application")
        self.assertEqual(spec["include"][0]["op"], "=")
        self.assertEqual(spec["include"][0]["values"], ("payments",))

    def test_a_bang_prefix_moves_the_expression_to_exclude(self):
        spec = ov.parse_filter(["!type=oci_core_nat_gateway"])
        self.assertEqual(spec["include"], [])
        self.assertEqual(spec["exclude"][0]["dim"], "type")

    def test_a_comma_list_is_an_or_within_one_expression(self):
        self.assertEqual(ov.parse_filter(["vcn=vcn-app,vcn-ops"])["include"][0]["values"],
                         ("vcn-app", "vcn-ops"))

    def test_the_substring_operator_is_recognised(self):
        expr = ov.parse_filter(["name~broker"])["include"][0]
        self.assertEqual((expr["dim"], expr["op"], expr["values"]), ("name", "~", ("broker",)))

    def test_the_dict_form_keeps_include_and_exclude_apart(self):
        spec = ov.parse_filter({"include": ["vcn=vcn-app"], "exclude": ["type=x"],
                                "keep_empty": True})
        self.assertEqual([e["dim"] for e in spec["include"]], ["vcn"])
        self.assertEqual([e["dim"] for e in spec["exclude"]], ["type"])
        self.assertTrue(spec["keep_empty"])

    def test_an_unknown_dimension_raises_and_names_the_known_ones(self):
        with self.assertRaises(ValueError) as ctx:
            ov.parse_filter(["colour=purple"])
        self.assertIn("colour", str(ctx.exception))
        self.assertIn("tag", str(ctx.exception))

    def test_a_malformed_expression_raises(self):
        for text in ("vcn", "=value", "tag:=x", "vcn<vcn-app"):
            with self.assertRaises(ValueError, msg=text):
                ov.parse_filter([text])

    def test_an_empty_spec_is_an_empty_include_which_means_everything(self):
        for spec in (None, [], {}, {"include": [], "exclude": []}):
            self.assertEqual(ov.parse_filter(spec)["include"], [])


def addresses(m):
    return set(ov.model_addresses(m))


class FilterModelTests(unittest.TestCase):
    def test_an_empty_include_keeps_everything_and_reports_nothing_dropped(self):
        out, report = ov.filter_model(model())
        self.assertEqual(addresses(out), addresses(model()))
        self.assertEqual((report["items_dropped"], report["edges_dropped"],
                          report["containers_dropped"]), (0, 0, 0))
        self.assertEqual(report["items_kept"], 8)

    def test_the_input_model_is_never_mutated(self):
        src = model()
        before = copy.deepcopy(src)
        ov.filter_model(src, ["vcn=vcn-app"])
        self.assertEqual(src, before)

    def test_a_tag_expression_keeps_only_the_matching_items(self):
        out, report = ov.filter_model(model(), ["tag:Application=payments"])
        self.assertIn("lb", addresses(out))
        self.assertIn("broker", addresses(out))
        self.assertNotIn("batch", addresses(out))
        self.assertNotIn("bastion", addresses(out))
        self.assertGreaterEqual(report["items_dropped"], 2)

    def test_a_defined_tag_is_addressed_by_its_namespaced_key(self):
        out, _ = ov.filter_model(model(), ["tag:Ops.Tier=gold"])
        self.assertIn("broker", addresses(out))
        self.assertNotIn("batch", addresses(out))
        out2, _ = ov.filter_model(model(), ["dtag:Ops.Tier=gold"])
        self.assertIn("broker", addresses(out2))
        out3, _ = ov.filter_model(model(), ["ftag:Ops.Tier=gold"])
        self.assertNotIn("broker", addresses(out3))

    def test_expressions_and_across_dimensions_and_or_within_one(self):
        out, _ = ov.filter_model(model(), ["tag:Application=payments", "tag:Environment=prod"])
        self.assertEqual({"lb", "broker"} & addresses(out), {"lb", "broker"})
        self.assertNotIn("batch", addresses(out))
        out2, _ = ov.filter_model(model(), ["name=Batch VM,Bastion"])
        self.assertEqual({"batch", "bastion"} & addresses(out2), {"batch", "bastion"})
        self.assertNotIn("broker", addresses(out2))

    def test_exclude_always_wins(self):
        out, _ = ov.filter_model(model(), {"include": ["tag:Application=payments"],
                                           "exclude": ["name=Web LB"]})
        self.assertNotIn("lb", addresses(out))
        self.assertIn("broker", addresses(out))

    def test_the_substring_operator_is_case_insensitive(self):
        out, _ = ov.filter_model(model(), ["name~BROKER"])
        self.assertIn("broker", addresses(out))
        self.assertNotIn("batch", addresses(out))

    def test_env_and_app_are_sugar_over_the_tag_dimension(self):
        out, _ = ov.filter_model(model(), ["env=nonprod"])
        self.assertEqual({"batch"} & addresses(out), {"batch"})
        self.assertNotIn("broker", addresses(out))
        out2, _ = ov.filter_model(model(), ["app=reporting"])
        self.assertIn("batch", addresses(out2))
        self.assertNotIn("lb", addresses(out2))

    def test_a_region_expression_is_a_whole_model_predicate(self):
        out, report = ov.filter_model(model(), ["region=us-ashburn-1"])
        self.assertEqual(addresses(out), addresses(model()))
        empty, report2 = ov.filter_model(model(), ["region=eu-frankfurt-1"])
        self.assertEqual(empty["vcns"], [])
        self.assertEqual(empty["services"], [])
        self.assertIsNone(empty["hub"])
        self.assertEqual(empty["drgs"], [])
        self.assertEqual(empty["edges"], [])
        self.assertGreater(report2["items_dropped"], 0)
        self.assertTrue(report)

    def test_a_filtered_out_region_empties_the_location_boxes_too(self):
        """6.5: it "either keeps or empties the model" - internet included."""
        m = model()
        m["internet"] = {"name": "Internet", "items": [
            {"icon": "user", "label": "Users", "address": "usr"}]}
        m["third_party"] = [{"name": "Other Cloud", "items": [
            {"icon": "vm", "label": "Peer VM", "address": "x3p"}]}]
        out, report = ov.filter_model(m, ["region=eu-frankfurt-1"])
        self.assertEqual(addresses(out), set())
        self.assertIsNone(out["internet"])
        self.assertEqual(out["third_party"], [])
        self.assertEqual(report["items_dropped"], 10)

    def test_structure_survives_a_predicate_that_does_not_name_it(self):
        """6.5: gateways, DRGs, attachments, subnets and VCNs are not predicated."""
        out, _ = ov.filter_model(model(), ["tag:Application=payments"])
        self.assertIn("nat", addresses(out))
        self.assertIn("drg", addresses(out))
        self.assertIn("att-app", addresses(out))
        self.assertEqual([v["name"] for v in out["vcns"]], ["vcn-app"])   # vcn-ops emptied out

    def test_a_vcn_expression_names_a_container_directly(self):
        out, report = ov.filter_model(model(), ["vcn=vcn-app"])
        self.assertEqual([v["name"] for v in out["vcns"]], ["vcn-app"])
        self.assertIn("bastion", addresses(model()))
        self.assertNotIn("bastion", addresses(out))
        # vcn-ops, its one subnet, and the On-premises box the CPE left behind.
        self.assertEqual(report["containers_dropped"], 3)
        self.assertIsNone(out["hub"])

    def test_a_subnet_expression_keeps_the_subnet_and_drops_its_siblings(self):
        out, _ = ov.filter_model(model(), ["subnet=sn-app"])
        self.assertEqual([s["name"] for v in out["vcns"] for s in v["subnets"]], ["sn-app"])
        self.assertIn("broker", addresses(out))

    def test_keep_empty_keeps_an_emptied_container(self):
        out, _ = ov.filter_model(model(), {"include": ["name=Bastion"], "keep_empty": True})
        self.assertEqual(sorted(v["name"] for v in out["vcns"]), ["vcn-app", "vcn-ops"])
        out2, _ = ov.filter_model(model(), {"include": ["name=Bastion"]})
        self.assertEqual([v["name"] for v in out2["vcns"]], ["vcn-ops"])

    def test_a_location_box_the_filter_empties_is_dropped(self):
        """An On-premises panel with nothing in it misleads the reader."""
        out, report = ov.filter_model(model(), ["type=oci_core_instance"])
        self.assertIsNone(out["hub"])
        self.assertGreaterEqual(report["containers_dropped"], 1)

    def test_keep_empty_keeps_an_emptied_location_box(self):
        out, _ = ov.filter_model(model(), {"include": ["type=oci_core_instance"],
                                           "keep_empty": True})
        self.assertIsInstance(out["hub"], dict)
        self.assertEqual(out["hub"]["items"], [])

    def test_a_box_that_was_already_empty_is_left_alone(self):
        """An empty Internet box is by design: it is what the IGW faces."""
        m = model()
        m["internet"] = {"name": "Internet", "items": []}
        out, _ = ov.filter_model(m, ["type=oci_core_instance"])
        self.assertEqual(out["internet"], {"name": "Internet", "items": []})

    def test_an_emptied_internet_box_survives_while_an_igw_still_faces_it(self):
        m = model()
        m["internet"] = {"name": "Internet", "items": [
            {"icon": "users", "label": "Users", "address": "users"}]}
        m["vcns"][0]["gateways"].append({"icon": "internet_gateway", "type": "igw",
                                         "label": "IGW", "address": "igw"})
        out, _ = ov.filter_model(m, ["type=oci_core_instance"])
        self.assertIsInstance(out["internet"], dict)
        self.assertEqual(out["internet"]["items"], [])
        m2 = copy.deepcopy(m)
        m2["vcns"][0]["gateways"] = [g for g in m2["vcns"][0]["gateways"] if g["type"] != "igw"]
        out2, _ = ov.filter_model(m2, ["type=oci_core_instance"])
        self.assertIsNone(out2["internet"])

    def test_an_edge_onto_a_dropped_location_box_goes_with_it(self):
        m = model()
        m["edges"].append({"source": "hub", "target": "broker", "label": "", "kind": "data",
                           "discovery": "user"})
        out, _ = ov.filter_model(m, ["type=oci_core_instance"])
        self.assertNotIn("hub", [e["source"] for e in out["edges"]])

    def test_an_emptied_third_party_box_is_dropped(self):
        m = model()
        m["third_party"] = [{"name": "3rd Party Cloud", "items": [
            {"icon": "vm", "label": "Peer VM", "type": "other", "address": "peer"}]}]
        out, _ = ov.filter_model(m, ["type=oci_core_instance"])
        self.assertEqual(out["third_party"], [])

    def test_an_edge_whose_endpoint_disappeared_is_dropped_and_counted(self):
        out, report = ov.filter_model(model(), ["name=App Broker VM"])
        self.assertEqual(out["edges"], [])
        self.assertEqual(report["edges_dropped"], 2)

    def test_a_discovery_selector_prunes_edges_without_touching_items(self):
        out, report = ov.filter_model(model(), discovery=("association",))
        self.assertEqual([e["source"] for e in out["edges"]], ["lb"])
        self.assertEqual(report["edges_dropped"], 1)
        self.assertIn("broker", addresses(out))
        self.assertIn("bastion", addresses(out))

    def test_a_comma_string_discovery_selector_is_read_like_every_other_list(self):
        """A CLI passes "association,user"; tuple() would explode it into characters."""
        out, report = ov.filter_model(model(), discovery="association,user")
        self.assertEqual([e["source"] for e in out["edges"]], ["lb"])
        self.assertEqual(report["edges_dropped"], 1)

    def test_a_discovery_filter_expression_works_through_the_same_predicate(self):
        out, _ = ov.filter_model(model(), ["!discovery=heuristic"])
        self.assertEqual([e["label"] for e in out["edges"]], ["8088"])

    def test_an_include_discovery_expression_prunes_edges_and_no_items(self):
        """6.8: provenance is a property of a relationship; an item has none.

        The exclude form passes whichever way the axis is wired, because an
        item's default "association" never equals the negated value. The
        include form is the one that used to empty the diagram.
        """
        for expr in ("discovery=heuristic", "discovery=config", "discovery=user"):
            with self.subTest(expr=expr):
                out, report = ov.filter_model(model(), [expr])
                self.assertEqual(addresses(out), addresses(model()))
                self.assertEqual(report["items_dropped"], 0)
                self.assertEqual(report["items_kept"], 8)
        kept, _ = ov.filter_model(model(), ["discovery=heuristic"])
        self.assertEqual([e["label"] for e in kept["edges"]], ["22"])

    def test_an_unknown_or_miscased_discovery_selector_is_rejected_not_silent(self):
        """resolve_view validates each kind; the two entry points must agree."""
        with self.assertRaises(ValueError):
            ov.filter_model(model(), discovery="assocation")
        out, report = ov.filter_model(model(), discovery="Association")
        self.assertEqual([e["source"] for e in out["edges"]], ["lb"])
        self.assertEqual(report["edges_dropped"], 1)

    def test_the_report_names_the_expressions_it_applied(self):
        _out, report = ov.filter_model(model(), {"include": ["vcn=vcn-app"],
                                                 "exclude": ["name=Batch VM"]})
        self.assertEqual(report["include"], ("vcn=vcn-app",))
        self.assertEqual(report["exclude"], ("name=Batch VM",))
        self.assertEqual(report["mode"], "all")


class ParticipatingTests(unittest.TestCase):
    def test_an_edge_endpoint_participates(self):
        keep = ov.participating(model())
        self.assertLessEqual({"lb", "broker", "bastion"}, keep)

    def test_structure_always_participates(self):
        keep = ov.participating(model())
        self.assertLessEqual({"nat", "drg", "att-app", "att-vpn", "cpe"}, keep)

    def test_a_badge_host_participates(self):
        self.assertIn("lb", ov.participating(model()))          # carries nsgs

    def test_a_group_member_participates(self):
        m = model()
        m["vcns"][0]["subnets"][1]["groups"] = [
            {"type": "oke_cluster", "label": "OKE", "items": ["batch"], "key": "oke-box"}]
        self.assertIn("batch", ov.participating(m))

    def test_an_item_named_by_an_include_expression_participates(self):
        parsed = ov.parse_filter(["name=Batch VM"])
        self.assertIn("batch", ov.participating(model(), include=parsed["include"]))

    def test_the_only_item_of_a_kept_subnet_participates(self):
        m = model()
        m["edges"] = []
        self.assertIn("bastion", ov.participating(m))           # sole item of sn-mgmt

    def test_an_unconnected_regional_service_does_not_participate(self):
        keep = ov.participating(model())
        self.assertNotIn("logs", keep)
        self.assertNotIn("vault", keep)
        self.assertNotIn("idcs", keep)

    def test_participating_mode_prunes_them_and_counts_the_prune(self):
        out, report = ov.filter_model(model(), mode="participating")
        self.assertNotIn("logs", addresses(out))
        self.assertNotIn("idcs", addresses(out))
        self.assertIn("broker", addresses(out))
        self.assertEqual(report["mode"], "participating")
        self.assertEqual(report["pruned_services"], 3)

    def test_a_container_level_include_expression_still_prunes(self):
        """6.6 clause 5 keeps what an expression names DIRECTLY.

        Every survivor of filter_model already satisfies the include list, so
        honouring region= / vcn= / compartment= here would keep everything and
        turn participating mode back into "all" - the live-tenancy case, where
        --compartment and --tag build exactly these expressions.
        """
        for spec in (["region=us-ashburn-1"], ["vcn=vcn-app"], ["compartment=app-prod"]):
            with self.subTest(spec=spec):
                out, report = ov.filter_model(model(), spec, mode="participating")
                self.assertNotIn("logs", addresses(out))
                self.assertNotIn("vault", addresses(out))
                self.assertGreater(report["pruned_services"], 0)
        out, _ = ov.filter_model(model(), ["name=Batch VM"], mode="participating")
        self.assertIn("batch", addresses(out))          # clause 5 still wins


class PruneDanglingTests(unittest.TestCase):
    def test_a_vcn_attachment_to_a_dropped_vcn_goes(self):
        m = model()
        m["vcns"] = [v for v in m["vcns"] if v["name"] == "vcn-app"]
        counts = ov.prune_dangling(m)
        self.assertEqual([a["address"] for a in m["drgs"][0]["attachments"]],
                         ["att-app", "att-vpn"])
        self.assertEqual(counts["attachments"], 1)

    def test_a_dangling_lpg_peer_is_nulled(self):
        m = model()
        m["vcns"][0]["gateways"].append({"icon": "remote_peering_gateway", "type": "lpg",
                                         "label": "LPG", "address": "lpg-a", "peer": "lpg-b"})
        counts = ov.prune_dangling(m)
        self.assertIsNone(m["vcns"][0]["gateways"][-1]["peer"])
        self.assertEqual(counts["peers"], 1)

    def test_an_edge_to_a_vanished_endpoint_is_dropped_and_counted(self):
        m = model()
        m["vcns"] = [v for v in m["vcns"] if v["name"] == "vcn-app"]
        counts = ov.prune_dangling(m)
        self.assertEqual([e["label"] for e in m["edges"]], ["8088"])
        self.assertEqual(counts["edges"], 1)

    def test_a_peer_naming_a_surviving_vcn_by_name_is_kept(self):
        m = model()
        m["vcns"][0]["gateways"].append({"icon": "remote_peering_gateway", "type": "lpg",
                                         "label": "LPG", "address": "lpg-a", "peer": "vcn-ops"})
        ov.prune_dangling(m)
        self.assertEqual(m["vcns"][0]["gateways"][-1]["peer"], "vcn-ops")

    def test_an_ipsec_attachment_whose_target_was_filtered_out_goes_too(self):
        """Otherwise build_diagram raises "edge endpoint 'cpe' not found"."""
        m = model()
        m["hub"] = None
        counts = ov.prune_dangling(m)
        self.assertEqual([a["address"] for a in m["drgs"][0]["attachments"]],
                         ["att-app", "att-ops"])
        self.assertEqual(counts["attachments"], 1)

    def test_an_attachment_target_the_walk_never_knew_is_left_alone(self):
        """Spec 11: an undrawn target must fail loudly, not lose the box in silence."""
        m = model()
        m["drgs"][0]["attachments"].append(
            {"type": "ipsec", "target": "cpe-not-drawn", "address": "att-x", "label": "IPSec 2"})
        counts = ov.prune_dangling(m, known=set(ov.model_addresses(m)))
        self.assertIn("att-x", [a["address"] for a in m["drgs"][0]["attachments"]])
        self.assertEqual(counts["attachments"], 0)
        ov.prune_dangling(m)                     # known=None keeps the strict behaviour
        self.assertNotIn("att-x", [a["address"] for a in m["drgs"][0]["attachments"]])

    def test_an_unfiltered_build_keeps_the_attachment_and_reports_nothing(self):
        m = model()
        m["drgs"][0]["attachments"].append(
            {"type": "ipsec", "target": "cpe-not-drawn", "address": "att-x", "label": "IPSec 2"})
        out, report = ov.filter_model(m, {})
        self.assertIn("att-x", [a["address"] for a in out["drgs"][0]["attachments"]])
        self.assertEqual(report["attachments_dropped"], 0)
        self.assertEqual(report["warnings"], [])

    def test_a_filter_still_prunes_the_attachments_it_orphans_and_counts_them(self):
        """vcn=vcn-app drops vcn-ops and, with it, the hub CPE the IPSec attachment needs."""
        out, report = ov.filter_model(model(), ["vcn=vcn-app"])
        self.assertEqual([a["address"] for a in out["drgs"][0]["attachments"]], ["att-app"])
        self.assertEqual(report["attachments_dropped"], 2)

    def test_an_orphaned_attachment_without_a_filter_is_reported(self):
        """6.5: the count is reported - mode=participating can orphan one with no filter."""
        m = model()
        m["drgs"][0]["attachments"].append(
            {"type": "ipsec", "target": "vault", "address": "att-y", "label": "IPSec 3"})
        out, report = ov.filter_model(m, {}, mode="participating")
        self.assertNotIn("att-y", [a["address"] for a in out["drgs"][0]["attachments"]])
        self.assertEqual(report["attachments_dropped"], 1)
        self.assertTrue([w for w in report["warnings"] if "DRG attachment" in w],
                        report["warnings"])

    def test_an_endpoint_the_walk_never_knew_is_not_treated_as_dangling(self):
        """The recipe's registry also resolves group keys, badges and container names."""
        m = model()
        m["edges"].append({"source": "lb", "target": "oke-box", "label": "", "kind": "association",
                           "discovery": "user"})
        ov.prune_dangling(m, known=set(ov.model_addresses(m)))
        self.assertIn("oke-box", [e["target"] for e in m["edges"]])
        ov.prune_dangling(m)                     # known=None keeps the strict behaviour
        self.assertNotIn("oke-box", [e["target"] for e in m["edges"]])
