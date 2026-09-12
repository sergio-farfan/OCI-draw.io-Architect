# Oracle draw.io Template Styles (v1.2.0)

Every value below was read back from `scripts/drawio_builder.py` 1.2.0 with Python
probes (`DrawioBuilder(style_profile=...)._group_styles[...]`, a test diagram written
to `/tmp` and inspected). `{FONT_STACK}` in a style string stands for the value of
`drawio_builder.FONT_STACK` (see section 8); everything else is literal.

## 1. Provenance

Styles follow Oracle's **OCI Architecture Diagram Toolkit** (docs.oracle.com, page
"OCI Architecture Diagram Toolkits"). The page publishes three assets and no newer
version exists as of September 2026:

| Asset | Contents | Version |
|-------|----------|---------|
| `OCI-Style-Guide-for-Drawio.zip` | `OCI Architecture Diagram Toolkit v24.2.drawio` (pages Start here / Logical / Physical / Icons) + `OCI Library.xml` (the icon library) | v24.2 |
| `OCI_Icons.pptx` | Style guide (palette, groupings, connector rules) | v24.1, January 2024, last updated April 2024 |
| `OCI_Icons_Visio.zip` | Visio stencils (not used by this plugin) | - |

Three provenance tags are used throughout this document:

- **official** - taken from the v24.2 `.drawio` templates / `OCI Library.xml` or the PPTX style guide.
- **sample** - taken from the user's reference diagram (`OCI_Architecture.drawio`, the v1.0.0 look). Reproduced by the `v1.0` profile and, with the official 12px container labels, by `default`.
- **project** - a plugin convention with no counterpart in the toolkit.

Facts established from the official sources that drive the profiles:

- Location groups (Region, AD, FD, on-premises, ...) use **fontSize 12**; labels are **left-aligned** in the physical templates and **centred** in the small logical swatches.
- The **compartment** label is left-aligned **Bark** (`#312D2A`), not Sienna; border is Sienna dotted (`dashPattern=1 1`).
- **Connectors** are 1pt, `rounded=0`, `endArrow=open` (also on the dashed user-interaction lines), label ~10.5px (8pt) with a **white label box**.
- **Oracle Sans for all diagram text**, with Arial/Calibri as sanctioned fallbacks. Georgia titles (v1.0/v1.1) were a project convention and are no longer emitted.
- The v1.1.0 `services` style (`#9E9892`, 2px dashed) was byte-for-byte Oracle's **"Metro Area or Realm"** grouping; it is now exposed as `group_type="metro_or_realm"`. `services` now uses the charcoal 1px dashed style that matches both the sample's services panel and the official logical **"Other Group"** stroke (there is no official "services panel").
- **Oracle Services Network** per the PPTX: Rose 1pt dashed, Air fill, centred label (the v24.2 `.drawio` uses a different Sienna 2pt variant; the plugin follows the PPTX).
- Rounded-corner radii differ between the two official sources: **AD arcSize 8 / FD arcSize 7** in `OCI Library.xml`, **1 / 3** in the physical templates. `official` uses the library values, `default`/`v1.0` the template values.

## 2. Palette (`drawio_builder.COLORS`)

| Key | Hex | Official Redwood name | Used for |
|-----|-----|-----------------------|----------|
| `region_fill` | `#F5F4F2` | Neutral 1 | region / onprem / third_party_cloud / internet fill |
| `region_stroke` | `#9E9892` | Neutral 3 | location-group borders (region, tenancy, AD, FD, onprem, metro_or_realm), table cell borders |
| `neutral_2` | `#DFDCD8` | Neutral 2 | availability_domain fill |
| `neutral_4` | `#70736E` | Neutral 4 | secondary text / connector labels (defined, not wired into a default style) |
| `air` | `#FCFBFA` | Air | fault_domain fill, oracle_services_network fill |
| `vcn_stroke` | `#AE562C` | Sienna | vcn / subnet / compartment borders |
| `vcn_label` | `#AE562C` | Sienna | vcn / subnet label text |
| `text_primary` | `#312D2A` | Bark | all text, services / other borders, caption text |
| `rose` | `#A36472` | Rose | oracle_services_network border + label |
| `ivy` | `#759C6C` | Ivy | OCI logical component border (defined, not wired into a group style) |
| `ocean` | `#2C5967` | Ocean | icon ink colour of the bundled SVGs (informational) |
| `oracle_red` | `#C74634` | Oracle Red | on-premises logical component border (defined, not wired into a group style) |
| `edge_color` | `#312D2A` | Bark | default connector colour |
| `edge_accent` | `#AE562C` | **project extension** | highlighted edges (`add_edge(color=COLORS["edge_accent"])`; `oci_layout` kind `analytics`) |
| `edge_purple` | `#7B61FF` | **project extension** | special connection type (`oci_layout` kind `datalake`, dashed) |

Every key except `edge_accent` and `edge_purple` is an official Redwood diagram colour.

## 3. Style profiles (`drawio_builder.STYLE_PROFILES`)

Choose with `DrawioBuilder(style_profile="default" | "official" | "v1.0")` or
`python3 oci_layout.py model.json --profile default|official|v1.0`. `"sample"` is an
alias of `"v1.0"` accepted by `DrawioBuilder` only. Unknown names raise
`ValueError: Unknown style_profile ...`.

| Knob | `default` | `official` | `v1.0` | What it changes |
|------|-----------|------------|--------|-----------------|
| `spacing_left` | 5 | 5 | 3 | `spacingLeft` of every left-aligned container label |
| `container_font` | 12 | 12 | 12 | `fontSize` of region, tenancy, AD, FD, compartment, OSN, onprem, metro_or_realm, third_party_cloud, internet |
| `vcn_font` | 12 | 12 | 13 | `fontSize` of `vcn` |
| `subnet_font` | 11 | 12 | 11 | `fontSize` of `subnet` |
| `arc_region` | 1 | 1 | 1 | `arcSize` of region / onprem / third_party_cloud / internet |
| `arc_ad` | 1 | 8 | 1 | `arcSize` of availability_domain |
| `arc_fd` | 3 | 7 | 3 | `arcSize` of fault_domain |
| `edge_width` | 1.5 | 1 | 1.5 | connector `strokeWidth` |
| `edge_rounded` | 1 | 0 | 1 | connector `rounded` (rounded vs sharp bends) |
| `edge_font` | 12 | 10.5 | 12 | connector label `fontSize` (also drives label-collision estimates) |
| `dash_pattern` | `6 3` | none | `6 3` | `dashPattern` on dashed edges (none = draw.io's default 3 3 pattern) |
| `dashed_arrow` | `none` | `open` | `none` | `endArrow` on dashed edges |

- **default** - the sample look with the official 12px container labels; dashed edges keep `6 3` so they stay distinct from dashed borders. Provenance: sample + official.
- **official** - strict toolkit values (library arc sizes, 1pt sharp connectors, open arrowheads on dashed lines, 10.5px labels, 12px subnet labels). Provenance: official.
- **v1.0** - byte-for-byte v1.0.0 sample styling (3px label inset, 13px VCN label). Provenance: sample.

Only the knobs above change between profiles; `services` and `other` labels are fixed at
11px in every profile (sample convention), and the icon/caption geometry (section 5) is
identical in all three.

## 4. Container styles (`add_group(..., group_type=...)`)

`GROUP_TYPES` = `region, tenancy, availability_domain, fault_domain, compartment, vcn,
subnet, services, oracle_services_network, onprem, hub, other, metro_or_realm,
third_party_cloud, internet` (`hub` is a deprecated alias whose style is identical to
`onprem`). Strings below are the **default** profile.

Every style starts with `whiteSpace=wrap;html=1;fontFamily={FONT_STACK};verticalAlign=top;`
and ends with `container=1;collapsible=0;expand=0;recursiveResize=0;`:

- `container=1` marks the cell as a container for draw.io (drop target, group behaviour) **and** is the token `check_overlaps.py` / `validate_file()` use to classify a rectangle as a container. Nesting itself is done by the `parent` attribute.
- `collapsible=0;expand=0` hide the collapse/expand handle.
- `recursiveResize=0` stops draw.io from scaling the children when a user resizes the container in the editor, so a resized subnet does not distort its icons.

### region
```
whiteSpace=wrap;html=1;fontFamily={FONT_STACK};verticalAlign=top;rounded=1;arcSize=1;strokeWidth=1;fillColor=#F5F4F2;strokeColor=#9E9892;fontSize=12;fontStyle=1;fontColor=#312D2A;align=left;spacingLeft=5;spacingRight=5;container=1;collapsible=0;expand=0;recursiveResize=0;
```
Solid Neutral 3 border, Neutral 1 fill, barely rounded, bold left-aligned Bark label (official physical template).

### onprem (and deprecated alias `hub`)
```
whiteSpace=wrap;html=1;fontFamily={FONT_STACK};verticalAlign=top;rounded=1;arcSize=1;strokeWidth=1;fillColor=#F5F4F2;strokeColor=#9E9892;fontSize=12;fontStyle=1;fontColor=#312D2A;align=left;spacingLeft=5;spacingRight=5;container=1;collapsible=0;expand=0;recursiveResize=0;
```
Identical to `region`: on-premises / hub networks are location groups in the toolkit.

### third_party_cloud, internet
```
whiteSpace=wrap;html=1;fontFamily={FONT_STACK};verticalAlign=top;rounded=1;arcSize=1;strokeWidth=1;fillColor=#F5F4F2;strokeColor=#9E9892;fontSize=12;fontStyle=1;fontColor=#312D2A;align=center;spacingRight=5;container=1;collapsible=0;expand=0;recursiveResize=0;
```
The location style with a centred label (logical-swatch alignment) for external clouds and the public internet.

### tenancy
```
whiteSpace=wrap;html=1;fontFamily={FONT_STACK};verticalAlign=top;rounded=0;strokeWidth=1;dashed=1;fillColor=none;strokeColor=#9E9892;fontSize=12;fontStyle=0;fontColor=#312D2A;align=left;spacingLeft=5;container=1;collapsible=0;expand=0;recursiveResize=0;
```
Dashed Neutral 3 border, no fill, square corners, **regular-weight** (`fontStyle=0`) label - the only non-bold container, per the PPTX and the library.

### availability_domain
```
whiteSpace=wrap;html=1;fontFamily={FONT_STACK};verticalAlign=top;rounded=1;arcSize=1;strokeWidth=1;fillColor=#DFDCD8;strokeColor=#9E9892;fontSize=12;fontStyle=1;fontColor=#312D2A;align=center;container=1;collapsible=0;expand=0;recursiveResize=0;
```
Solid Neutral 3 border, Neutral 2 fill, centred label. `arcSize` is the profile's `arc_ad`.

### fault_domain
```
whiteSpace=wrap;html=1;fontFamily={FONT_STACK};verticalAlign=top;rounded=1;arcSize=3;strokeWidth=1;fillColor=#FCFBFA;strokeColor=#9E9892;fontSize=12;fontStyle=1;fontColor=#312D2A;align=center;container=1;collapsible=0;expand=0;recursiveResize=0;
```
Solid Neutral 3 border, Air fill, centred label; nests inside `availability_domain`. `arcSize` is `arc_fd`.

### compartment
```
whiteSpace=wrap;html=1;fontFamily={FONT_STACK};verticalAlign=top;rounded=0;strokeWidth=1;dashed=1;dashPattern=1 1;fillColor=none;strokeColor=#AE562C;fontSize=12;fontStyle=1;fontColor=#312D2A;align=left;spacingLeft=5;container=1;collapsible=0;expand=0;recursiveResize=0;
```
Dotted (`dashPattern=1 1`) Sienna border, no fill, **left-aligned Bark** label (official). Unlike VCN/subnet the label does not take the border colour.

### vcn
```
whiteSpace=wrap;html=1;fontFamily={FONT_STACK};verticalAlign=top;rounded=0;strokeWidth=2;dashed=1;fillColor=none;strokeColor=#AE562C;labelBackgroundColor=none;fontSize=12;fontStyle=1;fontColor=#AE562C;align=left;spacingLeft=5;container=1;collapsible=0;expand=0;recursiveResize=0;
```
2px dashed Sienna border, Sienna label. `fontSize` is `vcn_font` (13 in `v1.0`).

### subnet
```
whiteSpace=wrap;html=1;fontFamily={FONT_STACK};verticalAlign=top;rounded=0;strokeWidth=1;dashed=1;fillColor=none;strokeColor=#AE562C;fontSize=11;fontStyle=1;fontColor=#AE562C;align=left;spacingLeft=5;container=1;collapsible=0;expand=0;recursiveResize=0;
```
Like `vcn` with a 1px border. `fontSize` is `subnet_font` (11 sample / 12 official).

### services
```
whiteSpace=wrap;html=1;fontFamily={FONT_STACK};verticalAlign=top;rounded=0;strokeWidth=1;dashed=1;fillColor=none;strokeColor=#312D2A;fontSize=11;fontStyle=1;fontColor=#312D2A;align=left;spacingLeft=5;container=1;collapsible=0;expand=0;recursiveResize=0;
```
Charcoal (Bark) 1px dashed panel for "OCI Services" - the sample's panel and the official "Other Group" stroke. Fixed 11px label in every profile. **Changed in v1.2.0**: the old grey 2px look is now `metro_or_realm`.

### metro_or_realm
```
whiteSpace=wrap;html=1;fontFamily={FONT_STACK};verticalAlign=top;rounded=0;strokeWidth=2;dashed=1;fillColor=none;strokeColor=#9E9892;fontSize=12;fontStyle=1;fontColor=#312D2A;align=left;spacingLeft=5;container=1;collapsible=0;expand=0;recursiveResize=0;
```
Oracle's "Metro Area or Realm" grouping: 2px dashed Neutral 3, no fill (official). This is what v1.1.0 emitted for `services`.

### oracle_services_network
```
whiteSpace=wrap;html=1;fontFamily={FONT_STACK};verticalAlign=top;rounded=0;strokeWidth=1;dashed=1;fillColor=#FCFBFA;strokeColor=#A36472;fontSize=12;fontStyle=1;fontColor=#A36472;align=center;container=1;collapsible=0;expand=0;recursiveResize=0;
```
Rose 1px dashed border, Air fill, centred Rose label (official PPTX spec).

### other
```
whiteSpace=wrap;html=1;fontFamily={FONT_STACK};verticalAlign=top;rounded=1;arcSize=10;strokeWidth=1;dashed=1;fillColor=none;strokeColor=#312D2A;fontSize=11;fontStyle=1;fontColor=#312D2A;align=center;container=1;collapsible=0;expand=0;recursiveResize=0;
```
The official logical "Other Group": rounded (`arcSize=10`) Bark 1px dashed, centred 11px label. Also the frame `add_legend()` draws (with `label_position="left"`).

### How `official` and `v1.0` differ from `default`

| group_type | `official` | `v1.0` |
|------------|------------|--------|
| region, onprem, hub, tenancy, compartment, subnet, services, metro_or_realm | - | `spacingLeft=3` |
| vcn | - | `spacingLeft=3`, `fontSize=13` |
| subnet | `fontSize=12` | `spacingLeft=3` |
| availability_domain | `arcSize=8` | - |
| fault_domain | `arcSize=7` | - |
| oracle_services_network, other, third_party_cloud, internet | - | - |

### Per-call overrides

- `label_position="center"` replaces `align=...` with `align=center` and removes `spacingLeft`; `label_position="left"` sets `align=left;spacingLeft=<profile spacing_left>`. Anything else raises `ValueError`.
- `style_extra="k=v;..."` is merged last and overrides any token (e.g. `style_extra="fillColor=#FFFFFF;"`).
- Labels are HTML-escaped and `\n` becomes `<br>` unless `raw_html=True`.

## 5. Icon cell geometry (`add_icon()`)

Constants: `ICON_W=75`, `ICON_H=95` (the **slot** that layout code positions),
`GLYPH_W=70`, `GLYPH_H=70`, `GLYPH_TOP=5`, `LABEL_GAP=2`, `LABEL_W=105`, `LABEL_H=45`,
`LABEL_FONT_SIZE=11`, `LABEL_LINE_H=14`, `ICON_FOOTPRINT_H=142` (95 + 2 + 45),
`MAX_LABEL_LINES=3`. Grid defaults: `PAD=20`, `ROW1_Y=50`, `COL_W=130`, `ROW_H=160`, `GAP=20`.

Image cell style (identical in all profiles):
```
shape=image;verticalLabelPosition=bottom;verticalAlign=top;imageAspect=1;aspect=fixed;image=data:image/svg+xml,<url-encoded svg>;
```

Default sizing (no `w`/`h`): the glyph is scaled by `min(70/native_w, 70/native_h)` and
centred inside the 70x70 glyph box at the top of the slot:
`cell_w = round(native_w*scale)`, `cell_h = round(native_h*scale)`,
`cell_x = x + round((75 - cell_w)/2)`, `cell_y = y + 5 + round((70 - cell_h)/2)`.
A square icon such as `vm` (viewBox `-1 -1 86 86` after cropping) becomes a 70x70 cell at
`(x+2, y+5)`. Native size comes from `_load_svg()`, which crops the SVG viewBox to the
drawn paths with 1 unit of padding and strips the OCI Library caption placeholder box, so
every icon renders at the same visual size (bundled aspect ratios range 0.57 to 1.93).

Explicit sizing: passing `w` and/or `h` places the image cell at exactly `(x, y)` with that
size (the missing dimension follows the native aspect ratio), and the slot becomes the
cell itself - the 75x95 slot and glyph fitting are bypassed.

Caption (a separate, non-connectable text cell, emitted only when the label is non-empty):
```
text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=top;whiteSpace=wrap;rounded=0;connectable=0;fontFamily={FONT_STACK};fontSize=11;fontStyle=0;fontColor=#312D2A;
```
- width `LABEL_W=105` (explicit-size icons: `max(105, cell_w + 30)`), centred on the slot: `x = slot_x - 15` for the default slot; `y = slot_y + 95 + 2`.
- height `max(45, lines*14 + 4)`: 45px for 1-2 lines, 46 for 3, 60 for 4, 74 for 5 (the caption grows ~14px per extra line). `lines` is estimated by `label_lines()` at about 16 characters per line.
- overrides: `label_w`, `label_h`, `font_size`; `key="lb"` names the cells `lb` and `lb-label`.
- `footprint(cid)` returns slot + caption; `place_icons()` returns the bounding box of all footprints so `fit_to_children()` includes captions.

## 6. Edge styles (`add_edge()`)

Base style, `default` profile (`official` swaps in `strokeWidth=1`, `fontSize=10.5`,
`rounded=0`):
```
edgeStyle=orthogonalEdgeStyle;html=1;strokeColor=#312D2A;strokeWidth=1.5;dashed=0;endArrow=open;endFill=0;fontFamily={FONT_STACK};fontSize=12;fontColor=#312D2A;rounded=1;jettySize=auto;orthogonalLoop=1;
```

| Mode | When | What is emitted |
|------|------|-----------------|
| `route="auto"` (default) | no ports / waypoints given | base style; at `validate()`/`write()` the builder appends `exitX/exitY/exitDx/exitDy/entryX/entryY/entryDx/entryDy` for the chosen sides and writes interior corners as `<Array as="points">` waypoints in the parent's coordinates |
| `route="direct"` (or `orthogonal=True`) | let draw.io's router pick the path | base style only, no pins, no waypoints |
| `route="pinned"` | any of `exit_x/exit_y/entry_x/entry_y` or `waypoints` given (v1.0.0 behaviour) | base style **without** `edgeStyle=orthogonalEdgeStyle;`, followed by `exitX=..;exitY=..;exitDx=0;exitDy=0;entryX=..;entryY=..;entryDx=0;entryDy=0;` (defaults exit `0.5,1` bottom, entry `0.5,0` top) plus the waypoints |
| `pinned_router` | pins/waypoints **and** `orthogonal=True` | orthogonal base style plus only the pins that were given |

Pinned example (default profile):
```
html=1;strokeColor=#312D2A;strokeWidth=1.5;dashed=0;endArrow=open;endFill=0;fontFamily={FONT_STACK};fontSize=12;fontColor=#312D2A;rounded=1;jettySize=auto;orthogonalLoop=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;
```

Dash / arrow fragment (`dashed=True`):

| Profile | Fragment |
|---------|----------|
| `default`, `v1.0` | `dashed=1;dashPattern=6 3;endArrow=none;endFill=0;` (sample) |
| `official` | `dashed=1;endArrow=open;endFill=0;` (toolkit: open arrowhead kept on user-interaction lines) |

`arrow=` overrides `endArrow`; `endFill=1` for `block`, `classic`, `diamond`, `oval`, otherwise `0`.
`color=` replaces `strokeColor` (label colour stays Bark). `style_extra` is merged last -
the official **white label box** is not emitted by any profile; add it with
`style_extra="labelBackgroundColor=#FFFFFF;"` if needed.

Labels: `label_pos` (-1..1, 0 = middle) is written as `<mxGeometry relative="1" x=... y="0">`.
For auto-routed edges without `label_pos` the builder tries the middle first, then
0.4/0.6, 0.3/0.7, 0.2/0.8, 0.12/0.88 along the path and keeps the first position whose
estimated label box clears every icon, caption and text cell.

Semantics: **solid** = data flow / network path; **dashed** = management, API or user
interaction. Connectors are Bark by default; `edge_accent` / `edge_purple` are project
extensions. `parent` defaults to the common ancestor of source and target.

## 7. Text, title, table and legend styles

`add_text()` (raw HTML by default, `font_size=10`, `align="left"`, `vertical_align="middle"`):
```
text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily={FONT_STACK};fontSize=10;fontStyle=0;fontColor=#312D2A;
```

`add_title()` - an `add_text` at `(20, 8)` 600x55 with `key="title"`, `fontSize=18;fontStyle=1`:
```
text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontFamily={FONT_STACK};fontSize=18;fontStyle=1;fontColor=#312D2A;
```
value `<b>{tenancy - }subject</b><br/><i>{region_label} ({region}) - Compartment: {compartment}</i>`
(pieces omitted when not given). An optional `logo` is embedded 148x39 at
`(page_w - logo_w - 22, y)` with key `title-logo`; a missing file or missing Pillow prints
`WARNING: logo skipped: ...` to stderr and returns `{"logo": None}`.

`add_table()` - one HTML text cell, width `sum(col_widths) + 6` (110px per column by
default), height `row_h*rows + (row_h if title) + 6`:
```
text;html=1;strokeColor=none;fillColor=#FFFFFF;align=left;verticalAlign=top;whiteSpace=wrap;overflow=fill;rounded=0;spacing=2;fontFamily={FONT_STACK};fontSize=10;fontColor=#312D2A;
```
Cells are `<th>/<td style="border:1px solid #9E9892;padding:1px 4px;text-align:left;width:..px;">`, header
cells add `background:#F5F4F2;`, an optional bold title `<div>` sits above the table.

`add_legend()` - an `other` container 230px wide, `30 + 22*entries + 8` high, with
`label_position="left"`:
```
whiteSpace=wrap;html=1;fontFamily={FONT_STACK};verticalAlign=top;rounded=1;arcSize=10;strokeWidth=1;dashed=1;fillColor=none;strokeColor=#312D2A;fontSize=11;fontStyle=1;fontColor=#312D2A;align=left;container=1;collapsible=0;expand=0;recursiveResize=0;spacingLeft=5;
```
Each row is either a 40px sample edge (the non-orthogonal base style with the profile's
solid/dashed fragment, drawn between `sourcePoint`/`targetPoint`) or a 36x16 swatch carrying
the group style minus `container/collapsible/expand/recursiveResize`, followed by a 10px
`add_text`. Default entries: solid "Data flow / network path", dashed "Management, API or
service traffic", swatches for region, vcn, subnet, services.

## 8. Fonts

```
FONT_STACK = "Oracle Sans,Arial,Helvetica,sans-serif"
TITLE_FONT_STACK = FONT_STACK
```

Oracle Sans is Oracle's proprietary face (not redistributable, install it manually); the
toolkit prescribes it for all diagram text with Arial/Calibri as fallbacks. draw.io copies
`fontFamily` straight into CSS, so a bare `fontFamily=Oracle Sans` falls back to the
renderer's **serif** default when the font is missing - the stack degrades to Arial /
Helvetica / a sans-serif face instead. draw.io renders system-installed fonts only (no web
fonts).

Override per builder with `DrawioBuilder(font_family="Calibri")` - it is applied to
container labels, captions, edges, text, titles, tables and legends - or per text cell with
`add_text(..., font_family=...)` / `add_title(..., font_family=...)`.
