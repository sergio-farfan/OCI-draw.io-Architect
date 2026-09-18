# Topology-Aware Placement (v1.3.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release oci-drawio-architect 1.3.0, whose layout recipe draws the DRG at region level with its attachments beside it, puts IGW/NAT/SGW/LPG on the VCN border, moves regional services into one Oracle Services Network panel, gives connectors four semantics, and makes the validator reject a DRG or any foreign icon drawn inside a VCN.

**Architecture:** `scripts/drawio_builder.py` gains edge kinds, a `drg` group type, `add_box()`, a caption fill option, an `ociGroup`/`ociRole` style tagging scheme and two validator rules. A new stdlib module `scripts/oci_topology.py` holds the pure functions (`classify_topology`, `migrate_legacy_model`, `is_regional`, `choose_drg_style`). `scripts/oci_layout.py` consumes them: VCN columns are laid out first, then the region-level OSN panel, the on-premises panel, the DRG column with attachment boxes, and the border-straddling gateways; connectors are auto-routed as before. `parse_terraform.py` emits schema 2 (`drgs[]`, `attachments[]`, `regional`, `peer`), and `query_tenancy.py` follows through the shared `ModelBuilder`.

**Tech Stack:** Python 3.9+ standard library only (`xml.etree`, `json`, `argparse`, `unittest`); draw.io desktop optional for PNG export; bash for `pack.sh` / `smoke_test.sh`.

**Spec:** `docs/superpowers/specs/2026-09-17-topology-aware-placement-design.md`

## Global Constraints

- Python 3.9+ standard library only; no new dependencies (Pillow stays optional and unused by these changes).
- Public MIT repository: no client, tenancy, compartment, colleague or company names and no real IP/CIDR ranges from customer diagrams in code, tests, fixtures, docs or commit messages; refer to "the team's diagram guidelines" and "reviewer feedback".
- Author of every file and commit is Sergio Farfan (repo-local identity `Sergio Farfan <sergio.farfan@gmail.com>`); never credit AI tooling.
- Conventional-commit messages (`feat:`, `fix:`, `test:`, `docs:`, `chore:`); commit after each task; never touch `main` (work on `feature/v1.3.0-topology-aware-placement`).
- Gates after every task: `python3 -m unittest discover -s oci-drawio-architect/tests` must pass and `python3 oci-drawio-architect/scripts/check_overlaps.py <file>` must exit 0 on every diagram the task produces.
- Deterministic output: every cell of the recipe gets a `key=` id derived from the model address; no randomness, no dict-order dependence on Python < 3.7 semantics.
- All paths in commands are relative to the repository root `/Users/sergio.farfan/projects/git/oci-drawio/OCI-Diagrams`; run commands from there.
- Message texts quoted in this plan (validator errors, warnings, labels) are contractual: tests assert on them.

---

### Task 1: Builder edge kinds and legend

**Files:**
- Modify: `oci-drawio-architect/scripts/drawio_builder.py:1786-1858` (`add_legend`, `_arrow_fragment`, `_edge_base_style`), `:1860-1960` (`add_edge`), `:2410-2417` (`__all__`)
- Test: `oci-drawio-architect/tests/test_builder.py` (class `TestStyles` around line 541, class `TestHelpers` legend tests around line 1222)

**Interfaces:**
- Consumes: existing `DrawioBuilder.add_edge(source, target, label="", parent=None, dashed=False, color=None, style_extra="", exit_x=None, exit_y=None, entry_x=None, entry_y=None, waypoints=None, orthogonal=None, route=None, label_pos=None, arrow=None, key=None, raw_html=False) -> str`; `STYLE_PROFILES[name]["dash_pattern"|"dashed_arrow"|"edge_width"]`.
- Produces: module constant `EDGE_KIND_STYLES: dict[str, dict]` with keys `data`, `control`, `association`, `attachment` (values have keys `dashed: bool`, `arrow: str`, `width: int | None`, `dash_pattern: str | None`); new keyword `kind: str | None = None` on `add_edge` (after `raw_html`); `_arrow_fragment(self, dashed, arrow=None, dash_pattern=None) -> str`; `_edge_base_style(self, color, dashed, style_extra, orthogonal, arrow=None, width=None, dash_pattern=None) -> str`; `add_legend` accepting edge entry styles `"solid"|"dashed"|"accent"|"purple"|"dotted"|"thin"|"data"|"control"|"association"|"attachment"` and new default entries (4 edges + 4 group swatches).

- [x] **Step 1: Write the failing tests for edge kinds**

Append to class `TestStyles` in `oci-drawio-architect/tests/test_builder.py` (after `test_official_profile_edges`):

```python
    def test_edge_kind_data(self):
        tok = tokens(self._edge_style("default", kind="data"))
        self.assertEqual((tok["dashed"], tok["endArrow"], tok["strokeWidth"]), ("0", "open", "1.5"))
        self.assertNotIn("dashPattern", tok)

    def test_edge_kind_control_is_dashed_with_open_arrow_in_every_profile(self):
        for profile in ("default", "official", "v1.0"):
            tok = tokens(self._edge_style(profile, kind="control"))
            self.assertEqual((tok["dashed"], tok["endArrow"]), ("1", "open"), profile)
        self.assertIn("dashPattern=6 3", self._edge_style("default", kind="control"))
        self.assertNotIn("dashPattern", tokens(self._edge_style("official", kind="control")))

    def test_edge_kind_association_is_dotted_without_arrowhead(self):
        tok = tokens(self._edge_style("default", kind="association"))
        self.assertEqual((tok["dashed"], tok["dashPattern"], tok["endArrow"]), ("1", "1 3", "none"))

    def test_edge_kind_attachment_is_thin_solid_without_arrowhead(self):
        tok = tokens(self._edge_style("default", kind="attachment"))
        self.assertEqual((tok["dashed"], tok["endArrow"], tok["strokeWidth"]), ("0", "none", "1"))

    def test_edge_kind_keeps_colour_override_and_rejects_unknown(self):
        tok = tokens(self._edge_style("default", kind="data", color=db.COLORS["edge_accent"]))
        self.assertEqual(tok["strokeColor"], db.COLORS["edge_accent"])
        d = DrawioBuilder()
        a = d.add_icon("A", "vm", 0, 0)
        b = d.add_icon("B", "vm", 300, 0)
        with self.assertRaises(ValueError):
            d.add_edge(a, b, kind="sideways")
        self.assertEqual(set(db.EDGE_KIND_STYLES), {"data", "control", "association", "attachment"})

    def test_plain_dashed_flag_keeps_profile_behaviour(self):
        self.assertIn("endArrow=none", self._edge_style("default", dashed=True))
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_builder.TestStyles -v 2>&1 | tail -15`
Expected: the five `test_edge_kind_*` tests ERROR with `TypeError: DrawioBuilder.add_edge() got an unexpected keyword argument 'kind'`; `test_plain_dashed_flag_keeps_profile_behaviour` and the pre-existing TestStyles tests PASS.

- [x] **Step 3: Implement `EDGE_KIND_STYLES`, the style overrides and `kind=`**

In `oci-drawio-architect/scripts/drawio_builder.py`, insert after `STYLE_PROFILES["sample"] = STYLE_PROFILES["v1.0"]` (line 646):

```python
# Connector semantics (team diagram guidelines + toolkit slides 10/20):
# data = solid open arrow, control = dashed open arrow, association = dotted
# no arrowhead, attachment = thin solid no arrowhead. ``width`` / ``dash_pattern``
# None = take the profile value.
EDGE_KIND_STYLES = {
    "data":        dict(dashed=False, arrow="open", width=None, dash_pattern=None),
    "control":     dict(dashed=True,  arrow="open", width=None, dash_pattern=None),
    "association": dict(dashed=True,  arrow="none", width=None, dash_pattern="1 3"),
    "attachment":  dict(dashed=False, arrow="none", width=1,    dash_pattern=None),
}
```

Replace `_arrow_fragment` and `_edge_base_style` (lines 1835-1858) with:

```python
    def _arrow_fragment(self, dashed: bool, arrow=None, dash_pattern=None) -> str:
        if arrow is None:
            arrow = self.profile["dashed_arrow"] if dashed else "open"
        fill = "1" if arrow in ("block", "classic", "diamond", "oval") else "0"
        frag = f"endArrow={arrow};endFill={fill};"
        if dashed:
            pattern = dash_pattern if dash_pattern is not None else self.profile["dash_pattern"]
            frag = "dashed=1;" + (f"dashPattern={pattern};" if pattern else "") + frag
        else:
            frag = "dashed=0;" + frag
        return frag

    def _edge_base_style(self, color, dashed, style_extra, orthogonal: bool, arrow=None,
                         width=None, dash_pattern=None) -> str:
        ec = color or COLORS["edge_color"]
        p = self.profile
        sw = p["edge_width"] if width is None else width
        core = (
            f"html=1;strokeColor={ec};strokeWidth={_fmt_num(sw)};"
            f"{self._arrow_fragment(dashed, arrow, dash_pattern)}"
            f"fontFamily={self.font};fontSize={_fmt_num(p['edge_font'])};"
            f"fontColor={COLORS['text_primary']};rounded={p['edge_rounded']};"
            f"jettySize=auto;orthogonalLoop=1;"
        )
        if orthogonal:
            core = "edgeStyle=orthogonalEdgeStyle;" + core
        return _merge_style(core, style_extra)
```

In `add_edge`, change the signature to end with `key=None, raw_html=False, kind=None) -> str:` and insert right after the docstring (before `source, target = str(source), str(target)`):

```python
        width = dash_pattern = None
        if kind is not None:
            spec = EDGE_KIND_STYLES.get(kind)
            if spec is None:
                raise ValueError(f"add_edge: unknown kind {kind!r}; choose from {sorted(EDGE_KIND_STYLES)}")
            dashed = spec["dashed"]
            arrow = spec["arrow"] if arrow is None else arrow
            width, dash_pattern = spec["width"], spec["dash_pattern"]
```

Then pass the overrides in both `_edge_base_style` calls inside `add_edge`: `self._edge_base_style(color, dashed, style_extra, orthogonal=False, arrow=arrow, width=width, dash_pattern=dash_pattern)` (pinned branch) and `self._edge_base_style(color, dashed, style_extra, orthogonal=True, arrow=arrow, width=width, dash_pattern=dash_pattern)` (router branch). Add a docstring line: `kind: "data" | "control" | "association" | "attachment" applies EDGE_KIND_STYLES (dashed / arrow / width / dash pattern); explicit arrow= still wins.` Add `"EDGE_KIND_STYLES"` to `__all__` after `"STYLE_PROFILES"`.

- [x] **Step 4: Run the edge-kind tests**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_builder.TestStyles -v 2>&1 | tail -15`
Expected: all `TestStyles` tests PASS (including the six new ones).

- [x] **Step 5: Write the failing legend tests**

In `oci-drawio-architect/tests/test_builder.py` class `TestHelpers`, replace `test_add_legend_creates_group_with_swatches_and_texts` assertions `self.assertEqual(len(edges), 2)`, `self.assertEqual(len(swatches), 4)`, `self.assertEqual(len(texts), 6)` with `4`, `4`, `8`, and add after `test_add_legend_custom_entries`:

```python
    def test_add_legend_default_rows_cover_the_four_connector_kinds(self):
        gid = self.d.add_legend(20, 20)
        kids = [c for _, c, _ in iter_cells(self.d.root) if c.get("parent") == gid]
        edge_styles = [tokens(c.get("style")) for c in kids if c.get("edge") == "1"]
        self.assertEqual([(t["dashed"], t["endArrow"]) for t in edge_styles],
                         [("0", "open"), ("1", "open"), ("1", "none"), ("0", "none")])
        self.assertEqual(edge_styles[2]["dashPattern"], "1 3")
        self.assertEqual(edge_styles[3]["strokeWidth"], "1")
        texts = [c.get("value") for c in kids if c.get("vertex") == "1" and "text" in tokens(c.get("style"))]
        self.assertEqual(texts, ["Data flow (protocol / port)", "Management / administrative traffic",
                                 "Association / dependency", "Attachment (structural)",
                                 "Region / on-premises", "VCN", "Subnet", "Oracle Services Network"])

    def test_add_legend_accepts_kind_names_and_dotted_thin(self):
        gid = self.d.add_legend(20, 20, entries=[("edge", "attachment", "A"), ("edge", "dotted", "B"),
                                                 ("edge", "thin", "C"), ("edge", "control", "D")])
        edges = [tokens(c.get("style")) for _, c, _ in iter_cells(self.d.root)
                 if c.get("parent") == gid and c.get("edge") == "1"]
        self.assertEqual([e["endArrow"] for e in edges], ["none", "none", "none", "open"])
        self.assertEqual(edges[1]["dashPattern"], "1 3")
        with self.assertRaises(ValueError):
            self.d.add_legend(20, 300, entries=[("edge", "zigzag", "x")])
```

- [x] **Step 6: Run the legend tests to verify they fail**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_builder.TestHelpers -k legend -v 2>&1 | tail -8`
Expected: FAIL (`AssertionError: 2 != 4`, and the new tests fail on row texts / `ValueError` not raised).

- [x] **Step 7: Implement the legend changes**

In `add_legend` (line 1786) replace the default `entries` list and the edge branch:

```python
        if entries is None:
            entries = [
                ("edge", "data", "Data flow (protocol / port)"),
                ("edge", "control", "Management / administrative traffic"),
                ("edge", "association", "Association / dependency"),
                ("edge", "attachment", "Attachment (structural)"),
                ("group", "region", "Region / on-premises"),
                ("group", "vcn", "VCN"),
                ("group", "subnet", "Subnet"),
                ("group", "oracle_services_network", "Oracle Services Network"),
            ]
```

and inside the loop:

```python
            if kind == "edge":
                legacy = {"solid": "data", "dashed": "control", "accent": "data", "purple": "control",
                          "dotted": "association", "thin": "attachment"}
                kind_name = legacy.get(spec, spec)
                if kind_name not in EDGE_KIND_STYLES:
                    raise ValueError(f"add_legend: unknown edge style {spec!r}")
                ks = EDGE_KIND_STYLES[kind_name]
                color = {"accent": COLORS["edge_accent"], "purple": COLORS["edge_purple"]}.get(spec, COLORS["edge_color"])
                arrow = "none" if spec == "dashed" and self.profile["dashed_arrow"] == "none" else ks["arrow"]
                style = self._edge_base_style(color, ks["dashed"], "", orthogonal=False, arrow=arrow,
                                              width=ks["width"], dash_pattern=ks["dash_pattern"])
```

(the rest of the edge branch - `eid`, `cell`, `geom`, source/target points, registry entry - is unchanged). The `"dashed"` legacy entry keeps the profile's no-arrow look; the `"purple"` legacy entry now shows the open arrowhead of kind control, matching the datalake edges after Task 7 (existing tests only assert its strokeColor).

- [x] **Step 8: Run the whole suite**

Run: `python3 -m unittest discover -s oci-drawio-architect/tests 2>&1 | tail -3`
Expected: `OK` (244 existing + 8 new tests).

- [x] **Step 9: Commit**

```bash
git add oci-drawio-architect/scripts/drawio_builder.py oci-drawio-architect/tests/test_builder.py
git commit -m "feat(builder): connector kinds data/control/association/attachment and legend rows"
```

---

### Task 2: Builder `drg` group type, `ociGroup`/`ociRole` tokens, `add_box()` and caption fill

**Files:**
- Modify: `oci-drawio-architect/scripts/drawio_builder.py:650-733` (`GROUP_TYPES`, `_build_group_styles`), `:1508-1612` (`add_group` docstring, `add_icon`), new method after `place_icons` (line ~1645), `:2410-2417` (`__all__`)
- Test: `oci-drawio-architect/tests/test_builder.py` (new class `TestTopologyCells` placed before `TestValidation`)

**Interfaces:**
- Consumes: Task 1 (`_edge_base_style` unchanged here).
- Produces: `GROUP_TYPES` includes `"drg"`; every container style string ends with `ociGroup=<group_type>;` before `container=1;...`; `DrawioBuilder.add_box(label, x, y, w, h, parent="1", key=None, style_extra="", metadata=None, tooltip=None) -> str` (registered kind `"other"`, style `BOX_STYLE`); `add_icon(..., label_fill=None)`; DRG icons carry `ociRole=drg;`; module constants `BOX_STYLE: str`, `DRG_ICON_STEM = "networking_dynamic_routing_gateway_drg"`.

- [x] **Step 1: Write the failing tests**

Insert before `class TestValidation` in `oci-drawio-architect/tests/test_builder.py`:

```python
class TestTopologyCells(TempDirMixin, unittest.TestCase):
    def test_drg_group_type_style(self):
        self.assertIn("drg", db.GROUP_TYPES)
        d = DrawioBuilder()
        gid = d.add_group("DRG: hub-drg", 0, 0, 300, 200, group_type="drg")
        tok = tokens(cell(d.root, gid).get("style"))
        self.assertEqual((tok["rounded"], tok["arcSize"], tok["dashed"], tok["strokeWidth"]), ("1", "10", "1", "1"))
        self.assertEqual((tok["strokeColor"], tok["fillColor"], tok["align"]), (db.COLORS["text_primary"], "none", "left"))
        self.assertEqual(tok["fontStyle"], "1")
        self.assertEqual(tok["ociGroup"], "drg")

    def test_every_group_style_carries_its_ocigroup_token(self):
        d = DrawioBuilder()
        for gt in db.GROUP_TYPES:
            gid = d.add_group(gt, 0, 0, 100, 100, group_type=gt)
            tok = tokens(cell(d.root, gid).get("style"))
            self.assertEqual(tok["ociGroup"], "onprem" if gt == "hub" else gt, gt)
            self.assertEqual(tok["container"], "1")
        self.assertEqual(tokens(db._GROUP_STYLES["vcn"])["ociGroup"], "vcn")

    def test_add_box_is_a_leaf_with_rounded_ivy_border(self):
        d = DrawioBuilder()
        r = d.add_group("R", 0, 0, 400, 300)
        bid = d.add_box("VCN attachment\nspoke", 20, 50, 100, 44, parent=r, key="att-spoke")
        self.assertEqual(bid, "att-spoke")
        c = cell(d.root, bid)
        self.assertEqual(c.get("value"), "VCN attachment<br>spoke")
        tok = tokens(c.get("style"))
        self.assertEqual((tok["rounded"], tok["strokeColor"], tok["fillColor"]), ("1", db.COLORS["ivy"], "#FFFFFF"))
        self.assertEqual(tok["fontFamily"], db.FONT_STACK)
        self.assertNotIn("container", tok)
        self.assertEqual(d._cells[bid]["kind"], "other")
        self.assertEqual(db._kind(db.build_cell_registry(d.root)[bid]), "other")
        self.assertEqual(geom(c), {"x": 20.0, "y": 50.0, "width": 100.0, "height": 44.0})
        # boxes take part in leaf collision checks and can be edge endpoints
        icon = d.add_icon("VM", "vm", 60, 40, parent=r)
        self.assertTrue(any("overlaps" in m for m in d.validate()))
        d2 = DrawioBuilder()
        r2 = d2.add_group("R", 0, 0, 400, 300)
        b2 = d2.add_box("box", 20, 50, 100, 44, parent=r2)
        v2 = d2.add_group("VCN", 200, 40, 150, 200, parent=r2, group_type="vcn")
        d2.add_edge(b2, v2, "", kind="attachment")
        self.assertEqual(d2.validate(), [])

    def test_add_box_metadata_and_style_extra(self):
        d = DrawioBuilder()
        bid = d.add_box("x", 0, 0, 80, 30, metadata={"ocid": "ocid1.drgattachment.oc1..x"},
                        style_extra="fontStyle=2;")
        self.assertEqual(wrapper(d.root, bid).tag, "object")
        self.assertEqual(tokens(cell(d.root, bid).get("style"))["fontStyle"], "2")

    def test_caption_fill_option(self):
        d = DrawioBuilder()
        plain = d.add_icon("Gateway", "internet_gateway", 0, 0)
        filled = d.add_icon("Gateway", "internet_gateway", 200, 0, label_fill=db.COLORS["region_fill"])
        plain_style = tokens(cell(d.root, d._cells[plain]["label_id"]).get("style"))
        filled_style = tokens(cell(d.root, d._cells[filled]["label_id"]).get("style"))
        self.assertEqual(plain_style["fillColor"], "none")
        self.assertEqual(filled_style["fillColor"], db.COLORS["region_fill"])
        ids, _ = d.place_icons("1", [("A", "vm")], cols=1, x0=400, label_fill="#FFFFFF")
        self.assertEqual(tokens(cell(d.root, d._cells[ids[0]]["label_id"]).get("style"))["fillColor"], "#FFFFFF")

    def test_drg_icons_are_tagged(self):
        d = DrawioBuilder()
        for key in ("drg", "dynamic_routing_gateway", "networking_dynamic_routing_gateway_drg"):
            cid = d.add_icon("DRG", key, 0, 0)
            self.assertEqual(tokens(cell(d.root, cid).get("style"))["ociRole"], "drg", key)
        vm = d.add_icon("VM", "vm", 300, 0)
        self.assertNotIn("ociRole", tokens(cell(d.root, vm).get("style")))
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_builder.TestTopologyCells -v 2>&1 | tail -12`
Expected: FAIL/ERROR with `AssertionError: 'drg' not found in ('region', ...)`, `AttributeError: 'DrawioBuilder' object has no attribute 'add_box'`, `KeyError: 'ociGroup'`, `KeyError: 'ociRole'`, `TypeError: DrawioBuilder.add_icon() got an unexpected keyword argument 'label_fill'`.

- [x] **Step 3: Implement the group type and tokens**

In `oci-drawio-architect/scripts/drawio_builder.py` replace `GROUP_TYPES` (lines 650-654):

```python
GROUP_TYPES = (
    "region", "tenancy", "availability_domain", "fault_domain", "compartment",
    "vcn", "subnet", "services", "oracle_services_network", "onprem", "hub",
    "other", "metro_or_realm", "third_party_cloud", "internet", "drg",
)
DRG_ICON_STEM = "networking_dynamic_routing_gateway_drg"
```

In `_build_group_styles`, add a `"drg"` entry after `"other"`:

```python
        "drg": (
            f"{common}rounded=1;arcSize=10;strokeWidth=1;dashed=1;fillColor=none;"
            f"strokeColor={c['text_primary']};fontSize=11;fontStyle=1;"
            f"fontColor={c['text_primary']};{left}{_CONTAINER_TAIL}"
        ),
```

and replace the two closing lines of the function with:

```python
    styles["hub"] = styles["onprem"]  # deprecated alias
    # ``ociGroup`` lets validate_file() recognise VCNs / subnets in written files.
    return {gt: st.replace(_CONTAINER_TAIL, f"ociGroup={'onprem' if gt == 'hub' else gt};{_CONTAINER_TAIL}")
            for gt, st in styles.items()}
```

Update the `add_group` docstring list to include `drg`.

- [x] **Step 4: Implement `label_fill`, the DRG tag and `add_box`**

In `add_icon`: add `label_fill=None` after `link=None` in the signature; after `data_uri, nw, nh = _load_svg(icon_key)` add:

```python
        role = ""
        try:
            if resolve_icon_path(icon_key).stem == DRG_ICON_STEM:
                role = "ociRole=drg;"
        except (KeyError, ValueError, FileNotFoundError):
            role = ""
```

and change the image style to `f"imageAspect=1;aspect=fixed;{role}image={data_uri};"`. In the caption style replace `"text;html=1;strokeColor=none;fillColor=none;align=center;"` with `f"text;html=1;strokeColor=none;fillColor={label_fill or 'none'};align=center;"`. Add to the docstring: `label_fill: opaque caption background (e.g. COLORS["region_fill"]) for icons that straddle a dashed border.`

Insert after `place_icons` (before `# -- images / text`):

```python
    # -- labelled boxes ---------------------------------------------------------
    def add_box(self, label, x, y, w, h, parent="1", key=None, style_extra="",
                metadata=None, tooltip=None) -> str:
        """Add a small labelled rounded rectangle (DRG attachment marker, note).

        The cell is a leaf (kind "other"): it is a routing obstacle, takes part
        in the collision checks and can be an edge endpoint. Returns its id.
        """
        parent = self._check_parent(parent, "add_box")
        if w <= 0 or h <= 0:
            raise ValueError(f"add_box({label!r}): width and height must be positive")
        style = _merge_style(BOX_STYLE.replace("{font}", self.font), style_extra)
        text = escape_label(label)
        cid = self._emit_vertex(text, style, parent, x, y, w, h, metadata=metadata, tooltip=tooltip,
                                cid=self._new_id(key) if key is not None else None)
        self._register(cid, "other", x, y, w, h, parent, label=text)
        return cid
```

and, next to `_CONTAINER_TAIL` (line 648), the constant:

```python
BOX_STYLE = (
    "rounded=1;arcSize=12;whiteSpace=wrap;html=1;strokeWidth=1;"
    f"strokeColor={COLORS['ivy']};fillColor=#FFFFFF;fontFamily={{font}};fontSize=11;"
    f"fontColor={COLORS['text_primary']};align=center;verticalAlign=middle;"
)
```

Add `"BOX_STYLE"`, `"DRG_ICON_STEM"` to `__all__`.

- [x] **Step 5: Run the new tests and the suite**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_builder.TestTopologyCells -v 2>&1 | tail -10 && cd .. && python3 -m unittest discover -s oci-drawio-architect/tests 2>&1 | tail -3`
Expected: the six new tests PASS; suite `OK`. (`test_default_region_style` uses `assertIn` and `tokens()` so the added token does not break it; `test_group_styles_module_view_matches_default_builder` compares two outputs of the same function.)

- [x] **Step 6: Commit**

```bash
git add oci-drawio-architect/scripts/drawio_builder.py oci-drawio-architect/tests/test_builder.py
git commit -m "feat(builder): drg group type, ociGroup/ociRole style tokens, add_box() and caption fill"
```

---

### Task 3: Validator - straddle tolerance, foreign containment, DRG-in-VCN error

**Files:**
- Modify: `oci-drawio-architect/scripts/drawio_builder.py:955-982` (`_label_of`, `_attach_captions`), `:1049-1162` (`validate_registry`), `:2410-2417` (`__all__`); `oci-drawio-architect/scripts/check_overlaps.py:9-13` (docstring check list)
- Test: `oci-drawio-architect/tests/test_builder.py` (new class `TestForeignContainment` after `TestValidation`)

**Interfaces:**
- Consumes: Task 2 tokens `ociGroup=<type>` (containers) and `ociRole=drg` (DRG icons); `add_box()`; `add_icon(label_fill=)`.
- Produces: module constants `STRADDLE_TOL = 4.0`, `FOREIGN_TOL = ICON_W / 4` (18.75); helpers `_group_type_of(entry: dict) -> str`, `_is_drg_icon(entry: dict) -> bool`, `_centre_within(outer: _Box, inner: _Box, tol: float) -> bool`; `_attach_captions` sets `registry[<caption id>]["owner"] = <icon id>`; validator messages `ERROR: DRG '<label>' is inside VCN '<vcn label>'` and `ERROR: '<label>' [abs ...] lies inside '<container>' [abs ...] but is not one of its children`.

- [ ] **Step 1: Write the failing tests**

Insert after `class TestValidation` (before the `# 9. Helpers` banner) in `oci-drawio-architect/tests/test_builder.py`:

```python
class TestForeignContainment(TempDirMixin, unittest.TestCase):
    def _region_vcn(self, d):
        r = d.add_group("us-ashburn-1", 20, 75, 900, 600, group_type="region", key="region")
        v = d.add_group("VCN: a (10.0.0.0/16)", 300, 40, 500, 400, parent=r, group_type="vcn", key="vcn-a")
        return r, v

    def test_region_parented_drg_inside_vcn_is_an_error(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        d.add_icon("DRG\ndrg-a", "drg", 400, 200, parent=r, key="drg")     # abs (420,275) inside the VCN
        self.assertEqual(only_errors(d.validate()),
                         ["ERROR: DRG 'DRG drg-a' is inside VCN 'VCN: a (10.0.0.0/16)'"])

    def test_vcn_parented_drg_is_also_an_error(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        d.add_icon("DRG\ndrg-a", "drg", 100, 100, parent=v, key="drg")
        self.assertEqual(only_errors(d.validate()),
                         ["ERROR: DRG 'DRG drg-a' is inside VCN 'VCN: a (10.0.0.0/16)'"])

    def test_region_parented_vm_inside_vcn_is_a_foreign_containment_error(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        d.add_icon("App VM", "vm", 400, 200, parent=r, key="vm")
        errors = only_errors(d.validate())
        self.assertEqual(len(errors), 2, errors)          # the icon and its caption
        for e in errors:
            self.assertIn("lies inside 'VCN: a (10.0.0.0/16)'", e)
            self.assertIn("but is not one of its children", e)

    def test_icon_inside_a_foreign_subnet_is_an_error(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        d.add_group("sn-app", 20, 50, 300, 200, parent=v, group_type="subnet", key="sn-app")
        d.add_icon("Stray", "vm", 40, 60, parent=v, key="stray")            # in the VCN but inside sn-app's box
        self.assertTrue(any("lies inside 'sn-app'" in e for e in only_errors(d.validate())))

    def test_border_centred_gateway_is_clean_whichever_parent(self):
        for parent_is_vcn in (False, True):
            d = DrawioBuilder()
            r, v = self._region_vcn(d)
            if parent_is_vcn:
                d.add_icon("Internet\nGateway", "internet_gateway", 20, 400 - 40, parent=v, key="igw")
            else:
                d.add_icon("Internet\nGateway", "internet_gateway", 320, 40 + 400 - 40, parent=r, key="igw")
            self.assertEqual(only_errors(d.validate()), [], f"parent_is_vcn={parent_is_vcn}")

    def test_side_border_gateway_is_clean(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        d.add_icon("Service\nGateway", "service_gateway", 300 + 500 - 38, 40 + 50, parent=r, key="sgw",
                   label_fill=db.COLORS["region_fill"])
        self.assertEqual(only_errors(d.validate()), [])

    def test_mostly_inside_icon_is_still_flagged(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        d.add_icon("Almost in", "vm", 300 - 10, 200, parent=r, key="almost")  # sticks out 10 px < FOREIGN_TOL
        self.assertTrue(any("lies inside" in e for e in only_errors(d.validate())))

    def test_box_inside_foreign_vcn_is_an_error_and_outside_is_clean(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        d.add_box("VCN attachment", 350, 200, 100, 44, parent=r, key="bad")
        self.assertTrue(any("'VCN attachment'" in e and "lies inside" in e for e in only_errors(d.validate())))
        d2 = DrawioBuilder()
        r2, v2 = self._region_vcn(d2)
        d2.add_box("VCN attachment", 150, 200, 100, 44, parent=r2, key="good")
        self.assertEqual(only_errors(d2.validate()), [])

    def test_own_children_are_never_foreign(self):
        d = DrawioBuilder()
        r, v = self._region_vcn(d)
        s = d.add_group("sn-app", 20, 50, 300, 200, parent=v, group_type="subnet")
        d.add_icon("App VM", "vm", 20, 50, parent=s)
        self.assertEqual(d.validate(), [])

    def test_handwritten_file_uses_style_heuristics(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="test">
  <diagram id="p1" name="Page-1">
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="r" value="us-ashburn-1" style="rounded=1;strokeColor=#9E9892;fillColor=#F5F4F2;container=1;" vertex="1" parent="1">
          <mxGeometry x="20" y="75" width="900" height="600" as="geometry"/>
        </mxCell>
        <mxCell id="v" value="VCN: a" style="rounded=0;strokeWidth=2;dashed=1;strokeColor=#AE562C;fillColor=none;container=1;" vertex="1" parent="r">
          <mxGeometry x="300" y="40" width="500" height="400" as="geometry"/>
        </mxCell>
        <mxCell id="drg" value="" style="shape=image;image=data:image/svg+xml,x;" vertex="1" parent="r">
          <mxGeometry x="400" y="200" width="70" height="70" as="geometry"/>
        </mxCell>
        <mxCell id="drg-l" value="DRG hub" style="text;html=1;align=center;" vertex="1" parent="r">
          <mxGeometry x="382" y="275" width="105" height="45" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
"""
        path = self.tmp / "handwritten.drawio"
        path.write_text(xml, encoding="utf-8")
        errors, _, _, _ = db.validate_file(path)
        self.assertEqual(errors, ["ERROR: DRG 'DRG hub' is inside VCN 'VCN: a'"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_builder.TestForeignContainment -v 2>&1 | tail -14`
Expected: `test_region_parented_drg_inside_vcn_is_an_error`, `test_vcn_parented_drg_is_also_an_error`, `test_icon_inside_a_foreign_subnet...`, `test_mostly_inside...`, `test_box_inside_foreign_vcn...`, `test_handwritten_file...` FAIL with `[] != [...]` / `False is not true`; `test_region_parented_vm_inside_vcn...` FAILS with `0 != 2`; `test_border_centred_gateway_is_clean_whichever_parent` FAILS for `parent_is_vcn=True` with the `extends outside its parent` error; `test_side_border_gateway_is_clean` and `test_own_children_are_never_foreign` already PASS.

- [ ] **Step 3: Implement the helpers**

In `oci-drawio-architect/scripts/drawio_builder.py`, after `_label_of` (line 961) add:

```python
# Validator tolerances (px). STRADDLE_TOL: an icon whose glyph centre lies on
# its parent's border (gateway on the VCN edge) passes the containment check.
# FOREIGN_TOL: a leaf sticking out of a VCN / subnet it does not belong to by
# more than this is not "inside" it (a border-centred icon sticks out 35-37 px).
STRADDLE_TOL = 4.0
FOREIGN_TOL = ICON_W / 4
_DRG_CAPTION_RE = re.compile(r"\bDRG\b|Dynamic Routing", re.I)


def _centre_within(outer: "_Box", inner: "_Box", tol: float) -> bool:
    return (outer.x - tol <= inner.cx <= outer.right + tol
            and outer.y - tol <= inner.cy <= outer.bottom + tol)


def _group_type_of(entry: dict) -> str:
    """Container group type: the ``ociGroup`` token, else a Sienna-dashed heuristic."""
    tok = _style_tokens(entry.get("style", ""))
    gt = tok.get("ociGroup")
    if gt:
        return gt
    if (tok.get("container") == "1" and tok.get("dashed") == "1"
            and str(tok.get("strokeColor", "")).upper() == COLORS["vcn_stroke"].upper()
            and tok.get("dashPattern") != "1 1"):
        return "vcn" if tok.get("strokeWidth") == "2" else "subnet"
    return ""


def _is_drg_icon(entry: dict) -> bool:
    if _kind(entry) != "icon":
        return False
    if _style_tokens(entry.get("style", "")).get("ociRole") == "drg":
        return True
    return bool(_DRG_CAPTION_RE.search(entry.get("caption") or ""))
```

In `_attach_captions` change `best = (gap, te)` to `best = (gap, tid, te)` and the tail to:

```python
        if best is not None:
            _, tid, te = best
            e["caption"] = re.sub(r"\s+", " ", _html.unescape(_TAG_RE.sub(" ", te.get("value", "")))).strip()
            te["owner"] = cid
```

- [ ] **Step 4: Implement the validator rules**

Replace rule 3 in `validate_registry` with:

```python
    # 3. containment: every vertex inside its parent container. Icons (and
    #    their captions) may straddle the parent's border - gateways on the
    #    VCN edge - as long as the glyph centre is on or inside the border.
    for cid, e in registry.items():
        if e.get("vertex") != "1" or cid in ("0", "1"):
            continue
        parent = e.get("parent")
        if parent in (None, "0", "1") or parent not in registry or kinds.get(parent) != "group":
            continue
        local = _Box(e["x"], e["y"], e["w"], e["h"])
        pbox = _Box(0, 0, registry[parent]["w"], registry[parent]["h"])
        if pbox.contains(local, tol=1.0):
            continue
        k = kinds.get(cid)
        if k == "icon" and _centre_within(pbox, local, STRADDLE_TOL):
            continue
        owner = registry.get(e.get("owner")) if k == "text" else None
        if owner is not None:
            ob = _Box(owner["x"], owner["y"], owner["w"], owner["h"])
            if pbox.contains(ob, tol=1.0) or _centre_within(pbox, ob, STRADDLE_TOL):
                continue
        errors.append(
            f"{prefix}ERROR: '{_label_of(e)}' [{local!r}] extends outside its parent "
            f"'{_label_of(registry[parent])}' [w={_fmt_num(pbox.w)},h={_fmt_num(pbox.h)}]")
```

Insert a rule 7 before the final `if not any(k in ("group", "icon", "text") ...)` check:

```python
    # 7. foreign containment: a leaf drawn inside a VCN / subnet it does not
    #    belong to (team rule: a box asserts location). A DRG inside any VCN
    #    box is an error even when its parent chain is correct.
    network_groups = [(gid, _group_type_of(registry[gid])) for gid in containers]
    network_groups = [(gid, gt) for gid, gt in network_groups if gt in ("vcn", "subnet")]
    for lid in leaves:
        lb = boxes[lid]
        le = registry[lid]
        if lb.w <= 0 or lb.h <= 0:
            continue
        owner = registry.get(le.get("owner")) if kinds.get(lid) == "text" else None
        if owner is not None and _is_drg_icon(owner):
            continue                      # the DRG message below covers its caption
        is_drg = _is_drg_icon(le)
        for gid, gt in network_groups:
            gb = boxes[gid]
            if not gb.contains(lb, tol=FOREIGN_TOL):
                continue
            if is_drg and gt == "vcn":
                errors.append(f"{prefix}ERROR: DRG '{_label_of(le)}' is inside VCN '{_label_of(registry[gid])}'")
                continue
            if _is_ancestor(registry, gid, lid):
                continue
            errors.append(
                f"{prefix}ERROR: '{_label_of(le)}' [abs {lb!r}] lies inside '{_label_of(registry[gid])}' "
                f"[abs {gb!r}] but is not one of its children")
```

Update the `validate()` docstring (line 2349) and the module docstring bullet on `validate()` to mention "foreign containment (icons inside a VCN/subnet they do not belong to; DRG inside a VCN)". Add `"STRADDLE_TOL"`, `"FOREIGN_TOL"` to `__all__`. In `scripts/check_overlaps.py` docstring add the line `  - icons, captions or boxes lying inside a VCN / subnet they do not belong to; a DRG inside any VCN`.

- [ ] **Step 5: Run the new tests and the suite**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_builder.TestForeignContainment -v 2>&1 | tail -14 && cd .. && python3 -m unittest discover -s oci-drawio-architect/tests 2>&1 | tail -3`
Expected: all ten PASS; suite `OK`. If `test_side_border_gateway_is_clean` reports a caption `extends outside` error, the caption owner link was not set - check that `_attach_captions` runs before rule 3 (it does, line 1055) and that the `owner` key is written on the text entry.

- [ ] **Step 6: Confirm the shipped examples still pass the gate**

Run: `python3 oci-drawio-architect/examples/generate_reference_layout.py /tmp/ref13.drawio && python3 oci-drawio-architect/scripts/check_overlaps.py /tmp/ref13.drawio && python3 oci-drawio-architect/examples/generate_demo_diagram.py /tmp/demo13.drawio && python3 oci-drawio-architect/scripts/check_overlaps.py /tmp/demo13.drawio`
Expected: both `OK: no container overlaps or layout errors ...` (the 1.2.0 reference draws the DRG inside the on-premises panel, which is a `onprem` group, not a VCN, so rule 7 does not fire yet).

- [ ] **Step 7: Commit**

```bash
git add oci-drawio-architect/scripts/drawio_builder.py oci-drawio-architect/scripts/check_overlaps.py oci-drawio-architect/tests/test_builder.py
git commit -m "feat(validator): straddle tolerance, foreign-containment rule and DRG-inside-VCN error"
```

---

### Task 4: `oci_topology.py` - schema-2 helpers, legacy migration and `classify_topology`

**Files:**
- Create: `oci-drawio-architect/scripts/oci_topology.py`
- Test: `oci-drawio-architect/tests/test_oci_topology.py` (new)

**Interfaces:**
- Consumes: nothing from the builder (pure dict functions; stdlib `copy`, `typing`).
- Produces (all imported by Tasks 5-8 and 9):
  - `ATTACHMENT_TYPES = ("vcn", "ipsec", "virtual_circuit", "rpc", "loopback")`, `ONPREM_ATTACHMENT_TYPES = ("ipsec", "virtual_circuit")`, `ATTACHMENT_LINK_LABELS: dict[str, str]`, `REGIONAL_ICON_KEYS: frozenset[str]`, `DRG_ICON_KEYS: frozenset[str]`, `RPC_ICON_KEYS: frozenset[str]`, `DRG_BOX_THRESHOLD = 4`, `TOPOLOGY_KINDS`
  - `first_line(text) -> str`
  - `attachment_type(att: dict) -> str` (normalised, defaults to `"vcn"`)
  - `attachment_label(att: dict) -> str` (display name, fallback `VCN attachment <vcn>` / `IPSec attachment` / `Virtual circuit attachment` / `RPC attachment`)
  - `attachment_link_label(att: dict) -> str` (`""` for vcn, `Site-to-Site VPN`, `FastConnect`, `Remote Peering`)
  - `is_drg_item(item: dict) -> bool`, `is_rpc_item(item: dict) -> bool`
  - `is_regional(item: dict) -> bool`
  - `migrate_legacy_model(model: dict) -> tuple[dict, list[str]]` (deep copy; warnings start with `WARNING: legacy model:` or `WARNING: model:`)
  - `classify_topology(model: dict) -> dict` with keys `kind, n_vcns, n_drgs, n_vcn_attachments, has_onprem, has_rpc, has_lpg`
  - `choose_drg_style(requested: str, n_attachments: int) -> str`

- [ ] **Step 1: Write the failing tests**

Create `oci-drawio-architect/tests/test_oci_topology.py`:

```python
"""Unit tests for scripts/oci_topology.py (classification, regional services, legacy migration)."""
import copy
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import oci_topology as ot  # noqa: E402


def vcn(name, gateways=None):
    return {"name": name, "cidr": "10.0.0.0/16", "subnets": [], "gateways": gateways or []}


def drg(name="drg", attachments=None):
    return {"name": name, "address": name, "label": "DRG", "attachments": attachments or []}


class ClassifyTests(unittest.TestCase):
    def test_single_and_multi_vcn_without_drg(self):
        t = ot.classify_topology({"vcns": [vcn("a")]})
        self.assertEqual(t, {"kind": "single_vcn", "n_vcns": 1, "n_drgs": 0, "n_vcn_attachments": 0,
                             "has_onprem": False, "has_rpc": False, "has_lpg": False})
        t = ot.classify_topology({"vcns": [vcn("a"), vcn("b", [{"type": "lpg", "icon": "rpg", "label": "lpg"}])]})
        self.assertEqual((t["kind"], t["has_lpg"]), ("multi_vcn", True))

    def test_vcn_with_drg(self):
        t = ot.classify_topology({"vcns": [vcn("a")], "drgs": [drg(attachments=[{"type": "vcn", "vcn": "a"}])]})
        self.assertEqual((t["kind"], t["n_drgs"], t["n_vcn_attachments"]), ("vcn_with_drg", 1, 1))

    def test_hub_spoke(self):
        d = drg(attachments=[{"vcn": "a"}, {"type": "vcn", "vcn": "b"}])   # missing type defaults to vcn
        t = ot.classify_topology({"vcns": [vcn("a"), vcn("b")], "drgs": [d]})
        self.assertEqual((t["kind"], t["n_vcn_attachments"]), ("hub_spoke", 2))

    def test_hybrid_wins_over_hub_spoke(self):
        d = drg(attachments=[{"type": "vcn", "vcn": "a"}, {"type": "vcn", "vcn": "b"}, {"type": "ipsec", "target": "cpe"}])
        t = ot.classify_topology({"vcns": [vcn("a"), vcn("b")], "drgs": [d]})
        self.assertEqual((t["kind"], t["has_onprem"], t["has_rpc"]), ("hybrid", True, False))
        hub = {"name": "On-premises", "items": [{"icon": "cpe", "label": "CPE", "address": "cpe"}]}
        t = ot.classify_topology({"vcns": [vcn("a")], "hub": hub, "drgs": [drg(attachments=[{"vcn": "a"}])]})
        self.assertEqual((t["kind"], t["has_onprem"]), ("hybrid", True))

    def test_rpc_only_hub_is_hybrid_but_not_onprem(self):
        hub = {"name": "Remote region", "items": [{"icon": "rpg", "label": "RPC", "address": "rpc"}]}
        t = ot.classify_topology({"vcns": [vcn("a")], "hub": hub, "drgs": [drg(attachments=[{"vcn": "a"}])]})
        self.assertEqual((t["kind"], t["has_onprem"], t["has_rpc"]), ("hybrid", False, True))

    def test_choose_drg_style(self):
        self.assertEqual(ot.choose_drg_style("auto", 4), "icon")
        self.assertEqual(ot.choose_drg_style("auto", 5), "box")
        self.assertEqual(ot.choose_drg_style("box", 1), "box")
        self.assertEqual(ot.choose_drg_style("icon", 9), "icon")
        with self.assertRaises(ValueError):
            ot.choose_drg_style("fancy", 1)


class RegionalTests(unittest.TestCase):
    def test_table_and_override(self):
        self.assertTrue(ot.is_regional({"icon": "logging"}))
        self.assertTrue(ot.is_regional({"icon": "buckets"}))
        self.assertTrue(ot.is_regional({"icon": "iam"}))
        self.assertFalse(ot.is_regional({"icon": "load_balancer"}))
        self.assertFalse(ot.is_regional({"icon": "functions"}))
        self.assertFalse(ot.is_regional({"icon": "logging", "regional": False}))
        self.assertTrue(ot.is_regional({"icon": "vm", "regional": True}))
        self.assertFalse(ot.is_regional({"icon": "no_such_icon"}))
        for key in ("logging", "logging_analytics", "notifications", "events", "alarms", "iam", "identity",
                    "vault", "kms", "object_storage", "ocir", "generative_ai", "data_safe", "connector_hub"):
            self.assertIn(key, ot.REGIONAL_ICON_KEYS, key)

    def test_attachment_helpers(self):
        self.assertEqual(ot.attachment_type({"vcn": "a"}), "vcn")
        self.assertEqual(ot.attachment_type({"type": "IPSEC_TUNNEL"}), "ipsec")
        self.assertEqual(ot.attachment_type({"type": "VIRTUAL_CIRCUIT"}), "virtual_circuit")
        self.assertEqual(ot.attachment_type({"type": "REMOTE_PEERING_CONNECTION"}), "rpc")
        self.assertEqual(ot.attachment_label({"type": "vcn", "vcn": "spoke-a"}), "VCN attachment\nspoke-a")
        self.assertEqual(ot.attachment_label({"type": "vcn", "vcn": "spoke-a", "label": "att-a"}), "att-a")
        self.assertEqual(ot.attachment_label({"type": "ipsec"}), "IPSec attachment")
        self.assertEqual(ot.attachment_link_label({"type": "ipsec"}), "Site-to-Site VPN")
        self.assertEqual(ot.attachment_link_label({"type": "virtual_circuit"}), "FastConnect")
        self.assertEqual(ot.attachment_link_label({"type": "rpc"}), "Remote Peering")
        self.assertEqual(ot.attachment_link_label({"type": "vcn", "vcn": "a"}), "")


class MigrationTests(unittest.TestCase):
    LEGACY = {
        "subject": "Spoke", "vcns": [vcn("Spoke", [
            {"icon": "service_gateway", "label": "Service\nGateway", "address": "sgw"},
            {"icon": "drg", "type": "drg", "label": "drg-hub", "address": "att-spoke"}])],
        "hub": {"name": "Hub Network", "link_label": "IPSec VPN",
                "items": [{"icon": "firewall", "label": "Corp VPN", "address": "cpe"},
                          {"icon": "drg", "label": "Dynamic Routing\nGateway (DRG)", "address": "drg"}]},
        "edges": [{"source": "drg", "target": "sgw", "label": "", "kind": "data"}],
    }

    def test_hub_drg_and_gateway_drg_are_migrated(self):
        src = copy.deepcopy(self.LEGACY)
        m, warnings = ot.migrate_legacy_model(src)
        self.assertEqual(src, self.LEGACY, "input must not be mutated")
        self.assertEqual([i["address"] for i in m["hub"]["items"]], ["cpe"])
        self.assertEqual([g["address"] for g in m["vcns"][0]["gateways"]], ["sgw"])
        self.assertEqual(len(m["drgs"]), 1)
        d = m["drgs"][0]
        self.assertEqual((d["name"], d["address"], d["label"]), ("Dynamic Routing", "drg", "Dynamic Routing\nGateway (DRG)"))
        self.assertEqual(d["attachments"], [{"type": "vcn", "vcn": "Spoke", "address": "att-spoke",
                                             "label": "VCN attachment\nSpoke"}])
        # link_label between the CPE and the moved DRG becomes an explicit edge
        self.assertIn({"source": "cpe", "target": "drg", "label": "IPSec VPN", "kind": "data"}, m["edges"])
        self.assertEqual(len(m["edges"]), 2)
        self.assertTrue(all(w.startswith("WARNING: legacy model:") for w in warnings))
        self.assertEqual(len(warnings), 2)

    def test_hub_with_only_a_drg_is_removed(self):
        m, warnings = ot.migrate_legacy_model({"vcns": [vcn("a")], "hub": {"name": "Hub", "items": [
            {"icon": "drg", "label": "drg-x", "address": "drg-x"}]}})
        self.assertIsNone(m["hub"])
        self.assertEqual(m["drgs"][0]["address"], "drg-x")
        # no attachments given and a single VCN -> implicit attachment
        self.assertEqual(m["drgs"][0]["attachments"], [{"type": "vcn", "vcn": "a", "address": "drg-x@a",
                                                        "label": "VCN attachment\na"}])
        self.assertTrue(any(w.startswith("WARNING: model: DRG 'drg-x' has no attachments") for w in warnings))

    def test_gateway_only_legacy_creates_a_drg(self):
        m, warnings = ot.migrate_legacy_model({"vcns": [
            vcn("a", [{"icon": "drg", "label": "drg-shared", "address": "att-a"}]),
            vcn("b", [{"icon": "drg", "label": "drg-shared", "address": "att-b"}])]})
        self.assertEqual(len(m["drgs"]), 1)
        self.assertEqual(m["drgs"][0]["name"], "drg-shared")
        self.assertEqual([a["vcn"] for a in m["drgs"][0]["attachments"]], ["a", "b"])
        self.assertEqual(len(warnings), 2)

    def test_v2_model_is_untouched(self):
        v2 = {"vcns": [vcn("a")], "drgs": [drg(attachments=[{"type": "vcn", "vcn": "a", "address": "att"}])],
              "hub": {"name": "On-premises", "items": [{"icon": "cpe", "address": "cpe", "label": "CPE"}]}}
        m, warnings = ot.migrate_legacy_model(copy.deepcopy(v2))
        self.assertEqual(m, v2)
        self.assertEqual(warnings, [])

    def test_existing_edge_is_not_duplicated(self):
        legacy = copy.deepcopy(self.LEGACY)
        legacy["edges"].append({"source": "cpe", "target": "drg", "label": "IPSec VPN", "kind": "data"})
        m, _ = ot.migrate_legacy_model(legacy)
        self.assertEqual(sum(1 for e in m["edges"] if (e["source"], e["target"]) == ("cpe", "drg")), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_oci_topology 2>&1 | tail -3`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'oci_topology'`.

- [ ] **Step 3: Create the module**

Create `oci-drawio-architect/scripts/oci_topology.py`:

```python
#!/usr/bin/env python3
"""Topology-aware helpers for the OCI layout recipe (standard library only).

* ``classify_topology(model)`` - which of single_vcn / multi_vcn / vcn_with_drg /
  hub_spoke / hybrid a model is, plus the counts the layout needs.
* ``migrate_legacy_model(model)`` - schema-1 models (DRG as a hub item and/or as
  ``drg``-typed VCN gateways) become schema-2 models with ``drgs[]``.
* ``is_regional(item)`` - regional Oracle service (OSN panel) vs VCN-resident.
* ``choose_drg_style(requested, n_attachments)`` - icon or box presentation.

All functions are pure: they never mutate their input.
"""
from __future__ import annotations

import copy
from typing import Dict, List, Optional, Tuple

TOPOLOGY_KINDS = ("single_vcn", "multi_vcn", "vcn_with_drg", "hub_spoke", "hybrid")
ATTACHMENT_TYPES = ("vcn", "ipsec", "virtual_circuit", "rpc", "loopback")
ONPREM_ATTACHMENT_TYPES = ("ipsec", "virtual_circuit")
ATTACHMENT_LINK_LABELS: Dict[str, str] = {"vcn": "", "ipsec": "Site-to-Site VPN",
                                          "virtual_circuit": "FastConnect", "rpc": "Remote Peering",
                                          "loopback": ""}
_ATTACHMENT_ALIASES: Dict[str, str] = {
    "vcn": "vcn", "ipsec": "ipsec", "ipsec_tunnel": "ipsec", "vpn": "ipsec",
    "virtual_circuit": "virtual_circuit", "virtualcircuit": "virtual_circuit", "fastconnect": "virtual_circuit",
    "vc": "virtual_circuit", "rpc": "rpc", "remote_peering_connection": "rpc", "remote_peering": "rpc",
    "loopback": "loopback",
}
_ATTACHMENT_FALLBACK_LABELS: Dict[str, str] = {"ipsec": "IPSec attachment", "virtual_circuit": "Virtual circuit attachment",
                                               "rpc": "RPC attachment", "loopback": "Loopback attachment"}
DRG_ICON_KEYS = frozenset({"drg", "dynamic_routing_gateway", "networking_dynamic_routing_gateway_drg"})
RPC_ICON_KEYS = frozenset({"remote_peering_gateway", "rpg", "networking_remote_peering_gateway"})
RPC_TYPE = "oci_core_remote_peering_connection"
DRG_BOX_THRESHOLD = 4          # auto style: more attachments than this -> "box"

# Regional Oracle services (drawn in the Oracle Services Network panel) by icon key.
# Everything else found in vcn.services / model.services stays VCN-resident.
REGIONAL_ICON_KEYS = frozenset({
    "logging", "logging_analytics",
    "monitoring", "alarms", "notifications", "ons", "events", "service_connector_hub", "connector_hub",
    "iam", "identity", "policies", "policy", "auditing", "audit", "cloud_guard",
    "vulnerability_scanning", "vuln_scanning", "threat_intelligence", "threat_intel",
    "vault", "key_vault", "key_management", "kms", "encryption", "certificates",
    "buckets", "object_storage", "container_registry", "ocir",
    "ai", "generative_ai", "data_safe", "data_science", "big_data", "analytics", "machine_learning", "ml",
    "digital_assistant", "oda", "data_integration", "data_flow", "data_catalog",
    "streaming", "queue", "queuing", "apm", "email_delivery", "email", "dns", "devops", "resource_manager",
    "health_checks", "waf",
})


def first_line(text) -> str:
    return str(text or "").split("\n")[0].strip()


def attachment_type(att: dict) -> str:
    raw = str(att.get("type") or "vcn").strip().lower()
    return _ATTACHMENT_ALIASES.get(raw, raw)


def attachment_label(att: dict) -> str:
    label = att.get("label")
    if label:
        return str(label)
    atype = attachment_type(att)
    if atype == "vcn":
        return f"VCN attachment\n{att.get('vcn') or ''}".rstrip()
    return _ATTACHMENT_FALLBACK_LABELS.get(atype, "Attachment")


def attachment_link_label(att: dict) -> str:
    return ATTACHMENT_LINK_LABELS.get(attachment_type(att), "")


def is_drg_item(item: dict) -> bool:
    return (str(item.get("type") or "").lower() in ("drg", "oci_core_drg")
            or str(item.get("icon") or "") in DRG_ICON_KEYS)


def is_rpc_item(item: dict) -> bool:
    return str(item.get("type") or "") == RPC_TYPE or str(item.get("icon") or "") in RPC_ICON_KEYS


def is_regional(item: dict) -> bool:
    flag = item.get("regional")
    if isinstance(flag, bool):
        return flag
    return str(item.get("icon") or "") in REGIONAL_ICON_KEYS


def choose_drg_style(requested: str, n_attachments: int) -> str:
    requested = (requested or "auto").lower()
    if requested not in ("auto", "icon", "box"):
        raise ValueError(f"drg_style must be auto, icon or box, not {requested!r}")
    if requested != "auto":
        return requested
    return "box" if n_attachments > DRG_BOX_THRESHOLD else "icon"


def _match_drg(drgs: List[dict], gateway: dict) -> Optional[dict]:
    if len(drgs) == 1:
        return drgs[0]
    name = first_line(gateway.get("label"))
    for d in drgs:
        if d.get("name") == name:
            return d
    return None


def migrate_legacy_model(model: dict) -> Tuple[dict, List[str]]:
    """Return (schema-2 model, warnings). Legacy DRG hub items and drg gateways move to drgs[]."""
    m = copy.deepcopy(model)
    warnings: List[str] = []
    drgs: List[dict] = list(m.get("drgs") or [])
    hub = m.get("hub")
    if hub and hub.get("items"):
        items = list(hub["items"])
        moved = [it for it in items if is_drg_item(it)]
        if moved:
            link = hub.get("link_label")
            existing = {(str(e.get("source")), str(e.get("target"))) for e in (m.get("edges") or [])}
            for it in moved:
                addr = str(it.get("address") or "drg")
                idx = items.index(it)
                for nb in (items[idx - 1] if idx > 0 else None, items[idx + 1] if idx + 1 < len(items) else None):
                    if nb is None or is_drg_item(nb) or link is None or not nb.get("address"):
                        continue
                    pair = (str(nb["address"]), addr)
                    if pair in existing or pair[::-1] in existing:
                        continue
                    m.setdefault("edges", []).append({"source": pair[0], "target": pair[1], "label": link, "kind": "data"})
                    existing.add(pair)
                drgs.append({"name": first_line(it.get("label")) or addr, "address": addr,
                             "label": it.get("label") or "DRG", "attachments": []})
                warnings.append(f"WARNING: legacy model: hub item {addr!r} moved to drgs[]")
            hub["items"] = [it for it in items if not is_drg_item(it)]
            if not hub["items"]:
                m["hub"] = None
    for vcn in m.get("vcns") or []:
        gws = list(vcn.get("gateways") or [])
        legacy = [g for g in gws if is_drg_item(g)]
        if not legacy:
            continue
        vcn["gateways"] = [g for g in gws if not is_drg_item(g)]
        vname = vcn.get("name") or vcn.get("address") or "vcn"
        for g in legacy:
            drg = _match_drg(drgs, g)
            if drg is None:
                addr = "drg" if not drgs else f"drg-{len(drgs) + 1}"
                drg = {"name": first_line(g.get("label")) or "DRG", "address": addr,
                       "label": g.get("label") or "DRG", "attachments": []}
                drgs.append(drg)
            att_addr = str(g.get("address") or f"{drg['address']}@{vname}")
            drg["attachments"].append({"type": "vcn", "vcn": vname, "address": att_addr,
                                       "label": f"VCN attachment\n{vname}"})
            warnings.append(f"WARNING: legacy model: gateway {att_addr!r} in VCN {vname!r} became a VCN attachment "
                            f"of DRG {drg['address']!r}")
    vcns = list(m.get("vcns") or [])
    for drg in drgs:
        if not drg.get("attachments") and len(vcns) == 1:
            vname = vcns[0].get("name") or vcns[0].get("address") or "vcn"
            drg["attachments"] = [{"type": "vcn", "vcn": vname, "address": f"{drg['address']}@{vname}",
                                   "label": f"VCN attachment\n{vname}"}]
            warnings.append(f"WARNING: model: DRG {drg['address']!r} has no attachments; assuming a VCN attachment "
                            f"to {vname!r}")
    if drgs or "drgs" in model:
        m["drgs"] = drgs
    return m, warnings


def classify_topology(model: dict) -> dict:
    """Pure classification of an (already migrated) model."""
    vcns = list(model.get("vcns") or [])
    drgs = list(model.get("drgs") or [])
    atts = [a for d in drgs for a in (d.get("attachments") or [])]
    hub_items = list((model.get("hub") or {}).get("items") or [])
    rpc_items = [it for it in hub_items if is_rpc_item(it)]
    has_rpc = bool(rpc_items) or any(attachment_type(a) == "rpc" for a in atts)
    has_onprem = len(rpc_items) < len(hub_items) or any(attachment_type(a) in ONPREM_ATTACHMENT_TYPES for a in atts)
    has_lpg = any(str(g.get("type") or "").lower() == "lpg" for v in vcns for g in (v.get("gateways") or []))
    n_vcn_att = sum(1 for a in atts if attachment_type(a) == "vcn")
    if not drgs:
        kind = "single_vcn" if len(vcns) <= 1 else "multi_vcn"
    elif has_onprem or has_rpc:
        kind = "hybrid"
    elif n_vcn_att >= 2:
        kind = "hub_spoke"
    else:
        kind = "vcn_with_drg"
    return {"kind": kind, "n_vcns": len(vcns), "n_drgs": len(drgs), "n_vcn_attachments": n_vcn_att,
            "has_onprem": has_onprem, "has_rpc": has_rpc, "has_lpg": has_lpg}


__all__ = [
    "TOPOLOGY_KINDS", "ATTACHMENT_TYPES", "ONPREM_ATTACHMENT_TYPES", "ATTACHMENT_LINK_LABELS",
    "DRG_ICON_KEYS", "RPC_ICON_KEYS", "DRG_BOX_THRESHOLD", "REGIONAL_ICON_KEYS",
    "first_line", "attachment_type", "attachment_label", "attachment_link_label",
    "is_drg_item", "is_rpc_item", "is_regional", "choose_drg_style",
    "migrate_legacy_model", "classify_topology",
]
```

- [ ] **Step 4: Run the tests**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_oci_topology -v 2>&1 | tail -16`
Expected: 13 tests PASS. If `test_v2_model_is_untouched` fails because `m["drgs"]` was re-assigned, check the final `if drgs or "drgs" in model` guard keeps the original list content (deep-copied) - equality must hold.

- [ ] **Step 5: Check the icon keys really exist**

Run: `python3 -c "import sys; sys.path.insert(0,'oci-drawio-architect/scripts'); import drawio_builder as d, oci_topology as t; print(sorted(k for k in t.REGIONAL_ICON_KEYS if k not in d.ICON_MAP))"`
Expected: `[]`.

- [ ] **Step 6: Commit**

```bash
git add oci-drawio-architect/scripts/oci_topology.py oci-drawio-architect/tests/test_oci_topology.py
git commit -m "feat(layout): oci_topology module with classify_topology, legacy migration and regional classification"
```

---

### Task 5: Layout - gateways on the VCN edge

**Files:**
- Modify: `oci-drawio-architect/scripts/oci_layout.py:73-92` (constants), `:216-297` (`_layout_vcn`), `:330-398` (`build_diagram`)
- Test: `oci-drawio-architect/tests/test_oci_layout.py` (new)

**Interfaces:**
- Consumes: `DrawioBuilder.place_icons(parent, items, cols, x0, y0, **icon_kwargs)` with `label_fill=` (Task 2); `COLORS["region_fill"]`; `ICON_W`, `ICON_FOOTPRINT_H`, `ROW_H`, `ROW1_Y`, `PAD` from `drawio_builder`.
- Produces: constants `GW_STRADDLE = 40`, `GW_SIDE_DX = 38`, `SIDE_GW_Y0 = ROW1_Y`, `LEFT_GW_Y0 = SIDE_GW_Y0`, `SIDE_GW_PITCH = ROW_H`, `VCN_BOTTOM_PAD_GW = 60`, `VCN_SIDE_PAD = 60`, `SIDE_INSET = 40`, `VCN_COLUMN_GAP_GW = 110`; functions `_vcn_order(vcns: list) -> dict[str, int]`, `_gateway_side(gw: dict, vcn_index: int, order: dict) -> str` (`"bottom" | "right" | "left"`), `_gateway_sides(vcn: dict, vcn_index: int, order: dict) -> dict[str, list]` (keys `left`, `right`, `bottom`), `_place_edge_gateway(d, region_id, box: tuple, side: str, slot: int, gw: dict, reg) -> str`; `_layout_vcn(d, region_id, vcn, x, y, reg, max_row_w=MAX_ROW_W, inset_left=0, right_pad=PAD, bottom_pad=VCN_BOTTOM_PAD, min_h=200) -> tuple[str, int, int]` (no longer draws gateways). Gateways are children of the region with their address as cell id.

- [ ] **Step 1: Write the failing tests**

Create `oci-drawio-architect/tests/test_oci_layout.py`:

```python
"""Layout tests for scripts/oci_layout.py (v1.3.0 topology-aware placement)."""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import drawio_builder as db  # noqa: E402
import oci_layout as ol  # noqa: E402


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def errors_of(d):
    return [m for m in d.validate() if not m.split("] ")[-1].startswith("WARNING")]


def style_of(d, cid):
    for el in d.root.iter("mxCell"):
        if el.get("id") == cid:
            return db._style_tokens(el.get("style", ""))
    raise KeyError(cid)


def gw(gtype, icon, label, address, **extra):
    g = {"type": gtype, "icon": icon, "label": label, "address": address}
    g.update(extra)
    return g


def simple_vcn(name, address=None, gateways=None, services=None, item="app"):
    return {"name": name, "address": address, "cidr": "10.0.0.0/16",
            "subnets": [{"name": f"sn-{name}", "cidr": "10.0.1.0/24", "tier": "app",
                         "items": [{"icon": "vm", "label": f"App {name}", "address": f"{item}-{name}"}]}],
            "services": services or [], "gateways": gateways or []}


MODEL_GW = {
    "subject": "gw", "region": "us-ashburn-1",
    "vcns": [simple_vcn("a", gateways=[
        gw("igw", "internet_gateway", "Internet\nGateway", "igw"),
        gw("nat", "nat_gateway", "NAT\nGateway", "nat"),
        gw("sgw", "service_gateway", "Service\nGateway", "sgw")])],
    "edges": [{"source": "app-a", "target": "sgw", "label": "OCI APIs", "kind": "control"}],
}


class GatewayPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = quiet(ol.build_diagram, MODEL_GW)
        cls.vx, cls.vy, cls.vw, cls.vh = cls.d.abs_bbox("vcn-a")

    def test_gateways_are_region_children_with_address_ids(self):
        for cid in ("igw", "nat", "sgw"):
            self.assertEqual(self.d._cells[cid]["parent"], "region", cid)
        self.assertEqual(errors_of(self.d), [])

    def test_igw_and_nat_straddle_the_bottom_border(self):
        for i, cid in enumerate(("igw", "nat")):
            x, y, w, h = self.d.abs_bbox(cid)                       # 75x95 slot
            self.assertEqual(y + ol.GW_STRADDLE, self.vy + self.vh, cid)   # glyph centre on the border line
            self.assertEqual(x, self.vx + ol.PAD + i * ol.GW_PITCH, cid)

    def test_sgw_straddles_the_right_border_with_opaque_caption(self):
        x, y, w, h = self.d.abs_bbox("sgw")
        self.assertEqual(x + ol.GW_SIDE_DX, self.vx + self.vw)
        self.assertEqual(y, self.vy + ol.SIDE_GW_Y0)
        caption = self.d._cells["sgw"]["label_id"]
        self.assertEqual(style_of(self.d, caption)["fillColor"], db.COLORS["region_fill"])

    def test_vcn_keeps_clearance_from_straddling_glyphs(self):
        sx, sy, sw, sh = self.d.abs_bbox("subnet-sn-a")
        self.assertGreaterEqual(self.vy + self.vh - ol.GW_STRADDLE - (sy + sh), 20)      # bottom gateways
        self.assertGreaterEqual(self.vx + self.vw - ol.GW_SIDE_DX - (sx + sw), 20)       # right gateway

    def test_region_encloses_the_hanging_captions(self):
        rx, ry, rw, rh = self.d.abs_bbox("region")
        for cid in ("igw", "nat", "sgw"):
            fx, fy, fw, fh = self.d._abs_footprint(cid)
            self.assertLessEqual(fy + fh, ry + rh + 0.5, cid)
            self.assertLessEqual(fx + fw, rx + rw + 0.5, cid)

    def test_edge_to_a_gateway_still_resolves(self):
        edges = [e for e in self.d._cells.values() if e["kind"] == "edge" and e.get("target") == "sgw"]
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["source"], "app-a")


class LpgSideTests(unittest.TestCase):
    def _model(self, peer_a="lpg-b", peer_b="lpg-a"):
        return {"subject": "peering", "region": "us-ashburn-1", "vcns": [
            simple_vcn("a", gateways=[gw("lpg", "remote_peering_gateway", "LPG\nlpg-a", "lpg-a", peer=peer_a)]),
            simple_vcn("b", gateways=[gw("lpg", "remote_peering_gateway", "LPG\nlpg-b", "lpg-b", peer=peer_b)])],
            "edges": [{"source": "lpg-a", "target": "lpg-b", "label": "Local Peering", "kind": "attachment"}]}

    def test_lpgs_face_their_peer_vcn(self):
        d = quiet(ol.build_diagram, self._model())
        ax, ay, aw, ah = d.abs_bbox("vcn-a")
        bx, by, bw, bh = d.abs_bbox("vcn-b")
        lx, ly, _, _ = d.abs_bbox("lpg-a")
        self.assertEqual(lx + ol.GW_SIDE_DX, ax + aw)                 # right border of a
        rx, ry, _, _ = d.abs_bbox("lpg-b")
        self.assertEqual(rx + ol.GW_SIDE_DX - 1, bx)                  # left border of b
        self.assertEqual(ry, by + ol.LEFT_GW_Y0)
        self.assertGreaterEqual(bx - (ax + aw), ol.VCN_COLUMN_GAP_GW)
        self.assertEqual(errors_of(d), [])
        edge = next(e for e in d._cells.values() if e["kind"] == "edge" and e.get("source") == "lpg-a")
        self.assertEqual(edge["target"], "lpg-b")

    def test_peer_may_be_a_vcn_name_and_unknown_peer_goes_to_the_bottom(self):
        d = quiet(ol.build_diagram, self._model(peer_a="b", peer_b="nowhere"))
        ax, ay, aw, ah = d.abs_bbox("vcn-a")
        lx, _, _, _ = d.abs_bbox("lpg-a")
        self.assertEqual(lx + ol.GW_SIDE_DX, ax + aw)
        bx, by, bw, bh = d.abs_bbox("vcn-b")
        _, ry, _, _ = d.abs_bbox("lpg-b")
        self.assertEqual(ry + ol.GW_STRADDLE, by + bh)
        self.assertEqual(ol._gateway_side(gw("lpg", "remote_peering_gateway", "x", "l", peer="nowhere"), 0, {}), "bottom")
        self.assertEqual(ol._gateway_side(gw("sgw", "service_gateway", "x", "s"), 0, {}), "right")
        self.assertEqual(ol._gateway_side(gw("igw", "internet_gateway", "x", "i"), 0, {}), "bottom")
        self.assertEqual(ol._gateway_side({"icon": "nat_gateway", "label": "n"}, 0, {}), "bottom")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_oci_layout 2>&1 | tail -5`
Expected: FAIL/ERROR - `AttributeError: module 'oci_layout' has no attribute 'GW_STRADDLE'`, and `parent` assertions `'vcn-a' != 'region'`.

- [ ] **Step 3: Add the constants and side helpers**

In `oci-drawio-architect/scripts/oci_layout.py` after `DATA_TIERS = ("data",)` (line 92) add:

```python
# Gateways straddle the VCN border (glyph centre on the line); parent = region.
GW_STRADDLE = 40                 # slot top -> glyph centre (GLYPH_TOP + GLYPH_H / 2)
GW_SIDE_DX = 38                  # slot left offset from a side border (round(ICON_W / 2))
SIDE_GW_Y0 = ROW1_Y              # first right-border slot
LEFT_GW_Y0 = SIDE_GW_Y0          # first left-border slot: same y series as the right-border slots (spec 7.3)
SIDE_GW_PITCH = ROW_H
VCN_BOTTOM_PAD_GW = 60           # VCN bottom padding when bottom-border gateways exist
VCN_SIDE_PAD = 60                # VCN right padding when right-border gateways exist
SIDE_INSET = 40                  # extra left inset of the VCN content when left-border gateways exist
VCN_COLUMN_GAP_GW = 110          # column gap after a VCN with right-border gateways: two 105 px captions on facing borders must not touch (>= LABEL_W + 1)
SGW_ICONS = ("service_gateway", "sgw", "networking_service_gateway")
LPG_ICONS = ("remote_peering_gateway", "rpg", "networking_remote_peering_gateway")
```

After `_vcn_label` (line 142) add:

```python
def _vcn_order(vcns) -> dict:
    """VCN name / address / 'vcn:<name>' / gateway address -> column index (for LPG peers)."""
    order = {}
    for i, v in enumerate(vcns):
        for key in (v.get("name"), v.get("address"), f"vcn:{v.get('name')}"):
            if key:
                order.setdefault(str(key), i)
        for g in v.get("gateways") or []:
            if g.get("address"):
                order.setdefault(str(g["address"]), i)
    return order


def _gateway_side(gw: dict, vcn_index: int, order: dict) -> str:
    """bottom (IGW, NAT, unknown), right (SGW; LPG whose peer is a later column), left (LPG, earlier peer)."""
    gtype = str(gw.get("type") or "").lower()
    icon = str(gw.get("icon") or "")
    if gtype == "sgw" or (not gtype and icon in SGW_ICONS):
        return "right"
    if gtype == "lpg" or (not gtype and icon in LPG_ICONS):
        peer = gw.get("peer")
        peer_idx = order.get(str(peer)) if peer is not None else None
        if peer_idx is None or peer_idx == vcn_index:
            return "bottom"
        return "right" if peer_idx > vcn_index else "left"
    return "bottom"


def _gateway_sides(vcn: dict, vcn_index: int, order: dict) -> dict:
    sides = {"left": [], "right": [], "bottom": []}
    for g in vcn.get("gateways") or []:
        sides[_gateway_side(g, vcn_index, order)].append(g)
    return sides


def _place_edge_gateway(d: DrawioBuilder, region_id, box, side: str, slot: int, gw: dict, reg) -> str:
    """One gateway icon centred on a VCN border; box = (x, y, w, h) of the VCN in region coordinates."""
    vx, vy, vw, vh = box
    if side == "bottom":
        x, y = vx + PAD + slot * GW_PITCH, vy + vh - GW_STRADDLE
    elif side == "right":
        x, y = vx + vw - GW_SIDE_DX, vy + SIDE_GW_Y0 + slot * SIDE_GW_PITCH
    else:
        x, y = vx - GW_SIDE_DX + 1, vy + LEFT_GW_Y0 + slot * SIDE_GW_PITCH
    spec = {"label": gw.get("label", ""), "icon": gw.get("icon", "service_gateway")}
    if gw.get("address"):
        spec["key"] = str(gw["address"])
    for k in ("metadata", "tooltip"):
        if gw.get(k):
            spec[k] = gw[k]
    ids, _ = d.place_icons(region_id, [spec], cols=1, x0=int(x), y0=int(y), label_fill=COLORS["region_fill"])
    reg.add_item(gw, ids[0])
    return ids[0]
```

- [ ] **Step 4: Rework `_layout_vcn` and `build_diagram`**

Change the `_layout_vcn` signature to:

```python
def _layout_vcn(d: DrawioBuilder, region_id, vcn: dict, x, y, reg, max_row_w=MAX_ROW_W,
                inset_left=0, right_pad=PAD, bottom_pad=VCN_BOTTOM_PAD, min_h=200):
```

Inside it, four one-line edits plus one block replacement (before -> after):

Lines 243-245: `row1_right = PAD` -> `row1_right = PAD + inset_left`; `cx = PAD` -> `cx = PAD + inset_left`.
Line 261: `px = (row1_right + PANEL_GAP) if rows else PAD` -> `px = (row1_right + PANEL_GAP) if rows else PAD + inset_left`.
Lines 272-276:

```python
    row_w = max(row1_right - PAD - inset_left, 0)
    for s in data_subnets:
        n = len(s.get("items") or [])
        sid, w, h = _layout_subnet(d, vid, s, PAD + inset_left, cy, max(2, min(5, n or 2)), reg,
                                   min_w=row_w if row_w else None)
        cy += h + V_GAP
```

Then delete lines 279-292 (the whole `# Gateways in the bottom row (bare icons)` block, including `content_bottom` and `gateways`) and replace lines 294-296 (the last three lines: `fit_to_children`, `resize`, `return`) with:

```python
    w, h = d.fit_to_children(vid, pad=PAD, min_w=300, min_h=min_h)
    w += right_pad - PAD
    h += bottom_pad - PAD
    d.resize(vid, w=w, h=h)
    return vid, w, h
```

`GW_GAP` (line 80) becomes unused and may be deleted.

In `build_diagram`, replace the VCN loop (`vcn_boxes = [] ... x += w + VCN_COLUMN_GAP`) with:

```python
    order = _vcn_order(vcns)
    vcn_boxes = []
    edge_gateways = []          # (vcn index, side, gateway dict, icon id)
    x = vcn_x
    for i, vcn in enumerate(vcns):
        sides = _gateway_sides(vcn, i, order)
        need_h = max(
            200,
            (SIDE_GW_Y0 + (len(sides["right"]) - 1) * SIDE_GW_PITCH + ICON_FOOTPRINT_H + PAD) if sides["right"] else 0,
            (LEFT_GW_Y0 + (len(sides["left"]) - 1) * SIDE_GW_PITCH + ICON_FOOTPRINT_H + PAD) if sides["left"] else 0,
        )
        vid, w, h = _layout_vcn(d, rid, vcn, x, VCN_Y, reg, max_row_w=max_row_w,
                                inset_left=SIDE_INSET if sides["left"] else 0,
                                right_pad=VCN_SIDE_PAD if sides["right"] else PAD,
                                bottom_pad=VCN_BOTTOM_PAD_GW if sides["bottom"] else VCN_BOTTOM_PAD,
                                min_h=need_h)
        vcn_boxes.append((vid, x, VCN_Y, w, h))
        for side in ("bottom", "right", "left"):
            for slot, g in enumerate(sides[side]):
                gid = _place_edge_gateway(d, rid, (x, VCN_Y, w, h), side, slot, g, reg)
                edge_gateways.append((i, side, g, gid))
        x += w + (VCN_COLUMN_GAP_GW if sides["right"] else VCN_COLUMN_GAP)
```

Update the module docstring line 14 to `+-- gateways centred on the VCN border (IGW / NAT bottom, SGW right, LPG facing its peer), parented to the region` and the schema example's gateway entry to include `"type": "sgw"`. Update SKILL.md is done in Task 12; leave docs for now.

- [ ] **Step 5: Run the tests and the examples**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_oci_layout -v 2>&1 | tail -12 && cd .. && python3 -m unittest discover -s oci-drawio-architect/tests 2>&1 | tail -3 && python3 oci-drawio-architect/examples/generate_reference_layout.py /tmp/ref13.drawio && python3 oci-drawio-architect/scripts/check_overlaps.py /tmp/ref13.drawio`
Expected: 8 layout tests PASS; suite `OK`; reference gate `OK` (its `sgw` now sits on the VCN's right border and `nat` on the bottom border, both children of `region`). If the reference reports a leaf collision between the SGW caption and the services panel, the services panel is still inside the VCN at this task - confirm `VCN_SIDE_PAD` was applied (`right_pad`), which pushes the border 40 px right of the panel.

- [ ] **Step 6: Commit**

```bash
git add oci-drawio-architect/scripts/oci_layout.py oci-drawio-architect/tests/test_oci_layout.py
git commit -m "feat(layout): IGW/NAT/SGW/LPG straddle the VCN border as region-level icons"
```

---

### Task 6: Layout - regional services panel (Oracle Services Network) and SGW facing it

**Files:**
- Modify: `oci-drawio-architect/scripts/oci_layout.py` (constants after Task 5 block; `_layout_vcn` services block; `build_diagram` after the VCN loop; new `_layout_osn`)
- Test: `oci-drawio-architect/tests/test_oci_layout.py` (new class `OsnPanelTests`)

**Interfaces:**
- Consumes: `oci_topology.is_regional(item) -> bool`; Task 5 `edge_gateways` list; `DrawioBuilder.add_group(..., group_type="oracle_services_network", label_position="left")`; `add_edge(kind="attachment")` (Task 1).
- Produces: constants `OSN_GAP = 45`, `OSN_LABEL = "Oracle Services Network"`; `_split_services(items: list) -> tuple[list, list]` (regional, local); `_layout_osn(d, region_id, items, x, y, min_h, reg) -> tuple[str, int, int]` (panel id `osn`, width, height); registry keys `osn` (and `services` when no per-VCN panel exists); one edge per SGW with key `<sgw address>-osn`.

- [ ] **Step 1: Write the failing tests**

Append to `oci-drawio-architect/tests/test_oci_layout.py` (before `if __name__`):

```python
def svc(icon, address, **extra):
    s = {"icon": icon, "label": icon.replace("_", " ").title(), "address": address}
    s.update(extra)
    return s


class OsnPanelTests(unittest.TestCase):
    def test_regional_services_move_to_the_osn_panel_right_of_the_vcn(self):
        model = {"subject": "svc", "region": "us-ashburn-1", "vcns": [simple_vcn(
            "a", gateways=[gw("sgw", "service_gateway", "Service\nGateway", "sgw")],
            services=[svc("logging", "log"), svc("buckets", "bkt"), svc("file_storage", "fss")])]}
        d = quiet(ol.build_diagram, model)
        vx, vy, vw, vh = d.abs_bbox("vcn-a")
        ox, oy, ow, oh = d.abs_bbox("osn")
        self.assertEqual(d._cells["osn"]["group_type"], "oracle_services_network")
        self.assertEqual(d._cells["osn"]["parent"], "region")
        self.assertEqual(style_of(d, "osn")["align"], "left")
        # a right-border SGW widens the last column gap so its caption clears the panel
        self.assertEqual(ox, vx + vw + ol.OSN_GAP + (ol.VCN_COLUMN_GAP_GW - ol.VCN_COLUMN_GAP))
        self.assertEqual((oy, oh), (vy, vh))                          # same vertical extent as the VCN
        self.assertEqual(d._cells["log"]["parent"], "osn")
        self.assertEqual(d._cells["bkt"]["parent"], "osn")
        self.assertEqual(d._cells["fss"]["parent"], "services-a")      # VCN-resident stays in the VCN panel
        self.assertEqual(d._cells["services-a"]["parent"], "vcn-a")
        osn_edges = [e for e in d._cells.values() if e["kind"] == "edge" and e.get("target") == "osn"]
        self.assertEqual([(e["source"], e["label"]) for e in osn_edges], [("sgw", "")])
        self.assertEqual(style_of(d, "sgw-osn")["endArrow"], "none")
        self.assertEqual(errors_of(d), [])

    def test_all_regional_means_no_vcn_services_panel_and_services_alias(self):
        model = {"subject": "svc", "region": "us-ashburn-1",
                 "vcns": [simple_vcn("a", services=[svc("logging", "log"), svc("alarms", "alarm")])],
                 "edges": [{"source": "app-a", "target": "services", "label": "logs", "kind": "control"}]}
        d = quiet(ol.build_diagram, model)
        self.assertNotIn("services-a", d._cells)
        edge = next(e for e in d._cells.values() if e["kind"] == "edge" and e.get("source") == "app-a")
        self.assertEqual(edge["target"], "osn")
        self.assertEqual(errors_of(d), [])

    def test_regional_override_and_top_level_services(self):
        model = {"subject": "svc", "region": "us-ashburn-1",
                 "vcns": [simple_vcn("a", services=[svc("logging", "log", regional=False)]),
                          simple_vcn("b", services=[])],
                 "services": [svc("vault", "vault"), svc("bastion", "bastion", regional=False)]}
        d = quiet(ol.build_diagram, model)
        self.assertEqual(d._cells["log"]["parent"], "services-a")
        self.assertEqual(d._cells["vault"]["parent"], "osn")
        self.assertEqual(d._cells["bastion"]["parent"], "services")     # region-level "OCI Services" panel (2 VCNs)
        bx, _, bw, _ = d.abs_bbox("vcn-b")
        sx, _, sw, _ = d.abs_bbox("services")
        ox, _, _, _ = d.abs_bbox("osn")
        self.assertGreater(sx, bx + bw)
        self.assertGreater(ox, sx + sw)
        self.assertEqual(errors_of(d), [])

    def test_no_regional_services_means_no_osn_panel(self):
        d = quiet(ol.build_diagram, MODEL_GW)
        self.assertNotIn("osn", d._cells)
        self.assertEqual([e for e in d._cells.values() if e["kind"] == "edge" and e.get("target") == "osn"], [])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_oci_layout.OsnPanelTests 2>&1 | tail -5`
Expected: FAIL with `KeyError: 'osn'` (no OSN panel yet) and `'vcn-a' != 'osn'`-style assertion errors.

- [ ] **Step 3: Implement the split and the panel**

Add to the imports of `oci_layout.py`:

```python
from oci_topology import is_regional  # noqa: E402
```

Constants (after `LPG_ICONS`):

```python
OSN_GAP = 45                     # last VCN column -> Oracle Services Network panel
OSN_LABEL = "Oracle Services Network"
```

After `_place_edge_gateway` add:

```python
def _split_services(items) -> tuple:
    """(regional, vcn-resident) using item['regional'] or the icon-key table."""
    items = list(items or [])
    return [s for s in items if is_regional(s)], [s for s in items if not is_regional(s)]


def _layout_osn(d: DrawioBuilder, region_id, items, x, y, min_h, reg):
    rows_n, cols = _grid(len(items), 2)
    prov_w = cols * COL_W + SUBNET_EXTRA_W
    prov_h = ROW1_Y + (rows_n - 1) * ROW_H + ICON_FOOTPRINT_H + SUBNET_BOTTOM_PAD
    pid = d.add_group(OSN_LABEL, x, y, prov_w, prov_h, parent=region_id,
                      group_type="oracle_services_network", key="osn", label_position="left")
    reg.containers["osn"] = pid
    reg.containers.setdefault("services", pid)
    _icon_items(d, pid, items, cols, reg=reg)
    w, h = d.fit_to_children(pid, pad=PAD, min_w=prov_w, min_h=max(prov_h, min_h or 0))
    return pid, w, h
```

In `build_diagram`, replace the `top_services` handling before the VCN loop with:

```python
    vcns = [dict(v) for v in (model.get("vcns") or [])]
    osn_items = []
    for vcn in vcns:
        regional, local = _split_services(vcn.get("services"))
        osn_items.extend(regional)
        vcn["services"] = local
    regional, top_services = _split_services(model.get("services"))
    osn_items.extend(regional)
    if top_services and len(vcns) == 1:
        vcns[0]["services"] = list(vcns[0].get("services") or []) + top_services
        top_services = []
```

and after the VCN loop (the existing `if top_services:` region-level panel stays, using `x` and advancing `x += cols * COL_W + SUBNET_EXTRA_W + VCN_COLUMN_GAP` after `fit_to_children` - change that block to record its width: `pw, _ = d.fit_to_children(pid, pad=PAD)` then `x += pw + VCN_COLUMN_GAP`), add:

```python
    ref_h = max((b[4] for b in vcn_boxes), default=400)
    osn_id = None
    if osn_items:
        osn_x = (x - VCN_COLUMN_GAP + OSN_GAP) if (vcn_boxes or top_services) else x
        osn_id, _, _ = _layout_osn(d, rid, osn_items, osn_x, VCN_Y, ref_h, reg)
```

The existing `ref_h` computation inside `if hub:` is removed (it is computed once above). After the region is fitted and before the model edges are drawn, add:

```python
    if osn_id is not None:
        for _i, side, g, gid in edge_gateways:
            if side == "right" and (str(g.get("type") or "").lower() == "sgw" or str(g.get("icon") or "") in SGW_ICONS):
                d.add_edge(gid, osn_id, "", kind="attachment",
                           key=f"{g['address']}-osn" if g.get("address") else None)
```

Note the last column gap: because the loop adds `VCN_COLUMN_GAP` (or `VCN_COLUMN_GAP_GW`) after the last VCN, `osn_x = x - VCN_COLUMN_GAP + OSN_GAP` gives `last_right + OSN_GAP` when the last VCN had no right gateways and `last_right + OSN_GAP + (VCN_COLUMN_GAP_GW - VCN_COLUMN_GAP)` when it had (room for the SGW caption). The test asserts the second case because its VCN has an SGW.

Update the module docstring: `+-- Oracle Services Network panel (region level, right of the VCN columns; regional services)` and `"services"` comments (`# regional services -> Oracle Services Network panel; "regional": false keeps an item in the VCN panel`).

- [ ] **Step 4: Run the tests, the suite and the reference gate**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_oci_layout -v 2>&1 | tail -14 && cd .. && python3 -m unittest discover -s oci-drawio-architect/tests 2>&1 | tail -3 && python3 oci-drawio-architect/examples/generate_reference_layout.py /tmp/ref13.drawio && python3 oci-drawio-architect/scripts/check_overlaps.py /tmp/ref13.drawio`
Expected: 12 layout tests PASS; suite `OK`; reference `OK` - all eight reference services are regional, so the VCN's `OCI Services` panel disappears and an `osn` panel appears right of the VCN. Warnings about estimated crossings are acceptable at this task; errors are not.

- [ ] **Step 5: Commit**

```bash
git add oci-drawio-architect/scripts/oci_layout.py oci-drawio-architect/tests/test_oci_layout.py
git commit -m "feat(layout): region-level Oracle Services Network panel fed by the Service Gateway"
```

---

### Task 7: Layout - schema-2 wiring, DRG column, attachments, icon and box styles, connector kinds

**Files:**
- Modify: `oci-drawio-architect/scripts/oci_layout.py` (imports, constants, `EDGE_KINDS` at line 94, `build_diagram`, new `_drg_*` helpers before `build_diagram`)
- Test: `oci-drawio-architect/tests/test_oci_layout.py` (new classes `DrgColumnTests`, `DrgStyleTests`, `LegacyModelTests`)

**Interfaces:**
- Consumes: `oci_topology.migrate_legacy_model`, `classify_topology`, `choose_drg_style`, `attachment_type`, `attachment_label`, `attachment_link_label`, `first_line`; `DrawioBuilder.add_box`, `add_group(group_type="drg")`, `add_edge(kind=)`; Task 5/6 helpers.
- Produces: `build_diagram(model, style_profile="default", legend=False, logo=None, page_name=None, title=True, max_row_w=MAX_ROW_W, drg_style=None) -> DrawioBuilder` with `builder.layout_info = {"topology": dict, "warnings": list[str], "drg_style": dict[address, "icon"|"box"]}`; constants `DRG_GAP = 45`, `ATT_W = 100`, `ATT_H = 44`, `ATT_GAP = 15`, `ATT_PITCH = 56`, `DRG_CLUSTER_GAP = 40`; helpers `_drg_attachments(drg) -> list`, `_drg_style_for(drg, requested) -> str`, `_drg_cluster_geometry(drg, style) -> dict` (keys `left, right, left_w, inner_w, body_h, cluster_h`), `_drg_column_width(drgs, requested) -> int`, `_layout_drg_column(d, region_id, drgs, col_x, stack_y, stack_h, requested, reg, style_out) -> list[dict]` (pending connectors `{"source", "vcn", "target", "label", "key"}`), `_resolve_attachment_target(reg, pe) -> str | None`; `EDGE_KINDS` values become `dict(kind=<builder kind>, color=...)`. Cell ids: DRG = its address; attachment box = its address; attachment connector = `<address>-edge`; box-style group = `drgbox:<address>` (slugged `drgbox-<address>`); registry aliases `drg:<name>`.

- [ ] **Step 1: Write the failing tests**

Append to `oci-drawio-architect/tests/test_oci_layout.py` (before `if __name__`):

```python
HYBRID = {
    "subject": "Spoke", "region": "us-ashburn-1",
    "hub": {"name": "On-premises", "items": [{"icon": "cpe", "label": "CPE\nhq", "address": "cpe"}]},
    "drgs": [{"name": "drg", "address": "drg", "label": "DRG\ndrg", "attachments": [
        {"type": "vcn", "vcn": "Spoke", "address": "att-spoke", "label": "VCN attachment\nSpoke"}]}],
    "vcns": [simple_vcn("Spoke", gateways=[gw("sgw", "service_gateway", "Service\nGateway", "sgw")])],
    "edges": [{"source": "cpe", "target": "drg", "label": "IPSec VPN", "kind": "data"},
              {"source": "drg", "target": "app-Spoke", "label": "", "kind": "data"}],
}


class DrgColumnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = quiet(ol.build_diagram, HYBRID)

    def test_topology_and_style_recorded(self):
        self.assertEqual(self.d.layout_info["topology"]["kind"], "hybrid")
        self.assertEqual(self.d.layout_info["drg_style"], {"drg": "icon"})
        self.assertEqual(self.d.layout_info["warnings"], [])

    def test_drg_is_a_region_child_between_hub_and_vcn(self):
        d = self.d
        self.assertEqual(d._cells["drg"]["parent"], "region")
        hx, hy, hw, hh = d.abs_bbox("hub")
        vx, vy, vw, vh = d.abs_bbox("vcn-Spoke")
        dx, dy, dw, dh = d.abs_bbox("drg")
        self.assertGreaterEqual(dx, hx + hw + ol.HUB_GAP)
        self.assertLess(dx + dw, vx)
        self.assertAlmostEqual(dy + ol.GW_STRADDLE, vy + vh / 2, delta=ol.ATT_PITCH)   # centred on the VCN stack

    def test_attachment_box_sits_between_drg_and_vcn_and_connects_to_the_border(self):
        d = self.d
        bx, by, bw, bh = d.abs_bbox("att-spoke")
        dx, dy, dw, dh = d.abs_bbox("drg")
        vx, vy, vw, vh = d.abs_bbox("vcn-Spoke")
        self.assertEqual(d._cells["att-spoke"]["parent"], "region")
        self.assertEqual(bx, dx + ol.ICON_W + ol.ATT_GAP)
        self.assertEqual((bw, bh), (ol.ATT_W, ol.ATT_H))
        self.assertEqual(vx - (bx + bw), ol.DRG_GAP)
        e = d._cells["att-spoke-edge"]
        self.assertEqual((e["source"], e["target"]), ("att-spoke", "vcn-Spoke"))
        tok = style_of(d, "att-spoke-edge")
        self.assertEqual((tok["endArrow"], tok["strokeWidth"], tok["dashed"]), ("none", "1", "0"))

    def test_hub_holds_only_the_cpe_and_explicit_edges_resolve(self):
        d = self.d
        self.assertEqual([c for c, e in d._cells.items() if e["parent"] == "hub" and e["kind"] == "icon"], ["cpe"])
        pairs = {(e["source"], e["target"]) for e in d._cells.values() if e["kind"] == "edge" and e.get("source")}
        self.assertIn(("cpe", "drg"), pairs)
        self.assertIn(("drg", "app-Spoke"), pairs)
        self.assertEqual(errors_of(d), [])

    def test_edge_kinds_map_to_builder_kinds(self):
        model = copy.deepcopy(MODEL_GW)
        model["vcns"][0]["subnets"][0]["items"].append({"icon": "vault", "label": "Vault", "address": "vault-a"})
        model["edges"] = [
            {"source": "app-a", "target": "vault-a", "label": "secrets", "kind": "association", "address": "e-assoc"},
            {"source": "app-a", "target": "sgw", "label": "443", "kind": "control", "address": "e-ctl"},
            {"source": "app-a", "target": "igw", "label": "", "kind": "datalake", "address": "e-lake"},
            {"source": "app-a", "target": "nat", "label": "", "kind": "data", "dashed": True, "address": "e-dashed"},
        ]
        d = quiet(ol.build_diagram, model)
        self.assertEqual((style_of(d, "e-assoc")["dashPattern"], style_of(d, "e-assoc")["endArrow"]), ("1 3", "none"))
        self.assertEqual((style_of(d, "e-ctl")["dashed"], style_of(d, "e-ctl")["endArrow"]), ("1", "open"))
        self.assertEqual(style_of(d, "e-lake")["strokeColor"], db.COLORS["edge_purple"])
        self.assertEqual(style_of(d, "e-dashed")["endArrow"], "none")     # explicit dashed keeps the profile look


class DrgStyleTests(unittest.TestCase):
    def _hub_spoke(self, n=5):
        vcns = [simple_vcn(f"v{i}") for i in range(2)]
        atts = [{"type": "vcn", "vcn": f"v{i % 2}", "address": f"att-{i}"} for i in range(n)]
        return {"subject": "hs", "region": "us-ashburn-1", "vcns": vcns,
                "drgs": [{"name": "drg", "address": "drg", "label": "DRG\ndrg", "attachments": atts}]}

    def test_auto_picks_box_above_four_attachments(self):
        d = quiet(ol.build_diagram, self._hub_spoke(5))
        self.assertEqual(d.layout_info["topology"]["kind"], "hub_spoke")
        self.assertEqual(d.layout_info["drg_style"]["drg"], "box")
        self.assertEqual(d._cells["drgbox-drg"]["group_type"], "drg")
        self.assertEqual(d._cells["drgbox-drg"]["parent"], "region")
        self.assertEqual(d._cells["drg"]["parent"], "drgbox-drg")
        self.assertEqual(d._cells["att-0"]["parent"], "drgbox-drg")
        self.assertEqual(style_of(d, "drgbox-drg")["ociGroup"], "drg")
        self.assertEqual(errors_of(d), [])

    def test_auto_picks_icon_up_to_four_and_overrides_apply(self):
        d = quiet(ol.build_diagram, self._hub_spoke(4))
        self.assertEqual(d.layout_info["drg_style"]["drg"], "icon")
        self.assertNotIn("drgbox-drg", d._cells)
        d = quiet(ol.build_diagram, self._hub_spoke(2), drg_style="box")
        self.assertIn("drgbox-drg", d._cells)
        model = self._hub_spoke(6)
        model["drg_style"] = "icon"
        d = quiet(ol.build_diagram, model)
        self.assertNotIn("drgbox-drg", d._cells)
        with self.assertRaises(ValueError):
            quiet(ol.build_diagram, model, drg_style="fancy")

    def test_onprem_attachments_sit_left_and_link_to_the_hub_item(self):
        model = self._hub_spoke(1)
        model["hub"] = {"name": "On-premises", "items": [{"icon": "cpe", "label": "CPE", "address": "cpe"},
                                                          {"icon": "rpg", "label": "RPC peer", "address": "rpc-peer"}]}
        model["drgs"][0]["attachments"] += [
            {"type": "ipsec", "target": "cpe", "address": "att-vpn", "label": "vpn-hq"},
            {"type": "rpc", "target": "rpc-peer", "address": "att-rpc"},
            {"type": "loopback", "address": "att-loop"}]
        d = quiet(ol.build_diagram, model)
        self.assertEqual(d.layout_info["topology"]["kind"], "hybrid")
        dx, _, _, _ = d.abs_bbox("drg")
        vx, _, _, _ = d.abs_bbox("att-vpn")
        self.assertEqual(vx + ol.ATT_W + ol.ATT_GAP, dx)
        self.assertEqual(d._cells["att-vpn-edge"]["target"], "cpe")
        self.assertEqual(d._cells["att-vpn-edge"]["label"], "Site-to-Site VPN")
        self.assertEqual(d._cells["att-rpc-edge"]["label"], "Remote Peering")
        self.assertEqual(d._cells["att-rpc"]["label"], "RPC attachment")
        self.assertNotIn("att-loop", d._cells)
        self.assertEqual(errors_of(d), [])


class LegacyModelTests(unittest.TestCase):
    LEGACY = {
        "subject": "Spoke", "region": "us-ashburn-1",
        "hub": {"name": "Hub Network", "link_label": "IPSec VPN",
                "items": [{"icon": "firewall", "label": "Corp VPN", "address": "cpe"},
                          {"icon": "drg", "label": "Dynamic Routing\nGateway (DRG)", "address": "drg"}]},
        "vcns": [simple_vcn("Spoke", gateways=[gw("sgw", "service_gateway", "Service\nGateway", "sgw")])],
        "edges": [{"source": "drg", "target": "app-Spoke", "label": "", "kind": "data"}],
    }

    def test_legacy_hub_drg_is_drawn_at_region_level_with_a_warning(self):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            d = ol.build_diagram(self.LEGACY)
        self.assertEqual(d._cells["drg"]["parent"], "region")
        self.assertEqual([c for c, e in d._cells.items() if e["parent"] == "hub" and e["kind"] == "icon"], ["cpe"])
        self.assertIn("drg-Spoke", d._cells)                      # implicit attachment drg@Spoke
        pairs = {(e["source"], e["target"]) for e in d._cells.values() if e["kind"] == "edge" and e.get("source")}
        self.assertIn(("cpe", "drg"), pairs)                      # link_label became an explicit edge
        self.assertIn(("drg", "app-Spoke"), pairs)
        self.assertTrue(d.layout_info["warnings"])
        self.assertIn("WARNING: legacy model: hub item 'drg' moved to drgs[]", err.getvalue())
        self.assertEqual(errors_of(d), [])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_oci_layout.DrgColumnTests tests.test_oci_layout.DrgStyleTests tests.test_oci_layout.LegacyModelTests 2>&1 | tail -6`
Expected: ERROR/FAIL - DrgColumnTests error in setUpClass with `ValueError: edge endpoint 'drg' not found` (no DRG cell yet), `TypeError: build_diagram() got an unexpected keyword argument 'drg_style'` in DrgStyleTests, `AttributeError: 'DrawioBuilder' object has no attribute 'layout_info'`, and for the legacy model `AssertionError: 'hub' != 'region'` (the DRG is still drawn inside the hub panel).

- [ ] **Step 3: Constants, imports and `EDGE_KINDS`**

In `oci_layout.py` extend the topology import to:

```python
from oci_topology import (  # noqa: E402
    attachment_label, attachment_link_label, attachment_type, choose_drg_style, classify_topology,
    first_line, is_regional, migrate_legacy_model,
)
```

Add constants after `OSN_LABEL`:

```python
DRG_GAP = 45                     # DRG column -> first VCN column
ATT_W = 100                      # attachment box
ATT_H = 44
ATT_GAP = 15                     # DRG slot -> attachment boxes
ATT_PITCH = 56                   # vertical pitch of stacked attachment boxes
DRG_CLUSTER_GAP = 40             # between stacked DRG clusters
```

Replace `EDGE_KINDS` (lines 94-100) with:

```python
# model edge kind -> builder kind (+ colour). analytics / datalake are project
# extensions kept for compatibility; management is an alias of control.
EDGE_KINDS = {
    "data": dict(kind="data", color=None),
    "control": dict(kind="control", color=None),
    "management": dict(kind="control", color=None),
    "association": dict(kind="association", color=None),
    "attachment": dict(kind="attachment", color=None),
    "analytics": dict(kind="data", color=COLORS["edge_accent"]),
    "datalake": dict(kind="control", color=COLORS["edge_purple"]),
}
```

- [ ] **Step 4: DRG column helpers**

Insert before `def build_diagram`:

```python
def _drg_attachments(drg: dict) -> list:
    return [a for a in (drg.get("attachments") or []) if attachment_type(a) != "loopback"]


def _drg_style_for(drg: dict, requested: str) -> str:
    return choose_drg_style(requested, len(_drg_attachments(drg)))


def _drg_cluster_geometry(drg: dict, style: str) -> dict:
    """Sizes of one DRG cluster: icon slot + attachment boxes (right = VCNs, left = on-prem / RPC)."""
    atts = _drg_attachments(drg)
    right = [a for a in atts if attachment_type(a) == "vcn"]
    left = [a for a in atts if attachment_type(a) != "vcn"]
    left_w = ATT_W + ATT_GAP if left else 0
    right_w = ATT_W + ATT_GAP if right else 0
    n = max(len(left), len(right))
    boxes_h = n * ATT_PITCH - (ATT_PITCH - ATT_H) if n else 0
    body_h = max(ICON_FOOTPRINT_H, boxes_h)
    inner_w = left_w + ICON_W + right_w
    cluster_h = body_h
    if style == "box":
        inner_w += 2 * PAD
        cluster_h += ROW1_Y + PAD
    return {"left": left, "right": right, "left_w": left_w, "inner_w": inner_w,
            "body_h": body_h, "cluster_h": cluster_h}


def _drg_column_width(drgs, requested: str) -> int:
    return max(_drg_cluster_geometry(drg, _drg_style_for(drg, requested))["inner_w"] for drg in drgs)


def _layout_drg_column(d: DrawioBuilder, region_id, drgs, col_x, stack_y, stack_h, requested, reg, style_out) -> list:
    """DRG icon(s) with their attachment boxes at region level, centred on the VCN stack.

    Returns the pending attachment connectors: {"source", "vcn", "target", "label", "key"}.
    """
    clusters = [(drg, _drg_style_for(drg, requested)) for drg in drgs]
    geoms = [_drg_cluster_geometry(drg, style) for drg, style in clusters]
    total_h = sum(g["cluster_h"] for g in geoms) + DRG_CLUSTER_GAP * (len(geoms) - 1)
    y = max(VCN_Y, int(round((stack_y + (stack_h - total_h) / 2) / 10.0) * 10))
    pending = []
    for (drg, style), g in zip(clusters, geoms):
        name = drg.get("name") or first_line(drg.get("label")) or "DRG"
        addr = str(drg.get("address") or f"drg:{name}")
        label = drg.get("label") or f"DRG\n{name}"
        if style == "box":
            gid = d.add_group(f"DRG: {name}", col_x, y, g["inner_w"], g["cluster_h"], parent=region_id,
                              group_type="drg", key=f"drgbox:{addr}")
            parent, x0, y0 = gid, PAD, ROW1_Y
        else:
            parent, x0, y0 = region_id, col_x, y
        cy = y0 + g["body_h"] / 2
        slot_x = x0 + g["left_w"]
        slot_y = int(round(cy - GW_STRADDLE))
        spec = {"label": label, "icon": drg.get("icon") or "drg", "key": addr}
        for k in ("metadata", "tooltip"):
            if drg.get(k):
                spec[k] = drg[k]
        (did,), _ = d.place_icons(parent, [spec], cols=1, x0=slot_x, y0=slot_y)
        reg.add_item({"address": addr, "label": label}, did)
        reg.containers[f"drg:{name}"] = did
        for side, atts in (("right", g["right"]), ("left", g["left"])):
            if not atts:
                continue
            bx = slot_x + ICON_W + ATT_GAP if side == "right" else x0
            block_h = len(atts) * ATT_PITCH - (ATT_PITCH - ATT_H)
            by = int(round(cy - block_h / 2))
            for i, att in enumerate(atts):
                akey = str(att["address"]) if att.get("address") else None
                text = attachment_label(att)
                bid = d.add_box(text, bx, by + i * ATT_PITCH, ATT_W, ATT_H, parent=parent, key=akey,
                                metadata=att.get("metadata"), tooltip=att.get("tooltip"))
                reg.add_item({"address": att.get("address"), "label": text}, bid)
                pending.append({"source": bid,
                                "vcn": att.get("vcn") if side == "right" else None,
                                "target": att.get("target") if side == "left" else None,
                                "label": attachment_link_label(att),
                                "key": f"{akey}-edge" if akey else None})
        if style == "box":
            d.fit_to_children(gid, pad=PAD)
        style_out[addr] = style
        y += g["cluster_h"] + DRG_CLUSTER_GAP
    return pending


def _resolve_attachment_target(reg: _Registry, pe: dict):
    if pe.get("vcn") is not None:
        for ref in (f"vcn:{pe['vcn']}", str(pe["vcn"])):
            try:
                return reg.resolve(ref)
            except ValueError:
                continue
        raise ValueError(f"DRG attachment {pe['source']!r}: VCN {pe['vcn']!r} is not in the model")
    if pe.get("target"):
        return reg.resolve(pe["target"])
    return None
```

- [ ] **Step 5: Rewrite `build_diagram`**

Replace the whole `build_diagram` function with (Task 5 and Task 6 pieces are included verbatim so the function reads top to bottom):

```python
def build_diagram(model: dict, style_profile="default", legend=False, logo=None,
                  page_name=None, title=True, max_row_w=MAX_ROW_W, drg_style=None) -> DrawioBuilder:
    """Lay out a normalized model and return the (unwritten) DrawioBuilder.

    Schema-1 models are migrated first (DRG hub items / drg gateways -> drgs[]);
    migration warnings go to stderr and to ``builder.layout_info["warnings"]``.
    ``drg_style`` (auto | icon | box) overrides ``model["drg_style"]``.
    """
    model, warnings = migrate_legacy_model(model)
    for w in warnings:
        print(w, file=sys.stderr)
    if not model.get("vcns") and not model.get("hub") and not model.get("drgs"):
        raise ValueError("model needs at least one VCN (model['vcns']), a hub or a DRG")
    requested = str(drg_style or model.get("drg_style") or "auto").lower()
    choose_drg_style(requested, 0)                     # validates the value early
    topo = classify_topology(model)
    subject = model.get("subject") or (model["vcns"][0].get("name") if model.get("vcns") else "Architecture")
    d = DrawioBuilder(page_name=page_name or f"{subject} Architecture", style_profile=style_profile)
    d.layout_info = {"topology": topo, "warnings": list(warnings), "drg_style": {}}
    reg = _Registry()

    if title:
        d.add_title(f"{subject} - Architecture", region_label=model.get("region_label"),
                    region=model.get("region"), compartment=model.get("compartment"),
                    tenancy=model.get("tenancy_name"), x=TITLE_BOX[0], y=TITLE_BOX[1],
                    w=TITLE_BOX[2], h=TITLE_BOX[3], logo=logo, page_w=None)

    region_label = model.get("region") or model.get("region_label") or "Region"
    rid = d.add_group(region_label, REGION_XY[0], REGION_XY[1], 800, 600, group_type="region",
                      key="region")
    reg.containers["region"] = rid

    hub = model.get("hub")
    drgs = list(model.get("drgs") or [])
    vcns = [dict(v) for v in (model.get("vcns") or [])]
    osn_items = []
    for vcn in vcns:
        regional, local = _split_services(vcn.get("services"))
        osn_items.extend(regional)
        vcn["services"] = local
    regional, top_services = _split_services(model.get("services"))
    osn_items.extend(regional)
    if top_services and len(vcns) == 1:
        vcns[0]["services"] = list(vcns[0].get("services") or []) + top_services
        top_services = []

    # Column order: on-premises panel | DRG column | VCN columns | OCI Services | Oracle Services Network
    x = HUB_X + HUB_W + HUB_GAP if hub else PAD
    drg_col_x = x
    if drgs:
        x = drg_col_x + _drg_column_width(drgs, requested) + DRG_GAP

    order = _vcn_order(vcns)
    vcn_boxes = []
    edge_gateways = []                 # (vcn index, side, gateway dict, icon id)
    for i, vcn in enumerate(vcns):
        sides = _gateway_sides(vcn, i, order)
        need_h = max(
            200,
            (SIDE_GW_Y0 + (len(sides["right"]) - 1) * SIDE_GW_PITCH + ICON_FOOTPRINT_H + PAD) if sides["right"] else 0,
            (LEFT_GW_Y0 + (len(sides["left"]) - 1) * SIDE_GW_PITCH + ICON_FOOTPRINT_H + PAD) if sides["left"] else 0,
        )
        vid, w, h = _layout_vcn(d, rid, vcn, x, VCN_Y, reg, max_row_w=max_row_w,
                                inset_left=SIDE_INSET if sides["left"] else 0,
                                right_pad=VCN_SIDE_PAD if sides["right"] else PAD,
                                bottom_pad=VCN_BOTTOM_PAD_GW if sides["bottom"] else VCN_BOTTOM_PAD,
                                min_h=need_h)
        vcn_boxes.append((vid, x, VCN_Y, w, h))
        for side in ("bottom", "right", "left"):
            for slot, g in enumerate(sides[side]):
                gid = _place_edge_gateway(d, rid, (x, VCN_Y, w, h), side, slot, g, reg)
                edge_gateways.append((i, side, g, gid))
        x += w + (VCN_COLUMN_GAP_GW if sides["right"] else VCN_COLUMN_GAP)

    if top_services:
        rows_n, cols = _grid(len(top_services), 2)
        pid = d.add_group("OCI Services", x, VCN_Y, cols * COL_W + SUBNET_EXTRA_W,
                          ROW1_Y + (rows_n - 1) * ROW_H + ICON_FOOTPRINT_H + SUBNET_BOTTOM_PAD,
                          parent=rid, group_type="services", key="services")
        reg.containers["services"] = pid
        _icon_items(d, pid, top_services, cols, reg=reg)
        pw, _ = d.fit_to_children(pid, pad=PAD)
        x += pw + VCN_COLUMN_GAP

    ref_h = max((b[4] for b in vcn_boxes), default=400)
    osn_id = None
    if osn_items:
        osn_x = (x - VCN_COLUMN_GAP + OSN_GAP) if (vcn_boxes or top_services) else x
        osn_id, _, _ = _layout_osn(d, rid, osn_items, osn_x, VCN_Y, ref_h, reg)

    if hub:
        pairs = {(str(e.get("source")), str(e.get("target"))) for e in (model.get("edges") or [])}
        _layout_hub(d, rid, hub, VCN_Y, ref_h, reg, explicit_pairs=pairs)

    pending = []
    if drgs:
        pending = _layout_drg_column(d, rid, drgs, drg_col_x, VCN_Y, ref_h, requested, reg,
                                     d.layout_info["drg_style"])

    d.fit_to_children(rid, pad=PAD)

    if model.get("notes"):
        d.add_text(escape_label(model["notes"]), TITLE_BOX[0] + TITLE_BOX[2] + 20, TITLE_BOX[1],
                   400, TITLE_BOX[3], font_size=10, raw_html=True)

    if osn_id is not None:
        for _i, side, g, gid in edge_gateways:
            if side == "right" and (str(g.get("type") or "").lower() == "sgw" or str(g.get("icon") or "") in SGW_ICONS):
                d.add_edge(gid, osn_id, "", kind="attachment",
                           key=f"{g['address']}-osn" if g.get("address") else None)

    for pe in pending:
        target = _resolve_attachment_target(reg, pe)
        if target is not None:
            d.add_edge(pe["source"], target, pe["label"], kind="attachment", key=pe["key"])

    for e in model.get("edges") or []:
        spec = EDGE_KINDS.get(str(e.get("kind") or "data").lower(), EDGE_KINDS["data"])
        kwargs = dict(color=e.get("color", spec["color"]), key=e.get("address"))
        if "dashed" in e:
            kwargs["dashed"] = e["dashed"]            # explicit override keeps the profile look
        else:
            kwargs["kind"] = spec["kind"]
        d.add_edge(reg.resolve(e["source"]), reg.resolve(e["target"]), e.get("label", ""), **kwargs)

    if legend:
        _, _, _, bottom = d.content_bbox()
        d.add_legend(REGION_XY[0], bottom + GAP)

    d.fit_page(margin=PAD)
    return d
```

- [ ] **Step 6: Run the tests, the suite and the reference gate**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_oci_layout -v 2>&1 | tail -22 && cd .. && python3 -m unittest discover -s oci-drawio-architect/tests 2>&1 | tail -3 && python3 oci-drawio-architect/examples/generate_reference_layout.py /tmp/ref13.drawio 2>&1 | tail -4 && python3 oci-drawio-architect/scripts/check_overlaps.py /tmp/ref13.drawio`
Expected: all layout tests PASS; suite `OK`; the (still legacy) reference prints `WARNING: legacy model: hub item 'drg' moved to drgs[]` and `WARNING: model: DRG 'drg' has no attachments; assuming a VCN attachment to 'Spoke-VCN-D'`, writes the file, and the gate prints `OK`.

- [ ] **Step 7: Commit**

```bash
git add oci-drawio-architect/scripts/oci_layout.py oci-drawio-architect/tests/test_oci_layout.py
git commit -m "feat(layout): region-level DRG column with attachment boxes, icon/box styles and connector kinds"
```

---

### Task 8: Layout CLI flag, docstring schema and render path

**Files:**
- Modify: `oci-drawio-architect/scripts/oci_layout.py:1-61` (module docstring), `main()` (line ~419)
- Test: `oci-drawio-architect/tests/test_oci_layout.py` (new class `CliTests`)

**Interfaces:**
- Consumes: `build_diagram(..., drg_style=)` (Task 7); `write_diagram(model, out_path, strict=False, render_fmt=None, **opts)` (unchanged, forwards `drg_style`); `check_overlaps.main(argv) -> int`.
- Produces: CLI `python3 oci_layout.py model.json -o out.drawio [--profile ...] [--legend] [--logo f] [--strict] [--render png|svg|pdf] [--drg-style auto|icon|box]`.

- [ ] **Step 1: Write the CLI test (the first one fails; the second is a regression guard that already passes after Task 7)**

Append to `oci-drawio-architect/tests/test_oci_layout.py`:

```python
class CliTests(unittest.TestCase):
    def test_cli_drg_style_and_gate(self):
        import check_overlaps
        with tempfile.TemporaryDirectory() as tmp:
            mpath = Path(tmp) / "m.json"
            out = Path(tmp) / "o.drawio"
            mpath.write_text(json.dumps(HYBRID))
            self.assertEqual(quiet(ol.main, [str(mpath), "-o", str(out), "--drg-style", "box"]), 0)
            self.assertIn('id="drgbox-drg"', out.read_text(encoding="utf-8"))
            self.assertEqual(quiet(check_overlaps.main, [str(out)]), 0)
            self.assertEqual(quiet(ol.main, [str(mpath), "-o", str(out)]), 0)
            self.assertNotIn('id="drgbox-drg"', out.read_text(encoding="utf-8"))
            self.assertEqual(quiet(check_overlaps.main, [str(out)]), 0)

    def test_write_diagram_forwards_drg_style_and_legend(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = quiet(ol.write_diagram, HYBRID, Path(tmp) / "h.drawio", drg_style="box", legend=True)
            text = out.read_text(encoding="utf-8")
            self.assertIn('id="drgbox-drg"', text)
            self.assertIn("Attachment (structural)", text)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_oci_layout.CliTests 2>&1 | tail -4`
Expected: test_cli_drg_style_and_gate errors with `SystemExit: 2` from argparse (`unrecognized arguments: --drg-style box`); test_write_diagram_forwards_drg_style_and_legend passes.

- [ ] **Step 3: Add the flag and update the docstring**

In `main()` add after the `--render` argument:

```python
    ap.add_argument("--drg-style", default=None, choices=("auto", "icon", "box"),
                    help="DRG presentation: icon (DRG icon with attachment boxes beside it) or box "
                         "(dashed 'DRG: <name>' group holding them); auto = icon unless a DRG has more "
                         "than 4 attachments (overrides model['drg_style'])")
```

and pass `drg_style=args.drg_style` to `write_diagram(...)`. Replace the module docstring's layout sketch and schema with:

```
    Title block (bold subject, italic "Region label (region) - Compartment: X")
    Region (solid, label top-left)
      +-- On-premises panel (left, vertically centred on the VCN stack): CPE, virtual circuit, RPC peer
      +-- DRG column (region level, centred on the VCN stack): DRG icon with one attachment
      |   box per attachment beside it (VCN attachments facing the VCNs, on-prem / RPC
      |   attachments facing the on-premises panel); drg_style "box" wraps them in a dashed group
      +-- VCN column(s)
      |     +-- row 1: lb -> app -> compute -> mgmt subnets (traffic order, 2 icon columns)
      |     +-- OCI Services panel (right of row 1) only for VCN-resident services without a subnet
      |     +-- data-tier subnets stretched to the row width
      |     gateways centred on the VCN border: IGW / NAT bottom, SGW right, LPG facing its peer
      +-- Oracle Services Network panel (right of the VCN columns, regional services, fed by the SGW)
      edges auto-routed through the gutters; optional legend below the region.

Model schema v2 (JSON-serialisable dict; every key optional except vcns/subject):

    {
      "subject": "Spoke-VCN-D", "region": "us-ashburn-1", "region_label": "Ashburn",
      "compartment": "Spoke-VCN-D", "tenancy_name": null,
      "drg_style": "auto",                # auto | icon | box (CLI --drg-style overrides)
      "hub": {"name": "On-premises",      # on-premises side only: CPE, IPSec, virtual circuit, RPC peer
              "items": [{"icon": "cpe", "label": "Corp VPN\\n(10.0.0.0/8)", "address": "cpe"}],
              "link_label": null},
      "drgs": [{"name": "drg", "address": "drg", "label": "Dynamic Routing\\nGateway (DRG)",
                "attachments": [{"type": "vcn", "vcn": "Spoke-VCN-D", "address": "drg-att-spoke",
                                 "label": "VCN attachment\\nSpoke-VCN-D"},
                                {"type": "ipsec", "target": "cpe", "address": "vpn@drg", "label": "vpn-hq"}]}],
      "vcns": [{
         "name": "Spoke-VCN-D", "cidr": "10.0.0.0/16",
         "subnets": [{"name": "sn-priv-lb", "cidr": "10.0.0.0/24", "tier": "lb", "public": false,
                      "items": [{"icon": "load_balancer", "label": "Load Balancer\\n10.0.0.23",
                                 "address": "lb", "metadata": {"ocid": "..."}, "tooltip": "..."}]}],
         "services": [{"icon": "logging", "label": "Logging", "address": "logs", "regional": true}],
         "services_label": "OCI Services",
         "gateways": [{"icon": "service_gateway", "type": "sgw", "label": "Service\\nGateway", "address": "sgw"},
                      {"icon": "remote_peering_gateway", "type": "lpg", "label": "LPG", "address": "lpg-a",
                       "peer": "lpg-b"}]
      }],
      "services": [ ... ],                  # more services; regional ones join the OSN panel
      "edges": [{"source": "lb", "target": "app-vm", "label": "3000 / 8000", "kind": "data"}],
      "notes": "optional free text placed under the title"
    }

Attachment "type": vcn (target = that VCN's border), ipsec / virtual_circuit (target = the
on-premises item, connector labelled "Site-to-Site VPN" / "FastConnect"), rpc (target = the
remote peer item, "Remote Peering"), loopback (not drawn). Services are regional (Oracle
Services Network panel) when "regional" is true or the icon is in
oci_topology.REGIONAL_ICON_KEYS; VCN-resident ones stay in the VCN.
Edge "kind": data (solid, open arrow), control / management (dashed, open arrow),
association (dotted, no arrowhead), attachment (thin solid, no arrowhead), analytics
(solid Sienna), datalake (dashed purple); or pass "dashed"/"color" directly.
Schema-1 models (DRG in hub.items or as a "drg" gateway) are migrated with a WARNING.
```

and add `[--drg-style auto|icon|box]` to the CLI usage line.

- [ ] **Step 4: Run the tests**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_oci_layout -v 2>&1 | tail -6 && cd .. && python3 -m unittest discover -s oci-drawio-architect/tests 2>&1 | tail -3`
Expected: PASS; suite `OK`.

- [ ] **Step 5: Commit**

```bash
git add oci-drawio-architect/scripts/oci_layout.py oci-drawio-architect/tests/test_oci_layout.py
git commit -m "feat(layout): --drg-style CLI flag and schema-2 docstring"
```

---

### Task 9: `parse_terraform.py` schema 2 - drgs, attachments, on-premises hub, LPG pairs, regional flag

**Files:**
- Create: `oci-drawio-architect/tests/fixtures/terraform/hub_spoke/main.tf`
- Modify: `oci-drawio-architect/scripts/parse_terraform.py:1-90` (docstring), `:94-103` (constants), `:236-281` (factories), `:352-475` (`validate_model`, `model_addresses`, `model_is_empty`), `:485-502` (`select_vcn`), `:1009-1034` (`ModelBuilder.__init__`), `:1154-1208` (`_build_gateways`, `_build_drgs`, `_build_hub`), `:1241-1264` (`_build_items`), `:1284-1314` (`_build_edges`), `:1402-1416` (`build`), `:1457-1464` (`summarise`)
- Test: `oci-drawio-architect/tests/test_parse_terraform.py`

**Interfaces:**
- Consumes: nothing new from other tasks (the parser stays importable on its own; `oci_topology` is not imported here).
- Produces: `SCHEMA_VERSION = 2`; `EDGE_KINDS = ("data", "control", "association", "attachment")`; `ATTACHMENT_TYPES`, `DRG_STYLES = ("auto", "icon", "box")`, `REGIONAL_TYPES: frozenset`, `REGIONAL_TYPE_PREFIXES`, `is_regional_type(rtype: str) -> bool`; `new_drg(name: str, address: str, label: str | None = None) -> dict`; `new_attachment(atype: str, address: str, label: str, vcn: str | None = None, target: str | None = None) -> dict` (keys `type, address, label, vcn, target`); `new_model()` adds `"drgs": []`, `"drg_style": "auto"`; `GATEWAY_ICONS` without `drg`; LPG gateways carry `peer`; services carry `regional: bool`; `ModelBuilder._build_drg_links()`; `model_addresses()` yields DRG and attachment addresses; `summarise()` mentions DRGs and attachments.

- [ ] **Step 1: Add the hub-and-spoke fixture**

Create `oci-drawio-architect/tests/fixtures/terraform/hub_spoke/main.tf`:

```hcl
variable "tenancy_ocid" {
  type = string
}

provider "oci" {
  region = "eu-frankfurt-1"
}

resource "oci_identity_compartment" "net" {
  compartment_id = var.tenancy_ocid
  name           = "network"
  description    = "Shared network"
}

resource "oci_core_vcn" "hub" {
  compartment_id = oci_identity_compartment.net.id
  display_name   = "vcn-hub"
  cidr_blocks    = ["10.10.0.0/16"]
}

resource "oci_core_vcn" "spoke" {
  compartment_id = oci_identity_compartment.net.id
  display_name   = "vcn-spoke"
  cidr_blocks    = ["10.20.0.0/16"]
}

resource "oci_core_subnet" "mgmt" {
  compartment_id             = oci_identity_compartment.net.id
  vcn_id                     = oci_core_vcn.hub.id
  display_name               = "sn-mgmt"
  cidr_block                 = "10.10.0.0/24"
  prohibit_public_ip_on_vnic = true
}

resource "oci_core_subnet" "app" {
  compartment_id             = oci_identity_compartment.net.id
  vcn_id                     = oci_core_vcn.spoke.id
  display_name               = "sn-app"
  cidr_block                 = "10.20.1.0/24"
  prohibit_public_ip_on_vnic = true
}

resource "oci_core_instance" "app" {
  compartment_id = oci_identity_compartment.net.id
  display_name   = "app-1"
  shape          = "VM.Standard.E4.Flex"
  create_vnic_details {
    subnet_id = oci_core_subnet.app.id
  }
}

resource "oci_core_service_gateway" "spoke" {
  compartment_id = oci_identity_compartment.net.id
  vcn_id         = oci_core_vcn.spoke.id
  display_name   = "sgw-spoke"
}

resource "oci_core_drg" "core" {
  compartment_id = oci_identity_compartment.net.id
  display_name   = "drg-core"
}

resource "oci_core_drg_attachment" "hub" {
  drg_id       = oci_core_drg.core.id
  display_name = "att-hub"
  network_details {
    id   = oci_core_vcn.hub.id
    type = "VCN"
  }
}

resource "oci_core_drg_attachment" "spoke" {
  drg_id       = oci_core_drg.core.id
  display_name = "att-spoke"
  network_details {
    id   = oci_core_vcn.spoke.id
    type = "VCN"
  }
}

resource "oci_core_local_peering_gateway" "hub" {
  compartment_id = oci_identity_compartment.net.id
  vcn_id         = oci_core_vcn.hub.id
  display_name   = "lpg-hub"
  peer_id        = oci_core_local_peering_gateway.spoke.id
}

resource "oci_core_local_peering_gateway" "spoke" {
  compartment_id = oci_identity_compartment.net.id
  vcn_id         = oci_core_vcn.spoke.id
  display_name   = "lpg-spoke"
}

resource "oci_core_virtual_circuit" "fc" {
  compartment_id = oci_identity_compartment.net.id
  display_name   = "fc-hq"
  type           = "PRIVATE"
  gateway_id     = oci_core_drg.core.id
}

resource "oci_core_remote_peering_connection" "dr" {
  compartment_id = oci_identity_compartment.net.id
  display_name   = "rpc-dr"
  drg_id         = oci_core_drg.core.id
}

resource "oci_logging_log_group" "app" {
  compartment_id = oci_identity_compartment.net.id
  display_name   = "lg-app"
}
```

- [ ] **Step 2: Update the existing expectations and add the new tests**

In `oci-drawio-architect/tests/test_parse_terraform.py`:

Replace `test_gateways` in `HclThreeTierTests` with:

```python
    def test_gateways(self):
        gws = {g["type"]: g for g in self.vcn["gateways"]}
        self.assertEqual(set(gws), {"igw", "nat", "sgw"})          # the DRG is no longer a VCN gateway
        self.assertEqual(gws["igw"]["label"], "igw-shop")
        self.assertEqual(gws["igw"]["icon"], "internet_gateway")
        self.assertEqual(gws["nat"]["icon"], "nat_gateway")
        self.assertEqual(gws["sgw"]["icon"], "service_gateway")
        self.assertNotIn("peer", gws["sgw"])
```

Replace `test_hub_from_drg_cpe_and_ipsec` with:

```python
    def test_hub_holds_only_the_on_premises_side(self):
        hub = self.model["hub"]
        self.assertEqual(hub["name"], "On-premises")
        self.assertIsNone(hub["link_label"])
        self.assertEqual([(i["icon"], i["label"], i["address"]) for i in hub["items"]],
                         [("cpe", "cpe-hq", "oci_core_cpe.onprem")])

    def test_drgs_and_attachments(self):
        m = self.model
        self.assertEqual(m["schema_version"], 2)
        self.assertEqual(m["drg_style"], "auto")
        self.assertEqual(m["drgs"], [{
            "name": "drg-shop", "address": "oci_core_drg.drg", "label": "DRG\ndrg-shop",
            "attachments": [
                {"type": "vcn", "address": "oci_core_drg_attachment.vcn", "label": "drg-att-shop",
                 "vcn": "vcn-shop", "target": None},
                {"type": "ipsec", "address": "oci_core_ipsec.vpn@oci_core_drg.drg", "label": "vpn-hq",
                 "vcn": None, "target": "oci_core_cpe.onprem"},
            ]}])
        self.assertIn("oci_core_drg.drg", list(pt.model_addresses(m)))
        self.assertIn("oci_core_ipsec.vpn@oci_core_drg.drg", list(pt.model_addresses(m)))
```

In `test_regional_services_attach_to_the_single_vcn` add `self.assertTrue(svc["oci_objectstorage_bucket"]["regional"])` and `self.assertTrue(svc["oci_kms_vault"]["regional"])`. Replace `test_edges` and `test_no_inferred_edges_keeps_only_reference_backed_ones` with:

```python
    def test_edges(self):
        edges = {(e["source"], e["target"]): e for e in self.model["edges"]}
        self.assertNotIn(("oci_core_cpe.onprem", "oci_core_drg.drg"), edges)   # drawn from drgs[] by the layout
        app_db = edges[("oci_core_instance.app", "oci_database_autonomous_database.shop")]
        self.assertEqual((app_db["label"], app_db["kind"], app_db["inferred"]), ("1522", "data", True))
        lb_app = edges[("oci_load_balancer_load_balancer.public", "oci_core_instance.app")]
        self.assertEqual((lb_app["label"], lb_app["inferred"]), ("443", True))
        self.assertEqual(len(edges), 2)

    def test_no_inferred_edges_keeps_only_reference_backed_ones(self):
        model = pt.parse_terraform_dir(FIXTURES / "three_tier", inferred_edges=False)
        self.assertEqual(model["edges"], [])
```

In `HelperTests.test_validate_model_reports_violations` add before `problems = ...`:

```python
        model["drgs"][0]["attachments"][0]["type"] = "tunnel"
        model["drgs"][0]["attachments"].append(pt.new_attachment("vcn", "att-x", "x", vcn="no-such-vcn"))
        model["drg_style"] = "fancy"
```

and to the assertions: `self.assertIn("attachments[0].type", joined)`, `self.assertIn("is not a VCN name", joined)`, `self.assertIn("drg_style", joined)`. In `CliTests.test_no_inferred_edges_flag` change the expectation to `self.assertEqual(json.loads(proc.stdout)["edges"], [])`. Extend `model_icons()` to also yield nothing for DRGs (no change needed) and add after `HclTfvarsMapTests`:

```python
class HclHubSpokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = pt.parse_terraform_dir(FIXTURES / "hub_spoke")
        cls.vcns = {v["name"]: v for v in cls.model["vcns"]}

    def test_valid(self):
        self.assertEqual(pt.validate_model(self.model, BUILDER_ICONS), [])
        self.assertEqual(set(self.vcns), {"vcn-hub", "vcn-spoke"})
        self.assertEqual(self.model["subject"], "hub_spoke")

    def test_drg_with_four_typed_attachments(self):
        drgs = self.model["drgs"]
        self.assertEqual(len(drgs), 1)
        d = drgs[0]
        self.assertEqual((d["name"], d["address"]), ("drg-core", "oci_core_drg.core"))
        atts = {a["address"]: a for a in d["attachments"]}
        self.assertEqual([a["type"] for a in d["attachments"]], ["vcn", "vcn", "virtual_circuit", "rpc"])
        self.assertEqual((atts["oci_core_drg_attachment.hub"]["vcn"], atts["oci_core_drg_attachment.hub"]["label"]),
                         ("vcn-hub", "att-hub"))
        self.assertEqual(atts["oci_core_drg_attachment.spoke"]["vcn"], "vcn-spoke")
        fc = atts["oci_core_virtual_circuit.fc@oci_core_drg.core"]
        self.assertEqual((fc["label"], fc["target"]), ("fc-hq", "oci_core_virtual_circuit.fc"))
        rpc = atts["oci_core_remote_peering_connection.dr@oci_core_drg.core"]
        self.assertEqual((rpc["label"], rpc["target"]), ("rpc-dr", "oci_core_remote_peering_connection.dr"))

    def test_hub_has_the_virtual_circuit_and_the_rpc_peer(self):
        hub = self.model["hub"]
        self.assertEqual(hub["name"], "On-premises")
        self.assertEqual([(i["icon"], i["label"]) for i in hub["items"]],
                         [("cpe", "fc-hq"), ("remote_peering_gateway", "rpc-dr")])
        self.assertNotIn("drg", [i["icon"] for i in hub["items"]])

    def test_lpg_pair_and_local_peering_edge(self):
        hub_gws = {g["type"]: g for g in self.vcns["vcn-hub"]["gateways"]}
        spoke_gws = {g["type"]: g for g in self.vcns["vcn-spoke"]["gateways"]}
        self.assertEqual(hub_gws["lpg"]["peer"], "oci_core_local_peering_gateway.spoke")
        self.assertIsNone(spoke_gws["lpg"]["peer"])                   # only one side declares peer_id
        self.assertEqual(set(spoke_gws), {"sgw", "lpg"})
        peering = [e for e in self.model["edges"] if e["label"] == "Local Peering"]
        self.assertEqual(peering, [pt.new_edge("oci_core_local_peering_gateway.hub",
                                               "oci_core_local_peering_gateway.spoke",
                                               "Local Peering", "attachment", False)])

    def test_regional_service_without_a_single_vcn_goes_to_model_services(self):
        self.assertEqual([(i["icon"], i["label"], i["regional"]) for i in self.model["services"]],
                         [("logging", "lg-app", True)])

    def test_select_vcn_prunes_attachments_of_dropped_vcns(self):
        model = pt.parse_terraform_dir(FIXTURES / "hub_spoke")
        self.assertTrue(pt.select_vcn(model, "vcn-spoke"))
        atts = model["drgs"][0]["attachments"]
        self.assertEqual([a["type"] for a in atts], ["vcn", "virtual_circuit", "rpc"])
        self.assertEqual(atts[0]["vcn"], "vcn-spoke")
        self.assertEqual(pt.validate_model(model, BUILDER_ICONS), [])
        self.assertEqual([e["label"] for e in model["edges"]], [])      # the peering edge lost an endpoint

    def test_summary_mentions_drgs(self):
        self.assertIn("1 DRG(s) / 4 attachment(s)", pt.summarise(self.model))
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_parse_terraform 2>&1 | tail -6`
Expected: several FAIL/ERROR - `KeyError: 'drgs'`, `AttributeError: module 'parse_terraform' has no attribute 'new_attachment'`, `{'igw','nat','sgw','drg'} != {'igw','nat','sgw'}`.

- [ ] **Step 4: Constants and factories**

In `parse_terraform.py` replace lines 94-103 (`SCHEMA_VERSION` through the closing `}` of `GATEWAY_ICONS`; keep the `# Resource type -> (icon key, default label)` banner at lines 105-107) with:

```python
SCHEMA_VERSION = 2
TIERS = ("lb", "app", "compute", "mgmt", "data", "other")
EDGE_KINDS = ("data", "control", "association", "attachment")
ATTACHMENT_TYPES = ("vcn", "ipsec", "virtual_circuit", "rpc", "loopback")
DRG_STYLES = ("auto", "icon", "box")
GATEWAY_ICONS: Dict[str, str] = {
    "igw": "internet_gateway",
    "nat": "nat_gateway",
    "sgw": "service_gateway",
    "lpg": "remote_peering_gateway",
}
# Regional Oracle services (drawn in the Oracle Services Network panel by the layout).
REGIONAL_TYPES = frozenset({
    "oci_objectstorage_bucket", "oci_kms_vault", "oci_kms_key", "oci_certificates_management_certificate",
    "oci_waf_web_app_firewall", "oci_logging_log_group", "oci_monitoring_alarm", "oci_apm_apm_domain",
    "oci_streaming_stream", "oci_queue_queue", "oci_events_rule", "oci_sch_service_connector",
    "oci_ons_notification_topic", "oci_datascience_project", "oci_analytics_analytics_instance",
    "oci_devops_project", "oci_artifacts_container_repository", "oci_dns_zone",
})
REGIONAL_TYPE_PREFIXES = ("oci_ai_", "oci_generative_ai_")


def is_regional_type(rtype: str) -> bool:
    return rtype in REGIONAL_TYPES or rtype.startswith(REGIONAL_TYPE_PREFIXES)
```

In `new_model()` add `"drgs": [],` and `"drg_style": "auto",` after `"hub": None,`. After `new_hub_item` add:

```python
def new_drg(name: str, address: str, label: Optional[str] = None) -> dict:
    return {"name": name, "address": address, "label": label or f"DRG\n{name}", "attachments": []}


def new_attachment(atype: str, address: str, label: str, vcn: Optional[str] = None,
                   target: Optional[str] = None) -> dict:
    return {"type": atype, "address": address, "label": label, "vcn": vcn, "target": target}
```

- [ ] **Step 5: Validation, addresses, selection, emptiness, summary**

In `_validate_item` add after the metadata check:

```python
    if "regional" in item:
        _expect(errors, item["regional"], bool, f"{path}.regional")
```

In `validate_model`, after the `source` block add:

```python
    if model.get("drg_style") not in DRG_STYLES:
        errors.append(f"drg_style: {model.get('drg_style')!r} not in {DRG_STYLES}")
    addresses = set(model_addresses(model))
    vcn_names = {v.get("name") for v in (model.get("vcns") or []) if isinstance(v, dict)}
    if _expect(errors, model.get("drgs"), list, "drgs"):
        for di, drg in enumerate(model["drgs"]):
            dp = f"drgs[{di}]"
            if not _expect(errors, drg, dict, dp):
                continue
            _expect(errors, drg.get("name"), str, f"{dp}.name")
            _expect(errors, drg.get("address"), str, f"{dp}.address")
            _expect(errors, drg.get("label"), str, f"{dp}.label")
            if _expect(errors, drg.get("attachments"), list, f"{dp}.attachments"):
                for ai, att in enumerate(drg["attachments"]):
                    ap_ = f"{dp}.attachments[{ai}]"
                    if not _expect(errors, att, dict, ap_):
                        continue
                    if att.get("type") not in ATTACHMENT_TYPES:
                        errors.append(f"{ap_}.type: {att.get('type')!r} not in {ATTACHMENT_TYPES}")
                    _expect(errors, att.get("address"), str, f"{ap_}.address")
                    _expect(errors, att.get("label"), str, f"{ap_}.label")
                    _expect(errors, att.get("vcn"), (str, type(None)), f"{ap_}.vcn")
                    _expect(errors, att.get("target"), (str, type(None)), f"{ap_}.target")
                    if att.get("type") == "vcn" and isinstance(att.get("vcn"), str) and att["vcn"] not in vcn_names:
                        errors.append(f"{ap_}.vcn: {att['vcn']!r} is not a VCN name in the model")
                    if isinstance(att.get("target"), str) and att["target"] not in addresses:
                        errors.append(f"{ap_}.target: {att['target']!r} is not an address in the model")
```

In the gateway loop add `if "peer" in gw: _expect(errors, gw["peer"], (str, type(None)), f"{gp}.peer")`. In the edges block delete the line `addresses = set(model_addresses(model))` (already computed above). In `model_addresses` add before the `for vcn in ...` loop:

```python
    for drg in model.get("drgs") or []:
        if drg.get("address"):
            yield drg["address"]
        for att in drg.get("attachments") or []:
            if att.get("address"):
                yield att["address"]
```

`model_is_empty`: `return not (model.get("vcns") or model.get("services") or model.get("hub") or model.get("drgs"))`. In `select_vcn`, after `model["subject"] = hits[0]["name"]` add:

```python
    keep_vcn = {hits[0]["name"], hits[0]["address"]}
    for drg in model.get("drgs") or []:
        drg["attachments"] = [a for a in drg.get("attachments") or []
                              if a.get("type") != "vcn" or a.get("vcn") in keep_vcn]
```

Replace `summarise` with:

```python
def summarise(model: dict) -> str:
    n_sub = sum(len(v["subnets"]) for v in model["vcns"])
    n_items = sum(len(s["items"]) for v in model["vcns"] for s in v["subnets"])
    n_svc = sum(len(v["services"]) for v in model["vcns"]) + len(model["services"])
    n_gw = sum(len(v["gateways"]) for v in model["vcns"])
    hub = len((model.get("hub") or {}).get("items") or [])
    drgs = model.get("drgs") or []
    n_att = sum(len(d.get("attachments") or []) for d in drgs)
    return (f"{model['subject']}: {len(model['vcns'])} VCN(s), {n_sub} subnet(s), {n_items} subnet item(s), "
            f"{n_svc} service(s), {n_gw} gateway(s), {len(drgs)} DRG(s) / {n_att} attachment(s), "
            f"{hub} hub item(s), {len(model['edges'])} edge(s)")
```

- [ ] **Step 6: ModelBuilder changes**

In `ModelBuilder.__init__` replace `self.link_labels: List[str] = []` with `self.drg_by_addr: Dict[str, dict] = {}`. Replace `_build_gateways`, `_build_drgs` and `_build_hub` with:

```python
    def _build_gateways(self) -> None:
        for r in self.resources:
            gtype = GATEWAY_TYPES.get(r.rtype)
            if gtype is None:
                continue
            vcn = self._vcn_or_single(r)
            if vcn is None:
                continue
            default = RESOURCE_ICONS[r.rtype][1]
            gw = new_gateway(gtype, r.label(default), r.address)
            if gtype == "lpg":
                peer = self.first_ref(r, ("peer_id",), "oci_core_local_peering_gateway")
                gw["peer"] = peer.address if peer is not None else None
            vcn["gateways"].append(gw)

    def _build_drgs(self) -> None:
        drgs = [r for r in self.resources if r.rtype == DRG_TYPE]
        for drg in drgs:
            entry = new_drg(drg.label("DRG"), drg.address)
            self.drg_by_addr[drg.address] = entry
            self.model["drgs"].append(entry)
        if not drgs:
            return
        for att in self.resources:
            if att.rtype != DRG_ATTACHMENT_TYPE:
                continue
            drg = self.first_ref(att, ("drg_id",), DRG_TYPE) or (drgs[0] if len(drgs) == 1 else None)
            vcn = self._vcn_or_single(att, ("vcn_id", "id", "network_details"))
            if drg is None or vcn is None:
                continue
            self.drg_by_addr[drg.address]["attachments"].append(
                new_attachment("vcn", att.address, att.label(f"VCN attachment\n{vcn['name']}"), vcn=vcn["name"]))
        for drg in drgs:
            entry = self.drg_by_addr[drg.address]
            vcn = self._single_vcn()
            if not entry["attachments"] and vcn is not None:
                entry["attachments"].append(new_attachment(
                    "vcn", f"{drg.address}@{vcn['address']}", f"VCN attachment\n{vcn['name']}", vcn=vcn["name"]))

    def _build_hub(self) -> None:
        onprem = rpc = 0
        for r in self.resources:
            if r.rtype not in HUB_TYPES:
                continue
            if r.rtype == "oci_core_ipsec" and any(x.rtype == "oci_core_cpe" for x in self.resources):
                continue  # the CPE resource already draws the on-prem endpoint
            icon, default = RESOURCE_ICONS[r.rtype]
            if r.rtype == "oci_core_remote_peering_connection":
                rpc += 1
            else:
                onprem += 1
            self.hub_items.append(new_hub_item(icon, r.label(default), r.rtype, r.address))
        if not self.hub_items:
            return
        self.model["hub"] = {"name": "On-premises" if onprem else "Remote region",
                             "items": self.hub_items, "link_label": None}

    def _build_drg_links(self) -> None:
        """IPSec / FastConnect / RPC resources referencing a DRG become typed attachments."""
        hub_addresses = {h["address"] for h in self.hub_items}
        for r in self.resources:
            if r.rtype == "oci_core_ipsec":
                cpe = self.first_ref(r, ("cpe_id",), "oci_core_cpe")
                atype, attrs, target, default = "ipsec", ("drg_id",), (cpe.address if cpe else r.address), "IPSec VPN"
            elif r.rtype == "oci_core_virtual_circuit":
                atype, attrs, target, default = "virtual_circuit", ("gateway_id",), r.address, "FastConnect"
            elif r.rtype == "oci_core_remote_peering_connection":
                atype, attrs, target, default = "rpc", ("drg_id",), r.address, "Remote peering"
            else:
                continue
            drg = self.first_ref(r, attrs, DRG_TYPE)
            addr = drg.address if drg is not None else (next(iter(self.drg_by_addr)) if len(self.drg_by_addr) == 1 else None)
            if addr is None:
                continue
            self.drg_by_addr[addr]["attachments"].append(new_attachment(
                atype, f"{r.address}@{addr}", r.label(default), target=target if target in hub_addresses else None))
```

In `_build_items`, mark services regional: replace the two `append(item)` lines for services with

```python
            if vcn is not None:
                item["regional"] = is_regional_type(r.rtype)
                vcn["services"].append(item)
                self._register(item, r, vcn["address"], None)
            else:
                item["regional"] = is_regional_type(r.rtype)
                self.model["services"].append(item)
                self._register(item, r, "", None)
```

In `_build_edges` delete the `# IPSec / FastConnect: CPE -> DRG` block (from `hub_addresses = ...` to the `elif r.rtype == "oci_core_virtual_circuit"` branch end) and insert in its place:

```python
        # Local Peering: one structural edge per LPG pair (declared from whichever side has peer_id)
        gateway_addresses = {g["address"] for v in self.model["vcns"] for g in v["gateways"] if g.get("address")}
        seen_pairs = set()
        for r in self.resources:
            if r.rtype != "oci_core_local_peering_gateway":
                continue
            peer = self.first_ref(r, ("peer_id",), "oci_core_local_peering_gateway")
            if peer is None or r.address not in gateway_addresses or peer.address not in gateway_addresses:
                continue
            pair = tuple(sorted((r.address, peer.address)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            edges.append(new_edge(pair[0], pair[1], "Local Peering", "attachment", False))
```

In `build()` call `self._build_drg_links()` right after `self._build_hub()`. Update the module docstring: schema block (`schema_version: 2`, `"drg_style": "auto"|"icon"|"box"`, the `drgs` block from the spec, `services[].regional: bool`, `gateways[].type` without `drg` and optional `"peer": str | null` on LPGs, `edges[].kind` values) and replace the paragraph "A DRG is reported once per attached VCN ..." with: "A DRG is reported once in ``drgs`` with one typed attachment per ``oci_core_drg_attachment`` (VCN), ``oci_core_ipsec`` (ipsec, target = the CPE), ``oci_core_virtual_circuit`` (virtual_circuit) and ``oci_core_remote_peering_connection`` (rpc); a DRG without attachments in a single-VCN model gets an implicit ``<drg>@<vcn>`` attachment. ``hub`` holds the on-premises side only (CPE, virtual circuit, RPC peer). LPG pairs produce one ``Local Peering`` edge of kind ``attachment``; the layout draws the DRG attachment connectors itself." Concretely, in the docstring schema block: line 15 `MODEL schema (``SCHEMA_VERSION = 2``)`; line 20 `"schema_version": 2,`; after line 26 (`"source": ...`) insert `"drg_style": "auto"|"icon"|"box",` and the `"drgs": [ {"name": str, "address": str, "label": str, "attachments": [ {"type": "vcn"|"ipsec"|"virtual_circuit"|"rpc"|"loopback", "address": str, "label": str, "vcn": str | null, "target": str | null} ]} ],` block from spec section 5; line 42 `"services": [ ITEM ],       # ... ITEM carries "regional": bool`; lines 45-46 `{"icon": "internet_gateway"|"nat_gateway"|"service_gateway"|"remote_peering_gateway", "type": "igw"|"nat"|"sgw"|"lpg", "label": str, "address": str | null, "peer": str | null   # lpg only}`; line 52 `"kind": "data"|"control"|"association"|"attachment"`.

- [ ] **Step 7: Run the parser tests and the suite**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_parse_terraform -v 2>&1 | tail -20 && cd .. && python3 -m unittest discover -s oci-drawio-architect/tests 2>&1 | tail -3`
Expected: parser tests PASS. The suite shows FAILURES only in `tests/test_query_tenancy.py` (hub/gateway expectations) - fixed in Task 10. If `HclHubSpokeTests.test_lpg_pair_and_local_peering_edge` finds no edge, check that `_build_edges` runs after `_build_gateways` (it does: `build()` order) and that `peer_id` produced a reference (the fixture uses `oci_core_local_peering_gateway.spoke.id`).

- [ ] **Step 8: Commit**

```bash
git add oci-drawio-architect/scripts/parse_terraform.py oci-drawio-architect/tests/test_parse_terraform.py oci-drawio-architect/tests/fixtures/terraform/hub_spoke/main.tf
git commit -m "feat(parser): schema 2 with drgs/attachments, on-premises hub, LPG pairs and regional flag"
```

---

### Task 10: `query_tenancy.py` alignment

**Files:**
- Modify: `oci-drawio-architect/scripts/query_tenancy.py:1-47` (docstring), `:165-170` (`_REF_FIELDS`)
- Test: `oci-drawio-architect/tests/test_query_tenancy.py:85-139, 186-189`

**Interfaces:**
- Consumes: `parse_terraform.ModelBuilder` (Task 9) through `entities_to_resources` / `build_model` (unchanged signatures).
- Produces: `_REF_FIELDS` includes `("peer_id", "peer_id")`; live-mode models have `drgs[]`, `hub` = on-premises items only.

- [ ] **Step 1: Update the expectations (they fail now)**

In `oci-drawio-architect/tests/test_query_tenancy.py` replace `test_gateways_including_ocid_derived_type`, `test_hub` and the DRG lines of `test_edges` / `test_no_inferred_edges` / `test_classify_response_and_load_bundle_single_response`:

```python
    def test_gateways_including_ocid_derived_type(self):
        gws = {g["type"]: g for g in self.vcn["gateways"]}
        self.assertEqual(set(gws), {"igw", "nat", "sgw"})
        self.assertEqual(gws["nat"]["label"], "nat-shop")                        # entity without 'type' key
        self.assertTrue(gws["nat"]["address"].startswith("ocid1.natgateway."))

    def test_drg_attachments_from_topology(self):
        drgs = self.model["drgs"]
        self.assertEqual([(d["name"], d["address"][:9]) for d in drgs], [("drg-shop", "ocid1.drg")])
        atts = drgs[0]["attachments"]
        self.assertEqual([a["type"] for a in atts], ["vcn", "ipsec"])
        self.assertTrue(atts[0]["address"].startswith("ocid1.drgattachment."))
        self.assertEqual((atts[0]["label"], atts[0]["vcn"]), ("drg-att-shop", "vcn-shop"))
        cpe = self.model["hub"]["items"][0]["address"]
        self.assertEqual((atts[1]["label"], atts[1]["target"]), ("vpn-hq", cpe))
        self.assertTrue(atts[1]["address"].startswith("ocid1.ipsecconnection."))

    def test_hub(self):
        hub = self.model["hub"]
        self.assertEqual(hub["name"], "On-premises")
        self.assertIsNone(hub["link_label"])
        self.assertEqual([(i["icon"], i["label"]) for i in hub["items"]], [("cpe", "cpe-hq")])
```

In `test_edges` delete the three lines `cpe = ...`, `drg = ...`, `self.assertEqual(edges[(cpe, drg)]["label"], "IPSec VPN")` and change `self.assertEqual(len(edges), 5)` to `4`. In `test_no_inferred_edges` change `3` to `2`. In `test_classify_response_and_load_bundle_single_response` replace the three hub assertions with:

```python
            # CPE/IPSec live in networking-topology; the VCN topology alone yields a DRG with its VCN attachment
            self.assertIsNone(model["hub"])
            self.assertEqual([d["name"] for d in model["drgs"]], ["drg-shop"])
            self.assertEqual([a["type"] for a in model["drgs"][0]["attachments"]], ["vcn"])
```

Add to `HelperTests`:

```python
    def test_peer_id_is_a_reference_field(self):
        norm = qt.normalise_entity({"type": "LocalPeeringGateway", "id": "ocid1.localpeeringgateway.oc1.eu-frankfurt-1.a",
                                    "peer-id": "ocid1.localpeeringgateway.oc1.eu-frankfurt-1.b"})
        self.assertEqual(norm["refs"]["peer_id"], ["ocid1.localpeeringgateway.oc1.eu-frankfurt-1.b"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_query_tenancy 2>&1 | tail -4`
Expected: `test_peer_id_is_a_reference_field` FAILS with `KeyError: 'peer_id'`; the other updated tests already pass against the Task 9 parser (the fixture flows through `ModelBuilder`).

- [ ] **Step 3: Implement**

In `query_tenancy.py` add `("peer_id", "peer_id"),` to `_REF_FIELDS`. In the docstring replace "Additional edges come from ``ROUTES_TO`` relationships (subnet -> gateway)." with "Additional edges come from ``ROUTES_TO`` relationships (subnet -> gateway); DRGs and their attachments are reported in ``drgs[]`` (schema 2), the hub holds the on-premises side only."

- [ ] **Step 4: Run the suite**

Run: `python3 -m unittest discover -s oci-drawio-architect/tests 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add oci-drawio-architect/scripts/query_tenancy.py oci-drawio-architect/tests/test_query_tenancy.py
git commit -m "feat(tenancy): schema-2 model output and LPG peer references"
```

---

### Task 11: Reference layout, demo diagram, `OCI_Architecture.drawio` and screenshots

**Files:**
- Modify: `oci-drawio-architect/examples/generate_reference_layout.py:1-101`, `oci-drawio-architect/examples/generate_demo_diagram.py:1-164`, `oci-drawio-architect/examples/make_screenshots.py:8, 95-101`, `oci-drawio-architect/scripts/drawio_builder.py` (new method `append_pages` after `use_page`, line ~1343), `OCI_Architecture.drawio` (regenerated), `screenshots/diagram-overview.png`, `screenshots/diagram-detail.png`, `Screens/1.png`, `Screens/2.png` (regenerated - draw.io desktop is installed at /Users/sergio.farfan/Applications/draw.io.app and `find_drawio_binary()` resolves it)
- Test: `oci-drawio-architect/tests/test_builder.py` (class `TestHelpers`, new `test_append_pages`), `oci-drawio-architect/tests/test_oci_layout.py` (new class `ExamplesTests`)

**Interfaces:**
- Consumes: `oci_layout.build_diagram(model, page_name=, legend=, drg_style=)` (Task 7), `write_diagram` (Task 8).
- Produces: `DrawioBuilder.append_pages(other: DrawioBuilder) -> None` (appends every page of another builder; ids only need to be unique per page); `examples.generate_reference_layout.MODEL` in schema 2; `examples.generate_demo_diagram.DEMO_MODEL` (schema 2, two VCNs, hybrid) and `build(out_path: Path, do_render: bool = False) -> None` producing a three-page file ("Architecture" icon style, "DRG as a box", "Security").

- [ ] **Step 1: Write the failing tests**

Append to `TestHelpers` in `oci-drawio-architect/tests/test_builder.py`:

```python
    def test_append_pages(self):
        a = DrawioBuilder(page_name="One")
        a.add_group("A", 0, 0, 200, 100, key="region")
        b = DrawioBuilder(page_name="Two")
        b.add_group("B", 0, 0, 200, 100, key="region")      # same key on another page is fine
        b.add_page("Three")
        b.add_icon("VM", "vm", 0, 0, key="vm")
        a.append_pages(b)
        self.assertEqual([p["name"] for p in a._pages], ["One", "Two", "Three"])
        self.assertEqual([d.get("id") for d in a.mxfile.findall("diagram")], ["page1", "page2", "page3"])
        self.assertEqual(a._page_idx, 2)
        path, _ = self.roundtrip(a)
        errors, _, pages, containers = db.validate_file(path)
        self.assertEqual((errors, pages, containers), ([], 3, 2))
        with self.assertRaises(ValueError):
            a.append_pages(a)
```

Append to `oci-drawio-architect/tests/test_oci_layout.py`:

```python
class ExamplesTests(unittest.TestCase):
    def test_reference_model_is_schema_2_and_passes_the_gate(self):
        import check_overlaps
        sys.path.insert(0, str(TESTS_DIR.parent / "examples"))
        from generate_reference_layout import MODEL
        self.assertEqual([i["address"] for i in MODEL["hub"]["items"]], ["cpe"])
        self.assertEqual([a["type"] for a in MODEL["drgs"][0]["attachments"]], ["vcn"])
        self.assertIn({"source": "cpe", "target": "drg", "label": "IPSec VPN", "kind": "data"}, MODEL["edges"])
        d = quiet(ol.build_diagram, MODEL)
        self.assertEqual(d.layout_info["warnings"], [])
        self.assertEqual(d.layout_info["topology"]["kind"], "hybrid")
        self.assertEqual(d._cells["drg"]["parent"], "region")
        self.assertEqual(d._cells["sgw"]["parent"], "region")
        self.assertEqual(d._cells["logging"]["parent"], "osn")
        self.assertNotIn("services-Spoke-VCN-D", d._cells)
        with tempfile.TemporaryDirectory() as tmp:
            out = quiet(ol.write_diagram, MODEL, Path(tmp) / "ref.drawio")
            self.assertEqual(quiet(check_overlaps.main, [str(out)]), 0)

    def test_demo_builds_three_pages_and_passes_the_gate(self):
        import check_overlaps
        sys.path.insert(0, str(TESTS_DIR.parent / "examples"))
        import generate_demo_diagram as demo
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "demo.drawio"
            quiet(demo.build, out)
            text = out.read_text(encoding="utf-8")
            self.assertEqual(text.count("<diagram "), 3)
            self.assertIn('id="drgbox-drg"', text)                  # page 2: box style
            self.assertIn("Attachment (structural)", text)          # legend row
            self.assertIn("Oracle Services Network", text)
            self.assertEqual(quiet(check_overlaps.main, [str(out)]), 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_builder.TestHelpers.test_append_pages tests.test_oci_layout.ExamplesTests 2>&1 | tail -6`
Expected: `AttributeError: 'DrawioBuilder' object has no attribute 'append_pages'`; `AssertionError: ['cpe', 'drg'] != ['cpe']` for the reference MODEL (the DRG is still a hub item); `AttributeError: module 'generate_demo_diagram' has no attribute 'DEMO_MODEL'`-style failure or a two-page count for the demo.

- [ ] **Step 3: Implement `append_pages`**

Insert after `use_page` in `drawio_builder.py`:

```python
    def append_pages(self, other: "DrawioBuilder") -> None:
        """Append every page of ``other`` to this document (cell ids are unique per page).

        ``other``'s pending auto routes are resolved first; the pages keep their
        geometry and become part of validate() / write(). The last appended
        page becomes current.
        """
        if other is self:
            raise ValueError("append_pages: cannot append a builder to itself")
        other.route_edges()
        for p in other._pages:
            p["diagram"].set("id", f"page{len(self._pages) + 1}")
            self.mxfile.append(p["diagram"])
            self._pages.append(p)
        self._page_idx = len(self._pages) - 1
```

Add `append_pages(other)` to the module docstring's helper list and to the `CLAUDE.md` API table in Task 12.

- [ ] **Step 4: Migrate the reference model**

In `oci-drawio-architect/examples/generate_reference_layout.py` replace the docstring paragraph with "...a generated script only has to fill in the model: subnets in traffic order, icons per subnet, regional services (drawn in the Oracle Services Network panel), gateways on the VCN border, the DRG with its attachments, the on-premises panel and the edges." and replace the `"hub": {...}` block and the two gateway entries / edges as follows:

```python
    "hub": {
        "name": "Hub Network\nHub-Network\n(Shared-Services)",
        "items": [
            {"icon": "firewall", "label": "Corp VPN\n(10.0.0.0/8)", "address": "cpe"},
        ],
    },
    "drgs": [{
        "name": "drg", "address": "drg", "label": "Dynamic Routing\nGateway (DRG)",
        "attachments": [
            {"type": "vcn", "vcn": "Spoke-VCN-D", "address": "drg-att-spoke", "label": "VCN attachment\nSpoke-VCN-D"},
        ],
    }],
```

```python
        "gateways": [
            {"icon": "service_gateway", "type": "sgw", "label": "Service\nGateway", "address": "sgw"},
            {"icon": "nat_gateway", "type": "nat", "label": "NAT Gateway\n(backup - unused)", "address": "nat"},
        ],
```

```python
    "edges": [
        {"source": "cpe", "target": "drg", "label": "IPSec VPN", "kind": "data"},
        {"source": "drg", "target": "lb", "label": "", "kind": "data"},
        ... (the remaining ten edges unchanged) ...
    ],
```

- [ ] **Step 5: Rewrite the demo**

Replace `oci-drawio-architect/examples/generate_demo_diagram.py` with:

```python
#!/usr/bin/env python3
"""Demo / smoke test for oci-drawio-architect v1.3.0.

Page 1 "Architecture": the layout recipe (oci_layout.build_diagram) on a two-VCN
hybrid model - on-premises panel with a CPE, a region-level DRG with two VCN
attachments and one IPSec attachment (drg_style "icon"), IGW / NAT on the hub
VCN's bottom border, the Service Gateway on the spoke VCN's right border, an
Oracle Services Network panel with the regional services, the four connector
kinds (data, control, association, attachment) and the legend.
Page 2 "DRG as a box": the same model with drg_style "box".
Page 3 "Security": an NSG rule table (custom DrawioBuilder API).

validate() must return no errors before the file is written.

Usage:
    python3 generate_demo_diagram.py [output_path] [--render]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from drawio_builder import PAD, __version__, build_cell_registry, render  # noqa: E402
from oci_layout import build_diagram  # noqa: E402

DEMO_MODEL = {
    "subject": "demo-app", "region": "us-ashburn-1", "region_label": "Ashburn",
    "compartment": "demo", "tenancy_name": "demo-tenancy",
    "hub": {"name": "On-premises",
            "items": [{"icon": "cpe", "label": "Customer Premises\nEquipment", "address": "cpe"}]},
    "drgs": [{"name": "drg-demo", "address": "drg", "label": "DRG\ndrg-demo", "attachments": [
        {"type": "vcn", "vcn": "vcn-hub", "address": "att-hub", "label": "VCN attachment\nvcn-hub"},
        {"type": "vcn", "vcn": "vcn-spoke", "address": "att-spoke", "label": "VCN attachment\nvcn-spoke"},
        {"type": "ipsec", "target": "cpe", "address": "att-vpn", "label": "IPSec attachment"}]}],
    "vcns": [
        {"name": "vcn-hub", "cidr": "10.0.0.0/16", "subnets": [
            {"name": "sn-public", "cidr": "10.0.1.0/24", "tier": "lb", "public": True, "items": [
                {"icon": "load_balancer", "label": "Public LB", "address": "lb"},
                {"icon": "waf", "label": "WAF", "address": "waf"}]},
            {"name": "sn-mgmt", "cidr": "10.0.2.0/24", "tier": "mgmt", "items": [
                {"icon": "bastion", "label": "Bastion", "address": "bastion"}]}],
         "gateways": [{"icon": "internet_gateway", "type": "igw", "label": "Internet\nGateway", "address": "igw"},
                      {"icon": "nat_gateway", "type": "nat", "label": "NAT\nGateway", "address": "nat"}]},
        {"name": "vcn-spoke", "cidr": "10.1.0.0/16", "subnets": [
            {"name": "sn-app", "cidr": "10.1.1.0/24", "tier": "app", "items": [
                {"icon": "vm", "label": "App VM\n10.1.1.5", "address": "app",
                 "metadata": {"ocid": "ocid1.instance.oc1..demo"}, "tooltip": "primary app node"}]},
            {"name": "sn-data", "cidr": "10.1.2.0/24", "tier": "data", "items": [
                {"icon": "autonomous_db", "label": "Autonomous\nDatabase", "address": "adb"}]}],
         "services": [{"icon": "logging", "label": "Logging", "address": "logs"},
                      {"icon": "vault", "label": "Vault", "address": "vault"},
                      {"icon": "buckets", "label": "Object Storage", "address": "buckets"}],
         "gateways": [{"icon": "service_gateway", "type": "sgw", "label": "Service\nGateway", "address": "sgw"}]}],
    "edges": [
        {"source": "igw", "target": "lb", "label": "443", "kind": "data"},
        {"source": "lb", "target": "app", "label": "8080", "kind": "data"},
        {"source": "app", "target": "adb", "label": "1522", "kind": "data"},
        {"source": "bastion", "target": "app", "label": "22", "kind": "control"},
        {"source": "app", "target": "vault", "label": "secrets", "kind": "association"},
        {"source": "lb", "target": "waf", "label": "WAF policy", "kind": "association"},
    ],
}


def build(out_path: Path, do_render: bool = False) -> None:
    d = build_diagram(DEMO_MODEL, page_name="Architecture", legend=True)
    box = build_diagram(DEMO_MODEL, page_name="DRG as a box", drg_style="box", legend=True)
    d.append_pages(box)

    d.add_page("Security", 800, 400)
    d.add_title("NSG rules - vcn-spoke", region_label="Ashburn", region="us-ashburn-1", key="title3")
    d.add_table([
        ["Direction", "Source / Destination", "Protocol", "Ports", "Description"],
        ["Ingress", "10.0.1.0/24", "TCP", "8080", "Public LB to the app tier"],
        ["Ingress", "10.0.2.0/24", "TCP", "22", "Bastion to the app tier"],
        ["Egress", "all-iad-services", "TCP", "443", "OCI services via the Service Gateway"],
    ], PAD, 75, col_widths=[80, 170, 80, 60, 260], title="nsg-app (3 rules)", key="nsg-table")
    d.fit_page()

    problems = d.validate()
    errors = [p for p in problems if not p.split("] ")[-1].startswith("WARNING")]
    for p in problems:
        print(p)
    if errors:
        raise SystemExit(1)

    d.write(out_path)
    n_groups = n_icons = n_edges = 0
    for p in d._pages:
        reg = build_cell_registry(p["root"])
        for e in reg.values():
            style = e.get("style", "")
            if e.get("edge") == "1" and e.get("source"):
                n_edges += 1
            elif "container=1" in style:
                n_groups += 1
            elif "shape=image" in style:
                n_icons += 1
    topo = d.layout_info["topology"]["kind"]
    print(f"{out_path} | v{__version__} | {len(d._pages)} pages | topology {topo} | "
          f"{n_groups} containers, {n_icons} icons, {n_edges} edges")
    if do_render:
        png = render(out_path, fmt="png")
        print(f"Rendered {png}" if png else "draw.io desktop not found; render skipped")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0]) if args else Path("demo_architecture.drawio")
    build(out, do_render="--render" in sys.argv)
```

- [ ] **Step 6: Adjust the screenshot crop**

In `oci-drawio-architect/examples/make_screenshots.py` replace lines 95-101 (`sx, sy, sw, sh = ...` through `_crop(full150, ...)`; the `gw_bottom = max(...)` statement spans two lines; lines 88-94 - `content_bbox()`, the `px()` helper and the two `_export` calls - stay) with:

```python
        sx, sy, sw, sh = d.abs_bbox("subnet-sn-priv-data")
        nx, ny, nw, nh = d._abs_footprint("nat")            # bottom-border gateway (caption hangs below the VCN)
        gx, gy, gw, gh = d._abs_footprint("sgw")            # right-border gateway
        x0, y0 = px(sx - 12, sy - 34, 1.5)
        x1, y1 = px(max(sx + sw + 35, gx + gw + 12), ny + nh + 12, 1.5)
        detail = tmp / "detail.png"
        _crop(full150, (x0, y0, x1, y1), detail)
```

and update the docstring line to `screenshots/diagram-detail.png     data subnet + border gateways (1.5x)`.

- [ ] **Step 7: Run the tests, regenerate the reference file and the screenshots**

Run: `python3 -m unittest discover -s oci-drawio-architect/tests 2>&1 | tail -3 && python3 oci-drawio-architect/examples/generate_reference_layout.py OCI_Architecture.drawio && python3 oci-drawio-architect/scripts/check_overlaps.py OCI_Architecture.drawio && python3 oci-drawio-architect/examples/generate_demo_diagram.py /tmp/demo13.drawio && python3 oci-drawio-architect/scripts/check_overlaps.py /tmp/demo13.drawio && python3 oci-drawio-architect/examples/make_screenshots.py; echo "screenshots exit $?"`
Expected: suite `OK`; both gates `OK` with no `WARNING: legacy model` lines; `make_screenshots.py` exits 0 and prints the four rewritten PNG paths with their pixel sizes (`screenshots/diagram-overview.png`, `screenshots/diagram-detail.png`, `Screens/1.png`, `Screens/2.png`); `git status --short` must list all four as modified. A `draw.io desktop not found` exit 3 is a failure of this step (the binary is in ~/Applications; set `DRAWIO_BIN=/Users/sergio.farfan/Applications/draw.io.app/Contents/MacOS/draw.io` if discovery changes).

- [ ] **Step 8: Commit**

```bash
git add oci-drawio-architect/scripts/drawio_builder.py oci-drawio-architect/examples/generate_reference_layout.py oci-drawio-architect/examples/generate_demo_diagram.py oci-drawio-architect/examples/make_screenshots.py OCI_Architecture.drawio oci-drawio-architect/tests/test_builder.py oci-drawio-architect/tests/test_oci_layout.py
git add screenshots/diagram-overview.png screenshots/diagram-detail.png Screens/1.png Screens/2.png
git commit -m "feat(examples): schema-2 reference model, three-page demo with both DRG styles, regenerated reference diagram"
```

---

### Task 12: Documentation and version bump to 1.3.0

**Files:**
- Modify: `oci-drawio-architect/.claude-plugin/plugin.json:3`; `oci-drawio-architect/scripts/drawio_builder.py:1,82`; `oci-drawio-architect/tests/test_builder.py:1,1376`; `oci-drawio-architect/skills/oci-drawio-architect/SKILL.md` (lines 6, 8, 14, 19-21, 25-58, 60-76, 89-93, 153-180, 198, 220); `oci-drawio-architect/commands/drawio-architect.md` (lines 3, 56-70, 72-105, 111-117, 127-136); `oci-drawio-architect/skills/oci-drawio-architect/references/oracle-styles.md` (lines 1, 3, 33, 88-179, 231-305); `oci-drawio-architect/skills/oci-drawio-architect/references/gotchas.md` (lines 1, 4, 86-95, 159-177, end of file); `oci-drawio-architect/CHANGELOG.md` (top); `oci-drawio-architect/README.md` (lines 5-22, 39, 106-113, 129, 141, 175-177); `README.md` (lines 5, 14, 50-71, 75-89, 108, 211); `CLAUDE.md` (lines 7, 42, 100-160)
- Test: `oci-drawio-architect/tests/test_builder.py::TestModuleCompat::test_version_and_exports`; `oci-drawio-architect/scripts/build_icon_catalog.py --check` (unchanged catalog)

**Interfaces:**
- Consumes: every public name introduced in Tasks 1-11 (names below are copied from those tasks).
- Produces: version string `1.3.0` in every place that carried `1.2.0` except `CHANGELOG.md` history and `dev.to/` (article assets are updated after the release, outside this plan).

- [ ] **Step 1: Make the version test fail**

In `oci-drawio-architect/tests/test_builder.py` line 1376 change `self.assertEqual(db.__version__, "1.2.0")` to `self.assertEqual(db.__version__, "1.3.0")` and line 1 to `"""Unit tests for scripts/drawio_builder.py (v1.3.0).`.

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_builder.TestModuleCompat.test_version_and_exports 2>&1 | tail -3`
Expected: FAIL `'1.2.0' != '1.3.0'`.

- [ ] **Step 2: Bump the version strings**

Apply, from the repository root:

```bash
sed -i '' 's/"version": "1.2.0"/"version": "1.3.0"/' oci-drawio-architect/.claude-plugin/plugin.json
sed -i '' '1s/(v1.2.0)/(v1.3.0)/; s/^__version__ = "1.2.0"/__version__ = "1.3.0"/' oci-drawio-architect/scripts/drawio_builder.py
sed -i '' 's/plugin v1.2.0/plugin v1.3.0/; s/DrawioBuilder v1.2.0/DrawioBuilder v1.3.0/; s/(v1.2.0, standard library only)/(v1.3.0, standard library only)/' oci-drawio-architect/skills/oci-drawio-architect/SKILL.md
sed -i '' 's/deterministic v1.2.0 layout recipe/deterministic v1.3.0 layout recipe/' oci-drawio-architect/commands/drawio-architect.md
sed -i '' '1s/(v1.2.0)/(v1.3.0)/; 3s/1.2.0/1.3.0/' oci-drawio-architect/skills/oci-drawio-architect/references/oracle-styles.md
sed -i '' '1s/(v1.2.0)/(v1.3.0)/; 4s/1.2.0/1.3.0/' oci-drawio-architect/skills/oci-drawio-architect/references/gotchas.md
sed -i '' 's/plugin (v1.2.0)/plugin (v1.3.0)/; s/Core builder (v1.2.0)/Core builder (v1.3.0)/; s/oci-drawio-architect-v1.2.0.tar.gz/oci-drawio-architect-v1.3.0.tar.gz/g' CLAUDE.md
sed -i '' 's/version-1.2.0-blue/version-1.3.0-blue/; s#releases/tag/v1.2.0#releases/tag/v1.3.0#g; s#releases/download/v1.2.0/oci-drawio-architect-v1.2.0.tar.gz#releases/download/v1.3.0/oci-drawio-architect-v1.3.0.tar.gz#g; s/\*\*Version:\*\* 1.2.0/**Version:** 1.3.0/' README.md
sed -i '' 's/oci-drawio-architect-v1.2.0.tar.gz/oci-drawio-architect-v1.3.0.tar.gz/g; s/(version 1.2.0)/(version 1.3.0)/; s/DrawioBuilder (v1.2.0)/DrawioBuilder (v1.3.0)/' oci-drawio-architect/README.md
grep -rn "1\.2\.0" --include="*.md" --include="*.json" --include="*.py" --include="*.sh" . | grep -v "^./dev.to" | grep -v CHANGELOG.md | grep -v "/.git/" | grep -v "docs/superpowers"
```

Expected: the grep prints exactly these residual hits and nothing else - `tests/fixtures/terraform/plan.json:58` (the CIDR `10.1.2.0/24`, not a version), `README.md:75` and `oci-drawio-architect/README.md:5` (`## What's new in 1.2.0`, renamed to `## What was new in 1.2.0` in Step 5 and kept), `references/oracle-styles.md:160` (`Changed in v1.2.0`) and `references/gotchas.md:66`, `:190`, `:229` (history notes about what changed in 1.2.0 - leave them). Re-run the grep after Step 5; the same seven lines must remain and no other.

- [ ] **Step 3: CHANGELOG**

Insert after the intro paragraph of `oci-drawio-architect/CHANGELOG.md` (before `## [1.2.0] - 2026-09-12`):

```markdown
## [1.3.0] - 2026-09-17

Topology-aware placement. The layout recipe now follows how Oracle's Architecture Diagram Toolkit (v24.2, slides 19-22 and 27-32), Oracle's reference architectures and the team's diagram guidelines draw connectivity infrastructure: the DRG is a region-level element with its attachments beside it, gateways sit on the VCN border, regional services live in an Oracle Services Network panel, and connectors carry four semantics. Design: `docs/superpowers/specs/2026-09-17-topology-aware-placement-design.md`.

### Added
- **Model schema 2** (`parse_terraform.py`, `query_tenancy.py`, `oci_layout.py`): `drgs[]` with typed `attachments[]` (`vcn`, `ipsec`, `virtual_circuit`, `rpc`, `loopback`) carrying their own display names; `drg_style` (`auto` | `icon` | `box`); `services[].regional`; `gateways[].peer` for Local Peering Gateways; edge kinds `association` and `attachment`. The hub panel holds the on-premises side only (CPE, IPSec, FastConnect virtual circuit, RPC peer). Schema-1 models are migrated at build time with `WARNING: legacy model: ...` lines.
- `scripts/oci_topology.py`: `classify_topology()` (`single_vcn`, `multi_vcn`, `vcn_with_drg`, `hub_spoke`, `hybrid`), `migrate_legacy_model()`, `is_regional()`, `choose_drg_style()`, `REGIONAL_ICON_KEYS`.
- **Layout**: DRG column between the on-premises panel and the VCN columns, vertically centred on the VCN stack, one rounded attachment box per attachment (VCN attachments facing the VCNs, IPSec / FastConnect / RPC attachments facing the on-premises panel) connected with arrowhead-less `attachment` connectors labelled `Site-to-Site VPN` / `FastConnect` / `Remote Peering`; `drg_style="box"` wraps a DRG and its boxes in a dashed `DRG: <name>` group (`auto` picks it above 4 attachments). IGW and NAT straddle the VCN's bottom border, the Service Gateway its right border, LPGs the border facing their peer VCN. Regional services (Logging, Monitoring, Notifications, Events, IAM, Vault/KMS, Object Storage, OCIR, AI services, Data Safe, Streaming, Queue, APM, DevOps and others) are drawn in one region-level `Oracle Services Network` panel right of the VCN columns with an SGW -> panel connector; `"regional": false` keeps an item in the VCN. CLI `--drg-style {auto,icon,box}`; `build_diagram(..., drg_style=)`; `builder.layout_info` exposes the topology, warnings and the chosen style per DRG.
- **Builder**: `add_edge(kind="data"|"control"|"association"|"attachment")` and `EDGE_KIND_STYLES` (data = solid open arrow, control = dashed open arrow, association = dotted no arrowhead, attachment = thin solid no arrowhead); `add_legend()` rows for the four kinds plus region, VCN, subnet and OSN; `drg` container type; `add_box()` for labelled rounded markers; `add_icon(label_fill=)` for captions crossing a dashed border; `append_pages()`; `ociGroup=<type>` token on every container and `ociRole=drg` on DRG icons so `check_overlaps.py` recognises them in hand-written files.
- **Validator**: foreign-containment rule (`ERROR: '<label>' ... lies inside '<VCN or subnet>' ... but is not one of its children`), `ERROR: DRG '<label>' is inside VCN '<vcn>'` for a DRG box inside any VCN, and a straddle tolerance so border-centred gateways pass the containment check (`STRADDLE_TOL`, `FOREIGN_TOL`).
- Tests: `tests/test_oci_topology.py`, `tests/test_oci_layout.py`, the `tests/fixtures/terraform/hub_spoke` fixture (two VCNs, one DRG with four attachments - two VCN attachments, a FastConnect virtual circuit and a remote peering connection - an LPG pair and a regional log group).

### Changed
- `examples/generate_reference_layout.py`: the DRG moved from `hub.items` to `drgs[]` with one VCN attachment; the CPE stays in the hub with an explicit `cpe -> drg` edge labelled `IPSec VPN`; the eight services are regional and render in the OSN panel. `OCI_Architecture.drawio`, `screenshots/` and `Screens/` regenerated (`examples/make_screenshots.py`; the detail crop now follows the NAT gateway on the bottom border and the Service Gateway on the right border).
- `examples/generate_demo_diagram.py`: three pages built from one schema-2 model - icon style, box style and the NSG rule table; exercises the OSN panel, border gateways and the four connector kinds.
- `parse_terraform.py` no longer emits CPE -> DRG edges (the layout draws the attachment connectors) and emits one `Local Peering` edge per LPG pair; `GATEWAY_ICONS` has no `drg` entry; `summarise()` reports DRGs and attachments.
- `oracle_services_network` panels created by the recipe use a left-aligned label; `oracle-styles.md` records that the Rose look is the toolkit's "Optional" grouping spec while slide 19 specifies Neutral 3 2pt dashed for the OSN.
- Documentation (README, plugin README, SKILL.md, command, references, repo CLAUDE.md) rewritten for schema 2 and the new placement rules.

### Roadmap (not in this release)
- Diagram purpose selection, resource filtering (tag / compartment / region / VCN / subnet / type / environment), detail levels, label modes, draw.io view layers, a separate global-services bucket, all-resources versus participating mode, multi-region canvases, an Internet location box outside the region, draw.io MCP integration.
```

- [ ] **Step 4: SKILL.md**

Edit `oci-drawio-architect/skills/oci-drawio-architect/SKILL.md`:

1. Section 1, item 3: `3. On-premises panel (`onprem`): left of the DRG column, 180 px wide, vertically centred on the VCN stack, label `On-premises` (or the hub network name), one icon per row (pitch 200): CPE, FastConnect virtual circuit, RPC peer. Never the DRG.`
2. Section 1, insert after item 3: `4. DRG column (`drgs[]`): region-level DRG icon between the on-premises panel and the VCN columns, centred on the VCN stack; one rounded attachment box (100x44, Ivy border) per attachment beside it - VCN attachments on the side facing the VCNs, IPSec / FastConnect / RPC attachments on the side facing the on-premises panel - each linked to its target by an arrowhead-less `attachment` connector (`Site-to-Site VPN`, `FastConnect`, `Remote Peering`). `drg_style` `icon` (default) or `box` (dashed `DRG: <name>` group); `auto` picks `box` above 4 attachments.` Renumber the following items.
3. Former item 8 (services): `OCI Services panel (`services`): inside the VCN, right of row 1, only for VCN-resident services without a subnet. Regional services (Logging, Logging Analytics, Monitoring / Alarms, Notifications, Events, Connector Hub, IAM / Identity, Vault / KMS, Certificates, Object Storage, OCIR, AI services, Data Safe, Data Science, Analytics, Streaming, Queue, APM, DevOps, DNS zones, WAF policies; full list `oci_topology.REGIONAL_ICON_KEYS`) go to ONE region-level `Oracle Services Network` panel right of the VCN columns, height matched to the tallest VCN, fed by an `attachment` connector from the Service Gateway. `"regional": false` on an item keeps it in the VCN panel.`
4. Former item 9 (gateways): `Gateways straddle the VCN border (glyph centre on the line, caption with an opaque region-fill background, parent = region): IGW and NAT on the bottom border (pitch 180), the Service Gateway on the right border facing the OSN panel, LPGs on the border facing their peer VCN (`peer` = peer LPG address or VCN name; unknown peer -> bottom) linked by a `Local Peering` attachment connector.`
5. Former item 10 (edges): `Edges: `data` solid Bark open arrow (label = protocol / port); `control` dashed Bark open arrow (management / administrative); `association` dotted, no arrowhead (dependency, configuration relationship); `attachment` thin solid, no arrowhead (structural: DRG attachments, LPG pairs, SGW -> OSN); `analytics` solid Sienna and `datalake` dashed purple remain. Routed automatically through the gutters.`
6. Section 2: replace the `MODEL` block with the schema-2 example from `oci_layout.py`'s docstring (Task 8) and replace rule 3 with `Edge `kind`: `data`, `control`/`management`, `association`, `attachment`, `analytics`, `datalake`; or pass `dashed`/`color` directly (an explicit `dashed` keeps the profile look).`; add rule 6: `DRGs: never inside `hub.items` or `vcn.gateways`; `drgs[].attachments[].type` in `vcn | ipsec | virtual_circuit | rpc | loopback`, `vcn` = VCN name, `target` = hub item address. Schema-1 models are migrated with a `WARNING: legacy model:` line - move the DRG to `drgs` to silence it.`; add rule 7: `Edge endpoints also accept `drg:<name>`, a DRG address, an attachment address and `osn`.`
7. Section 3: signature `build_diagram(model, style_profile="default", legend=False, logo=None, page_name=None, title=True, max_row_w=MAX_ROW_W, drg_style=None) -> DrawioBuilder`; CLI adds `[--drg-style auto|icon|box]`; order of operations: `migrate legacy model -> classify topology -> title -> region -> for each VCN: subnet rows -> VCN-resident services panel -> data subnets -> fit_to_children(vcn) -> border gateways (region children) -> optional region-level OCI Services panel -> Oracle Services Network panel -> on-premises panel -> DRG column -> fit_to_children(region) -> SGW -> OSN connectors -> attachment connectors -> model edges -> optional legend -> fit_page()`; add the new constants to the table: `DRG_GAP 45`, `ATT_W x ATT_H 100 x 44`, `ATT_GAP / ATT_PITCH 15 / 56`, `DRG_CLUSTER_GAP 40`, `OSN_GAP 45`, `GW_STRADDLE / GW_SIDE_DX 40 / 38`, `SIDE_GW_Y0 / LEFT_GW_Y0 / SIDE_GW_PITCH 50 / 50 / 160`, `VCN_BOTTOM_PAD_GW / VCN_SIDE_PAD / SIDE_INSET 60 / 60 / 40`, `VCN_COLUMN_GAP_GW 110`.
8. Section 4 table rows: `oci_core_drg` -> `drg` -> `drgs[]`; `oci_core_drg_attachment` -> (box) -> `drgs[].attachments` (`type: vcn`); `oci_core_local_peering_gateway` -> `rpg` -> `gateways` (`type: lpg`, `peer`); `oci_core_remote_peering_connection` -> `rpg` -> `hub.items` + `drgs[].attachments` (`type: rpc`); `oci_core_cpe` / `oci_core_ipsec` / `oci_core_virtual_circuit` -> `cpe` / (attachment `ipsec`) / `cpe` -> `hub.items` / `drgs[].attachments` / `hub.items` + attachment `virtual_circuit`; `oci_network_firewall_network_firewall` -> `firewall` -> subnet (hub VCN); regional rows (`oci_objectstorage_bucket`, `oci_kms_*`, logging, monitoring, notifications, apm, streaming, queue, dns zones, devops, OCIR, connector hub, events, resource manager, data science, generative AI, analytics, cloud guard, data safe, vulnerability scanning) -> `services` (`regional: true`, OSN panel).
9. Section 6 worked example: replace the hub-and-spoke script so the DRG is a region child and the attachments are boxes:

```python
import sys
sys.path.insert(0, "/ABSOLUTE/PATH/TO/oci-drawio-architect/scripts")
from drawio_builder import DrawioBuilder, PAD, ROW1_Y, GAP, ICON_W

d = DrawioBuilder(page_name="Hub-and-Spoke")
d.add_title("Hub-and-Spoke - Architecture", region_label="Frankfurt", region="eu-frankfurt-1", compartment="network")
region = d.add_group("eu-frankfurt-1", PAD, 75, 900, 400, group_type="region", key="region")
(drg,), _ = d.place_icons(region, [{"label": "DRG\nhub-drg", "icon": "drg", "key": "drg"}], cols=1, x0=PAD, y0=150)
att = d.add_box("VCN attachment\nspoke-a", PAD + ICON_W + 15, 190, 100, 44, parent=region, key="att-spoke-a")
spoke = d.add_group("VCN: spoke-a (10.1.0.0/16)", PAD + ICON_W + 15 + 100 + 45, 40, 300, 200,
                    parent=region, group_type="vcn", key="vcn-spoke-a")
sn = d.add_group("sn-app (10.1.1.0/24)", PAD, ROW1_Y, 200, 150, parent=spoke, group_type="subnet", key="sn-app")
(vm,), _ = d.place_icons(sn, [{"label": "App VM\n10.1.1.5", "icon": "vm", "key": "app-vm",
                               "metadata": {"ocid": "ocid1.instance.oc1..x"}, "tooltip": "primary app node"}], cols=1)
for cid in (sn, spoke, region):
    d.fit_to_children(cid)
d.add_edge(att, spoke, "", kind="attachment")        # structural: box -> VCN border, no arrowhead
d.add_edge(drg, vm, "443", kind="data")              # traffic: solid, open arrow
d.fit_page()
problems = d.validate()
print("\n".join(problems))
if any(not p.split("] ")[-1].startswith("WARNING") for p in problems):
    raise SystemExit("layout errors; diagram not written")
d.write("hub_spoke.drawio")
```

   and in the API table add `add_box(label, x, y, w, h, parent="1", key=None, style_extra="", metadata=None, tooltip=None) -> str`, `append_pages(other)`, `add_edge(..., kind=None)` with the kind list, `add_icon(..., label_fill=None)`, `add_legend` entry styles `data | control | association | attachment | solid | dashed | accent | purple | dotted | thin`, `group_type` list including `drg`.
10. Section 7 item 4: replace `hub centred on the VCN; gateways in the bottom row;` with `on-premises panel and DRG column centred on the VCN stack; DRG outside every VCN with its attachment boxes beside it; gateways centred on the VCN border; regional services in the Oracle Services Network panel right of the VCNs;`. Section 8 table: add `ERROR: DRG '...' is inside VCN '...'` -> `move the DRG to `drgs[]` (recipe) or parent it to the region outside every VCN box (custom)` and `ERROR: '...' lies inside '...' but is not one of its children` -> `the icon's box overlaps a VCN / subnet it does not belong to; move it or make it a child of that container`.
11. Section 9: add `Topology helpers: ${CLAUDE_PLUGIN_ROOT}/scripts/oci_topology.py`.

- [ ] **Step 5: Command, references, READMEs, CLAUDE.md**

`oci-drawio-architect/commands/drawio-architect.md`:
- Step 2.4.5: `Regional services (Logging, Monitoring / Alarms, Notifications, Events, Connector Hub, IAM / Identity, Vault / KMS, Certificates, Object Storage, OCIR, AI, Data Safe, Streaming, Queue, APM, DevOps, DNS zones) go to `vcn.services` or `model.services`; the recipe draws them in the region-level Oracle Services Network panel. VCN-resident services without a subnet (mount targets, file systems, private DNS resolvers) also go to `vcn.services` with `"regional": false` when the table would misclassify them.`
- Step 2.4.6: `Gateways (IGW, NAT, SGW, LPG) go to `vcn.gateways` with `type` (`igw`, `nat`, `sgw`, `lpg`), two-line captions and, for LPGs, `peer`. Never put a DRG or a DRG attachment in `gateways`.`
- Step 2.4.7: `DRGs go to `model.drgs` with one attachment per attached network (`type` `vcn` + `vcn` name, `ipsec` / `virtual_circuit` / `rpc` + `target` hub item address). CPE, IPSec endpoint, FastConnect virtual circuit, RPC peer and on-premises firewalls go to `model.hub` (`name = "On-premises"`). Add an explicit `cpe -> drg` edge only when the model has no `ipsec` attachment. Choose `drg_style`: `icon` (default, architecture views) or `box` when the reader wants the attachments as a network detail (`auto` = box above 4 attachments).`
- Step 3 template: add `"drg_style": "auto",`, a `"drgs": [...]` block with one VCN attachment and a `"hub"` with a CPE, `"type"` on the gateways and one `"kind": "association"` edge; add `drg_style="box"` to the optional kwargs in Step 3.2.
- Step 5.4 checklist: replace `hub centred on the VCN; gateways in the bottom row;` with `on-premises panel and DRG centred on the VCN stack; DRG outside every VCN, attachment boxes beside it; gateways centred on the VCN border; Oracle Services Network panel right of the VCNs;`.
- Diagram types: Hub-and-spoke row -> `model.hub` (CPE) + `model.drgs` (one DRG, one attachment per spoke) + spoke VCN columns; regional services in the OSN panel | one while <= 3 VCNs and <= 40 icons`; Multi-VCN overview row -> `several VCNs, LPG pairs via `gateways[].peer`, edges between `vcn:<name>` endpoints`.
- Failure table: add the two validator messages from SKILL.md item 10 and `WARNING: legacy model: ...` -> `the model still uses schema 1; move the DRG into `drgs[]``.

`references/oracle-styles.md`: section 4 - add `drg` to the `GROUP_TYPES` list, a `### drg` entry with the style string (`whiteSpace=wrap;html=1;fontFamily={FONT_STACK};verticalAlign=top;rounded=1;arcSize=10;strokeWidth=1;dashed=1;fillColor=none;strokeColor=#312D2A;fontSize=11;fontStyle=1;fontColor=#312D2A;align=left;spacingLeft=5;ociGroup=drg;container=1;collapsible=0;expand=0;recursiveResize=0;` - "the official logical Other Group look with a left-aligned label; project convention for `DRG: <name>` boxes"), a note that every style now carries `ociGroup=<type>;` before `container=1` (read by `validate_file()`), and under `oracle_services_network` replace the provenance sentence with `Rose 1px dashed border, Air fill (PPTX slide 19 "Optional" grouping spec; slide 19's Oracle Services Network spec is Neutral 3 2pt dashed with a Bark label and the v24.2 .drawio uses Sienna 2px dashed). The recipe labels it "Oracle Services Network" left-aligned (`label_position="left"`).`; line 33 of section 1 updated the same way. Section 5: `add_icon(label_fill=)` and the `ociRole=drg;` token. Section 6: a table of `EDGE_KIND_STYLES` (kind, dashed, dashPattern, endArrow, strokeWidth) and the legend defaults; a `### add_box()` entry with `BOX_STYLE` (`rounded=1;arcSize=12;whiteSpace=wrap;html=1;strokeWidth=1;strokeColor=#759C6C;fillColor=#FFFFFF;fontFamily={FONT_STACK};fontSize=11;fontColor=#312D2A;align=center;verticalAlign=middle;`, provenance: A-Team hub-and-spoke figure, Ivy = OCI logical component border). Section 7: legend rows.

`references/gotchas.md`: item 5 example -> `(DRG at region level, LB in a subnet)`; item 11 -> add the two new messages and the tolerances (`STRADDLE_TOL` 4 px for an icon whose glyph centre sits on its parent's border, `FOREIGN_TOL` 18.75 px for leaves inside a VCN / subnet they do not belong to); append `## 19. DRG placement: region level only, attachments beside it` (why: a box asserts location; the recipe enforces it; how the validator detects it via `ociRole=drg` or a caption matching `DRG`) and `## 20. *migration* - schema 2: `drgs[]`, `regional`, `peer`; legacy models are migrated with warnings`.

`README.md` (root): "How it works" step 3 -> `normalizes the input into the diagram model (VCNs, subnets, services with their regional / VCN-resident class, gateways, DRGs with attachments, on-premises side, edges)`; diagram-types table -> Single-VCN: `Region > optional on-premises panel + DRG column + one VCN column: subnet rows in traffic order, data tier, gateways on the VCN border, Oracle Services Network panel`; Hub-and-Spoke: `On-premises panel (CPE), region-level DRG with one attachment box per spoke, spoke VCN columns, OSN panel; attachment connectors without arrowheads`; Multi-VCN: `Several VCN columns, LPG pairs on facing borders, OSN panel, cross-VCN edges`; replace `## What's new in 1.2.0` with a `## What's new in 1.3.0` section (six bullets: DRG at region level with attachment boxes and two styles; gateways on the VCN border; Oracle Services Network panel; four connector kinds and legend; validator rules; schema 2 with migration) and keep the 1.2.0 section below it under `## What was new in 1.2.0`; update the screenshot captions (`*Single-VCN topology with the on-premises panel, region-level DRG and its VCN attachment, subnets, gateways on the VCN border and the Oracle Services Network panel*`, `*Detail view: data subnet, NAT gateway on the bottom border and Service Gateway on the right border*`).

`oci-drawio-architect/README.md`: mirror the root README bullets (`## What's new in 1.3.0`), rename the existing section to `## What was new in 1.2.0` and keep it below the new one, workflow step 3 and the diagram-types table; add `oci_topology.py` to the structure listing and `tests/test_oci_topology.py`, `tests/test_oci_layout.py`, `tests/fixtures/terraform/hub_spoke/` under tests; CLI line for `oci_layout.py` gains `[--drg-style auto|icon|box]`.

`CLAUDE.md` (repo root): version strings; "Repository Contents" tree adds `oci_topology.py` and the two test files; the `oci_layout.py` paragraph rewritten to the Task 8 docstring summary (columns, DRG column, border gateways, OSN panel, edge kinds, migration); the builder bullets gain `EDGE_KIND_STYLES` / `add_edge(kind=)`, `drg` group type, `add_box`, `append_pages`, `label_fill`, the `ociGroup` / `ociRole` tokens and the validator rules; the API table gains `add_box`, `append_pages`; the command section step 3 mentions `drgs[]`; the layout constants line gains the Task 5-7 constants.

- [ ] **Step 6: Verify**

Run: `: "${FORBIDDEN:?export FORBIDDEN=<name1|name2|...> first}" && python3 -m unittest discover -s oci-drawio-architect/tests 2>&1 | tail -3 && python3 oci-drawio-architect/scripts/build_icon_catalog.py --check && python3 oci-drawio-architect/scripts/check_overlaps.py --version && grep -rniE "$FORBIDDEN" docs/superpowers oci-drawio-architect/examples oci-drawio-architect/tests/fixtures/terraform/hub_spoke oci-drawio-architect/CHANGELOG.md README.md oci-drawio-architect/README.md oci-drawio-architect/skills oci-drawio-architect/commands; echo "public-repo grep exit $? (1 = clean)"`
where `FORBIDDEN` is exported beforehand as a pipe-separated, case-insensitive list of the company, project, tenancy, compartment and colleague names from the private review inputs (the list itself must never be written into the repository).
Expected: suite `OK`; catalog check `OK`; `drawio_builder 1.3.0`; the grep exits 1 (no forbidden names).

- [ ] **Step 7: Commit**

```bash
git add -A oci-drawio-architect/.claude-plugin oci-drawio-architect/scripts/drawio_builder.py oci-drawio-architect/tests/test_builder.py oci-drawio-architect/skills oci-drawio-architect/commands oci-drawio-architect/CHANGELOG.md oci-drawio-architect/README.md README.md CLAUDE.md
git commit -m "docs: v1.3.0 - topology-aware placement documentation and version bump"
```

---

### Task 13: End-to-end gate

**Files:**
- Test: `oci-drawio-architect/tests/test_oci_layout.py` (new class `EndToEndTests`)
- Verify only (no edits): every example output, `smoke_test.sh`, `pack.sh`

**Interfaces:**
- Consumes: `parse_terraform.parse_terraform_dir`, `query_tenancy.load_bundle` / `build_model`, `oci_layout.write_diagram`, `check_overlaps.main`, `oci_topology.classify_topology`.
- Produces: the release gate for 1.3.0.

- [ ] **Step 1: Write the end-to-end tests**

Append to `oci-drawio-architect/tests/test_oci_layout.py`:

```python
class EndToEndTests(unittest.TestCase):
    FIXTURES = TESTS_DIR / "fixtures"

    def _gate(self, model, name):
        import check_overlaps
        with tempfile.TemporaryDirectory() as tmp:
            out = quiet(ol.write_diagram, model, Path(tmp) / name)
            self.assertEqual(quiet(check_overlaps.main, [str(out)]), 0, name)
            return out.read_text(encoding="utf-8")

    def test_three_tier_terraform_model(self):
        import oci_topology as ot
        import parse_terraform as pt
        model = pt.parse_terraform_dir(self.FIXTURES / "terraform" / "three_tier")
        self.assertEqual(ot.classify_topology(model)["kind"], "hybrid")
        text = self._gate(model, "three_tier.drawio")
        self.assertIn('id="oci_core_drg.drg"', text)                 # DRG at region level (dots survive _slug)
        self.assertIn('id="oci_core_ipsec.vpn-oci_core_drg.drg"', text)   # IPSec attachment box (@ -> -)
        d = quiet(ol.build_diagram, model)
        self.assertEqual(d._cells["oci_core_drg.drg"]["parent"], "region")
        self.assertEqual(d._cells["oci_core_cpe.onprem"]["parent"], "hub")
        self.assertEqual(d.layout_info["warnings"], [])

    def test_hub_spoke_terraform_model(self):
        import oci_topology as ot
        import parse_terraform as pt
        model = pt.parse_terraform_dir(self.FIXTURES / "terraform" / "hub_spoke")
        self.assertEqual(ot.classify_topology(model)["kind"], "hybrid")
        text = self._gate(model, "hub_spoke.drawio")
        self.assertIn("Local Peering", text)
        self.assertIn("FastConnect", text)
        self.assertIn("Remote Peering", text)
        self.assertIn("Oracle Services Network", text)
        model["drg_style"] = "box"
        self._gate(model, "hub_spoke_box.drawio")

    def test_tenancy_bundle_model(self):
        import query_tenancy as qt
        bundle = qt.load_bundle(self.FIXTURES / "tenancy" / "topology_bundle.json")
        model = qt.build_model(bundle, "ocid1.compartment.oc1..aaaaaaaashopprod000001")
        self._gate(model, "tenancy.drawio")
```

- [ ] **Step 2: Run the end-to-end tests**

Run: `cd oci-drawio-architect && python3 -m unittest tests.test_oci_layout.EndToEndTests -v 2>&1 | tail -8`
Expected: 3 PASS. If the hub_spoke gate reports `WARNING: edge ... is estimated to cross`, that is acceptable (warnings do not fail the gate); an `ERROR`/`OVERLAP` line is a layout bug in Tasks 5-7 - typical causes: the OSN panel `osn_x` colliding with the SGW caption (check `VCN_COLUMN_GAP_GW` is applied for a VCN with right gateways) or the left LPG of `vcn-spoke` colliding with the right LPG/SGW of `vcn-hub` (check `LEFT_GW_Y0 == SIDE_GW_Y0` and `VCN_COLUMN_GAP_GW >= LABEL_W + 1`).

- [ ] **Step 3: Run every gate**

```bash
python3 -m unittest discover -s oci-drawio-architect/tests 2>&1 | tail -3
python3 oci-drawio-architect/examples/generate_reference_layout.py /tmp/v13-ref.drawio && python3 oci-drawio-architect/scripts/check_overlaps.py /tmp/v13-ref.drawio OCI_Architecture.drawio
python3 oci-drawio-architect/examples/generate_demo_diagram.py /tmp/v13-demo.drawio && python3 oci-drawio-architect/scripts/check_overlaps.py /tmp/v13-demo.drawio
python3 oci-drawio-architect/scripts/parse_terraform.py oci-drawio-architect/tests/fixtures/terraform/hub_spoke --out /tmp/v13-hs.json && python3 oci-drawio-architect/scripts/oci_layout.py /tmp/v13-hs.json -o /tmp/v13-hs.drawio --legend --drg-style box && python3 oci-drawio-architect/scripts/check_overlaps.py /tmp/v13-hs.drawio
SMOKE_SKIP_PNG=1 oci-drawio-architect/scripts/smoke_test.sh
oci-drawio-architect/pack.sh /tmp/v13-pack && tar -tzf /tmp/v13-pack/oci-drawio-architect-v1.3.0.tar.gz | grep -E "oci_topology.py|hub_spoke/main.tf|test_oci_layout.py" && rm -rf /tmp/v13-pack
git status --short
```

Expected: `OK` (244 original tests plus the new ones, all passing); every `check_overlaps.py` line prints `OK: no container overlaps or layout errors`; `Smoke test passed.`; `pack.sh` prints `Created: /tmp/v13-pack/oci-drawio-architect-v1.3.0.tar.gz` and the three grep hits; `git status --short` is empty after the commit below.

- [ ] **Step 4: Commit**

```bash
git add oci-drawio-architect/tests/test_oci_layout.py
git commit -m "test: end-to-end gate for Terraform, tenancy, reference and demo models"
```

- [ ] **Step 5: Hand-off**

Do not merge or tag. Report the branch, the test count, and confirm the four regenerated PNGs (`screenshots/diagram-overview.png`, `screenshots/diagram-detail.png`, `Screens/1.png`, `Screens/2.png`) are in the Task 11 commit (`git show --stat HEAD~2 -- screenshots Screens`) so the release step (`pack.sh`, GitHub release asset, `install.sh`, dev.to update) can follow the repository `CLAUDE.md`.

---

## Self-review

**Spec coverage (design decisions -> tasks)**

| Decision | Tasks |
|----------|-------|
| D1 DRG is region-level; hard validator error | 3 (rule 7 DRG message), 7 (`_layout_drg_column` parent = region / `drg` group), 13 (E2E asserts parent) |
| D2 attachments adjacent, boxes, attachment connectors, targets and labels | 2 (`add_box`), 4 (`attachment_label`, `attachment_link_label`), 7 |
| D3 `drg_style` icon / box, model key, CLI flag, auto threshold | 2 (`drg` group type), 4 (`choose_drg_style`), 7, 8 (`--drg-style`) |
| D4 `classify_topology` and per-class layout | 4, 7 (column position by hub / drgs presence, centring) |
| D5 gateways straddle the border; LPG pairs; straddle tolerance | 3 (rule 3 tolerance), 5, 9 (`peer`, `Local Peering` edge) |
| D6 OSN panel, SGW facing it, classification table, `regional` override | 4 (`REGIONAL_ICON_KEYS`, `is_regional`), 6, 9 (`REGIONAL_TYPES`) |
| D7 connector semantics and legend | 1, 7 (`EDGE_KINDS` mapping), 11 (demo uses all four), 12 (docs) |
| D8 foreign containment + DRG-in-VCN error | 3 |
| D9 legacy migration with warnings; schema 2; hub on-prem only | 4 (`migrate_legacy_model`), 7 (wired), 9, 10 |
| D10 AD/FD unchanged | no task (stated in spec section 4) |
| D11 version bump, CHANGELOG, docs, reference model, `OCI_Architecture.drawio`, screenshots, demo | 11, 12 |
| D12 stdlib only, deterministic ids, gate on every example, suite green | every task ends with the suite; 13 runs all gates |
| Roadmap items | spec section 13, CHANGELOG roadmap (12) - no implementation task, by design |

**Placeholder scan:** searched this plan for "TBD", "TODO", "implement later", "add appropriate", "handle edge cases", "similar to Task", "write tests for the above" - none present. Every code step shows the code; every doc step names the file, the location and the replacement text. One deliberate exception: Task 12 step 5 describes documentation prose by content rather than reproducing whole README sections verbatim, because those sections are rewritten from the spec sections 1, 6 and 7 that the implementer has in hand.

**Type consistency check:**
- `add_edge(..., kind=None)` (Task 1) is used with `kind="attachment"` in Tasks 2, 6, 7, 11, 12 and `kind=spec["kind"]` in Task 7.
- `EDGE_KIND_STYLES` keys `data/control/association/attachment` (Task 1) match `oci_layout.EDGE_KINDS[...]["kind"]` values (Task 7) and `add_legend` kind names (Task 1).
- `add_box(label, x, y, w, h, parent, key, style_extra, metadata, tooltip)` (Task 2) is called with `(text, bx, by, ATT_W, ATT_H, parent=..., key=..., metadata=..., tooltip=...)` in Task 7 and positionally in Task 3 tests and the Task 12 worked example.
- `add_icon(label_fill=)` (Task 2) is passed through `place_icons(**icon_kwargs)` in Task 5 (`_place_edge_gateway`) and asserted in Tasks 3 and 5.
- `_gateway_side(gw, vcn_index, order) -> str`, `_gateway_sides(vcn, vcn_index, order) -> dict`, `_vcn_order(vcns) -> dict`, `_place_edge_gateway(d, region_id, box, side, slot, gw, reg) -> str` (Task 5) are called with those signatures in Task 7's `build_diagram`.
- `_layout_vcn(..., inset_left, right_pad, bottom_pad, min_h)` (Task 5) matches the call in Task 7.
- `_split_services(items) -> (regional, local)` and `_layout_osn(d, region_id, items, x, y, min_h, reg) -> (pid, w, h)` (Task 6) match Task 7.
- `migrate_legacy_model(model) -> (model, warnings)`, `classify_topology(model) -> dict`, `choose_drg_style(requested, n) -> str`, `attachment_type/label/link_label(att) -> str`, `first_line(text) -> str`, `is_regional(item) -> bool` (Task 4) match their uses in Tasks 6, 7, 13.
- `_layout_drg_column(d, region_id, drgs, col_x, stack_y, stack_h, requested, reg, style_out) -> list` and `_resolve_attachment_target(reg, pe)` (Task 7) are consistent between definition and call; pending dict keys `source, vcn, target, label, key` are the same in both.
- Cell ids: `region`, `hub`, `osn`, `vcn:<name>` -> `vcn-<name>`, `subnet:<name>` -> `subnet-<name>`, `services:<vcn>` -> `services-<vcn>`, `drgbox:<addr>` -> `drgbox-<addr>`, attachment edge `<addr>-edge`, SGW edge `<addr>-osn`, implicit attachment `<drg>@<vcn>` -> `<drg>-<vcn>` (slug replaces `:` and `@` with `-`; `.` is kept, so Terraform addresses appear unchanged, e.g. `oci_core_drg.drg`) - tests in Tasks 5, 6, 7, 8, 11, 13 use the slugged forms.
- `parse_terraform.new_attachment(atype, address, label, vcn=None, target=None)` returns `{type, address, label, vcn, target}`; Task 9 tests compare full dicts with `"vcn": None` / `"target": None` present, and `oci_topology.attachment_type` tolerates the `vcn` key being `None`.
- `builder.layout_info = {"topology", "warnings", "drg_style"}` (Task 7) is read in Tasks 7, 11, 13 with those keys.
- Version string `1.3.0` appears in `plugin.json`, `drawio_builder.__version__`, the test assertion and the docs (Task 12); `check_overlaps.py --version` reads the builder value.
