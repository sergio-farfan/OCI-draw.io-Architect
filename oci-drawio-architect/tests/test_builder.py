"""Unit tests for scripts/drawio_builder.py (v1.3.0).

Run from the plugin root:
    python3 -m unittest discover -s tests -v

Standard library only (Python 3.9+). Every test is deterministic and writes
only into temporary directories. The single draw.io render test is skipped
when no draw.io desktop binary is installed.

Tests decorated with ``@unittest.expectedFailure`` document known builder
defects (see the docstrings); they must start passing once the builder is
fixed, at which point the decorator has to be removed.
"""
from __future__ import annotations

import base64
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = TESTS_DIR.parent
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import drawio_builder as db  # noqa: E402
from drawio_builder import DrawioBuilder  # noqa: E402

DATA_URI_PREFIX = "data:image/svg+xml,"
SVG_NS = "{http://www.w3.org/2000/svg}"
TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(=.*)?$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def iter_cells(root):
    """Yield (id, mxCell, wrapper-or-None) for every cell under a <root>."""
    for el in root:
        if el.tag == "mxCell":
            yield el.get("id"), el, None
        elif el.tag in ("object", "UserObject"):
            cell = el.find("mxCell")
            if cell is not None:
                yield el.get("id"), cell, el


def cell(root, cid):
    """The mxCell element for an id (unwrapping object/UserObject)."""
    for i, c, _ in iter_cells(root):
        if i == cid:
            return c
    raise KeyError(f"no cell {cid!r}")


def wrapper(root, cid):
    """The <object>/<UserObject> wrapper for an id, or None when plain."""
    for i, _, w in iter_cells(root):
        if i == cid:
            return w
    raise KeyError(f"no cell {cid!r}")


def tokens(style):
    """Parse a draw.io style string into an ordered dict (flags -> None)."""
    out = {}
    for tok in (style or "").split(";"):
        if not tok:
            continue
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
        else:
            out[tok] = None
    return out


def geom(c):
    g = c.find("mxGeometry")
    return {k: float(g.get(k, 0) or 0) for k in ("x", "y", "width", "height")}


def quiet_write(d, path):
    """DrawioBuilder.write() prints a summary line; keep the test output clean."""
    with contextlib.redirect_stdout(io.StringIO()):
        return d.write(path)


def decode_uri(uri):
    assert uri.startswith(DATA_URI_PREFIX)
    return urllib.parse.unquote(uri[len(DATA_URI_PREFIX):])


def only_errors(messages):
    return [m for m in messages if not db.is_warning(m)]


def only_warnings(messages):
    return [m for m in messages if db.is_warning(m)]


class TestWarningSplit(unittest.TestCase):
    def test_is_warning_handles_a_page_prefix_and_brackets_in_the_label(self):
        """A16: only the message's own prefix decides; a "] " inside a label must not."""
        self.assertTrue(db.is_warning("WARNING: caption 'sn [old] app' needs ~4 lines"))
        self.assertTrue(db.is_warning("[page: Page-1] WARNING: caption 'sn [old] app' needs ~4 lines"))
        self.assertFalse(db.is_warning("[page: Page-1] ERROR: 'x [y] z' overlaps 'q'"))
        self.assertFalse(db.is_warning("ERROR: unknown parent 'nope'"))


class TempDirMixin:
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="drawio-builder-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def roundtrip(self, d, name="out.drawio"):
        """Write the diagram and return (path, parsed <mxfile> element)."""
        path = quiet_write(d, self.tmp / name)
        return path, ET.parse(path).getroot()


class CustomIconMixin(TempDirMixin):
    """Registers temporary icons in the module-level ICON_MAP and removes them."""

    def register_svg(self, key, svg_text):
        path = self.tmp / f"{key}.svg"
        path.write_text(svg_text, encoding="utf-8")
        db.add_icons_to_map({key: str(path)})
        self.addCleanup(self._unregister, key)
        return path

    @staticmethod
    def _unregister(key):
        db.ICON_MAP.pop(key, None)
        db._svg_cache.clear()


def build_realistic_layout():
    """Two subnets side by side (2 icon rows each), a DB subnet spanning both.

    Returns (builder, ids) where ids holds the container/icon/edge ids.
    """
    d = DrawioBuilder()
    region = d.add_group("us-ashburn-1", 20, 75, 100, 100, group_type="region")
    vcn = d.add_group("VCN: app (10.0.0.0/16)", 20, 40, 100, 100, parent=region, group_type="vcn")
    sn_web = d.add_group("sn-web (10.0.1.0/24)", 20, 50, 100, 100, parent=vcn, group_type="subnet")
    web, _ = d.place_icons(sn_web, [("Load Balancer", "lb"), ("Web VM 1", "vm"),
                                    ("WAF", "waf"), ("Web VM 2", "vm")], cols=2)
    d.fit_to_children(sn_web)
    x1, y1, w1, h1 = d.bbox(sn_web)
    sn_app = d.add_group("sn-app (10.0.2.0/24)", x1 + w1 + db.GAP, 50, 100, 100,
                         parent=vcn, group_type="subnet")
    app, _ = d.place_icons(sn_app, [("App VM 1", "vm"), ("App VM 2", "vm"),
                                    ("Functions", "functions"), ("API Gateway", "api_gateway")], cols=2)
    d.fit_to_children(sn_app)
    x2, y2, w2, h2 = d.bbox(sn_app)
    span_w = x2 + w2 - x1
    sn_db = d.add_group("sn-db (10.0.3.0/24)", x1, max(y1 + h1, y2 + h2) + db.GAP, span_w, 100,
                        parent=vcn, group_type="subnet")
    dbs, _ = d.place_icons(sn_db, [("ADB", "adb")], cols=1, x0=int((span_w - db.ICON_W) / 2))
    d.fit_to_children(sn_db, min_w=span_w)
    d.fit_to_children(vcn)
    d.fit_to_children(region)
    edges = {
        "web_db": d.add_edge(web[0], dbs[0], "1521"),
        "app_db": d.add_edge(app[0], dbs[0], "1521"),
        "web_row": d.add_edge(web[0], web[1], "80"),
    }
    d.fit_page()
    ids = dict(region=region, vcn=vcn, sn_web=sn_web, sn_app=sn_app, sn_db=sn_db,
               web=web, app=app, dbs=dbs, edges=edges)
    return d, ids


# ---------------------------------------------------------------------------
# 1. Icon loading
# ---------------------------------------------------------------------------
class TestIconLoading(CustomIconMixin, unittest.TestCase):
    def test_icon_dir_resolved(self):
        self.assertIsNotNone(db.OCI_SVG_DIR, "bundled icons/ directory was not found")
        self.assertTrue(Path(db.OCI_SVG_DIR).is_dir())

    def test_every_alias_loads_as_url_encoded_data_uri(self):
        for key in sorted(db.ICON_ALIASES):
            with self.subTest(icon=key):
                uri, _, _ = db._load_svg(key)
                self.assertTrue(uri.startswith("data:image/svg+xml,%3Csvg"), uri[:60])
                self.assertNotIn(";base64,", uri)
                self.assertNotIn(";", uri.split(",", 1)[1], "raw ';' would break style parsing")
                decoded = decode_uri(uri)
                self.assertNotIn('stroke="#000000"', decoded, "stencil placeholder leaked")
                self.assertTrue(decoded.lstrip().startswith("<svg"))

    def test_every_alias_viewbox_is_cropped_to_glyph(self):
        for key in sorted(db.ICON_ALIASES):
            with self.subTest(icon=key):
                uri, w, h = db._load_svg(key)
                self.assertTrue(40 <= w <= 100, f"viewBox width {w}")
                self.assertTrue(40 <= h <= 100, f"viewBox height {h}")
                root = ET.fromstring(decode_uri(uri))
                vb = [float(v) for v in root.get("viewBox").split()]
                self.assertEqual(len(vb), 4)
                self.assertAlmostEqual(vb[2], w)
                self.assertAlmostEqual(vb[3], h)
                self.assertAlmostEqual(float(root.get("width")), w)
                self.assertAlmostEqual(float(root.get("height")), h)

    def test_load_svg_is_cached_per_path(self):
        first = db._load_svg("vm")
        self.assertIs(db._load_svg("vm"), first)
        self.assertIs(db._load_svg("compute"), first, "aliases of one file share the cache entry")

    def test_typo_raises_with_suggestion(self):
        with self.assertRaises(ValueError) as cm:
            db.resolve_icon_path("load_balancr")
        self.assertIn("Did you mean", str(cm.exception))
        self.assertIn("load_balancer", str(cm.exception))

    def test_unknown_key_without_close_match_raises(self):
        with self.assertRaises(ValueError) as cm:
            db.resolve_icon_path("zzqqxx_not_an_icon")
        self.assertIn("Unknown icon_key", str(cm.exception))
        self.assertNotIn("Did you mean", str(cm.exception))

    def test_resolve_accepts_stem_alias_and_absolute_path(self):
        by_alias = db.resolve_icon_path("vm")
        by_stem = db.resolve_icon_path("compute_virtual_machine_vm")
        by_path = db.resolve_icon_path(str(by_alias))
        self.assertEqual(by_alias, by_stem)
        self.assertEqual(by_alias, by_path)

    def test_svg_without_drawable_content_raises(self):
        self.register_svg("tb_empty_icon",
                          '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>')
        with self.assertRaises(ValueError) as cm:
            db._load_svg("tb_empty_icon")
        self.assertIn("no drawable content", str(cm.exception))

    def test_set_icon_dir_missing_raises_and_keeps_state(self):
        before = db.OCI_SVG_DIR
        with self.assertRaises(FileNotFoundError):
            db.set_icon_dir(self.tmp / "does-not-exist")
        self.assertEqual(db.OCI_SVG_DIR, before)

    def test_load_svg_rewrites_only_root_attributes(self):
        inner = '<rect width="100" height="100" fill="red"/>'
        self.register_svg(
            "tb_rect_icon",
            f'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" '
            f'viewBox="0 0 200 200"><g>{inner}</g></svg>')
        uri, w, h = db._load_svg("tb_rect_icon")
        decoded = decode_uri(uri)
        self.assertIn(inner, decoded, "inner element must be untouched")
        self.assertEqual(decoded.count("<rect"), 1)
        root = ET.fromstring(decoded)
        self.assertEqual(root.get("viewBox"), "0 0 200 200")
        self.assertEqual((w, h), (200.0, 200.0))
        self.assertEqual(root.get("width"), "200")
        self.assertEqual(root.get("height"), "200")

    def test_add_icons_to_map_overrides_existing_key(self):
        self.register_svg("tb_override",
                          '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                          '<circle cx="5" cy="5" r="4"/></svg>')
        first = db._load_svg("tb_override")
        other = self.register_svg("tb_override",
                                  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
                                  '<circle cx="10" cy="10" r="8"/></svg>')
        second = db._load_svg("tb_override")
        self.assertEqual(db.resolve_icon_path("tb_override"), other)
        self.assertNotEqual(first, second)
        self.assertEqual(second[1:], (20.0, 20.0))


# ---------------------------------------------------------------------------
# 2. add_icon geometry
# ---------------------------------------------------------------------------
class TestAddIconGeometry(TempDirMixin, unittest.TestCase):
    SLOT_X, SLOT_Y = 100, 200

    def setUp(self):
        super().setUp()
        self.d = DrawioBuilder()

    def _icon(self, label="Web VM", icon="vm", **kw):
        cid = self.d.add_icon(label, icon, self.SLOT_X, self.SLOT_Y, **kw)
        return cid, cell(self.d.root, cid)

    def test_default_slot_image_fits_glyph_box_and_is_centred(self):
        for key in ("vm", "lb", "adb", "customer_data_center", "drg"):
            with self.subTest(icon=key):
                d = DrawioBuilder()
                cid = d.add_icon("x", key, self.SLOT_X, self.SLOT_Y)
                g = geom(cell(d.root, cid))
                self.assertLessEqual(g["width"], db.GLYPH_W)
                self.assertLessEqual(g["height"], db.GLYPH_H)
                self.assertTrue(g["width"] == db.GLYPH_W or g["height"] == db.GLYPH_H,
                                "glyph should be scaled to fill one dimension")
                # horizontally centred in the 75px slot
                self.assertAlmostEqual(g["x"] + g["width"] / 2, self.SLOT_X + db.ICON_W / 2, delta=1)
                # vertically inside the glyph band at the top of the slot
                self.assertGreaterEqual(g["y"], self.SLOT_Y + db.GLYPH_TOP)
                self.assertLessEqual(g["y"] + g["height"], self.SLOT_Y + db.GLYPH_TOP + db.GLYPH_H)

    def test_image_cell_style(self):
        _, c = self._icon()
        tok = tokens(c.get("style"))
        self.assertEqual(tok.get("shape"), "image")
        self.assertEqual(tok.get("aspect"), "fixed")
        self.assertTrue(tok.get("image", "").startswith("data:image/svg+xml,%3Csvg"))
        self.assertEqual(c.get("vertex"), "1")
        self.assertEqual(c.get("value"), "")

    def test_caption_cell_geometry_and_style(self):
        cid, _ = self._icon()
        lid = self.d._cells[cid]["label_id"]
        self.assertIsNotNone(lid)
        lc = cell(self.d.root, lid)
        tok = tokens(lc.get("style"))
        self.assertEqual(tok.get("connectable"), "0")
        self.assertIn("text", tok)
        self.assertEqual(tok.get("whiteSpace"), "wrap")
        self.assertEqual(tok.get("align"), "center")
        g = geom(lc)
        self.assertEqual(g["width"], db.LABEL_W)
        self.assertEqual(g["width"], 105)
        self.assertAlmostEqual(g["x"], self.SLOT_X - 15, delta=1)
        self.assertEqual(g["y"], self.SLOT_Y + db.ICON_H + db.LABEL_GAP)
        self.assertEqual(g["y"], self.SLOT_Y + 97)
        self.assertEqual(g["height"], db.LABEL_H)
        self.assertEqual(lc.get("value"), "Web VM")

    def test_caption_height_grows_with_four_line_label(self):
        short_id, _ = self._icon("one line")
        d2 = DrawioBuilder()
        long_id = d2.add_icon("line one\nline two\nline three\nline four", "vm", 0, 0)
        short_h = geom(cell(self.d.root, self.d._cells[short_id]["label_id"]))["height"]
        long_h = geom(cell(d2.root, d2._cells[long_id]["label_id"]))["height"]
        self.assertEqual(short_h, db.LABEL_H)
        self.assertGreater(long_h, db.LABEL_H)
        self.assertGreaterEqual(long_h, 4 * db.LABEL_LINE_H)

    def test_footprint_covers_icon_and_caption(self):
        cid, _ = self._icon()
        lg = geom(cell(self.d.root, self.d._cells[cid]["label_id"]))
        fx, fy, fw, fh = self.d.footprint(cid)
        self.assertEqual(fx, min(self.SLOT_X, lg["x"]))
        self.assertEqual(fy, self.SLOT_Y)
        self.assertEqual(fw, db.LABEL_W)
        self.assertEqual(fh, db.ICON_FOOTPRINT_H)
        self.assertEqual(fh, 142)
        self.assertGreaterEqual(fx + fw, lg["x"] + lg["width"])
        self.assertGreaterEqual(fy + fh, lg["y"] + lg["height"])

    def test_explicit_width_sizes_cell_and_widens_caption(self):
        cid, c = self._icon("Wide", w=120)
        g = geom(c)
        self.assertEqual((g["x"], g["y"], g["width"], g["height"]), (100.0, 200.0, 120.0, 120.0))
        lg = geom(cell(self.d.root, self.d._cells[cid]["label_id"]))
        self.assertEqual(lg["width"], 150)  # max(LABEL_W, w + 30)
        self.assertEqual(lg["y"], 200 + 120 + db.LABEL_GAP)
        self.assertAlmostEqual(lg["x"] + lg["width"] / 2, 100 + 60, delta=1)
        self.assertEqual(self.d.bbox(cid), (100, 200, 120, 120))

    def test_explicit_height_keeps_aspect(self):
        cid, c = self._icon("Small", icon="adb", h=40)
        g = geom(c)
        self.assertEqual(g["height"], 40)
        _, nw, nh = db._load_svg("adb")
        self.assertEqual(g["width"], round(40 * nw / nh))
        self.assertEqual(g["x"], 100)

    def test_empty_label_produces_no_caption(self):
        before = len(list(iter_cells(self.d.root)))
        cid, _ = self._icon("")
        self.assertIsNone(self.d._cells[cid]["label_id"])
        self.assertEqual(len(list(iter_cells(self.d.root))), before + 1)
        self.assertEqual(self.d.footprint(cid), (100, 200, db.ICON_W, db.ICON_H))

    def test_metadata_and_tooltip_produce_object_wrapper(self):
        cid, c = self._icon(metadata={"ocid": "ocid1.instance.oc1..x", "shape": "VM.Standard.E4"},
                            tooltip="Web tier")
        w = wrapper(self.d.root, cid)
        self.assertIsNotNone(w)
        self.assertEqual(w.tag, "object")
        self.assertEqual(w.get("id"), cid)
        self.assertEqual(w.get("tooltip"), "Web tier")
        self.assertEqual(w.get("ocid"), "ocid1.instance.oc1..x")
        self.assertEqual(w.get("placeholders"), "1")
        self.assertIsNone(c.get("id"), "inner mxCell must not repeat the id")

    def test_link_produces_userobject_wrapper(self):
        cid, _ = self._icon(link="https://cloud.oracle.com/compute")
        w = wrapper(self.d.root, cid)
        self.assertEqual(w.tag, "UserObject")
        self.assertEqual(w.get("id"), cid)
        self.assertEqual(w.get("link"), "https://cloud.oracle.com/compute")

    def test_invalid_metadata_key_raises(self):
        with self.assertRaises(ValueError):
            self._icon(metadata={"label": "reserved"})
        with self.assertRaises(ValueError):
            self._icon(metadata={"bad key": "spaces"})

    def test_key_gives_deterministic_ids(self):
        cid, _ = self._icon(key="web-vm-1")
        self.assertEqual(cid, "web-vm-1")
        self.assertEqual(self.d._cells[cid]["label_id"], "web-vm-1-label")
        cell(self.d.root, "web-vm-1-label")
        slug = self.d.add_icon("x", "vm", 400, 200, key="app vm/2")
        self.assertEqual(slug, "app-vm-2")

    def test_duplicate_key_raises(self):
        self._icon(key="dup")
        with self.assertRaises(ValueError) as cm:
            self.d.add_icon("again", "vm", 400, 200, key="dup")
        self.assertIn("Duplicate", str(cm.exception))
        with self.assertRaises(ValueError):
            self.d.add_group("g", 0, 0, 10, 10, key="dup")


# ---------------------------------------------------------------------------
# 3. Escaping
# ---------------------------------------------------------------------------
class TestEscaping(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.d = DrawioBuilder()

    def test_group_label_is_html_escaped(self):
        gid = self.d.add_group("a < b & c", 0, 0, 200, 100)
        _, mx = self.roundtrip(self.d)
        root = mx.find("diagram/mxGraphModel/root")
        self.assertEqual(cell(root, gid).get("value"), "a &lt; b &amp; c")

    def test_group_label_raw_html_kept(self):
        gid = self.d.add_group("<b>VCN</b> &amp; more", 0, 0, 200, 100, raw_html=True)
        self.assertEqual(cell(self.d.root, gid).get("value"), "<b>VCN</b> &amp; more")

    def test_icon_label_is_html_escaped(self):
        cid = self.d.add_icon("x < y", "vm", 0, 0)
        lc = cell(self.d.root, self.d._cells[cid]["label_id"])
        self.assertEqual(lc.get("value"), "x &lt; y")

    def test_icon_label_raw_html_kept(self):
        cid = self.d.add_icon("<i>vm</i>", "vm", 0, 0, raw_html=True)
        lc = cell(self.d.root, self.d._cells[cid]["label_id"])
        self.assertEqual(lc.get("value"), "<i>vm</i>")

    def test_newlines_become_br(self):
        gid = self.d.add_group("line1\nline2", 0, 0, 200, 100)
        self.assertEqual(cell(self.d.root, gid).get("value"), "line1<br>line2")
        cid = self.d.add_icon("App VM\n10.0.1.5", "vm", 300, 0)
        lc = cell(self.d.root, self.d._cells[cid]["label_id"])
        self.assertEqual(lc.get("value"), "App VM<br>10.0.1.5")

    def test_add_text_keeps_html_by_default(self):
        tid = self.d.add_text("<b>bold</b> &amp; <i>it</i>", 0, 300)
        self.assertEqual(cell(self.d.root, tid).get("value"), "<b>bold</b> &amp; <i>it</i>")

    def test_add_text_raw_html_false_escapes(self):
        tid = self.d.add_text("<b>not bold</b>", 0, 300, raw_html=False)
        self.assertEqual(cell(self.d.root, tid).get("value"), "&lt;b&gt;not bold&lt;/b&gt;")

    def test_edge_label_is_escaped(self):
        a = self.d.add_icon("A", "vm", 0, 0)
        b = self.d.add_icon("B", "vm", 300, 0)
        eid = self.d.add_edge(a, b, "TCP <443> & 80", route="direct")
        self.assertEqual(cell(self.d.root, eid).get("value"), "TCP &lt;443&gt; &amp; 80")


# ---------------------------------------------------------------------------
# 4. Reference validation and basic I/O
# ---------------------------------------------------------------------------
class TestReferences(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.d = DrawioBuilder()

    def test_add_group_unknown_parent_raises(self):
        with self.assertRaises(ValueError) as cm:
            self.d.add_group("x", 0, 0, 100, 100, parent="does-not-exist")
        self.assertIn("unknown parent", str(cm.exception))

    def test_add_group_none_parent_raises(self):
        with self.assertRaises(ValueError):
            self.d.add_group("x", 0, 0, 100, 100, parent=None)

    def test_add_group_unknown_type_and_zero_size_raise(self):
        with self.assertRaises(ValueError):
            self.d.add_group("x", 0, 0, 100, 100, group_type="datacenter")
        with self.assertRaises(ValueError):
            self.d.add_group("x", 0, 0, 0, 100)

    def test_add_edge_unknown_source_raises(self):
        b = self.d.add_icon("B", "vm", 300, 0)
        with self.assertRaises(ValueError) as cm:
            self.d.add_edge("ghost", b)
        self.assertIn("unknown source", str(cm.exception))
        with self.assertRaises(ValueError):
            self.d.add_edge(b, "ghost")

    def test_add_edge_to_edge_raises(self):
        a = self.d.add_icon("A", "vm", 0, 0)
        b = self.d.add_icon("B", "vm", 300, 0)
        eid = self.d.add_edge(a, b, route="direct")
        with self.assertRaises(ValueError):
            self.d.add_edge(a, eid)

    def test_add_edge_int_label_coerced_and_written(self):
        a = self.d.add_icon("A", "vm", 0, 0)
        b = self.d.add_icon("B", "vm", 300, 0)
        eid = self.d.add_edge(a, b, 443)
        path, mx = self.roundtrip(self.d)
        root = mx.find("diagram/mxGraphModel/root")
        self.assertEqual(cell(root, eid).get("value"), "443")

    def test_write_accepts_str_path_and_creates_parent_dirs(self):
        self.d.add_icon("A", "vm", 0, 0)
        target = str(self.tmp / "nested" / "dir" / "out.drawio")
        result = quiet_write(self.d, target)
        self.assertIsInstance(result, Path)
        self.assertTrue(Path(target).is_file())
        mx = ET.parse(target).getroot()
        self.assertEqual(mx.tag, "mxfile")
        self.assertEqual(mx.get("compressed"), "false")
        self.assertIsNotNone(mx.find("diagram/mxGraphModel/root"))

    def test_edge_parent_must_exist_when_given(self):
        a = self.d.add_icon("A", "vm", 0, 0)
        b = self.d.add_icon("B", "vm", 300, 0)
        with self.assertRaises(ValueError):
            self.d.add_edge(a, b, parent="nope")


# ---------------------------------------------------------------------------
# 5. Styles
# ---------------------------------------------------------------------------
class TestStyles(TempDirMixin, unittest.TestCase):
    def _edge_style(self, profile, **kw):
        d = DrawioBuilder(style_profile=profile)
        a = d.add_icon("A", "vm", 0, 0)
        b = d.add_icon("B", "vm", 300, 0)
        eid = d.add_edge(a, b, "x", route="direct", **kw)
        return cell(d.root, eid).get("style")

    def test_default_region_style(self):
        d = DrawioBuilder()
        gid = d.add_group("us-ashburn-1", 0, 0, 400, 300, group_type="region")
        style = cell(d.root, gid).get("style")
        self.assertIn("align=left;spacingLeft=5", style)
        self.assertIn("fontSize=12", style)
        self.assertIn("recursiveResize=0", style)
        tok = tokens(style)
        self.assertEqual(tok["container"], "1")
        self.assertEqual(tok["fillColor"], db.COLORS["region_fill"])
        self.assertEqual(tok["strokeColor"], db.COLORS["region_stroke"])
        self.assertEqual(tok["fontFamily"], db.FONT_STACK)

    def test_services_style(self):
        d = DrawioBuilder()
        gid = d.add_group("OCI Services", 0, 0, 400, 300, group_type="services")
        style = cell(d.root, gid).get("style")
        self.assertIn("strokeColor=#312D2A;", style)
        self.assertIn("strokeWidth=1;", style)
        self.assertEqual(tokens(style)["dashed"], "1")

    def test_vcn_and_subnet_styles_use_sienna(self):
        d = DrawioBuilder()
        v = d.add_group("VCN", 0, 0, 400, 300, group_type="vcn")
        s = d.add_group("Subnet", 20, 40, 200, 100, parent=v, group_type="subnet")
        for cid in (v, s):
            tok = tokens(cell(d.root, cid).get("style"))
            self.assertEqual(tok["strokeColor"], db.COLORS["vcn_stroke"])
            self.assertEqual(tok["fontColor"], db.COLORS["vcn_label"])
        self.assertEqual(tokens(cell(d.root, v).get("style"))["strokeWidth"], "2")

    def test_default_dashed_edge(self):
        style = self._edge_style("default", dashed=True)
        self.assertIn("dashPattern=6 3", style)
        self.assertIn("endArrow=none", style)
        tok = tokens(style)
        self.assertEqual(tok["dashed"], "1")
        self.assertEqual(tok["strokeWidth"], "1.5")
        self.assertEqual(tok["rounded"], "1")

    def test_default_solid_edge(self):
        tok = tokens(self._edge_style("default"))
        self.assertEqual(tok["dashed"], "0")
        self.assertEqual(tok["endArrow"], "open")
        self.assertEqual(tok["strokeColor"], db.COLORS["edge_color"])
        self.assertNotIn("dashPattern", tok)

    def test_official_profile_edges(self):
        dashed = self._edge_style("official", dashed=True)
        self.assertIn("strokeWidth=1;", dashed)
        self.assertIn("rounded=0", dashed)
        self.assertNotIn("dashPattern", dashed)
        self.assertIn("endArrow=open", dashed)
        solid = tokens(self._edge_style("official"))
        self.assertEqual(solid["strokeWidth"], "1")
        self.assertEqual(solid["rounded"], "0")
        self.assertEqual(solid["fontSize"], "10.5")

    def test_edge_kind_data(self):
        tok = tokens(self._edge_style("default", kind="data"))
        self.assertEqual((tok["dashed"], tok["endArrow"], tok["strokeWidth"]), ("0", "open", "1.5"))
        self.assertNotIn("dashPattern", tok)

    def test_edge_kind_control_is_dashed_with_open_arrow_in_every_profile(self):
        for profile in ("default", "official", "v1.0"):
            tok = tokens(self._edge_style(profile, kind="control"))
            self.assertEqual((tok["dashed"], tok["endArrow"]), ("1", "open"), profile)
        self.assertIn("dashPattern=6 3", self._edge_style("default", kind="control"))
        self.assertNotIn("dashPattern", tokens(self._edge_style("official", kind="control")))

    def test_edge_kind_association_is_dotted_without_arrowhead(self):
        tok = tokens(self._edge_style("default", kind="association"))
        self.assertEqual((tok["dashed"], tok["dashPattern"], tok["endArrow"]), ("1", "1 3", "none"))

    def test_edge_kind_attachment_is_thin_solid_without_arrowhead(self):
        tok = tokens(self._edge_style("default", kind="attachment"))
        self.assertEqual((tok["dashed"], tok["endArrow"], tok["strokeWidth"]), ("0", "none", "1"))

    def test_edge_kind_keeps_colour_override_and_rejects_unknown(self):
        tok = tokens(self._edge_style("default", kind="data", color=db.COLORS["edge_accent"]))
        self.assertEqual(tok["strokeColor"], db.COLORS["edge_accent"])
        d = DrawioBuilder()
        a = d.add_icon("A", "vm", 0, 0)
        b = d.add_icon("B", "vm", 300, 0)
        with self.assertRaises(ValueError):
            d.add_edge(a, b, kind="sideways")
        self.assertEqual(set(db.EDGE_KIND_STYLES), {"data", "control", "association", "attachment"})

    def test_plain_dashed_flag_keeps_profile_behaviour(self):
        self.assertIn("endArrow=none", self._edge_style("default", dashed=True))

    def test_v10_profile_spacing_and_vcn_font(self):
        d = DrawioBuilder(style_profile="v1.0")
        r = d.add_group("R", 0, 0, 800, 600, group_type="region")
        v = d.add_group("V", 20, 40, 400, 300, parent=r, group_type="vcn")
        self.assertIn("spacingLeft=3", cell(d.root, r).get("style"))
        vtok = tokens(cell(d.root, v).get("style"))
        self.assertEqual(vtok["fontSize"], "13")
        self.assertEqual(vtok["spacingLeft"], "3")
        # "sample" is an alias of v1.0
        self.assertIs(db.STYLE_PROFILES["sample"], db.STYLE_PROFILES["v1.0"])

    def test_every_emitted_font_family_is_font_stack(self):
        d = DrawioBuilder()
        r = d.add_group("Region", 0, 0, 1400, 1200, group_type="region")
        y = 40
        for gt in db.GROUP_TYPES:
            d.add_group(gt, 20, y, 300, 40, parent=r, group_type=gt)
            y += 60
        icon = d.add_icon("VM", "vm", 400, 40, parent=r)
        icon2 = d.add_icon("DB", "adb", 700, 40, parent=r)
        d.add_text("<b>text</b>", 400, 300, parent=r)
        d.add_title("Title", region_label="Ashburn", region="us-ashburn-1")
        d.add_legend(900, 40, parent=r)
        d.add_table([["a", "b"], ["1", "2"]], 400, 400, parent=r)
        d.add_edge(icon, icon2, "solid")
        d.add_edge(icon, icon2, "dashed", dashed=True, route="direct")
        _, mx = self.roundtrip(d)
        root = mx.find("diagram/mxGraphModel/root")
        seen = 0
        for cid, c, _ in iter_cells(root):
            tok = tokens(c.get("style"))
            if "fontFamily" in tok:
                seen += 1
                self.assertEqual(tok["fontFamily"], db.FONT_STACK, f"cell {cid}")
        self.assertGreater(seen, len(db.GROUP_TYPES) + 5)

    def test_custom_font_family_is_used(self):
        d = DrawioBuilder(font_family="Arial")
        gid = d.add_group("R", 0, 0, 100, 100)
        self.assertEqual(tokens(cell(d.root, gid).get("style"))["fontFamily"], "Arial")

    def test_unknown_profile_raises(self):
        with self.assertRaises(ValueError) as cm:
            DrawioBuilder(style_profile="redwood-2030")
        self.assertIn("style_profile", str(cm.exception))

    def test_hub_alias_equals_onprem_style(self):
        d = DrawioBuilder()
        hub = d.add_group("Hub", 0, 0, 300, 200, group_type="hub")
        onprem = d.add_group("On-prem", 400, 0, 300, 200, group_type="onprem")
        self.assertEqual(cell(d.root, hub).get("style"), cell(d.root, onprem).get("style"))
        self.assertEqual(d._cells[hub]["group_type"], "hub")

    def test_label_position_center_removes_spacing_left(self):
        d = DrawioBuilder()
        gid = d.add_group("R", 0, 0, 300, 200, group_type="region", label_position="center")
        tok = tokens(cell(d.root, gid).get("style"))
        self.assertEqual(tok["align"], "center")
        self.assertNotIn("spacingLeft", tok)
        ad = d.add_group("AD-1", 0, 300, 300, 200, group_type="availability_domain",
                         label_position="left")
        tok = tokens(cell(d.root, ad).get("style"))
        self.assertEqual(tok["align"], "left")
        self.assertEqual(tok["spacingLeft"], "5")
        with self.assertRaises(ValueError):
            d.add_group("bad", 0, 600, 100, 100, label_position="right")

    def test_style_extra_overrides_group_tokens(self):
        d = DrawioBuilder()
        gid = d.add_group("R", 0, 0, 300, 200, style_extra="fillColor=#FFFFFF;fontStyle=0")
        tok = tokens(cell(d.root, gid).get("style"))
        self.assertEqual(tok["fillColor"], "#FFFFFF")
        self.assertEqual(tok["fontStyle"], "0")
        self.assertEqual(tok["container"], "1")


# ---------------------------------------------------------------------------
# 6. Edge modes
# ---------------------------------------------------------------------------
class TestEdgeModes(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.d = DrawioBuilder()
        self.r = self.d.add_group("R", 0, 0, 600, 400)
        self.a = self.d.add_icon("A", "vm", 20, 50, parent=self.r)
        self.b = self.d.add_icon("B", "vm", 400, 200, parent=self.r)

    def _style(self, eid):
        return cell(self.d.root, eid).get("style")

    def test_default_edge_is_routed_at_write(self):
        eid = self.d.add_edge(self.a, self.b, "443")
        before = tokens(self._style(eid))
        self.assertEqual(before.get("edgeStyle"), "orthogonalEdgeStyle")
        self.assertNotIn("exitX", before, "pins are only computed at write()/validate()")
        _, mx = self.roundtrip(self.d)
        root = mx.find("diagram/mxGraphModel/root")
        tok = tokens(cell(root, eid).get("style"))
        self.assertEqual(tok["edgeStyle"], "orthogonalEdgeStyle")
        for k in ("exitX", "exitY", "entryX", "entryY"):
            self.assertIn(k, tok)
            self.assertIn(tok[k], ("0", "0.5", "1"))
        self.assertEqual(self.d._cells[eid]["route"], "auto")

    def test_default_edge_is_routed_at_validate(self):
        eid = self.d.add_edge(self.a, self.b, "443")
        self.assertEqual(len(self.d._pending_routes), 1)
        self.d.validate()
        self.assertEqual(self.d._pending_routes, [])
        self.assertIn("exitX", tokens(self._style(eid)))
        self.assertEqual(self.d.route_edges(), 0, "already routed")

    def test_route_direct_has_no_pins(self):
        eid = self.d.add_edge(self.a, self.b, "443", route="direct")
        quiet_write(self.d, self.tmp / "d.drawio")
        tok = tokens(self._style(eid))
        self.assertEqual(tok["edgeStyle"], "orthogonalEdgeStyle")
        for k in ("exitX", "exitY", "entryX", "entryY"):
            self.assertNotIn(k, tok)
        self.assertIsNone(cell(self.d.root, eid).find("mxGeometry/Array"))

    def test_orthogonal_true_without_pins_is_direct(self):
        eid = self.d.add_edge(self.a, self.b, orthogonal=True)
        self.assertEqual(self.d._cells[eid]["route"], "direct")

    def test_exit_pins_give_legacy_pinned_style(self):
        eid = self.d.add_edge(self.a, self.b, exit_x=1, exit_y=0.5)
        tok = tokens(self._style(eid))
        self.assertNotIn("edgeStyle", tok)
        self.assertEqual(tok["exitX"], "1")
        self.assertEqual(tok["exitY"], "0.5")
        self.assertEqual(tok["entryX"], "0.5")  # defaults to top centre
        self.assertEqual(tok["entryY"], "0")
        self.assertEqual(self.d._cells[eid]["route"], "pinned")
        self.d.validate()
        self.assertNotIn("edgeStyle", tokens(self._style(eid)), "auto router must not touch it")

    def test_orthogonal_true_with_pins_keeps_edge_style(self):
        eid = self.d.add_edge(self.a, self.b, exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5,
                              orthogonal=True)
        tok = tokens(self._style(eid))
        self.assertEqual(tok["edgeStyle"], "orthogonalEdgeStyle")
        self.assertEqual(tok["exitX"], "1")
        self.assertEqual(tok["entryX"], "0")
        self.assertEqual(self.d._cells[eid]["route"], "pinned_router")

    def test_half_pin_pair_raises_in_router_mode(self):
        with self.assertRaises(ValueError):
            self.d.add_edge(self.a, self.b, exit_x=1, orthogonal=True)
        with self.assertRaises(ValueError):
            self.d.add_edge(self.a, self.b, route="bogus")

    def test_waypoints_become_points_array(self):
        eid = self.d.add_edge(self.a, self.b, waypoints=[(200, 87), (200, 260)])
        arr = cell(self.d.root, eid).find("mxGeometry/Array")
        self.assertIsNotNone(arr)
        self.assertEqual(arr.get("as"), "points")
        pts = [(p.get("x"), p.get("y")) for p in arr.findall("mxPoint")]
        self.assertEqual(pts, [("200", "87"), ("200", "260")])
        self.assertEqual(self.d._cells[eid]["route"], "pinned")

    def test_parent_defaults_to_common_ancestor(self):
        d = DrawioBuilder()
        region = d.add_group("R", 0, 0, 900, 600, group_type="region")
        vcn = d.add_group("VCN", 20, 40, 800, 500, parent=region, group_type="vcn")
        s1 = d.add_group("S1", 20, 40, 300, 250, parent=vcn, group_type="subnet")
        s2 = d.add_group("S2", 400, 40, 300, 250, parent=vcn, group_type="subnet")
        i1 = d.add_icon("A", "vm", 20, 50, parent=s1)
        i2 = d.add_icon("B", "vm", 20, 50, parent=s2)
        i3 = d.add_icon("C", "vm", 160, 50, parent=s1)
        eid = d.add_edge(i1, i2, "x")
        self.assertEqual(cell(d.root, eid).get("parent"), vcn)
        self.assertEqual(cell(d.root, d.add_edge(i1, i3)).get("parent"), s1)
        self.assertEqual(cell(d.root, d.add_edge(i1, vcn)).get("parent"), region)
        self.assertEqual(cell(d.root, eid).get("source"), i1)
        self.assertEqual(cell(d.root, eid).get("target"), i2)
        self.assertEqual(cell(d.root, eid).get("edge"), "1")

    def test_explicit_parent_is_honoured(self):
        eid = self.d.add_edge(self.a, self.b, parent="1", route="direct")
        self.assertEqual(cell(self.d.root, eid).get("parent"), "1")

    def test_style_extra_without_trailing_semicolon_keeps_tokens_separate(self):
        pinned = self.d.add_edge(self.a, self.b, style_extra="strokeColor=#FF0000",
                                 exit_x=1, exit_y=0.5)
        direct = self.d.add_edge(self.a, self.b, style_extra="strokeColor=#00FF00",
                                 route="direct")
        auto = self.d.add_edge(self.a, self.b, style_extra="strokeColor=#0000FF")
        self.d.validate()
        for eid, colour, pinned_expected in ((pinned, "#FF0000", True), (direct, "#00FF00", False),
                                             (auto, "#0000FF", True)):
            style = self._style(eid)
            with self.subTest(edge=eid):
                for tok in filter(None, style.split(";")):
                    self.assertRegex(tok, TOKEN_RE, f"corrupted token {tok!r} in {style}")
                parsed = tokens(style)
                self.assertEqual(parsed["strokeColor"], colour)
                self.assertEqual(style.count("strokeColor="), 1)
                self.assertTrue(style.endswith(";"))
                self.assertEqual("exitX" in parsed, pinned_expected)

    def test_label_pos_sets_geometry_x(self):
        eid = self.d.add_edge(self.a, self.b, "lbl", label_pos=0.3, route="direct")
        g = cell(self.d.root, eid).find("mxGeometry")
        self.assertEqual(g.get("relative"), "1")
        self.assertEqual(g.get("x"), "0.3")
        self.assertEqual(g.get("y"), "0")
        clamped = self.d.add_edge(self.a, self.b, "lbl", label_pos=5, route="direct")
        self.assertEqual(cell(self.d.root, clamped).find("mxGeometry").get("x"), "1")

    def test_edge_colour_and_arrow_overrides(self):
        eid = self.d.add_edge(self.a, self.b, color=db.COLORS["edge_purple"], arrow="block",
                              dashed=True, route="direct")
        tok = tokens(self._style(eid))
        self.assertEqual(tok["strokeColor"], "#7B61FF")
        self.assertEqual(tok["endArrow"], "block")
        self.assertEqual(tok["endFill"], "1")


# ---------------------------------------------------------------------------
# 7. Router quality
# ---------------------------------------------------------------------------
class TestRouterQuality(TempDirMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d, cls.ids = build_realistic_layout()
        cls.problems = cls.d.validate()

    def test_realistic_layout_has_no_errors(self):
        self.assertEqual(only_errors(self.problems), [])

    def test_realistic_layout_has_no_crossing_warnings(self):
        crossings = [w for w in only_warnings(self.problems) if "estimated to cross" in w]
        self.assertEqual(crossings, [])

    def test_realistic_layout_is_deterministic(self):
        again, ids2 = build_realistic_layout()
        again.validate()
        for name, eid in self.ids["edges"].items():
            with self.subTest(edge=name):
                a = cell(self.d.root, eid)
                b = cell(again.root, ids2["edges"][name])
                self.assertEqual(a.get("style"), b.get("style"))
                self.assertEqual(self.d._cells[eid]["points"], again._cells[ids2["edges"][name]]["points"])

    def test_realistic_layout_no_error_and_content_fits_page(self):
        self.assertFalse(any("exceeds the page" in w for w in self.problems))
        pw = int(self.d.model.get("pageWidth"))
        ph = int(self.d.model.get("pageHeight"))
        _, _, right, bottom = self.d.content_bbox()
        self.assertGreaterEqual(pw, right)
        self.assertGreaterEqual(ph, bottom)

    def test_edges_to_bottom_subnet_use_vcn_as_parent_and_are_orthogonal(self):
        for name in ("web_db", "app_db"):
            eid = self.ids["edges"][name]
            with self.subTest(edge=name):
                c = cell(self.d.root, eid)
                self.assertEqual(c.get("parent"), self.ids["vcn"])
                tok = tokens(c.get("style"))
                self.assertEqual(tok["edgeStyle"], "orthogonalEdgeStyle")
                self.assertIn("exitX", tok)
                self.assertIn("entryX", tok)
                poly = self.d._cells[eid].get("polyline")
                self.assertTrue(poly and len(poly) >= 2)
                for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
                    self.assertTrue(abs(x0 - x1) < 0.01 or abs(y0 - y1) < 0.01,
                                    f"non-orthogonal segment {(x0, y0)}->{(x1, y1)}")

    def test_aligned_icons_in_one_subnet_connect_straight(self):
        eid = self.ids["edges"]["web_row"]
        c = cell(self.d.root, eid)
        self.assertEqual(c.get("parent"), self.ids["sn_web"])
        self.assertIsNone(c.find("mxGeometry/Array"), "no waypoints expected")
        self.assertEqual(self.d._cells[eid]["points"], [])
        tok = tokens(c.get("style"))
        # a straight horizontal connector: same docking height on both icons
        self.assertEqual(tok["exitY"], tok["entryY"])

    def test_isolated_aligned_pair_docks_right_to_left(self):
        d = DrawioBuilder()
        sn = d.add_group("S", 0, 0, 400, 250, group_type="subnet")
        a = d.add_icon("A", "vm", 20, 50, parent=sn)
        b = d.add_icon("B", "vm", 150, 50, parent=sn)
        eid = d.add_edge(a, b, "80")
        self.assertEqual(d.validate(), [])
        tok = tokens(cell(d.root, eid).get("style"))
        self.assertEqual((tok["exitX"], tok["exitY"]), ("1", "0.5"))
        self.assertEqual((tok["entryX"], tok["entryY"]), ("0", "0.5"))
        self.assertEqual(d._cells[eid]["points"], [])

    def test_routed_waypoints_are_in_parent_coordinates(self):
        eid = self.ids["edges"]["web_db"]
        pts = self.d._cells[eid]["points"]
        self.assertTrue(pts)
        _, _, vw, vh = self.d.bbox(self.ids["vcn"])
        for x, y in pts:
            self.assertTrue(0 <= x <= vw and 0 <= y <= vh, f"waypoint {x, y} outside VCN")

    def test_edge_leaves_sideways_instead_of_through_own_caption(self):
        """Source with a right-hand neighbour and a target below-right: the
        cheapest path by length/bends is straight down through the source's
        caption; the router must pay for the caption and go around."""
        d = DrawioBuilder()
        r = d.add_group("R", 0, 0, 700, 600)
        src = d.add_icon("Load Balancer", "lb", 20, 50, parent=r)
        d.add_icon("Web VM", "vm", 150, 50, parent=r)
        tgt = d.add_icon("ADB", "adb", 400, 400, parent=r)
        eid = d.add_edge(src, tgt, "1521")
        problems = d.validate()
        self.assertEqual([w for w in problems if "estimated to cross" in w], [])
        self.assertNotEqual(tokens(cell(d.root, eid).get("style")).get("exitY"), "1")
        self._assert_no_segment_in_caption_gap(d, eid)

    def _assert_no_segment_in_caption_gap(self, d, eid):
        """No horizontal run of the edge may sit between an endpoint's glyph
        and that endpoint's caption (the builder's stated routing intent)."""
        poly = d._cells[eid]["polyline"]
        for end in (d._cells[eid]["source"], d._cells[eid]["target"]):
            lid = d._cells[end].get("label_id")
            if not lid:
                continue
            cx, cy, cw, ch = d._abs_cell(end)
            lx, ly, lw, lh = d._abs_cell(lid)
            for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
                if abs(y0 - y1) > 0.01:
                    continue  # vertical run
                in_gap = cy + ch + 0.5 < y0 < ly - 0.5
                overlaps_x = min(x0, x1) < lx + lw and max(x0, x1) > lx
                self.assertFalse(in_gap and overlaps_x,
                                 f"segment {(x0, y0)}->{(x1, y1)} runs between the glyph "
                                 f"(bottom {cy + ch}) and caption (top {ly}) of {end}")

    def test_label_with_no_room_on_the_line_is_shifted_off_it(self):
        """Two icons side by side: the label is wider than the gap between them,
        so it must be offset off the line instead of drawn over the glyphs."""
        d = DrawioBuilder()
        sn = d.add_group("S", 0, 0, 400, 300, group_type="subnet")
        a = d.add_icon("A", "lb", 20, 80, parent=sn)
        b = d.add_icon("B", "waf", 150, 80, parent=sn)
        eid = d.add_edge(a, b, "WAF policy", kind="association")
        self.assertEqual(only_errors(d.validate()), [])
        offsets = [pt for pt in cell(d.root, eid).findall("mxGeometry/mxPoint")
                   if pt.get("as") == "offset"]
        self.assertEqual(len(offsets), 1, "expected an absolute label offset")
        self.assertNotEqual(offsets[0].get("y"), "0")
        lbox = db._Box(*d._cells[eid]["label_box"])
        for end in (a, b):
            for cid in (end, d._cells[end]["label_id"]):
                with self.subTest(shape=cid):
                    self.assertFalse(db._Box(*d._abs_cell(cid)).intersects(lbox))

    def test_second_edge_does_not_squeeze_between_own_glyph_and_caption(self):
        """KNOWN DEFECT: when a source's right-hand corridor is already used
        by an earlier edge, the shared-corridor penalty makes the router exit
        the bottom port and run horizontally in the 22px gap between the
        source glyph and its own caption (the endpoint's footprint is excluded
        from the obstacle costs, so nothing forbids that band)."""
        d = DrawioBuilder()
        sn = d.add_group("S", 0, 0, 700, 600, group_type="subnet")
        a = d.add_icon("A", "vm", 20, 50, parent=sn)
        b = d.add_icon("B", "vm", 150, 50, parent=sn)
        c = d.add_icon("C", "adb", 300, 400, parent=sn)
        d.add_edge(a, b, "80")          # routed first: takes A's right corridor
        eid = d.add_edge(a, c, "1521")  # then has to leave A some other way
        self.assertEqual(only_errors(d.validate()), [])
        self._assert_no_segment_in_caption_gap(d, eid)


# ---------------------------------------------------------------------------
# 7a. topology-aware cells: drg group type, ociGroup/ociRole tokens, add_box()
# ---------------------------------------------------------------------------
class TestTopologyCells(TempDirMixin, unittest.TestCase):
    def test_drg_group_type_style(self):
        self.assertIn("drg", db.GROUP_TYPES)
        d = DrawioBuilder()
        gid = d.add_group("DRG: hub-drg", 0, 0, 300, 200, group_type="drg")
        tok = tokens(cell(d.root, gid).get("style"))
        self.assertEqual((tok["rounded"], tok["arcSize"], tok["dashed"], tok["strokeWidth"]), ("1", "10", "1", "1"))
        self.assertEqual((tok["strokeColor"], tok["fillColor"], tok["align"]), (db.COLORS["text_primary"], "none", "left"))
        self.assertEqual(tok["fontStyle"], "1")
        self.assertEqual(tok["ociGroup"], "drg")

    def test_every_group_style_carries_its_ocigroup_token(self):
        d = DrawioBuilder()
        for gt in db.GROUP_TYPES:
            gid = d.add_group(gt, 0, 0, 100, 100, group_type=gt)
            tok = tokens(cell(d.root, gid).get("style"))
            self.assertEqual(tok["ociGroup"], "onprem" if gt == "hub" else gt, gt)
            self.assertEqual(tok["container"], "1")
        self.assertEqual(tokens(db._GROUP_STYLES["vcn"])["ociGroup"], "vcn")

    def test_add_box_is_a_leaf_with_rounded_ivy_border(self):
        d = DrawioBuilder()
        r = d.add_group("R", 0, 0, 400, 300)
        bid = d.add_box("VCN attachment\nspoke", 20, 50, 100, 44, parent=r, key="att-spoke")
        self.assertEqual(bid, "att-spoke")
        c = cell(d.root, bid)
        self.assertEqual(c.get("value"), "VCN attachment<br>spoke")
        tok = tokens(c.get("style"))
        self.assertEqual((tok["rounded"], tok["strokeColor"], tok["fillColor"]), ("1", db.COLORS["ivy"], "#FFFFFF"))
        self.assertEqual(tok["fontFamily"], db.FONT_STACK)
        self.assertNotIn("container", tok)
        self.assertEqual(d._cells[bid]["kind"], "other")
        self.assertEqual(db._kind(db.build_cell_registry(d.root)[bid]), "other")
        self.assertEqual(geom(c), {"x": 20.0, "y": 50.0, "width": 100.0, "height": 44.0})
        # boxes take part in leaf collision checks and can be edge endpoints
        icon = d.add_icon("VM", "vm", 60, 40, parent=r)
        self.assertTrue(any("overlaps" in m for m in d.validate()))
        d2 = DrawioBuilder()
        r2 = d2.add_group("R", 0, 0, 400, 300)
        b2 = d2.add_box("box", 20, 50, 100, 44, parent=r2)
        v2 = d2.add_group("VCN", 200, 40, 150, 200, parent=r2, group_type="vcn")
        d2.add_edge(b2, v2, "", kind="attachment")
        self.assertEqual(d2.validate(), [])

    def test_add_box_metadata_and_style_extra(self):
        d = DrawioBuilder()
        bid = d.add_box("x", 0, 0, 80, 30, metadata={"ocid": "ocid1.drgattachment.oc1..x"},
                        style_extra="fontStyle=2;")
        self.assertEqual(wrapper(d.root, bid).tag, "object")
        self.assertEqual(tokens(cell(d.root, bid).get("style"))["fontStyle"], "2")

    def test_caption_fill_option(self):
        d = DrawioBuilder()
        plain = d.add_icon("Gateway", "internet_gateway", 0, 0)
        filled = d.add_icon("Gateway", "internet_gateway", 200, 0, label_fill=db.COLORS["region_fill"])
        plain_style = tokens(cell(d.root, d._cells[plain]["label_id"]).get("style"))
        filled_style = tokens(cell(d.root, d._cells[filled]["label_id"]).get("style"))
        self.assertEqual(plain_style["fillColor"], "none")
        self.assertEqual(filled_style["fillColor"], db.COLORS["region_fill"])
        ids, _ = d.place_icons("1", [("A", "vm")], cols=1, x0=400, label_fill="#FFFFFF")
        self.assertEqual(tokens(cell(d.root, d._cells[ids[0]]["label_id"]).get("style"))["fillColor"], "#FFFFFF")

    def test_drg_icons_are_tagged(self):
        d = DrawioBuilder()
        for key in ("drg", "dynamic_routing_gateway", "networking_dynamic_routing_gateway_drg"):
            cid = d.add_icon("DRG", key, 0, 0)
            self.assertEqual(tokens(cell(d.root, cid).get("style"))["ociRole"], "drg", key)
        vm = d.add_icon("VM", "vm", 300, 0)
        self.assertNotIn("ociRole", tokens(cell(d.root, vm).get("style")))


# ---------------------------------------------------------------------------
# 8. validate() / check_overlaps() / validate_file()
# ---------------------------------------------------------------------------
class TestValidation(TempDirMixin, unittest.TestCase):
    def _spill_diagram(self):
        d = DrawioBuilder()
        r = d.add_group("R", 0, 0, 800, 600)
        v1 = d.add_group("V1", 20, 40, 300, 300, parent=r, group_type="vcn")
        d.add_group("V2", 340, 40, 300, 300, parent=r, group_type="vcn")
        d.add_group("S", 20, 40, 400, 200, parent=v1, group_type="subnet")
        return d

    def test_overlapping_sibling_containers_report_overlap(self):
        d = DrawioBuilder()
        r = d.add_group("R", 0, 0, 800, 600)
        d.add_group("A", 20, 40, 300, 200, parent=r, group_type="vcn")
        d.add_group("B", 200, 40, 300, 200, parent=r, group_type="vcn")
        msgs = d.check_overlaps()
        self.assertEqual(len(msgs), 1)
        self.assertTrue(msgs[0].startswith("OVERLAP:"))
        self.assertIn("'A'", msgs[0])
        self.assertIn("'B'", msgs[0])
        self.assertIn("siblings", msgs[0])

    def test_subnet_spilling_into_sibling_vcn_is_an_error(self):
        msgs = self._spill_diagram().validate()
        containment = [m for m in msgs if m.startswith("ERROR") and "extends outside" in m]
        overlaps = [m for m in msgs if m.startswith("OVERLAP") and "different parents" in m]
        self.assertEqual(len(containment), 1, msgs)
        self.assertIn("'S'", containment[0])
        self.assertIn("'V1'", containment[0])
        self.assertEqual(len(overlaps), 1, msgs)
        self.assertIn("'V2'", overlaps[0])

    def test_two_overlapping_icons_are_an_error(self):
        d = DrawioBuilder()
        d.add_icon("A", "vm", 20, 50)
        d.add_icon("B", "vm", 40, 50)
        errors = only_errors(d.validate())
        self.assertTrue(errors)
        self.assertTrue(all(e.startswith("ERROR") and "overlaps" in e for e in errors))

    def test_long_caption_is_a_warning_only(self):
        d = DrawioBuilder()
        d.add_icon("word " * 30, "vm", 20, 50, label_h=db.LABEL_H)
        msgs = d.validate()
        self.assertTrue(msgs)
        self.assertTrue(all(m.startswith("WARNING") for m in msgs))
        self.assertTrue(any("caption" in m and "lines" in m for m in msgs))
        self.assertEqual(d.check_overlaps(), [], "warnings are not blocking")

    def test_box_label_taller_than_its_box_is_a_warning(self):
        # a 43-character parser-style display name in the old fixed 100x44 box
        text = db.wrap_hints("drg_attachment_vcn_prod_shared_services_hub")
        lines = db.label_lines(text, 100 - 4, 11)
        self.assertEqual(lines, 5)
        d = DrawioBuilder()
        r = d.add_group("R", 0, 0, 500, 300)
        d.add_box(text, 20, 50, 100, 44, parent=r, key="tight")
        msgs = d.validate()
        self.assertEqual(len(msgs), 1, msgs)
        self.assertTrue(msgs[0].startswith("WARNING: label "), msgs[0])
        self.assertIn(f"needs ~{lines} lines", msgs[0])
        self.assertIn("44px tall", msgs[0])
        self.assertEqual(d.check_overlaps(), [], "warnings are not blocking")
        # a box grown to the estimated line count (what the layout recipe does) is clean
        d2 = DrawioBuilder()
        r2 = d2.add_group("R", 0, 0, 500, 300)
        d2.add_box(text, 20, 50, 100, lines * db.LABEL_LINE_H + 8, parent=r2, key="roomy")
        self.assertEqual(d2.validate(), [])

    def test_clean_diagram_validates_empty(self):
        d = DrawioBuilder()
        r = d.add_group("R", 0, 0, 500, 300)
        a = d.add_icon("A", "vm", 20, 50, parent=r)
        b = d.add_icon("B", "vm", 300, 50, parent=r)
        d.add_edge(a, b, "80")
        self.assertEqual(d.validate(), [])
        self.assertEqual(d.check_overlaps(), [])

    def test_content_exceeding_page_is_a_warning(self):
        d = DrawioBuilder(width=200, height=200)
        d.add_group("R", 0, 0, 500, 300)
        msgs = d.validate()
        self.assertTrue(any("exceeds the page" in m for m in msgs))
        d.fit_page()
        self.assertEqual(d.validate(), [])

    def test_validate_file_matches_validate(self):
        d = self._spill_diagram()
        in_memory = only_errors(d.validate())
        path, _ = self.roundtrip(d)
        errors, warnings, pages, containers = db.validate_file(path)
        self.assertEqual(errors, in_memory)
        self.assertEqual(pages, 1)
        self.assertEqual(containers, 4)
        self.assertEqual(warnings, only_warnings(d.validate()))

    def test_validate_file_decodes_compressed_page(self):
        d = self._spill_diagram()
        expected = only_errors(d.validate())
        path, mx = self.roundtrip(d)
        diagram = mx.find("diagram")
        model = diagram.find("mxGraphModel")
        xml = ET.tostring(model, encoding="unicode")
        comp = zlib.compressobj(9, zlib.DEFLATED, -15)
        data = comp.compress(urllib.parse.quote(xml, safe="").encode("utf-8")) + comp.flush()
        diagram.remove(model)
        diagram.text = base64.b64encode(data).decode("ascii")
        cpath = self.tmp / "compressed.drawio"
        ET.ElementTree(mx).write(cpath, encoding="utf-8", xml_declaration=True)
        self.assertNotIn("mxGraphModel", cpath.read_text(encoding="utf-8"))
        errors, _, pages, containers = db.validate_file(cpath)
        self.assertEqual(errors, expected)
        self.assertEqual((pages, containers), (1, 4))

    def test_validate_file_rejects_bad_compressed_payload(self):
        bad = self.tmp / "bad.drawio"
        bad.write_text('<mxfile><diagram name="p">not-base64-deflate!!</diagram></mxfile>')
        with self.assertRaises(ValueError):
            db.validate_file(bad)

    def test_wrapped_containers_are_seen(self):
        d = DrawioBuilder()
        d.add_group("plain", 0, 0, 200, 100)
        d.add_group("with tooltip", 300, 0, 200, 100, tooltip="tip", metadata={"cidr": "10.0.0.0/16"})
        d.add_group("with link", 600, 0, 200, 100, link="https://example.com")
        path, mx = self.roundtrip(d)
        root = mx.find("diagram/mxGraphModel/root")
        self.assertEqual({w.tag for _, _, w in iter_cells(root) if w is not None}, {"object", "UserObject"})
        _, _, _, containers = db.validate_file(path)
        self.assertEqual(containers, 3)
        # an overlap involving the wrapped containers is detected
        d.add_group("overlaps link", 650, 20, 200, 100, tooltip="x")
        path2, _ = self.roundtrip(d, "wrapped2.drawio")
        errors, _, _, _ = db.validate_file(path2)
        self.assertTrue(any("'with link'" in e and "'overlaps link'" in e for e in errors), errors)

    def test_unknown_parent_in_handwritten_xml_is_an_error(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="test">
  <diagram id="p1" name="Page-1">
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="orphan" value="Orphan" style="rounded=0;container=1;" vertex="1" parent="zzz-missing">
          <mxGeometry x="10" y="10" width="100" height="50" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
"""
        path = self.tmp / "orphan.drawio"
        path.write_text(xml, encoding="utf-8")
        errors, _, pages, _ = db.validate_file(path)
        self.assertEqual(pages, 1)
        self.assertTrue(any("unknown parent" in e and "zzz-missing" in e for e in errors), errors)

    def test_multi_page_messages_are_prefixed(self):
        d = DrawioBuilder(page_name="One")
        d.add_group("A", 0, 0, 200, 100)
        d.add_group("B", 100, 0, 200, 100)
        d.add_page("Two")
        d.add_icon("VM", "vm", 0, 0)
        msgs = d.validate()
        self.assertTrue(any(m.startswith("[page: One] OVERLAP") for m in msgs), msgs)
        blocking = d.check_overlaps()
        self.assertEqual(len(blocking), 1)

    def test_strict_turns_crossings_into_errors(self):
        d = DrawioBuilder()
        r = d.add_group("R", 0, 0, 700, 300)
        a = d.add_icon("A", "vm", 20, 50, parent=r)
        d.add_icon("Blocker", "vm", 250, 50, parent=r)
        b = d.add_icon("B", "vm", 500, 50, parent=r)
        d.add_edge(a, b, "x", exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5)
        lenient = d.validate()
        strict = d.validate(strict=True)
        self.assertTrue(any(m.startswith("WARNING") and "Blocker" in m for m in lenient), lenient)
        self.assertTrue(any(m.startswith("ERROR") and "Blocker" in m for m in strict), strict)


class TestForeignContainment(TempDirMixin, unittest.TestCase):
    def _region_vcn(self, d):
        r = d.add_group("us-ashburn-1", 20, 75, 900, 600, group_type="region", key="region")
        v = d.add_group("VCN: a (10.0.0.0/16)", 300, 40, 500, 400, parent=r, group_type="vcn", key="vcn-a")
        return r, v

    def test_region_parented_drg_inside_vcn_is_an_error(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        d.add_icon("DRG\ndrg-a", "drg", 400, 200, parent=r, key="drg")     # abs (420,275) inside the VCN
        self.assertEqual(only_errors(d.validate()),
                         ["ERROR: DRG 'DRG drg-a' is inside VCN 'VCN: a (10.0.0.0/16)'"])

    def test_vcn_parented_drg_is_also_an_error(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        d.add_icon("DRG\ndrg-a", "drg", 100, 100, parent=v, key="drg")
        self.assertEqual(only_errors(d.validate()),
                         ["ERROR: DRG 'DRG drg-a' is inside VCN 'VCN: a (10.0.0.0/16)'"])

    def test_drg_caption_inside_a_vcn_is_flagged_when_the_glyph_only_straddles(self):
        """A02: the glyph straddles the VCN top border (no DRG error) but the caption is inside it."""
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        # slot y such that the glyph centre sits on the VCN top border (GLYPH_TOP + GLYPH_H / 2 = 40)
        d.add_icon("DRG\nhub", "drg", 400, 0, parent=r, key="drg")
        errors = only_errors(d.validate())
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("'DRG hub'", errors[0])
        self.assertIn("lies inside 'VCN: a (10.0.0.0/16)'", errors[0])
        self.assertNotIn("is inside VCN", errors[0])

    def test_nested_foreign_containers_report_only_the_innermost(self):
        """A13: a leaf inside a foreign subnet inside a foreign VCN is one error, not two."""
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        d.add_group("sn-app", 20, 50, 300, 200, parent=v, group_type="subnet", key="sn-app")
        d.add_box("VCN attachment", 340, 100, 100, 44, parent=r, key="att")
        errors = only_errors(d.validate())
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("lies inside 'sn-app'", errors[0])

    def test_region_parented_vm_inside_vcn_is_a_foreign_containment_error(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        d.add_icon("App VM", "vm", 400, 200, parent=r, key="vm")
        errors = only_errors(d.validate())
        self.assertEqual(len(errors), 2, errors)          # the icon and its caption
        for e in errors:
            self.assertIn("lies inside 'VCN: a (10.0.0.0/16)'", e)
            self.assertIn("but is not one of its children", e)

    def test_icon_inside_a_foreign_subnet_is_an_error(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        d.add_group("sn-app", 20, 50, 300, 200, parent=v, group_type="subnet", key="sn-app")
        d.add_icon("Stray", "vm", 40, 60, parent=v, key="stray")            # in the VCN but inside sn-app's box
        self.assertTrue(any("lies inside 'sn-app'" in e for e in only_errors(d.validate())))

    def test_border_centred_gateway_is_clean_whichever_parent(self):
        for parent_is_vcn in (False, True):
            d = DrawioBuilder()
            r, v = self._region_vcn(d)
            if parent_is_vcn:
                d.add_icon("Internet\nGateway", "internet_gateway", 20, 400 - 40, parent=v, key="igw")
            else:
                d.add_icon("Internet\nGateway", "internet_gateway", 320, 40 + 400 - 40, parent=r, key="igw")
            self.assertEqual(only_errors(d.validate()), [], f"parent_is_vcn={parent_is_vcn}")

    def test_side_border_gateway_is_clean(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        d.add_icon("Service\nGateway", "service_gateway", 300 + 500 - 38, 40 + 50, parent=r, key="sgw",
                   label_fill=db.COLORS["region_fill"])
        self.assertEqual(only_errors(d.validate()), [])

    def test_caption_spilling_out_of_a_short_parent_is_still_an_error(self):
        """The glyph fits, the caption does not: the too-short-container defect."""
        d = DrawioBuilder()
        sn = d.add_group("sn-app", 0, 0, 200, 130, group_type="subnet", key="sn")
        d.add_icon("App VM", "vm", 20, 50, parent=sn, key="vm")
        errors = only_errors(d.validate())
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("extends outside its parent 'sn-app'", errors[0])
        d.fit_to_children(sn)
        self.assertEqual(only_errors(d.validate()), [])

    def test_caption_of_a_straddling_icon_stays_exempt(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        d.add_icon("NAT\nGateway", "nat_gateway", 60, 400 - 40, parent=v, key="nat")
        self.assertEqual(only_errors(d.validate()), [])

    def test_mostly_inside_icon_is_still_flagged(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        d.add_icon("Almost in", "vm", 300 - 10, 200, parent=r, key="almost")  # the glyph sticks out 8 px < FOREIGN_TOL
        self.assertTrue(any("lies inside" in e for e in only_errors(d.validate())))

    def test_foreign_containment_tolerance_boundary(self):
        """A12: FOREIGN_TOL (18.75 px) is the exact cut-off, measured on a box with no glyph inset."""
        for overhang, flagged in ((db.FOREIGN_TOL - 1, True), (db.FOREIGN_TOL + 1, False)):
            with self.subTest(overhang=overhang):
                d = DrawioBuilder()
                r, v = self._region_vcn(d)                       # VCN starts at absolute x = 320
                d.add_box("Marker", 300 - overhang, 200, 100, 44, parent=r, key="m")
                errs = [e for e in only_errors(d.validate()) if "lies inside" in e]
                self.assertEqual(bool(errs), flagged, errs)

    def test_box_inside_foreign_vcn_is_an_error_and_outside_is_clean(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        d.add_box("VCN attachment", 350, 200, 100, 44, parent=r, key="bad")
        self.assertTrue(any("'VCN attachment'" in e and "lies inside" in e for e in only_errors(d.validate())))
        d2 = DrawioBuilder()
        r2, v2 = self._region_vcn(d2)
        d2.add_box("VCN attachment", 150, 200, 100, 44, parent=r2, key="good")
        self.assertEqual(only_errors(d2.validate()), [])

    def test_own_children_are_never_foreign(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        s = d.add_group("sn-app", 20, 50, 300, 200, parent=v, group_type="subnet")
        d.add_icon("App VM", "vm", 20, 50, parent=s)
        self.assertEqual(d.validate(), [])

    def test_handwritten_file_uses_style_heuristics(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="test">
  <diagram id="p1" name="Page-1">
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="r" value="us-ashburn-1" style="rounded=1;strokeColor=#9E9892;fillColor=#F5F4F2;container=1;" vertex="1" parent="1">
          <mxGeometry x="20" y="75" width="900" height="600" as="geometry"/>
        </mxCell>
        <mxCell id="v" value="VCN: a" style="rounded=0;strokeWidth=2;dashed=1;strokeColor=#AE562C;fillColor=none;container=1;" vertex="1" parent="r">
          <mxGeometry x="300" y="40" width="500" height="400" as="geometry"/>
        </mxCell>
        <mxCell id="drg" value="" style="shape=image;image=data:image/svg+xml,x;" vertex="1" parent="r">
          <mxGeometry x="400" y="200" width="70" height="70" as="geometry"/>
        </mxCell>
        <mxCell id="drg-l" value="DRG hub" style="text;html=1;align=center;" vertex="1" parent="r">
          <mxGeometry x="382" y="275" width="105" height="45" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
"""
        path = self.tmp / "handwritten.drawio"
        path.write_text(xml, encoding="utf-8")
        errors, _, _, _ = db.validate_file(path)
        self.assertEqual(errors, ["ERROR: DRG 'DRG hub' is inside VCN 'VCN: a'"])


class TestBadges(TempDirMixin, unittest.TestCase):
    """Route table / security list badges on a subnet corner, NSG badges over an icon (v1.3.0 addendum)."""

    def _subnet(self, d):
        r = d.add_group("us-ashburn-1", 20, 75, 900, 600, group_type="region", key="region")
        v = d.add_group("VCN: a (10.0.0.0/16)", 20, 40, 500, 400, parent=r, group_type="vcn", key="vcn-a")
        s = d.add_group("sn-app (10.0.1.0/24)", db.PAD, db.ROW1_Y, 300, 200, parent=v, group_type="subnet",
                        key="subnet:sn-app")
        ids, _ = d.place_icons(s, [{"label": "App VM\n10.0.1.5", "icon": "vm", "key": "app"},
                                   {"label": "Vault", "icon": "vault", "key": "vault"}], cols=2)
        w, h = d.fit_to_children(s)
        return r, v, s, ids, w, h

    def test_corner_badges_centre_on_the_subnet_corner_and_validate_clean(self):
        d = DrawioBuilder()
        r, v, s, ids, w, h = self._subnet(d)
        rt = d.add_badge("route_table", w, 0, parent=s, host=s, key=f"{s}-rt", tooltip="Route table: rt-app")
        sl = d.add_badge("security_list", w - db.BADGE_SIZE - db.BADGE_GAP, 0, parent=s, host=s, key=f"{s}-sl")
        self.assertEqual((rt, sl), ("subnet-sn-app-rt", "subnet-sn-app-sl"))
        sx, sy, sw, sh = d.abs_bbox(s)
        bx, by, bw, bh = d.abs_bbox(rt)
        self.assertEqual((bw, bh), (db.BADGE_SIZE, db.BADGE_SIZE))
        self.assertAlmostEqual(bx + bw / 2, sx + sw, delta=1.0)          # centred on the top-right corner
        self.assertAlmostEqual(by + bh / 2, sy, delta=1.0)
        lx, ly, lw, lh = d.abs_bbox(sl)
        self.assertAlmostEqual(lx + lw / 2, sx + sw - db.BADGE_SIZE - db.BADGE_GAP, delta=1.0)
        self.assertAlmostEqual(ly + lh / 2, sy, delta=1.0)
        for cid in (v, r):
            d.fit_to_children(cid)
        d.fit_page()
        self.assertEqual(only_errors(d.validate()), [])                  # straddling the corner passes rule 3
        path, _ = self.roundtrip(d)
        errors, _, _, _ = db.validate_file(path)
        self.assertEqual(errors, [])

    def test_badge_style_tokens_geometry_and_no_caption(self):
        d = DrawioBuilder()
        r, v, s, ids, w, h = self._subnet(d)
        rt = d.add_badge("route_table", w, 0, parent=s, host=s, key="rt",
                         metadata={"route_table": "rt-app"}, tooltip="Route table: rt-app")
        c = cell(d.root, rt)
        tok = tokens(c.get("style"))
        self.assertEqual((tok["shape"], tok["ociRole"], tok["ociHost"], tok["imageAspect"]), ("image", "badge", s, "1"))
        self.assertTrue(tok["image"].startswith(DATA_URI_PREFIX))
        self.assertEqual(geom(c), {"x": w - 11.0, "y": -11.0, "width": 22.0, "height": 22.0})
        e = d._cells[rt]
        self.assertEqual((e["kind"], e["badge"], e["host"], e["label_id"]), ("icon", True, s, None))
        self.assertEqual((e["slot_x"], e["slot_y"], e["slot_w"], e["slot_h"]), (w - 11.0, -11.0, 22.0, 22.0))
        obj = wrapper(d.root, rt)
        self.assertEqual((obj.tag, obj.get("tooltip"), obj.get("route_table")), ("object", "Route table: rt-app", "rt-app"))
        self.assertEqual(len([t for t in d._cells.values() if t["kind"] == "text"]), 2)   # only the two icon captions

    def test_nsg_badge_sits_inside_the_host_slot_and_may_cover_the_glyph(self):
        d = DrawioBuilder()
        r, v, s, ids, w, h = self._subnet(d)
        app = ids[0]
        sx, sy, sw, sh = d.bbox(app)
        nsg = d.add_badge("nsg", sx + db.ICON_W - db.BADGE_SIZE / 2, sy + db.BADGE_SIZE / 2, parent=s, host=app,
                          key="app-nsg", tooltip="NSG: nsg-app")
        hx, hy, hw, hh = d.abs_bbox(app)
        nx, ny, nw, nh = d.abs_bbox(nsg)
        self.assertEqual((nx + nw, ny, nw, nh), (hx + hw, hy, 22.0, 22.0))           # top-right of the 75x95 slot
        gx, gy, gw_, gh = d._abs_cell(app)
        self.assertTrue(nx < gx + gw_ and ny + nh > gy)                              # overlaps the 70x70 glyph cell
        self.assertEqual(only_errors(d.validate()), [])                              # ... which is allowed for the host
        path, _ = self.roundtrip(d)
        self.assertEqual(db.validate_file(path)[0], [])

    def test_badge_of_an_endpoint_is_not_a_crossing_but_another_badge_is(self):
        """A15: rule 6 treats a badge over an endpoint as part of that endpoint."""
        d = DrawioBuilder()
        r = d.add_group("R", 0, 0, 700, 600)
        a = d.add_icon("A", "vm", 20, 50, parent=r, key="a")
        b = d.add_icon("B", "vm", 500, 50, parent=r, key="b")
        c = d.add_icon("C", "vm", 250, 300, parent=r, key="c")      # off the line; only its badge is on it
        d.add_badge("nsg", 150, 90, parent=r, host=a, key="a-nsg")
        d.add_edge(a, b, "x", exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5)
        self.assertEqual([m for m in d.validate() if "estimated to cross" in m], [])
        d.add_badge("nsg", 350, 90, parent=r, host=c, key="c-nsg")
        self.assertTrue(any("estimated to cross" in m for m in d.validate()))

    def test_badge_over_a_foreign_icon_is_still_a_collision(self):
        d = DrawioBuilder()
        g = d.add_group("R", 0, 0, 400, 300, key="r")
        d.add_icon("A", "vm", 20, 50, parent=g, key="a")
        d.add_icon("B", "vm", 150, 50, parent=g, key="b")
        d.add_badge("nsg", 20 + db.ICON_W - 11, 50 + 11, parent=g, host="b", key="stray")   # over A, hosted by B
        errors = only_errors(d.validate())
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("'A'", errors[0])
        self.assertIn("overlaps", errors[0])

    def test_two_corner_badges_do_not_collide_and_fit_ignores_them(self):
        d = DrawioBuilder()
        r, v, s, ids, w, h = self._subnet(d)
        d.add_badge("route_table", w, 0, parent=s, host=s, key="rt")
        d.add_badge("security_list", w - db.BADGE_SIZE - db.BADGE_GAP, 0, parent=s, host=s, key="sl")
        self.assertEqual(d.fit_to_children(s), (w, h))                    # badges never grow their host
        sib = d.add_group("sn-db (10.0.2.0/24)", db.PAD + w + db.GAP, db.ROW1_Y, 200, 150, parent=v,
                          group_type="subnet", key="sn-db")
        d.place_icons(sib, [("ADB", "adb")], cols=1)
        d.fit_to_children(sib)
        self.assertEqual(only_errors(d.validate()), [])                   # the 20 px gutter clears the 11 px overhang

    def test_routing_obstacles_keep_corner_badges_and_drop_icon_badges(self):
        d = DrawioBuilder()
        r, v, s, ids, w, h = self._subnet(d)
        rt = d.add_badge("route_table", w, 0, parent=s, host=s, key="rt")
        nsg = d.add_badge("nsg", db.PAD + db.ICON_W - 11, db.ROW1_Y + 11, parent=s, host=ids[0], key="nsg")
        _, obstacles = d._routing_shapes(d._page_idx)
        self.assertIn(rt, obstacles)
        self.assertNotIn(nsg, obstacles)

    def test_badged_container_title_running_under_the_badges_warns(self):
        """A27: a container title must fit in the width its corner badges leave."""
        d = DrawioBuilder()
        s = d.add_group("sn-shared-services-management (10.0.240.0/24)", 0, 0, 180, 200,
                        group_type="subnet", key="sn")
        d.add_badge("route_table", 180, 0, parent=s, host=s, key="sn-rt")
        msgs = [m for m in d.validate() if "its badges leave" in m]
        self.assertEqual(len(msgs), 1, msgs)
        self.assertIn("sn-shared-services-management", msgs[0])

    def test_add_badge_rejects_bad_input_and_constants_are_exported(self):
        d = DrawioBuilder()
        with self.assertRaises(ValueError):
            d.add_badge("route_table", 0, 0, parent="nope")
        with self.assertRaises(ValueError):
            d.add_badge("route_table", 0, 0, size=0)
        with self.assertRaises(ValueError):
            d.add_badge("no_such_icon_key", 0, 0)
        self.assertEqual((db.BADGE_SIZE, db.BADGE_GAP), (22, 4))
        for name in ("BADGE_SIZE", "BADGE_GAP"):
            self.assertIn(name, db.__all__)
        self.assertIsNone(db._badge_host({"style": "shape=image;image=x;"}))
        self.assertEqual(db._badge_host({"style": "shape=image;ociRole=badge;ociHost=app;image=x;"}), "app")
        self.assertEqual(db._badge_host({"style": "shape=image;ociRole=badge;ociHost=;image=x;"}), "")


# ---------------------------------------------------------------------------
# 9. Helpers
# ---------------------------------------------------------------------------
class TestHelpers(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.d = DrawioBuilder()

    def test_place_icons_returns_ids_and_bbox_covering_captions(self):
        sn = self.d.add_group("S", 0, 0, 100, 100, group_type="subnet")
        ids, (x0, y0, right, bottom) = self.d.place_icons(
            sn, [("Load Balancer", "lb"), ("App VM\n10.0.1.5", "vm"), ("ADB", "adb")], cols=2)
        self.assertEqual(len(ids), 3)
        self.assertTrue(all(self.d._cells[i]["kind"] == "icon" for i in ids))
        self.assertEqual((x0, y0), (db.PAD, db.ROW1_Y))
        exp_right = max(fx + fw for fx, _, fw, _ in map(self.d.footprint, ids))
        exp_bottom = max(fy + fh for _, fy, _, fh in map(self.d.footprint, ids))
        self.assertEqual(right, exp_right)
        self.assertEqual(bottom, exp_bottom)
        for i in ids:
            lid = self.d._cells[i]["label_id"]
            lg = geom(cell(self.d.root, lid))
            self.assertLessEqual(lg["x"] + lg["width"], right)
            self.assertLessEqual(lg["y"] + lg["height"], bottom)
        # grid: second column at x0 + COL_W, second row at y0 + ROW_H
        self.assertEqual(self.d.bbox(ids[1])[0], db.PAD + db.COL_W)
        self.assertEqual(self.d.bbox(ids[2])[1], db.ROW1_Y + db.ROW_H)

    def test_place_icons_accepts_dict_items_and_rejects_bad_cols(self):
        sn = self.d.add_group("S", 0, 0, 100, 100, group_type="subnet")
        ids, _ = self.d.place_icons(sn, [{"label": "VM", "icon": "vm", "key": "vm-a",
                                          "tooltip": "t"}], cols=1)
        self.assertEqual(ids, ["vm-a"])
        self.assertEqual(wrapper(self.d.root, "vm-a").get("tooltip"), "t")
        with self.assertRaises(ValueError):
            self.d.place_icons(sn, [("x", "vm")], cols=0)

    def test_fit_to_children_fixes_containment(self):
        sn = self.d.add_group("S", 0, 0, 100, 60, group_type="subnet")
        ids, (_, _, right, bottom) = self.d.place_icons(sn, [("A", "vm"), ("B", "adb")], cols=2)
        self.assertTrue(any("extends outside" in m for m in self.d.validate()))
        w, h = self.d.fit_to_children(sn)
        self.assertEqual((w, h), (right + db.PAD, bottom + db.PAD))
        g = geom(cell(self.d.root, sn))
        self.assertEqual((g["width"], g["height"]), (w, h))
        self.assertEqual(self.d.validate(), [])
        with self.assertRaises(ValueError):
            self.d.fit_to_children(ids[0])

    def test_fit_to_children_respects_minimums(self):
        sn = self.d.add_group("S", 0, 0, 100, 60, group_type="subnet")
        self.d.add_icon("A", "vm", 20, 50, parent=sn)
        w, h = self.d.fit_to_children(sn, min_w=800, min_h=500)
        self.assertEqual((w, h), (800, 500))

    def test_fit_page_covers_content(self):
        d = DrawioBuilder(width=100, height=100)
        d.add_group("R", 20, 20, 500, 400)
        w, h = d.fit_page()
        _, _, right, bottom = d.content_bbox()
        self.assertGreaterEqual(w, right)
        self.assertGreaterEqual(h, bottom)
        self.assertEqual(d.model.get("pageWidth"), str(w))
        self.assertEqual(d.model.get("pageHeight"), str(h))
        self.assertEqual(w % 10, 0)
        self.assertEqual((w, h), (540, 440))

    def test_add_title_renders_bold_and_italic(self):
        res = self.d.add_title("app-prod <x>", region_label="Ashburn", region="us-ashburn-1",
                               compartment="prod", tenancy="acme")
        self.assertEqual(res["title"], "title")
        self.assertIsNone(res["logo"])
        value = cell(self.d.root, "title").get("value")
        self.assertIn("<b>acme - app-prod &lt;x&gt;</b>", value)
        self.assertIn("<i>Ashburn (us-ashburn-1) - Compartment: prod</i>", value)
        tok = tokens(cell(self.d.root, "title").get("style"))
        self.assertEqual(tok["fontSize"], "18")
        self.assertEqual(tok["fontFamily"], db.TITLE_FONT_STACK)

    def test_add_title_missing_logo_warns_instead_of_raising(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            res = self.d.add_title("Subject", logo=str(self.tmp / "missing-logo.png"))
        self.assertIsNone(res["logo"])
        self.assertIn("WARNING", err.getvalue())
        self.assertIn("logo skipped", err.getvalue())
        cell(self.d.root, res["title"])

    def test_add_title_with_svg_logo_embeds_image(self):
        logo = self.tmp / "logo.svg"
        logo.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
                        '<rect width="10" height="10"/></svg>', encoding="utf-8")
        res = self.d.add_title("Subject", logo=str(logo), page_w=1000)
        self.assertIsNotNone(res["logo"])
        c = cell(self.d.root, res["logo"])
        tok = tokens(c.get("style"))
        self.assertEqual(tok["shape"], "image")
        self.assertTrue(tok["image"].startswith("data:image/svg+xml,"))
        g = geom(c)
        self.assertEqual(g["x"], 1000 - 148 - 22)

    def test_add_legend_creates_group_with_swatches_and_texts(self):
        gid = self.d.add_legend(20, 20)
        gcell = cell(self.d.root, gid)
        self.assertEqual(tokens(gcell.get("style"))["container"], "1")
        self.assertEqual(gcell.get("value"), "Legend")
        kids = [(cid, c) for cid, c, _ in iter_cells(self.d.root) if c.get("parent") == gid]
        edges = [c for _, c in kids if c.get("edge") == "1"]
        texts = [c for _, c in kids if "text" in tokens(c.get("style")) and c.get("vertex") == "1"]
        swatches = [c for _, c in kids if c.get("vertex") == "1" and "text" not in tokens(c.get("style"))]
        self.assertEqual(len(edges), 4)
        self.assertEqual(len(swatches), 4)
        self.assertEqual(len(texts), 8)
        for sw in swatches:
            self.assertNotIn("container", tokens(sw.get("style")))
        for e in edges:
            g = e.find("mxGeometry")
            self.assertIsNotNone(g.find("mxPoint[@as='sourcePoint']"))
            self.assertIsNotNone(g.find("mxPoint[@as='targetPoint']"))
        self.assertEqual(self.d.validate(), [])

    def test_add_legend_custom_entries(self):
        gid = self.d.add_legend(20, 20, entries=[("edge", "purple", "FastConnect"),
                                                 ("group", "vcn", "VCN")], title="Key")
        kids = [c for _, c, _ in iter_cells(self.d.root) if c.get("parent") == gid]
        self.assertEqual(len(kids), 4)  # 1 edge + 1 swatch + 2 texts
        purple = [c for c in kids if c.get("edge") == "1"][0]
        self.assertEqual(tokens(purple.get("style"))["strokeColor"], db.COLORS["edge_purple"])

    def test_add_legend_default_rows_cover_the_four_connector_kinds(self):
        gid = self.d.add_legend(20, 20)
        kids = [c for _, c, _ in iter_cells(self.d.root) if c.get("parent") == gid]
        edge_styles = [tokens(c.get("style")) for c in kids if c.get("edge") == "1"]
        self.assertEqual([(t["dashed"], t["endArrow"]) for t in edge_styles],
                         [("0", "open"), ("1", "open"), ("1", "none"), ("0", "none")])
        self.assertEqual(edge_styles[2]["dashPattern"], "1 3")
        self.assertEqual(edge_styles[3]["strokeWidth"], "1")
        texts = [c.get("value") for c in kids if c.get("vertex") == "1" and "text" in tokens(c.get("style"))]
        self.assertEqual(texts, ["Data flow (protocol / port)", "Management / administrative traffic",
                                 "Association / dependency", "Attachment (structural)",
                                 "Region / on-premises", "VCN", "Subnet", "Oracle Services Network"])

    def test_add_legend_accepts_kind_names_and_dotted_thin(self):
        gid = self.d.add_legend(20, 20, entries=[("edge", "attachment", "A"), ("edge", "dotted", "B"),
                                                 ("edge", "thin", "C"), ("edge", "control", "D")])
        edges = [tokens(c.get("style")) for _, c, _ in iter_cells(self.d.root)
                 if c.get("parent") == gid and c.get("edge") == "1"]
        self.assertEqual([e["endArrow"] for e in edges], ["none", "none", "none", "open"])
        self.assertEqual(edges[1]["dashPattern"], "1 3")
        with self.assertRaises(ValueError):
            self.d.add_legend(20, 300, entries=[("edge", "zigzag", "x")])

    def test_default_legend_fits_its_box_and_the_page_after_fit_page(self):
        """The default legend grew from 6 to 8 rows (4 connector kinds + 4
        swatches): the extra height has to stay inside the legend box and be
        absorbed by fit_page(), so the mandatory check_overlaps gate
        (db.validate_file) still reports no errors for a diagram that places
        the legend the way the layout recipe does - content first, then
        add_legend(), then fit_page().
        """
        r = self.d.add_group("Region", 0, 0, 420, 320, group_type="region")
        self.d.add_icon("VM", "vm", db.PAD, db.ROW1_Y, parent=r)
        _, _, right, _ = self.d.content_bbox()
        gid = self.d.add_legend(right + db.GAP, 0)
        box = geom(cell(self.d.root, gid))
        self.assertEqual(box["height"], 30 + 22 * 8 + 8)
        rows = [geom(c) for _, c, _ in iter_cells(self.d.root)
                if c.get("parent") == gid and c.get("vertex") == "1"]
        self.assertEqual(len(rows), 12)  # 4 group swatches + 8 row texts
        self.assertLessEqual(max(g["y"] + g["height"] for g in rows), box["height"])
        self.assertLessEqual(max(g["x"] + g["width"] for g in rows), box["width"])
        w, h = self.d.fit_page()
        self.assertGreaterEqual(w, box["x"] + box["width"])
        self.assertGreaterEqual(h, box["y"] + box["height"])
        self.assertEqual(self.d.validate(strict=True), [])
        path = quiet_write(self.d, self.tmp / "legend.drawio")
        errors, warnings, _pages, _containers = db.validate_file(path)
        self.assertEqual((errors, warnings), ([], []))

    def test_add_table_html_rows(self):
        tid = self.d.add_table([["Source", "Dest", "Port"], ["0.0.0.0/0", "10.0.1.0/24", "443"],
                                ["10.0.0.0/16", "10.0.2.0/24", "1521"]], 20, 20,
                               title="Rules <v1>")
        value = cell(self.d.root, tid).get("value")
        self.assertIn("<table", value)
        self.assertEqual(value.count("<tr>"), 3)
        self.assertEqual(value.count("<th "), 3)
        self.assertEqual(value.count("<td "), 6)
        self.assertIn("Rules &lt;v1&gt;", value)
        g = geom(cell(self.d.root, tid))
        self.assertEqual(g["width"], 3 * 110 + 6)
        self.assertEqual(g["height"], 18 * 3 + 18 + 6)
        with self.assertRaises(ValueError):
            self.d.add_table([], 0, 0)

    def test_add_table_pads_ragged_rows_and_widths(self):
        tid = self.d.add_table([["a", "b", "c"], ["1"]], 20, 20, header=False, col_widths=[50])
        value = cell(self.d.root, tid).get("value")
        self.assertEqual(value.count("<td "), 6)
        self.assertEqual(value.count("<th "), 0)
        self.assertEqual(geom(cell(self.d.root, tid))["width"], 50 + 110 + 110 + 6)

    def test_add_page_and_cross_page_edge_raises(self):
        a = self.d.add_icon("A", "vm", 20, 20)
        idx = self.d.add_page("Second", 800, 600)
        self.assertEqual(idx, 1)
        diagrams = self.d.mxfile.findall("diagram")
        self.assertEqual(len(diagrams), 2)
        self.assertEqual(diagrams[1].get("name"), "Second")
        self.assertEqual(diagrams[1].find("mxGraphModel").get("pageWidth"), "800")
        b = self.d.add_icon("B", "vm", 20, 20)
        with self.assertRaises(ValueError) as cm:
            self.d.add_edge(a, b)
        self.assertIn("another page", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            self.d.add_group("x", 0, 0, 10, 10, parent=a)  # parent lives on page 0
        self.assertIn("another page", str(cm.exception))
        self.assertEqual(self.d.use_page(0), 0)
        self.assertEqual(self.d.use_page("Second"), 1)
        with self.assertRaises(KeyError):
            self.d.use_page("Nope")
        with self.assertRaises(IndexError):
            self.d.use_page(7)
        _, mx = self.roundtrip(self.d)
        self.assertEqual(len(mx.findall("diagram")), 2)

    def test_add_layer_has_parent_zero(self):
        lid = self.d.add_layer("Ops", key="ops")
        c = cell(self.d.root, lid)
        self.assertEqual(lid, "ops")
        self.assertEqual(c.get("parent"), "0")
        self.assertEqual(c.get("value"), "Ops")
        self.assertIsNone(c.get("visible"))
        hidden = self.d.add_layer("Hidden", visible=False)
        self.assertEqual(cell(self.d.root, hidden).get("visible"), "0")
        gid = self.d.add_group("R", 0, 0, 200, 100, parent=lid)
        self.assertEqual(cell(self.d.root, gid).get("parent"), lid)
        self.assertIn(lid, self.d.page["layers"])
        self.assertEqual(self.d.validate(), [])

    def test_add_image_svg_without_pillow(self):
        logo = self.tmp / "logo.svg"
        logo.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
                        '<circle cx="5" cy="5" r="4"/></svg>', encoding="utf-8")
        cid = self.d.add_image(logo, 10, 10, 100, 40)
        tok = tokens(cell(self.d.root, cid).get("style"))
        self.assertIn("%3Ccircle", tok["image"])
        with self.assertRaises(FileNotFoundError):
            self.d.add_image(self.tmp / "nope.svg", 0, 0, 10, 10)

    def test_resize_updates_geometry_and_registry(self):
        gid = self.d.add_group("R", 0, 0, 200, 100)
        self.d.resize(gid, w=300, h=150, x=10)
        g = geom(cell(self.d.root, gid))
        self.assertEqual((g["x"], g["y"], g["width"], g["height"]), (10.0, 0.0, 300.0, 150.0))
        self.assertEqual(self.d.bbox(gid), (10.0, 0.0, 300.0, 150.0))

    def test_append_pages(self):
        a = DrawioBuilder(page_name="One")
        a.add_group("A", 0, 0, 200, 100, key="region")
        b = DrawioBuilder(page_name="Two")
        b.add_group("B", 0, 0, 200, 100, key="region")      # same key on another page is fine
        b.add_page("Three")
        b.add_icon("VM", "vm", 0, 0, key="vm")
        a.append_pages(b)
        self.assertEqual([p["name"] for p in a._pages], ["One", "Two", "Three"])
        self.assertEqual([d.get("id") for d in a.mxfile.findall("diagram")], ["page1", "page2", "page3"])
        self.assertEqual(a._page_idx, 0)                    # appended pages are read-only
        path, _ = self.roundtrip(a)
        errors, _, pages, containers = db.validate_file(path)
        self.assertEqual((errors, pages, containers), ([], 3, 2))
        with self.assertRaises(ValueError):
            a.append_pages(a)

    def test_append_pages_keeps_both_builders_usable(self):
        b = DrawioBuilder(page_name="Two")
        b.add_group("B", 0, 0, 200, 100, key="region")
        b.add_page("Three")
        b.add_icon("VM", "vm", 0, 0, key="vm")
        docs = []
        for name in ("One", "Uno"):
            a = DrawioBuilder(page_name=name)
            a.add_group("A", 0, 0, 200, 100, key="region")
            a.append_pages(b)
            docs.append(a)
        # the source keeps its own pages and ids; appending it twice corrupts neither document
        self.assertEqual([d.get("id") for d in b.mxfile.findall("diagram")], ["page1", "page2"])
        for a in docs:
            self.assertEqual([d.get("id") for d in a.mxfile.findall("diagram")],
                             ["page1", "page2", "page3"])
            # the current page is still the builder's own and still sizeable from its content
            self.assertEqual(a.fit_page(), (220, 120))
            self.assertEqual([m for m in a.validate() if "exceeds the page" in m], [])
        path, _ = self.roundtrip(b, name="source.drawio")
        errors, _, pages, _ = db.validate_file(path)
        self.assertEqual((errors, pages), ([], 2))
        # an appended page cannot be made current (its cells are not in the registry)
        with self.assertRaises(ValueError):
            docs[0].use_page("Three")
        with self.assertRaises(ValueError):
            docs[0].use_page(1)
        self.assertEqual(docs[0].use_page("One"), 0)


# ---------------------------------------------------------------------------
# 10. Module-level compatibility helpers
# ---------------------------------------------------------------------------
class TestModuleCompat(unittest.TestCase):
    def test_find_container_overlaps_on_root(self):
        d = DrawioBuilder()
        r = d.add_group("R", 0, 0, 800, 600)
        d.add_group("A", 20, 40, 300, 200, parent=r, group_type="vcn")
        d.add_group("B", 200, 40, 300, 200, parent=r, group_type="vcn")
        msgs = db.find_container_overlaps(d.root)
        self.assertEqual(len(msgs), 1)
        self.assertTrue(msgs[0].startswith("OVERLAP"))
        clean = DrawioBuilder()
        clean.add_group("R", 0, 0, 100, 100)
        self.assertEqual(db.find_container_overlaps(clean.root), [])

    def test_build_cell_registry_unwraps_object_and_userobject(self):
        d = DrawioBuilder()
        obj = d.add_group("Tooltip group", 0, 0, 200, 100, tooltip="t")
        uo = d.add_group("Link group", 300, 0, 200, 100, link="https://x")
        icon = d.add_icon("VM", "vm", 600, 0, metadata={"ocid": "x"})
        reg = db.build_cell_registry(d.root)
        self.assertIn("0", reg)
        self.assertIn("1", reg)
        for cid, label in ((obj, "Tooltip group"), (uo, "Link group")):
            self.assertIn(cid, reg)
            self.assertEqual(reg[cid]["value"], label)
            self.assertEqual(reg[cid]["vertex"], "1")
            self.assertEqual(reg[cid]["parent"], "1")
            self.assertEqual(reg[cid]["w"], 200.0)
            self.assertEqual(db._kind(reg[cid]), "group")
        self.assertEqual(db._kind(reg[icon]), "icon")

    def test_edge_label_extent_estimates_width_and_height(self):
        w, h = db.edge_label_extent("Site-to-Site VPN", 12)
        self.assertAlmostEqual(w, 16 * 12 * 0.56 + 8)
        self.assertAlmostEqual(h, 15)
        w2, h2 = db.edge_label_extent("one<br>three", 12)
        self.assertAlmostEqual(w2, 5 * 12 * 0.56 + 8)          # widest line wins
        self.assertAlmostEqual(h2, 30)
        self.assertAlmostEqual(db.edge_label_extent("", 12)[0], 8)
        self.assertAlmostEqual(db.edge_label_extent("&amp;", 12)[0], 1 * 12 * 0.56 + 8)

    def test_label_lines_estimate(self):
        self.assertGreater(db.label_lines("word " * 30, 101), 3)
        self.assertEqual(db.label_lines("", 101), 1)
        self.assertEqual(db.label_lines("short", 101), 1)
        self.assertEqual(db.label_lines("a<br>b<br>c", 101), 3)
        self.assertEqual(db.label_lines("a\nb", 101), 2)
        # a wrap hint is a break opportunity of zero width: measured as a space
        self.assertEqual(db.label_lines(f"aaaaa{db.WRAP_HINT}bbbbb", 40, 11), 2)
        self.assertEqual(db.label_lines("aaaaa bbbbb", 40, 11), 2)

    def test_wrap_hints_only_break_identifier_separators(self):
        self.assertEqual(db.wrap_hints("vcn_a-b.c"),
                         f"vcn_{db.WRAP_HINT}a-{db.WRAP_HINT}b.{db.WRAP_HINT}c")
        self.assertEqual(db.wrap_hints("VCN attachment\nspoke"), "VCN attachment\nspoke")
        self.assertEqual(db.wrap_hints("ends-"), "ends-")                  # nothing to break before
        self.assertEqual(db.wrap_hints("a__b"), f"a__{db.WRAP_HINT}b")     # one hint per run
        self.assertEqual(db.wrap_hints("10.0.0.0/16"), "10.0.0.0/16")      # dotted numbers keep their line
        self.assertEqual(db.wrap_hints(None), "")
        hinted = db.wrap_hints("drg_attachment_vcn_prod_shared_services_hub")
        self.assertEqual(hinted.replace(db.WRAP_HINT, ""), "drg_attachment_vcn_prod_shared_services_hub")
        self.assertGreater(db.label_lines(hinted, 96, 11), 1)

    def test_escape_label(self):
        self.assertEqual(db.escape_label(None), "")
        self.assertEqual(db.escape_label("a < b & c\nd"), "a &lt; b &amp; c<br>d")
        self.assertEqual(db.escape_label(443), "443")
        self.assertEqual(db.escape_label('say "hi"'), 'say "hi"')

    def test_version_and_exports(self):
        self.assertEqual(db.__version__, "1.3.0")
        for name in ("DrawioBuilder", "validate_file", "find_container_overlaps",
                     "build_cell_registry", "escape_label", "label_lines", "FONT_STACK"):
            self.assertIn(name, db.__all__)
            self.assertTrue(hasattr(db, name))
        self.assertEqual(db.ICON_FOOTPRINT_H, db.ICON_H + db.LABEL_GAP + db.LABEL_H)
        self.assertEqual(db.ICON_FOOTPRINT_H, 142)

    def test_group_styles_module_view_matches_default_builder(self):
        d = DrawioBuilder()
        for gt in db.GROUP_TYPES:
            self.assertEqual(db._GROUP_STYLES[gt], d._group_styles[gt], gt)


# ---------------------------------------------------------------------------
# 11. Optional draw.io desktop render
# ---------------------------------------------------------------------------
class TestRender(TempDirMixin, unittest.TestCase):
    def _fake_export(self, out_dir):
        """Patch find_drawio_binary/subprocess.run; returns the recorded argv list."""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"\x89PNG\r\n\x1a\nfake")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        self.addCleanup(setattr, db, "find_drawio_binary", db.find_drawio_binary)
        self.addCleanup(setattr, db.subprocess, "run", db.subprocess.run)
        db.find_drawio_binary = lambda: str(out_dir / "fake-drawio")
        db.subprocess.run = fake_run
        return calls

    def test_render_returns_none_without_binary(self):
        self.addCleanup(setattr, db, "find_drawio_binary", db.find_drawio_binary)
        db.find_drawio_binary = lambda: None
        self.assertIsNone(db.render(self.tmp / "x.drawio"))

    def test_render_command_line_default_scale(self):
        calls = self._fake_export(self.tmp)
        src = self.tmp / "a.drawio"
        src.write_text("<mxfile/>")
        out = db.render(src, fmt="svg")
        self.assertEqual(out, src.with_suffix(".svg"))
        (cmd,) = calls
        self.assertEqual(cmd[1:4], ["-x", "-f", "svg"])
        self.assertEqual(cmd[-1], str(src))
        self.assertNotIn("-s", cmd)

    def test_render_scale_flag_does_not_split_format_option(self):
        """KNOWN DEFECT: render(scale=2) splices "-s 2" at cmd[3:3], i.e.
        between "-f" and its value ("-f -s 2 png ..."), so the draw.io CLI
        reads "-s" as the format and fails with 'input file/directory not
        found'. The flag must be inserted after the format value (cmd[4:4])."""
        calls = self._fake_export(self.tmp)
        src = self.tmp / "a.drawio"
        src.write_text("<mxfile/>")
        db.render(src, fmt="png", scale=2.0)
        (cmd,) = calls
        self.assertEqual(cmd[cmd.index("-f") + 1], "png")
        self.assertEqual(cmd[cmd.index("-s") + 1], "2.0")

    def test_render_png_with_drawio_desktop(self):
        if db.find_drawio_binary() is None:
            self.skipTest("draw.io desktop binary not installed")
        d = DrawioBuilder()
        r = d.add_group("Region", 20, 20, 300, 200, group_type="region")
        d.add_icon("VM", "vm", 20, 50, parent=r)
        path = quiet_write(d, self.tmp / "render.drawio")
        out = d.render(path, fmt="png")
        self.assertIsNotNone(out)
        self.assertTrue(Path(out).is_file())
        self.assertEqual(Path(out).suffix, ".png")
        with open(out, "rb") as fh:
            self.assertEqual(fh.read(8), b"\x89PNG\r\n\x1a\n")
        self.assertGreater(os.path.getsize(out), 500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
