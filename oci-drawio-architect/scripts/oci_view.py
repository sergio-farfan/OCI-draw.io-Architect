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
