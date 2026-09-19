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
import sys
from typing import Dict, List, Optional, Tuple

TOPOLOGY_KINDS = ("single_vcn", "multi_vcn", "vcn_with_drg", "hub_spoke", "hybrid")
ATTACHMENT_TYPES = ("vcn", "ipsec", "virtual_circuit", "rpc", "loopback")
ONPREM_ATTACHMENT_TYPES = ("ipsec", "virtual_circuit")
# Spec 7.1: a hub is on-premises when it holds a CPE, an IPSec endpoint or a
# virtual circuit. Any other item (an RPC peer, a firewall, a generic box) does
# not by itself make the topology hybrid.
ONPREM_ITEM_TYPES = frozenset({"oci_core_cpe", "oci_core_ipsec", "oci_core_virtual_circuit",
                               "cpe", "ipsec", "virtual_circuit"})
ONPREM_ICON_KEYS = frozenset({"cpe", "customer_premises_equipment", "fastconnect", "vpn"})

# Hub panel kinds. The container keeps the onprem styling in both cases; only
# the default title follows the kind (an explicit hub["name"] always wins).
HUB_KINDS = ("onprem", "remote_region")
HUB_TITLES = {"onprem": "On-premises", "remote_region": "Remote region"}

# v1.4.0 view choices. Every one of them is a property of the VIEW, never of
# the Terraform: the parser never writes them (spec section 5).
LOCATION_MODES = ("outside", "nested")          # L1: Oracle's Location Canvas, or the 1.3.0 nested panel
GATEWAY_EDGES = ("auto", "internet", "top", "bottom")
GATEWAY_SIDES = ("top", "right", "bottom", "left")
SUBNET_LABEL_MODES = ("twoline", "inline")      # L4: name+token over CIDR, or the 1.3.0 single line
ATTACHMENT_STYLE_MODES = ("solid", "dotted")    # mirrors drawio_builder.ATTACHMENT_STYLES
# G6: one grouping mechanism for B05 (User Group, Tier) and B06 (OKE cluster).
GROUP_BOX_TYPES = ("oke_cluster", "tier", "user_group", "other")
GROUP_BOX_TITLES = {"oke_cluster": "Container Engine for Kubernetes Cluster",
                    "tier": "Tier", "user_group": "User Group", "other": "Group"}
# Which container a groups[] entry hangs off, and the member key it uses there:
# a subnet group encloses items, a VCN group bands whole subnets.
GROUP_SCOPES = ("subnet", "vcn")
_GROUP_MEMBER_KEYS = {"subnet": "items", "vcn": "subnets"}


def _choice(value, allowed: tuple, default: str, what: str) -> str:
    """A normalised enum value; absent / empty -> ``default``, unknown -> ValueError."""
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


def locations_mode(model: dict) -> str:
    """``outside`` (default, Oracle's Location Canvas) or ``nested`` (the 1.3.0 panel)."""
    return _choice((model or {}).get("locations"), LOCATION_MODES, "outside", "locations")


def gateway_edge_mode(model: dict) -> str:
    """Which border the Internet-facing gateways take: auto | internet | top | bottom."""
    return _choice((model or {}).get("gateway_edge"), GATEWAY_EDGES, "auto", "gateway_edge")


def subnet_label_mode(model: dict) -> str:
    """``twoline`` (default) or ``inline`` (the 1.3.0 single-line label)."""
    return _choice((model or {}).get("subnet_label"), SUBNET_LABEL_MODES, "twoline", "subnet_label")


def attachment_style_of(model: dict):
    """The model's attachment connector form, or None to take the style profile's."""
    value = (model or {}).get("attachment_style")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _choice(value, ATTACHMENT_STYLE_MODES, "solid", "attachment_style")


def show_compartments(model: dict) -> bool:
    """L2: compartments are drawn as containers only when the view asks for it."""
    return bool((model or {}).get("show_compartments"))


def hub_kind(hub: dict) -> str:
    """``hub['kind']`` normalised; 'onprem' when absent or unknown."""
    kind = str((hub or {}).get("kind") or "").strip().lower()
    return kind if kind in HUB_KINDS else "onprem"


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

# Terraform resource types that stay VCN-resident even though their icon key
# is in REGIONAL_ICON_KEYS (spec section 6: "oci_dns_resolver is VCN-resident;
# the dns icon alone is regional"). Checked before the icon-key lookup so a
# resolver item (icon "dns", type "oci_dns_resolver") without an explicit
# "regional" override is never misclassified into the OSN panel.
_VCN_RESIDENT_TYPES = frozenset({"oci_dns_resolver"})


_WARNED = set()


def _warn_once(message: str) -> None:
    """Print a one-off WARNING to stderr; repeats within the process are dropped."""
    if message not in _WARNED:
        _WARNED.add(message)
        print(message, file=sys.stderr)


def first_line(text) -> str:
    return str(text or "").split("\n")[0].strip()


def attachment_type(att: dict) -> str:
    raw = str(att.get("type") or "vcn").strip().lower()
    atype = _ATTACHMENT_ALIASES.get(raw, raw)
    if atype not in ATTACHMENT_TYPES:
        _warn_once(f"WARNING: attachment type {raw!r} is not one of {ATTACHMENT_TYPES}")
    return atype


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


def is_onprem_item(item: dict) -> bool:
    """Spec 7.1: a CPE, an IPSec endpoint or a virtual circuit in the hub panel."""
    return (str(item.get("type") or "").lower() in ONPREM_ITEM_TYPES
            or str(item.get("icon") or "").lower() in ONPREM_ICON_KEYS)


def is_regional(item: dict) -> bool:
    flag = item.get("regional")
    if isinstance(flag, bool):
        return flag
    if isinstance(flag, str) and flag.strip().lower() in ("true", "false"):
        return flag.strip().lower() == "true"
    if isinstance(flag, int) and not isinstance(flag, bool):
        return bool(flag)
    if flag not in (None, ""):
        _warn_once(f"WARNING: regional: {flag!r} is not a boolean; falling back to the icon table")
    if str(item.get("type") or "") in _VCN_RESIDENT_TYPES:
        return False
    return str(item.get("icon") or "") in REGIONAL_ICON_KEYS


def badge_refs(value) -> List[dict]:
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


def drg_route_tables(drg: dict) -> List[dict]:
    """B09: the DRG's route tables, in model order (Oracle creates two by default)."""
    return badge_refs((drg or {}).get("route_table"))


def label_parts(name, cidr=None, public=None) -> Tuple[str, str]:
    """L4 / B08: (line 1, line 2) of a two-line subnet or VCN label.

    Line 1 is the name plus a ``(Public)`` / ``(Private)`` token when ``public``
    is present AND a bool - so parser output is always marked and a hand-written
    model that never mentions it stays unmarked. Line 2 is the CIDR.
    """
    line1 = str(name or "")
    if isinstance(public, bool):
        token = "(Public)" if public else "(Private)"
        if token.lower() not in line1.lower():
            line1 = f"{line1} {token}".strip()
    return line1, str(cidr or "")


def choose_drg_style(requested: str, n_attachments: int) -> str:
    if requested is not None and not isinstance(requested, str):
        raise ValueError(f"drg_style must be auto, icon or box, not {requested!r}")
    requested = (requested or "auto").lower()
    if requested not in ("auto", "icon", "box"):
        raise ValueError(f"drg_style must be auto, icon or box, not {requested!r}")
    if requested != "auto":
        return requested
    return "box" if n_attachments > DRG_BOX_THRESHOLD else "icon"


def _match_drg(drgs: List[dict], gateway: dict, warnings: Optional[List[str]] = None) -> Optional[dict]:
    name = first_line(gateway.get("label"))
    if len(drgs) == 1:
        only = drgs[0]
        if name and only.get("name") and str(only["name"]) != name:
            message = (f"WARNING: legacy model: gateway {name!r} merged into the only DRG "
                       f"{only['name']!r}")
            if warnings is not None and message not in warnings:
                warnings.append(message)
        return only
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
                idx = next(i for i, x in enumerate(items) if x is it)
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
            drg = _match_drg(drgs, g, warnings)
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
    # Defensive check (spec section 5: "attachments[].address must be unique in
    # the model"): a duplicate here would otherwise surface only as an opaque
    # ValueError from the builder's duplicate-cell-key guard once laid out.
    seen_addrs: set = set()
    for drg in drgs:
        for att in drg.get("attachments") or []:
            addr = att.get("address")
            if not addr:
                continue
            if addr in seen_addrs:
                warnings.append(f"WARNING: model: attachments[].address duplicate: {addr!r}")
            else:
                seen_addrs.add(addr)
    if drgs or "drgs" in model:
        m["drgs"] = drgs
    return m, warnings


def _slug_label(text: str) -> str:
    out = "".join(ch.lower() if (ch.isalnum() or ch in "-_") else "-" for ch in str(text))
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "group"


def normalise_groups(container: dict, scope: str, parent_key: str) -> List[dict]:
    """G6: the ``groups[]`` entries of one VCN or subnet as ``{type, label, members, key}``.

    ``scope`` selects the member key: ``items`` on a subnet, ``subnets`` on a
    VCN. Members are only names/addresses here - the recipe resolves them and
    raises when one is not in this container (spec 6.5).
    """
    if scope not in _GROUP_MEMBER_KEYS:
        raise ValueError(f"normalise_groups: scope must be 'vcn' or 'subnet', not {scope!r}")
    member_key = _GROUP_MEMBER_KEYS[scope]
    entries = (container or {}).get("groups") or []
    if not isinstance(entries, (list, tuple)):
        raise ValueError(f"{parent_key}: groups must be a list, not {type(entries).__name__}")
    out: List[dict] = []
    seen: Dict[str, str] = {}
    for i, raw in enumerate(entries):
        path = f"{parent_key}: groups[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{path} must be an object with a 'type' and {member_key!r}")
        gtype = str(raw.get("type") or "").strip().lower()
        if gtype not in GROUP_BOX_TYPES:
            raise ValueError(f"{path}: type {raw.get('type')!r} is not one of {GROUP_BOX_TYPES}")
        members = raw.get(member_key)
        if not isinstance(members, (list, tuple)) or not members:
            raise ValueError(f"{path}: {member_key!r} must list at least one member "
                             f"(a groups[] box with no members has nothing to enclose)")
        members = list(members)
        for m in members:
            if not isinstance(m, str) or not m.strip():
                raise ValueError(f"{path}: {member_key!r} members must be non-empty strings, got {m!r}")
            if m in seen:
                raise ValueError(f"{path}: member {m!r} is already in the group {seen[m]!r}; "
                                 f"groups[] boxes in one container may not overlap")
        label = str(raw.get("label") or GROUP_BOX_TITLES[gtype])
        key = str(raw.get("key") or f"group:{parent_key}:{gtype}:{_slug_label(label)}")
        for m in members:
            seen[m] = label
        out.append({"type": gtype, "label": label, "members": members, "key": key})
    return out


def _walk_compartments(nodes: List[dict]):
    """Yield every compartment node of a ``compartment_tree()`` result, depth first."""
    for node in nodes:
        yield node
        for child in _walk_compartments(node["children"]):
            yield child


def compartment_tree(model: dict) -> List[dict]:
    """L2 / B04: the compartment forest, ordered by the column order of the first VCN.

    Accepts both ``compartments`` forms (a bare name, or
    ``{"name", "parent"?, "vcns"?}``) in the same list; an object entry wins
    over a string of the same name. VCNs not claimed by an object entry are
    placed by their own ``vcn["compartment"]``; a VCN naming no known
    compartment stays outside every box and is simply absent from the tree.
    """
    nodes: Dict[str, dict] = {}
    order: List[str] = []
    for entry in (model or {}).get("compartments") or []:
        name = entry.get("name") if isinstance(entry, dict) else entry
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"compartments: {entry!r} has no name")
        node = nodes.setdefault(name, {"name": name, "parent": None, "vcns": [], "children": []})
        if name not in order:
            order.append(name)
        if isinstance(entry, dict):
            parent = entry.get("parent")
            if parent is not None:
                node["parent"] = str(parent)
            for vname in entry.get("vcns") or []:
                if vname not in node["vcns"]:
                    node["vcns"].append(str(vname))
    claimed = {v for node in nodes.values() for v in node["vcns"]}
    vcn_index = {}
    for i, vcn in enumerate((model or {}).get("vcns") or []):
        name = vcn.get("name")
        if not name:
            continue
        vcn_index[name] = i
        cname = vcn.get("compartment")
        if name in claimed or not cname or cname not in nodes:
            continue
        nodes[cname]["vcns"].append(name)
    for name in order:
        parent = nodes[name]["parent"]
        if parent is not None and parent not in nodes:
            raise ValueError(f"compartments: {name!r} names an unknown parent {parent!r}")
    for name in order:
        seen, cur = {name}, nodes[name]["parent"]
        while cur is not None:
            if cur in seen:
                raise ValueError(f"compartments: cycle through {name!r}")
            seen.add(cur)
            cur = nodes[cur]["parent"]
    def rank(name: str) -> tuple:
        idx = [vcn_index[v] for v in nodes[name]["vcns"] if v in vcn_index]
        kids = [rank(c) for c in order if nodes[c]["parent"] == name]
        best = min(idx) if idx else None
        for k in kids:
            if k[0] == 0:
                best = k[1] if best is None else min(best, k[1])
        return (0, best) if best is not None else (1, order.index(name))
    roots = []
    for name in order:
        node = nodes[name]
        node["children"] = sorted((nodes[c] for c in order if nodes[c]["parent"] == name),
                                  key=lambda n: rank(n["name"]))
        if node["parent"] is None:
            roots.append(node)
    return sorted(roots, key=lambda n: rank(n["name"]))


def classify_topology(model: dict) -> dict:
    """Pure classification of an (already migrated) model."""
    vcns = list(model.get("vcns") or [])
    drgs = list(model.get("drgs") or [])
    atts = [a for d in drgs for a in (d.get("attachments") or [])]
    hub_items = list((model.get("hub") or {}).get("items") or [])
    rpc_items = [it for it in hub_items if is_rpc_item(it)]
    has_rpc = bool(rpc_items) or any(attachment_type(a) == "rpc" for a in atts)
    has_onprem = (any(is_onprem_item(it) for it in hub_items)
                  or any(attachment_type(a) in ONPREM_ATTACHMENT_TYPES for a in atts))
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
    "ONPREM_ITEM_TYPES", "ONPREM_ICON_KEYS", "HUB_KINDS", "HUB_TITLES", "hub_kind",
    "LOCATION_MODES", "GATEWAY_EDGES", "GATEWAY_SIDES", "SUBNET_LABEL_MODES",
    "ATTACHMENT_STYLE_MODES", "GROUP_BOX_TYPES", "GROUP_BOX_TITLES", "GROUP_SCOPES",
    "locations_mode", "gateway_edge_mode", "subnet_label_mode", "attachment_style_of",
    "show_compartments", "badge_refs", "drg_route_tables", "label_parts",
    "normalise_groups", "compartment_tree",
    "first_line", "attachment_type", "attachment_label", "attachment_link_label",
    "is_drg_item", "is_rpc_item", "is_onprem_item", "is_regional", "choose_drg_style",
    "migrate_legacy_model", "classify_topology",
]
