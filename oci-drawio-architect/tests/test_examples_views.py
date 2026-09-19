"""Example tests for the v1.5.0 reference-sample migration (A3) and the six-page demo."""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = TESTS_DIR.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import check_overlaps  # noqa: E402
import oci_layout as ol  # noqa: E402


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def caption_of(d, cid):
    """The rendered caption, back in plain text (the registry stores it escaped)."""
    return (d._cells[d._cells[cid]["label_id"]]["label"]
            .replace("<br>", "\n").replace("&amp;", "&"))


class ExamplesPathMixin:
    """``examples/`` on sys.path for the duration of the class, exactly as ExamplesTests does.

    Inserting it permanently at import time would leak into every other test
    module in the same process.
    """

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(PLUGIN_ROOT / "examples"))
        cls.addClassCleanup(sys.path.remove, str(PLUGIN_ROOT / "examples"))


class ReferenceMigrationTests(ExamplesPathMixin, unittest.TestCase):
    def model(self):
        from generate_reference_layout import MODEL
        return MODEL

    def items(self):
        out = {}
        for vcn in self.model()["vcns"]:
            for sn in vcn["subnets"]:
                for it in sn["items"]:
                    out[it["address"]] = it
            for it in vcn["services"]:
                out[it["address"]] = it
        return out

    def test_the_load_balancer_renders_its_ip_from_the_metadata(self):
        """A3 / V5: the sample exercises the renderer instead of bypassing it.

        The network mode renders three fields, so this caption gains an
        HTTPS/443 line that 1.4.0 did not draw. That is the one accepted
        deviation from A3's "rendered text identical" (see the Self-review).
        """
        lb = self.items()["lb"]
        self.assertEqual(lb["label"], "Load Balancer")
        self.assertEqual(lb["metadata"]["private_ip"], "10.0.0.23")
        d = quiet(ol.build_diagram, self.model())
        self.assertEqual(caption_of(d, "lb"), "Load Balancer\n10.0.0.23\nHTTPS/443")

    def test_an_item_whose_ip_is_not_the_last_authored_line_keeps_its_caption(self):
        """V5's dedupe rule: the metadata is provenance, the caption is unchanged."""
        vm = self.items()["app-vm"]
        self.assertEqual(vm["label"], "App VM\n10.0.1.251\n16 OCPU / 96 GB")
        self.assertEqual(vm["metadata"]["private_ip"], "10.0.1.251")
        d = quiet(ol.build_diagram, self.model())
        self.assertEqual(caption_of(d, "app-vm"), "App VM\n10.0.1.251\n16 OCPU / 96 GB")

    def test_the_database_and_the_load_balancer_carry_ports(self):
        self.assertEqual(self.items()["adb"]["metadata"]["ports"], "1522")
        self.assertEqual(self.items()["lb"]["metadata"]["ports"], "HTTPS/443")

    def test_every_metadata_address_and_port_reaches_the_rendered_caption(self):
        for address, it in self.items().items():
            caption = ol.ov.render_caption(it, ol._DEFAULT_VIEW, type_labels=ol._type_labels())
            for field in ("private_ip", "ports"):
                value = (it.get("metadata") or {}).get(field)
                if value:
                    self.assertIn(value, caption, f"{address}.{field}")

    def test_the_sample_still_uses_the_network_label_mode(self):
        self.assertNotIn("label_mode", self.model())
        self.assertEqual(quiet(ol.build_diagram, self.model()).layout_info["view"]["label_mode"],
                         "network")

    def test_the_regenerated_sample_still_passes_the_strict_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = quiet(ol.write_diagram, self.model(), Path(tmp) / "ref.drawio")
            self.assertEqual(quiet(check_overlaps.main, ["--strict", str(out)]), 0)


class DemoPageTests(ExamplesPathMixin, unittest.TestCase):
    def test_the_demo_has_six_pages_with_the_expected_names(self):
        import generate_demo_diagram as demo
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "demo.drawio"
            quiet(demo.build, out)
            text = out.read_text(encoding="utf-8")
        # append_pages appends and add_page("Security") runs last, so the order
        # is fixed: 1 Architecture, 2 DRG as a box, 3 Compartments and OKE,
        # 4 Executive overview, 5 Engineering detail, 6 Security.
        names = [n for n in ("Architecture", "DRG as a box", "Compartments and OKE",
                             "Executive overview", "Engineering detail", "Security")]
        self.assertEqual([text.index(f'name="{n}"') for n in names],
                         sorted(text.index(f'name="{n}"') for n in names))
        self.assertEqual(text.count("<diagram "), 6)

    def test_page_4_is_the_executive_view_with_minimal_captions(self):
        import generate_demo_diagram as demo
        d = quiet(ol.build_diagram, demo.DEMO_MODEL, page_name="Executive overview",
                  detail="executive", label_mode="minimal")
        self.assertEqual([cid for cid, e in d._cells.items() if e.get("badge")], [])
        self.assertEqual(d.layout_info["view"]["label_mode"], "minimal")

    def test_page_5_is_the_engineering_view_with_layers_and_routes_hidden(self):
        import generate_demo_diagram as demo
        d = quiet(ol.build_diagram, demo.DEMO_MODEL, page_name="Engineering detail",
                  detail="engineering", label_mode="detailed", layers="auto",
                  hidden_layers=["routes"])
        self.assertIn("routes", d.layout_info["layers"]["enabled"])
        self.assertEqual(d.layout_info["layers"]["hidden"], ["routes"])
        self.assertEqual(d.layout_info["view"]["label_mode"], "detailed")

    def test_the_whole_demo_passes_the_strict_gate(self):
        import generate_demo_diagram as demo
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "demo.drawio"
            quiet(demo.build, out)
            self.assertEqual(quiet(check_overlaps.main, ["--strict", str(out)]), 0)
