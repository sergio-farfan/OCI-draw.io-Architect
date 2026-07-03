"""Reusable draw.io builder for OCI architecture diagrams.

Requires Python 3.9+.

Provides the DrawioBuilder class, OCI SVG icon loading with viewBox fix,
Oracle template container styles, PNG-in-SVG logo embedding, and a
find_container_overlaps()/check_overlaps() pair for catching overlapping
containers before you hand the file to draw.io.

Usage:
    1. Copy this file into your diagram script directory
    2. Icons are bundled in the plugin's icons/ directory (auto-detected)
    3. Override with OCI_SVG_DIR env var if needed
    4. Import and use:

        from drawio_builder import DrawioBuilder, add_icons_to_map
        add_icons_to_map({"my_icon": "networking/networking_vcn.svg"})
        d = DrawioBuilder(page_name="My Diagram", width=1600, height=1100)
        region = d.add_group("eu-frankfurt-1", 20, 75, 1560, 1000, group_type="region")
        d.add_icon("Load Balancer", "load_balancer", 50, 50, parent=region)
        d.add_edge(source_id, target_id, "443", parent=region)
        d.write(Path("output.drawio"))
"""

from __future__ import annotations

import base64
import difflib
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths - resolve icons directory with fallback chain:
#   1. OCI_SVG_DIR env var (explicit override)
#   2. Bundled icons/ directory (sibling to scripts/, inside plugin)
#   3. Legacy path ~/tests/oci-iconset/icons/svg
# ---------------------------------------------------------------------------
def _resolve_icon_dir() -> Path:
    env = os.environ.get("OCI_SVG_DIR")
    if env:
        return Path(env)
    bundled = Path(__file__).resolve().parent.parent / "icons"
    if bundled.is_dir():
        return bundled
    return Path.home() / "tests" / "oci-iconset" / "icons" / "svg"

OCI_SVG_DIR = _resolve_icon_dir()

# ---------------------------------------------------------------------------
# OCI Template Colors (from Oracle draw.io templates)
# ---------------------------------------------------------------------------
COLORS = {
    # Official Redwood diagram palette (OCI Architecture Diagram Toolkit v24.2)
    "region_fill": "#F5F4F2",    # Neutral 1 - region / on-prem group fill
    "region_stroke": "#9E9892",  # Neutral 3 - location-group borders
    "neutral_2": "#DFDCD8",      # Availability Domain fill
    "air": "#FCFBFA",            # Fault Domain fill
    "vcn_stroke": "#AE562C",     # Sienna - VCN/subnet/compartment borders
    "vcn_label": "#AE562C",      # Sienna - VCN/subnet labels
    "text_primary": "#312D2A",   # Bark - all text and connectors
    "rose": "#A36472",           # Oracle Services Network border/label
    "ivy": "#759C6C",            # OCI logical component border
    "oracle_red": "#C74634",     # On-premises logical component border only
    "edge_color": "#312D2A",     # Bark - official connector color
    # Custom extensions (not part of the official Oracle palette)
    "edge_accent": "#AE562C",    # legacy accent edges - kept for script compat
    "edge_purple": "#7B61FF",    # custom extension for special data flows
}

ICON_W = 75  # nominal slot width - actual cell width is derived from the SVG's aspect
ICON_H = 95  # fixed icon cell height
LABEL_GAP = 2
LABEL_W = 105
LABEL_H = 45

# ---------------------------------------------------------------------------
# Icon key -> SVG file path (relative to OCI_SVG_DIR)
# ---------------------------------------------------------------------------
ICON_MAP = {
    "load_balancer": "networking/networking_load_balancer.svg",
    "vm": "compute/compute_virtual_machine_vm.svg",
    "block_storage": "storage/storage_block_storage.svg",
    "functions": "compute/compute_functions.svg",
    "autonomous_db": "database/database_autonomous_db.svg",
    "nosql": "database/database_nosql.svg",
    "nsg": "identity_and_security/identity_and_security_nsg.svg",
    "big_data": "analytics_and_ai/analytics_and_ai_big_data.svg",
    "service_gateway": "networking/networking_service_gateway.svg",
    "data_science": "analytics_and_ai/analytics_and_ai_data_science.svg",
    "ai": "analytics_and_ai/analytics_and_ai_artificial_intelligence.svg",
    "vault": "identity_and_security/identity_and_security_vault.svg",
    "waf": "identity_and_security/identity_and_security_waf.svg",
    "certificates": "identity_and_security/identity_and_security_certificates.svg",
    "devops": "developer_services/developer_services_devops.svg",
    "container_registry": "developer_services/developer_services_container_registry.svg",
    "buckets": "storage/storage_buckets.svg",
    "queuing": "observability_and_management/observability_and_management_queuing.svg",
    "logging": "observability_and_management/observability_and_management_logging.svg",
    "apm": "observability_and_management/observability_and_management_application_performance_management.svg",
    "alarms": "observability_and_management/observability_and_management_alarms.svg",
    "dns": "networking/networking_dns.svg",
    "cpe": "networking/networking_customer_premises_equipment_cpe.svg",
    "drg": "networking/networking_dynamic_routing_gateway_drg.svg",
    "nat_gateway": "networking/networking_nat_gateway.svg",
    "firewall": "identity_and_security/identity_and_security_firewall.svg",
    "internet_gateway": "networking/networking_internet_gateway.svg",
}


def add_icons_to_map(new_icons: dict[str, str]) -> None:
    """Add or override entries in the global ICON_MAP.

    Args:
        new_icons: dict of {key: "category/filename.svg"} paths relative to OCI_SVG_DIR.
    """
    ICON_MAP.update(new_icons)


# Cache: icon_key -> (URL-encoded SVG data URI, native width, native height)
_svg_cache: dict[str, tuple[str, float, float]] = {}


def _load_svg(icon_key: str) -> tuple[str, float, float]:
    """Load an SVG, fix viewBox to fit all content, return (data_uri, native_w, native_h).

    OCI SVGs sometimes have content that extends beyond the declared viewBox
    (translate offsets + scaled paths exceed the width/height). We compute the
    actual content bounds from the transform attributes and expand the viewBox.
    The returned native width/height reflect that expanded viewBox so callers
    can size icon cells to the SVG's real aspect ratio.
    """
    if icon_key in _svg_cache:
        return _svg_cache[icon_key]

    import urllib.parse

    svg_path = OCI_SVG_DIR / ICON_MAP[icon_key]
    if not svg_path.is_file():
        raise FileNotFoundError(
            f"Icon SVG not found: {svg_path}. Check that OCI_SVG_DIR "
            f"(currently {OCI_SVG_DIR}) points at a valid icon set, or set "
            f"the OCI_SVG_DIR env var to override it."
        )
    svg_text = svg_path.read_text()

    native_w = native_h = None

    # Compute actual content bounds from translate+scale transforms.
    # Each <g transform="translate(tx,ty) scale(sx,sy)"> contains paths in
    # a 0-100 coordinate space, so the drawn area goes to (tx+100*sx, ty+100*sy).
    transforms = re.findall(
        r'translate\(([\d.]+),([\d.]+)\)\s*scale\(([\d.]+),([\d.]+)\)', svg_text)
    if transforms:
        max_x = max(float(tx) + 100 * float(sx) for tx, _, sx, _ in transforms)
        max_y = max(float(ty) + 100 * float(sy) for _, ty, _, sy in transforms)
        # Add small padding
        max_x = round(max_x + 2)
        max_y = round(max_y + 2)

        vb_m = re.search(r'viewBox="([^"]+)"', svg_text)
        if vb_m:
            parts = vb_m.group(1).split()
            cur_w, cur_h = float(parts[2]), float(parts[3])
            new_w = max(cur_w, max_x)
            new_h = max(cur_h, max_y)
            svg_text = svg_text.replace(
                f'viewBox="{vb_m.group(1)}"',
                f'viewBox="0 0 {new_w} {new_h}"')
            # Update width/height attributes to match
            svg_text = re.sub(r'\bwidth="\d+"', f'width="{int(new_w)}"', svg_text)
            svg_text = re.sub(r'\bheight="\d+"', f'height="{int(new_h)}"', svg_text)
            native_w, native_h = new_w, new_h

    if native_w is None:
        vb_m = re.search(r'viewBox="([^"]+)"', svg_text)
        if vb_m:
            parts = vb_m.group(1).split()
            native_w, native_h = float(parts[2]), float(parts[3])
        else:
            w_m = re.search(r'\bwidth="(\d+(?:\.\d+)?)"', svg_text)
            h_m = re.search(r'\bheight="(\d+(?:\.\d+)?)"', svg_text)
            if w_m and h_m:
                native_w, native_h = float(w_m.group(1)), float(h_m.group(1))
            else:
                native_w, native_h = float(ICON_W), float(ICON_H)

    encoded = urllib.parse.quote(svg_text, safe='')
    data_uri = f"data:image/svg+xml,{encoded}"
    result = (data_uri, native_w, native_h)
    _svg_cache[icon_key] = result
    return result


# ---------------------------------------------------------------------------
# Group style templates (from Oracle draw.io templates)
# ---------------------------------------------------------------------------
_GROUP_STYLES = {
    "region": (
        "whiteSpace=wrap;html=1;rounded=1;arcSize=2;"
        "fillColor={region_fill};strokeColor={region_stroke};"
        "fontFamily=Oracle Sans;fontSize=11;fontStyle=1;"
        "fontColor={text_primary};verticalAlign=top;align=center;"
        "labelBackgroundColor=none;spacingRight=5;"
        "container=1;collapsible=0;expand=0;"
    ),
    "tenancy": (
        "whiteSpace=wrap;html=1;rounded=0;strokeWidth=1;dashed=1;"
        "fillColor=none;strokeColor={region_stroke};"
        "fontFamily=Oracle Sans;fontSize=12;fontStyle=1;"
        "fontColor={text_primary};verticalAlign=top;align=left;"
        "spacingLeft=5;container=1;collapsible=0;expand=0;"
    ),
    "availability_domain": (
        "whiteSpace=wrap;html=1;rounded=1;"
        "fillColor={neutral_2};strokeColor={region_stroke};"
        "fontFamily=Oracle Sans;fontSize=11;fontStyle=1;"
        "fontColor={text_primary};verticalAlign=top;align=center;"
        "container=1;collapsible=0;expand=0;"
    ),
    "fault_domain": (
        "whiteSpace=wrap;html=1;rounded=1;"
        "fillColor={air};strokeColor={region_stroke};"
        "fontFamily=Oracle Sans;fontSize=11;fontStyle=1;"
        "fontColor={text_primary};verticalAlign=top;align=center;"
        "container=1;collapsible=0;expand=0;"
    ),
    "compartment": (
        "whiteSpace=wrap;html=1;rounded=0;strokeWidth=1;dashed=1;dashPattern=1 1;"
        "fillColor=none;strokeColor={vcn_stroke};"
        "fontFamily=Oracle Sans;fontSize=11;fontStyle=1;"
        "fontColor={text_primary};verticalAlign=top;align=center;"
        "spacingLeft=5;container=1;collapsible=0;expand=0;"
    ),
    "vcn": (
        "whiteSpace=wrap;html=1;rounded=0;strokeWidth=2;dashed=1;"
        "fillColor=none;strokeColor={vcn_stroke};labelBackgroundColor=none;"
        "fontFamily=Oracle Sans;fontSize=12;fontStyle=1;"
        "fontColor={vcn_label};verticalAlign=top;align=left;"
        "spacingLeft=5;container=1;collapsible=0;expand=0;"
    ),
    "subnet": (
        "whiteSpace=wrap;html=1;rounded=0;strokeWidth=1;dashed=1;"
        "fillColor=none;strokeColor={vcn_stroke};"
        "fontFamily=Oracle Sans;fontSize=11;fontStyle=1;"
        "fontColor={vcn_label};verticalAlign=top;align=left;"
        "spacingLeft=5;container=1;collapsible=0;expand=0;"
    ),
    "services": (
        "whiteSpace=wrap;html=1;rounded=0;strokeWidth=2;dashed=1;"
        "fillColor=none;strokeColor={region_stroke};"
        "fontFamily=Oracle Sans;fontSize=11;fontStyle=1;"
        "fontColor={text_primary};verticalAlign=top;align=left;"
        "spacingLeft=5;container=1;collapsible=0;expand=0;"
    ),
    "oracle_services_network": (
        "whiteSpace=wrap;html=1;rounded=0;strokeWidth=2;dashed=1;"
        "fillColor=none;strokeColor={rose};"
        "fontFamily=Oracle Sans;fontSize=11;fontStyle=1;"
        "fontColor={rose};verticalAlign=top;align=left;"
        "spacingLeft=5;container=1;collapsible=0;expand=0;"
    ),
    "onprem": (
        "whiteSpace=wrap;html=1;rounded=1;arcSize=2;"
        "fillColor={region_fill};strokeColor={region_stroke};"
        "fontFamily=Oracle Sans;fontSize=11;fontStyle=1;"
        "fontColor={text_primary};verticalAlign=top;align=center;"
        "labelBackgroundColor=none;spacingRight=5;"
        "container=1;collapsible=0;expand=0;"
    ),
}
# Deprecated alias (pre-1.1.0 scripts): hub renders like onprem/region
_GROUP_STYLES["hub"] = _GROUP_STYLES["onprem"]


def _fmt_num(value: float) -> str:
    """Render a float as a plain int string when it's a whole number."""
    return str(int(value)) if float(value).is_integer() else str(value)


# ---------------------------------------------------------------------------
# Overlap detection - call before write() to catch overlapping containers
# ---------------------------------------------------------------------------
def build_cell_registry(root) -> dict[str, dict]:
    """Parse direct children of an mxGraphModel <root> into a cell registry.

    Maps cell id -> {value, style, parent, vertex, x, y, w, h}, handling both
    plain <mxCell> vertices and <object> wrappers (metadata/tooltip cells).
    Shared by find_container_overlaps and the check_overlaps CLI.
    """
    registry = {}
    for el in root:
        cid = el.get("id")
        if cid is None:
            continue
        if el.tag == "mxCell":
            value = el.get("value", "")
            style = el.get("style", "")
            parent = el.get("parent")
            vertex = el.get("vertex")
            geom = el.find("mxGeometry")
        elif el.tag == "object":
            value = el.get("label", "")
            inner = el.find("mxCell")
            if inner is None:
                continue
            style = inner.get("style", "")
            parent = inner.get("parent")
            vertex = inner.get("vertex")
            geom = inner.find("mxGeometry")
        else:
            continue
        if geom is not None:
            x = float(geom.get("x", 0) or 0)
            y = float(geom.get("y", 0) or 0)
            w = float(geom.get("width", 0) or 0)
            h = float(geom.get("height", 0) or 0)
        else:
            x = y = w = h = 0.0
        registry[cid] = {
            "value": value, "style": style, "parent": parent,
            "vertex": vertex, "x": x, "y": y, "w": w, "h": h,
        }
    return registry


def find_container_overlaps(root) -> list[str]:
    """Find overlapping sibling containers under an mxGraphModel <root>.

    `root` is the <root> Element of an mxGraphModel (i.e. DrawioBuilder.root).
    Containers are vertex cells whose style contains "container=1"; two
    siblings (same parent) overlap when their absolute bounding boxes
    intersect with positive area (touching edges are not an overlap).

    Returns a list of "OVERLAP: ..." messages, or [] when clean.
    """
    registry = build_cell_registry(root)

    errors = []
    abs_cache = {}

    def abs_xy(cid):
        if cid in abs_cache:
            return abs_cache[cid]
        x_sum = y_sum = 0.0
        visited = set()
        current = cid
        while True:
            if current in abs_cache:
                cx, cy = abs_cache[current]
                x_sum += cx
                y_sum += cy
                break
            if current in visited:
                errors.append(
                    f"OVERLAP: cycle detected in parent chain at id '{current}'"
                )
                break
            visited.add(current)
            entry = registry.get(current)
            if entry is None:
                break
            x_sum += entry["x"]
            y_sum += entry["y"]
            parent = entry["parent"]
            if parent in (None, "0", "1") or parent not in registry:
                break
            current = parent
        result = (x_sum, y_sum)
        abs_cache[cid] = result
        return result

    containers = [
        cid for cid, e in registry.items()
        if e["vertex"] == "1" and "container=1" in e["style"]
    ]

    by_parent: dict = {}
    for cid in containers:
        by_parent.setdefault(registry[cid]["parent"], []).append(cid)

    for parent, siblings in by_parent.items():
        parent_entry = registry.get(parent)
        parent_label = (parent_entry["value"] if parent_entry and parent_entry["value"]
                         else parent)
        for i in range(len(siblings)):
            for j in range(i + 1, len(siblings)):
                a, b = siblings[i], siblings[j]
                ea, eb = registry[a], registry[b]
                ax, ay = abs_xy(a)
                bx, by = abs_xy(b)
                aw, ah = ea["w"], ea["h"]
                bw, bh = eb["w"], eb["h"]
                if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                    errors.append(
                        "OVERLAP: '{}' [abs x={},y={},w={},h={}] intersects "
                        "'{}' [abs x={},y={},w={},h={}] (siblings under '{}')".format(
                            ea["value"], _fmt_num(ax), _fmt_num(ay), _fmt_num(aw), _fmt_num(ah),
                            eb["value"], _fmt_num(bx), _fmt_num(by), _fmt_num(bw), _fmt_num(bh),
                            parent_label,
                        )
                    )
    return errors


# ---------------------------------------------------------------------------
# XML builder
# ---------------------------------------------------------------------------
class DrawioBuilder:
    """Builds a draw.io XML document.

    Typical usage:
        d = DrawioBuilder(page_name="Architecture", width=1600, height=1100)
        region = d.add_group("eu-frankfurt-1", 20, 75, 1560, 1000, group_type="region")
        vcn = d.add_group("VCN: MyVCN (10.0.0.0/16)", 20, 40, 1500, 900,
                          parent=region, group_type="vcn")
        d.add_icon("Load Balancer", "load_balancer", 50, 50, parent=vcn)
        d.add_edge(source_id, target_id, "443", parent=vcn)
        d.write(Path("output.drawio"))
    """

    def __init__(self, page_name="Architecture", width=1600, height=1100):
        self._cell_id = 1
        self.mxfile = ET.Element("mxfile", host="Python", type="device", compressed="false")
        self.diagram = ET.SubElement(self.mxfile, "diagram", id="page1", name=page_name)
        self.model = ET.SubElement(
            self.diagram, "mxGraphModel",
            dx=str(width), dy=str(height),
            grid="1", gridSize="10", guides="1", tooltips="1",
            connect="1", arrows="1", fold="1", page="1",
            pageScale="1", pageWidth=str(width), pageHeight=str(height),
            math="0", shadow="0", background="#FFFFFF",
        )
        self.root = ET.SubElement(self.model, "root")
        ET.SubElement(self.root, "mxCell", id="0")
        ET.SubElement(self.root, "mxCell", id="1", parent="0")

    def _next_id(self) -> str:
        self._cell_id += 1
        return str(self._cell_id)

    _RESERVED_METADATA_KEYS = {"id", "label", "placeholders", "tooltip"}
    _METADATA_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")

    def _emit_vertex(self, value, style, parent, x, y, w, h,
                      metadata=None, tooltip=None) -> str:
        """Emit a vertex cell, wrapping it in an <object> when metadata or a
        tooltip is supplied so custom attributes/tooltips survive round-trips
        through draw.io. Returns the new cell's id.
        """
        cid = self._next_id()
        if metadata or tooltip is not None:
            obj_attrs = {"id": cid, "label": value, "placeholders": "1"}
            if tooltip is not None:
                obj_attrs["tooltip"] = str(tooltip)
            if metadata:
                for key, val in metadata.items():
                    if not self._METADATA_KEY_RE.fullmatch(key) or key in self._RESERVED_METADATA_KEYS:
                        raise ValueError(
                            f"Invalid metadata key {key!r}: must match "
                            f"^[A-Za-z_][A-Za-z0-9_-]*$ and not be one of "
                            f"{sorted(self._RESERVED_METADATA_KEYS)}"
                        )
                    obj_attrs[key] = str(val)
            obj = ET.SubElement(self.root, "object", **obj_attrs)
            cell = ET.SubElement(obj, "mxCell", style=style, vertex="1", parent=parent)
        else:
            cell = ET.SubElement(
                self.root, "mxCell", id=cid, value=value, style=style,
                vertex="1", parent=parent,
            )
        ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y),
                       width=str(w), height=str(h)).set("as", "geometry")
        return cid

    def check_overlaps(self) -> list[str]:
        """Return overlap warnings for sibling containers. Call before write()."""
        return find_container_overlaps(self.root)

    def add_group(self, label, x, y, w, h, parent="1", group_type="region",
                  metadata=None, tooltip=None):
        """Add a container rectangle. Returns cell ID."""
        if group_type not in _GROUP_STYLES:
            raise ValueError(
                f"Unknown group_type {group_type!r}. Valid group types: "
                f"{sorted(_GROUP_STYLES)}"
            )
        style = _GROUP_STYLES[group_type].format(**COLORS)
        return self._emit_vertex(label, style, parent, x, y, w, h,
                                  metadata=metadata, tooltip=tooltip)

    def add_icon(self, label, icon_key, x, y, parent="1", w=None, h=None,
                 metadata=None, tooltip=None):
        """Add an OCI SVG icon with a label below. Returns cell ID.

        Sizing: with neither w nor h, the icon cell is sized to ICON_H tall
        and scaled to the SVG's native aspect ratio (and re-centered in the
        ICON_W slot). Passing only w or only h scales the other dimension
        to match the aspect ratio; passing both uses them as-is.
        """
        if icon_key not in ICON_MAP:
            suggestions = difflib.get_close_matches(icon_key, ICON_MAP, n=3)
            hint = f" Did you mean {', '.join(suggestions)}?" if suggestions else ""
            raise ValueError(
                f"Unknown icon_key {icon_key!r}.{hint} See references/icon-catalog.md "
                f"for the full list of available icons, or register a custom one "
                f"with add_icons_to_map()."
            )
        data_uri, nw, nh = _load_svg(icon_key)
        # Malformed SVG dimensions fall back to nominal cell size
        if nw <= 0 or nh <= 0:
            nw, nh = float(ICON_W), float(ICON_H)

        if w is None and h is None:
            cell_h = ICON_H
            cell_w = round(ICON_H * nw / nh)
            cell_x = x + round((ICON_W - cell_w) / 2)
        elif h is None:
            cell_w = w
            cell_h = round(w * nh / nw)
            cell_x = x
        elif w is None:
            cell_h = h
            cell_w = round(h * nw / nh)
            cell_x = x
        else:
            cell_w, cell_h = w, h
            cell_x = x

        style = (
            f"shape=image;verticalLabelPosition=bottom;verticalAlign=top;"
            f"imageAspect=1;aspect=fixed;"
            f"image={data_uri};"
        )
        cid = self._emit_vertex("", style, parent, cell_x, y, cell_w, cell_h,
                                 metadata=metadata, tooltip=tooltip)

        # Text label below (plain mxCell, never wrapped in <object>)
        lid = self._next_id()
        label_style = (
            "text;html=1;strokeColor=none;fillColor=none;align=center;"
            "verticalAlign=top;whiteSpace=wrap;rounded=0;"
            f"fontFamily=Oracle Sans;fontSize=11;fontStyle=0;"
            f"fontColor={COLORS['text_primary']};"
        )
        label_w = max(cell_w + 30, LABEL_W)
        label_x = cell_x + round((cell_w - label_w) / 2)
        label_y = y + cell_h + LABEL_GAP
        lc = ET.SubElement(
            self.root, "mxCell", id=lid, value=label, style=label_style,
            vertex="1", parent=parent,
        )
        ET.SubElement(lc, "mxGeometry",
                       x=str(label_x), y=str(label_y),
                       width=str(label_w), height=str(LABEL_H)).set("as", "geometry")
        return cid

    def add_image(self, image_path, x, y, w, h, parent="1"):
        """Add a PNG/image as a URL-encoded SVG wrapper (a raw ';base64,' marker
        would break draw.io's semicolon-delimited style parsing - URL-encoding
        avoids it)."""
        import urllib.parse
        from PIL import Image
        import io

        cid = self._next_id()
        img_path = Path(image_path)

        # Load and resize to max 300px wide to keep data small
        img = Image.open(img_path)
        if img.width > 300:
            ratio = 300 / img.width
            img = img.resize((300, int(img.height * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        img_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        # Wrap PNG in an SVG so we can URL-encode it (a raw ';base64,' marker would
        # break draw.io's semicolon-delimited style parsing - URL-encoding avoids it)
        svg_wrapper = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{img.width}" height="{img.height}">'
            f'<image width="{img.width}" height="{img.height}" '
            f'xlink:href="data:image/png;base64,{img_b64}"/>'
            f'</svg>'
        )
        encoded = urllib.parse.quote(svg_wrapper, safe='')
        data_uri = f"data:image/svg+xml,{encoded}"

        style = (
            f"shape=image;verticalLabelPosition=bottom;labelBackgroundColor=none;"
            f"verticalAlign=top;aspect=fixed;imageAspect=1;"
            f"image={data_uri};"
        )
        cell = ET.SubElement(
            self.root, "mxCell", id=cid, value="", style=style,
            vertex="1", parent=parent,
        )
        ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y),
                       width=str(w), height=str(h)).set("as", "geometry")
        return cid

    def add_text(self, label, x, y, w=200, h=30, parent="1",
                 font_size=10, font_style=0, align="left", font_color=None,
                 font_family="Oracle Sans"):
        """Add a text-only label."""
        cid = self._next_id()
        fc = font_color or COLORS["text_primary"]
        style = (
            f"text;html=1;strokeColor=none;fillColor=none;align={align};"
            f"verticalAlign=middle;whiteSpace=wrap;rounded=0;"
            f"fontFamily={font_family};fontSize={font_size};fontStyle={font_style};"
            f"fontColor={fc};"
        )
        cell = ET.SubElement(
            self.root, "mxCell", id=cid, value=label, style=style,
            vertex="1", parent=parent,
        )
        ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y),
                       width=str(w), height=str(h)).set("as", "geometry")
        return cid

    @staticmethod
    def _arrow_fragment(dashed: bool) -> str:
        """Shared open/closed arrowhead style fragment for add_edge."""
        if dashed:
            return "dashed=1;endArrow=none;endFill=0;"
        return "dashed=0;endArrow=open;endFill=0;"

    def _edge_style(self, color, dashed, style_extra):
        """Legacy (pinned, non-orthogonal-router) edge base style."""
        ec = color or COLORS["edge_color"]
        arrow = self._arrow_fragment(dashed)
        return (
            f"html=1;strokeColor={ec};strokeWidth=1.5;{arrow}"
            f"fontFamily=Oracle Sans;fontSize=12;"
            f"fontColor={COLORS['text_primary']};rounded=1;"
            f"jettySize=auto;orthogonalLoop=1;"
            f"{style_extra}"
        )

    def add_edge(self, source, target, label="", parent="1",
                 dashed=False, color=None, style_extra="",
                 exit_x=None, exit_y=None, entry_x=None, entry_y=None,
                 waypoints=None, orthogonal=None):
        """Add an edge between two cells. Returns cell ID.

        By default (no ports, no waypoints) edges use draw.io's orthogonal
        router with no fixed connection points. Passing any of
        exit_x/exit_y/entry_x/entry_y or waypoints switches to legacy pinned
        mode (fixed side/point, router disabled) for backward compatibility
        with older diagram scripts. Pass orthogonal=True together with ports
        to pin the sides while still using the orthogonal router; pass
        orthogonal=False to force legacy mode even without ports/waypoints.
        """
        cid = self._next_id()
        ec = color or COLORS["edge_color"]
        arrow = self._arrow_fragment(dashed)

        ports_given = any(p is not None for p in (exit_x, exit_y, entry_x, entry_y))
        if orthogonal is None:
            use_orthogonal = not (ports_given or bool(waypoints))
        else:
            use_orthogonal = orthogonal

        if not use_orthogonal:
            exit_x = 0.5 if exit_x is None else exit_x
            exit_y = 1.0 if exit_y is None else exit_y
            entry_x = 0.5 if entry_x is None else entry_x
            entry_y = 0.0 if entry_y is None else entry_y
            style = self._edge_style(color, dashed, style_extra)
            style += (
                f"exitX={exit_x};exitY={exit_y};exitDx=0;exitDy=0;"
                f"entryX={entry_x};entryY={entry_y};entryDx=0;entryDy=0;"
            )
        else:
            # Validate modern-mode pins: both coordinates must be provided or neither
            if (exit_x is not None) != (exit_y is not None):
                raise ValueError("exit_x and exit_y must be passed together")
            if (entry_x is not None) != (entry_y is not None):
                raise ValueError("entry_x and entry_y must be passed together")

            style = (
                f"edgeStyle=orthogonalEdgeStyle;rounded=1;jettySize=auto;orthogonalLoop=1;"
                f"html=1;strokeColor={ec};strokeWidth=1.5;{arrow}"
                f"fontFamily=Oracle Sans;fontSize=12;fontColor={COLORS['text_primary']};"
                f"{style_extra}"
            )
            if exit_x is not None and exit_y is not None:
                style += f"exitX={exit_x};exitY={exit_y};exitDx=0;exitDy=0;"
            if entry_x is not None and entry_y is not None:
                style += f"entryX={entry_x};entryY={entry_y};entryDx=0;entryDy=0;"

        cell = ET.SubElement(
            self.root, "mxCell", id=cid, value=label, style=style,
            edge="1", parent=parent, source=source, target=target,
        )
        geom = ET.SubElement(cell, "mxGeometry", relative="1")
        geom.set("as", "geometry")
        if waypoints:
            arr = ET.SubElement(geom, "Array")
            arr.set("as", "points")
            for wx, wy in waypoints:
                ET.SubElement(arr, "mxPoint", x=str(wx), y=str(wy))
        return cid

    def write(self, path: Path):
        """Write the draw.io XML to disk."""
        tree = ET.ElementTree(self.mxfile)
        ET.indent(tree, space="  ")
        path.parent.mkdir(parents=True, exist_ok=True)
        tree.write(str(path), encoding="utf-8", xml_declaration=True)
        print(f"Wrote {path} ({path.stat().st_size:,} bytes)")
