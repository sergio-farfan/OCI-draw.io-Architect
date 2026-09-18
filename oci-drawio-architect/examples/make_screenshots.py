#!/usr/bin/env python3
"""Regenerate the README screenshots from the reference layout example.

Renders examples/generate_reference_layout.py with the draw.io desktop CLI and
crops it into the four images the docs use:

    screenshots/diagram-overview.png   full diagram (1.25x)
    screenshots/diagram-detail.png     data subnet + border gateways (1.5x)
    Screens/1.png                      top-left 1138x693 window-like crop (1.25x)
    Screens/2.png                      same as diagram-detail.png

Cropping uses Pillow when installed, otherwise macOS `sips`.

Usage:
    python3 make_screenshots.py [repo_root]   # default: the repository containing this plugin
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))
from drawio_builder import find_drawio_binary, is_warning  # noqa: E402
from generate_reference_layout import MODEL  # noqa: E402
from oci_layout import build_diagram  # noqa: E402

BORDER = 10


def _export(binary: str, src: Path, out: Path, scale: float) -> Path:
    cmd = [binary, "-x", "-f", "png", "-s", str(scale), "-b", str(BORDER), "-o", str(out), str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0 or not out.exists():
        raise SystemExit(f"draw.io export failed: {proc.stderr.strip()[-300:]}")
    return out


def _size(path: Path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except ImportError:
        out = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
                             capture_output=True, text=True, check=True).stdout
        vals = [int(line.split()[-1]) for line in out.splitlines() if "pixel" in line]
        return vals[0], vals[1]


def _crop(src: Path, box, out: Path) -> None:
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    w, h = _size(src)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    try:
        from PIL import Image
        with Image.open(src) as im:
            im.crop((x0, y0, x1, y1)).save(out, optimize=True)
        return
    except ImportError:
        pass
    # sips treats a 0 offset as "centre", so keep offsets >= 1
    subprocess.run(["sips", "-c", str(y1 - y0), str(x1 - x0), "--cropOffset", str(max(1, y0)), str(max(1, x0)),
                    str(src), "--out", str(out)], check=True, capture_output=True)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    repo = Path(argv[0]).resolve() if argv else HERE.parent.parent
    binary = find_drawio_binary()
    if not binary:
        print("draw.io desktop not found; cannot render screenshots", file=sys.stderr)
        return 3

    d = build_diagram(MODEL)
    problems = d.validate()
    if any(not is_warning(p) for p in problems):
        raise SystemExit("\n".join(problems))
    cx0, cy0, _, _ = d.content_bbox()

    def px(x, y, scale):
        return (x - cx0) * scale + BORDER, (y - cy0) * scale + BORDER

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        drawio = d.write(tmp / "reference.drawio")
        full125 = _export(binary, drawio, tmp / "full_125.png", 1.25)
        full150 = _export(binary, drawio, tmp / "full_150.png", 1.5)

        sx, sy, sw, sh = d.abs_bbox("subnet-sn-priv-data")
        nx, ny, nw, nh = d._abs_footprint("nat")            # bottom-border gateway (caption hangs below the VCN)
        gx, gy, gw, gh = d._abs_footprint("sgw")            # right-border gateway
        x0, y0 = px(sx - 12, sy - 34, 1.5)
        x1, y1 = px(max(sx + sw + 35, gx + gw + 12), ny + nh + 12, 1.5)
        detail = tmp / "detail.png"
        _crop(full150, (x0, y0, x1, y1), detail)

        topleft = tmp / "topleft.png"
        _crop(full125, (0, 0, 1138, 693), topleft)

        targets = {
            repo / "screenshots" / "diagram-overview.png": full125,
            repo / "screenshots" / "diagram-detail.png": detail,
            repo / "Screens" / "1.png": topleft,
            repo / "Screens" / "2.png": detail,
        }
        for dst, src in targets.items():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            w, h = _size(dst)
            print(f"{dst.relative_to(repo)}: {w}x{h} ({dst.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
