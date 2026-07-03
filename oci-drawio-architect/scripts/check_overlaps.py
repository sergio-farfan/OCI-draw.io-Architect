#!/usr/bin/env python3
"""Validate a .drawio file for overlapping containers.

Standalone CLI wrapper around find_container_overlaps() from the sibling
drawio_builder.py. Run this after generating a diagram to catch overlapping
sibling containers (regions/VCNs/subnets/etc.) before opening the file in
draw.io. Intended as a mandatory post-generation gate.

Usage:
    python3 check_overlaps.py <file.drawio>

Exit codes:
    0 - no overlaps found
    1 - one or more overlapping container pairs found
    2 - usage error, missing/unreadable file, unparsable XML, or
        unsupported (compressed) diagram content
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from drawio_builder import find_container_overlaps
except ImportError:
    print(
        "check_overlaps.py must live next to drawio_builder.py (plugin scripts "
        "directory), or copy drawio_builder.py alongside it.",
        file=sys.stderr,
    )
    sys.exit(2)


def _fmt_num(value: float) -> str:
    """Render a float as a plain int string when it's a whole number."""
    return str(int(value)) if float(value).is_integer() else str(value)


def _build_cell_registry(root) -> dict:
    """Map cell id -> {value, style, parent, vertex, x, y, w, h}.

    Mirrors the registry drawio_builder.find_container_overlaps() builds
    internally, so the WARNING pass below can reuse the same shape.
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


def _registered_containers(registry: dict) -> set:
    return {
        cid for cid, e in registry.items()
        if e["vertex"] == "1" and "container=1" in e["style"]
    }


def _find_nested_container_warnings(root) -> list:
    """Vertices with container=1 that spill outside their parent container.

    A vertex's geometry is already expressed relative to its immediate
    parent's origin, so containment can be checked in that local frame
    without walking the full absolute-coordinate ancestor chain: converting
    both sides to absolute page coordinates would add the same ancestor
    offset to the child and the parent alike, so it cancels out of the
    comparison. Only checked when the parent is itself a registered
    container (top-level containers whose parent is the default layer are
    skipped).
    """
    registry = _build_cell_registry(root)
    containers = _registered_containers(registry)
    warnings = []
    for cid in containers:
        entry = registry[cid]
        parent = entry["parent"]
        if parent not in containers:
            continue
        p = registry[parent]
        if (entry["x"] < 0 or entry["y"] < 0
                or entry["x"] + entry["w"] > p["w"]
                or entry["y"] + entry["h"] > p["h"]):
            warnings.append(
                "WARNING: '{}' [x={},y={},w={},h={}] is not fully inside "
                "parent container '{}' [w={},h={}]".format(
                    entry["value"], _fmt_num(entry["x"]), _fmt_num(entry["y"]),
                    _fmt_num(entry["w"]), _fmt_num(entry["h"]),
                    p["value"], _fmt_num(p["w"]), _fmt_num(p["h"]),
                )
            )
    return warnings


def _count_containers(root) -> int:
    return len(_registered_containers(_build_cell_registry(root)))


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 check_overlaps.py <file.drawio>", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"Cannot read '{path}': {exc}", file=sys.stderr)
        return 2

    try:
        mxfile = ET.fromstring(text)
    except ET.ParseError as exc:
        print(f"Failed to parse '{path}' as XML: {exc}", file=sys.stderr)
        return 2

    diagrams = mxfile.findall("diagram")
    multi_page = len(diagrams) > 1

    all_overlaps = []
    all_warnings = []
    total_containers = 0

    for diagram in diagrams:
        name = diagram.get("name") or diagram.get("id", "")
        model = diagram.find("mxGraphModel")
        if model is None:
            if (diagram.text or "").strip():
                print(
                    'compressed .drawio content is not supported; regenerate '
                    'with DrawioBuilder v1.1.0+ (writes compressed="false")',
                    file=sys.stderr,
                )
                return 2
            continue

        root = model.find("root")
        if root is None:
            continue

        overlaps = find_container_overlaps(root)
        warnings = _find_nested_container_warnings(root)
        total_containers += _count_containers(root)

        prefix = f"[page: {name}] " if multi_page else ""
        all_overlaps.extend(prefix + msg for msg in overlaps)
        all_warnings.extend(prefix + msg for msg in warnings)

    for msg in all_overlaps:
        print(msg)
    for msg in all_warnings:
        print(msg)

    if all_overlaps:
        print(f"FAIL: {len(all_overlaps)} overlapping pair(s).")
        return 1

    print(
        f"OK: no container overlaps ({total_containers} containers checked "
        f"across {len(diagrams)} page(s))."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
