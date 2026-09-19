#!/usr/bin/env python3
"""View resolution and caption rendering for the OCI layout recipe (standard library only).

* ``resolve_view(model, **overrides)`` - the whole view of one diagram, every key
  concrete, resolved most-specific-first: CLI flag / ``build_diagram`` kwarg ->
  explicit model key -> ``detail`` preset -> ``purpose`` preset -> hard default
  (spec 6.1).
* ``render_caption(item, view)`` - an icon caption as a rendered field list over the
  vocabulary of 6.3, never containing an OCID in any mode.
* ``draws(view, gate)`` - whether a gated element is emitted at all: a gate that is
  off still emits when its view layer is enabled, because the layer then carries the
  visibility (V4).

This module imports nothing from the plugin, exactly as ``oci_topology`` does not
import the builder: the parser and the live-tenancy reader can resolve and validate
a view without registering 159 SVGs.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Enums (the team's diagram guidelines, sections 1, 7 and 8)
# ---------------------------------------------------------------------------
PURPOSES_ORDER = ("network", "dataflow", "security", "inventory", "dependency", "ha")
# The six names VERBATIM from the guidelines, for the command's Step 1 question.
PURPOSE_TITLES: Dict[str, str] = {
    "network": "Network topology",
    "dataflow": "Application / data flow",
    "security": "Security architecture",
    "inventory": "Resource / inventory view",
    "dependency": "Dependency / relationship view",
    "ha": "Deployment / high-availability architecture",
}
DETAIL_ORDER = ("executive", "application", "network", "engineering")
LABEL_MODE_ORDER = ("minimal", "network", "detailed")
# 6.3: the configurable field list. The OCID is deliberately absent - it is in the
# tooltip and the metadata and is never rendered in a caption, in any mode.
LABEL_FIELDS = ("display_name", "resource_type", "shape", "private_ip", "public_ip", "cidr",
                "fqdn", "port_protocol", "compartment", "ad_fd", "lifecycle", "tags")
NEVER_RENDERED = ("ocid",)
LABEL_MODES: Dict[str, Tuple[str, ...]] = {
    "minimal": ("display_name",),
    "network": ("display_name", "private_ip", "port_protocol"),
    "detailed": ("display_name", "private_ip", "ad_fd", "compartment"),
}
# Mirrors drawio_builder.LABEL_LINE_BUDGET (pinned by tests/test_layout_label_modes.py):
# this module may not import the builder.
LABEL_LINE_BUDGET = {"minimal": 2, "network": 3, "detailed": 5}
# 6.2 / V2: only these six of the guidelines' twelve layers are CELL layers. The
# others are the base layer, a label field or a build-time selector.
VIEW_LAYERS = ("routes", "security", "iam", "dataflow", "management", "associations")
LAYER_TITLES: Dict[str, str] = {"routes": "Routes", "security": "Security", "iam": "IAM",
                                "dataflow": "Data flows", "management": "Management paths",
                                "associations": "Associations"}
BASE_LAYER_NAME = "Network"
LAYER_MODES = ("off", "auto")
# 6.2: "Resource IPs" and "Ports and protocols" are label FIELDS, not layers.
# --layers ips is accepted and rewritten, with a note the caller prints.
LAYER_FIELD_ALIASES: Dict[str, Tuple[str, ...]] = {
    "ips": ("private_ip", "public_ip"), "resource_ips": ("private_ip", "public_ip"),
    "ports": ("port_protocol",), "ports_and_protocols": ("port_protocol",),
}
MODES = ("all", "participating")
GLOBAL_SERVICES_MODES = ("osn", "bucket")
# Mirrors oci_topology.SUBNET_LABEL_MODES, which gains "name" in the same release.
SUBNET_LABEL_MODES = ("twoline", "inline", "name")
# 6.8: the guidelines' six methods plus the plugin's own "heuristic".
DISCOVERY_KINDS = ("association", "config", "reachability", "tag", "observed", "user", "heuristic")
# 6.8 / compatibility: edges[].inferred is True for exactly the plausibility
# guesses, which is what it meant in 1.4.0 - the load-balancer -> app-tier and
# compute -> database heuristics. Every other provenance is a fact stated by a
# source of truth, so it is inferred=False and every 1.4.0 consumer of the
# boolean keeps its answers.
INFERRED_DISCOVERY = ("heuristic",)
# --no-inferred-edges has always meant "drop the plausibility guesses"; a
# route-derived edge is a fact, so it stays in the alias set (6.8). The alias
# therefore drops exactly the three kinds no 1.5.0 producer emits by default
# plus "heuristic": tag, observed and heuristic.
NO_INFERRED_DISCOVERY = ("association", "config", "reachability", "user")
# 6.3: lifecycle renders only when it is NOT one of these.
HEALTHY_LIFECYCLE_STATES = frozenset({"AVAILABLE", "ACTIVE", "RUNNING", "SUCCEEDED", "UP", "OK"})
FQDN_MAX_CHARS = 20

# ---------------------------------------------------------------------------
# Content gates (6.4) and their layers (V4)
# ---------------------------------------------------------------------------
GATE_KEYS = ("subnet_cidr", "badges_routes", "badges_security", "drg_route_table",
             "drg_attachments", "gateways", "edge_labels", "osn")
# A gate whose content lives on a view layer is not dropped when the layer is
# enabled: the cells are emitted and the layer carries the visibility (V4).
# drg_route_table is deliberately NOT here: the DRG route-table strip consumes
# layout space in the DRG cluster, so emitting it because the "routes" layer is
# on would move pixels and break V1 (enabling layers moves nothing).
GATE_LAYERS: Dict[str, str] = {"badges_routes": "routes", "badges_security": "security"}

DETAIL_LEVELS: Dict[str, dict] = {
    "executive": {
        "label_mode": "minimal", "subnet_cidr": False, "badges_routes": False,
        "badges_security": False, "drg_route_table": False, "drg_attachments": False,
        "gateways": True, "edge_labels": False, "osn": True, "legend": True,
        "auto_layers": ("dataflow",),
    },
    "application": {
        "label_mode": "minimal", "label_fields": ("display_name", "port_protocol"),
        "subnet_cidr": False, "badges_routes": False, "badges_security": False,
        "drg_route_table": False, "drg_attachments": True, "gateways": True,
        "edge_labels": True, "osn": True, "legend": True,
        "auto_layers": ("dataflow", "management"),
    },
    "network": {
        # drg_route_table stays True here: it is the 1.4.0 behaviour and the
        # default level is contractually today's output (spec 11).
        "label_mode": "network", "subnet_cidr": True, "badges_routes": True,
        "badges_security": True, "drg_route_table": True, "drg_attachments": True,
        "gateways": True, "edge_labels": True, "osn": True, "legend": None,
        "auto_layers": VIEW_LAYERS,
    },
    "engineering": {
        "label_mode": "detailed", "subnet_cidr": True, "badges_routes": True,
        "badges_security": True, "drg_route_table": True, "drg_attachments": True,
        "gateways": True, "edge_labels": True, "osn": True, "legend": True,
        "auto_layers": VIEW_LAYERS,
    },
}

# 6.9: a purpose is a named composition. It sets the layer SET and the hidden set,
# never the layer MODE - layers stay opt-in (V3 / A5), and with them off a hidden
# layer's content is dropped instead (V4).
PURPOSES: Dict[str, dict] = {
    "network": {
        "detail": "network", "label_mode": "network",
        "layers": ("routes", "security", "dataflow", "management"), "hidden_layers": (),
        "mode": "all",
    },
    "dataflow": {
        "detail": "application", "label_fields": ("display_name", "port_protocol"),
        "layers": ("routes", "security", "dataflow", "management"),
        "hidden_layers": ("routes", "security"), "mode": "participating",
        "edge_labels": True,
    },
    "security": {
        "detail": "network", "label_fields": ("display_name", "private_ip"),
        "layers": ("routes", "security", "iam", "dataflow", "management"),
        "hidden_layers": ("dataflow",), "mode": "all",
        "global_services": "bucket", "legend": True,
    },
    "inventory": {
        "detail": "executive", "label_fields": ("display_name", "resource_type", "compartment"),
        "layers": ("iam",), "hidden_layers": (), "mode": "all",
        "show_edges": False, "show_compartments": True, "global_services": "bucket",
    },
    "dependency": {
        "detail": "application", "label_fields": ("display_name",),
        "layers": ("routes", "security", "dataflow", "management", "associations"),
        "hidden_layers": ("routes", "security"), "mode": "participating",
        "annotate_discovery": True,
    },
    "ha": {
        "detail": "network", "label_fields": ("display_name", "ad_fd"),
        "layers": ("routes", "security"), "hidden_layers": ("security",), "mode": "all",
    },
}

DEFAULTS: Dict[str, object] = {
    "detail": "network",
    "label_mode": "network",          # D1: the one default this release flips
    "label_tag_keys": (),
    "layers": "off",                  # A5 / V3
    "hidden_layers": (),
    "mode": "all",                    # A1: query_tenancy passes "participating" itself
    "discovery": None,                # None = every discovery kind
    "annotate_discovery": False,
    "global_services": "osn",         # A2 / V7
    "show_edges": True,
    "show_compartments": False,
    "subnet_label": "twoline",
    "legend": None,                   # None = the caller's choice
}

VIEW_KEYS = ("purpose", "detail", "label_mode", "label_fields", "label_tag_keys",
             "layers", "hidden_layers", "filter", "mode", "discovery", "annotate_discovery",
             "global_services", "show_edges", "show_compartments", "subnet_label", "legend")


def choice(value, allowed: tuple, default, what: str):
    """A normalised enum value; absent / empty -> ``default``, unknown -> ValueError.

    The same reader ``oci_topology._choice`` applies to the v1.4.0 view keys.
    """
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{what} must be one of {allowed}, not {value!r}")
    text = value.strip().lower()
    if not text:
        return default
    if text not in allowed:
        raise ValueError(f"{what} must be one of {allowed}, not {value!r}")
    return text


def _as_tuple(value, what: str) -> Tuple[str, ...]:
    """A comma-separated string or a sequence of strings -> a tuple of trimmed names."""
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
    elif isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(f"{what}: {item!r} is not a string")
            parts.extend(p.strip() for p in item.split(","))
    else:
        raise ValueError(f"{what} must be a string or a list of strings, not {value!r}")
    return tuple(p for p in parts if p)


def _dedupe(names) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(names))


def _as_exprs(value, what: str) -> Tuple[str, ...]:
    """A filter expression list; unlike ``_as_tuple`` it never splits on ','.

    6.5 makes the comma the OR operator INSIDE one expression
    (``vcn=vcn-app,vcn-ops``), so splitting the list on commas would destroy
    the grammar before the expression parser ever saw it.
    """
    if value is None:
        return ()
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, (list, tuple)):
        raise ValueError(f"{what} must be a string or a list of strings, not {value!r}")
    out = []
    for item in items:
        if not isinstance(item, str):
            raise ValueError(f"{what}: {item!r} is not a string")
        if item.strip():
            out.append(item.strip())
    return tuple(out)


def _filter_spec(value) -> dict:
    """Normalise ``{"include", "exclude", "keep_empty"}`` or a flat list with ``!`` prefixes."""
    include: List[str] = []
    exclude: List[str] = []
    keep_empty = False
    if value is None or value == "" or value == [] or value == {}:
        pass
    elif isinstance(value, dict):
        include = list(_as_exprs(value.get("include"), "filter.include"))
        exclude = list(_as_exprs(value.get("exclude"), "filter.exclude"))
        keep_empty = bool(value.get("keep_empty"))
    else:
        for expr in _as_exprs(value, "filter"):
            (exclude if expr.startswith("!") else include).append(expr.lstrip("!"))
    return {"include": _dedupe(include), "exclude": _dedupe(exclude), "keep_empty": keep_empty}


def resolve_view(model: Optional[dict] = None, **overrides) -> dict:
    """The whole view of one diagram, every key concrete (6.1).

    Resolution order, most specific first: ``overrides`` (the CLI flag and the
    ``build_diagram`` keyword arrive through the same channel) -> an explicit model
    key -> the ``detail`` preset when ``detail`` was set explicitly -> the ``purpose``
    preset -> the ``detail`` preset the purpose selected -> the hard default. The
    middle two are split because a purpose that names ``label_fields`` must beat the
    detail level it chose itself, while an explicit ``--detail`` must beat the purpose.
    """
    model = dict(model or {})
    unknown = sorted(k for k in overrides if k not in VIEW_KEYS)
    if unknown:
        raise ValueError(f"resolve_view: unknown view key(s) {unknown}; choose from {list(VIEW_KEYS)}")
    over = {k: v for k, v in overrides.items() if v is not None}

    purpose = choice(over.get("purpose", model.get("purpose")), PURPOSES_ORDER, None, "purpose")
    pre_p: dict = dict(PURPOSES.get(purpose) or {})
    detail_explicit = ("detail" in over) or (model.get("detail") is not None)
    detail = choice(over.get("detail", model.get("detail")) or pre_p.get("detail"),
                    DETAIL_ORDER, DEFAULTS["detail"], "detail")
    pre_d: dict = dict(DETAIL_LEVELS[detail])

    def pick(key):
        if key in over:
            return over[key]
        if model.get(key) is not None:
            return model[key]
        if detail_explicit and key in pre_d:
            return pre_d[key]
        if key in pre_p:
            return pre_p[key]
        if key in pre_d:
            return pre_d[key]
        return DEFAULTS.get(key)

    notes: List[str] = []
    label_mode = choice(pick("label_mode"), LABEL_MODE_ORDER, DEFAULTS["label_mode"], "label_mode")
    raw_fields = pick("label_fields")
    fields = list(_as_tuple(raw_fields, "label_fields")) if raw_fields else list(LABEL_MODES[label_mode])

    # layers: "off" | "auto" | an explicit list. The two guideline "layers" that are
    # really label fields are rewritten here, with a note the caller prints (6.2).
    # A5 / V3 / ruling 3: a purpose sets the layer SET, never the layer MODE, so
    # "layers" is read from the override and the model only - never from a preset.
    raw_layers = over["layers"] if "layers" in over else model.get("layers")
    if raw_layers is None:
        raw_layers = DEFAULTS["layers"]
    named: Optional[Tuple[str, ...]] = None
    if raw_layers is True:
        layers_mode = "auto"
    elif raw_layers is False or raw_layers is None:
        layers_mode = "off"
    elif isinstance(raw_layers, str) and raw_layers.strip().lower() in ("", "off", "none", "no"):
        layers_mode = "off"
    elif isinstance(raw_layers, str) and raw_layers.strip().lower() == "auto":
        layers_mode = "auto"
    else:
        layers_mode = "explicit"
        named = _as_tuple(raw_layers, "layers")
    if named is not None:
        kept: List[str] = []
        for name in named:
            key = name.strip().lower()
            if key in LAYER_FIELD_ALIASES:
                wanted = LAYER_FIELD_ALIASES[key]
                fields.extend(f for f in wanted if f not in fields)
                notes.append(f"WARNING: layer {name!r} is a label field, not a cell layer; "
                             f"added {', '.join(wanted)} to label_fields")
                continue
            if key not in VIEW_LAYERS:
                raise ValueError(f"layers: {name!r} is not one of {VIEW_LAYERS} "
                                 f"(or {sorted(LAYER_FIELD_ALIASES)})")
            kept.append(key)
        named = _dedupe(kept)
        if not named:
            layers_mode = "off"

    for field in fields:
        if field in NEVER_RENDERED:
            raise ValueError(f"label_fields: {field!r} is never rendered in a caption; "
                             f"it stays in the tooltip and the metadata")
        if field not in LABEL_FIELDS:
            raise ValueError(f"label_fields: {field!r} is not one of {LABEL_FIELDS}")
    label_fields = _dedupe(fields)

    if layers_mode == "off":
        layers: Tuple[str, ...] = ()
    elif layers_mode == "explicit":
        layers = named or ()
    else:
        layers = _dedupe(pre_p.get("layers") or pre_d["auto_layers"])

    view: Dict[str, object] = {
        "purpose": purpose,
        "detail": detail,
        "label_mode": label_mode,
        "label_fields": label_fields,
        "label_tag_keys": _as_tuple(pick("label_tag_keys"), "label_tag_keys"),
        "layers_mode": layers_mode,
        "layers": layers,
        "base_layer_name": BASE_LAYER_NAME,
        "filter": _filter_spec(pick("filter")),
        "mode": choice(pick("mode"), MODES, DEFAULTS["mode"], "mode"),
        "annotate_discovery": bool(pick("annotate_discovery")),
        "global_services": choice(pick("global_services"), GLOBAL_SERVICES_MODES,
                                  DEFAULTS["global_services"], "global_services"),
        "show_edges": bool(pick("show_edges")),
        "show_compartments": bool(pick("show_compartments")),
        "legend": pick("legend"),
        "notes": notes,
    }
    discovery = pick("discovery")
    if discovery is None:
        view["discovery"] = None
    else:
        picked = _as_tuple(discovery, "discovery")
        for kind in picked:
            choice(kind, DISCOVERY_KINDS, None, "discovery")
        view["discovery"] = _dedupe(k.strip().lower() for k in picked) or None
    for gate in GATE_KEYS:
        view[gate] = bool(pick(gate))
    # 6.3: the minimal label mode drops connector labels. It does so by setting
    # the edge_labels GATE as a default, not by a second test inside the layout
    # helper, so there is exactly one place that decides whether a connector
    # carries a label. It is only a default: an explicit edge_labels override,
    # model key or purpose value still wins, and a detail level that asked for
    # "minimal" (executive, application) is not affected, because only an
    # explicitly chosen label_mode triggers it.
    if (label_mode == "minimal"
            and ("label_mode" in over or model.get("label_mode") is not None)
            and "edge_labels" not in over and model.get("edge_labels") is None
            and "edge_labels" not in pre_p):
        view["edge_labels"] = False
    # 6.3: a level that hides the CIDR titles subnets and VCNs by name alone,
    # unless the model / CLI named a subnet_label itself.
    subnet_label = over.get("subnet_label", model.get("subnet_label"))
    if subnet_label is None and not view["subnet_cidr"]:
        subnet_label = "name"
    view["subnet_label"] = choice(subnet_label, SUBNET_LABEL_MODES,
                                  DEFAULTS["subnet_label"], "subnet_label")
    # V4: a gate that is off hides its layer rather than dropping its cells.
    hidden = list(_as_tuple(pick("hidden_layers"), "hidden_layers"))
    for name in hidden:
        if name not in VIEW_LAYERS:
            raise ValueError(f"hidden_layers: {name!r} is not one of {VIEW_LAYERS}")
    for gate, layer in GATE_LAYERS.items():
        if layer in layers and not view[gate] and layer not in hidden:
            hidden.append(layer)
    if not view["show_edges"]:
        hidden.extend(n for n in ("dataflow", "management", "associations")
                      if n in layers and n not in hidden)
    view["hidden_layers"] = _dedupe(n for n in hidden if n in layers)
    view["line_budget"] = max(LABEL_LINE_BUDGET[label_mode], len(label_fields))
    return view


def draws(view: dict, gate: str) -> bool:
    """Whether a gated element is emitted at all (V4).

    A gate that is off still emits when its view layer is enabled: the cells are
    drawn and the layer - created hidden by ``resolve_view`` - carries the
    visibility, which is what lets the reader switch the content back on in
    draw.io without regenerating.
    """
    if gate not in GATE_KEYS:
        raise ValueError(f"draws: unknown gate {gate!r}; choose from {GATE_KEYS}")
    if view.get(gate):
        return True
    layer = GATE_LAYERS.get(gate)
    return bool(layer and layer in (view.get("layers") or ()))


# ---------------------------------------------------------------------------
# Caption rendering (6.3)
# ---------------------------------------------------------------------------
_AD_RE = re.compile(r"AD[-_ ]?(\d+)\s*$", re.I)
_FD_RE = re.compile(r"(?:FAULT[-_ ]?DOMAIN|FD)[-_ ]?(\d+)\s*$", re.I)

# 6.3: a gateway's "type" is the recipe's short code (igw / nat / sgw / lpg /
# drg / rpc), not a Terraform resource type, so humanise_type() would render it
# "Igw". The detailed mode uses these names instead, and the V5 dedupe below
# then drops the line entirely when the authored caption already says it -
# which is the usual case ("Service\nGateway").
GATEWAY_TYPE_LABELS: Dict[str, str] = {
    "igw": "Internet gateway", "nat": "NAT gateway", "sgw": "Service gateway",
    "lpg": "Local peering gateway", "drg": "Dynamic routing gateway",
    "rpc": "Remote peering connection",
}


def _normalise(text: str) -> str:
    """Whitespace- and case-normalised text, for the V5 dedupe.

    An authored caption is wrapped by hand ("Service\\nGateway"); a rendered
    field is not ("Service gateway"). Comparing the raw strings would let the
    second through, so both sides are collapsed to single spaces first.
    """
    return " ".join(str(text or "").lower().split())


def _occurs_in(candidate: str, rendered: str) -> bool:
    """Does the normalised ``candidate`` already occur in the rendered text?

    "Occurs" is whole-token containment, not plain substring containment: the
    candidate must start and end on a whitespace boundary of ``rendered``. Plain
    ``in`` would drop the port line of ``ports: "80"`` merely because "80" is a
    tail of the private IP ``10.0.0.80`` (and ``"22"`` inside ``10.0.0.22``),
    which is ordinary output of the parser's own producers in the default
    ``network`` label mode. The V5 case this rule exists for - an authored
    ``"Load Balancer\\n10.0.0.23"`` absorbing the rendered ``private_ip`` - is
    whole-token equality and still matches.
    """
    if not candidate:
        return False
    return re.search(r"(?<!\S)" + re.escape(candidate) + r"(?!\S)", rendered) is not None


def humanise_type(rtype: str) -> str:
    """``oci_core_instance`` -> ``Core instance``.

    The fallback when the caller supplies no ``type_labels`` map. The recipe
    passes the parser's own ``RESOURCE_ICONS`` table, which carries Oracle's
    wording; this module may not import it.
    """
    text = str(rtype or "").strip()
    if not text:
        return ""
    if text.startswith("oci_"):
        text = text[4:]
    text = text.replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else ""


def _elide(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "..."


def _ad_fd(meta: dict) -> str:
    parts = []
    ad = _AD_RE.search(str(meta.get("availability_domain") or ""))
    if ad:
        parts.append(f"AD-{ad.group(1)}")
    fd = _FD_RE.search(str(meta.get("fault_domain") or ""))
    if fd:
        parts.append(f"FD-{fd.group(1)}")
    return " / ".join(parts)


def _tag_value(item: dict, key: str) -> Optional[str]:
    tags = item.get("tags") or {}
    for bucket in ("freeform", "defined"):
        values = tags.get(bucket) or {}
        if isinstance(values, dict) and key in values and values[key] not in (None, ""):
            return str(values[key])
    return None


def _field_texts(field: str, item: dict, view: dict, type_labels, kind: str = "icon") -> List[str]:
    """The zero, one or more lines a single field contributes."""
    meta = item.get("metadata") or {}
    if field == "display_name":
        return [str(item.get("label") or "")] if item.get("label") else []
    if field == "resource_type":
        rtype = str(item.get("type") or "")
        if not rtype:
            return []
        if kind == "gateway":
            label = GATEWAY_TYPE_LABELS.get(rtype.strip().lower(), "")
        else:
            label = (type_labels or {}).get(rtype) or humanise_type(rtype)
        return [label] if label else []
    if field == "shape":
        # 11: the "1.4 caption" restore recipe is display_name,shape - the line
        # the parser used to append to the label itself.
        return [str(meta["shape"])] if meta.get("shape") else []
    if field == "private_ip":
        value = meta.get("private_ip") or meta.get("ip_address")
        return [str(value)] if value else []
    if field in ("public_ip", "cidr"):
        value = meta.get(field) or item.get(field)
        return [str(value)] if value else []
    if field == "fqdn":
        return [_elide(meta["fqdn"], FQDN_MAX_CHARS)] if meta.get("fqdn") else []
    if field == "port_protocol":
        return [str(meta["ports"])] if meta.get("ports") else []
    if field == "compartment":
        return [f"Compartment: {meta['compartment']}"] if meta.get("compartment") else []
    if field == "ad_fd":
        text = _ad_fd(meta)
        return [text] if text else []
    if field == "lifecycle":
        state = str(meta.get("lifecycle_state") or "").strip()
        return [state] if state and state.upper() not in HEALTHY_LIFECYCLE_STATES else []
    if field == "tags":
        out = []
        for key in view.get("label_tag_keys") or ():
            value = _tag_value(item, key)
            if value is not None:
                out.append(f"{key}={value}")
        return out
    raise ValueError(f"render_caption: unknown label field {field!r}")


def caption_lines(item: dict, view: dict, kind: str = "icon", type_labels=None) -> List[str]:
    """The caption of one element as a list of lines (6.3).

    V5: the authored ``label`` is kept verbatim - it may already be multi-line -
    and every later field whose text already occurs as whole tokens in what has
    been rendered so far is skipped (``_occurs_in``), so a hand-written model
    renders exactly as it does today in every mode.
    """
    if kind == "gateway":
        # 6.3: gateway captions are width-critical (they straddle a border and
        # carry label_fill), so only the authored form, plus the resource type in
        # the detailed mode when the caption does not already name it.
        fields = ["display_name"] + (["resource_type"] if view.get("label_mode") == "detailed" else [])
    else:
        fields = list(view.get("label_fields") or LABEL_MODES[DEFAULTS["label_mode"]])
    lines: List[str] = []
    seen = ""
    for field in fields:
        for text in _field_texts(field, item, view, type_labels, kind=kind):
            text = str(text).strip()
            # V5: both sides are whitespace-normalised, so a hand-wrapped
            # authored caption ("Service\nGateway") still absorbs the rendered
            # form of the same words ("Service gateway"); the match is on whole
            # tokens, so a short value is not swallowed by a longer one that
            # merely ends with it (ports "80" under private_ip "10.0.0.80").
            if not text or _occurs_in(_normalise(text), seen):
                continue
            lines.append(text)
            seen = _normalise(" ".join(lines))
    return lines


def render_caption(item: dict, view: dict, kind: str = "icon", type_labels=None) -> str:
    """``caption_lines`` joined with newlines - one field per line.

    The guidelines write the modes inline (``App Broker VM / 10.0.2.47 / TCP/22,
    8088``); the caption box is 105 px wide, so the plugin renders one field per
    LINE, which is the same information in the geometry the recipe already has.
    """
    return "\n".join(caption_lines(item, view, kind=kind, type_labels=type_labels))


# ---------------------------------------------------------------------------
# Filtering (6.5), participating mode (6.6) and dangling pruning
# ---------------------------------------------------------------------------
import copy  # noqa: E402  (kept beside the section that needs it)

FILTER_OPS = ("=", "~")
# 6.5: the dimensions of the guidelines' section 1 filter list, plus the two
# conveniences (env / app) and the 6.8 provenance axis.
FILTER_DIMENSIONS = ("tag", "ftag", "dtag", "compartment", "region", "vcn", "subnet",
                     "type", "icon", "name", "address", "env", "app", "discovery")
# 6.5: "Structure is not predicated ... unless an expression names it directly."
STRUCTURAL_DIMENSIONS = ("vcn", "subnet", "type", "name")
# 6.8: "A filter expression discovery=heuristic works too" - on EDGES. Provenance
# is a property of a relationship, never of an item, and _lookup defaults a
# dimensionless entry to "association", so evaluating this axis over items would
# make any include form (discovery=heuristic, discovery=config, ...) drop every
# item in the diagram. keep_items therefore predicates ITEM_DIMENSIONS only.
EDGE_DIMENSIONS = ("discovery",)
ITEM_DIMENSIONS = tuple(d for d in FILTER_DIMENSIONS if d not in EDGE_DIMENSIONS)
# 6.6 clause 5: "named DIRECTLY by an include filter expression". Only the
# dimensions read off the item itself qualify. A container- or model-level
# dimension (region, vcn, subnet, compartment) matches every item inside it
# equally, and an inherited tag (item -> subnet -> VCN) can do the same, so
# treating either as a direct naming would keep the whole model and silently
# disable participating mode - exactly the live-tenancy case 6.6 exists for,
# where the sugar flags --compartment and --tag build include expressions.
DIRECT_DIMENSIONS = ("name", "address", "type", "icon")
# Conventions, not OCI concepts: documented sugar over tag:, listed here so a
# project can see exactly which keys are tried and in which order.
ENV_TAG_KEYS = ("Environment", "environment", "env")
APP_TAG_KEYS = ("Application", "application", "app", "Team", "team")
_EXPR_RE = re.compile(r"^(?P<neg>!?)(?P<dim>[A-Za-z_]+)(?::(?P<key>[^=~]+))?"
                      r"(?P<op>[=~])(?P<val>.*)$")


def _parse_expr(text: str) -> dict:
    m = _EXPR_RE.match(str(text).strip())
    if not m:
        raise ValueError(f"filter: {text!r} is not '[!]<dimension>[:<key>]<op><value>[,<value>]' "
                         f"with <op> one of {FILTER_OPS}")
    dim = m.group("dim").strip().lower()
    if dim not in FILTER_DIMENSIONS:
        raise ValueError(f"filter: {dim!r} is not one of {FILTER_DIMENSIONS}")
    key = (m.group("key") or "").strip()
    if dim in ("tag", "ftag", "dtag") and not key:
        raise ValueError(f"filter: {text!r} needs a tag key, e.g. 'tag:Application=payments'")
    values = tuple(v.strip() for v in m.group("val").split(",") if v.strip())
    if not values:
        raise ValueError(f"filter: {text!r} has no value")
    return {"negate": bool(m.group("neg")), "dim": dim, "key": key,
            "op": m.group("op"), "values": values, "raw": str(text).strip()}


def parse_filter(spec) -> dict:
    """Normalise a filter spec into ``{"include": [expr], "exclude": [expr], "keep_empty": bool}``.

    Accepts the model form ``{"include": [...], "exclude": [...]}`` and the flat
    CLI form ``["vcn=vcn-app", "!type=..."]``; a leading ``!`` always means
    exclude, in either form.
    """
    norm = _filter_spec(spec)
    include, exclude = [], []
    for raw in norm["include"]:
        expr = _parse_expr(raw)
        (exclude if expr["negate"] else include).append(expr)
    for raw in norm["exclude"]:
        expr = _parse_expr(raw)
        expr["negate"] = True
        exclude.append(expr)
    return {"include": include, "exclude": exclude, "keep_empty": norm["keep_empty"]}


def _list(value) -> list:
    return value if isinstance(value, list) else []


def model_addresses(model: dict) -> List[str]:
    """Every address in the model, in the order ``parse_terraform.model_addresses`` yields them.

    Deliberately duplicated here rather than imported: this module must stay
    plugin-free (V9) so the parser can import it, not the other way round. The
    two walks are pinned together by
    ``tests/test_parse_terraform_views.py::AddressWalkTests``.
    """
    out: List[str] = []

    def take(entry):
        if isinstance(entry, dict) and isinstance(entry.get("address"), str):
            out.append(entry["address"])

    for box in [model.get("hub"), model.get("internet")] + _list(model.get("third_party")):
        for item in _list(box.get("items") if isinstance(box, dict) else None):
            take(item)
    for drg in _list(model.get("drgs")):
        take(drg)
        for att in (_list(drg.get("attachments")) if isinstance(drg, dict) else []):
            take(att)
    for vcn in _list(model.get("vcns")):
        if not isinstance(vcn, dict):
            continue
        take(vcn)
        for sn in _list(vcn.get("subnets")):
            if not isinstance(sn, dict):
                continue
            take(sn)
            for item in _list(sn.get("items")):
                take(item)
        for coll in ("services", "controls", "gateways"):
            for item in _list(vcn.get(coll)):
                take(item)
    for item in _list(model.get("services")):
        take(item)
    return out


def _tags_of(entry) -> Tuple[dict, dict]:
    tags = (entry or {}).get("tags") or {}
    free = tags.get("freeform") if isinstance(tags.get("freeform"), dict) else {}
    defined = tags.get("defined") if isinstance(tags.get("defined"), dict) else {}
    return free, defined


def _lookup(expr: dict, item: dict, vcn: Optional[dict], subnet: Optional[dict],
            model: dict) -> List[str]:
    """Every value of the expression's dimension for this item, as strings.

    Tags are inherited item -> subnet -> VCN, NEAREST WINS: a VCN tagged
    ``Application=payments`` scopes everything drawn inside it, which is what a
    reader asking for "the payments application" means, but an item that sets
    the same key itself overrides it. Collecting every level into one list
    instead would make an override impossible - the VCN's value would keep
    matching - so the walk returns at the first level that has the key.
    """
    dim, key = expr["dim"], expr["key"]
    if dim in ("tag", "ftag", "dtag"):
        for level in (item, subnet, vcn):
            if level is None:
                continue
            free, defined = _tags_of(level)
            out = []
            if dim in ("tag", "ftag") and key in free:
                out.append(str(free[key]))
            if dim in ("tag", "dtag") and key in defined:
                out.append(str(defined[key]))
            if out:
                return out
        return []
    if dim in ("env", "app"):
        # Sugar over tag:, in this exact key order (6.5) - the first key present wins.
        for candidate in (ENV_TAG_KEYS if dim == "env" else APP_TAG_KEYS):
            hit = _lookup({"dim": "tag", "key": candidate}, item, vcn, subnet, model)
            if hit:
                return hit
        return []
    if dim == "compartment":
        meta = item.get("metadata") or {}
        value = meta.get("compartment") or (vcn or {}).get("compartment") or model.get("compartment")
        return [str(value)] if value else []
    if dim == "region":
        return [str(model.get("region") or "")]
    if dim == "vcn":
        return [str(v) for v in ((vcn or {}).get("name"), (vcn or {}).get("address")) if v]
    if dim == "subnet":
        return [str(v) for v in ((subnet or {}).get("name"), (subnet or {}).get("address")) if v]
    if dim == "type":
        return [str(item.get("type") or "")]
    if dim == "icon":
        return [str(item.get("icon") or "")]
    if dim == "name":
        return [str(item.get("label") or "").split("\n")[0].strip()]
    if dim == "address":
        return [str(item.get("address") or "")]
    if dim == "discovery":
        return [str(item.get("discovery") or "association")]
    raise ValueError(f"filter: unhandled dimension {dim!r}")


def _expr_matches(expr: dict, values: List[str]) -> bool:
    for value in values:
        low = value.lower()
        for want in expr["values"]:
            if expr["op"] == "=" and low == want.lower():
                return True
            if expr["op"] == "~" and want.lower() in low:
                return True
    return False


def _matches(parsed: dict, item: dict, vcn=None, subnet=None, model=None,
             dims=None) -> bool:
    """AND across dimensions, OR within one; exclude always wins (6.5)."""
    model = model or {}
    for expr in parsed["exclude"]:
        if dims is not None and expr["dim"] not in dims:
            continue
        if _expr_matches(expr, _lookup(expr, item, vcn, subnet, model)):
            return False
    groups: Dict[Tuple[str, str], List[dict]] = {}
    for expr in parsed["include"]:
        if dims is not None and expr["dim"] not in dims:
            continue
        groups.setdefault((expr["dim"], expr["key"]), []).append(expr)
    for exprs in groups.values():
        if not any(_expr_matches(e, _lookup(e, item, vcn, subnet, model)) for e in exprs):
            return False
    return True


def prune_dangling(model: dict, known=None) -> dict:
    """Drop DRG attachments whose other end is gone, null dangling LPG peers, drop dead edges.

    Extracted from ``parse_terraform.select_vcn``, which now calls it, so the
    single-VCN shortcut and the general filter behave identically (6.5).
    Mutates ``model``; returns ``{"attachments": n, "peers": n, "edges": n}``.

    ``known`` is the set of endpoint names this pruner is allowed to judge -
    normally the model's addresses BEFORE the filter ran. An edge endpoint the
    walk has never heard of is not a dangling reference: the recipe's registry
    also resolves ``groups[]`` box keys, NSG badge addresses, ``services:<vcn>``
    and plain container names. Without ``known`` those endpoints would be
    deleted from every diagram, filtered or not, so an unrecognised form is
    left alone and only a name that *was* in the model and is not any more is
    pruned. ``known=None`` keeps the strict behaviour ``select_vcn`` wants.
    """
    vcn_keys = {str(v[k]) for v in _list(model.get("vcns")) if isinstance(v, dict)
                for k in ("name", "address") if isinstance(v.get(k), str)}
    dropped = {"attachments": 0, "peers": 0, "edges": 0}
    reachable = set(model_addresses(model)) | vcn_keys

    def _dangling(att) -> bool:
        if not isinstance(att, dict):
            return False
        if att.get("type") == "vcn":
            return str(att.get("vcn")) not in vcn_keys
        # An ipsec / virtual-circuit / rpc attachment points at a CPE, a DRG or
        # a peer that the filter may have removed; leaving it in makes
        # build_diagram raise "edge endpoint 'cpe' not found".
        return bool(att.get("target")) and str(att.get("target")) not in reachable

    for drg in _list(model.get("drgs")):
        if not isinstance(drg, dict):
            continue
        atts = _list(drg.get("attachments"))
        kept = [a for a in atts if not _dangling(a)]
        dropped["attachments"] += len(atts) - len(kept)
        drg["attachments"] = kept
    alive = set(model_addresses(model)) | vcn_keys
    for vcn in _list(model.get("vcns")):
        for gw in _list(vcn.get("gateways") if isinstance(vcn, dict) else None):
            if isinstance(gw, dict) and gw.get("peer") and str(gw["peer"]) not in alive:
                gw["peer"] = None
                dropped["peers"] += 1

    def _dead(ref) -> bool:
        ref = str(ref)
        if ref in alive:
            return False
        return known is None or ref in known

    edges = _list(model.get("edges"))
    kept_edges = [e for e in edges if isinstance(e, dict)
                  and not _dead(e.get("source")) and not _dead(e.get("target"))]
    dropped["edges"] += len(edges) - len(kept_edges)
    model["edges"] = kept_edges
    return dropped


def filter_model(model: dict, spec=None, mode: str = "all", discovery=None) -> Tuple[dict, dict]:
    """Apply the shared predicate and the participating mode; return (new model, report).

    Never mutates its input. Items in subnets, VCN services and controls,
    top-level services and location-box items are predicated; structure is not,
    unless a ``vcn=`` / ``subnet=`` expression names the container directly
    (6.5). A subnet the filter empties is dropped, and so is a VCN with no
    subnets and no services, unless ``keep_empty`` is set - its gateways do not
    keep it alive, because they were never predicated in the first place.
    """
    mode = choice(mode, MODES, DEFAULTS["mode"], "mode")
    parsed = parse_filter(spec)
    # The endpoint names this model knew before anything was removed; see
    # prune_dangling's docstring for why an unknown endpoint form is kept.
    known_before = set(model_addresses(model))
    m = copy.deepcopy(model)
    report = {"include": tuple(e["raw"] for e in parsed["include"]),
              "exclude": tuple(e["raw"] for e in parsed["exclude"]),
              "items_kept": 0, "items_dropped": 0, "edges_dropped": 0,
              "containers_dropped": 0, "pruned_items": 0, "pruned_services": 0,
              "mode": mode, "warnings": []}
    has_filter = bool(parsed["include"] or parsed["exclude"])

    # A region expression is a whole-model predicate: it either keeps or empties.
    region_exprs = [e for e in parsed["include"] + parsed["exclude"] if e["dim"] == "region"]
    if region_exprs and not _matches(parsed, {}, None, None, m, dims=("region",)):
        # Count the DRAWN items that disappear, not every address: an address
        # walk also yields VCNs, subnets, DRGs and attachments, which are
        # containers and structure, not items.
        report["items_dropped"] = (
            sum(len(_list(sn.get("items"))) for v in _list(m.get("vcns"))
                if isinstance(v, dict) for sn in _list(v.get("subnets")) if isinstance(sn, dict))
            + sum(len(_list(v.get(coll))) for v in _list(m.get("vcns")) if isinstance(v, dict)
                  for coll in ("services", "controls"))
            + len(_list(m.get("services")))
            + sum(len(_list(box.get("items"))) for box in
                  [m.get("hub"), m.get("internet")] + _list(m.get("third_party"))
                  if isinstance(box, dict)))
        # internet and third_party are emptied too: 6.5 calls region "a
        # whole-model predicate; it either keeps or empties the model", and
        # leaving them behind would still draw an Internet box with users in a
        # region the reader filtered out, while the report counted their items
        # as dropped.
        m.update({"vcns": [], "services": [], "hub": None, "drgs": [], "edges": [],
                  "internet": None, "third_party": []})
        report["containers_dropped"] = len(_list(model.get("vcns")))
        return m, report

    def keep_items(items, vcn=None, subnet=None):
        kept = []
        for item in _list(items):
            if not has_filter or _matches(parsed, item, vcn, subnet, m, dims=ITEM_DIMENSIONS):
                kept.append(item)
                report["items_kept"] += 1
            else:
                report["items_dropped"] += 1
        return kept

    def keep_container(entry, vcn=None, subnet=None, dims=()) -> bool:
        """6.5: a container is predicated only by the dimensions that name IT.

        ``dims`` is ``("vcn",)`` for a VCN and ``("subnet",)`` for a subnet.
        Evaluating every STRUCTURAL_DIMENSION at every level instead would make
        ``subnet=sn-app`` or ``type=oci_core_instance`` drop every VCN, because
        a VCN probe matches neither.
        """
        if not has_filter or not dims:
            return True
        named = [e for e in parsed["include"] + parsed["exclude"] if e["dim"] in dims]
        if not named:
            return True
        return _matches(parsed, entry, vcn, subnet, m, dims=dims)

    vcns = []
    for vcn in _list(m.get("vcns")):
        probe = {"label": vcn.get("name"), "address": vcn.get("address"), "type": "oci_core_vcn"}
        if not keep_container(probe, vcn=vcn, dims=("vcn",)):
            report["containers_dropped"] += 1 + len(_list(vcn.get("subnets")))
            report["items_dropped"] += sum(len(_list(s.get("items")))
                                           for s in _list(vcn.get("subnets")))
            report["items_dropped"] += len(_list(vcn.get("services")))
            continue
        subnets = []
        for sn in _list(vcn.get("subnets")):
            sprobe = {"label": sn.get("name"), "address": sn.get("address"),
                      "type": "oci_core_subnet"}
            if not keep_container(sprobe, vcn=vcn, subnet=sn, dims=("subnet",)):
                report["containers_dropped"] += 1
                report["items_dropped"] += len(_list(sn.get("items")))
                continue
            sn["items"] = keep_items(sn.get("items"), vcn=vcn, subnet=sn)
            if sn["items"] or parsed["keep_empty"] or not has_filter:
                subnets.append(sn)
            else:
                report["containers_dropped"] += 1
        vcn["subnets"] = subnets
        for coll in ("services", "controls"):
            vcn[coll] = keep_items(vcn.get(coll), vcn=vcn)
        # Gateways alone do NOT keep a VCN: they survive every predicate by
        # construction (structure is not predicated), so counting them would
        # make every VCN unemptiable and test_keep_empty_keeps_an_emptied_
        # container could never observe a difference.
        if vcn["subnets"] or vcn["services"] or parsed["keep_empty"] or not has_filter:
            vcns.append(vcn)
        else:
            report["containers_dropped"] += 1
    m["vcns"] = vcns
    m["services"] = keep_items(m.get("services"))
    for box_key in ("hub", "internet"):
        box = m.get(box_key)
        if isinstance(box, dict):
            box["items"] = keep_items(box.get("items"))
    for box in _list(m.get("third_party")):
        if isinstance(box, dict):
            box["items"] = keep_items(box.get("items"))

    # 6.8: the discovery selector and the discovery= expressions prune edges only.
    # Read through _as_tuple, not tuple(): a front end may hand this the raw
    # flag value "association,user", and tuple() on a string yields its
    # CHARACTERS, which matches no discovery kind and would silently drop every
    # edge in the diagram.
    # Each kind goes through ``choice`` exactly as resolve_view does, so the two
    # entry points into the same concept agree: an unknown or mis-cased kind is
    # a ValueError, not a diagram that silently lost every edge.
    wanted = tuple(choice(kind, DISCOVERY_KINDS, None, "discovery")
                   for kind in _as_tuple(discovery, "discovery")) or None
    if wanted or any(e["dim"] == "discovery" for e in parsed["include"] + parsed["exclude"]):
        kept_edges = []
        for edge in _list(m.get("edges")):
            kind = str(edge.get("discovery") or "association").strip().lower()
            if wanted and kind not in wanted:
                report["edges_dropped"] += 1
                continue
            if not _matches(parsed, edge, None, None, m, dims=("discovery",)):
                report["edges_dropped"] += 1
                continue
            kept_edges.append(edge)
        m["edges"] = kept_edges

    if mode == "participating":
        keep = participating(m, include=parsed["include"])
        for vcn in _list(m.get("vcns")):
            for sn in _list(vcn.get("subnets")):
                before = len(_list(sn.get("items")))
                sn["items"] = [i for i in _list(sn.get("items"))
                               if str(i.get("address") or "") in keep]
                report["pruned_items"] += before - len(sn["items"])
            for coll in ("services", "controls"):
                before = len(_list(vcn.get(coll)))
                vcn[coll] = [i for i in _list(vcn.get(coll))
                             if str(i.get("address") or "") in keep]
                report["pruned_services"] += before - len(vcn[coll])
        before = len(_list(m.get("services")))
        m["services"] = [i for i in _list(m.get("services"))
                         if str(i.get("address") or "") in keep]
        report["pruned_services"] += before - len(m["services"])

    report["edges_dropped"] += prune_dangling(m, known=known_before)["edges"]
    return m, report


def participating(model: dict, include=()) -> set:
    """Addresses of the items that take part in the architecture (6.6).

    An item participates when any of the six clauses holds: it is an endpoint of
    a surviving edge; it is structure (a gateway, a DRG, an attachment, a hub /
    internet / third-party item); it carries a badge or is a badge host; a
    ``groups[]`` box names it; an ``include`` expression names it directly; or it
    is the only item of a subnet that survived for structural reasons.
    """
    keep: set = set()
    for edge in _list(model.get("edges")):
        if isinstance(edge, dict):
            keep.update(str(edge.get(end) or "") for end in ("source", "target"))
    for box in [model.get("hub"), model.get("internet")] + _list(model.get("third_party")):
        for item in _list(box.get("items") if isinstance(box, dict) else None):
            if isinstance(item, dict) and item.get("address"):
                keep.add(str(item["address"]))
    for drg in _list(model.get("drgs")):
        if not isinstance(drg, dict):
            continue
        if drg.get("address"):
            keep.add(str(drg["address"]))
        for att in _list(drg.get("attachments")):
            if isinstance(att, dict) and att.get("address"):
                keep.add(str(att["address"]))
    # Clause 5 keeps only what an include expression names DIRECTLY, so it is
    # read over DIRECT_DIMENSIONS. Every item that reaches participating()
    # already satisfied the whole include list in filter_model, so honouring a
    # region= / vcn= / compartment= expression here would match every survivor
    # and turn participating mode back into "all" whenever a filter is set.
    parsed_include = [e for e in (include or ()) if e.get("dim") in DIRECT_DIMENSIONS]
    for vcn in _list(model.get("vcns")):
        if not isinstance(vcn, dict):
            continue
        for gw in _list(vcn.get("gateways")):
            if isinstance(gw, dict) and gw.get("address"):
                keep.add(str(gw["address"]))
        grouped = {str(name) for container in [vcn] + _list(vcn.get("subnets"))
                   if isinstance(container, dict)
                   for grp in _list(container.get("groups")) if isinstance(grp, dict)
                   for name in (_list(grp.get("items")) + _list(grp.get("subnets")))}
        keep.update(grouped)
        for sn in _list(vcn.get("subnets")):
            if not isinstance(sn, dict):
                continue
            items = [i for i in _list(sn.get("items")) if isinstance(i, dict)]
            for item in items:
                addr = str(item.get("address") or "")
                if not addr:
                    continue
                if item.get("nsgs"):
                    keep.add(addr)
                if parsed_include and _matches({"include": parsed_include, "exclude": []},
                                               item, vcn, sn, model,
                                               dims=DIRECT_DIMENSIONS):
                    keep.add(addr)
            if len(items) == 1 and items[0].get("address"):
                keep.add(str(items[0]["address"]))       # clause 6
        for coll in ("services", "controls"):
            for item in _list(vcn.get(coll)):
                if not isinstance(item, dict):
                    continue
                addr = str(item.get("address") or "")
                if addr and parsed_include and _matches({"include": parsed_include, "exclude": []},
                                                        item, vcn, None, model,
                                                        dims=DIRECT_DIMENSIONS):
                    keep.add(addr)
    for item in _list(model.get("services")):
        if not isinstance(item, dict):
            continue
        addr = str(item.get("address") or "")
        if addr and parsed_include and _matches({"include": parsed_include, "exclude": []},
                                                item, None, None, model,
                                                dims=DIRECT_DIMENSIONS):
            keep.add(addr)
    keep.discard("")
    return keep
