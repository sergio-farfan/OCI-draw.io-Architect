"""
Integrity tests for the bundled OCI icon set (stdlib only, Python 3.9+).

Run from the plugin root:
    python3 -m unittest discover -s tests -v
or directly:
    python3 tests/test_icons.py

Environment:
    OCI_SVG_DIR              icon directory (default: <plugin>/icons)
    OCI_ICON_ALIASES_JSON    alias JSON used when drawio_builder.ICON_ALIASES is absent
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
ICON_DIR = Path(os.environ.get("OCI_SVG_DIR") or PLUGIN_ROOT / "icons")

SVG_NS = "{http://www.w3.org/2000/svg}"
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PLACEHOLDER_STROKE = 'stroke="#000000"'
TRANSFORM_RE = re.compile(
    r"translate\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)\s*scale\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)"
)
NUM_RE = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")
MAX_PADDING = 3.0  # viewBox may exceed the glyph bbox by at most this many units per side


def all_svgs():
    return sorted(ICON_DIR.rglob("*.svg"))


def import_builder():
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        return importlib.import_module("drawio_builder")
    except Exception:  # noqa: BLE001 - any import problem just disables builder-based tests
        return None


def load_aliases():
    """Return (aliases, source) preferring drawio_builder.ICON_ALIASES, else the JSON file."""
    builder = import_builder()
    aliases = getattr(builder, "ICON_ALIASES", None) if builder else None
    if isinstance(aliases, dict) and aliases:
        return dict(aliases), "drawio_builder.ICON_ALIASES"
    path = os.environ.get("OCI_ICON_ALIASES_JSON")
    if path and Path(path).is_file():
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), path
    return None, None


def content_bbox(root):
    """Union bbox of all path coordinates after each <g translate+scale> transform."""
    xs, ys = [], []
    for g in root.iter(f"{SVG_NS}g"):
        m = TRANSFORM_RE.search(g.get("transform", ""))
        tx, ty, sx, sy = map(float, m.groups()) if m else (0.0, 0.0, 1.0, 1.0)
        for path in g.iter(f"{SVG_NS}path"):
            nums = [float(n) for n in NUM_RE.findall(path.get("d", ""))]
            for i in range(0, len(nums) - 1, 2):
                xs.append(tx + sx * nums[i])
                ys.append(ty + sy * nums[i + 1])
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


class TestIconDirectory(unittest.TestCase):
    def test_icon_dir_exists_with_svgs(self):
        self.assertTrue(ICON_DIR.is_dir(), f"icon dir missing: {ICON_DIR}")
        self.assertGreater(len(all_svgs()), 0, "no SVG files found")

    def test_no_empty_category_dirs(self):
        for d in sorted(p for p in ICON_DIR.iterdir() if p.is_dir()):
            with self.subTest(category=d.name):
                self.assertTrue(any(d.glob("*.svg")), f"category dir has no SVGs: {d}")

    def test_no_duplicate_icon_content(self):
        seen = {}
        for p in all_svgs():
            digest = hashlib.md5(p.read_bytes()).hexdigest()
            seen.setdefault(digest, []).append(p.relative_to(ICON_DIR).as_posix())
        dups = [v for v in seen.values() if len(v) > 1]
        self.assertEqual(dups, [], f"duplicate-content icons: {dups}")


class TestEverySvg(unittest.TestCase):
    def test_filenames_are_valid_keys(self):
        for p in all_svgs():
            with self.subTest(file=p.name):
                self.assertRegex(p.stem, KEY_RE)
                self.assertNotIn("amp_nbsp", p.stem, "scrape artifact in filename")

    def test_parses_and_has_path(self):
        for p in all_svgs():
            with self.subTest(file=p.relative_to(ICON_DIR).as_posix()):
                root = ET.parse(p).getroot()
                self.assertGreater(len(root), 0, "SVG root has no children")
                self.assertGreaterEqual(len(root.findall(f".//{SVG_NS}path")), 1, "no <path>")

    def test_no_placeholder_stroke(self):
        for p in all_svgs():
            with self.subTest(file=p.relative_to(ICON_DIR).as_posix()):
                self.assertNotIn(PLACEHOLDER_STROKE, p.read_text(encoding="utf-8"))

    def test_viewbox_positive_and_consistent(self):
        for p in all_svgs():
            with self.subTest(file=p.relative_to(ICON_DIR).as_posix()):
                root = ET.parse(p).getroot()
                vb = root.get("viewBox")
                self.assertIsNotNone(vb, "missing viewBox")
                parts = [float(v) for v in vb.split()]
                self.assertEqual(len(parts), 4, f"bad viewBox {vb!r}")
                self.assertGreater(parts[2], 0)
                self.assertGreater(parts[3], 0)
                if root.get("width") and root.get("height"):
                    self.assertAlmostEqual(float(root.get("width")), parts[2], places=2)
                    self.assertAlmostEqual(float(root.get("height")), parts[3], places=2)

    def test_viewbox_hugs_content(self):
        for p in all_svgs():
            with self.subTest(file=p.relative_to(ICON_DIR).as_posix()):
                root = ET.parse(p).getroot()
                bbox = content_bbox(root)
                self.assertIsNotNone(bbox, "no coordinates found")
                minx, miny, w, h = [float(v) for v in root.get("viewBox").split()]
                bx0, by0, bx1, by1 = bbox
                eps = 1e-6
                self.assertLessEqual(minx, bx0 + eps, "content clipped on the left")
                self.assertLessEqual(miny, by0 + eps, "content clipped at the top")
                self.assertGreaterEqual(minx + w, bx1 - eps, "content clipped on the right")
                self.assertGreaterEqual(miny + h, by1 - eps, "content clipped at the bottom")
                for side, pad in (("left", bx0 - minx), ("top", by0 - miny),
                                  ("right", minx + w - bx1), ("bottom", miny + h - by1)):
                    self.assertLessEqual(pad, MAX_PADDING, f"loose viewBox: {pad:.2f} units of {side} padding")


class TestAliases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aliases, cls.source = load_aliases()
        cls.by_rel = {p.relative_to(ICON_DIR).as_posix(): p for p in all_svgs()}
        cls.by_stem = {p.stem: p for p in all_svgs()}

    def setUp(self):
        if not self.aliases:
            self.skipTest("no aliases: drawio_builder.ICON_ALIASES absent and OCI_ICON_ALIASES_JSON not set")

    def test_alias_keys_are_valid(self):
        for key in self.aliases:
            with self.subTest(alias=key):
                self.assertRegex(key, KEY_RE)

    def test_alias_targets_exist(self):
        for key, rel in sorted(self.aliases.items()):
            with self.subTest(alias=key):
                self.assertIn(rel, self.by_rel, f"{key} -> {rel} does not exist (source: {self.source})")

    def test_alias_does_not_shadow_a_different_stem(self):
        for key, rel in sorted(self.aliases.items()):
            if key in self.by_stem:
                with self.subTest(alias=key):
                    self.assertEqual(self.by_stem[key].relative_to(ICON_DIR).as_posix(), rel)


class TestBuilderIconMap(unittest.TestCase):
    """If drawio_builder still exposes ICON_MAP, all of its targets must exist too."""

    def test_icon_map_targets_exist(self):
        builder = import_builder()
        icon_map = getattr(builder, "ICON_MAP", None) if builder else None
        if not isinstance(icon_map, dict):
            self.skipTest("drawio_builder.ICON_MAP not available")
        for key, rel in sorted(icon_map.items()):
            with self.subTest(key=key):
                self.assertTrue((ICON_DIR / rel).is_file(), f"{key} -> {rel} missing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
