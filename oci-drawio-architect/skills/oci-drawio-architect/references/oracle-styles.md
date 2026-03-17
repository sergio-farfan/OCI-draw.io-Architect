# Oracle draw.io Template Styles

Extracted from the official OCI Architecture Diagram Toolkit v24.2.

## Color Palette

| Key | Hex | Usage |
|-----|-----|-------|
| `region_fill` | `#F5F4F2` | Region/compartment/hub background |
| `region_stroke` | `#9E9892` | Region/compartment/hub border |
| `vcn_stroke` | `#AE562C` | VCN and subnet borders (oracle orange) |
| `vcn_label` | `#AE562C` | VCN and subnet label text |
| `text_primary` | `#312D2A` | Region labels, general text, charcoal |
| `edge_color` | `#312D2A` | Default edge/arrow color |
| `edge_accent` | `#AE562C` | Accent edges (e.g., OAC/PAC connections) |
| `edge_purple` | `#7B61FF` | Special-purpose edges (e.g., AIDP data flows) |

## Container Styles

### Region
```
whiteSpace=wrap;html=1;rounded=1;arcSize=1;
fillColor=#F5F4F2;strokeColor=#9E9892;
fontFamily=Oracle Sans;fontSize=12;fontStyle=1;
fontColor=#312D2A;verticalAlign=top;align=left;
spacingLeft=3;spacingRight=5;container=1;collapsible=0;expand=0;
```
- Solid border, warm gray fill, rounded corners
- Bold Oracle Sans 12px, charcoal text

### Compartment
Same as Region but without `spacingRight=5`.

### VCN
```
whiteSpace=wrap;html=1;rounded=0;
strokeWidth=2;dashed=1;
fillColor=none;strokeColor=#AE562C;
labelBackgroundColor=none;
fontFamily=Oracle Sans;fontSize=13;fontStyle=1;
fontColor=#AE562C;verticalAlign=top;align=left;
spacingLeft=3;container=1;collapsible=0;expand=0;
```
- **Dashed** orange border (`strokeWidth=2`), transparent fill
- Sharp corners (`rounded=0`)
- Orange label text matches border

### Subnet
```
whiteSpace=wrap;html=1;rounded=0;
strokeWidth=1;dashed=1;
fillColor=none;strokeColor=#AE562C;
fontFamily=Oracle Sans;fontSize=11;fontStyle=1;
fontColor=#AE562C;verticalAlign=top;align=left;
spacingLeft=3;container=1;collapsible=0;expand=0;
```
- Same as VCN but thinner (`strokeWidth=1`) and smaller font (11px)

### Services Panel
```
whiteSpace=wrap;html=1;rounded=0;
strokeWidth=1;dashed=1;
fillColor=none;strokeColor=#312D2A;
fontFamily=Oracle Sans;fontSize=11;fontStyle=1;
fontColor=#312D2A;verticalAlign=top;align=left;
spacingLeft=3;container=1;collapsible=0;expand=0;
```
- Charcoal dashed border (not orange) to distinguish from subnets

### Hub / On-Premises
Same as Region (solid warm gray fill, rounded corners).

## Common Container Properties

All containers share:
- `container=1` - **Required** for child cells to nest correctly
- `collapsible=0;expand=0` - Disable draw.io collapse/expand behavior
- `verticalAlign=top;align=left` - Label in top-left corner
- `spacingLeft=3` - Small left padding for label
- `whiteSpace=wrap;html=1` - Enable HTML and text wrapping

## Icon Cell Style

```
shape=image;verticalLabelPosition=bottom;verticalAlign=top;
imageAspect=0;aspect=fixed;
image=data:image/svg+xml,{url_encoded_svg};
```

Key properties:
- `imageAspect=0` - Stretch SVG to fill cell (matches Oracle templates)
- `aspect=fixed` - Maintain cell aspect ratio when user resizes in draw.io
- Label is a separate text cell placed below the icon (not inline)

## Edge Styles

### Solid Edge (data flow, network connection)
```
html=1;strokeColor=#312D2A;strokeWidth=1.5;
dashed=0;endArrow=open;endFill=0;
fontFamily=Oracle Sans;fontSize=12;
fontColor=#312D2A;rounded=1;
jettySize=auto;orthogonalLoop=1;
exitX=0.5;exitY=1.0;exitDx=0;exitDy=0;
entryX=0.5;entryY=0.0;entryDx=0;entryDy=0;
```

### Dashed Edge (logical/optional connection)
```
html=1;strokeColor=#312D2A;strokeWidth=1.5;
dashed=1;dashPattern=6 3;endArrow=none;endFill=0;
fontFamily=Oracle Sans;fontSize=12;
fontColor=#312D2A;rounded=1;
jettySize=auto;orthogonalLoop=1;
```

### Exit/Entry Ports
- `exitX/exitY` and `entryX/entryY` control which side of the icon the edge connects to
- Values: `0` = left/top, `0.5` = center, `1` = right/bottom
- Common: top `(0.5, 0)`, bottom `(0.5, 1)`, left `(0, 0.5)`, right `(1, 0.5)`

## Font Stack

| Font | Usage | Availability |
|------|-------|-------------|
| **Oracle Sans** | Body text, labels, containers | Must be system-installed |
| **Georgia** | Titles, headings | Web-safe, available everywhere |

draw.io desktop (Electron) renders system-installed fonts. Web fonts are NOT supported.
