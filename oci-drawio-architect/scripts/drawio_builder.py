"""Reusable draw.io builder for OCI architecture diagrams.

Provides the DrawioBuilder class, OCI SVG icon loading with viewBox fix,
Oracle template container styles, and PNG-in-SVG logo embedding.

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
        d.write(Path("output.drawio"))
"""

import base64
import os
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
    "region_fill": "#F5F4F2",
    "region_stroke": "#9E9892",
    "vcn_stroke": "#AE562C",       # oracle orange for VCN/subnet borders
    "vcn_label": "#AE562C",        # same orange for VCN/subnet labels
    "text_primary": "#312D2A",     # charcoal for region/general text
    "edge_color": "#312D2A",
    "edge_accent": "#AE562C",      # orange for accent edges
    "edge_purple": "#7B61FF",
}

ICON_W = 75
ICON_H = 95
LABEL_GAP = 2

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


# Cache: icon_key -> URL-encoded SVG data URI
_svg_cache: dict[str, str] = {}


def _load_svg(icon_key: str) -> str:
    """Load an SVG, fix viewBox to fit all content, return URL-encoded data URI.

    OCI SVGs sometimes have content that extends beyond the declared viewBox
    (translate offsets + scaled paths exceed the width/height). We compute the
    actual content bounds from the transform attributes and expand the viewBox.
    """
    if icon_key in _svg_cache:
        return _svg_cache[icon_key]

    import re
    import urllib.parse

    svg_path = OCI_SVG_DIR / ICON_MAP[icon_key]
    svg_text = svg_path.read_text()

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

    encoded = urllib.parse.quote(svg_text, safe='')
    data_uri = f"data:image/svg+xml,{encoded}"
    _svg_cache[icon_key] = data_uri
    return data_uri


# ---------------------------------------------------------------------------
# Group style templates (from Oracle draw.io templates)
# ---------------------------------------------------------------------------
_GROUP_STYLES = {
    "region": (
        "whiteSpace=wrap;html=1;rounded=1;arcSize=1;"
        "fillColor={region_fill};strokeColor={region_stroke};"
        "fontFamily=Oracle Sans;fontSize=12;fontStyle=1;"
        "fontColor={text_primary};verticalAlign=top;align=left;"
        "spacingLeft=3;spacingRight=5;container=1;collapsible=0;expand=0;"
    ),
    "compartment": (
        "whiteSpace=wrap;html=1;rounded=1;arcSize=1;"
        "fillColor={region_fill};strokeColor={region_stroke};"
        "fontFamily=Oracle Sans;fontSize=12;fontStyle=1;"
        "fontColor={text_primary};verticalAlign=top;align=left;"
        "spacingLeft=3;container=1;collapsible=0;expand=0;"
    ),
    "vcn": (
        "whiteSpace=wrap;html=1;rounded=0;"
        "strokeWidth=2;dashed=1;"
        "fillColor=none;strokeColor={vcn_stroke};"
        "labelBackgroundColor=none;"
        "fontFamily=Oracle Sans;fontSize=13;fontStyle=1;"
        "fontColor={vcn_label};verticalAlign=top;align=left;"
        "spacingLeft=3;container=1;collapsible=0;expand=0;"
    ),
    "subnet": (
        "whiteSpace=wrap;html=1;rounded=0;"
        "strokeWidth=1;dashed=1;"
        "fillColor=none;strokeColor={vcn_stroke};"
        "fontFamily=Oracle Sans;fontSize=11;fontStyle=1;"
        "fontColor={vcn_label};verticalAlign=top;align=left;"
        "spacingLeft=3;container=1;collapsible=0;expand=0;"
    ),
    "services": (
        "whiteSpace=wrap;html=1;rounded=0;"
        "strokeWidth=1;dashed=1;"
        "fillColor=none;strokeColor={text_primary};"
        "fontFamily=Oracle Sans;fontSize=11;fontStyle=1;"
        "fontColor={text_primary};verticalAlign=top;align=left;"
        "spacingLeft=3;container=1;collapsible=0;expand=0;"
    ),
    "hub": (
        "whiteSpace=wrap;html=1;rounded=1;arcSize=1;"
        "fillColor={region_fill};strokeColor={region_stroke};"
        "fontFamily=Oracle Sans;fontSize=12;fontStyle=1;"
        "fontColor={text_primary};verticalAlign=top;align=left;"
        "spacingLeft=3;container=1;collapsible=0;expand=0;"
    ),
}


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
        self.mxfile = ET.Element("mxfile", host="Python", type="device")
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

    def add_group(self, label, x, y, w, h, parent="1", group_type="region"):
        """Add a container rectangle. Returns cell ID."""
        cid = self._next_id()
        style = _GROUP_STYLES[group_type].format(**COLORS)
        cell = ET.SubElement(
            self.root, "mxCell", id=cid, value=label, style=style,
            vertex="1", parent=parent,
        )
        ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y),
                       width=str(w), height=str(h)).set("as", "geometry")
        return cid

    def add_icon(self, label, icon_key, x, y, parent="1",
                 w=ICON_W, h=ICON_H):
        """Add an OCI SVG icon with a label below. Returns cell ID."""
        cid = self._next_id()
        data_uri = _load_svg(icon_key)
        style = (
            f"shape=image;verticalLabelPosition=bottom;verticalAlign=top;"
            f"imageAspect=0;aspect=fixed;"
            f"image={data_uri};"
        )
        cell = ET.SubElement(
            self.root, "mxCell", id=cid, value="", style=style,
            vertex="1", parent=parent,
        )
        ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y),
                       width=str(w), height=str(h)).set("as", "geometry")

        # Text label below
        lid = self._next_id()
        label_style = (
            "text;html=1;strokeColor=none;fillColor=none;align=center;"
            "verticalAlign=top;whiteSpace=wrap;rounded=0;"
            f"fontFamily=Oracle Sans;fontSize=11;fontStyle=0;"
            f"fontColor={COLORS['text_primary']};"
        )
        lc = ET.SubElement(
            self.root, "mxCell", id=lid, value=label, style=label_style,
            vertex="1", parent=parent,
        )
        ET.SubElement(lc, "mxGeometry",
                       x=str(x - 15), y=str(y + h + LABEL_GAP),
                       width=str(w + 30), height=str(45)).set("as", "geometry")
        return cid

    def add_image(self, image_path, x, y, w, h, parent="1"):
        """Add a PNG/image as a URL-encoded SVG wrapper (draw.io ignores base64)."""
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

        # Wrap PNG in an SVG so we can URL-encode it (draw.io renders URL-encoded SVGs)
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

    def _edge_style(self, color, dashed, style_extra):
        ec = color or COLORS["edge_color"]
        if dashed:
            arrow = "dashed=1;dashPattern=6 3;endArrow=none;endFill=0;"
        else:
            arrow = "dashed=0;endArrow=open;endFill=0;"
        return (
            f"html=1;strokeColor={ec};strokeWidth=1.5;{arrow}"
            f"fontFamily=Oracle Sans;fontSize=12;"
            f"fontColor={COLORS['text_primary']};rounded=1;"
            f"jettySize=auto;orthogonalLoop=1;"
            f"{style_extra}"
        )

    def add_edge(self, source, target, label="", parent="1",
                 dashed=False, color=None, style_extra="",
                 exit_x=0.5, exit_y=1.0, entry_x=0.5, entry_y=0.0,
                 waypoints=None):
        """Add an edge with explicit ports and optional waypoints."""
        cid = self._next_id()
        style = self._edge_style(color, dashed, style_extra)
        style += (
            f"exitX={exit_x};exitY={exit_y};exitDx=0;exitDy=0;"
            f"entryX={entry_x};entryY={entry_y};entryDx=0;entryDy=0;"
        )
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
