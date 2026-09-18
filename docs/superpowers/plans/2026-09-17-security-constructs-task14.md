# Security Constructs as Badges (v1.3.0 addendum) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend oci-drawio-architect 1.3.0 so route tables and security lists are drawn as half-size badges straddling the subnet's top-right corner, NSGs as a shield badge on the top-right of the protected resource's icon slot, never as captioned workload icons; the model carries them as `subnet.route_table`, `subnet.security_lists` and `item.nsgs`; `parse_terraform.py` and `query_tenancy.py` fill those fields; the validator accepts the badge geometry and the docs describe the rule.

**Architecture:** `scripts/drawio_builder.py` gains `BADGE_SIZE` / `BADGE_GAP`, `_badge_host()`, `DrawioBuilder.add_badge()` (a caption-less image cell tagged `ociRole=badge;ociHost=<id>`), badge-aware `fit_to_children()` / `_routing_shapes()` / `_attach_captions()` and two validator exclusions (rule 4 badge-vs-host, rule 6 badge-of-endpoint). `scripts/oci_layout.py` gains `_badge_refs()`, `_add_subnet_badges()` (called at the end of `_layout_subnet`) and `_add_nsg_badge()` (called from `_icon_items`). `scripts/parse_terraform.py` resolves `route_table_id`, `security_list_ids`, `nsg_ids` / `network_security_group_ids` and `oci_core_vnic_attachment` NSGs into the fields through the existing `Res.refs`; `scripts/query_tenancy.py` adds the reference fields and copies `nsg_ids` from VNICs to their hosts.

**Tech Stack:** Python 3.9+ standard library only (`xml.etree`, `json`, `argparse`, `unittest`); draw.io desktop optional for PNG export; bash for `pack.sh` / `smoke_test.sh`.

**Spec:** `docs/superpowers/specs/2026-09-17-security-constructs-addendum.md` (addendum to `docs/superpowers/specs/2026-09-17-topology-aware-placement-design.md`)

## Global Constraints

- Python 3.9+ standard library only; no new dependencies (Pillow stays optional and unused by these changes).
- Public MIT repository: no client, tenancy, compartment, colleague or company names and no real IP/CIDR ranges from customer diagrams in code, tests, fixtures, docs or commit messages; refer to "the team's diagram guidelines" and "reviewer feedback".
- Author of every file and commit is Sergio Farfan (repo-local identity `Sergio Farfan <sergio.farfan@gmail.com>`); never credit AI tooling.
- Conventional-commit messages (`feat:`, `fix:`, `test:`, `docs:`, `chore:`); commit after each task; never touch `main` (work on `feature/v1.3.0-topology-aware-placement`).
- Gates after every task: `python3 -m unittest discover -s oci-drawio-architect/tests` must pass and `python3 oci-drawio-architect/scripts/check_overlaps.py <file>` must exit 0 on every diagram the task produces.
- Deterministic output: every cell of the recipe gets a `key=` id derived from the model address; no randomness, no dict-order dependence on Python < 3.7 semantics.
- All paths in commands are relative to the repository root `/Users/sergio.farfan/projects/git/oci-drawio/OCI-Diagrams`; run commands from there.
- Message texts quoted in this plan (validator errors, warnings, labels, tooltips) are contractual: tests assert on them.
- **Ordering and anchors:** Tasks 14 and 15 run after Tasks 1-13 of `docs/superpowers/plans/2026-09-17-topology-aware-placement.md` are committed. The `file:line` hints in the `Files:` blocks were taken from the tree at commit `fde3830` (Task 1 committed, Task 2 not) and will have shifted; **locate every anchor by the quoted content**, never by line number. Every "insert after / replace" instruction quotes the exact text to find.

---

### Task 14: Route table, security list and NSG badges - builder, validator, layout, demo

**Files:**
- Modify: `oci-drawio-architect/scripts/drawio_builder.py` (module constants near `_label_of` / `_attach_captions`, `validate_registry` rules 4 and 6, `DrawioBuilder.fit_to_children`, `DrawioBuilder._routing_shapes`, new method after `place_icons`, `__all__`); `oci-drawio-architect/scripts/check_overlaps.py` (docstring check list); `oci-drawio-architect/scripts/oci_layout.py` (imports, new helpers before `_icon_items`, `_icon_items`, `_layout_subnet`, module docstring); `oci-drawio-architect/examples/generate_demo_diagram.py` (`DEMO_MODEL`, as rewritten by Task 11)
- Test: `oci-drawio-architect/tests/test_builder.py` (new class `TestBadges` after `TestForeignContainment`, before the `# 9. Helpers` banner); `oci-drawio-architect/tests/test_oci_layout.py` (new classes `BadgeLayoutTests`, `DemoBadgeTests` before `if __name__`)

**Interfaces:**
- Consumes: Task 2 `add_icon(...)` slot geometry (`bbox(cid)` = local slot), `ociRole` token convention; Task 3 rule-3 straddle branch `kinds.get(cid) == "icon" and _centre_within(pbox, local, STRADDLE_TOL)` and `STRADDLE_TOL = 4.0`; Task 5 `_layout_subnet(d, vcn_id, subnet, x, y, max_cols, reg, min_w=None) -> (sid, w, h)` (body unchanged by Tasks 5-7 apart from its callers), `_icon_items(d, parent, items, cols, x0=PAD, y0=ROW1_Y, reg=None) -> (ids, bbox)`; Task 5 test helpers `quiet`, `errors_of`, `gw`, `simple_vcn`, `MODEL_GW`; Task 11 `examples.generate_demo_diagram.DEMO_MODEL` and `build(out_path, do_render=False)`; `check_overlaps.main(argv) -> int`.
- Produces: module constants `BADGE_SIZE = 22`, `BADGE_GAP = 4` (exported); helper `_badge_host(entry: dict) -> str | None`; `DrawioBuilder.add_badge(icon_key, cx, cy, parent="1", host=None, size=BADGE_SIZE, key=None, metadata=None, tooltip=None) -> str` (kind `icon`, registry keys `badge=True`, `host=<id or None>`, `label_id=None`, `slot_* = cell`; style tokens `ociRole=badge;ociHost=<host id>`); `fit_to_children` ignores badge children; `_routing_shapes` skips badges hosted by an icon; `_attach_captions` skips badges; rule 4 skips badge/host pairs; rule 6 skips badge obstacles whose host is an endpoint. Layout: `_badge_refs(value) -> list[dict]`, `_badge_tooltip(kind: str, refs: list) -> str`, `_register_badge(reg, refs: list, bid: str) -> None`, `_add_subnet_badges(d, sid, subnet, width, reg) -> list[str]`, `_add_nsg_badge(d, parent, cid, item, reg=None) -> str | None`; cell ids `<subnet id>-rt`, `<subnet id>-sl`, `<host id>-nsg`; tooltips `Route table: <names>`, `Security list: <name>` / `Security lists: <names>`, `NSG: <name>` / `NSGs: <names>`; metadata keys `route_table`, `security_lists`, `nsgs`.

- [x] **Step 1: Write the failing builder tests**

Insert after `class TestForeignContainment` (before the `# 9. Helpers` banner) in `oci-drawio-architect/tests/test_builder.py`:

```python
class TestBadges(TempDirMixin, unittest.TestCase):
    """Route table / security list badges on a subnet corner, NSG badges over an icon (v1.3.0 addendum)."""

    def _subnet(self, d):
        r = d.add_group("us-ashburn-1", 20, 75, 900, 600, group_type="region", key="region")
        v = d.add_group("VCN: a (10.0.0.0/16)", 20, 40, 500, 400, parent=r, group_type="vcn", key="vcn-a")
        s = d.add_group("sn-app (10.0.1.0/24)", db.PAD, db.ROW1_Y, 300, 200, parent=v, group_type="subnet",
                        key="subnet:sn-app")
        ids, _ = d.place_icons(s, [{"label": "App VM\n10.0.1.5", "icon": "vm", "key": "app"},
                                   {"label": "Vault", "icon": "vault", "key": "vault"}], cols=2)
        w, h = d.fit_to_children(s)
        return r, v, s, ids, w, h

    def test_corner_badges_centre_on_the_subnet_corner_and_validate_clean(self):
        d = DrawioBuilder()
        r, v, s, ids, w, h = self._subnet(d)
        rt = d.add_badge("route_table", w, 0, parent=s, host=s, key=f"{s}-rt", tooltip="Route table: rt-app")
        sl = d.add_badge("security_list", w - db.BADGE_SIZE - db.BADGE_GAP, 0, parent=s, host=s, key=f"{s}-sl")
        self.assertEqual((rt, sl), ("subnet-sn-app-rt", "subnet-sn-app-sl"))
        sx, sy, sw, sh = d.abs_bbox(s)
        bx, by, bw, bh = d.abs_bbox(rt)
        self.assertEqual((bw, bh), (db.BADGE_SIZE, db.BADGE_SIZE))
        self.assertAlmostEqual(bx + bw / 2, sx + sw, delta=1.0)          # centred on the top-right corner
        self.assertAlmostEqual(by + bh / 2, sy, delta=1.0)
        lx, ly, lw, lh = d.abs_bbox(sl)
        self.assertAlmostEqual(lx + lw / 2, sx + sw - db.BADGE_SIZE - db.BADGE_GAP, delta=1.0)
        self.assertAlmostEqual(ly + lh / 2, sy, delta=1.0)
        for cid in (v, r):
            d.fit_to_children(cid)
        d.fit_page()
        self.assertEqual(only_errors(d.validate()), [])                  # straddling the corner passes rule 3
        path, _ = self.roundtrip(d)
        errors, _, _, _ = db.validate_file(path)
        self.assertEqual(errors, [])

    def test_badge_style_tokens_geometry_and_no_caption(self):
        d = DrawioBuilder()
        r, v, s, ids, w, h = self._subnet(d)
        rt = d.add_badge("route_table", w, 0, parent=s, host=s, key="rt",
                         metadata={"route_table": "rt-app"}, tooltip="Route table: rt-app")
        c = cell(d.root, rt)
        tok = tokens(c.get("style"))
        self.assertEqual((tok["shape"], tok["ociRole"], tok["ociHost"], tok["imageAspect"]), ("image", "badge", s, "1"))
        self.assertTrue(tok["image"].startswith(DATA_URI_PREFIX))
        self.assertEqual(geom(c), {"x": w - 11.0, "y": -11.0, "width": 22.0, "height": 22.0})
        e = d._cells[rt]
        self.assertEqual((e["kind"], e["badge"], e["host"], e["label_id"]), ("icon", True, s, None))
        self.assertEqual((e["slot_x"], e["slot_y"], e["slot_w"], e["slot_h"]), (w - 11.0, -11.0, 22.0, 22.0))
        obj = wrapper(d.root, rt)
        self.assertEqual((obj.tag, obj.get("tooltip"), obj.get("route_table")), ("object", "Route table: rt-app", "rt-app"))
        self.assertEqual(len([t for t in d._cells.values() if t["kind"] == "text"]), 2)   # only the two icon captions

    def test_nsg_badge_sits_inside_the_host_slot_and_may_cover_the_glyph(self):
        d = DrawioBuilder()
        r, v, s, ids, w, h = self._subnet(d)
        app = ids[0]
        sx, sy, sw, sh = d.bbox(app)
        nsg = d.add_badge("nsg", sx + db.ICON_W - db.BADGE_SIZE / 2, sy + db.BADGE_SIZE / 2, parent=s, host=app,
                          key="app-nsg", tooltip="NSG: nsg-app")
        hx, hy, hw, hh = d.abs_bbox(app)
        nx, ny, nw, nh = d.abs_bbox(nsg)
        self.assertEqual((nx + nw, ny, nw, nh), (hx + hw, hy, 22.0, 22.0))           # top-right of the 75x95 slot
        gx, gy, gw_, gh = d._abs_cell(app)
        self.assertTrue(nx < gx + gw_ and ny + nh > gy)                              # overlaps the 70x70 glyph cell
        self.assertEqual(only_errors(d.validate()), [])                              # ... which is allowed for the host
        path, _ = self.roundtrip(d)
        self.assertEqual(db.validate_file(path)[0], [])

    def test_badge_over_a_foreign_icon_is_still_a_collision(self):
        d = DrawioBuilder()
        g = d.add_group("R", 0, 0, 400, 300, key="r")
        d.add_icon("A", "vm", 20, 50, parent=g, key="a")
        d.add_icon("B", "vm", 150, 50, parent=g, key="b")
        d.add_badge("nsg", 20 + db.ICON_W - 11, 50 + 11, parent=g, host="b", key="stray")   # over A, hosted by B
        errors = only_errors(d.validate())
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("'A'", errors[0])
        self.assertIn("overlaps", errors[0])

    def test_two_corner_badges_do_not_collide_and_fit_ignores_them(self):
        d = DrawioBuilder()
        r, v, s, ids, w, h = self._subnet(d)
        d.add_badge("route_table", w, 0, parent=s, host=s, key="rt")
        d.add_badge("security_list", w - db.BADGE_SIZE - db.BADGE_GAP, 0, parent=s, host=s, key="sl")
        self.assertEqual(d.fit_to_children(s), (w, h))                    # badges never grow their host
        sib = d.add_group("sn-db (10.0.2.0/24)", db.PAD + w + db.GAP, db.ROW1_Y, 200, 150, parent=v,
                          group_type="subnet", key="sn-db")
        d.place_icons(sib, [("ADB", "adb")], cols=1)
        d.fit_to_children(sib)
        self.assertEqual(only_errors(d.validate()), [])                   # the 20 px gutter clears the 11 px overhang

    def test_routing_obstacles_keep_corner_badges_and_drop_icon_badges(self):
        d = DrawioBuilder()
        r, v, s, ids, w, h = self._subnet(d)
        rt = d.add_badge("route_table", w, 0, parent=s, host=s, key="rt")
        nsg = d.add_badge("nsg", db.PAD + db.ICON_W - 11, db.ROW1_Y + 11, parent=s, host=ids[0], key="nsg")
        _, obstacles = d._routing_shapes(d._page_idx)
        self.assertIn(rt, obstacles)
        self.assertNotIn(nsg, obstacles)

    def test_add_badge_rejects_bad_input_and_constants_are_exported(self):
        d = DrawioBuilder()
        with self.assertRaises(ValueError):
            d.add_badge("route_table", 0, 0, parent="nope")
        with self.assertRaises(ValueError):
            d.add_badge("route_table", 0, 0, size=0)
        with self.assertRaises(ValueError):
            d.add_badge("no_such_icon_key", 0, 0)
        self.assertEqual((db.BADGE_SIZE, db.BADGE_GAP), (22, 4))
        for name in ("BADGE_SIZE", "BADGE_GAP"):
            self.assertIn(name, db.__all__)
        self.assertIsNone(db._badge_host({"style": "shape=image;image=x;"}))
        self.assertEqual(db._badge_host({"style": "shape=image;ociRole=badge;ociHost=app;image=x;"}), "app")
        self.assertEqual(db._badge_host({"style": "shape=image;ociRole=badge;ociHost=;image=x;"}), "")
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_builder.TestBadges 2>&1 | tail -6`
Expected: 7 tests, all ERROR with `AttributeError: 'DrawioBuilder' object has no attribute 'add_badge'` (the `_subnet` helper itself passes) or `AttributeError: module 'drawio_builder' has no attribute 'BADGE_SIZE'`.

- [x] **Step 3: Implement the constants, `_badge_host`, `add_badge` and the badge-aware builder paths**

In `oci-drawio-architect/scripts/drawio_builder.py`:

1. Insert immediately before `def _attach_captions(registry: dict, boxes: dict) -> None:` (after the Task 3 helpers `_centre_within` / `_group_type_of` / `_is_drg_icon`):

```python
# Security-construct badges (v1.3.0 addendum): half-size caption-less icons
# (toolkit slide 18) centred on a subnet's top-right corner (route table,
# security lists) or laid over the top-right of a host icon's slot (NSG).
BADGE_SIZE = 22
BADGE_GAP = 4


def _badge_host(entry: dict):
    """Host cell id of a badge (style ``ociRole=badge;ociHost=<id>``); None for non-badges."""
    tok = _style_tokens(entry.get("style", ""))
    if tok.get("ociRole") != "badge":
        return None
    return tok.get("ociHost") or ""


```

2. In `_attach_captions`, replace

```python
        if e.get("vertex") != "1" or _kind(e) != "icon" or cid not in boxes:
            continue
        ib = boxes[cid]
```

with

```python
        if e.get("vertex") != "1" or _kind(e) != "icon" or cid not in boxes:
            continue
        if _badge_host(e) is not None:
            continue                      # badges have no caption
        ib = boxes[cid]
```

3. In `validate_registry` rule 4 (`# 4. non-container vertex collisions`), replace

```python
            a, b = leaves[i], leaves[j]
            if _is_ancestor(registry, a, b) or _is_ancestor(registry, b, a):
                continue
            ba, bb = boxes[a], boxes[b]
```

with

```python
            a, b = leaves[i], leaves[j]
            if _is_ancestor(registry, a, b) or _is_ancestor(registry, b, a):
                continue
            if _badge_host(registry[a]) == b or _badge_host(registry[b]) == a:
                continue                  # a badge may cover its own host icon (NSG shield)
            ba, bb = boxes[a], boxes[b]
```

4. In rule 6 (`# 6. estimated edge crossings`), replace

```python
        for oid, ob in obstacles.items():
            if oid in (e.get("source"), e.get("target")):
                continue
```

with

```python
        for oid, ob in obstacles.items():
            if oid in (e.get("source"), e.get("target")):
                continue
            if _badge_host(registry[oid]) in (e.get("source"), e.get("target")):
                continue                  # a badge over an endpoint is part of that endpoint
```

5. In `fit_to_children`, replace

```python
            if ke["parent"] != cid or ke["kind"] in ("edge", "layer"):
                continue
```

with

```python
            if ke["parent"] != cid or ke["kind"] in ("edge", "layer") or ke.get("badge"):
                continue                  # badges straddle the border on purpose; they never grow the host
```

6. In `_routing_shapes`, replace

```python
            elif e["kind"] == "icon":
                # slot + caption as one block so connectors never squeeze
```

with

```python
            elif e["kind"] == "icon" and e.get("badge"):
                host = self._cells.get(e.get("host") or "")
                if host is not None and host["kind"] == "icon":
                    continue              # covered by the host icon's footprint obstacle
                ax, ay, w, h = self.abs_bbox(cid)
                obstacles[cid] = _Box(ax, ay, w, h)      # corner badge: keep connectors off the corner
            elif e["kind"] == "icon":
                # slot + caption as one block so connectors never squeeze
```

7. Insert before `    # -- images / text -------------------------------------------------------` (after `place_icons`, and after Task 2's `add_box`):

```python
    # -- badges ----------------------------------------------------------------
    def add_badge(self, icon_key, cx, cy, parent="1", host=None, size=BADGE_SIZE,
                  key=None, metadata=None, tooltip=None) -> str:
        """Add a caption-less half-size icon centred on (cx, cy) in parent coordinates.

        Badges mark route tables / security lists on a subnet's top-right corner
        and NSGs on the top-right of a resource's icon slot. ``host`` is the cell
        the badge decorates (the subnet or the icon): the validator lets a badge
        overlap its own host, ``fit_to_children()`` ignores badges and the router
        ignores badges laid over an icon. Returns the badge cell id.
        """
        parent = self._check_parent(parent, "add_badge")
        if size <= 0:
            raise ValueError("add_badge: size must be positive")
        data_uri, _nw, _nh = _load_svg(icon_key)
        x, y = cx - size / 2, cy - size / 2
        host_id = "" if host is None else str(host)
        style = (
            "shape=image;verticalLabelPosition=bottom;verticalAlign=top;imageAspect=1;aspect=fixed;"
            f"ociRole=badge;ociHost={host_id};image={data_uri};"
        )
        cid = self._emit_vertex("", style, parent, x, y, size, size, metadata=metadata, tooltip=tooltip,
                                cid=self._new_id(key) if key is not None else None)
        self._register(cid, "icon", x, y, size, size, parent, label="", icon_key=icon_key,
                       slot_x=x, slot_y=y, slot_w=size, slot_h=size, label_id=None,
                       badge=True, host=host_id or None)
        return cid

```

8. Add `"BADGE_SIZE", "BADGE_GAP",` to `__all__` right after `"ICON_FOOTPRINT_H",`. In the module docstring bullet that describes `validate()`, append the sentence `Badges (``add_badge()``, style ``ociRole=badge``) may straddle their subnet's corner and cover their own host icon.`

In `oci-drawio-architect/scripts/check_overlaps.py`, insert after the docstring line `  - icons / captions / text cells overlapping each other` the line:

```
    (badges - style ociRole=badge - may straddle their subnet's corner and cover their own host icon)
```

- [x] **Step 4: Run the builder tests and the suite**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_builder.TestBadges -v 2>&1 | tail -10 && cd .. && python3 -m unittest discover -s oci-drawio-architect/tests 2>&1 | tail -3`
Expected: 7 PASS; suite `OK`. If `test_corner_badges_centre_on_the_subnet_corner_and_validate_clean` reports `extends outside its parent`, rule 3 lost the Task 3 branch `if k == "icon" and _centre_within(pbox, local, STRADDLE_TOL): continue` - restore it as written in the main plan (Task 3 Step 4); do not add a badge-specific tolerance.

- [x] **Step 5: Write the failing layout tests**

Append to `oci-drawio-architect/tests/test_oci_layout.py` (before `if __name__`):

```python
BADGED = {
    "subject": "badges", "region": "us-ashburn-1",
    "vcns": [{"name": "a", "cidr": "10.0.0.0/16", "subnets": [
        {"name": "sn-lb", "cidr": "10.0.0.0/24", "tier": "lb", "public": True,
         "route_table": "rt-public", "security_lists": ["sl-lb", {"name": "sl-shared", "address": "sl-shared"}],
         "items": [{"icon": "load_balancer", "label": "Public LB", "address": "lb", "nsgs": ["nsg-lb"]}]},
        {"name": "sn-app", "cidr": "10.0.1.0/24", "tier": "app",
         "route_table": {"name": "rt-private", "address": "rt-private"},
         "items": [{"icon": "vm", "label": "App VM\n10.0.1.5", "address": "app",
                    "nsgs": [{"name": "nsg-app", "address": "nsg-app"}, "nsg-mgmt"]},
                   {"icon": "vault", "label": "Vault", "address": "vault"}]},
        {"name": "sn-db", "cidr": "10.0.2.0/24", "tier": "data", "security_lists": ["sl-db"],
         "items": [{"icon": "autonomous_db", "label": "ADB", "address": "adb", "nsgs": ["nsg-db"]}]}],
        "gateways": [gw("sgw", "service_gateway", "Service\nGateway", "sgw")]}],
    "edges": [{"source": "lb", "target": "app", "label": "8080", "kind": "data"},
              {"source": "app", "target": "adb", "label": "1522", "kind": "data"},
              {"source": "rt-private", "target": "sgw", "label": "OSN", "kind": "control"}],
}


def badge_style(d, cid):
    """Style tokens of any cell, including <object>-wrapped ones (badges carry tooltips)."""
    return db._style_tokens(db.build_cell_registry(d.root)[cid]["style"])


class BadgeLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = quiet(ol.build_diagram, BADGED)

    def test_route_table_badge_is_centred_on_the_subnet_top_right_corner(self):
        for name in ("sn-lb", "sn-app"):
            sx, sy, sw, sh = self.d.abs_bbox(f"subnet-{name}")
            bx, by, bw, bh = self.d.abs_bbox(f"subnet-{name}-rt")
            self.assertAlmostEqual(bx + bw / 2, sx + sw, delta=1.0, msg=name)
            self.assertAlmostEqual(by + bh / 2, sy, delta=1.0, msg=name)
            self.assertEqual((bw, bh), (ol.BADGE_SIZE, ol.BADGE_SIZE), name)
            self.assertEqual(self.d._cells[f"subnet-{name}-rt"]["parent"], f"subnet-{name}", name)

    def test_security_list_badge_sits_left_of_the_route_table_or_takes_the_corner(self):
        sx, sy, sw, sh = self.d.abs_bbox("subnet-sn-lb")
        bx, by, bw, bh = self.d.abs_bbox("subnet-sn-lb-sl")
        self.assertAlmostEqual(bx + bw / 2, sx + sw - ol.BADGE_SIZE - ol.BADGE_GAP, delta=1.0)
        self.assertAlmostEqual(by + bh / 2, sy, delta=1.0)
        dx, dy, dw, dh = self.d.abs_bbox("subnet-sn-db")                 # security lists, no route table
        cx, cy, cw, ch = self.d.abs_bbox("subnet-sn-db-sl")
        self.assertAlmostEqual(cx + cw / 2, dx + dw, delta=1.0)
        self.assertAlmostEqual(cy + ch / 2, dy, delta=1.0)
        self.assertNotIn("subnet-sn-db-rt", self.d._cells)
        self.assertNotIn("subnet-sn-app-sl", self.d._cells)

    def test_nsg_badge_sits_in_the_top_right_of_the_host_slot(self):
        for host in ("lb", "app", "adb"):
            hx, hy, hw, hh = self.d.abs_bbox(host)
            nx, ny, nw, nh = self.d.abs_bbox(f"{host}-nsg")
            self.assertEqual((nx + nw, ny, nw, nh), (hx + hw, hy, ol.BADGE_SIZE, ol.BADGE_SIZE), host)
            self.assertEqual(self.d._cells[f"{host}-nsg"]["parent"], self.d._cells[host]["parent"], host)
        self.assertNotIn("vault-nsg", self.d._cells)

    def test_badges_have_no_caption_and_carry_names_in_tooltips(self):
        tips = {el.get("id"): el.get("tooltip") for el in self.d.root if el.tag == "object" and el.get("tooltip")}
        self.assertEqual(tips["subnet-sn-lb-rt"], "Route table: rt-public")
        self.assertEqual(tips["subnet-sn-lb-sl"], "Security lists: sl-lb, sl-shared")
        self.assertEqual(tips["subnet-sn-db-sl"], "Security list: sl-db")
        self.assertEqual(tips["app-nsg"], "NSGs: nsg-app, nsg-mgmt")
        self.assertEqual(tips["lb-nsg"], "NSG: nsg-lb")
        meta = {el.get("id"): el for el in self.d.root if el.tag == "object"}
        self.assertEqual(meta["subnet-sn-lb-sl"].get("security_lists"), "sl-lb, sl-shared")
        self.assertEqual(meta["app-nsg"].get("nsgs"), "nsg-app, nsg-mgmt")
        for cid in ("subnet-sn-lb-rt", "subnet-sn-lb-sl", "app-nsg"):
            self.assertIsNone(self.d._cells[cid]["label_id"])
            self.assertEqual(badge_style(self.d, cid)["ociRole"], "badge")
        self.assertEqual(badge_style(self.d, "app-nsg")["ociHost"], "app")
        self.assertEqual(badge_style(self.d, "subnet-sn-lb-rt")["ociHost"], "subnet-sn-lb")

    def test_badge_addresses_resolve_as_edge_endpoints(self):
        edge = next(e for e in self.d._cells.values() if e["kind"] == "edge" and e.get("target") == "sgw")
        self.assertEqual(edge["source"], "subnet-sn-app-rt")

    def test_validates_and_passes_the_gate(self):
        import check_overlaps
        self.assertEqual(errors_of(self.d), [])
        with tempfile.TemporaryDirectory() as tmp:
            out = quiet(ol.write_diagram, BADGED, Path(tmp) / "badges.drawio")
            self.assertEqual(quiet(check_overlaps.main, [str(out)]), 0)
            text = out.read_text(encoding="utf-8")
            self.assertEqual(text.count("ociRole=badge"), 7)            # rt+sl, rt, sl + 3 NSG badges

    def test_models_without_the_fields_draw_no_badges(self):
        d = quiet(ol.build_diagram, MODEL_GW)
        self.assertEqual([c for c, e in d._cells.items() if e.get("badge")], [])
        self.assertEqual(ol._badge_refs(None), [])
        self.assertEqual(ol._badge_refs("rt"), [{"name": "rt", "address": None}])
        self.assertEqual(ol._badge_refs([{"name": "a", "address": "x"}, "b", {"label": "c"}, ""]),
                         [{"name": "a", "address": "x"}, {"name": "b", "address": None}, {"name": "c", "address": None}])
        self.assertEqual(ol._badge_tooltip("NSG", ol._badge_refs(["a", "b"])), "NSGs: a, b")


class DemoBadgeTests(unittest.TestCase):
    def test_demo_model_carries_badges_on_both_layout_pages(self):
        import check_overlaps
        sys.path.insert(0, str(TESTS_DIR.parent / "examples"))
        import generate_demo_diagram as demo
        subnets = {s["name"]: s for v in demo.DEMO_MODEL["vcns"] for s in v["subnets"]}
        self.assertEqual(subnets["sn-public"]["route_table"], "rt-public")
        self.assertEqual(subnets["sn-app"]["security_lists"], ["sl-app"])
        items = {i["address"]: i for s in subnets.values() for i in s["items"]}
        self.assertEqual((items["lb"]["nsgs"], items["app"]["nsgs"], items["adb"]["nsgs"]),
                         (["nsg-lb"], ["nsg-app"], ["nsg-db"]))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "demo.drawio"
            quiet(demo.build, out)
            text = out.read_text(encoding="utf-8")
            self.assertEqual(text.count("ociRole=badge"), 14)          # 7 badges on each of the two layout pages
            self.assertEqual(quiet(check_overlaps.main, [str(out)]), 0)
```

- [x] **Step 6: Run the tests to verify they fail**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_oci_layout.BadgeLayoutTests tests.test_oci_layout.DemoBadgeTests 2>&1 | tail -8`
Expected: `BadgeLayoutTests` errors in `setUpClass` with `ValueError: edge endpoint 'rt-private' not found` (no badge cell registers the address yet); `DemoBadgeTests` fails with `KeyError: 'route_table'`.

- [x] **Step 7: Implement the layout helpers**

In `oci-drawio-architect/scripts/oci_layout.py`:

1. In the `from drawio_builder import (` block add `BADGE_GAP, BADGE_SIZE,` as the first names (keep the list alphabetical: `BADGE_GAP, BADGE_SIZE, COL_W, COLORS, ...`).

2. Insert immediately before `def _icon_items(d: DrawioBuilder, parent, items, cols, x0=PAD, y0=ROW1_Y, reg=None):`:

```python
def _badge_refs(value) -> list:
    """Normalise ``str | dict | list[str | dict]`` into ``[{"name", "address"}]`` (empty for None)."""
    if value is None or value == "" or value == []:
        return []
    items = value if isinstance(value, (list, tuple)) else [value]
    out = []
    for it in items:
        if isinstance(it, dict):
            name = str(it.get("name") or it.get("label") or it.get("address") or "").strip()
            addr = it.get("address")
        else:
            name, addr = str(it).strip(), None
        if name:
            out.append({"name": name, "address": str(addr) if addr else None})
    return out


def _badge_tooltip(kind: str, refs: list) -> str:
    return f"{kind}{'s' if len(refs) > 1 else ''}: " + ", ".join(r["name"] for r in refs)


def _register_badge(reg, refs: list, bid: str) -> None:
    if reg is None:
        return
    for r in refs:
        if r["address"]:
            reg.by_address.setdefault(r["address"], bid)   # first badge wins: several subnets share a construct


def _add_subnet_badges(d: DrawioBuilder, sid: str, subnet: dict, width, reg) -> list:
    """Route-table / security-list badges straddling the subnet's top-right corner.

    Route table centred on the corner, security lists one badge to its left
    (toolkit slide 18: half-size icons used as labels of the subnet box).
    Returns the badge ids (0-2).
    """
    ids = []
    cx = width
    rt = _badge_refs(subnet.get("route_table"))
    if rt:
        bid = d.add_badge("route_table", cx, 0, parent=sid, host=sid, key=f"{sid}-rt",
                          tooltip=_badge_tooltip("Route table", rt),
                          metadata={"route_table": ", ".join(r["name"] for r in rt)})
        _register_badge(reg, rt, bid)
        ids.append(bid)
        cx -= BADGE_SIZE + BADGE_GAP
    sls = _badge_refs(subnet.get("security_lists"))
    if sls:
        bid = d.add_badge("security_list", cx, 0, parent=sid, host=sid, key=f"{sid}-sl",
                          tooltip=_badge_tooltip("Security list", sls),
                          metadata={"security_lists": ", ".join(r["name"] for r in sls)})
        _register_badge(reg, sls, bid)
        ids.append(bid)
    return ids


def _add_nsg_badge(d: DrawioBuilder, parent, cid: str, item: dict, reg=None):
    """NSG shield badge over the top-right of the host icon's slot; None when the item has no ``nsgs``."""
    nsgs = _badge_refs(item.get("nsgs"))
    if not nsgs:
        return None
    sx, sy, _sw, _sh = d.bbox(cid)
    bid = d.add_badge("nsg", sx + ICON_W - BADGE_SIZE / 2, sy + BADGE_SIZE / 2, parent=parent, host=cid,
                      key=f"{cid}-nsg", tooltip=_badge_tooltip("NSG", nsgs),
                      metadata={"nsgs": ", ".join(r["name"] for r in nsgs)})
    _register_badge(reg, nsgs, bid)
    return bid


```

3. In `_icon_items`, replace

```python
    ids, bbox = d.place_icons(parent, specs, cols=cols, x0=x0, y0=y0)
    if reg is not None:
```

with

```python
    ids, bbox = d.place_icons(parent, specs, cols=cols, x0=x0, y0=y0)
    for it, cid in zip(items, ids):
        _add_nsg_badge(d, parent, cid, it, reg)
    if reg is not None:
```

4. In `_layout_subnet`, replace the tail

```python
        if min_w:
            w = max(w, min_w)
        d.resize(sid, w=w, h=h)
    return sid, w, h
```

with

```python
        if min_w:
            w = max(w, min_w)
        d.resize(sid, w=w, h=h)
    _add_subnet_badges(d, sid, subnet, w, reg)       # after the final size: badges sit on the corner
    return sid, w, h
```

5. Module docstring (schema block as rewritten by Task 8): replace the line

```
                                 "address": "lb", "metadata": {"ocid": "..."}, "tooltip": "..."}]}],
```

with

```
                                 "address": "lb", "metadata": {"ocid": "..."}, "tooltip": "...",
                                 "nsgs": ["nsg-lb"]}],
                      "route_table": "rt-lb", "security_lists": ["sl-lb"]}],
```

and append after the paragraph that starts `Edge "kind": data (solid, open arrow)` the paragraph:

```
Security constructs are badges, never workload icons: "route_table" (str or {"name", "address"})
and "security_lists" ([str or {"name", "address"}]) on a subnet draw half-size icons straddling
the subnet's top-right corner (route table on the corner, security lists to its left); "nsgs"
([str or {"name", "address"}]) on any item draws a shield badge over the top-right of that
item's icon slot. Badges have no caption; names go to the tooltip and metadata. An entry with an
"address" can be an edge endpoint.
```

- [x] **Step 8: Add the fields to the demo model**

In `oci-drawio-architect/examples/generate_demo_diagram.py` (`DEMO_MODEL` from Task 11):

- In the `vcn-hub` subnet `sn-public`, replace `"tier": "lb", "public": True, "items": [` with `"tier": "lb", "public": True, "route_table": "rt-public", "security_lists": ["sl-public"], "items": [`.
- In that subnet replace `{"icon": "load_balancer", "label": "Public LB", "address": "lb"},` with `{"icon": "load_balancer", "label": "Public LB", "address": "lb", "nsgs": ["nsg-lb"]},`.
- In the `vcn-spoke` subnet `sn-app`, replace `"tier": "app", "items": [` with `"tier": "app", "route_table": "rt-private", "security_lists": ["sl-app"], "items": [`.
- In that subnet replace `"metadata": {"ocid": "ocid1.instance.oc1..demo"}, "tooltip": "primary app node"}]},` with `"metadata": {"ocid": "ocid1.instance.oc1..demo"}, "tooltip": "primary app node", "nsgs": ["nsg-app"]}]},`.
- In the subnet `sn-data`, replace `{"icon": "autonomous_db", "label": "Autonomous\nDatabase", "address": "adb"}]}],` with `{"icon": "autonomous_db", "label": "Autonomous\nDatabase", "address": "adb", "nsgs": ["nsg-db"]}]}],` - note the **four** closers `}]}],`: `sn-data` is the last subnet of `vcn-spoke`, so the item dict, the `items` list, the subnet dict and the `subnets` list all close on that line before the comma that leads into `"services"`. Do not drop the trailing `]` (that would fold `services` / `gateways` into the subnet dict).
- In the module docstring, after the sentence that ends `kinds (data, control, association, attachment) and the legend.` add: `Route tables and security lists appear as badges on the subnets' top-right corners and NSGs as shield badges on the load balancer, the app VM and the database.` The sentence is hard-wrapped in Task 11's docstring (`... the four connector` / `kinds (data, control, association, attachment) and the legend.`), so search for the second line, not for the whole sentence.

- [x] **Step 9: Run the tests, the suite and the gates**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_oci_layout.BadgeLayoutTests tests.test_oci_layout.DemoBadgeTests -v 2>&1 | tail -12 && cd .. && python3 -m unittest discover -s oci-drawio-architect/tests 2>&1 | tail -3 && python3 oci-drawio-architect/examples/generate_demo_diagram.py /tmp/v13-badges-demo.drawio && python3 oci-drawio-architect/scripts/check_overlaps.py /tmp/v13-badges-demo.drawio && python3 oci-drawio-architect/examples/generate_reference_layout.py /tmp/v13-badges-ref.drawio && python3 oci-drawio-architect/scripts/check_overlaps.py /tmp/v13-badges-ref.drawio && SMOKE_SKIP_PNG=1 oci-drawio-architect/scripts/smoke_test.sh`
Expected: 8 PASS; suite `OK`; both `check_overlaps.py` lines print `OK: no container overlaps or layout errors`; `Smoke test passed.`. The reference output is byte-for-byte the Task 11 output (its model has no badge fields). If the demo gate reports `overlaps '(unlabelled)'`, a badge covers a leaf other than its host: check that `_add_nsg_badge` passes `host=cid` (the icon id) and that `_add_subnet_badges` receives the subnet's final width (it must run after `fit_to_children` / `resize`).
If instead the message pairs a **gateway caption** with `'(unlabelled)'`, it is the known clearance limitation in spec section 6: a side gateway's 105 px opaque caption starts 15 px left of its slot, so it overlaps a corner badge's x range by 4 px, and a subnet row whose top edge falls inside a side caption band (VCN-local `y` within 11 px of `SIDE_GW_Y0 + k * SIDE_GW_PITCH + ICON_H + LABEL_GAP`, i.e. `147 + 160k`) collides with it. That needs two or more right-border gateways plus a second subnet row or a stretched data-tier subnet; the demo and the fixtures do not hit it. Do **not** paper over it with a new validator tolerance or by moving the badge - record it and raise it as a separate task (spec section 12).

- [x] **Step 10: Commit**

```bash
git add oci-drawio-architect/scripts/drawio_builder.py oci-drawio-architect/scripts/check_overlaps.py oci-drawio-architect/scripts/oci_layout.py oci-drawio-architect/examples/generate_demo_diagram.py oci-drawio-architect/tests/test_builder.py oci-drawio-architect/tests/test_oci_layout.py
git commit -m "feat(builder,layout): route table / security list corner badges and NSG icon badges"
```

---

### Task 15: Parser and tenancy badge fields, documentation

**Files:**
- Modify: `oci-drawio-architect/tests/fixtures/terraform/three_tier/compute.tf` (load balancer block, end of file), `oci-drawio-architect/tests/fixtures/terraform/three_tier/network.tf` (end of file), `oci-drawio-architect/tests/fixtures/tenancy/topology_bundle.json` (`vcn_topology.data.entities`)
- Modify: `oci-drawio-architect/scripts/parse_terraform.py` (module docstring, constants after `CONTROL_TYPES`, `new_subnet`, new `badge_ref` after `new_gateway`, `_validate_item`, new `_validate_badge_refs`, `validate_model` subnet loop, `ModelBuilder._build_subnets`, new `_badge_ref` / `_nsg_refs` / `_build_vnic_nsgs`, `_build_items`, `build`); `oci-drawio-architect/scripts/query_tenancy.py` (docstring, `_REF_FIELDS`, `apply_relationships`)
- Modify (docs): `oci-drawio-architect/skills/oci-drawio-architect/SKILL.md`, `oci-drawio-architect/commands/drawio-architect.md`, `oci-drawio-architect/skills/oci-drawio-architect/references/oracle-styles.md`, `oci-drawio-architect/skills/oci-drawio-architect/references/gotchas.md`, `oci-drawio-architect/CHANGELOG.md`, `README.md`, `oci-drawio-architect/README.md`, `CLAUDE.md`
- Test: `oci-drawio-architect/tests/test_parse_terraform.py` (`HclThreeTierTests`, `HelperTests`), `oci-drawio-architect/tests/test_query_tenancy.py` (`BundleModelTests`, `HelperTests`), `oci-drawio-architect/tests/test_oci_layout.py` (`EndToEndTests`, new test methods)

**Interfaces:**
- Consumes: Task 14 (`_add_subnet_badges`, `_add_nsg_badge`, `add_badge`, ids `<subnet id>-rt` / `-sl` / `<host id>-nsg`); Task 9 `ModelBuilder` (`first_ref(res, attrs, rtype=None, rtypes=None)`, `all_refs(res, attrs, rtypes=None)`, `item_index`, `build()` order `_build_items -> _build_edges`), `new_subnet(name, address, cidr=None, public=None, tier=None)`, `_validate_item(errors, item, path, with_metadata, icon_keys)`, `validate_model`, `Res(address, rtype, name, attrs=None, refs=None)`; Task 10 `query_tenancy._REF_FIELDS`, `apply_relationships`, `normalise_entity`; Task 12 documentation text (anchors quoted below); Task 13 `EndToEndTests._gate(model, name)`.
- Produces: `parse_terraform` constants `ROUTE_TABLE_TYPE = "oci_core_route_table"`, `SECURITY_LIST_TYPE = "oci_core_security_list"`, `NSG_TYPE = "oci_core_network_security_group"`, `NSG_ATTRS = ("nsg_ids", "network_security_group_ids")`, `VNIC_ATTACHMENT_TYPES = frozenset({"oci_core_vnic_attachment", "oci_core_vnic"})`; `badge_ref(name: str, address: str | None = None) -> dict` (`{"name", "address"}`); `new_subnet()` adds `"route_table": None, "security_lists": []`; `_validate_badge_refs(errors, value, path, single=False) -> None`; `ModelBuilder._badge_ref(res, default) -> dict`, `_nsg_refs(res) -> list[dict]`, `_build_vnic_nsgs() -> None`; items carry `nsgs` only when non-empty. `query_tenancy._REF_FIELDS` gains `security_list_ids`, `nsg_ids`, `network_security_group_ids`; VNIC -> host copies `nsg_ids`. Validation messages: `<path>.route_table: expected str, got int`, `<path>.security_lists[0].name: expected str, got NoneType`, `<path>.items[0].nsgs: expected list, got str`. (Only single-type `_expect` calls read well: `_expect` formats the expected type as `getattr(types, "__name__", types)`, so the tuple call `_expect(errors, ref.get("address"), (str, type(None)), f"{rp}.address")` prints `expected (<class 'str'>, <class 'NoneType'>), got int`. That is the existing helper's behaviour, no test asserts it - do not "fix" `_expect`.)

- [ ] **Step 1: Extend the fixtures**

`oci-drawio-architect/tests/fixtures/terraform/three_tier/compute.tf`: in `resource "oci_load_balancer_load_balancer" "public"` replace

```hcl
  subnet_ids     = [oci_core_subnet.lb.id]
  is_private     = false
```

with

```hcl
  subnet_ids     = [oci_core_subnet.lb.id]
  is_private     = false
  network_security_group_ids = [oci_core_network_security_group.lb.id]
```

and append at the end of the file:

```hcl

# Secondary VNIC: its NSGs join the instance's NSG badge (oci_core_instance.app[0] resolves to the base address).
resource "oci_core_vnic_attachment" "app_mgmt" {
  instance_id  = oci_core_instance.app[0].id
  display_name = "vnic-mgmt"
  create_vnic_details {
    subnet_id = oci_core_subnet.app.id
    nsg_ids   = [oci_core_network_security_group.mgmt.id, oci_core_network_security_group.app.id]
  }
}
```

`oci-drawio-architect/tests/fixtures/terraform/three_tier/network.tf`: append at the end of the file:

```hcl

resource "oci_core_network_security_group" "lb" {
  compartment_id = oci_identity_compartment.app.id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "nsg-lb"
}

resource "oci_core_network_security_group" "mgmt" {
  compartment_id = oci_identity_compartment.app.id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "nsg-mgmt"
}
```

`oci-drawio-architect/tests/fixtures/tenancy/topology_bundle.json`, inside `vcn_topology.data.entities`:

- In the `sn-lb-public` Subnet entity replace `"route-table-id": "ocid1.routetable.oc1.eu-frankfurt-1.aaaaaaaartpublic0001", "lifecycle-state": "AVAILABLE"},` with

```json
         "route-table-id": "ocid1.routetable.oc1.eu-frankfurt-1.aaaaaaaartpublic0001",
         "security-list-ids": ["ocid1.securitylist.oc1.eu-frankfurt-1.aaaaaaaaslapp0000001"], "lifecycle-state": "AVAILABLE"},
```

- In the Vnic entity replace `"privateIp": "10.0.1.5", "lifecycleState": "AVAILABLE"},` with

```json
         "privateIp": "10.0.1.5", "nsgIds": ["ocid1.networksecuritygroup.oc1.eu-frankfurt-1.aaaaaaaansgapp000001"],
         "lifecycleState": "AVAILABLE"},
```

- In the LoadBalancer entity replace `"subnet-ids": ["ocid1.subnet.oc1.eu-frankfurt-1.aaaaaaaasnlb00000001"], "lifecycle-state": "ACTIVE"},` with

```json
         "subnet-ids": ["ocid1.subnet.oc1.eu-frankfurt-1.aaaaaaaasnlb00000001"],
         "network-security-group-ids": ["ocid1.networksecuritygroup.oc1.eu-frankfurt-1.aaaaaaaansglb0000001"], "lifecycle-state": "ACTIVE"},
```

- After the SecurityList entity (the object ending `"display-name": "sl-app", "vcn-id": "ocid1.vcn.oc1.eu-frankfurt-1.amaaaaaavcnshop000001",\n         "lifecycle-state": "AVAILABLE"},`) insert:

```json
        {"type": "NetworkSecurityGroup", "id": "ocid1.networksecuritygroup.oc1.eu-frankfurt-1.aaaaaaaansgapp000001",
         "display-name": "nsg-app", "vcn-id": "ocid1.vcn.oc1.eu-frankfurt-1.amaaaaaavcnshop000001",
         "lifecycle-state": "AVAILABLE"},
        {"type": "NetworkSecurityGroup", "id": "ocid1.networksecuritygroup.oc1.eu-frankfurt-1.aaaaaaaansglb0000001",
         "displayName": "nsg-lb", "vcnId": "ocid1.vcn.oc1.eu-frankfurt-1.amaaaaaavcnshop000001",
         "lifecycleState": "AVAILABLE"},
```

Run: `python3 -c "import json; json.load(open('oci-drawio-architect/tests/fixtures/tenancy/topology_bundle.json')); print('json ok')"`
Expected: `json ok`.

- [ ] **Step 2: Write the failing parser tests**

Append to class `HclThreeTierTests` in `oci-drawio-architect/tests/test_parse_terraform.py` (after `test_network_controls_are_separated`):

```python
    def test_subnet_security_constructs_are_badge_fields(self):
        lb = find_subnet(self.vcn, "sn-lb-public")
        self.assertEqual(lb["route_table"], {"name": "rt-public", "address": "oci_core_route_table.public"})
        self.assertEqual(lb["security_lists"], [{"name": "sl-app", "address": "oci_core_security_list.app"}])
        app = find_subnet(self.vcn, "sn-app")
        self.assertIsNone(app["route_table"])
        self.assertEqual(app["security_lists"], [])

    def test_nsgs_are_item_badge_fields_never_workload_icons(self):
        lb = find_subnet(self.vcn, "sn-lb-public")["items"][0]
        self.assertEqual(lb["nsgs"], [{"name": "nsg-lb", "address": "oci_core_network_security_group.lb"}])
        inst = find_subnet(self.vcn, "sn-app")["items"][0]
        # create_vnic_details.nsg_ids plus the secondary oci_core_vnic_attachment (nsg-app deduplicated)
        self.assertEqual([n["name"] for n in inst["nsgs"]], ["nsg-app", "nsg-mgmt"])
        adb = find_subnet(self.vcn, "sn-database")["items"][0]
        self.assertEqual([n["address"] for n in adb["nsgs"]], ["oci_core_network_security_group.app"])
        for sn in self.vcn["subnets"]:
            for item in sn["items"]:
                self.assertNotIn(item["icon"], ("nsg", "security_list", "route_table"))
        self.assertNotIn("oci_core_vnic_attachment", json.dumps(self.model))       # placement helper, not an item
        self.assertEqual({i["type"] for i in self.vcn["controls"]},
                         {"oci_core_route_table", "oci_core_security_list", "oci_core_network_security_group"})
```

Append to class `HelperTests` in the same file:

```python
    def test_badge_fields_from_json_shaped_resources(self):
        res = [pt.Res("oci_core_vcn.v", "oci_core_vcn", "v", {"display_name": "v"}),
               pt.Res("oci_core_subnet.s", "oci_core_subnet", "s", {"display_name": "sn-app", "cidr": "10.0.1.0/24"},
                      {"vcn_id": ["oci_core_vcn.v"], "route_table_id": ["oci_core_route_table.rt"],
                       "security_list_ids": ["oci_core_security_list.a", "oci_core_security_list.b"]}),
               pt.Res("oci_core_route_table.rt", "oci_core_route_table", "rt", {"display_name": "rt-x"},
                      {"vcn_id": ["oci_core_vcn.v"]}),
               pt.Res("oci_core_security_list.a", "oci_core_security_list", "a", {"display_name": "sl-a"},
                      {"vcn_id": ["oci_core_vcn.v"]}),
               pt.Res("oci_core_security_list.b", "oci_core_security_list", "b", {}, {"vcn_id": ["oci_core_vcn.v"]}),
               pt.Res("oci_core_network_security_group.n", "oci_core_network_security_group", "n",
                      {"display_name": "nsg-x"}, {"vcn_id": ["oci_core_vcn.v"]}),
               pt.Res("oci_network_load_balancer_network_load_balancer.nlb",
                      "oci_network_load_balancer_network_load_balancer", "nlb", {"display_name": "nlb"},
                      {"subnet_id": ["oci_core_subnet.s"], "network_security_group_ids": ["oci_core_network_security_group.n"]}),
               pt.Res("oci_database_db_system.dbs", "oci_database_db_system", "dbs", {"display_name": "dbs"},
                      {"subnet_id": ["oci_core_subnet.s"], "nsg_ids": ["oci_core_network_security_group.n"]})]
        model = pt.ModelBuilder(res, "x").build()
        sn = model["vcns"][0]["subnets"][0]
        self.assertEqual(sn["route_table"], pt.badge_ref("rt-x", "oci_core_route_table.rt"))
        self.assertEqual([s["name"] for s in sn["security_lists"]], ["sl-a", "b"])       # no display_name -> resource name
        self.assertEqual([(i["address"].rsplit(".", 1)[-1], [n["name"] for n in i["nsgs"]]) for i in sn["items"]],
                         [("nlb", ["nsg-x"]), ("dbs", ["nsg-x"])])
        self.assertEqual(pt.validate_model(model, BUILDER_ICONS), [])

    def test_validate_model_reports_bad_badge_fields(self):
        model = pt.parse_terraform_dir(FIXTURES / "three_tier")
        sn = model["vcns"][0]["subnets"][0]
        sn["route_table"] = 5
        sn["security_lists"] = [{"address": "x"}]
        sn["items"][0]["nsgs"] = "nsg"
        joined = "\n".join(pt.validate_model(model))
        self.assertIn("vcns[0].subnets[0].route_table: expected str, got int", joined)
        self.assertIn("vcns[0].subnets[0].security_lists[0].name: expected str, got NoneType", joined)
        self.assertIn("vcns[0].subnets[0].items[0].nsgs: expected list, got str", joined)
```

- [ ] **Step 3: Write the failing tenancy tests**

In `oci-drawio-architect/tests/test_query_tenancy.py`, in `test_search_items_become_services_dead_and_helper_entities_are_dropped` replace

```python
        self.assertEqual(ctl, {"oci_core_route_table", "oci_core_security_list"})
```

with

```python
        self.assertEqual(ctl, {"oci_core_route_table", "oci_core_security_list", "oci_core_network_security_group"})
```

Append to class `BundleModelTests`:

```python
    def test_security_constructs_become_badge_fields(self):
        lb_sn = subnet(self.vcn, "sn-lb-public")
        self.assertEqual(lb_sn["route_table"]["name"], "rt-public")
        self.assertTrue(lb_sn["route_table"]["address"].startswith("ocid1.routetable."))
        self.assertEqual([s["name"] for s in lb_sn["security_lists"]], ["sl-app"])
        self.assertEqual([n["name"] for n in lb_sn["items"][0]["nsgs"]], ["nsg-lb"])          # networkSecurityGroupIds
        app = subnet(self.vcn, "sn-app")
        self.assertIsNone(app["route_table"])
        self.assertEqual([n["name"] for n in app["items"][0]["nsgs"]], ["nsg-app"])           # via the VNIC's nsgIds
        self.assertNotIn("nsgs", subnet(self.vcn, "sn-database")["items"][0])
        self.assertNotIn("ocid1.vnic.", json.dumps(self.model))
```

Append to class `HelperTests` in the same file:

```python
    def test_security_reference_fields_are_normalised(self):
        norm = qt.normalise_entity({"type": "Vnic", "id": "ocid1.vnic.oc1.eu-frankfurt-1.a",
                                    "nsg-ids": ["ocid1.networksecuritygroup.oc1.eu-frankfurt-1.n"]})
        self.assertEqual(norm["refs"]["nsg_ids"], ["ocid1.networksecuritygroup.oc1.eu-frankfurt-1.n"])
        norm = qt.normalise_entity({"type": "Subnet", "id": "ocid1.subnet.oc1.eu-frankfurt-1.s",
                                    "securityListIds": ["ocid1.securitylist.oc1.eu-frankfurt-1.l"]})
        self.assertEqual(norm["refs"]["security_list_ids"], ["ocid1.securitylist.oc1.eu-frankfurt-1.l"])
        norm = qt.normalise_entity({"type": "LoadBalancer", "id": "ocid1.loadbalancer.oc1.eu-frankfurt-1.b",
                                    "network-security-group-ids": ["ocid1.networksecuritygroup.oc1.eu-frankfurt-1.n"]})
        self.assertEqual(norm["refs"]["network_security_group_ids"], ["ocid1.networksecuritygroup.oc1.eu-frankfurt-1.n"])
```

Append to class `EndToEndTests` in `oci-drawio-architect/tests/test_oci_layout.py`:

```python
    def test_three_tier_and_tenancy_models_draw_badges(self):
        import parse_terraform as pt
        import query_tenancy as qt
        model = pt.parse_terraform_dir(self.FIXTURES / "terraform" / "three_tier")
        text = self._gate(model, "three_tier_badges.drawio")
        self.assertEqual(text.count("ociRole=badge"), 5)          # rt + sl on sn-lb-public, NSG on lb, instance, adb
        self.assertIn('id="subnet-sn-lb-public-rt"', text)
        self.assertIn('id="oci_core_instance.app-nsg"', text)
        bundle = qt.load_bundle(self.FIXTURES / "tenancy" / "topology_bundle.json")
        text = self._gate(qt.build_model(bundle, "ocid1.compartment.oc1..aaaaaaaashopprod000001"), "tenancy_badges.drawio")
        self.assertEqual(text.count("ociRole=badge"), 4)          # rt + sl on sn-lb-public, NSG on the LB and the instance
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_parse_terraform.HclThreeTierTests tests.test_parse_terraform.HelperTests tests.test_query_tenancy.BundleModelTests tests.test_query_tenancy.HelperTests tests.test_oci_layout.EndToEndTests 2>&1 | tail -12`
Expected: `test_subnet_security_constructs_are_badge_fields` and `test_security_constructs_become_badge_fields` ERROR with `KeyError: 'route_table'`; `test_nsgs_are_item_badge_fields_never_workload_icons` with `KeyError: 'nsgs'`; `test_badge_fields_from_json_shaped_resources` with `KeyError: 'route_table'` (the left operand is evaluated before `pt.badge_ref`); `test_security_reference_fields_are_normalised` with `KeyError: 'nsg_ids'`; `test_validate_model_reports_bad_badge_fields` **FAILS**, not errors - it only assigns the bad values (`sn["route_table"] = 5`), so `validate_model` returns `[]` and the first `assertIn` reports `'vcns[0].subnets[0].route_table: expected str, got int' not found in ''`; `test_three_tier_and_tenancy_models_draw_badges` FAILS with `0 != 5`; `test_search_items_become_services_dead_and_helper_entities_are_dropped` already PASSES (the fixture now has NSG entities and the existing parser files them under `controls`). Everything else in those classes still passes.

- [ ] **Step 5: Implement the parser fields**

In `oci-drawio-architect/scripts/parse_terraform.py`:

1. Insert after the line `CONTROL_TYPES = frozenset({"oci_core_network_security_group", "oci_core_security_list", "oci_core_route_table"})`:

```python
# Security constructs drawn as badges by the layout (subnet corner: route table + security
# lists; resource icon: NSGs) instead of workload icons. ``controls`` keeps the inventory.
ROUTE_TABLE_TYPE = "oci_core_route_table"
SECURITY_LIST_TYPE = "oci_core_security_list"
NSG_TYPE = "oci_core_network_security_group"
NSG_ATTRS = ("nsg_ids", "network_security_group_ids")
VNIC_ATTACHMENT_TYPES = frozenset({"oci_core_vnic_attachment", "oci_core_vnic"})
```

2. In `new_subnet`, replace `"tier": tier or infer_tier(name), "items": []}` with `"tier": tier or infer_tier(name), "items": [], "route_table": None, "security_lists": []}`.

3. Insert before `def new_hub_item(icon: str, label: str, rtype: str, address: Optional[str]) -> dict:`:

```python
def badge_ref(name: str, address: Optional[str] = None) -> dict:
    """A route table / security list / NSG reference drawn as a badge: ``{"name", "address"}``."""
    return {"name": name, "address": address}


```

4. Insert before `def _validate_item(errors: List[str], item, path: str, with_metadata: bool, icon_keys) -> None:`:

```python
def _validate_badge_refs(errors: List[str], value, path: str, single: bool = False) -> None:
    """``route_table`` (single) / ``security_lists`` / ``nsgs``: str or {name, address} entries."""
    if value is None:
        return
    if single:
        refs = [value]
    elif not _expect(errors, value, list, path):
        return
    else:
        refs = value
    for i, ref in enumerate(refs):
        rp = path if single else f"{path}[{i}]"
        if isinstance(ref, dict):
            _expect(errors, ref.get("name"), str, f"{rp}.name")
            _expect(errors, ref.get("address"), (str, type(None)), f"{rp}.address")
        else:
            _expect(errors, ref, str, rp)


```

5. At the end of `_validate_item` (after the `unknown icon key` check) add:

```python
    if "nsgs" in item:
        _validate_badge_refs(errors, item["nsgs"], f"{path}.nsgs")
```

6. In `validate_model`, inside the subnet loop, replace

```python
                    if sn.get("tier") not in TIERS:
                        errors.append(f"{sp}.tier: {sn.get('tier')!r} not in {TIERS}")
```

with

```python
                    if sn.get("tier") not in TIERS:
                        errors.append(f"{sp}.tier: {sn.get('tier')!r} not in {TIERS}")
                    _validate_badge_refs(errors, sn.get("route_table"), f"{sp}.route_table", single=True)
                    if "security_lists" in sn:
                        _validate_badge_refs(errors, sn["security_lists"], f"{sp}.security_lists")
```

7. In `ModelBuilder._build_subnets`, replace

```python
            if not isinstance(r.attrs.get("display_name"), str):
                subnet["_unresolved"] = True
            vcn["subnets"].append(subnet)
```

with

```python
            if not isinstance(r.attrs.get("display_name"), str):
                subnet["_unresolved"] = True
            rt = self.first_ref(r, ("route_table_id",), ROUTE_TABLE_TYPE)
            if rt is not None:
                subnet["route_table"] = self._badge_ref(rt, "Route table")
            subnet["security_lists"] = [self._badge_ref(sl, "Security list") for sl in
                                        self.all_refs(r, ("security_list_ids",), frozenset({SECURITY_LIST_TYPE}))]
            vcn["subnets"].append(subnet)
```

8. Insert before `    def _skip_as_item(self, r: Res) -> bool:`:

```python
    def _badge_ref(self, res: Res, default: str) -> dict:
        return badge_ref(res.label(default), res.address)

    def _nsg_refs(self, res: Res) -> List[dict]:
        return [self._badge_ref(n, "NSG") for n in self.all_refs(res, NSG_ATTRS, frozenset({NSG_TYPE}))]

```

9. In `_build_items`, replace

```python
            item = self._item_for(r)
            if item is None:
                continue
            subnet = self.first_ref(r, SUBNET_ATTRS, SUBNET_TYPE)
```

with

```python
            item = self._item_for(r)
            if item is None:
                continue
            nsgs = self._nsg_refs(r)
            if nsgs:
                item["nsgs"] = nsgs
            subnet = self.first_ref(r, SUBNET_ATTRS, SUBNET_TYPE)
```

10. Insert before `    def _register(self, item: dict, r: Res, vcn_addr: str, subnet_addr: Optional[str]) -> None:`:

```python
    def _build_vnic_nsgs(self) -> None:
        """Secondary VNICs (``oci_core_vnic_attachment``) add their NSGs to the attached instance's badge."""
        for r in self.resources:
            if r.rtype not in VNIC_ATTACHMENT_TYPES:
                continue
            inst = self.first_ref(r, ("instance_id",), "oci_core_instance")
            if inst is None or inst.address not in self.item_index:
                continue
            item = self.item_index[inst.address]
            have = {n["address"] for n in item.get("nsgs") or []}
            for ref in self._nsg_refs(r):
                if ref["address"] not in have:
                    item.setdefault("nsgs", []).append(ref)
                    have.add(ref["address"])

```

11. In `build()`, replace

```python
        self._build_items()
        self._build_edges()
```

with

```python
        self._build_items()
        self._build_vnic_nsgs()
        self._build_edges()
```

12. Module docstring: in the schema block, after the subnet line that ends `"tier": ..., "items": [ ITEM ]` (the subnet dict), document `"route_table": {"name": str, "address": str} | null, "security_lists": [{"name": str, "address": str}]` as subnet keys and `"nsgs": [{"name": str, "address": str}]   # only when non-empty` as an ITEM key (place each on its own line inside the existing block, matching its indentation). Then append this paragraph after the paragraph that starts `A DRG is reported once in ``drgs```:

```
Route tables, security lists and NSGs are never subnet items. A subnet's ``route_table_id`` and
``security_list_ids`` become ``route_table`` / ``security_lists`` badge references; an item's
``nsg_ids`` / ``network_security_group_ids`` (instances via ``create_vnic_details``, load balancers,
network load balancers, DB systems) and the ``nsg_ids`` of ``oci_core_vnic_attachment`` resources
attached to an instance become the item's ``nsgs``. The layout draws them as badges on the subnet's
top-right corner and on the resource icon. ``controls`` still lists the resources themselves.
```

- [ ] **Step 6: Implement the tenancy fields**

In `oci-drawio-architect/scripts/query_tenancy.py`:

1. Locate the `_REF_FIELDS = (` tuple **by name** (do not search for its last line: Task 10 adds `("peer_id", "peer_id"),` to it without pinning the position, so the closing lines may already have changed) and add these three entries as the last lines before the closing `)`, keeping every entry Task 10 left in place:

```python
    ("security_list_ids", "security_list_ids"), ("nsg_ids", "nsg_ids"),
    ("network_security_group_ids", "network_security_group_ids"),
```

Each entry is `(source_key, target_key)`; `get()` tries the snake, kebab and camel spellings of the source key (`_variants()`), so `security_list_ids` also matches `security-list-ids` and `securityListIds` - no per-spelling entries are needed. Afterwards the tuple must contain the pre-existing entries (`subnet_id`, `subnet_ids`, `target_subnet_id`, `vcn_id`, `compartment_id`, `drg_id`, `cpe_id`, `gateway_id`, `route_table_id`, `network_entity_id`), Task 10's `peer_id` and the three above - verify with `python3 -c "import sys; sys.path.insert(0,'oci-drawio-architect/scripts'); import query_tenancy as q; print([a for a,_ in q._REF_FIELDS])"`.

2. In `apply_relationships`, replace

```python
                if ka == "vnic" and kb not in HELPER_KINDS and "subnet_id" in ents[a]["refs"]:
                    ents[b]["refs"].setdefault("subnet_id", list(ents[a]["refs"]["subnet_id"]))
```

with

```python
                if ka == "vnic" and kb not in HELPER_KINDS:
                    for field in ("subnet_id", "nsg_ids"):      # the VNIC places its host and carries its NSGs
                        if field in ents[a]["refs"]:
                            ents[b]["refs"].setdefault(field, list(ents[a]["refs"][field]))
```

3. In the module docstring, after the sentence Task 10 added (`... DRGs and their attachments are reported in ``drgs[]`` (schema 2), the hub holds the on-premises side only.`) append: `Subnet ``routeTableId`` / ``securityListIds`` and VNIC / load balancer ``nsgIds`` / ``networkSecurityGroupIds`` become the badge fields ``route_table``, ``security_lists`` and ``nsgs`` (NSGs of a resource whose VNIC the topology does not return are only captured when the resource entity itself carries the field).`

- [ ] **Step 7: Run the tests, the suite and the end-to-end gates**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_parse_terraform tests.test_query_tenancy tests.test_oci_layout.EndToEndTests 2>&1 | tail -4 && cd .. && python3 -m unittest discover -s oci-drawio-architect/tests 2>&1 | tail -3 && python3 oci-drawio-architect/scripts/parse_terraform.py oci-drawio-architect/tests/fixtures/terraform/three_tier --out /tmp/v13-tt.json && python3 oci-drawio-architect/scripts/oci_layout.py /tmp/v13-tt.json -o /tmp/v13-tt.drawio && python3 oci-drawio-architect/scripts/check_overlaps.py /tmp/v13-tt.drawio && grep -c "ociRole=badge" /tmp/v13-tt.drawio && python3 oci-drawio-architect/scripts/query_tenancy.py --compartment-id ocid1.compartment.oc1..aaaaaaaashopprod000001 --from-json oci-drawio-architect/tests/fixtures/tenancy/topology_bundle.json --out /tmp/v13-ten.json && python3 oci-drawio-architect/scripts/oci_layout.py /tmp/v13-ten.json -o /tmp/v13-ten.drawio && python3 oci-drawio-architect/scripts/check_overlaps.py /tmp/v13-ten.drawio`
Expected: all three modules `OK`; suite `OK`; `parse_terraform.py` prints `Wrote /tmp/v13-tt.json` and a summary line; both `check_overlaps.py` lines print `OK: no container overlaps or layout errors`; the `grep -c` prints `5`. If the instance shows only `nsg-app`, `_build_vnic_nsgs` ran before `_build_items` filled `item_index` - check the `build()` order.

- [ ] **Step 8: Commit the code**

```bash
git add oci-drawio-architect/scripts/parse_terraform.py oci-drawio-architect/scripts/query_tenancy.py oci-drawio-architect/tests/fixtures/terraform/three_tier/compute.tf oci-drawio-architect/tests/fixtures/terraform/three_tier/network.tf oci-drawio-architect/tests/fixtures/tenancy/topology_bundle.json oci-drawio-architect/tests/test_parse_terraform.py oci-drawio-architect/tests/test_query_tenancy.py oci-drawio-architect/tests/test_oci_layout.py
git commit -m "feat(parser,tenancy): route table, security list and NSG badge fields"
```

- [ ] **Step 9: Documentation**

All anchors below are content in the files as left by Task 12; find them by text.

`oci-drawio-architect/skills/oci-drawio-architect/SKILL.md`:

1. Section 1: replace the item `Icon order inside a subnet: primary resource (LB, VM, DB) -> attached resources (block volume, certificate, WAF) -> NSG last.` with `Icon order inside a subnet: primary resource (LB, VM, DB) -> attached resources (block volume, certificate, WAF). Route tables, security lists and NSGs are never icons in a subnet (next item).` Insert a new item right after the gateways item (the one starting `Gateways straddle the VCN border`), renumbering the following items: `Security constructs are badges: a subnet's route table and security lists are half-size (22 px) caption-less icons straddling the subnet's top-right corner (route table centred on the corner, security lists one badge to its left; toolkit slide 18 uses the icons at half size as labels of the subnet box); an NSG is a 22 px shield badge in the top-right of the protected resource's 75x95 slot. Names go to the tooltip and metadata. Model fields: `subnet.route_table`, `subnet.security_lists`, `item.nsgs`.`
2. Section 2 `MODEL` block: replace the line ending `"address": "lb", "metadata": {"ocid": "..."}, "tooltip": "..."}]}],` with three lines: `"address": "lb", "metadata": {"ocid": "..."}, "tooltip": "...",` / `"nsgs": ["nsg-lb"]}],` / `"route_table": "rt-lb", "security_lists": ["sl-lb"]}],` (keep the indentation of the surrounding lines). Add rule 8 after rule 7: `Security constructs: `subnet.route_table` (str or `{"name", "address"}`), `subnet.security_lists` and `item.nsgs` (lists of the same forms) draw badges; never add `route_table`, `security_list` or `nsg` items to a subnet. An entry with an `address` can be an edge endpoint (`{"source": "rt-private", "target": "sgw"}`).`
3. Section 3: in the order-of-operations sentence replace `subnet rows -> ` with `subnet rows (each subnet: icons with their NSG badges -> `fit_to_children(subnet)` -> route table / security list badges on the subnet's top-right corner) -> `; add the table row `| `BADGE_SIZE` (badge side) | 22 | `BADGE_GAP` (route table -> security list badge) | 4 |` after the last row of the constants table.
4. Section 4 table: replace the row `| `oci_core_network_security_group` | `nsg` | last item of its subnet |` with `| `oci_core_network_security_group` | `nsg` (badge) | `items[].nsgs` of the protected resources - never an item |` and the row `| `oci_core_security_list` / `oci_core_route_table` | `security_list` / `route_table` | omit (or `add_table` on page 2) |` with `| `oci_core_security_list` / `oci_core_route_table` | `security_list` / `route_table` (badges) | `subnets[].security_lists` / `subnets[].route_table`; rule tables via `add_table` on page 2 |`.
5. Section 6 API table: insert after the `place_icons` row: `| `add_badge(icon_key, cx, cy, parent="1", host=None, size=22, key=None, metadata=None, tooltip=None) -> str` | caption-less half-size icon centred on (cx, cy) in parent coordinates; `host` = the subnet or icon it decorates (may be overlapped by the badge, ignored by `fit_to_children`); style `ociRole=badge;ociHost=<id>` |`. In the worked example insert before `for cid in (sn, spoke, region):` the line `d.add_badge("nsg", PAD + ICON_W - 11, ROW1_Y + 11, parent=sn, host=vm, key="app-vm-nsg", tooltip="NSG: nsg-app")   # shield on the VM's slot`.
6. Section 7 item 4: after `regional services in the Oracle Services Network panel right of the VCNs;` insert ` route tables and security lists as badges on the subnets' top-right corners and NSGs as shield badges on their resources, never as workload icons;`.
7. Section 8 table: add the row `| `ERROR: 'X' [abs ...] overlaps '(unlabelled)' [abs ...]` where the unlabelled cell is a badge | the badge covers an icon that is not its host: pass `host=<that icon id>` to `add_badge` (recipe: move the `nsgs` field to that item) |`.

`oci-drawio-architect/commands/drawio-architect.md`:

1. Step 2.4.4: replace `-> NSG last.` with `-> attached resources (block volume, certificate, WAF). NSGs are not items (2.4.10).`
2. Insert after step 2.4.9 (`Keep OCIDs and shapes in item `metadata` and a one-line `tooltip`.`): `   10. Security constructs: put the subnet's route table in `subnet.route_table` and its security lists in `subnet.security_lists`, and the NSGs of a resource in that item's `nsgs` (names, or `{"name", "address"}` when you want the badge as an edge endpoint). The recipe draws them as badges on the subnet's top-right corner and on the resource's icon; never add `route_table`, `security_list` or `nsg` icons to a subnet.`
3. Step 3 template: in the first subnet dict (the one containing the first `"items": [`) add `"route_table": "rt-app", "security_lists": ["sl-app"],` as its first keys, and add `"nsgs": ["nsg-app"]` to the first item dict.
4. Step 5.4 checklist: after `Oracle Services Network panel right of the VCNs;` insert ` route table / security list badges on the subnets' top-right corners and NSG badges on the top-right of their icons, none of them drawn as captioned icons;`.

`oci-drawio-architect/skills/oci-drawio-architect/references/oracle-styles.md`:

1. Section 1, insert before the bullet starting `- **Rounded-corner radii differ`: `- **Route table / security list / NSG badges**: PPTX slide 18 - "VCN, routing table, and security list icons are used at half size as labels to differentiate the VCN and subnet"; the v24.2 `.drawio` changelog - "Add a combination icon for situations when both a route table and security list icon are needed". The bundled set has the separate glyphs (`route_table`, `security_list`, `nsg`) and no combined one, so `add_badge()` draws 22 px badges: route table centred on the subnet's top-right corner, security lists 26 px to its left, the NSG shield over the top-right of the resource's slot (**project** geometry, **official** rule).`
2. Section 4 `### subnet`: append to the paragraph `Like `vcn` with a 1px border. ...` the sentence ` Route table / security list badges (`add_badge()`, section 5) straddle its top-right corner.`
3. Section 5: insert before `## 6. Edge styles (`add_edge()`)`:

```
### add_badge()

`add_badge(icon_key, cx, cy, parent="1", host=None, size=BADGE_SIZE, key=None, metadata=None, tooltip=None)`
emits one image cell of `size` x `size` (22) centred on `(cx, cy)` in the parent's coordinates,
no caption:
```
shape=image;verticalLabelPosition=bottom;verticalAlign=top;imageAspect=1;aspect=fixed;ociRole=badge;ociHost=<host id>;image=data:image/svg+xml,<url-encoded svg>;
```
`ociRole=badge` marks the cell for the validator (it may straddle its parent's border and overlap the
cell named by `ociHost`); `fit_to_children()` ignores badges; the router ignores badges hosted by an
icon and treats corner badges as obstacles. Recipe geometry: route table centre `(w, 0)` and
security lists `(w - 26, 0)` in subnet coordinates (`BADGE_GAP` = 4); NSG box `(53, 0, 22, 22)` in
the host's 75x95 slot. Ids `<subnet>-rt`, `<subnet>-sl`, `<icon>-nsg`.

```

`oci-drawio-architect/skills/oci-drawio-architect/references/gotchas.md`: append at the end of the file (after item 20 from Task 12):

```

## 21. Security constructs are badges, not workload icons

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
```

`oci-drawio-architect/CHANGELOG.md`, in `## [1.3.0] - 2026-09-17`:

- In `### Added`, insert after the `- **Validator**: ...` bullet (before `- Tests: `tests/test_oci_topology.py``):

```markdown
- **Security constructs as badges**: `subnet.route_table`, `subnet.security_lists` and `item.nsgs` (names or `{"name", "address"}`) draw 22 px caption-less badges - route table centred on the subnet's top-right corner, security lists one badge to its left, an NSG shield over the top-right of the protected resource's icon slot - with the names in the tooltip and metadata; never as workload icons (team diagram guidelines; toolkit slide 18 half-size labels and the v24.2 combination icon). `DrawioBuilder.add_badge()`, `BADGE_SIZE` / `BADGE_GAP`, style tokens `ociRole=badge;ociHost=<id>`; the validator lets a badge straddle its parent's corner and overlap its own host only. `parse_terraform.py` fills the fields from `route_table_id`, `security_list_ids`, `create_vnic_details.nsg_ids`, `network_security_group_ids`, `nsg_ids` and `oci_core_vnic_attachment`; `query_tenancy.py` from `routeTableId`, `securityListIds`, `nsgIds` and `networkSecurityGroupIds`. Design: `docs/superpowers/specs/2026-09-17-security-constructs-addendum.md`.
```

- In `### Changed`, insert after the `examples/generate_demo_diagram.py` bullet: `- The demo model carries route tables, security lists and NSGs on its subnets and resources; the skill and command no longer ask for an NSG as the last item of a subnet.`

`README.md` (root) and `oci-drawio-architect/README.md`: append as the last bullet of `## What's new in 1.3.0` (before the next heading or `---`): `- **Route tables, security lists and NSGs are badges, not icons.** `subnet.route_table` / `subnet.security_lists` draw half-size badges on the subnet's top-right corner and `item.nsgs` a shield on the protected resource's icon (names in the tooltip); `parse_terraform.py` and `query_tenancy.py` fill the fields from the Terraform and topology attributes.`

`CLAUDE.md` (repository root): in the API table insert after the `place_icons` row: `| `add_badge(icon_key, cx, cy, parent, host, size, key, metadata, tooltip)` | Caption-less 22 px icon centred on (cx, cy): route table / security list on a subnet corner, NSG on a resource icon |`; append to the paragraph under `### `oci_layout.py` — Layout Recipe`: `Subnet `route_table` / `security_lists` and item `nsgs` become badges (`_add_subnet_badges`, `_add_nsg_badge`; ids `<subnet>-rt`, `<subnet>-sl`, `<icon>-nsg`).`

- [ ] **Step 10: Verify**

Run: `: "${FORBIDDEN:?export FORBIDDEN=<name1|name2|...> first}" && python3 -m unittest discover -s oci-drawio-architect/tests 2>&1 | tail -3 && python3 oci-drawio-architect/scripts/build_icon_catalog.py --check && grep -rniE "$FORBIDDEN" docs/superpowers/specs/2026-09-17-security-constructs-addendum.md docs/superpowers/plans/2026-09-17-security-constructs-task14.md oci-drawio-architect/examples oci-drawio-architect/tests/fixtures oci-drawio-architect/CHANGELOG.md README.md oci-drawio-architect/README.md oci-drawio-architect/skills oci-drawio-architect/commands CLAUDE.md; echo "public-repo grep exit $? (1 = clean)" && grep -rn "NSG last" oci-drawio-architect/skills oci-drawio-architect/commands; echo "stale guidance grep exit $? (1 = clean)"`
where `FORBIDDEN` is exported beforehand as a pipe-separated, case-insensitive list of the company, project, tenancy, compartment and colleague names from the private review inputs (the list itself must never be written into the repository).
Expected: suite `OK`; catalog check `OK`; both greps exit 1.

- [ ] **Step 11: Commit the documentation**

```bash
git add oci-drawio-architect/skills oci-drawio-architect/commands oci-drawio-architect/CHANGELOG.md README.md oci-drawio-architect/README.md CLAUDE.md
git commit -m "docs: route table, security list and NSG badges - skill, command, references, changelog"
git status --short
```

Expected: `git status --short` prints nothing.

---

## Self-review

**Spec coverage (brief items S1-S7 and spec decisions B1-B10 -> steps)**

| Requirement | Steps |
|-------------|-------|
| S1 / B1 route table + security list badges on the subnet's top-right corner, straddling the border, RT on the corner then SL leftwards, no caption, names in tooltip / metadata, optional schema-2 fields | 14.3 (`add_badge`), 14.7 (`_add_subnet_badges`, `_badge_refs`, docstring), 14.1 / 14.5 tests (`test_corner_badges_centre_on_the_subnet_corner_and_validate_clean`, `test_route_table_badge_is_centred_on_the_subnet_top_right_corner`, `test_security_list_badge_sits_left_of_the_route_table_or_takes_the_corner`, `test_badges_have_no_caption_and_carry_names_in_tooltips`) |
| S2 / B2 NSG shield badge inside the host's 75x95 slot over the glyph area, no caption, names in tooltip; hand-placed `nsg` / `security_list` / `route_table` icons still legal, guidance prefers the fields | 14.3, 14.7 (`_add_nsg_badge` from `_icon_items`), tests `test_nsg_badge_sits_inside_the_host_slot_and_may_cover_the_glyph`, `test_nsg_badge_sits_in_the_top_right_of_the_host_slot`; 15.9 SKILL section 1 / 2 rule 8 / section 4 rows, command 2.4.4 and 2.4.10 |
| S3 / B6 / B7 parser fills the fields from `route_table_id`, `security_list_ids`, `create_vnic_details.nsg_ids`, LB / NLB `network_security_group_ids`, DB system `nsg_ids`, `oci_core_vnic_attachment`; no workload-icon emission (never existed - `controls` kept); tenancy best effort with documented gap | 15.5 (`_build_subnets`, `_nsg_refs`, `_build_vnic_nsgs`), 15.6 (`_REF_FIELDS`, VNIC copy, docstring gap), tests 15.2 / 15.3 |
| S4 / B5 validator: badges are leaves parented to the subnet / the icon's parent; pass `validate()` and `check_overlaps.py`; straddle rule covers a badge centred on the parent's corner; badge excluded from leaf collisions against its own host only | 14.3 items 2-4 (captions, rule 4, rule 6), rule 3 unchanged and pinned by `test_corner_badges_centre_on_the_subnet_corner_and_validate_clean` + `validate_file`; `test_badge_over_a_foreign_icon_is_still_a_collision` proves the exclusion is host-only; `test_validates_and_passes_the_gate`, `DemoBadgeTests`, `EndToEndTests.test_three_tier_and_tenancy_models_draw_badges` run `check_overlaps.main` |
| S5 / B8 docs: SKILL (schema, mapping rows, acceptance item), command enrichment step, oracle-styles provenance (slide 18, v24.2 changelog), gotchas item, CHANGELOG 1.3.0 Added bullets, README What's new bullet | 15.9 (every file and anchor listed), 14.3 item 8 (`check_overlaps.py` docstring) |
| S6 tests: badge geometry within 1 px, NSG inside slot, validator acceptance, parser extraction on a fixture, end-to-end build -> `check_overlaps.py` exit 0 | 14.1, 14.5, 15.1 (fixture extension), 15.2, 15.3 |
| S7 / B10 stdlib only, deterministic `key=` ids, conventional commits, no AI attribution | ids `<subnet id>-rt` / `-sl` / `<host id>-nsg` (14.7); commits 14.10, 15.8, 15.11 |
| B3 fields accept `str | {name, address}`; address registers the badge as an edge endpoint (first wins); `controls` unchanged | 14.7 (`_badge_refs`, `_register_badge`), tests `test_badge_addresses_resolve_as_edge_endpoints`, `test_models_without_the_fields_draw_no_badges`; 15.2 `test_nsgs_are_item_badge_fields_never_workload_icons` asserts the `controls` set |
| B4 `fit_to_children` ignores badges; routing treats corner badges as obstacles and NSG badges as part of the host | 14.3 items 5-6, tests `test_two_corner_badges_do_not_collide_and_fit_ignores_them`, `test_routing_obstacles_keep_corner_badges_and_drop_icon_badges` |
| B9 demo exercises the badges, reference sample and screenshots untouched | 14.8, `DemoBadgeTests`; 14.9 confirms the reference output is unchanged |

**Placeholder scan:** searched this plan for "TBD", "TODO", "implement later", "add appropriate", "handle edge cases", "similar to", "write tests for the above", "etc." - none present. Every code step shows the code; every documentation edit names the file, the exact anchor text and the replacement text. The one conditional instruction (Step 14.4: restore the Task 3 rule-3 branch if it went missing) points to the exact code in the main plan and adds no new behaviour.

**Prototype evidence:** the builder, validator, layout, parser and tenancy code in Steps 14.3, 14.7, 15.5 and 15.6 was executed against scratch copies of the current scripts (with the Task 3 straddle branch applied) before this plan was written: `validate()` and `validate_file()` returned `[]`, `check_overlaps.main` returned 0, the route-table badge centre equalled the subnet's top-right corner exactly, the security-list centre sat 26 px left of it, the NSG badge box was `(slot_x + 53, slot_y, 22, 22)`, a badge over a non-host icon produced exactly one `overlaps` error, `fit_to_children` returned the same size after the badges existed, the extended `three_tier` fixture yielded `rt-public` / `sl-app` / `nsg-lb` / `nsg-app, nsg-mgmt` / `nsg-app`, the synthetic JSON-shaped resources yielded `rt-x` / `sl-a, b` / `nsg-x`, the three validation messages matched, and the extended tenancy bundle yielded `rt-public` / `sl-app` / `nsg-lb` / `nsg-app` with the gate at 0.

**Type consistency check (names shared with the main plan):**
- `add_badge(icon_key, cx, cy, parent="1", host=None, size=BADGE_SIZE, key=None, metadata=None, tooltip=None) -> str` (14.3) is called as `d.add_badge("route_table", cx, 0, parent=sid, host=sid, key=..., tooltip=..., metadata=...)` and `d.add_badge("nsg", sx + ICON_W - BADGE_SIZE / 2, sy + BADGE_SIZE / 2, parent=parent, host=cid, key=..., tooltip=..., metadata=...)` (14.7), positionally with `parent=`/`host=`/`key=` in the tests (14.1) and in the SKILL worked example (15.9).
- `_check_parent(parent, what)`, `_load_svg(icon_key) -> (data_uri, w, h)`, `_emit_vertex(value, style, parent, x, y, w, h, metadata, tooltip, cid, link)`, `_register(cid, kind, x, y, w, h, parent, label, **extra)`, `_new_id(key)` (existing) are used with their current signatures.
- Registry keys read by the new builder paths - `kind`, `parent`, `badge`, `host`, `slot_x/slot_y/slot_w/slot_h`, `label_id` - are the ones `_register` writes in 14.3; `_routing_shapes`, `footprint`, `bbox`, `abs_bbox`, `content_bbox` keep working because a badge is registered as kind `icon` with slot fields.
- `_badge_host(entry) -> str | None` reads `entry["style"]` through `_style_tokens`, the same registry entries `validate_registry` iterates (`build_cell_registry` output) - so the exclusions apply identically in `DrawioBuilder.validate()` and `validate_file()`.
- Task 3 names used unchanged: `STRADDLE_TOL`, `_centre_within(outer, inner, tol)`, rule-3 branch `kinds.get(cid) == "icon"`; Task 2 token convention `ociRole=<role>` extended with `badge` and the new `ociHost` token.
- Task 5 signatures used unchanged: `_layout_subnet(d, vcn_id, subnet, x, y, max_cols, reg, min_w=None) -> (sid, w, h)`, `_icon_items(d, parent, items, cols, x0=PAD, y0=ROW1_Y, reg=None) -> (ids, bbox)`; test helpers `quiet`, `errors_of`, `gw`, `simple_vcn`, `MODEL_GW`, `TESTS_DIR`, `tempfile`, `Path`, `sys`, `db`, `ol` from Task 5's module header; `EndToEndTests._gate(model, name) -> str` and `FIXTURES` from Task 13.
- Task 9 / 10 names used unchanged: `Res(address, rtype, name, attrs=None, refs=None)`, `first_ref(res, attrs, rtype=None, rtypes=None)`, `all_refs(res, attrs, rtypes=None)`, `item_index`, `new_subnet(...)`, `_validate_item(errors, item, path, with_metadata, icon_keys)`, `_expect(errors, value, types, path)`, `validate_model(model, icon_keys=None)`, `normalise_entity(entity)`, `apply_relationships(ents, rels)`, `HELPER_KINDS`, `_REF_FIELDS` (with Task 10's `peer_id` entry retained).
- Cell ids: `subnet:<name>` -> `subnet-<name>` so the badge ids are `subnet-<name>-rt` / `subnet-<name>-sl`; Terraform addresses keep their dots (`oci_core_instance.app-nsg`, asserted in 15.3); `_slug` leaves `-rt` / `-sl` / `-nsg` suffixes untouched.
- Message texts asserted by tests: tooltips `Route table: rt-public`, `Security lists: sl-lb, sl-shared`, `Security list: sl-db`, `NSGs: nsg-app, nsg-mgmt`, `NSG: nsg-lb` (14.5) match `_badge_tooltip` (14.7); validation messages `expected str, got int` / `expected str, got NoneType` / `expected list, got str` (15.2) come from the existing `_expect` format through `_validate_badge_refs` (15.5).
- Counts asserted: 7 badges in `BADGED`, 14 in the demo file (two layout pages), 5 in the `three_tier` file, 4 in the tenancy file - each derived from the fields listed in 14.5, 14.8, 15.1.
