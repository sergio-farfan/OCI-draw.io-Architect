---
name: oci-drawio-architect
description: Use when generating draw.io diagrams for OCI architectures, creating OCI architecture diagrams programmatically, or when the user says "draw.io OCI", "diagram this architecture", or "drawio with OCI icons"
---

# OCI draw.io Architecture Diagrams

Generate production-quality draw.io diagrams for Oracle Cloud Infrastructure using Python, embedded OCI SVG icons, and Oracle template styles.

## Overview

This skill provides a battle-tested `DrawioBuilder` Python class that produces `.drawio` XML files with:
- Embedded OCI SVG icons (URL-encoded, single-cell, clean rendering)
- Oracle template container styles (Region, VCN, Subnet, Services, On-Premises)
- PNG logo embedding via SVG wrapper trick
- Orthogonal-router edges by default, with explicit ports/waypoints available for tight control

**Core principle:** Copy `drawio_builder.py` into your script, write a `build_diagram()` function that places containers/icons on a grid, then let the orthogonal router connect them — explicit ports/waypoints only where tight control is needed.

**DrawioBuilder script location:** `${CLAUDE_PLUGIN_ROOT}/scripts/drawio_builder.py`

## When to Use

- Generating a draw.io diagram for any OCI architecture
- Visualizing VCN topology, subnets, and service placement
- Creating architecture diagrams from Terraform configurations
- Producing professional OCI diagrams matching Oracle template style

**When NOT to use:**
- Non-OCI diagrams (use draw.io manually or other tools)
- Simple flowcharts or sequence diagrams (use Mermaid or PlantUML)

## 5-Phase Workflow

### Phase 1: Understand the Architecture

Read Terraform configs or documentation to identify:
- VCNs, subnets, CIDRs
- Services deployed (compute, databases, LB, functions, etc.)
- Network topology (DRG, VPN, gateways)
- Compartment hierarchy

**Input sources:** `VCN.auto.tfvars`, `DRG.auto.tfvars`, `main.tf`, service `.tf` files

### Phase 2: Plan the Layout

Design the container hierarchy and grid before writing code:

```
Region
  +-- Hub (left side, narrow)
  |     +-- Firewall / DRG
  +-- VCN (right side, wide)
        +-- Subnet 1 (icons in rows)
        +-- Subnet 2
        +-- Services panel
        +-- Gateways (bottom)
```

**Grid constants** (adjust per diagram):
```python
R1 = 50        # first icon row y (below container title)
R2 = 210       # second icon row y
COL = 130      # column gap between icons
SN_H = 380     # subnet height for 2 rows of icons
GAP = 30       # gap between sibling containers
ICON_W = 75    # nominal slot width (actual cell width derived from the SVG's aspect)
ICON_H = 95    # fixed icon cell height
```

**Page dimensions:** Calculate from content. Typical: 1600x1100 for single-VCN, 2400x1400 for multi-VCN.

### Phase 2b: Verify No Container Overlaps (MANDATORY)

Before writing any code, compute bounding boxes for every sibling container and verify no overlaps exist. This is the #1 source of visual bugs.

**The Rule:** For each row of containers, `row_start_y = max(bottom_of_all_containers_above) + gap`. Never hardcode row positions - always derive from computed bottoms.

**Step-by-step:**

1. **Compute row bottoms explicitly** in comments at the top of `build_diagram()`:
```python
# Row 1:  y=50,  heights: [380, 230, 230] -> bottoms: [430, 280, 280]
# Row 1.5: y=300, height: 230 -> bottom: 530
# Row 2 must start at: max(430, 530) + 20(gap) = 550
ROW2_Y = max(ROW1_BOTTOM, CPLB_BOTTOM) + GAP
```

2. **Use named variables** for row positions (`ROW1_Y`, `ROW2_Y`, `GW_Y`), not magic numbers. Each variable is derived from the previous row's computed bottom + a gap constant.

3. **Account for icon label overflow**: Each icon occupies `ICON_H(95) + LABEL_GAP(2) + label_h(45) = 142px` vertically. A container with 2 icon rows needs at least `R2(210) + 142 = 352px` height (380 SN_H provides 28px padding).

4. **Use the shipped overlap checker** - don't hand-roll one:
   - In the generated script, call `d.check_overlaps()` before `d.write()` and abort on any findings:
     ```python
     problems = d.check_overlaps()
     if problems:
         for p in problems:
             print(p)
         raise SystemExit(1)
     d.write(Path("output.drawio"))
     ```
   - After generation, also run the standalone CLI gate:
     ```bash
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_overlaps.py" <output>.drawio
     ```
     Exit `0` is clean. Exit code `1` means overlaps were found - fix the layout math (see the row-derivation rule above) and regenerate. Exit code `2` means a usage/parse/compressed/import error (missing or unreadable file, unparsable XML, unsupported compressed diagram content, or a missing sibling `drawio_builder.py`) - diagnose the setup rather than the layout.

**Common overlap traps:**
- Containers of **different heights** in the same visual row - the tallest one's bottom sets the next row's y
- **Staggered containers** (e.g., OKE-CP-LB at y=300 below OKE-Worker-LB at y=50) - their bottom may exceed the main row's bottom
- **Service panels** with 3+ icon rows being taller than adjacent 2-row subnets

### Phase 3: Generate the Script

1. **Copy** `${CLAUDE_PLUGIN_ROOT}/scripts/drawio_builder.py` into your working directory
2. **Create** a new script (e.g., `generate_my_diagram.py`)
3. **Import** and build:

```python
from pathlib import Path
from drawio_builder import DrawioBuilder, add_icons_to_map, COLORS

# Add any icons not in the default ICON_MAP
add_icons_to_map({
    "oke": "developer_services/developer_services_container_engine_for_kubernetes.svg",
    "bastion": "identity_and_security/identity_and_security_bastion.svg",
})

def build_diagram():
    d = DrawioBuilder(page_name="My Architecture", width=1600, height=1100)

    # Title
    d.add_text(
        "<b>My Architecture</b><br/><i>Frankfurt (eu-frankfurt-1)</i>",
        x=20, y=8, w=600, h=55, font_size=18, font_style=1,
        font_family="Georgia",
    )

    # Logos (optional)
    LOGO_DIR = Path("logos")
    d.add_image(LOGO_DIR / "company_logo_dark.png",
                x=1450, y=8, w=148, h=39)

    # Region container
    region = d.add_group("eu-frankfurt-1", x=20, y=75, w=1560, h=1000,
                         group_type="region")

    # VCN container (inside region)
    vcn = d.add_group("VCN: MyVCN (10.0.0.0/16)", x=20, y=40, w=1500, h=900,
                       parent=region, group_type="vcn")

    # Subnet (inside VCN)
    sn = d.add_group("sn-app (10.0.1.0/24)", x=20, y=50, w=400, h=380,
                      parent=vcn, group_type="subnet")

    # Icons (inside subnet)
    lb = d.add_icon("Load Balancer", "load_balancer", x=20, y=50, parent=sn)
    vm = d.add_icon("App VM", "vm", x=150, y=50, parent=sn)

    # Icon with metadata + tooltip (survives round-trips through draw.io)
    db = d.add_icon("Autonomous Database", "autonomous_db", x=280, y=50, parent=sn,
                     metadata={"ocid": "ocid1.autonomousdatabase.oc1..example"},
                     tooltip="Primary OLTP database")

    # Edges - modern port-less form; the orthogonal router picks the path
    d.add_edge(lb, vm, "443", parent=sn)

    # Mandatory overlap gate before writing
    problems = d.check_overlaps()
    if problems:
        for p in problems:
            print(p)
        raise SystemExit(1)

    d.write(Path("output.drawio"))

if __name__ == "__main__":
    build_diagram()
```

### Phase 4: Route Edges

`add_edge` defaults to draw.io's orthogonal router (`edgeStyle=orthogonalEdgeStyle`) with no fixed connection points - draw.io picks the path. Key rules:

- **Same container:** Just call `d.add_edge(source, target, label, parent=container)` - no ports, no waypoints needed.
- **Cross-container:** Still set `parent` to the common ancestor of the two endpoints, even in the default (no-ports) mode.
- **Tight control:** Passing any of `exit_x`/`exit_y`/`entry_x`/`entry_y` or `waypoints` switches that edge to legacy pinned mode (fixed side/point, router disabled - the v1.0.0 behavior). Use this when you need to route around obstacles or dock at a specific side.
- **Router + docked endpoints:** Pass `orthogonal=True` together with full exit/entry pins to keep the orthogonal router active while still pinning the connection sides.
- **Force legacy mode without ports:** Pass `orthogonal=False` to use legacy pinned mode even when no ports/waypoints are given (falls back to the default port positions: exit bottom-center, entry top-center).
- **Parallel routes (legacy mode only):** Offset by ~8px to prevent overlap.

```python
# Default: modern, port-less, same-container
d.add_edge(lb, vm, "443", parent=sn)

# Cross-container, still port-less: parent is the common ancestor
d.add_edge(drg, lb, "", parent=region)

# Tight control: any port or waypoint switches to legacy pinned mode
d.add_edge(drg, lb, "", parent=region,
           exit_x=1.0, exit_y=0.5, entry_x=0.0, entry_y=0.5,
           waypoints=[(gap_x, drg_y), (gap_x, lb_y)])
```

**Exit/entry port reference** (legacy pinned mode, or `orthogonal=True` with full pins):
| Position | exitX/entryX | exitY/entryY |
|----------|-------------|-------------|
| Top | 0.5 | 0.0 |
| Bottom | 0.5 | 1.0 |
| Left | 0.0 | 0.5 |
| Right | 1.0 | 0.5 |

**Semantics:** solid = data flow, dashed (`dashed=True`) = user interaction. This is the official Oracle toolkit convention - don't invert it.

### Phase 5: Finalize

1. Add logos via `d.add_image()` (PNG files, resized automatically)
2. Add title text via `d.add_text()` (Georgia for titles, Oracle Sans for labels)
3. Call `d.write(Path("output.drawio"))` to generate the file
4. Open in draw.io desktop to verify rendering
5. If fonts look wrong, close and reopen the file (draw.io caches renders)

## Quick Reference

### Container Types

11 group types are defined in `_GROUP_STYLES`:

| Type | Border | Fill | Font Color | Use For |
|------|--------|------|------------|---------|
| `region` | `#9E9892` solid, rounded | `#F5F4F2` | `#312D2A` bold | OCI region |
| `tenancy` | `#9E9892` dashed 1px, square | none | `#312D2A` bold | Tenancy boundary |
| `availability_domain` | `#9E9892` solid, rounded | `#DFDCD8` | `#312D2A` bold | Availability Domain |
| `fault_domain` | `#9E9892` solid, rounded | `#FCFBFA` | `#312D2A` bold | Fault Domain |
| `compartment` | `#AE562C` dotted 1px, square | none | `#312D2A` bold | Compartment |
| `vcn` | `#AE562C` dashed 2px, square | none | `#AE562C` bold | VCN |
| `subnet` | `#AE562C` dashed 1px, square | none | `#AE562C` bold | Subnet |
| `services` | `#9E9892` dashed 2px, square | none | `#312D2A` bold | OCI services panel |
| `oracle_services_network` | `#A36472` dashed 2px, square | none | `#A36472` bold | Oracle Services Network |
| `onprem` | `#9E9892` solid, rounded | `#F5F4F2` | `#312D2A` bold | On-premises / hub network |
| `hub` | *(deprecated alias of `onprem`)* | | | Use `onprem` in new diagrams |

### DrawioBuilder API

| Method | Returns | Description |
|--------|---------|-------------|
| `add_group(label, x, y, w, h, parent, group_type, metadata=None, tooltip=None)` | cell ID | Container rectangle |
| `add_icon(label, icon_key, x, y, parent, w=None, h=None, metadata=None, tooltip=None)` | cell ID | OCI SVG icon + text label; derived aspect-correct sizing when w/h omitted |
| `add_image(path, x, y, w, h, parent)` | cell ID | PNG/image (logo embedding) |
| `add_text(label, x, y, w, h, parent, ...)` | cell ID | Text-only label |
| `add_edge(src, tgt, label, parent, dashed, color, ..., orthogonal=None)` | cell ID | Edge; port-less orthogonal router by default, legacy pinned mode when ports/waypoints are passed, or forced either way via `orthogonal=True`/`orthogonal=False` |
| `check_overlaps()` | list of `"OVERLAP: ..."` strings | Sibling-container overlap check; call before `write()` |
| `write(path)` | None | Write .drawio XML to disk |

### Helper Functions

| Function | Description |
|----------|-------------|
| `add_icons_to_map({"key": "category/file.svg"})` | Add icons to global ICON_MAP |
| `find_container_overlaps(root)` | Module-level function `check_overlaps()` delegates to; takes an `mxGraphModel` `<root>` Element, returns the same overlap-message list |

## Key References

- **Full style details:** `${CLAUDE_PLUGIN_ROOT}/skills/oci-drawio-architect/references/oracle-styles.md`
- **All available icons:** `${CLAUDE_PLUGIN_ROOT}/skills/oci-drawio-architect/references/icon-catalog.md` (~160 icons across 14 categories)
- **Common pitfalls:** `${CLAUDE_PLUGIN_ROOT}/skills/oci-drawio-architect/references/gotchas.md` (12 issues)
- **OCI SVG icons:** Bundled at `${CLAUDE_PLUGIN_ROOT}/icons/` (override with `OCI_SVG_DIR` env var)
- **Working example:** `${CLAUDE_PLUGIN_ROOT}/examples/generate_demo_diagram.py` (exercises every container type, the main icon-sizing and edge modes, metadata, and the overlap gate)
- **Overlap checker CLI:** `${CLAUDE_PLUGIN_ROOT}/scripts/check_overlaps.py`

## Common Mistakes

1. **Using a raw base64 data URI** - `image=data:image/png;base64,iVBOR...` gets truncated at the `;base64,` marker because draw.io/mxGraph splits cell styles on `;`. Always URL-encode instead: `image=data:image/svg+xml,{urllib.parse.quote(svg, safe='')}`.
2. **Missing `container=1`** - Children render at root level if parent lacks `container=1`. All `_GROUP_STYLES` include it, but custom styles must too.
3. **Wrong edge parent** - Cross-container edges must use a common ancestor as parent. Icons in different containers cannot share an edge parented to either container.
4. **Forgetting viewBox fix** - OCI SVGs clip without the transform-based viewBox expansion. Use `_load_svg()` which handles this automatically.
5. **Hardcoded cell IDs** - Always use `_next_id()`. Duplicate IDs cause silent rendering failures.
6. **Don't stretch icons** - default derived sizing preserves aspect; pass explicit `w`/`h` only for wide logical/physical connector shapes.
