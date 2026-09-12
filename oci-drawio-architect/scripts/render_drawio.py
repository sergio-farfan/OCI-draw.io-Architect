#!/usr/bin/env python3
"""Export a .drawio file to PNG/SVG/PDF with the draw.io desktop CLI.

Thin wrapper around ``drawio_builder.render()``. Useful as a visual smoke
test after generating a diagram: open the PNG (or let Claude read it) and
check routing, labels and spacing before handing the file over.

Usage:
    python3 render_drawio.py <file.drawio> [-f png|svg|pdf] [-o OUT] [-s SCALE]

Exit codes:
    0 - exported (path printed)
    1 - export failed
    3 - no draw.io desktop binary found (set DRAWIO_BIN to override)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from drawio_builder import find_drawio_binary, render  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file", metavar="file.drawio")
    ap.add_argument("-f", "--format", default="png", choices=("png", "svg", "pdf", "jpg"))
    ap.add_argument("-o", "--out", default=None, help="output path (default: alongside the input)")
    ap.add_argument("-s", "--scale", type=float, default=1.0, help="raster scale (png/jpg)")
    args = ap.parse_args(argv)

    if find_drawio_binary() is None:
        print("draw.io desktop not found (looked on PATH, /Applications, /opt, snap; "
              "set DRAWIO_BIN=/path/to/drawio to override). Skipping render.", file=sys.stderr)
        return 3
    try:
        out = render(args.file, fmt=args.format, out=args.out, scale=args.scale)
    except Exception as exc:  # noqa: BLE001
        print(f"Render failed: {exc}", file=sys.stderr)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
