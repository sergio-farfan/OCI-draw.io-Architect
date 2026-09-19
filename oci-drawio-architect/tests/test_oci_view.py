"""Unit tests for scripts/oci_view.py - presets, view resolution, caption rendering."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import oci_view as ov  # noqa: E402


class PresetTableTests(unittest.TestCase):
    def test_the_six_purposes_are_the_guidelines_six_in_order(self):
        self.assertEqual(ov.PURPOSES_ORDER,
                         ("network", "dataflow", "security", "inventory", "dependency", "ha"))
        self.assertEqual(tuple(ov.PURPOSES), ov.PURPOSES_ORDER)
        self.assertEqual(list(ov.PURPOSE_TITLES.values()),
                         ["Network topology", "Application / data flow", "Security architecture",
                          "Resource / inventory view", "Dependency / relationship view",
                          "Deployment / high-availability architecture"])

    def test_the_four_detail_levels_define_every_gate(self):
        self.assertEqual(ov.DETAIL_ORDER, ("executive", "application", "network", "engineering"))
        for name in ov.DETAIL_ORDER:
            for gate in ov.GATE_KEYS:
                self.assertIn(gate, ov.DETAIL_LEVELS[name], f"{name}.{gate}")

    def test_the_executive_level_is_the_only_one_that_drops_structure(self):
        ex = ov.DETAIL_LEVELS["executive"]
        self.assertEqual((ex["subnet_cidr"], ex["badges_routes"], ex["badges_security"],
                          ex["drg_route_table"], ex["drg_attachments"], ex["edge_labels"]),
                         (False, False, False, False, False, False))
        self.assertTrue(ex["gateways"] and ex["osn"])
        for name in ("application", "network", "engineering"):
            self.assertTrue(ov.DETAIL_LEVELS[name]["drg_attachments"], name)

    def test_the_drg_route_table_survives_from_the_network_level_up(self):
        """Ruling: the default level keeps the 1.4.0 DRG route-table badge (spec 11)."""
        self.assertEqual([n for n in ov.DETAIL_ORDER if ov.DETAIL_LEVELS[n]["drg_route_table"]],
                         ["network", "engineering"])

    def test_the_three_label_modes_match_the_guidelines_examples(self):
        self.assertEqual(ov.LABEL_MODES["minimal"], ("display_name",))
        self.assertEqual(ov.LABEL_MODES["network"], ("display_name", "private_ip", "port_protocol"))
        self.assertEqual(ov.LABEL_MODES["detailed"],
                         ("display_name", "private_ip", "ad_fd", "compartment"))
        self.assertEqual(ov.LABEL_LINE_BUDGET, {"minimal": 2, "network": 3, "detailed": 5})

    def test_the_field_vocabulary_never_contains_the_ocid(self):
        self.assertNotIn("ocid", ov.LABEL_FIELDS)
        self.assertIn("ocid", ov.NEVER_RENDERED)
        # Spec 11's "1.4 caption" recipe is --label-fields display_name,shape,
        # so shape has to be a renderable field of its own.
        self.assertIn("shape", ov.LABEL_FIELDS)
        for mode_fields in ov.LABEL_MODES.values():
            for field in mode_fields:
                self.assertIn(field, ov.LABEL_FIELDS)

    def test_the_six_layers_are_the_layerable_ones_only(self):
        self.assertEqual(ov.VIEW_LAYERS,
                         ("routes", "security", "iam", "dataflow", "management", "associations"))
        self.assertEqual(ov.BASE_LAYER_NAME, "Network")
        self.assertEqual(sorted(ov.LAYER_TITLES), sorted(ov.VIEW_LAYERS))

    def test_the_discovery_enum_is_the_guidelines_six_plus_heuristic(self):
        self.assertEqual(ov.DISCOVERY_KINDS,
                         ("association", "config", "reachability", "tag", "observed", "user",
                          "heuristic"))
        self.assertEqual(ov.INFERRED_DISCOVERY, ("heuristic",))
        self.assertEqual(ov.NO_INFERRED_DISCOVERY,
                         ("association", "config", "reachability", "user"))
        self.assertEqual(sorted(set(ov.DISCOVERY_KINDS) - set(ov.NO_INFERRED_DISCOVERY)),
                         ["heuristic", "observed", "tag"])

    def test_every_purpose_names_a_known_detail_and_known_layers(self):
        for name, preset in ov.PURPOSES.items():
            self.assertIn(preset["detail"], ov.DETAIL_ORDER, name)
            for layer in preset["layers"]:
                self.assertIn(layer, ov.VIEW_LAYERS, f"{name}: {layer}")
            for layer in preset["hidden_layers"]:
                self.assertIn(layer, preset["layers"], f"{name}: hidden {layer} is not enabled")

    def test_security_and_inventory_switch_the_global_bucket_on(self):
        """A2: the bucket is opt-in, and automatic under exactly these two purposes."""
        self.assertEqual(sorted(n for n, p in ov.PURPOSES.items()
                                if p.get("global_services") == "bucket"),
                         ["inventory", "security"])
        self.assertEqual(ov.DEFAULTS["global_services"], "osn")

    def test_no_purpose_sets_a_filter(self):
        """6.9: a filter is about this tenancy, a purpose is about this diagram."""
        for name, preset in ov.PURPOSES.items():
            self.assertNotIn("filter", preset, name)

    def test_the_hard_defaults_are_the_1_4_behaviour_plus_the_one_caption_flip(self):
        self.assertEqual(ov.DEFAULTS["layers"], "off")            # A5 / V3
        self.assertEqual(ov.DEFAULTS["mode"], "all")              # A1
        self.assertEqual(ov.DEFAULTS["label_mode"], "network")    # D1
        self.assertEqual(ov.DEFAULTS["detail"], "network")
        self.assertIs(ov.DEFAULTS["show_edges"], True)
        self.assertIs(ov.DEFAULTS["show_compartments"], False)
        self.assertEqual(ov.DEFAULTS["subnet_label"], "twoline")


class ResolveViewTests(unittest.TestCase):
    def test_an_empty_model_resolves_to_the_1_4_behaviour(self):
        v = ov.resolve_view({})
        self.assertIsNone(v["purpose"])
        self.assertEqual((v["detail"], v["label_mode"]), ("network", "network"))
        self.assertEqual(v["label_fields"], ("display_name", "private_ip", "port_protocol"))
        self.assertEqual((v["layers_mode"], v["layers"], v["hidden_layers"]), ("off", (), ()))
        self.assertEqual((v["mode"], v["global_services"], v["subnet_label"]),
                         ("all", "osn", "twoline"))
        self.assertIs(v["show_edges"], True)
        self.assertIs(v["show_compartments"], False)
        self.assertIsNone(v["legend"])
        self.assertEqual(v["filter"], {"include": (), "exclude": (), "keep_empty": False})
        self.assertEqual(v["notes"], [])
        for gate in ("subnet_cidr", "badges_routes", "badges_security", "drg_route_table",
                     "drg_attachments", "gateways", "edge_labels", "osn"):
            self.assertIs(v[gate], True, gate)
        self.assertIs(v["edge_labels"], True)

    def test_an_override_beats_a_model_key(self):
        v = ov.resolve_view({"label_mode": "detailed"}, label_mode="minimal")
        self.assertEqual(v["label_mode"], "minimal")
        self.assertEqual(v["label_fields"], ("display_name",))

    def test_a_model_key_beats_the_detail_preset(self):
        v = ov.resolve_view({"detail": "executive", "label_mode": "detailed"})
        self.assertEqual(v["label_mode"], "detailed")
        self.assertIs(v["badges_routes"], False)          # the gate still comes from the level

    def test_an_explicit_detail_beats_the_purpose_it_did_not_choose(self):
        v = ov.resolve_view({"purpose": "security", "detail": "engineering"})
        self.assertEqual(v["detail"], "engineering")
        self.assertEqual(v["label_mode"], "detailed")     # engineering's, not security's
        self.assertIs(v["drg_route_table"], True)

    def test_a_purpose_derived_detail_does_not_beat_the_purpose(self):
        """6.9: the purpose selected 'network', so security's field list still wins."""
        v = ov.resolve_view({"purpose": "security"})
        self.assertEqual(v["detail"], "network")
        self.assertEqual(v["label_fields"], ("display_name", "private_ip"))
        self.assertEqual(v["global_services"], "bucket")
        self.assertIs(v["legend"], True)

    def test_label_fields_beat_the_label_mode(self):
        v = ov.resolve_view({"label_mode": "minimal", "label_fields": ["display_name", "fqdn"]})
        self.assertEqual(v["label_fields"], ("display_name", "fqdn"))
        self.assertEqual(v["label_mode"], "minimal")

    def test_every_purpose_resolves_and_keeps_layers_off(self):
        """A5: choosing a purpose composes the view; it does not turn layers on."""
        for name in ov.PURPOSES_ORDER:
            v = ov.resolve_view({"purpose": name})
            self.assertEqual(v["purpose"], name)
            self.assertEqual(v["layers_mode"], "off", name)
            self.assertEqual(v["layers"], (), name)

    def test_layers_auto_takes_the_purpose_set_and_hides_what_the_purpose_hides(self):
        v = ov.resolve_view({"purpose": "dataflow"}, layers="auto")
        self.assertEqual(v["layers_mode"], "auto")
        self.assertEqual(v["layers"], ("routes", "security", "dataflow", "management"))
        self.assertEqual(v["hidden_layers"], ("routes", "security"))

    def test_layers_auto_without_a_purpose_creates_every_layer_and_hides_the_rest(self):
        """6.2: auto = every layer whose content exists; the detail row is the VISIBLE set."""
        v = ov.resolve_view({"detail": "application"}, layers="auto")
        self.assertEqual(v["layers"], ov.VIEW_LAYERS)
        self.assertEqual(v["hidden_layers"], ("routes", "security", "iam", "associations"))
        v = ov.resolve_view({"detail": "executive"}, layers="auto")
        self.assertEqual(v["layers"], ov.VIEW_LAYERS)
        self.assertEqual(v["hidden_layers"],
                         ("routes", "security", "iam", "management", "associations"))
        v = ov.resolve_view({}, layers="auto")
        self.assertEqual(v["layers"], ov.VIEW_LAYERS)
        self.assertEqual(v["hidden_layers"], ())

    def test_layers_auto_at_an_elided_level_still_emits_the_badges(self):
        """6.4 / V4: '--detail application --layers auto ... emitted and hidden'."""
        v = ov.resolve_view({"detail": "application"}, layers="auto")
        self.assertIs(v["badges_routes"], False)
        self.assertIs(v["badges_security"], False)
        self.assertTrue(ov.draws(v, "badges_routes"))
        self.assertTrue(ov.draws(v, "badges_security"))
        self.assertIn("routes", v["hidden_layers"])
        self.assertIn("security", v["hidden_layers"])

    def test_a_gate_that_is_off_hides_its_layer_instead_of_dropping_it(self):
        """V4: an explicit --layers routes,security,dataflow emits the badges and hides them."""
        v = ov.resolve_view({"detail": "application"},
                            layers=["routes", "security", "dataflow"])
        self.assertEqual(v["layers_mode"], "explicit")
        self.assertEqual(v["layers"], ("routes", "security", "dataflow"))
        self.assertEqual(v["hidden_layers"], ("routes", "security"))
        self.assertIs(v["badges_routes"], False)
        self.assertTrue(ov.draws(v, "badges_routes"))
        self.assertTrue(ov.draws(v, "badges_security"))

    def test_a_gate_that_is_off_with_layers_off_drops_the_cells(self):
        v = ov.resolve_view({"detail": "application"})
        self.assertIs(v["badges_routes"], False)
        self.assertFalse(ov.draws(v, "badges_routes"))

    def test_an_ips_layer_is_rewritten_to_the_label_fields_with_a_note(self):
        v = ov.resolve_view({}, layers=["routes", "ips", "ports"])
        self.assertEqual(v["layers"], ("routes",))
        self.assertIn("private_ip", v["label_fields"])
        self.assertIn("public_ip", v["label_fields"])
        self.assertIn("port_protocol", v["label_fields"])
        self.assertEqual(v["notes"],
                         ["WARNING: layer 'ips' is a label field, not a cell layer; "
                          "added private_ip, public_ip to label_fields",
                          "WARNING: layer 'ports' is a label field, not a cell layer; "
                          "added port_protocol to label_fields"])
        # Both notes name the ALIAS's whole field list, not the delta actually
        # appended: the default network mode already carries private_ip and
        # port_protocol, so a delta-based note would read "added public_ip" and
        # "added nothing", which is what this assertion rules out.

    def test_an_executive_view_titles_subnets_without_their_cidr(self):
        self.assertEqual(ov.resolve_view({"detail": "executive"})["subnet_label"], "name")
        self.assertEqual(ov.resolve_view({"detail": "executive", "subnet_label": "inline"})
                         ["subnet_label"], "inline")

    def test_the_inventory_purpose_draws_no_connectors_and_shows_compartments(self):
        v = ov.resolve_view({"purpose": "inventory"})
        self.assertIs(v["show_edges"], False)
        self.assertIs(v["show_compartments"], True)
        self.assertEqual(v["global_services"], "bucket")
        self.assertEqual(v["label_fields"], ("display_name", "resource_type", "compartment"))

    def test_the_dependency_purpose_annotates_discovery(self):
        self.assertIs(ov.resolve_view({"purpose": "dependency"})["annotate_discovery"], True)

    def test_the_filter_spec_is_normalised_from_both_shapes(self):
        v = ov.resolve_view({"filter": {"include": ["vcn=vcn-app"], "exclude": ["type=x"]}})
        self.assertEqual(v["filter"], {"include": ("vcn=vcn-app",), "exclude": ("type=x",),
                                       "keep_empty": False})
        v2 = ov.resolve_view({}, filter=["vcn=vcn-app", "!type=x"])
        self.assertEqual(v2["filter"], {"include": ("vcn=vcn-app",), "exclude": ("type=x",),
                                        "keep_empty": False})

    def test_the_discovery_selector_is_normalised_and_validated(self):
        self.assertIsNone(ov.resolve_view({})["discovery"])
        self.assertEqual(ov.resolve_view({}, discovery="association, config")["discovery"],
                         ("association", "config"))
        with self.assertRaises(ValueError) as ctx:
            ov.resolve_view({}, discovery="guesswork")
        self.assertIn("discovery", str(ctx.exception))

    def test_the_line_budget_follows_the_mode_and_never_shrinks_below_the_field_count(self):
        self.assertEqual(ov.resolve_view({"label_mode": "minimal"})["line_budget"], 2)
        self.assertEqual(ov.resolve_view({"label_mode": "detailed"})["line_budget"], 5)
        self.assertEqual(ov.resolve_view(
            {"label_mode": "minimal",
             "label_fields": ["display_name", "private_ip", "fqdn", "compartment"]}
        )["line_budget"], 4)

    def test_unknown_values_and_unknown_keys_raise(self):
        for kwargs in ({"purpose": "pretty"}, {"detail": "medium"}, {"label_mode": "verbose"},
                       {"mode": "some"}, {"global_services": "everywhere"},
                       {"subnet_label": "fancy"}):
            with self.assertRaises(ValueError, msg=kwargs):
                ov.resolve_view(kwargs)
        with self.assertRaises(ValueError) as ctx:
            ov.resolve_view({"label_fields": ["display_name", "ocid"]})
        self.assertIn("ocid", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            ov.resolve_view({}, colour="purple")
        self.assertIn("unknown view key", str(ctx.exception))

    def test_the_view_is_json_serialisable_after_a_list_round_trip(self):
        import json
        v = ov.resolve_view({"purpose": "ha"}, layers="auto")
        text = json.dumps({k: (list(x) if isinstance(x, tuple) else x) for k, x in v.items()})
        self.assertIn('"ha"', text)


class RenderCaptionTests(unittest.TestCase):
    ITEM = {
        "icon": "vm", "label": "App Broker VM", "type": "oci_core_instance",
        "address": "oci_core_instance.broker",
        "metadata": {"shape": "VM.Standard.E5.Flex", "private_ip": "10.0.2.47",
                     "public_ip": "203.0.113.10", "fqdn": "broker.sub01.vcnapp.oraclevcn.com",
                     "availability_domain": "Uocm:PHX-AD-1", "fault_domain": "FAULT-DOMAIN-2",
                     "compartment": "app-prod", "lifecycle_state": "AVAILABLE",
                     "ports": "TCP/22, 8088"},
        "tags": {"freeform": {"Application": "payments", "Environment": "prod"}, "defined": {}},
    }

    def render(self, model=None, item=None, **over):
        return ov.render_caption(item or self.ITEM, ov.resolve_view(model or {}, **over))

    def test_minimal_is_the_authored_label_alone(self):
        self.assertEqual(self.render(label_mode="minimal"), "App Broker VM")

    def test_network_is_name_over_private_ip_over_ports(self):
        self.assertEqual(self.render(), "App Broker VM\n10.0.2.47\nTCP/22, 8088")

    def test_detailed_adds_the_ad_fd_pair_and_the_compartment(self):
        self.assertEqual(self.render(label_mode="detailed"),
                         "App Broker VM\n10.0.2.47\nAD-1 / FD-2\nCompartment: app-prod")

    def test_the_ad_name_is_reduced_to_its_trailing_ad_number(self):
        item = dict(self.ITEM, metadata=dict(self.ITEM["metadata"],
                                             availability_domain="kIdk:EU-FRANKFURT-1-AD-3",
                                             fault_domain="FAULT-DOMAIN-1"))
        self.assertIn("AD-3 / FD-1", self.render(item=item, label_mode="detailed"))

    def test_an_authored_multi_line_label_is_kept_verbatim_and_never_duplicated(self):
        """V5: the renderer never discards an authored caption."""
        item = {"label": "Load Balancer\n10.0.0.23", "metadata": {"private_ip": "10.0.0.23"}}
        self.assertEqual(self.render(item=item), "Load Balancer\n10.0.0.23")

    def test_the_dedupe_matches_whole_tokens_not_substrings(self):
        """V5 skips a value already rendered, not one that merely ends another."""
        item = {"label": "public-lb", "metadata": {"private_ip": "10.0.0.80", "ports": "80"}}
        self.assertEqual(self.render(item=item), "public-lb\n10.0.0.80\n80")
        item = {"label": "bastion", "metadata": {"private_ip": "10.0.0.22", "ports": "22"}}
        self.assertEqual(self.render(item=item), "bastion\n10.0.0.22\n22")

    def test_a_hand_wrapped_authored_caption_still_absorbs_the_rendered_form(self):
        """The whole-token rule keeps the multi-word V5 case working."""
        item = {"label": "Service\nGateway", "type": "sgw"}
        out = ov.render_caption(item, ov.resolve_view({}, label_mode="detailed"), kind="gateway")
        self.assertEqual(out, "Service\nGateway")

    def test_a_value_with_regex_metacharacters_is_matched_literally(self):
        item = {"label": "10.0.0.0/24 gw", "metadata": {"private_ip": "10.0.0.0/24"}}
        self.assertEqual(self.render(item=item), "10.0.0.0/24 gw")
        item = {"label": "app", "metadata": {"private_ip": "1a0b0c0d", "ports": "1.0.0.0"}}
        self.assertEqual(self.render(item=item), "app\n1a0b0c0d\n1.0.0.0")

    def test_a_missing_value_is_skipped_silently_with_no_empty_line(self):
        item = {"label": "Functions App", "metadata": {}}
        self.assertEqual(self.render(item=item), "Functions App")
        self.assertEqual(self.render(item=item, label_mode="detailed"), "Functions App")

    def test_the_ocid_is_never_rendered_in_any_mode(self):
        item = dict(self.ITEM, address="ocid1.instance.oc1..aaaaexample")
        for mode in ov.LABEL_MODE_ORDER:
            self.assertNotIn("ocid1.", self.render(item=item, label_mode=mode), mode)

    def test_public_ip_and_fqdn_are_opt_in_fields(self):
        out = self.render(label_fields=["display_name", "public_ip", "fqdn"])
        self.assertEqual(out.split("\n")[:2], ["App Broker VM", "203.0.113.10"])
        self.assertTrue(out.split("\n")[2].endswith("..."))
        self.assertLessEqual(len(out.split("\n")[2]), ov.FQDN_MAX_CHARS + 3)

    def test_lifecycle_renders_only_when_it_is_not_a_healthy_state(self):
        healthy = self.render(label_fields=["display_name", "lifecycle"])
        self.assertEqual(healthy, "App Broker VM")
        item = dict(self.ITEM, metadata=dict(self.ITEM["metadata"], lifecycle_state="STOPPED"))
        self.assertEqual(self.render(item=item, label_fields=["display_name", "lifecycle"]),
                         "App Broker VM\nSTOPPED")

    def test_tags_render_only_the_requested_keys_in_order(self):
        out = self.render(label_fields=["display_name", "tags"],
                          label_tag_keys=["Environment", "Application"])
        self.assertEqual(out, "App Broker VM\nEnvironment=prod\nApplication=payments")

    def test_a_defined_tag_is_addressed_by_its_namespaced_key(self):
        item = {"label": "App VM", "tags": {"freeform": {}, "defined": {"Ops.Environment": "prod"}}}
        self.assertEqual(self.render(item=item, label_fields=["display_name", "tags"],
                                     label_tag_keys=["Ops.Environment"]),
                         "App VM\nOps.Environment=prod")

    def test_private_ip_falls_back_to_the_cpe_ip_address_field(self):
        item = {"label": "Corp VPN", "metadata": {"ip_address": "203.0.113.1"}}
        self.assertEqual(self.render(item=item), "Corp VPN\n203.0.113.1")

    def test_resource_type_uses_the_supplied_human_label_then_a_fallback(self):
        view = ov.resolve_view({}, label_fields=["display_name", "resource_type"])
        self.assertEqual(ov.render_caption(self.ITEM, view,
                                           type_labels={"oci_core_instance": "Compute instance"}),
                         "App Broker VM\nCompute instance")
        self.assertEqual(ov.render_caption(self.ITEM, view), "App Broker VM\nCore instance")
        self.assertEqual(ov.humanise_type("oci_containerengine_node_pool"),
                         "Containerengine node pool")

    def test_a_gateway_caption_is_the_authored_two_line_form_in_every_mode(self):
        """V5: 'Sgw' is not a resource type, and 'Service gateway' is already said."""
        gw = {"label": "Service\nGateway", "type": "sgw",
              "metadata": {"private_ip": "10.0.0.9", "ports": "443"}}
        for mode in ov.LABEL_MODE_ORDER:
            view = ov.resolve_view({}, label_mode=mode)
            self.assertEqual(ov.render_caption(gw, view, kind="gateway"),
                             "Service\nGateway", mode)

    def test_a_gateway_type_renders_its_human_name_when_the_caption_omits_it(self):
        gw = {"label": "Corp egress", "type": "nat"}
        view = ov.resolve_view({}, label_mode="detailed")
        self.assertEqual(ov.render_caption(gw, view, kind="gateway"),
                         "Corp egress\nNAT gateway")
        self.assertEqual(ov.GATEWAY_TYPE_LABELS["lpg"], "Local peering gateway")

    def test_caption_lines_returns_the_same_content_as_a_list(self):
        view = ov.resolve_view({})
        self.assertEqual(ov.caption_lines(self.ITEM, view),
                         ["App Broker VM", "10.0.2.47", "TCP/22, 8088"])
