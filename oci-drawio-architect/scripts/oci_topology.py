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

# Terraform resource types that stay VCN-resident even though their icon key
# is in REGIONAL_ICON_KEYS (spec section 6: "oci_dns_resolver is VCN-resident;
# the dns icon alone is regional"). Checked before the icon-key lookup so a
# resolver item (icon "dns", type "oci_dns_resolver") without an explicit
# "regional" override is never misclassified into the OSN panel.
_VCN_RESIDENT_TYPES = frozenset({"oci_dns_resolver"})


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
    if str(item.get("type") or "") in _VCN_RESIDENT_TYPES:
        return False
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
