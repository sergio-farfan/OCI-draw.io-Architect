# Oracle draw.io Template Styles

Styles extracted from Oracle's official OCI Architecture Diagram Toolkit v24.2 (docs.oracle.com > OCI Architecture Diagram Toolkits).

## Color Palette

Redwood diagram palette, as defined in `COLORS` in `drawio_builder.py`:

| Key | Hex | Official Name | Usage |
|-----|-----|----------------|-------|
| `region_fill` | `#F5F4F2` | Neutral 1 | Region / on-prem group fill |
| `region_stroke` | `#9E9892` | Neutral 3 | Location-group borders (region, tenancy, availability domain, fault domain), services-panel border |
| `neutral_2` | `#DFDCD8` | Neutral 2 | Availability Domain fill |
| `air` | `#FCFBFA` | Air | Fault Domain fill |
| `vcn_stroke` | `#AE562C` | Sienna | VCN / subnet / compartment borders |
| `vcn_label` | `#AE562C` | Sienna | VCN / subnet label text |
| `text_primary` | `#312D2A` | Bark | All text and all connectors |
| `rose` | `#A36472` | Rose | Oracle Services Network border + label |
| `ivy` | `#759C6C` | Ivy | OCI logical component border. Defined in `COLORS` but not currently wired into any `_GROUP_STYLES` entry - reserved for logical/physical shape icons |
| `oracle_red` | `#C74634` | Oracle Red / O-Red | On-premises **logical component** border only - never used for VCNs. Same "defined but not yet wired in" status as `ivy` |
| `edge_color` | `#312D2A` | Bark | Default/official connector color |
| `edge_accent` | `#AE562C` | *(not official)* | Legacy accent edges - kept for older script compatibility |
| `edge_purple` | `#7B61FF` | *(not official)* | Custom extension for special-purpose data flows |

`edge_accent` and `edge_purple` are **not** part of the official Oracle Redwood palette - they are project-specific extensions layered on top of it. Every other key above maps to an official Redwood color name.

## Container Styles

One entry per `_GROUP_STYLES` key in `drawio_builder.py`. Each value is a template string resolved with `.format(**COLORS)` inside `add_group()`.

### region
```
whiteSpace=wrap;html=1;rounded=1;arcSize=2;fillColor={region_fill};strokeColor={region_stroke};fontFamily=Oracle Sans;fontSize=11;fontStyle=1;fontColor={text_primary};verticalAlign=top;align=center;labelBackgroundColor=none;spacingRight=5;container=1;collapsible=0;expand=0;
```
Solid Neutral 3 border, Neutral 1 fill, rounded corners, bold centered label.

### tenancy
```
whiteSpace=wrap;html=1;rounded=0;strokeWidth=1;dashed=1;fillColor=none;strokeColor={region_stroke};fontFamily=Oracle Sans;fontSize=12;fontStyle=1;fontColor={text_primary};verticalAlign=top;align=left;spacingLeft=5;container=1;collapsible=0;expand=0;
```
Dashed Neutral 3 border, no fill, square corners, left-aligned label - the outermost tenancy boundary.

### availability_domain
```
whiteSpace=wrap;html=1;rounded=1;fillColor={neutral_2};strokeColor={region_stroke};fontFamily=Oracle Sans;fontSize=11;fontStyle=1;fontColor={text_primary};verticalAlign=top;align=center;container=1;collapsible=0;expand=0;
```
Solid Neutral 3 border, Neutral 2 fill, rounded corners.

### fault_domain
```
whiteSpace=wrap;html=1;rounded=1;fillColor={air};strokeColor={region_stroke};fontFamily=Oracle Sans;fontSize=11;fontStyle=1;fontColor={text_primary};verticalAlign=top;align=center;container=1;collapsible=0;expand=0;
```
Solid Neutral 3 border, Air fill, rounded corners - nests inside `availability_domain`.

### compartment
```
whiteSpace=wrap;html=1;rounded=0;strokeWidth=1;dashed=1;dashPattern=1 1;fillColor=none;strokeColor={vcn_stroke};fontFamily=Oracle Sans;fontSize=11;fontStyle=1;fontColor={text_primary};verticalAlign=top;align=center;spacingLeft=5;container=1;collapsible=0;expand=0;
```
Dotted (`dashPattern=1 1`) Sienna border per the official v24.2 toolkit, no fill. Note the label is **Bark** (`text_primary`), not Sienna - unlike VCN/subnet, whose labels match their border color.

### vcn
```
whiteSpace=wrap;html=1;rounded=0;strokeWidth=2;dashed=1;fillColor=none;strokeColor={vcn_stroke};labelBackgroundColor=none;fontFamily=Oracle Sans;fontSize=12;fontStyle=1;fontColor={vcn_label};verticalAlign=top;align=left;spacingLeft=5;container=1;collapsible=0;expand=0;
```
Dashed Sienna border (`strokeWidth=2`), no fill, Sienna label text.

### subnet
```
whiteSpace=wrap;html=1;rounded=0;strokeWidth=1;dashed=1;fillColor=none;strokeColor={vcn_stroke};fontFamily=Oracle Sans;fontSize=11;fontStyle=1;fontColor={vcn_label};verticalAlign=top;align=left;spacingLeft=5;container=1;collapsible=0;expand=0;
```
Same as `vcn` but thinner border (`strokeWidth=1`) and smaller font (11px).

### services
```
whiteSpace=wrap;html=1;rounded=0;strokeWidth=2;dashed=1;fillColor=none;strokeColor={region_stroke};fontFamily=Oracle Sans;fontSize=11;fontStyle=1;fontColor={text_primary};verticalAlign=top;align=left;spacingLeft=5;container=1;collapsible=0;expand=0;
```
Dashed Neutral 3 border (not Sienna) - visually distinguishes an OCI services panel from a subnet.

### oracle_services_network
```
whiteSpace=wrap;html=1;rounded=0;strokeWidth=2;dashed=1;fillColor=none;strokeColor={rose};fontFamily=Oracle Sans;fontSize=11;fontStyle=1;fontColor={rose};verticalAlign=top;align=left;spacingLeft=5;container=1;collapsible=0;expand=0;
```
Dashed Rose border and label. **Caveat:** the color (Rose) is official; the stroke weight/dash pattern is inferred from the `services` panel analog (identical `strokeWidth=2;dashed=1`) pending a future re-extraction from the toolkit.

### onprem
```
whiteSpace=wrap;html=1;rounded=1;arcSize=2;fillColor={region_fill};strokeColor={region_stroke};fontFamily=Oracle Sans;fontSize=11;fontStyle=1;fontColor={text_primary};verticalAlign=top;align=center;labelBackgroundColor=none;spacingRight=5;container=1;collapsible=0;expand=0;
```
Template-identical to `region` (solid Neutral 3 border, Neutral 1 fill, rounded corners) - used for on-premises / hub networks.

### hub (deprecated)
`_GROUP_STYLES["hub"] = _GROUP_STYLES["onprem"]` - `hub` is a **deprecated alias of `onprem`**, kept only so pre-1.1.0 scripts passing `group_type="hub"` keep working. Use `onprem` in new diagrams.

## Common Container Properties

All eleven group types share:
- `container=1;collapsible=0;expand=0;` - required for children to nest correctly; disables draw.io's collapse/expand UI
- `whiteSpace=wrap;html=1;` - enable HTML rendering and text wrapping
- `verticalAlign=top;` - label anchored at the top of the container
- `fontFamily=Oracle Sans;fontStyle=1;` - bold Oracle Sans labels

Two visual families:
- **Solid, filled, rounded:** `region`, `availability_domain`, `fault_domain`, `onprem` (+ `hub` alias) - Neutral/Air fill, Neutral 3 border, `align=center`.
- **Dashed, transparent, square-cornered:** `tenancy`, `compartment`, `vcn`, `subnet`, `services`, `oracle_services_network` - no fill, border color varies by type, `align=left` except `compartment`, which is `align=center`.

## Icon Cell Style

```
shape=image;verticalLabelPosition=bottom;verticalAlign=top;imageAspect=1;aspect=fixed;image={data_uri};
```

Sizing (from `add_icon()` in `drawio_builder.py`):
- `imageAspect=1` - preserve the SVG's native aspect ratio (v1.1.0; v1.0.0 used `imageAspect=0`, which stretched every icon into a fixed cell - see `gotchas.md` #12)
- Cell height is fixed at `ICON_H = 95`
- Cell width is derived from the SVG's actual (viewBox-corrected) native dimensions: `cell_w = round(ICON_H * native_w / native_h)`
- The cell is horizontally centered in the `ICON_W = 75` nominal slot: `cell_x = x + round((ICON_W - cell_w) / 2)`
- Passing explicit `w` and/or `h` to `add_icon()` overrides derived sizing (the omitted dimension is scaled to match the aspect ratio if only one of `w`/`h` is given)

The label is a **separate text cell** placed below the icon:
```
text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=top;whiteSpace=wrap;rounded=0;fontFamily=Oracle Sans;fontSize=11;fontStyle=0;fontColor={COLORS['text_primary']};
```
- `LABEL_W = 105`, `LABEL_H = 45`, `LABEL_GAP = 2` (vertical gap between the icon's bottom edge and the label's top edge)
- Label width is `max(cell_w + 30, LABEL_W)`, horizontally centered under the icon cell
- `fontColor` resolves to Bark (`#312D2A`, `COLORS['text_primary']`)

## Edge Styles

### Modern default (orthogonal router, no fixed ports)
```
edgeStyle=orthogonalEdgeStyle;rounded=1;jettySize=auto;orthogonalLoop=1;html=1;strokeColor={ec};strokeWidth=1.5;{arrow}fontFamily=Oracle Sans;fontSize=12;fontColor={COLORS['text_primary']};{style_extra}
```
This is what `add_edge()` emits when no ports/waypoints are passed - draw.io's orthogonal router chooses the path. `{ec}` is the `color` argument or `COLORS['edge_color']` (Bark) by default; `{arrow}` is the dashed/solid arrowhead fragment below; `{style_extra}` is caller-supplied extra style text (empty by default).

### Legacy pinned mode (explicit ports/waypoints)
```
html=1;strokeColor={ec};strokeWidth=1.5;{arrow}fontFamily=Oracle Sans;fontSize=12;fontColor={COLORS['text_primary']};rounded=1;jettySize=auto;orthogonalLoop=1;{style_extra}exitX={exit_x};exitY={exit_y};exitDx=0;exitDy=0;entryX={entry_x};entryY={entry_y};entryDx=0;entryDy=0;
```
Used when any of `exit_x`/`exit_y`/`entry_x`/`entry_y` or `waypoints` are passed to `add_edge()` (the v1.0.0 behavior) - fixed connection points, router disabled. Defaults when ports are only partially given: `exit_x=0.5, exit_y=1.0, entry_x=0.5, entry_y=0.0` (bottom-to-top).

### Arrowhead fragments
```
dashed=0;endArrow=open;endFill=0;
```
Solid edge (data flow). Dashed edges use the plain fragment - no `dashPattern`:
```
dashed=1;endArrow=none;endFill=0;
```

### Semantics
- **Solid** = data flow / network connection
- **Dashed** = user interaction
- Connectors are always **Bark** (`#312D2A`, `COLORS['edge_color']`) by default. `edge_accent` and `edge_purple` are non-official custom overrides available via `add_edge(..., color=...)`.

### Exit/Entry Ports
- `exitX/exitY` and `entryX/entryY` control which side of the shape the edge connects to (legacy pinned mode only)
- Values: `0` = left/top, `0.5` = center, `1` = right/bottom
- Common: top `(0.5, 0)`, bottom `(0.5, 1)`, left `(0, 0.5)`, right `(1, 0.5)`

## Font Stack

| Font | Usage | Availability |
|------|-------|---------------|
| **Oracle Sans** | Body text, labels, containers (the `fontFamily` emitted in every style above) | Oracle's proprietary corporate font - not redistributable, must be installed manually |
| **Arial / Calibri** | Oracle's sanctioned fallbacks when Oracle Sans is unavailable | System-installed, widely available |
| **Georgia** | Titles, headings | Web-safe, available everywhere |

draw.io falls back automatically to a system font when Oracle Sans is absent - no error, just a visual mismatch. Close and reopen the file after installing Oracle Sans to pick it up (see `gotchas.md` #5).
