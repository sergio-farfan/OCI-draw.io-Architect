# draw.io + OCI Icons - Gotchas & Workarounds

10 issues learned the hard way building OCI draw.io diagrams.

## 1. URL-encode SVGs, never base64

draw.io desktop silently ignores base64-encoded SVGs and PNGs. Always use `urllib.parse.quote()`:

```python
encoded = urllib.parse.quote(svg_text, safe='')
data_uri = f"data:image/svg+xml,{encoded}"
```

**Symptom:** Blank/invisible icon cells in the diagram.

## 2. PNG logo SVG wrapper trick

draw.io also ignores base64 PNG data URIs. Wrap the PNG inside an SVG, then URL-encode the SVG:

```python
svg_wrapper = (
    f'<svg xmlns="http://www.w3.org/2000/svg" '
    f'xmlns:xlink="http://www.w3.org/1999/xlink" '
    f'width="{w}" height="{h}">'
    f'<image width="{w}" height="{h}" '
    f'xlink:href="data:image/png;base64,{png_b64}"/>'
    f'</svg>'
)
encoded = urllib.parse.quote(svg_wrapper, safe='')
```

Resize large PNGs first (max ~300px wide) to keep the URL-encoded string manageable.

## 3. OCI SVG viewBox overflow fix

OCI SVGs have content that extends beyond the declared `viewBox`. Translate offsets + scaled paths exceed the width/height, causing icons to appear cropped or clipped.

**Fix:** Parse `translate(tx,ty) scale(sx,sy)` transforms, compute actual bounds (`tx + 100*sx`, `ty + 100*sy`), and expand the viewBox. The `_load_svg()` function in `drawio_builder.py` handles this automatically.

## 4. Cross-container edge parent rule

When connecting icons in different containers (e.g., DRG in Hub to LB in VCN), the edge's `parent` must be a **common ancestor** (e.g., the Region container).

```python
# DRG is in hub, LB is in sn_lb inside vcn
# parent=region (common ancestor), NOT parent=hub or parent=vcn
d.add_edge(drg, lb, "", parent=region, ...)
```

Waypoint coordinates are then in the **parent's coordinate space** (region-relative, not VCN-relative).

**Symptom:** Edge appears in wrong position or is invisible.

## 5. draw.io render caching

draw.io desktop caches rendered diagrams. After changing fonts, styles, or icon data URIs, you must **close and reopen the file** to see changes. Saving and switching tabs is not enough.

**Workaround:** Close the `.drawio` file completely, then reopen it.

## 6. Cell ID uniqueness

Every `mxCell` must have a unique `id`. Duplicate IDs cause silent rendering failures - some cells disappear or edges attach to wrong nodes.

**Fix:** Use an incrementing counter (`DrawioBuilder._next_id()`). Never hardcode IDs.

## 7. `container=1` requirement

Group cells (Region, VCN, Subnet) **must** have `container=1` in their style for child cells to nest correctly. Without it, children placed with `parent=group_id` will render at the root level instead.

**Symptom:** Icons appear at wrong position, outside their intended container.

## 8. Data URI size limits (~20KB)

Very large SVGs or high-resolution PNGs can produce data URIs exceeding ~20KB. draw.io may silently truncate or fail to render these.

**Mitigations:**
- Resize PNGs to max 300px wide before encoding
- OCI SVGs are typically small (~2-5KB) - not usually a problem
- If an SVG is too large, simplify it or convert to optimized PNG first

## 9. Font availability (system fonts only)

draw.io desktop (Electron) only renders **system-installed fonts**. Web fonts, Google Fonts, and CDN-hosted fonts do NOT work.

- **Oracle Sans** - Oracle's brand font. Must be installed manually. The Oracle templates assume this font.
- **Georgia** - Web-safe serif font, works everywhere. Good fallback for titles.
- **Helvetica/Arial** - Safe fallbacks for body text if Oracle Sans is unavailable.

**Symptom:** Text appears in a default font (usually Times New Roman) instead of the specified font.

## 10. Avoid multi-cell OCI Library.xml stencils

The official `OCI Library.xml` for draw.io uses 10-14 cells per icon (multiple layers with fills, strokes, masks). Embedding these programmatically causes:
- Dark rectangle artifacts from `fillColor=#2d5967` background layers
- Massive XML size (each icon is ~2KB of XML vs ~200 bytes for SVG approach)
- Difficulty positioning and connecting edges to multi-cell icons

**Use single-cell SVG embedding instead** (the `add_icon()` approach in `drawio_builder.py`). Clean, single cells that connect and position correctly.

## 11. Container overlap from staggered rows

When subnets of different heights share a visual row, the next row's y-position must be computed from the **tallest** sibling's bottom - not from the main row's height.

**Example failure:**
```
OKE-Worker:    y=50,  h=380 -> bottom=430
OKE-CP-LB:    y=300, h=230 -> bottom=530  (staggered below OKE-Worker-LB)
Bastion:       y=450  <- WRONG, overlaps OKE-CP-LB (bottom 530)!
```

**Fix:** Derive every row position from computed bottoms:
```python
ROW1_BOTTOM = ROW1_Y + SN_H          # 430
CPLB_BOTTOM = CPLB_Y + 230           # 530
ROW2_Y = max(ROW1_BOTTOM, CPLB_BOTTOM) + GAP  # 550 - no overlap
```

**Prevention:** Always run a post-generation overlap check that parses the `.drawio` XML and tests all sibling containers (same parent) for bounding-box intersection. Zero tolerance - any overlap means the layout math is wrong.

---

## Bonus: Arrow Routing Tips

- draw.io's `orthogonalEdgeStyle` does **NOT** auto-avoid obstacles - always use explicit waypoints for complex routes
- Route edges along container margins, then through gaps between containers
- Offset parallel routes by ~8px to prevent overlap
- `exitX/exitY` and `entryX/entryY` use 0-1 range: `0`=left/top, `0.5`=center, `1`=right/bottom
