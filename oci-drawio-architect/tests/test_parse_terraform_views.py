"""Parser tests for the v1.5.0 tags, caption metadata, discovery provenance and filter flags."""
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
FIXTURES = TESTS_DIR / "fixtures" / "terraform"
sys.path.insert(0, str(SCRIPTS_DIR))
import oci_view as ov  # noqa: E402
import parse_terraform as pt  # noqa: E402


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def parsed():
    return quiet(pt.parse_terraform_dir, FIXTURES / "tagged_app")


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


class AddressWalkTests(unittest.TestCase):
    def test_the_two_address_walks_agree(self):
        """oci_view duplicates the walk deliberately; this is the pin."""
        for name in ("three_tier", "hub_spoke", "landing_zone", "tagged_app"):
            model = quiet(pt.parse_terraform_dir, FIXTURES / name)
            self.assertEqual(list(ov.model_addresses(model)), list(pt.model_addresses(model)), name)


class TagCaptureTests(unittest.TestCase):
    def test_hcl_freeform_tags_survive_ingestion(self):
        self.assertEqual(item(parsed(), "oci_core_instance.broker")["tags"]["freeform"],
                         {"Application": "payments", "Environment": "prod"})

    def test_hcl_defined_tags_keep_their_namespaced_key(self):
        self.assertEqual(item(parsed(), "oci_core_instance.broker")["tags"]["defined"],
                         {"Ops.Tier": "gold"})

    def test_a_variable_reference_that_resolves_is_kept(self):
        model = parsed()
        self.assertEqual([v for v in model["vcns"] if v["name"] == "vcn-app"][0]["tags"]["freeform"],
                         {"Application": "payments"})

    def test_an_unresolvable_tag_value_is_skipped_with_a_warning(self):
        model = parsed()
        tags = item(model, "oci_core_instance.batch")["tags"]["freeform"]
        self.assertEqual(tags, {"Application": "reporting"})
        self.assertTrue([w for w in model["warnings"]
                         if "freeform_tags" in w and "Environment" in w], model["warnings"])

    def test_state_json_tags_are_flattened_into_the_same_shape(self):
        model = quiet(pt.parse_show_json, FIXTURES / "tagged_app" / "state.json", "state")
        broker = item(model, "oci_core_instance.broker")
        self.assertEqual(broker["tags"]["freeform"],
                         {"Application": "payments", "Environment": "prod"})
        self.assertEqual(broker["tags"]["defined"], {"Ops.Tier": "gold"})

    def test_an_untagged_resource_carries_no_tags_key_at_all(self):
        """5: tags are a sibling key, written only when there is something to write."""
        listener = [r for r in quiet(pt.collect_hcl_resources,
                                     pt.ds.TerraformContext(FIXTURES / "tagged_app"))
                    if r.rtype == "oci_load_balancer_listener"][0]
        self.assertEqual(listener.tags, {"freeform": {}, "defined": {}})
        self.assertNotIn("tags", pt.new_item("vm", "X", "oci_core_instance", "x", {},
                                             {"freeform": {}, "defined": {}}))


class CaptionMetadataTests(unittest.TestCase):
    def test_the_shape_line_leaves_the_label_and_stays_in_the_metadata(self):
        """D1 / 6.3: the visible default change for a parsed model."""
        broker = item(parsed(), "oci_core_instance.broker")
        self.assertEqual(broker["label"], "App Broker VM")
        self.assertEqual(broker["metadata"]["shape"], "VM.Standard.E5.Flex")

    def test_the_private_ip_comes_from_a_state_json(self):
        model = quiet(pt.parse_show_json, FIXTURES / "tagged_app" / "state.json", "state")
        self.assertEqual(item(model, "oci_core_instance.broker")["metadata"]["private_ip"],
                         "10.0.1.47")

    def test_a_null_public_ip_is_simply_absent(self):
        model = quiet(pt.parse_show_json, FIXTURES / "tagged_app" / "state.json", "state")
        self.assertNotIn("public_ip", item(model, "oci_core_instance.broker")["metadata"])

    def test_the_lifecycle_state_and_hostname_reach_the_metadata(self):
        model = quiet(pt.parse_show_json, FIXTURES / "tagged_app" / "state.json", "state")
        meta = item(model, "oci_core_instance.broker")["metadata"]
        self.assertEqual(meta["lifecycle_state"], "RUNNING")
        self.assertEqual(meta["hostname_label"], "broker")

    def test_the_compartment_name_reaches_every_item(self):
        self.assertIn("compartment", item(parsed(), "oci_core_instance.broker")["metadata"])

    def test_listener_ports_become_the_load_balancers_port_metadata(self):
        self.assertEqual(item(parsed(), "oci_load_balancer_load_balancer.web")["metadata"]["ports"],
                         "HTTP/443")

    def test_a_database_gets_its_well_known_port(self):
        self.assertEqual(
            item(parsed(), "oci_database_autonomous_database.core")["metadata"]["ports"], "1522")

    def test_the_ad_and_fd_were_already_captured_and_still_are(self):
        meta = item(parsed(), "oci_core_instance.broker")["metadata"]
        self.assertEqual((meta["availability_domain"], meta["fault_domain"]),
                         ("Uocm:PHX-AD-1", "FAULT-DOMAIN-2"))


class DiscoveryTests(unittest.TestCase):
    def test_new_edge_writes_both_keys(self):
        """6.8: inferred is True for exactly the plausibility guesses, as in 1.4.0."""
        e = pt.new_edge("a", "b", "443", "data")
        self.assertEqual((e["discovery"], e["inferred"]), ("association", False))
        self.assertEqual(pt.new_edge("a", "b", discovery="reachability")["inferred"], False)
        self.assertEqual(pt.new_edge("a", "b", discovery="heuristic")["inferred"], True)

    def test_discovery_is_keyword_only_and_the_fifth_positional_is_still_inferred(self):
        """query_tenancy.py and the v1.4.0 parser suite both call new_edge(..., kind, inferred)."""
        self.assertIs(pt.new_edge("a", "b", "443", "control", False)["inferred"], False)
        self.assertIs(pt.new_edge("a", "b", "443", "control", True)["inferred"], True)
        with self.assertRaises(TypeError):
            pt.new_edge("a", "b", "443", "data", False, "reachability")

    def test_an_explicit_inferred_still_wins_for_a_legacy_caller(self):
        self.assertEqual(pt.new_edge("a", "b", inferred=True)["inferred"], True)

    def test_an_unknown_discovery_value_raises(self):
        with self.assertRaises(ValueError):
            pt.new_edge("a", "b", discovery="telepathy")

    def test_every_edge_of_the_fixture_carries_a_discovery(self):
        for e in parsed()["edges"]:
            self.assertIn(e["discovery"], ov.DISCOVERY_KINDS, e)

    def test_a_heuristic_edge_says_so(self):
        # The load balancer is in sn-web and the app-tier compute in sn-app, which
        # is exactly the shape _heuristic_edges looks for (a different subnet).
        kinds = {(e["source"], e["target"]): e["discovery"] for e in parsed()["edges"]}
        self.assertEqual(kinds[("oci_load_balancer_load_balancer.web",
                                "oci_core_instance.batch")], "heuristic")

    def test_a_resolved_reference_between_two_drawn_items_is_a_config_edge(self):
        kinds = {e["discovery"] for e in parsed()["edges"]}
        self.assertIn("config", kinds)

    def test_no_inferred_edges_keeps_the_association_config_and_user_edges(self):
        model = quiet(pt.parse_terraform_dir, FIXTURES / "tagged_app", inferred_edges=False)
        self.assertEqual({e["discovery"] for e in model["edges"]} - set(ov.NO_INFERRED_DISCOVERY),
                         set())


class RelationshipsTests(unittest.TestCase):
    def test_a_sidecar_merges_as_user_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            side = Path(tmp) / "rel.json"
            side.write_text(json.dumps([
                {"source": "oci_core_instance.broker",
                 "target": "oci_database_autonomous_database.core",
                 "label": "1522", "kind": "data"}]), encoding="utf-8")
            edges = pt.load_relationships(side)
        self.assertEqual(edges[0]["discovery"], "user")
        self.assertEqual(edges[0]["kind"], "data")

    def test_a_malformed_sidecar_raises_an_input_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            side = Path(tmp) / "rel.json"
            side.write_text('[{"source": "a"}]', encoding="utf-8")
            with self.assertRaises(pt.InputError):
                pt.load_relationships(side)


class SelectVcnTests(unittest.TestCase):
    def test_select_vcn_still_behaves_exactly_as_before(self):
        model = quiet(pt.parse_terraform_dir, FIXTURES / "hub_spoke")
        names = [v["name"] for v in model["vcns"]]
        self.assertTrue(pt.select_vcn(model, names[0]))
        self.assertEqual([v["name"] for v in model["vcns"]], [names[0]])
        self.assertEqual(model["subject"], names[0])
        alive = set(pt.model_addresses(model))
        for e in model["edges"]:
            self.assertIn(e["source"], alive)
            self.assertIn(e["target"], alive)
        for drg in model["drgs"]:
            for att in drg["attachments"]:
                if att["type"] == "vcn":
                    self.assertEqual(att["vcn"], names[0])


class ValidateModelTests(unittest.TestCase):
    def base(self):
        return quiet(pt.parse_terraform_dir, FIXTURES / "tagged_app")

    def test_a_parsed_model_validates(self):
        self.assertEqual(pt.validate_model(self.base()), [])

    def test_every_new_view_key_is_accepted(self):
        m = self.base()
        m.update({"purpose": "security", "detail": "engineering", "label_mode": "detailed",
                  "label_fields": ["display_name", "private_ip"], "label_tag_keys": ["Environment"],
                  "layers": "auto", "hidden_layers": ["routes"], "mode": "participating",
                  "global_services": "bucket", "show_edges": False,
                  "filter": {"include": ["vcn=vcn-app"], "exclude": ["type=x"]},
                  "subnet_label": "name"})
        self.assertEqual(pt.validate_model(m), [])
        m["filter"] = ["vcn=vcn-app", "!type=x"]
        self.assertEqual(pt.validate_model(m), [])

    def test_a_bad_value_of_each_new_key_is_rejected(self):
        for key, bad in (("purpose", "pretty"), ("detail", "medium"), ("label_mode", "verbose"),
                         ("mode", "some"), ("global_services", "everywhere"),
                         ("subnet_label", "fancy"), ("layers", ["nonsense"]),
                         ("hidden_layers", ["nonsense"]), ("label_fields", ["ocid"]),
                         ("show_edges", "yes"), ("filter", 7)):
            m = self.base()
            m[key] = bad
            self.assertTrue(pt.validate_model(m), f"{key}={bad!r} should be rejected")

    def test_an_unknown_discovery_on_an_edge_is_rejected(self):
        m = self.base()
        m["edges"][0]["discovery"] = "telepathy"
        self.assertTrue([e for e in pt.validate_model(m) if "discovery" in e])

    def test_a_bad_tags_shape_is_rejected(self):
        m = self.base()
        item(m, "oci_core_instance.broker")["tags"] = ["Application=payments"]
        self.assertTrue([e for e in pt.validate_model(m) if "tags" in e])


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "m.json"
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                rc = pt.main([str(FIXTURES / "tagged_app"), "--out", str(out), *args])
            return rc, json.loads(out.read_text(encoding="utf-8")), err.getvalue()

    def test_the_default_mode_is_all(self):
        """A1: a Terraform configuration is already a curated set."""
        self.assertEqual(pt.DEFAULT_MODE, "all")
        rc, model, _err = self.run_cli()
        self.assertEqual(rc, 0)
        self.assertEqual(model["mode"], "all")

    def test_the_tag_flag_is_sugar_for_an_include_expression(self):
        _rc, model, _err = self.run_cli("--tag", "Application=reporting")
        self.assertEqual(model["filter"]["include"], ["tag:Application=reporting"])
        addresses = set(pt.model_addresses(model))
        self.assertNotIn("oci_core_instance.broker", addresses)

    def test_the_compartment_subnet_and_resource_type_flags_are_sugar_too(self):
        _rc, model, _err = self.run_cli("--subnet", "sn-web",
                                        "--resource-type", "oci_core_instance")
        self.assertEqual(sorted(model["filter"]["include"]),
                         ["subnet=sn-web", "type=oci_core_instance"])

    def test_the_mode_flag_reaches_the_model_and_the_summary(self):
        _rc, model, err = self.run_cli("--mode", "participating")
        self.assertEqual(model["mode"], "participating")
        self.assertIn("pruned", err)

    def test_the_summary_reports_the_filter_counts(self):
        _rc, _model, err = self.run_cli("--filter", "tag:Application=payments")
        self.assertIn("filtered", err)

    def test_the_discovery_flag_prunes_the_edges(self):
        _rc, model, _err = self.run_cli("--discovery", "association")
        self.assertEqual({e["discovery"] for e in model["edges"]} - {"association"}, set())

    def test_a_relationships_sidecar_is_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            side = Path(tmp) / "rel.json"
            side.write_text(json.dumps([
                {"source": "oci_core_instance.broker",
                 "target": "oci_database_autonomous_database.core",
                 "label": "1522", "kind": "data"}]), encoding="utf-8")
            _rc, model, _err = self.run_cli("--relationships", str(side))
        self.assertIn("user", {e["discovery"] for e in model["edges"]})
