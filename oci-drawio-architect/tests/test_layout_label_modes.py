"""Layout tests for the v1.5.0 label modes (C04) and the mode-aware caption box."""
from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import drawio_builder as db  # noqa: E402
import oci_layout as ol  # noqa: E402
import oci_topology as ot  # noqa: E402
import oci_view as ov  # noqa: E402


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def caption_of(d, cid):
    """The rendered caption of an icon, back in plain text.

    The registry stores the ESCAPED label, so a multi-line caption is joined
    with ``<br>``; both substitutions are needed or every multi-line assertion
    below compares against a single line.
    """
    return (d._cells[d._cells[cid]["label_id"]]["label"]
            .replace("<br>", "\n").replace("&amp;", "&"))


MODEL = {
    "subject": "views", "region": "us-ashburn-1", "region_label": "Ashburn",
    "vcns": [{
        "name": "vcn-app", "cidr": "10.0.0.0/16", "subnets": [
            {"name": "sn-app", "cidr": "10.0.2.0/24", "tier": "app", "public": False,
             "route_table": "rt-app", "security_lists": ["sl-app"], "items": [
                 {"icon": "vm", "label": "App Broker VM", "type": "oci_core_instance",
                  "address": "broker", "nsgs": [{"name": "nsg-app", "address": "nsg.app"}],
                  "metadata": {"private_ip": "10.0.2.47", "ports": "TCP/22, 8088",
                               "availability_domain": "Uocm:PHX-AD-1",
                               "fault_domain": "FAULT-DOMAIN-2", "compartment": "app-prod"}}]}],
        "gateways": [{"icon": "service_gateway", "type": "sgw", "label": "Service\nGateway",
                      "address": "sgw"}],
        "services": [{"icon": "logging", "label": "Logging", "address": "logs"}],
    }],
    "edges": [],
}


class PinTests(unittest.TestCase):
    def test_the_line_budget_tables_agree(self):
        self.assertEqual(ov.LABEL_LINE_BUDGET, db.LABEL_LINE_BUDGET)

    def test_the_subnet_label_enums_agree(self):
        self.assertEqual(ov.SUBNET_LABEL_MODES, ot.SUBNET_LABEL_MODES)


class CaptionRenderingTests(unittest.TestCase):
    def build(self, **over):
        return quiet(ol.build_diagram, MODEL, **over)

    def test_the_default_caption_is_the_network_mode(self):
        """D1: name + private IP + port / protocol."""
        d = self.build()
        self.assertEqual(caption_of(d, "broker"), "App Broker VM\n10.0.2.47\nTCP/22, 8088")
        self.assertEqual(d.layout_info["view"]["label_mode"], "network")

    def test_minimal_is_the_authored_name_alone(self):
        self.assertEqual(caption_of(self.build(label_mode="minimal"), "broker"), "App Broker VM")

    def test_detailed_adds_the_ad_fd_pair_and_the_compartment(self):
        self.assertEqual(caption_of(self.build(label_mode="detailed"), "broker"),
                         "App Broker VM\n10.0.2.47\nAD-1 / FD-2\nCompartment: app-prod")

    def test_explicit_label_fields_win_over_the_mode(self):
        d = self.build(label_fields=["display_name", "resource_type"])
        # RESOURCE_ICONS["oci_core_instance"][1] is "Instance" - Oracle's own
        # wording, which _type_labels() hands to the renderer.
        self.assertEqual(caption_of(d, "broker"), "App Broker VM\nInstance")

    def test_a_gateway_caption_is_the_authored_form_in_every_mode(self):
        for mode in ("minimal", "network", "detailed"):
            self.assertTrue(caption_of(self.build(label_mode=mode), "sgw").startswith(
                "Service\nGateway"), mode)


class CaptionGeometryTests(unittest.TestCase):
    def test_a_one_line_caption_keeps_the_1_4_box_in_the_network_mode(self):
        """V6: only the detailed mode grows the caption box.

        A three-line caption is auto-grown by add_icon to 46 px in 1.4.0 too,
        so the invariant that actually holds is per caption, not per document:
        _label_h / _row_h are unchanged and a ONE-line caption gets LABEL_H.
        """
        d = quiet(ol.build_diagram, MODEL)
        _x, _y, _w, h = d.bbox(d._cells["logs"]["label_id"])
        self.assertEqual(h, float(db.LABEL_H))
        self.assertEqual(ol._label_h(ov.resolve_view({})), db.LABEL_H)
        self.assertEqual(ol._row_h(ov.resolve_view({})), ol.ROW_H)

    def test_the_detailed_mode_grows_the_caption_box_and_the_row_pitch_only(self):
        view = ov.resolve_view({"label_mode": "detailed"})
        self.assertEqual(ol._label_h(view), db.LABEL_H_DETAILED)
        self.assertEqual(ol._row_h(view), ol.ROW_H + db.LABEL_H_DETAILED - db.LABEL_H)
        d = quiet(ol.build_diagram, MODEL, label_mode="detailed")
        _x, _y, w, h = d.bbox(d._cells["broker"]["label_id"])
        self.assertEqual((w, h), (float(db.LABEL_W), float(db.LABEL_H_DETAILED)))

    def test_the_slot_and_the_column_pitch_never_change(self):
        for mode in ("minimal", "network", "detailed"):
            d = quiet(ol.build_diagram, MODEL, label_mode=mode)
            e = d._cells["broker"]
            self.assertEqual((e["slot_w"], e["slot_h"]), (float(db.ICON_W), float(db.ICON_H)), mode)
        self.assertEqual((db.ICON_W, db.LABEL_W, db.COL_W), (75, 105, 130))

    def test_every_mode_validates_clean_and_strict(self):
        for mode in ("minimal", "network", "detailed"):
            d = quiet(ol.build_diagram, MODEL, label_mode=mode)
            self.assertEqual([m for m in d.validate() if not db.is_warning(m)], [], mode)
            self.assertEqual(d.check_overlaps(strict=True), [], mode)

    def test_the_builder_ceiling_follows_the_mode(self):
        self.assertEqual(quiet(ol.build_diagram, MODEL).max_label_lines, 3)
        self.assertEqual(quiet(ol.build_diagram, MODEL, label_mode="detailed").max_label_lines, 5)


class ContainerTitleTests(unittest.TestCase):
    def test_the_name_mode_drops_the_cidr_and_keeps_the_token(self):
        self.assertEqual(ol._subnet_title_lines(MODEL["vcns"][0]["subnets"][0], "name"),
                         ["sn-app (Private)"])
        self.assertEqual(ol._vcn_title_lines(MODEL["vcns"][0], "name"), ["VCN: vcn-app"])

    def test_twoline_and_inline_are_unchanged(self):
        sn = MODEL["vcns"][0]["subnets"][0]
        self.assertEqual(ol._subnet_title_lines(sn, "twoline"),
                         ["sn-app (Private)", "10.0.2.0/24"])
        self.assertEqual(ol._subnet_title_lines(sn, "inline"), ["sn-app (10.0.2.0/24)"])

    def test_a_minimal_view_titles_the_subnet_by_name(self):
        """6.3: 'show subnet CIDRs when the view is network-focused', made mechanical."""
        d = quiet(ol.build_diagram, MODEL, label_mode="minimal", subnet_label="name")
        # _new_id() slugs a key, so the cell id is "subnet-sn-app", never "subnet:sn-app".
        self.assertEqual(d._cells["subnet-sn-app"]["label"], "sn-app (Private)")
        self.assertNotIn("10.0.2.0/24", d._cells["subnet-sn-app"]["label"])


class BadgeTooltipTests(unittest.TestCase):
    def test_network_names_the_construct_and_detailed_adds_its_address(self):
        refs = [{"name": "rt-app", "address": "oci_core_route_table.app"}]
        self.assertEqual(ol._badge_tooltip("Route table", refs), "Route table: rt-app")
        self.assertEqual(ol._badge_tooltip("Route table", refs, detailed=True),
                         "Route table: rt-app (oci_core_route_table.app)")

    def test_a_ref_without_an_address_is_unchanged_in_both_modes(self):
        refs = [{"name": "sl-app", "address": None}]
        self.assertEqual(ol._badge_tooltip("Security list", refs, detailed=True),
                         "Security list: sl-app")


class EdgeLabelTests(unittest.TestCase):
    def test_minimal_drops_the_connector_labels(self):
        model = dict(MODEL, edges=[{"source": "broker", "target": "logs", "label": "443",
                                    "kind": "control"}])
        d = quiet(ol.build_diagram, model)
        self.assertIn("443", [e["label"] for e in d._cells.values() if e["kind"] == "edge"])
        d2 = quiet(ol.build_diagram, model, label_mode="minimal")
        self.assertNotIn("443", [e["label"] for e in d2._cells.values() if e["kind"] == "edge"])


# 6.3 "Per element" lists hub items alongside the workloads and the services,
# so every item placed by _place_hub_items - the nested on-premises panel, the
# page-level On-Premises box and the Internet / 3rd Party Cloud boxes - is
# captioned from the mode's field list too. The CPE is also the only element
# that reaches the private_ip field's metadata.ip_address fallback.
CANVAS_MODEL = {
    "subject": "canvas", "region": "us-ashburn-1", "locations": "outside",
    "hub": {"name": "On-Premises", "link_label": "trunk", "items": [
        {"icon": "cpe", "label": "Edge CPE", "address": "cpe",
         "metadata": {"ip_address": "203.0.113.5", "compartment": "net-prod",
                      "availability_domain": "Uocm:PHX-AD-1",
                      "fault_domain": "FAULT-DOMAIN-2"}},
        {"icon": "firewall", "label": "Edge Firewall", "address": "fw",
         "metadata": {"ip_address": "203.0.113.6"}}]},
    "internet": {"name": "Internet", "items": [
        {"icon": "user", "label": "Users", "address": "usr",
         "metadata": {"ip_address": "198.51.100.9"}}]},
    "third_party": [{"name": "3rd Party Cloud", "items": [
        {"icon": "vm", "label": "Partner VM", "address": "pvm",
         "metadata": {"ip_address": "192.0.2.10", "compartment": "partner-cmp"}}]}],
    "vcns": [{"name": "vcn-app", "cidr": "10.0.0.0/16", "subnets": [
        {"name": "sn-app", "cidr": "10.0.2.0/24", "tier": "app", "public": False, "items": [
            {"icon": "vm", "label": "App VM", "address": "vm"}]}]}],
    "edges": [],
}

NESTED_HUB_MODEL = dict(CANVAS_MODEL, locations="nested", internet=None, third_party=[])


class HubItemCaptionTests(unittest.TestCase):
    def build(self, model=None, **over):
        return quiet(ol.build_diagram, model or CANVAS_MODEL, **over)

    def test_the_network_mode_captions_a_hub_item_with_its_ip(self):
        """The private_ip field's metadata.ip_address fallback, which only a CPE reaches."""
        self.assertEqual(caption_of(self.build(), "cpe"), "Edge CPE\n203.0.113.5")

    def test_the_detailed_mode_captions_a_hub_item_in_full(self):
        self.assertEqual(caption_of(self.build(label_mode="detailed"), "cpe"),
                         "Edge CPE\n203.0.113.5\nAD-1 / FD-2\nCompartment: net-prod")

    def test_the_minimal_mode_leaves_a_hub_item_at_its_name(self):
        self.assertEqual(caption_of(self.build(label_mode="minimal"), "cpe"), "Edge CPE")

    def test_the_internet_and_third_party_boxes_caption_their_items_too(self):
        d = self.build()
        self.assertEqual(caption_of(d, "usr"), "Users\n198.51.100.9")
        self.assertEqual(caption_of(d, "pvm"), "Partner VM\n192.0.2.10")

    def test_the_nested_on_premises_panel_captions_its_items_too(self):
        d = self.build(NESTED_HUB_MODEL)
        self.assertEqual(caption_of(d, "cpe"), "Edge CPE\n203.0.113.5")

    def test_every_mode_validates_clean_and_strict_on_both_canvases(self):
        for model, name in ((CANVAS_MODEL, "outside"), (NESTED_HUB_MODEL, "nested")):
            for mode in ("minimal", "network", "detailed"):
                d = self.build(model, label_mode=mode)
                self.assertEqual([m for m in d.validate() if not db.is_warning(m)], [],
                                 (name, mode))
                self.assertEqual(d.check_overlaps(strict=True), [], (name, mode))


class StructuralEdgeLabelTests(unittest.TestCase):
    """6.3: the edge-label gate has no carve-out, so every labelled path obeys it."""

    def edge_labels(self, **over):
        d = quiet(ol.build_diagram, ATTACHMENT_MODEL, **over)
        return {e["label"] for e in d._cells.values() if e["kind"] == "edge"}

    def test_the_hub_link_label_follows_the_gate(self):
        self.assertIn("trunk", {e["label"] for e in
                                quiet(ol.build_diagram, CANVAS_MODEL)._cells.values()
                                if e["kind"] == "edge"})
        self.assertNotIn("trunk", {e["label"] for e in
                                   quiet(ol.build_diagram, CANVAS_MODEL,
                                         label_mode="minimal")._cells.values()
                                   if e["kind"] == "edge"})

    def test_the_drg_attachment_label_follows_the_gate(self):
        """oci_topology.ATTACHMENT_LINK_LABELS is real text, not a structural blank."""
        self.assertIn("Site-to-Site VPN", self.edge_labels())
        self.assertNotIn("Site-to-Site VPN", self.edge_labels(label_mode="minimal"))

    def test_the_connectors_themselves_are_still_drawn_in_the_minimal_mode(self):
        kept = len([e for e in quiet(ol.build_diagram, ATTACHMENT_MODEL)._cells.values()
                    if e["kind"] == "edge"])
        dropped = len([e for e in quiet(ol.build_diagram, ATTACHMENT_MODEL,
                                        label_mode="minimal")._cells.values()
                       if e["kind"] == "edge"])
        self.assertEqual(kept, dropped)


ATTACHMENT_MODEL = {
    "subject": "attachments", "region": "us-ashburn-1",
    "hub": {"name": "On-Premises", "link_label": "trunk", "items": [
        {"icon": "cpe", "label": "Edge CPE", "address": "cpe"},
        {"icon": "firewall", "label": "Edge Firewall", "address": "fw"}]},
    "drgs": [{"name": "DRG", "address": "drg", "drg_style": "box", "attachments": [
        {"type": "ipsec", "name": "vpn-1", "target": "cpe", "address": "att-vpn"},
        {"type": "vcn", "name": "vcn-app", "vcn": "vcn-app", "address": "att-vcn"}]}],
    "vcns": [{"name": "vcn-app", "cidr": "10.0.0.0/16", "subnets": [
        {"name": "sn-app", "cidr": "10.0.2.0/24", "tier": "app", "public": False, "items": [
            {"icon": "vm", "label": "App VM", "address": "vm"}]}]}],
    "edges": [],
}
