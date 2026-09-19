# draw.io + OCI Icons - Gotchas & Workarounds (v1.3.1)

20 verified pitfalls. Every claim below was reproduced against `scripts/drawio_builder.py`
1.3.1 (error texts are quoted verbatim). Items marked *migration* matter when updating a
v1.0/v1.1 script.

## 1. URL-encode SVG data URIs - `;base64,` breaks the style tokenizer

draw.io/mxGraph splits a cell style on `;`. A standard data URI such as
`image=data:image/svg+xml;base64,PHN2...` is cut at the marker's semicolon: the image value
becomes `data:image/svg+xml` and the rest turns into garbage style tokens. The builder
therefore emits **URL-encoded** SVG (`urllib.parse.quote(svg, safe="")`), which also
percent-encodes any semicolon inside the SVG (`%3B`), so nothing can collide with the
tokenizer:

```python
data_uri = "data:image/svg+xml," + urllib.parse.quote(svg_text, safe="")
```

**Symptom of doing it wrong:** blank icon cells. A written `.drawio` from the builder
contains no `;base64,` at all.

## 2. PNG/JPEG logos need Pillow; SVG logos need nothing

`add_image()` embeds SVG files directly (URL-encoded, see #1). PNG/JPEG logos are resized to
at most 300px wide, base64-encoded and wrapped in an `<svg><image xlink:href="data:image/png;base64,..."/></svg>`
shell so the outer URI can still be URL-encoded. That path imports Pillow and fails with

```
ImportError: Pillow is required for PNG/JPEG logos: run `python3 -m pip install --user Pillow`, or supply an SVG logo instead.
```

`add_title(..., logo="x.png")` catches this (and a missing file) and prints
`WARNING: logo skipped: ...` to stderr, returning `{"logo": None}` - the diagram is still
written. Prefer an SVG logo when Pillow is not available.

## 3. Icon resolution when the builder is imported from another directory

At import time `drawio_builder` picks the first existing directory among, in order:
`$OCI_SVG_DIR`, `<module dir>/../icons` (plugin layout), `<module dir>/icons`,
`$CLAUDE_PLUGIN_ROOT/icons`, `~/.claude/plugins/marketplaces/*/plugins/oci-drawio-architect/icons`,
`~/.claude/plugins/cache/*/oci-drawio-architect/*/icons`, `~/.claude/plugins/cache/*/oci-drawio-architect/icons`,
`~/.claude/plugins/oci-drawio-architect/icons`. If none exists, the first `add_icon()` raises

```
FileNotFoundError: OCI icon directory not found. Set the OCI_SVG_DIR environment variable (or call set_icon_dir()) to the plugin's icons/ folder. Searched:
  <each candidate path>
```

A copy of `drawio_builder.py` dropped into a project folder has no `../icons`, so **import
it from the plugin instead of copying it**:

```python
import sys
sys.path.insert(0, "<plugin>/scripts")   # e.g. os.environ["CLAUDE_PLUGIN_ROOT"] + "/scripts"
from drawio_builder import DrawioBuilder
```

or export `OCI_SVG_DIR=<plugin>/icons`, or call `drawio_builder.set_icon_dir(path)`.
Unknown icon keys raise `ValueError: Unknown icon_key 'virtual_machine'. Did you mean
compute_virtual_machine_vm? ...` - every bundled SVG is addressable by file stem or alias.

## 4. Unknown parent / source / target ids raise at call time

draw.io stops rendering a page at the first cell whose `parent` cannot be resolved, so a
typo used to blank the whole diagram. Since v1.2.0 the builder validates ids immediately:

```
ValueError: add_group: unknown parent id 'nope'. Pass the id returned by add_group()/add_layer()
ValueError: add_group: parent must be a cell id (use '1' for the default layer)
ValueError: add_edge: unknown target id 'zzz'; pass the id returned by add_icon()/add_group()
```

(the same for `add_icon`, `add_text`, `add_image`, `add_table`, `add_legend`). Parents that
are edges or live on another page are rejected too. For hand-written or externally edited
files, `scripts/check_overlaps.py` reports

```
ERROR: cell 'Orphan VCN' (id orphan) has unknown parent id 'missing-parent'; draw.io drops the rest of the diagram when a parent is missing
ERROR: edge '(unlabelled)' (id e1) target id 'ghost' does not exist
```

and exits 1.

## 5. Cross-container edges: parent = common ancestor, waypoints in the parent's space

When source and target sit in different containers (DRG at region level, LB in a subnet) the
edge's `parent` must be an ancestor of both; `add_edge()` picks the **common ancestor**
automatically when `parent` is omitted (e.g. the region for hub -> subnet, the VCN for
subnet -> subnet, the subnet for two icons in the same subnet). Waypoints - yours or the
auto-router's - are expressed in **that parent's** coordinate space, not the page's and not
the VCN's. Passing a parent that is not an ancestor of both ends makes draw.io draw the
edge in the wrong place.

## 6. Edge routing modes, and when auto routes are resolved

- `route="auto"` (default when no ports/waypoints are given): the builder picks the exit/entry
  sides and gutter waypoints on an orthogonal lattice so the connector avoids icons,
  captions and foreign containers. Routes are computed **lazily at `validate()` / `write()`
  / `route_edges()`**, once - so add every container and icon before the first `validate()`,
  or an icon added afterwards will not be avoided. A docking point another connector
  already uses costs extra, so two connectors on one shape take different sides unless
  every free side is a long detour away; add the edge you care about most first.
- `route="direct"`: draw.io's own orthogonal router, no pins. Use it for short
  neighbour-to-neighbour links where you want the editor to keep re-routing when a user
  drags shapes.
- `route="pinned"` (automatic when any of `exit_x/exit_y/entry_x/entry_y` or `waypoints` is
  passed): fixed ports, router off, exactly what v1.0.0 did. Use it when you need a specific
  side or a specific corridor; ports are 0..1 fractions (`0` = left/top, `1` = right/bottom).
  Passing pins together with `orthogonal=True` keeps the router and only fixes the sides.

`validate()` estimates the polyline draw.io will draw and emits
`WARNING: edge '443' (Load Balancer -> App VM) is estimated to cross: Blocker` when it passes
through an icon or caption that is not an endpoint. It is a **heuristic** (it does not know
draw.io's exact jetty behaviour); `--strict` / `validate(strict=True)` turns it into an
ERROR. Neither router avoids obstacles for pinned edges - that is what waypoints are for.

## 7. draw.io render caching and system-only fonts

draw.io desktop keeps rendered pages cached: after regenerating a file, changing styles or
swapping icon data URIs, **close the file and reopen it** - saving or switching tabs is not
enough. Fonts are system fonts only (no web fonts); Oracle Sans is proprietary and must be
installed manually, which is why every style carries the stack
`Oracle Sans,Arial,Helvetica,sans-serif` (a bare `fontFamily=Oracle Sans` falls back to a
serif face). To check a result without the editor, `python3 scripts/render_drawio.py
out.drawio -f png` exports through the draw.io desktop CLI when it is installed.

## 8. Cell ids: `key=` slugs, duplicates raise, deterministic output

Ids are generated by a per-builder counter (`2`, `3`, ...) unless you pass `key=`. Keys are
slugged with `[^A-Za-z0-9_.-]+ -> "-"` and trimmed (`"sn-app/lb 01"` -> `sn-app-lb-01`); the
caption cell gets `<key>-label`. Empty keys and `"0"`/`"1"` are rejected
(`ValueError: Invalid cell key '0'`), and a second use of the same slug raises
`ValueError: Duplicate cell key 'sn-app-lb-01'` - even across pages, because the id set is
per file. The same script always yields the same ids, so keyed diagrams are diffable in git
and stable for `add_edge(source, target)` references, metadata and links.

## 9. What `container=1` actually does

draw.io nests cells purely by the `parent` attribute; children render inside their parent
with or without `container=1`. The token matters for two other reasons: in the editor it
makes the rectangle a drop target / group (with `collapsible=0;expand=0` hiding the fold
handle and `recursiveResize=0` keeping children unscaled on resize), and in this toolchain it
is how `check_overlaps.py` / `validate_file()` **classify** a vertex as a container for the
overlap, containment and routing checks (`shape=image` = icon, a leading `text` token =
text). A hand-written rectangle without `container=1` is treated as a leaf shape, not a
container. The old "children render at root level without it" symptom was actually an
unresolved parent id (#4).

## 10. Data URI size: there is no ~20 KB limit

Measured on the bundled set: SVG files are 1.3-25 KB on disk and encode to **2.1-35.5 KB
data URIs each** (median ~9 KB). The reference sample (27 icons plus 4 badges) is
279,871 bytes and a 31-distinct-icon probe built with the builder was ~342 KB; a
single-icon file is ~7 KB.
Both render fine (the probe was exported to PNG through the draw.io desktop CLI with every
icon intact) - file size simply scales with icon count. Keep PNG
logos small (the builder caps them at 300px wide) for file size and editor responsiveness,
not because of a hard limit.

## 11. Overlap, containment and collision checks are errors for *any* two containers

`validate()` (and the `check_overlaps.py` CLI gate) reports, with absolute page coordinates:

- `OVERLAP: 'Hub' [abs [...]] intersects 'sn-lb' [abs [...]] (different parents)` - any two
  containers that are not in an ancestor relationship, **not just siblings** (a subnet
  intruding into an adjacent hub panel is caught even though their parents differ).
- `ERROR: 'sn-app' [[x=600,y=50,w=300,h=220]] extends outside its parent 'VCN' [w=700,h=500]`
  - every vertex must fit inside its parent container (1px tolerance).
- `ERROR: 'App' [abs [...]] overlaps 'Load Balancer' [abs [...]]` - icons, captions and text
  cells may not intersect each other.
- `WARNING: caption '...' needs ~5 lines at 11px in 105px but its box is 45px tall` - long
  captions are warnings, and only when the box is too short: `add_icon()` grows the caption
  by ~14px per line, so this fires for fixed `label_h=` captions and hand-written files.
- `WARNING: title 'sn-shared-services-management (10.0.240.0/24)' needs ~2 lines at 11px in
  the 124px its badges leave` - a container carrying corner badges (route table / security
  list) whose own title runs under them: the badges reserve `BADGE_RESERVE = 52` px of the
  title line. Only lines the narrowed width *forces* count - a title deliberately broken
  over two lines (Oracle's name-over-CIDR subnet label) is fine as long as each line fits.
  The recipe widens a badged subnet automatically (`_subnet_min_w`); a hand-written
  container has to be widened or its title shortened.
- `ERROR: DRG 'hub-drg' is inside VCN 'Spoke-VCN-D'` - a DRG icon (recognised by `ociRole=drg`
  or a caption matching `DRG`) whose box lies inside a `vcn` container; DRGs are region-level
  only (gotcha #19).
- `ERROR: 'sn-app' [abs [...]] lies inside 'Spoke-VCN-B' [abs [...]] but is not one of its
  children` - a leaf or container overlaps a VCN/subnet it is not parented to (the foreign-
  containment check, distinct from the sibling `OVERLAP` above).

Two tolerances keep border-straddling shapes from false-positiving: `STRADDLE_TOL = 4.0` px
lets an icon whose glyph centre sits exactly on its parent's border (gateways on the VCN edge)
still count as "inside"; `FOREIGN_TOL = ICON_W / 4 = 18.75` px lets a leaf overlap a VCN/subnet
it does not belong to by a hair before the foreign-containment `ERROR` above fires.

`check_overlaps()` returns only the blocking messages (OVERLAP/ERROR); `validate()` returns
errors followed by warnings. Derive row positions from computed bottoms
(`fit_to_children()`, `footprint()`, `place_icons()`'s bbox) rather than hardcoding them.

## 12. Labels are HTML-escaped by default; `add_text` is not

`add_group`, `add_icon` and `add_edge` run labels through `escape_label()`: `&`, `<`, `>`
become entities and `\n` becomes `<br>` (`"a & b\n<x>"` -> `a &amp; b<br>&lt;x&gt;`), so
CIDRs in angle brackets and ampersands survive. Pass `raw_html=True` for intentional markup
(`"<b>bold</b>"`). `add_text()` is **raw by default** (`raw_html=True`) because it is meant
for HTML snippets; use `raw_html=False` there for untrusted plain text. `add_title()` and
`add_table()` escape their inputs before building their markup.

## 13. Empty SVGs and the stencil placeholder box

Oracle's `OCI Library.xml` export left 55 stencil shells with no drawable content and, in
some icons, an empty 100x100 caption rectangle (`M 0 100 L 100 100 L 100 0 L 0 0 L 0 100`,
`fill="none" stroke="#000000"`). The v1.2.0 bundle drops the shells and `_load_svg()` strips
the placeholder before measuring, so bundled icons are clean - but custom icon sets
registered through `add_icons_to_map()` / `set_icon_dir()` may still contain both. An SVG
with nothing drawable raises `ValueError: Icon 'empty' (/path/empty.svg) has no drawable content`
instead of producing an invisible cell; a leftover placeholder would enlarge the viewBox and
shrink the glyph.

## 14. The viewBox crop only understands flat `<g transform><path>` SVGs

`_load_svg()` computes the glyph's bounding box from `<path d="...">` coordinates inside
top-level `<g transform="translate(...) scale(...)">` groups (absolute `M/L/C/Z` commands
only), then rewrites the root viewBox/width/height to hug it with 1 unit of padding. All 159
bundled icons match this form. Anything else - nested groups, `<rect>`/`<circle>`/`<use>`,
relative path commands, other transforms - keeps its **declared** viewBox, which for a
padded logo or stencil means the glyph renders smaller than its neighbours. For such icons
pass explicit `w`/`h`, or pre-crop the SVG.

## 15. `fit_to_children()` works inside-out; `resize()` moves siblings

`fit_to_children(cid)` sizes a container from the children **already registered** (icon
footprints include captions), keeping its x/y. Call it after the children exist and from the
innermost container outwards: `fit(subnet); fit(vcn); fit(region)`. Fitting the region first
leaves it at its minimum size and `validate()` then reports the VCN as extending outside it.
A grown container does not push its siblings - reposition them with
`resize(sibling, x=..., y=...)` using the new width plus `GAP`. Finish with `fit_page()` so
the page follows the content (otherwise `validate()` warns `content ... exceeds the page`).

## 16. Multi-page files: unique ids, no cross-page edges

`add_page()` appends a `<diagram id="pageN">`; the only ids that repeat per page are the
mandatory root cells `0` and `1`. Every id the builder generates is unique across the whole
file (one counter and one key set per builder). Edges cannot join cells on different pages
(`ValueError: add_edge: source '3' is on another page`) and a parent from another page is
rejected (`add_icon: parent '2' lives on another page`). Use `use_page(index_or_name)` to
switch the current page; `validate()` / `check_overlaps.py` check every page.

## 17. *migration* - `services` changed look; the old style is `metro_or_realm`

The v1.1.0 `services` container (grey `#9E9892` 2px dashed) was in fact Oracle's "Metro
Area or Realm" grouping. In v1.2.0 `services` renders as the sample's charcoal 1px dashed
panel and the former look is `group_type="metro_or_realm"`. `hub` still works as a
deprecated alias of `onprem`. Scripts that hardcoded `spacingLeft=3`, 13px VCN labels or
`fontSize=11` on region/AD/FD should switch to `DrawioBuilder(style_profile="v1.0")`
instead of `style_extra` patches.

## 18. *migration* - explicit `w`/`h` bypasses the 75x95 slot

Pre-1.1.0 every icon was stretched into a 75x95 cell (`imageAspect=0`). Now the glyph is
fitted into a 70x70 box inside the 75x95 slot with `imageAspect=1`. Passing `w` and/or `h`
to `add_icon()` switches to explicit sizing: the image cell sits at exactly `(x, y)`, the
slot *is* the cell, and the caption widens to `max(105, w + 30)` - so grids built with
`COL_W=130` may collide (see #11). Only do this for deliberately wide shapes; otherwise let
the slot geometry do the work.

## 19. DRG placement: region level only, attachments beside it

A DRG icon parented inside a VCN box asserts that the DRG belongs to that VCN, which is wrong
- a DRG is a region-level resource that several VCNs attach to. The recipe (`oci_layout.py`)
therefore always parents the DRG icon (and, in `drg_style="box"`, the group around it) to the
region, never to a `vcn` container, and represents each attachment as its own box beside it.
The validator enforces this even in hand-written files: it recognises a DRG by the
`ociRole=drg;` style token (set automatically on the `networking_dynamic_routing_gateway_drg`
glyph) or, failing that, a caption containing the word `DRG` or `Dynamic Routing`
(case-insensitive), and raises `ERROR: DRG '...' is inside VCN '...'` (see #11) when that
icon's box lies inside any `vcn` container. Fix: `parent=region_id`, not `parent=vcn_id`.

## 20. *migration* - schema 2: `drgs[]`, `regional`, `peer`; legacy models are migrated with warnings

Schema 1 modelled a DRG as a `hub.items` entry (or a `"drg"` gateway) with no attachment
detail; schema 2 moves it to `model.drgs[]` with a typed `attachments[]` list (`vcn`, `ipsec`,
`virtual_circuit`, `rpc`, `loopback`), adds `services[].regional` (VCN-resident vs. the
Oracle Services Network panel) and `gateways[].peer` (LPG pairing). `build_diagram()` /
`write_diagram()` call `oci_topology.migrate_legacy_model()` first, so a schema-1 model still
renders, but prints `WARNING: legacy model: ...` to stderr and to
`builder.layout_info["warnings"]`. Move the DRG into `drgs[]` (and add explicit attachments)
to silence the warning and get the region-level placement of #19.

## 21. Long display names in a fixed-width box: wrap hints, then grow the box

`whiteSpace=wrap` only breaks a label where the renderer sees a break opportunity - a space or
a hyphen. A parser-style display name such as `drg_attachment_vcn_prod_shared_services_hub` is
one unbreakable word, so a 100 px attachment box renders it as a single ~240 px line straight
across the DRG glyph, the connector and the VCN border. Two steps fix it, both applied by the
recipe: `drawio_builder.wrap_hints()` inserts a zero-width space (`WRAP_HINT`) after `_`, `-`
and `.` so the text can wrap (dots between digits are left alone, so CIDRs keep their line),
and the box height grows to `label_lines(text, w - 8, 11) * LABEL_LINE_H + 8` (minimum
`ATT_H`), with the stack pitch following the real heights. `label_lines()` measures a wrap
hint as a space, so the estimate matches what the browser does. Validator rule 5 now covers
`add_box()` cells too: any wrapped label taller than its box is a `WARNING: label '...' needs
~N lines ...` - a caption still has to exceed three lines to be reported, a box does not.

## 22. Security constructs are badges, not workload icons

A route table or security list drawn as a captioned icon inside a subnet reads as a workload,
and an NSG icon next to a VM says nothing about which VNIC it protects. The team's diagram
guidelines and Oracle's toolkit (slide 18: half-size icons as labels of the subnet box) attach
them to what they govern, so the recipe reads `subnet.route_table`, `subnet.security_lists` and
`item.nsgs` and calls `add_badge()`: 22 px caption-less icons on the subnet's top-right corner
(route table on the corner, security lists to its left) and a shield over the top-right of the
resource's slot. Names live in the tooltip / metadata. Two validator details: a badge may
overlap **only** the cell named in its `ociHost` token (any other overlap is still an error), and
`fit_to_children()` skips badges, so calling it again after the badges exist does not move the
corner. Custom layouts: place the badge after the host's final size is known and pass
`host=<subnet id or icon id>`.
