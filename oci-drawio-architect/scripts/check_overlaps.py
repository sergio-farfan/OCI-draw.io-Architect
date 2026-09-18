#!/usr/bin/env python3
"""Validate a .drawio file: overlaps, containment, references, captions, crossings.

Standalone CLI around ``drawio_builder.validate_file()``. Run it after
generating a diagram; it is the mandatory gate in the /drawio-architect
workflow. Compressed pages are inflated transparently, ``<object>`` and
``<UserObject>`` wrappers are understood, and every page is checked.

Checks (ERROR = exit 1):
  - cells whose parent id does not exist, edges whose source/target is missing
  - any two containers (not just siblings) whose boxes intersect
  - any shape extending outside its parent container
  - icons, captions or boxes lying inside a VCN / subnet they do not belong to; a DRG inside any VCN
  - icons / captions / text cells overlapping each other
    (badges - style ociRole=badge - may straddle their subnet's corner and cover their own host icon)
Checks (WARNING = exit 0 unless --strict):
  - captions that need more lines than their box provides
  - connectors estimated to cross icons or captions that are not endpoints
  - pages without content

Usage:
    python3 check_overlaps.py [--strict] [--quiet] <file.drawio> [more files...]

Exit codes:
    0 - clean (warnings may have been printed unless --strict)
    1 - one or more errors (or warnings with --strict)
    2 - usage error, missing/unreadable file, unparsable XML or a missing
        sibling drawio_builder.py (ImportError)
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from drawio_builder import __version__, validate_file
except ImportError as exc:
    print(
        "check_overlaps.py must live next to drawio_builder.py (plugin scripts "
        f"directory), or copy drawio_builder.py alongside it. ({exc})",
        file=sys.stderr,
    )
    sys.exit(2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="+", metavar="file.drawio")
    ap.add_argument("--strict", action="store_true",
                    help="treat warnings (e.g. estimated edge crossings) as errors")
    ap.add_argument("--quiet", action="store_true", help="print only the summary lines")
    ap.add_argument("--version", action="version", version=f"drawio_builder {__version__}")
    args = ap.parse_args(argv)

    worst = 0
    for name in args.files:
        path = Path(name)
        try:
            errors, warnings, pages, containers = validate_file(path, strict=args.strict)
        except (OSError, UnicodeDecodeError) as exc:
            print(f"Cannot read '{path}': {exc}", file=sys.stderr)
            return 2
        except ET.ParseError as exc:
            print(f"Failed to parse '{path}' as XML: {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"'{path}': {exc}", file=sys.stderr)
            return 2

        if not args.quiet:
            for msg in errors:
                print(msg)
            for msg in warnings:
                print(msg)
        label = f"{path}: " if len(args.files) > 1 else ""
        if errors:
            print(f"{label}FAIL: {len(errors)} error(s), {len(warnings)} warning(s) "
                  f"({containers} containers across {pages} page(s)).")
            worst = max(worst, 1)
        else:
            extra = f", {len(warnings)} warning(s)" if warnings else ""
            print(f"{label}OK: no container overlaps or layout errors "
                  f"({containers} containers checked across {pages} page(s){extra}).")
    return worst


if __name__ == "__main__":
    sys.exit(main())
