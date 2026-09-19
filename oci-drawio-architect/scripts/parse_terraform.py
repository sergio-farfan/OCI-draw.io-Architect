#!/usr/bin/env python3
"""Normalise OCI Terraform into the architecture MODEL consumed by the diagram layout.

Inputs (one of)
---------------
* a Terraform directory (HCL): every top-level ``*.tf`` is parsed with comments
  stripped and real brace matching (``.terraform`` is never entered);
* ``terraform show -json tfplan`` output  (``--plan-json FILE``);
* ``terraform show -json``        output  (``--state-json FILE``).

Output: the MODEL as JSON on stdout (or ``--out FILE``).  A one-line summary goes
to stderr.

MODEL schema (``SCHEMA_VERSION = 2``)
-------------------------------------
::

    {
      "schema_version": 2,
      "subject": str,                 # diagram title subject (VCN or project name)
      "region": str | null,           # "eu-frankfurt-1"
      "region_label": str | null,     # "Frankfurt"
      "compartment": str | null,      # compartment name when it can be determined
      "tenancy_name": str | null,
      "source": {"mode": "hcl"|"plan"|"state"|"tenancy", "path": str | null},
      "drg_style": "auto"|"icon"|"box",
      "drgs": [                       # dynamic routing gateways, drawn at region level
        {
          "name": str, "address": str, "label": str,
          "attachments": [
            {"type": "vcn"|"ipsec"|"virtual_circuit"|"rpc"|"loopback",
             "address": str, "label": str,
             "vcn": str | null,       # VCN name / address for "vcn" attachments
             "target": str | null}    # hub item address the attachment connects to
          ]
        }
      ],
      "hub": {                        # on-premises / transit side, null when absent
        "name": str,
        "items": [ HUB_ITEM ],        # {"icon": str, "label": str, "type": str, "address": str | null}
        "link_label": str | null      # hand-written models only; parser output sets null
      } | null,
      "vcns": [
        {
          "name": str, "address": str, "cidr": str | null, "compartment": str | null,
          "subnets": [
            {
              "name": str, "address": str, "cidr": str | null, "public": bool,
              "tier": "lb"|"app"|"compute"|"mgmt"|"data"|"other",
              "items": [ ITEM ],
              "route_table": {"name": str, "address": str} | null,
              "security_lists": [{"name": str, "address": str}]
            }
          ],
          "services": [ ITEM ],       # VCN-scoped / same-compartment resources outside any subnet,
                                      # each carrying "regional": bool
          "controls": [ ITEM ],       # route tables, security lists, NSGs (usually not drawn)
          "gateways": [
            {"icon": "internet_gateway"|"nat_gateway"|"service_gateway"|"remote_peering_gateway",
             "type": "igw"|"nat"|"sgw"|"lpg", "label": str, "address": str | null,
             "peer": str | null}      # lpg only: the peer LPG address
          ]
        }
      ],
      "services": [ ITEM ],           # resources with no single VCN to attach them to ("regional": bool)
      "compartments": [ str ],
      "edges": [
        {"source": str, "target": str, "label": str,
         "kind": "data"|"control"|"association"|"attachment", "inferred": bool}
      ]
    }

    ITEM = {"icon": str, "label": str, "type": str, "address": str | null, "metadata": {...},
            "nsgs": [{"name": str, "address": str}]}   # "nsgs" only when non-empty

``address`` is the Terraform resource address (base address ``TYPE.NAME`` in HCL
mode because ``count``/``for_each`` cannot be expanded statically; the full
indexed address such as ``oci_core_instance.app[0]`` in plan/state mode) or the
OCID in live-tenancy mode (see ``query_tenancy.py``).  Addresses are unique per
model and meant to seed deterministic draw.io cell ids.  A DRG is reported once
in ``drgs`` with one typed attachment per ``oci_core_drg_attachment`` (VCN),
``oci_core_ipsec`` (ipsec, target = the CPE), ``oci_core_virtual_circuit``
(virtual_circuit; private circuits only - a ``PUBLIC`` circuit has no DRG) and
``oci_core_remote_peering_connection`` (rpc); a DRG without attachments in a
single-VCN model gets an implicit ``<drg>@<vcn>`` attachment.

Route tables, security lists and NSGs are never subnet items. A subnet's ``route_table_id`` and
``security_list_ids`` become ``route_table`` / ``security_lists`` badge references - the managed
``oci_core_route_table`` / ``oci_core_security_list`` and the VCN's ``oci_core_default_route_table``
/ ``oci_core_default_security_list`` alike. An item's ``nsg_ids`` / ``network_security_group_ids``
(instances via ``create_vnic_details``, load balancers, network load balancers, DB systems) and the
``nsg_ids`` of ``oci_core_vnic_attachment`` resources attached to an instance become the item's
``nsgs``. The layout draws them as badges on the subnet's top-right corner and on the resource
icon. ``controls`` still lists the resources themselves.

``hub`` holds the on-premises side only (CPE, virtual circuit, RPC peer).  LPG
pairs produce one ``Local Peering`` edge of kind ``attachment`` and both
gateways carry ``peer`` even though only the requestor declares ``peer_id``; the
layout draws the DRG attachment connectors itself.  ``edges[].inferred`` is
``false`` for edges backed by an explicit reference (LB backend -> instance, LPG
peering) and ``true`` for the tier heuristics (LB -> app compute, app compute ->
database).
Every ``icon`` value is a key of ``drawio_builder.ICON_ALIASES``; the local
peering gateway uses ``remote_peering_gateway`` because no dedicated LPG glyph is
bundled.

Usage
-----
    python3 parse_terraform.py [TF_DIR] [--plan-json FILE | --state-json FILE]
                               [--vcn NAME] [--out model.json] [--no-inferred-edges]

Exit codes: 0 success, 1 nothing recognisable (or ``--vcn`` matched nothing),
2 bad path / unreadable input.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import detect_settings as ds  # noqa: E402

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


# ---------------------------------------------------------------------------
# Resource type -> (icon key, default label)
# ---------------------------------------------------------------------------

RESOURCE_ICONS: Dict[str, Tuple[str, str]] = {
    # compute
    "oci_core_instance": ("vm", "Instance"),
    "oci_core_instance_pool": ("instance_pool", "Instance pool"),
    "oci_containerengine_cluster": ("oke", "OKE cluster"),
    "oci_containerengine_node_pool": ("vm", "Node pool"),
    "oci_functions_application": ("functions", "Functions"),
    # storage
    "oci_core_volume": ("block_storage", "Block volume"),
    "oci_file_storage_file_system": ("file_storage", "File system"),
    "oci_file_storage_mount_target": ("file_storage", "Mount target"),
    "oci_objectstorage_bucket": ("buckets", "Bucket"),
    # database
    "oci_database_autonomous_database": ("autonomous_db", "Autonomous DB"),
    "oci_database_db_system": ("db_system", "DB system"),
    "oci_mysql_mysql_db_system": ("mysql", "MySQL"),
    "oci_nosql_table": ("nosql", "NoSQL table"),
    "oci_redis_redis_cluster": ("nosql", "Redis cluster"),
    # networking
    "oci_load_balancer_load_balancer": ("load_balancer", "Load balancer"),
    "oci_load_balancer": ("load_balancer", "Load balancer"),
    "oci_network_load_balancer_network_load_balancer": ("load_balancer", "Network LB"),
    "oci_core_internet_gateway": ("internet_gateway", "Internet gateway"),
    "oci_core_nat_gateway": ("nat_gateway", "NAT gateway"),
    "oci_core_service_gateway": ("service_gateway", "Service gateway"),
    "oci_core_drg": ("drg", "DRG"),
    "oci_core_local_peering_gateway": ("remote_peering_gateway", "Local peering gateway"),
    "oci_core_remote_peering_connection": ("remote_peering_gateway", "Remote peering"),
    "oci_core_cpe": ("cpe", "CPE"),
    "oci_core_ipsec": ("cpe", "IPSec VPN"),
    "oci_core_virtual_circuit": ("cpe", "FastConnect"),
    "oci_dns_zone": ("dns", "DNS zone"),
    "oci_dns_resolver": ("dns", "DNS resolver"),
    "oci_core_network_security_group": ("nsg", "NSG"),
    "oci_core_security_list": ("security_list", "Security list"),
    "oci_core_route_table": ("route_table", "Route table"),
    "oci_core_default_security_list": ("security_list", "Default security list"),
    "oci_core_default_route_table": ("route_table", "Default route table"),
    # identity & security
    "oci_kms_vault": ("vault", "Vault"),
    "oci_kms_key": ("key_management", "Key"),
    "oci_certificates_management_certificate": ("certificates", "Certificate"),
    "oci_waf_web_app_firewall": ("waf", "WAF"),
    "oci_network_firewall_network_firewall": ("firewall", "Network firewall"),
    "oci_bastion_bastion": ("bastion", "Bastion"),
    # observability & messaging
    "oci_logging_log_group": ("logging", "Log group"),
    "oci_monitoring_alarm": ("alarms", "Alarm"),
    "oci_apm_apm_domain": ("apm", "APM domain"),
    "oci_streaming_stream": ("streaming", "Stream"),
    "oci_queue_queue": ("queuing", "Queue"),
    "oci_events_rule": ("events", "Event rule"),
    "oci_sch_service_connector": ("service_connector_hub", "Service connector"),
    "oci_ons_notification_topic": ("notifications", "Topic"),
    # analytics & AI
    "oci_datascience_project": ("data_science", "Data Science"),
    "oci_analytics_analytics_instance": ("big_data", "Analytics"),
    # developer services
    "oci_apigateway_gateway": ("api_gateway", "API gateway"),
    "oci_devops_project": ("devops", "DevOps project"),
    "oci_artifacts_container_repository": ("container_registry", "Container registry"),
}

# Prefix matches for service families with many resource types.
RESOURCE_ICON_PREFIXES: Tuple[Tuple[str, Tuple[str, str]], ...] = (
    ("oci_ai_language_", ("ai", "AI Language")),
    ("oci_generative_ai_", ("ai", "Generative AI")),
    ("oci_ai_", ("ai", "AI service")),
)

VCN_TYPE = "oci_core_vcn"
SUBNET_TYPE = "oci_core_subnet"
COMPARTMENT_TYPE = "oci_identity_compartment"
DRG_TYPE = "oci_core_drg"
DRG_ATTACHMENT_TYPE = "oci_core_drg_attachment"
GATEWAY_TYPES: Dict[str, str] = {
    "oci_core_internet_gateway": "igw",
    "oci_core_nat_gateway": "nat",
    "oci_core_service_gateway": "sgw",
    "oci_core_local_peering_gateway": "lpg",
}
# Hub-side resources: they become items of the on-premises / remote-region panel.
# (The per-type link labels this table used to carry were never read - the parser
# always emits hub.link_label = None and the layout draws attachment connectors.)
HUB_TYPES = frozenset({"oci_core_cpe", "oci_core_ipsec", "oci_core_virtual_circuit",
                       "oci_core_remote_peering_connection"})
# Security constructs drawn as badges by the layout (subnet corner: route table + security
# lists; resource icon: NSGs) instead of workload icons. ``controls`` keeps the inventory.
# A subnet may use the VCN's default route table / security list instead of a managed one
# (``oci_core_default_route_table`` / ``oci_core_default_security_list``, the pattern of the
# Oracle network modules and of the CIS landing zone), so both types resolve to a badge.
ROUTE_TABLE_TYPE = "oci_core_route_table"
SECURITY_LIST_TYPE = "oci_core_security_list"
NSG_TYPE = "oci_core_network_security_group"
DEFAULT_ROUTE_TABLE_TYPE = "oci_core_default_route_table"
DEFAULT_SECURITY_LIST_TYPE = "oci_core_default_security_list"
ROUTE_TABLE_TYPES = frozenset({ROUTE_TABLE_TYPE, DEFAULT_ROUTE_TABLE_TYPE})
SECURITY_LIST_TYPES = frozenset({SECURITY_LIST_TYPE, DEFAULT_SECURITY_LIST_TYPE})
CONTROL_TYPES = ROUTE_TABLE_TYPES | SECURITY_LIST_TYPES | frozenset({NSG_TYPE})
NSG_ATTRS = ("nsg_ids", "network_security_group_ids")
# Only the attachment is a managed resource; oci_core_vnic exists as a data source only.
VNIC_ATTACHMENT_TYPES = frozenset({"oci_core_vnic_attachment"})
LB_TYPES = frozenset({"oci_load_balancer_load_balancer", "oci_load_balancer",
                      "oci_network_load_balancer_network_load_balancer"})
LB_BACKEND_TYPES = frozenset({"oci_load_balancer_backend", "oci_network_load_balancer_backend"})
LB_LISTENER_TYPES = frozenset({"oci_load_balancer_listener", "oci_network_load_balancer_listener"})
# LB child resources that never become items (exercised only for edges).
LB_CHILD_TYPES = LB_BACKEND_TYPES | LB_LISTENER_TYPES | frozenset({
    "oci_load_balancer_backend_set", "oci_network_load_balancer_backend_set",
    "oci_load_balancer_certificate", "oci_load_balancer_hostname",
    "oci_load_balancer_path_route_set", "oci_load_balancer_rule_set",
})
COMPUTE_TYPES = frozenset({"oci_core_instance", "oci_containerengine_node_pool", "oci_core_instance_pool"})
DB_PORTS: Dict[str, str] = {
    "oci_database_autonomous_database": "1522",
    "oci_database_db_system": "1521",
    "oci_mysql_mysql_db_system": "3306",
}
SHAPE_LABEL_TYPES = COMPUTE_TYPES | frozenset({"oci_database_db_system", "oci_mysql_mysql_db_system"})
SUBNET_ATTRS = ("subnet_id", "subnet_ids", "target_subnet_id")
METADATA_KEYS = ("shape", "shape_name", "availability_domain", "fault_domain", "count", "for_each",
                 "ocpus", "memory_in_gbs", "cpu_core_count", "compute_count", "data_storage_size_in_gb",
                 "db_workload", "db_name", "is_free_tier", "is_private", "node_count",
                 "kubernetes_version", "mysql_version", "size_in_gbs", "ip_address",
                 "minimum_bandwidth_in_mbps", "maximum_bandwidth_in_mbps")

# ---------------------------------------------------------------------------
# Model factories, tier inference and validation (shared with query_tenancy.py)
# ---------------------------------------------------------------------------


def icon_for_type(rtype: str) -> Optional[Tuple[str, str]]:
    """Return ``(icon_key, default_label)`` for a Terraform resource type, or None."""
    hit = RESOURCE_ICONS.get(rtype)
    if hit:
        return hit
    for prefix, value in RESOURCE_ICON_PREFIXES:
        if rtype.startswith(prefix):
            return value
    return None


def new_model(subject: str = "OCI Architecture", region: Optional[str] = None,
              source_mode: str = "hcl", source_path: Optional[str] = None) -> dict:
    region = region.strip().lower() if isinstance(region, str) and region.strip() else None
    return {
        "schema_version": SCHEMA_VERSION,
        "subject": subject,
        "region": region,
        "region_label": ds.region_display_label(region) if region else None,
        "compartment": None,
        "tenancy_name": None,
        "source": {"mode": source_mode, "path": source_path},
        "hub": None,
        "drgs": [],
        "drg_style": "auto",
        "vcns": [],
        "services": [],
        "compartments": [],
        "edges": [],
    }


def new_vcn(name: str, address: str, cidr: Optional[str] = None, compartment: Optional[str] = None) -> dict:
    return {"name": name, "address": address, "cidr": cidr, "compartment": compartment,
            "subnets": [], "services": [], "controls": [], "gateways": []}


def new_subnet(name: str, address: str, cidr: Optional[str] = None, public: Optional[bool] = None,
               tier: Optional[str] = None) -> dict:
    return {"name": name, "address": address, "cidr": cidr,
            "public": infer_public(name) if public is None else bool(public),
            "tier": tier or infer_tier(name), "items": [], "route_table": None, "security_lists": []}


def new_item(icon: str, label: str, rtype: str, address: Optional[str], metadata: Optional[dict] = None) -> dict:
    return {"icon": icon, "label": label, "type": rtype, "address": address, "metadata": dict(metadata or {})}


def new_gateway(gtype: str, label: str, address: Optional[str]) -> dict:
    return {"icon": GATEWAY_ICONS[gtype], "type": gtype, "label": label, "address": address}


def badge_ref(name: str, address: Optional[str] = None) -> dict:
    """A route table / security list / NSG reference drawn as a badge: ``{"name", "address"}``."""
    return {"name": name, "address": address}


def new_hub_item(icon: str, label: str, rtype: str, address: Optional[str]) -> dict:
    return {"icon": icon, "label": label, "type": rtype, "address": address}


def new_drg(name: str, address: str, label: Optional[str] = None) -> dict:
    return {"name": name, "address": address, "label": label or f"DRG\n{name}", "attachments": []}


def new_attachment(atype: str, address: str, label: str, vcn: Optional[str] = None,
                   target: Optional[str] = None) -> dict:
    return {"type": atype, "address": address, "label": label, "vcn": vcn, "target": target}


def new_edge(source: str, target: str, label: str = "", kind: str = "data", inferred: bool = False) -> dict:
    return {"source": source, "target": target, "label": label, "kind": kind, "inferred": inferred}


_TIER_TOKENS: Tuple[Tuple[str, frozenset], ...] = (
    ("data", frozenset({"db", "dbs", "data", "database", "databases", "adb", "atp", "adw", "mysql",
                        "oracle", "redis", "nosql"})),
    ("mgmt", frozenset({"mgmt", "management", "bastion", "ops", "admin", "jump", "jumphost", "tooling",
                        "tools", "monitoring"})),
    ("compute", frozenset({"compute", "oke", "node", "nodes", "k8s", "kubernetes", "pods", "workers"})),
    ("app", frozenset({"app", "apps", "api", "worker", "application", "backend", "middleware", "svc",
                       "service", "services", "fn", "functions"})),
    ("lb", frozenset({"lb", "lbr", "web", "dmz", "public", "pub", "loadbalancer", "frontend", "edge",
                      "ingress"})),
)
_TIER_SUBSTRINGS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("data", ("db", "data")),
    ("mgmt", ("mgmt", "bastion")),
    ("compute", ("compute", "oke", "node")),
    ("app", ("app", "api")),
    ("lb", ("lb", "web", "dmz", "public")),
)
_PUBLIC_TOKENS = frozenset({"public", "pub", "lb", "lbr", "web", "dmz", "edge", "ingress", "frontend"})
_PRIVATE_TOKENS = frozenset({"private", "priv", "prv"})


def _tokens(name: str) -> frozenset:
    return frozenset(t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if t)


def infer_tier(name: str) -> str:
    """Map a subnet name to a layout tier (``lb``/``app``/``compute``/``mgmt``/``data``/``other``)."""
    tokens = _tokens(name)
    for tier, words in _TIER_TOKENS:
        if tokens & words:
            return tier
    lowered = (name or "").lower()
    for tier, subs in _TIER_SUBSTRINGS:
        if any(s in lowered for s in subs):
            return tier
    return "other"


def infer_public(name: str, prohibit_public_ip: Optional[bool] = None) -> bool:
    """``prohibit_public_ip_on_vnic`` wins when known; otherwise guess from the name."""
    if prohibit_public_ip is not None:
        return not prohibit_public_ip
    tokens = _tokens(name)
    if tokens & _PRIVATE_TOKENS:
        return False
    return bool(tokens & _PUBLIC_TOKENS)


def _expect(errors: List[str], value, types, path: str) -> bool:
    if not isinstance(value, types):
        errors.append(f"{path}: expected {getattr(types, '__name__', types)}, got {type(value).__name__}")
        return False
    return True


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


def _validate_item(errors: List[str], item, path: str, with_metadata: bool, icon_keys) -> None:
    if not _expect(errors, item, dict, path):
        return
    _expect(errors, item.get("icon"), str, f"{path}.icon")
    _expect(errors, item.get("label"), str, f"{path}.label")
    _expect(errors, item.get("type"), str, f"{path}.type")
    _expect(errors, item.get("address"), (str, type(None)), f"{path}.address")
    if with_metadata:
        _expect(errors, item.get("metadata"), dict, f"{path}.metadata")
    if "regional" in item:
        _expect(errors, item["regional"], bool, f"{path}.regional")
    if icon_keys is not None and isinstance(item.get("icon"), str) and item["icon"] not in icon_keys:
        errors.append(f"{path}.icon: unknown icon key {item['icon']!r}")
    if "nsgs" in item:
        _validate_badge_refs(errors, item["nsgs"], f"{path}.nsgs")


def validate_model(model, icon_keys: Optional[Iterable[str]] = None) -> List[str]:
    """Return a list of schema violations (empty when ``model`` conforms).

    ``icon_keys`` (e.g. ``drawio_builder.ICON_MAP``) additionally checks that
    every icon key is known to the builder.
    """
    errors: List[str] = []
    if not _expect(errors, model, dict, "model"):
        return errors
    keys = set(icon_keys) if icon_keys is not None else None
    _expect(errors, model.get("schema_version"), int, "schema_version")
    _expect(errors, model.get("subject"), str, "subject")
    for key in ("region", "region_label", "compartment", "tenancy_name"):
        _expect(errors, model.get(key), (str, type(None)), key)
    if _expect(errors, model.get("source"), dict, "source"):
        if model["source"].get("mode") not in ("hcl", "plan", "state", "tenancy"):
            errors.append("source.mode: expected hcl|plan|state|tenancy")
        _expect(errors, model["source"].get("path"), (str, type(None)), "source.path")
    if model.get("drg_style") not in DRG_STYLES:
        errors.append(f"drg_style: {model.get('drg_style')!r} not in {DRG_STYLES}")
    # A41: check the container types before collecting addresses, which walks them.
    drgs_ok = _expect(errors, model.get("drgs"), list, "drgs")
    vcns_ok = _expect(errors, model.get("vcns"), list, "vcns")
    addresses = set(model_addresses(model))
    vcn_keys = {v.get(k) for v in _entries(model.get("vcns")) if isinstance(v, dict) for k in ("name", "address")}
    if drgs_ok:
        for di, drg in enumerate(model["drgs"]):
            dp = f"drgs[{di}]"
            if not _expect(errors, drg, dict, dp):
                continue
            _expect(errors, drg.get("name"), str, f"{dp}.name")
            _expect(errors, drg.get("address"), str, f"{dp}.address")
            _expect(errors, drg.get("label"), str, f"{dp}.label")
            if _expect(errors, drg.get("attachments"), list, f"{dp}.attachments"):
                for ai, att in enumerate(drg["attachments"]):
                    ap = f"{dp}.attachments[{ai}]"
                    if not _expect(errors, att, dict, ap):
                        continue
                    if att.get("type") not in ATTACHMENT_TYPES:
                        errors.append(f"{ap}.type: {att.get('type')!r} not in {ATTACHMENT_TYPES}")
                    _expect(errors, att.get("address"), str, f"{ap}.address")
                    _expect(errors, att.get("label"), str, f"{ap}.label")
                    _expect(errors, att.get("vcn"), (str, type(None)), f"{ap}.vcn")
                    _expect(errors, att.get("target"), (str, type(None)), f"{ap}.target")
                    if att.get("type") == "vcn" and isinstance(att.get("vcn"), str) and att["vcn"] not in vcn_keys:
                        errors.append(f"{ap}.vcn: {att['vcn']!r} is not a VCN name or address in the model")
                    if isinstance(att.get("target"), str) and att["target"] not in addresses:
                        errors.append(f"{ap}.target: {att['target']!r} is not an address in the model")

    hub = model.get("hub")
    if hub is not None and _expect(errors, hub, dict, "hub"):
        _expect(errors, hub.get("name"), str, "hub.name")
        _expect(errors, hub.get("link_label"), (str, type(None)), "hub.link_label")
        if _expect(errors, hub.get("items"), list, "hub.items"):
            for i, item in enumerate(hub["items"]):
                _validate_item(errors, item, f"hub.items[{i}]", False, keys)

    if vcns_ok:
        for vi, vcn in enumerate(model["vcns"]):
            vp = f"vcns[{vi}]"
            if not _expect(errors, vcn, dict, vp):
                continue
            _expect(errors, vcn.get("name"), str, f"{vp}.name")
            _expect(errors, vcn.get("address"), str, f"{vp}.address")
            _expect(errors, vcn.get("cidr"), (str, type(None)), f"{vp}.cidr")
            _expect(errors, vcn.get("compartment"), (str, type(None)), f"{vp}.compartment")
            if _expect(errors, vcn.get("subnets"), list, f"{vp}.subnets"):
                for si, sn in enumerate(vcn["subnets"]):
                    sp = f"{vp}.subnets[{si}]"
                    if not _expect(errors, sn, dict, sp):
                        continue
                    _expect(errors, sn.get("name"), str, f"{sp}.name")
                    _expect(errors, sn.get("address"), str, f"{sp}.address")
                    _expect(errors, sn.get("cidr"), (str, type(None)), f"{sp}.cidr")
                    _expect(errors, sn.get("public"), bool, f"{sp}.public")
                    if sn.get("tier") not in TIERS:
                        errors.append(f"{sp}.tier: {sn.get('tier')!r} not in {TIERS}")
                    _validate_badge_refs(errors, sn.get("route_table"), f"{sp}.route_table", single=True)
                    if "security_lists" in sn:
                        _validate_badge_refs(errors, sn["security_lists"], f"{sp}.security_lists")
                    if _expect(errors, sn.get("items"), list, f"{sp}.items"):
                        for ii, item in enumerate(sn["items"]):
                            _validate_item(errors, item, f"{sp}.items[{ii}]", True, keys)
            for coll in ("services", "controls"):
                if _expect(errors, vcn.get(coll), list, f"{vp}.{coll}"):
                    for ii, item in enumerate(vcn[coll]):
                        _validate_item(errors, item, f"{vp}.{coll}[{ii}]", True, keys)
            if _expect(errors, vcn.get("gateways"), list, f"{vp}.gateways"):
                for gi, gw in enumerate(vcn["gateways"]):
                    gp = f"{vp}.gateways[{gi}]"
                    if not _expect(errors, gw, dict, gp):
                        continue
                    if gw.get("type") not in GATEWAY_ICONS:
                        errors.append(f"{gp}.type: {gw.get('type')!r} not in {tuple(GATEWAY_ICONS)}")
                    elif gw.get("icon") != GATEWAY_ICONS[gw["type"]]:
                        errors.append(f"{gp}.icon: {gw.get('icon')!r} does not match type {gw['type']!r}")
                    _expect(errors, gw.get("label"), str, f"{gp}.label")
                    _expect(errors, gw.get("address"), (str, type(None)), f"{gp}.address")
                    if "peer" in gw:
                        if (_expect(errors, gw["peer"], (str, type(None)), f"{gp}.peer")
                                and gw["peer"] is not None
                                and gw["peer"] not in addresses and gw["peer"] not in vcn_keys):
                            errors.append(f"{gp}.peer: {gw['peer']!r} is not an address or a VCN name "
                                          f"in the model")

    if _expect(errors, model.get("services"), list, "services"):
        for ii, item in enumerate(model["services"]):
            _validate_item(errors, item, f"services[{ii}]", True, keys)
    if _expect(errors, model.get("compartments"), list, "compartments"):
        for ci, name in enumerate(model["compartments"]):
            _expect(errors, name, str, f"compartments[{ci}]")
    if _expect(errors, model.get("edges"), list, "edges"):
        for ei, edge in enumerate(model["edges"]):
            ep = f"edges[{ei}]"
            if not _expect(errors, edge, dict, ep):
                continue
            for end in ("source", "target"):
                if _expect(errors, edge.get(end), str, f"{ep}.{end}") and edge[end] not in addresses:
                    errors.append(f"{ep}.{end}: {edge[end]!r} is not an address in the model")
            _expect(errors, edge.get("label"), str, f"{ep}.label")
            if edge.get("kind") not in EDGE_KINDS:
                errors.append(f"{ep}.kind: {edge.get('kind')!r} not in {EDGE_KINDS}")
            _expect(errors, edge.get("inferred"), bool, f"{ep}.inferred")

    seen: Dict[str, int] = {}
    for addr in model_addresses(model):
        seen[addr] = seen.get(addr, 0) + 1
    for addr, n in sorted(seen.items()):
        if n > 1:
            errors.append(f"address {addr!r} appears {n} times")
    return errors


def _addr(entry) -> Optional[str]:
    """``entry["address"]`` for a dict, else None - validate_model reports the bad type itself."""
    return entry.get("address") if isinstance(entry, dict) else None


def _entries(value) -> list:
    """A list of entries; validate_model reports a bad container type itself."""
    return value if isinstance(value, list) else []


def model_addresses(model: dict) -> Iterator[str]:
    """Yield every address in the model (containers, items, gateways, hub items, DRGs)."""
    hub = model.get("hub") if isinstance(model.get("hub"), dict) else {}
    for item in _entries(hub.get("items")):
        if _addr(item):
            yield item["address"]
    for drg in _entries(model.get("drgs")):
        if _addr(drg):
            yield drg["address"]
        for att in (_entries(drg.get("attachments")) if isinstance(drg, dict) else []):
            if _addr(att):
                yield att["address"]
    for vcn in _entries(model.get("vcns")):
        if not isinstance(vcn, dict):
            continue
        if _addr(vcn):
            yield vcn["address"]
        for sn in _entries(vcn.get("subnets")):
            if not isinstance(sn, dict):
                continue
            if _addr(sn):
                yield sn["address"]
            for item in _entries(sn.get("items")):
                if _addr(item):
                    yield item["address"]
        for coll in ("services", "controls", "gateways"):
            for item in _entries(vcn.get(coll)):
                if _addr(item):
                    yield item["address"]
    for item in _entries(model.get("services")):
        if _addr(item):
            yield item["address"]


def model_is_empty(model: dict) -> bool:
    return not (model.get("vcns") or model.get("services") or model.get("hub") or model.get("drgs"))


def dedupe_edges(edges: List[dict]) -> List[dict]:
    out, seen = [], set()
    for e in edges:
        key = (e["source"], e["target"], e["label"])
        if e["source"] != e["target"] and key not in seen:
            seen.add(key)
            out.append(e)
    return out


def select_vcn(model: dict, name: str) -> bool:
    """Keep only the VCN whose name/address matches ``name``; return False when nothing matched."""
    want = (name or "").strip().lower()
    vcns = model.get("vcns") or []
    hits = [v for v in vcns if want in (v["name"].lower(), v["address"].lower())]
    if not hits:
        hits = [v for v in vcns if want and (want in v["name"].lower() or want in v["address"].lower())]
    if not hits:
        return False
    model["vcns"] = hits[:1]
    model["subject"] = hits[0]["name"]
    keep_vcn = {hits[0]["name"], hits[0]["address"]}
    for drg in model.get("drgs") or []:
        drg["attachments"] = [a for a in drg.get("attachments") or []
                              if a.get("type") != "vcn" or a.get("vcn") in keep_vcn]
    keep = set(model_addresses(model))
    for vcn in model["vcns"]:                     # a peer LPG in a dropped VCN no longer exists
        for g in vcn.get("gateways") or []:
            if g.get("peer") and g["peer"] not in keep and g["peer"] not in keep_vcn:
                g["peer"] = None
    model["edges"] = [e for e in model["edges"] if e["source"] in keep and e["target"] in keep]
    return True


# ---------------------------------------------------------------------------
# Intermediate resource representation
# ---------------------------------------------------------------------------

_INDEX_RE = re.compile(r"\[[^\]]*\]")


def base_address(address: str) -> str:
    """``module.a[0].oci_core_subnet.app["x"]`` -> ``module.a.oci_core_subnet.app``."""
    return _INDEX_RE.sub("", address or "")


def index_key(address: str) -> Optional[str]:
    m = re.search(r"\[([^\]]*)\]$", address or "")
    return m.group(1).strip().strip('"\'') if m else None


class Res:
    """One Terraform-managed resource with resolved scalar attrs and outgoing references."""

    __slots__ = ("address", "rtype", "name", "attrs", "refs")

    def __init__(self, address: str, rtype: str, name: str,
                 attrs: Optional[Dict[str, Any]] = None, refs: Optional[Dict[str, List[str]]] = None):
        self.address = address
        self.rtype = rtype
        self.name = name
        self.attrs: Dict[str, Any] = attrs or {}
        self.refs: Dict[str, List[str]] = refs or {}

    @property
    def base(self) -> str:
        return base_address(self.address)

    def label(self, default: Optional[str] = None) -> str:
        for key in ("display_name", "name", "db_name"):
            val = self.attrs.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return self.name or default or self.rtype

    def as_bool(self, key: str) -> Optional[bool]:
        return _as_bool(self.attrs.get(key))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Res({self.address!r})"


def _as_bool(value) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
    return None


def _coerce(literal: str):
    low = literal.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if re.fullmatch(r"-?\d+", low):
        return int(low)
    return literal


# ---------------------------------------------------------------------------
# HCL mode
# ---------------------------------------------------------------------------

_REF_RE = re.compile(r"(?<![\w.\-])((?:module\.[\w-]+(?:\[[^\]]*\])?\.)*)(oci_[a-z0-9_]+)\.([A-Za-z_][\w-]*)(\[[^\]]*\])?")
_MODULE_REF_RE = re.compile(r"(?<![\w.\-])module\.([\w-]+)")
_PATH_REF_RE = re.compile(r"^(var|local)\.([\w-]+)((?:\.[\w-]+|\[[^\]]+\])+)$")
_CIDRSUBNET_RE = re.compile(r"cidrsubnet\(\s*([^,()]+?)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")
_INNER_REF_RE = re.compile(r"(?<![\w.])((?:var|local)\.[\w-]+(?:\.[\w-]+|\[[^\]]+\])*)")
_MAP_ENTRY_RE = re.compile(r'^"?([\w.:/-]+)"?\s*[=:]\s*(.*)$', re.DOTALL)
_SKIP_ATTR_KEYS = frozenset({"freeform_tags", "defined_tags", "metadata", "extended_metadata", "system_tags",
                             "user_data", "ssh_authorized_keys", "depends_on", "lifecycle", "provider",
                             "ignore_changes"})


def _literal(raw: Optional[str]) -> Optional[str]:
    parsed = ds._parse_value(raw or "")
    return parsed[1] if parsed and parsed[0] == "lit" else None


def _map_entries(raw: str) -> List[Tuple[str, str]]:
    """``{ a = {...}, b = {...} }`` -> ``[("a", "{...}"), ...]``; lists yield ``("0", item)``."""
    s = (raw or "").strip()
    if s[:1] == "{" and s[-1:] == "}":
        out: List[Tuple[str, str]] = []
        for stmt in ds._split_statements(s[1:-1]):
            m = _MAP_ENTRY_RE.match(stmt.rstrip(","))
            if m:
                out.append((m.group(1), m.group(2).strip().rstrip(",")))
        return out
    if s[:1] == "[" and s[-1:] == "]":
        return [(str(i), st.rstrip(",")) for i, st in enumerate(ds._split_statements(s[1:-1]))]
    return []


def _lookup_path(raw: Optional[str], segments: List[str]) -> Optional[str]:
    """Descend into a raw HCL map/list literal following attribute / index segments."""
    cur = raw
    for seg in segments:
        if cur is None:
            return None
        entries = _map_entries(cur)
        hit = None
        for key, value in entries:
            if key.strip('"') == seg:
                hit = value
                break
        cur = hit
    return cur


def _follow(ctx: ds.TerraformContext, raw: Optional[str], depth: int = 0) -> Optional[str]:
    """Follow ``var.X`` / ``local.X`` (optionally ``.attr`` / ``["key"]`` paths) to the final raw value."""
    if raw is None or depth > 8:
        return raw
    text = raw.strip()
    parsed = ds._parse_value(text)
    if parsed and parsed[0] == "ref":
        kind, name = parsed[1], parsed[2]
        target = ctx.var_raw(name) if kind == "var" else ctx.locals.get(name)
        return _follow(ctx, target, depth + 1) if target is not None else raw
    m = _PATH_REF_RE.match(text)
    if m:
        kind, name, path = m.group(1), m.group(2), m.group(3)
        target = ctx.var_raw(name) if kind == "var" else ctx.locals.get(name)
        target = _follow(ctx, target, depth + 1)
        segments = [s.strip().strip('"\'') for s in re.findall(r'\.([\w-]+)|\[([^\]]+)\]', path) for s in s if s]
        value = _lookup_path(target, segments)
        return _follow(ctx, value, depth + 1) if value is not None else raw
    return raw


def _resolve_literal(ctx: ds.TerraformContext, raw: Optional[str]) -> Optional[str]:
    final = _follow(ctx, raw)
    return _literal(final) if final is not None else None


def _cidr_from(ctx: ds.TerraformContext, raw: Optional[str], depth: int = 0) -> Optional[str]:
    """Extract a CIDR from a raw value, following variables and evaluating ``cidrsubnet()``."""
    if raw is None or depth > 4:
        return None
    final = _follow(ctx, raw) or ""
    m = _CIDRSUBNET_RE.search(final)   # before the bare-CIDR search: the prefix argument may be a literal
    if m:
        prefix = _cidr_from(ctx, m.group(1), depth + 1)
        if prefix:
            try:
                net = ipaddress.ip_network(prefix, strict=False)
                newbits, netnum = int(m.group(2)), int(m.group(3))
                new_len = net.prefixlen + newbits
                if new_len <= net.max_prefixlen:
                    start = int(net.network_address) + netnum * (1 << (net.max_prefixlen - new_len))
                    return str(ipaddress.ip_network((start, new_len)))
            except ValueError:
                return None
    m = ds.CIDR_RE.search(final)
    if m:
        return m.group(1)
    # ``[var.vcn_cidr]`` / ``[local.cidrs["vcn"]]``: follow references embedded in a list literal.
    for inner in _INNER_REF_RE.findall(final):
        hit = _cidr_from(ctx, inner, depth + 1)
        if hit:
            return hit
    return None


def _refs_in(text: Optional[str]) -> List[str]:
    """Resource references (``TYPE.NAME`` with optional module prefix / literal index) in raw HCL."""
    out: List[str] = []
    for prefix, rtype, name, idx in _REF_RE.findall(text or ""):
        ref = f"{prefix}{rtype}.{name}"
        if idx and re.fullmatch(r'\[\s*(?:\d+|"[^"]*")\s*\]', idx):
            ref += idx.replace(" ", "")
        if ref not in out:
            out.append(ref)
    if not out:
        for mod in _MODULE_REF_RE.findall(text or ""):
            ref = f"module.{mod}"
            if ref not in out:
                out.append(ref)
    return out


def _collect_attrs(body: str) -> Dict[str, str]:
    """Depth-0 attributes plus those of nested blocks (outer wins on name clashes)."""
    attrs = ds.top_level_attrs(body)
    for _kind, _labels, sub in ds.iter_top_level_blocks(body):
        for k, v in _collect_attrs(sub).items():
            attrs.setdefault(k, v)
    return attrs


def collect_hcl_resources(ctx: ds.TerraformContext) -> List[Res]:
    """Every ``resource "oci_*" "name" {}`` block of the directory as a ``Res``."""
    out: List[Res] = []
    for _fname in sorted(ctx.tf_texts):
        for kind, labels, body in ds.iter_top_level_blocks(ctx.tf_texts[_fname]):
            if kind != "resource" or len(labels) < 2 or not labels[0].startswith("oci_"):
                continue
            rtype, name = labels[0], labels[1]
            raw_attrs = _collect_attrs(body)
            attrs: Dict[str, Any] = {}
            refs: Dict[str, List[str]] = {}
            for key, raw in raw_attrs.items():
                if key in _SKIP_ATTR_KEYS:
                    continue
                followed = _follow(ctx, raw)
                lit = _literal(followed) if followed is not None else None
                if lit is not None:
                    attrs[key] = _coerce(lit)
                found = _refs_in(followed)
                if found:
                    refs[key] = found
            cidr = _cidr_from(ctx, raw_attrs.get("cidr_block")) or _cidr_from(ctx, raw_attrs.get("cidr_blocks"))
            if cidr:
                attrs["cidr"] = cidr
            if "for_each" in raw_attrs:
                attrs["for_each"] = True
            out.append(Res(f"{rtype}.{name}", rtype, name, attrs, refs))
    return out


def _loose_subnets(vcn_address: str, body_attrs: Dict[str, str]) -> List[dict]:
    subnets: List[dict] = []
    for key, value in body_attrs.items():
        if "subnet" not in key.lower() or (value or "").lstrip()[:1] not in "{[":
            continue
        for skey, sbody in _map_entries(value):
            if sbody.lstrip()[:1] != "{":
                continue
            sattrs = ds.top_level_attrs(sbody.strip()[1:-1])
            sname = _literal(sattrs.get("display_name")) or _literal(sattrs.get("name")) or skey
            cm = ds.CIDR_RE.search(sbody)
            prohibit = _as_bool(_literal(sattrs.get("prohibit_public_ip_on_vnic")))
            public: Optional[bool] = None if prohibit is None else not prohibit
            if public is None:
                for k in ("is_public", "public"):
                    b = _as_bool(_literal(sattrs.get(k)))
                    if b is not None:
                        public = b
                        break
            if public is None:
                b = _as_bool(_literal(sattrs.get("private") or sattrs.get("is_private")))
                if b is not None:
                    public = not b
            if public is None:
                t = (_literal(sattrs.get("type")) or "").lower()
                if t in ("public", "private"):
                    public = t == "public"
            subnets.append(new_subnet(sname, f"{vcn_address}.{skey}", cm.group(1) if cm else None,
                                      public=public if public is not None else infer_public(sname)))
    return subnets


def loose_vcn_models(ctx: ds.TerraformContext) -> List[dict]:
    """VCNs (with subnets) from tfvars maps such as ``vcns = { hub = { cidr = ..., subnets = {...} } }``."""
    vcns: List[dict] = []
    seen = set()
    for source, origin in ((ctx.tfvars, "tfvars"), (ctx.extra_tfvars, "tfvars"), (ctx.var_defaults, "var")):
        for key in sorted(source):
            if "vcn" not in key.lower():
                continue
            raw = (source[key] or "").strip()
            if raw[:1] not in "{[":
                continue
            entries = [(k, v) for k, v in _map_entries(raw) if v.lstrip()[:1] == "{"]
            candidates = entries if entries else [(key, raw)]
            for ekey, ebody in candidates:
                body_attrs = ds.top_level_attrs(ebody.strip()[1:-1])
                name = (_literal(body_attrs.get("display_name")) or _literal(body_attrs.get("vcn_name"))
                        or _literal(body_attrs.get("name")))
                cm = ds._LOOSE_CIDR_RE.search(ebody)
                cidr = cm.group(1) if cm else None
                address = f"{origin}.{key}.{ekey}" if entries else f"{origin}.{key}"
                subnets = _loose_subnets(address, body_attrs)
                if name is None and cidr is None and not subnets:
                    continue
                marker = (name or ekey, cidr)
                if marker in seen:
                    continue
                seen.add(marker)
                vcn = new_vcn(name or ekey, address, cidr)
                vcn["subnets"] = subnets
                vcns.append(vcn)
    return vcns


def _hcl_region(ctx: ds.TerraformContext) -> Optional[str]:
    return ctx.provider_settings().get("region")


# ---------------------------------------------------------------------------
# Plan / state JSON mode (``terraform show -json``)
# ---------------------------------------------------------------------------

class InputError(Exception):
    """Unreadable or malformed input file."""


def load_show_json(path) -> dict:
    p = Path(path)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InputError(f"cannot read {p}: {exc}") from exc
    if not isinstance(doc, dict):
        raise InputError(f"{p}: expected a JSON object from 'terraform show -json'")
    return doc


def _flatten_values(values: dict, out: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = {} if out is None else out
    for key, val in (values or {}).items():
        if key in _SKIP_ATTR_KEYS:
            continue
        if isinstance(val, dict):
            _flatten_values(val, out)
        elif isinstance(val, list):
            if val and all(isinstance(v, dict) for v in val):
                for v in val:
                    _flatten_values(v, out)
            else:
                out.setdefault(key, val)
        else:
            out.setdefault(key, val)
    return out


def _iter_strings(value) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            if isinstance(v, str):
                yield v


def _normalise_config_ref(ref: str) -> Optional[str]:
    """``oci_core_subnet.app[0].id`` -> ``oci_core_subnet.app[0]``; drops var/local/each/count/data refs."""
    m = _REF_RE.match(ref.strip())
    if not m:
        return None
    prefix, rtype, name, idx = m.groups()
    out = f"{prefix}{rtype}.{name}"
    if idx and re.fullmatch(r'\[\s*(?:\d+|"[^"]*")\s*\]', idx):
        out += idx.replace(" ", "")
    return out


def _refs_from_expr(expr, out: Optional[List[str]] = None) -> List[str]:
    out = [] if out is None else out
    if isinstance(expr, dict):
        for ref in expr.get("references") or []:
            if isinstance(ref, str) and ref not in out:
                out.append(ref)
        for key, val in expr.items():
            if key != "references":
                _refs_from_expr(val, out)
    elif isinstance(expr, list):
        for val in expr:
            _refs_from_expr(val, out)
    return out


def _walk_expressions(expressions, out: Dict[str, List[str]]) -> None:
    for key, val in (expressions or {}).items():
        if isinstance(val, dict) and ("references" in val or "constant_value" in val):
            refs = [r for r in val.get("references") or [] if isinstance(r, str)]
            if refs:
                out.setdefault(key, [])
                out[key].extend(r for r in refs if r not in out[key])
        elif isinstance(val, list):
            for block in val:
                if isinstance(block, dict):
                    _walk_expressions(block, out)
        elif isinstance(val, dict):
            _walk_expressions(val, out)


def _configuration_refs(config: dict) -> Dict[str, Dict[str, List[str]]]:
    """``{config_address: {attr: [qualified base refs]}}`` from ``configuration.root_module``."""
    module_outputs: Dict[str, Dict[str, List[str]]] = {}

    def collect_outputs(mod: dict, prefix: str) -> None:
        outs: Dict[str, List[str]] = {}
        for name, o in (mod.get("outputs") or {}).items():
            outs[name] = _refs_from_expr((o or {}).get("expression") or {})
        module_outputs[prefix] = outs
        for name, call in (mod.get("module_calls") or {}).items():
            collect_outputs((call or {}).get("module") or {}, f"{prefix}module.{name}.")

    def qualify(ref: str, prefix: str, depth: int = 0) -> List[str]:
        mm = re.match(r"^module\.([\w-]+)(?:\[[^\]]*\])?\.([\w-]+)", ref.strip())
        if mm and depth < 2:
            sub_prefix = f"{prefix}module.{mm.group(1)}."
            out: List[str] = []
            for inner in module_outputs.get(sub_prefix, {}).get(mm.group(2), []):
                out.extend(qualify(inner, sub_prefix, depth + 1))
            return out
        norm = _normalise_config_ref(ref)
        return [prefix + norm] if norm else []

    result: Dict[str, Dict[str, List[str]]] = {}

    def collect_resources(mod: dict, prefix: str) -> None:
        for r in mod.get("resources") or []:
            raw: Dict[str, List[str]] = {}
            _walk_expressions(r.get("expressions") or {}, raw)
            qualified: Dict[str, List[str]] = {}
            for attr, refs in raw.items():
                vals: List[str] = []
                for ref in refs:
                    for q in qualify(ref, prefix):
                        if q not in vals:
                            vals.append(q)
                if vals:
                    qualified[attr] = vals
            result[prefix + r.get("address", "")] = qualified
        for name, call in (mod.get("module_calls") or {}).items():
            collect_resources((call or {}).get("module") or {}, f"{prefix}module.{name}.")

    root = (config or {}).get("root_module") or {}
    collect_outputs(root, "")
    collect_resources(root, "")
    return result


def collect_json_resources(doc: dict) -> List[Res]:
    """Resources from ``planned_values`` (plan) or ``values`` (state), with OCID and configuration refs."""
    values = doc.get("planned_values") or doc.get("values") or {}
    resources: List[Res] = []

    def walk(mod: dict) -> None:
        for r in mod.get("resources") or []:
            if not isinstance(r, dict) or r.get("mode", "managed") != "managed":
                continue
            rtype = r.get("type") or ""
            if not rtype.startswith("oci_") or not r.get("address"):
                continue
            attrs = _flatten_values(r.get("values") or {})
            if isinstance(attrs.get("cidr_block"), str):
                attrs["cidr"] = attrs["cidr_block"]
            elif isinstance(attrs.get("cidr_blocks"), list) and attrs["cidr_blocks"]:
                first = attrs["cidr_blocks"][0]
                if isinstance(first, str):
                    attrs["cidr"] = first
            resources.append(Res(r["address"], rtype, r.get("name") or "", attrs, {}))
        for child in mod.get("child_modules") or []:
            if isinstance(child, dict):
                walk(child)

    walk(values.get("root_module") or {})

    ocids: Dict[str, str] = {}
    for r in resources:
        rid = r.attrs.get("id")
        if isinstance(rid, str) and rid.startswith("ocid1."):
            ocids.setdefault(rid, r.address)

    config_refs = _configuration_refs(doc.get("configuration") or {})
    for r in resources:
        refs: Dict[str, List[str]] = {}
        for key, val in r.attrs.items():
            if key == "id":
                continue
            for s in _iter_strings(val):
                target = ocids.get(s)
                if target and target != r.address:
                    refs.setdefault(key, [])
                    if target not in refs[key]:
                        refs[key].append(target)
        for key, lst in config_refs.get(r.base, {}).items():
            refs.setdefault(key, [])
            refs[key].extend(x for x in lst if x not in refs[key])
        r.refs = refs
    return resources


def _json_region(doc: dict) -> Optional[str]:
    prov = ((doc.get("configuration") or {}).get("provider_config") or {}).get("oci") or {}
    expr = (prov.get("expressions") or {}).get("region") or {}
    const = expr.get("constant_value")
    if isinstance(const, str) and const.strip():
        return const.strip()
    for ref in expr.get("references") or []:
        m = re.match(r"^var\.([\w-]+)$", str(ref))
        if m:
            val = ((doc.get("variables") or {}).get(m.group(1)) or {}).get("value")
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


# ---------------------------------------------------------------------------
# Model builder (shared by HCL and JSON modes)
# ---------------------------------------------------------------------------

def _with_regional(item: dict) -> dict:
    """Schema 2: every ``model['services']`` entry carries the ``regional`` flag."""
    if isinstance(item, dict):
        item.setdefault("regional", is_regional_type(str(item.get("type") or "")))
    return item


class ModelBuilder:
    """Turn a list of ``Res`` into the MODEL dict."""

    def __init__(self, resources: List[Res], subject_hint: str, region: Optional[str] = None,
                 source_mode: str = "hcl", source_path: Optional[str] = None,
                 inferred_edges: bool = True, loose_vcns: Optional[List[dict]] = None):
        self.resources = list(resources)   # definition order (deterministic: files sorted, blocks in order)
        self.subject_hint = subject_hint
        self.inferred_edges = inferred_edges
        self.loose_vcns = loose_vcns or []
        self.model = new_model(subject_hint, region, source_mode, source_path)
        self.by_address: Dict[str, Res] = {r.address: r for r in self.resources}
        self.by_base: Dict[str, List[Res]] = {}
        for r in self.resources:
            self.by_base.setdefault(r.base, []).append(r)
        self.compartment_names: Dict[str, str] = {}
        self.vcn_by_addr: Dict[str, dict] = {}
        self.subnet_by_addr: Dict[str, dict] = {}
        self.subnet_vcn: Dict[str, str] = {}
        self.item_place: Dict[str, Tuple[str, Optional[str]]] = {}   # item address -> (vcn addr, subnet addr)
        self.item_type: Dict[str, str] = {}
        self.item_index: Dict[str, dict] = {}
        self.hub_items: List[dict] = []
        self.drg_by_addr: Dict[str, dict] = {}
        # (attachment, VCN, label-is-derived) triples: the VCN name is snapshotted only in
        # _finish(), because _merge_loose() can still rename or drop a for_each placeholder VCN.
        self.att_vcns: List[Tuple[dict, dict, bool]] = []
        self.explicit_lb_targets: Dict[str, bool] = {}

    # -- reference resolution ------------------------------------------------
    def resolve_ref(self, ref: str, from_res: Optional[Res] = None) -> Optional[Res]:
        if ref in self.by_address:
            return self.by_address[ref]
        cands = self.by_base.get(base_address(ref)) or []
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        want = index_key(ref)
        if want is not None:
            for c in cands:
                if index_key(c.address) == want:
                    return c
        if from_res is not None:
            mine = index_key(from_res.address)
            for c in cands:
                if index_key(c.address) == mine:
                    return c
        return cands[0]

    def first_ref(self, res: Res, attrs: Iterable[str], rtype: Optional[str] = None,
                  rtypes: Optional[frozenset] = None) -> Optional[Res]:
        for attr in attrs:
            for ref in res.refs.get(attr, []):
                hit = self.resolve_ref(ref, res)
                if hit is None:
                    continue
                if rtype is not None and hit.rtype != rtype:
                    continue
                if rtypes is not None and hit.rtype not in rtypes:
                    continue
                return hit
        return None

    def all_refs(self, res: Res, attrs: Iterable[str], rtypes: Optional[frozenset] = None) -> List[Res]:
        out: List[Res] = []
        for attr in attrs:
            for ref in res.refs.get(attr, []):
                hit = self.resolve_ref(ref, res)
                if hit is not None and (rtypes is None or hit.rtype in rtypes) and hit not in out:
                    out.append(hit)
        return out

    def _compartment_name(self, res: Res) -> Optional[str]:
        comp = self.first_ref(res, ("compartment_id",), COMPARTMENT_TYPE)
        if comp is not None:
            return self.compartment_names.get(comp.address)
        return None

    # -- containers ------------------------------------------------------------
    def _vcn_for(self, res: Res, attrs: Iterable[str] = ("vcn_id",)) -> Optional[dict]:
        vcn = self.first_ref(res, attrs, VCN_TYPE)
        if vcn is not None and vcn.address in self.vcn_by_addr:
            return self.vcn_by_addr[vcn.address]
        for attr in attrs:
            for ref in res.refs.get(attr, []):
                if ref in self.vcn_by_addr:
                    return self.vcn_by_addr[ref]
        return None

    def _placeholder_vcn(self, ref: Optional[str]) -> dict:
        address = ref or "vcn"
        if address not in self.vcn_by_addr:
            vcn = new_vcn(ref or "VCN", address)
            vcn["_unresolved"] = True
            self.vcn_by_addr[address] = vcn
            self.model["vcns"].append(vcn)
        return self.vcn_by_addr[address]

    def _single_vcn(self) -> Optional[dict]:
        return self.model["vcns"][0] if len(self.model["vcns"]) == 1 else None

    def _vcn_or_single(self, res: Res, attrs: Iterable[str] = ("vcn_id",)) -> Optional[dict]:
        return self._vcn_for(res, attrs) or self._single_vcn()

    def _build_compartments(self) -> None:
        for r in self.resources:
            if r.rtype == COMPARTMENT_TYPE:
                name = r.attrs.get("name") if isinstance(r.attrs.get("name"), str) else r.name
                self.compartment_names[r.address] = name
                if name not in self.model["compartments"]:
                    self.model["compartments"].append(name)

    def _build_vcns(self) -> None:
        for r in self.resources:
            if r.rtype != VCN_TYPE:
                continue
            resolved = isinstance(r.attrs.get("display_name"), str)
            vcn = new_vcn(r.label(), r.address, r.attrs.get("cidr") if isinstance(r.attrs.get("cidr"), str) else None,
                          self._compartment_name(r))
            if not resolved:
                vcn["_unresolved"] = True
                if r.attrs.get("for_each") or isinstance(r.attrs.get("count"), int) or index_key(r.address):
                    vcn["_dynamic"] = True
            self.vcn_by_addr[r.address] = vcn
            self.model["vcns"].append(vcn)

    def _build_subnets(self) -> None:
        for r in self.resources:
            if r.rtype != SUBNET_TYPE:
                continue
            vcn = self._vcn_for(r)
            if vcn is None:
                vcn = self._single_vcn()
            if vcn is None:
                refs = r.refs.get("vcn_id") or []
                vcn = self._placeholder_vcn(refs[0] if refs else None)
            name = r.label()
            prohibit = r.as_bool("prohibit_public_ip_on_vnic")
            subnet = new_subnet(name, r.address,
                                r.attrs.get("cidr") if isinstance(r.attrs.get("cidr"), str) else None,
                                public=infer_public(name, prohibit), tier=infer_tier(name))
            if not isinstance(r.attrs.get("display_name"), str):
                subnet["_unresolved"] = True
            rt = self.first_ref(r, ("route_table_id",), rtypes=ROUTE_TABLE_TYPES)
            if rt is not None:
                subnet["route_table"] = self._badge_ref(rt, "Route table")
            subnet["security_lists"] = [self._badge_ref(sl, "Security list") for sl in
                                        self.all_refs(r, ("security_list_ids",), SECURITY_LIST_TYPES)]
            vcn["subnets"].append(subnet)
            self.subnet_by_addr[r.address] = subnet
            self.subnet_vcn[r.address] = vcn["address"]

    def _build_gateways(self) -> None:
        lpgs: Dict[str, dict] = {}
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
                lpgs[r.address] = gw
            vcn["gateways"].append(gw)
        self._mirror_lpg_peers(lpgs)

    @staticmethod
    def _mirror_lpg_peers(lpgs: Dict[str, dict]) -> None:
        """Give the acceptor LPG of a pair the peer its requestor declares.

        Local peering is symmetric, but only one side carries ``peer_id`` - in
        Terraform by convention and in the OCI API until the peering request is
        accepted. Without the mirror the acceptor has ``peer: None``, so the
        layout puts it on the VCN's bottom border instead of the border facing
        its peer and the ``Local Peering`` connector runs along the peer VCN's
        side border.
        """
        for address, gw in lpgs.items():
            acceptor = lpgs.get(str(gw.get("peer") or ""))
            if acceptor is not None and not acceptor.get("peer"):
                acceptor["peer"] = address

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
            default = f"VCN attachment\n{vcn['name']}"
            label = att.label(default)
            self._add_vcn_attachment(self.drg_by_addr[drg.address],
                                     new_attachment("vcn", att.address, label, vcn=vcn["name"]),
                                     vcn, label == default)
        for drg in drgs:
            entry = self.drg_by_addr[drg.address]
            vcn = self._single_vcn()
            if not entry["attachments"] and vcn is not None:
                self._add_vcn_attachment(entry, new_attachment(
                    "vcn", f"{drg.address}@{vcn['address']}", f"VCN attachment\n{vcn['name']}",
                    vcn=vcn["name"]), vcn, True)

    def _add_vcn_attachment(self, drg: dict, att: dict, vcn: dict, derived_label: bool) -> None:
        """Append a VCN attachment and remember the VCN dict for the final name resolution."""
        drg["attachments"].append(att)
        self.att_vcns.append((att, vcn, derived_label))

    def _build_hub(self) -> None:
        onprem = 0
        for r in self.resources:
            if r.rtype not in HUB_TYPES:
                continue
            if r.rtype == "oci_core_ipsec" and any(x.rtype == "oci_core_cpe" for x in self.resources):
                continue  # the CPE resource already draws the on-prem endpoint
            icon, default = RESOURCE_ICONS[r.rtype]
            if r.rtype != "oci_core_remote_peering_connection":
                onprem += 1
            self.hub_items.append(new_hub_item(icon, r.label(default), r.rtype, r.address))
        if not self.hub_items:
            return
        self.model["hub"] = {"name": "On-premises" if onprem else "Remote region",
                             "items": self.hub_items, "link_label": None}

    def _build_drg_links(self) -> None:
        """IPSec / FastConnect / RPC resources referencing a DRG become typed attachments.

        An IPSec connection and a remote peering connection always name a DRG
        (``drg_id`` is required), so an unresolvable reference may fall back to
        the tenancy's only DRG. A **public** virtual circuit peers with Oracle's
        public services and has no DRG at all (the provider docs: "Private
        virtual circuits require a dynamic routing gateway (DRG) ID, while
        public virtual circuits allow customers to advertise specific public IP
        prefixes"), so it never becomes an attachment - it stays an
        on-premises item with no connector to the DRG.
        """
        hub_addresses = {h["address"] for h in self.hub_items}
        for r in self.resources:
            if r.rtype == "oci_core_ipsec":
                cpe = self.first_ref(r, ("cpe_id",), "oci_core_cpe")
                atype, attrs, target, default = ("ipsec", ("drg_id",),
                                                cpe.address if cpe is not None else r.address, "IPSec VPN")
            elif r.rtype == "oci_core_virtual_circuit":
                if str(r.attrs.get("type") or "").strip().upper() == "PUBLIC":
                    continue
                atype, attrs, target, default = "virtual_circuit", ("gateway_id",), r.address, "FastConnect"
            elif r.rtype == "oci_core_remote_peering_connection":
                atype, attrs, target, default = "rpc", ("drg_id",), r.address, "Remote peering"
            else:
                continue
            drg = self.first_ref(r, attrs, DRG_TYPE)
            if drg is not None:
                addr = drg.address
            elif len(self.drg_by_addr) == 1:
                addr = next(iter(self.drg_by_addr))
            else:
                continue
            self.drg_by_addr[addr]["attachments"].append(new_attachment(
                atype, f"{r.address}@{addr}", r.label(default), target=target if target in hub_addresses else None))

    # -- items -------------------------------------------------------------------
    def _item_for(self, r: Res) -> Optional[dict]:
        hit = icon_for_type(r.rtype)
        if hit is None:
            return None
        icon, default = hit
        label = r.label(default)
        if r.rtype == "oci_containerengine_node_pool" and not isinstance(r.attrs.get("display_name"), str) \
                and not isinstance(r.attrs.get("name"), str):
            label = "Node pool"
        shape = r.attrs.get("shape") or r.attrs.get("shape_name")
        if r.rtype in SHAPE_LABEL_TYPES and isinstance(shape, str) and shape.strip():
            label = f"{label}\n{shape.strip()}"
        metadata = {k: r.attrs[k] for k in METADATA_KEYS
                    if k in r.attrs and isinstance(r.attrs[k], (str, int, float, bool))}
        return new_item(icon, label, r.rtype, r.address, metadata)

    def _badge_ref(self, res: Res, default: str) -> dict:
        return badge_ref(res.label(default), res.address)

    def _nsg_refs(self, res: Res) -> List[dict]:
        return [self._badge_ref(n, "NSG") for n in self.all_refs(res, NSG_ATTRS, frozenset({NSG_TYPE}))]

    def _skip_as_item(self, r: Res) -> bool:
        return (r.rtype in (VCN_TYPE, SUBNET_TYPE, COMPARTMENT_TYPE, DRG_TYPE, DRG_ATTACHMENT_TYPE)
                or r.rtype in GATEWAY_TYPES or r.rtype in HUB_TYPES or r.rtype in LB_CHILD_TYPES)

    def _vcn_by_compartment(self, r: Res) -> Optional[dict]:
        refs = r.refs.get("compartment_id") or []
        if not refs:
            return None
        hits = []
        for vcn_res in self.resources:
            if vcn_res.rtype == VCN_TYPE and (vcn_res.refs.get("compartment_id") or [])[:1] == refs[:1]:
                hits.append(vcn_res.address)
        return self.vcn_by_addr.get(hits[0]) if len(hits) == 1 else None

    def _build_items(self) -> None:
        for r in self.resources:
            if self._skip_as_item(r):
                continue
            item = self._item_for(r)
            if item is None:
                continue
            nsgs = self._nsg_refs(r)
            if nsgs:
                item["nsgs"] = nsgs
            subnet = self.first_ref(r, SUBNET_ATTRS, SUBNET_TYPE)
            if subnet is not None and subnet.address in self.subnet_by_addr:
                self.subnet_by_addr[subnet.address]["items"].append(item)
                self._register(item, r, self.subnet_vcn[subnet.address], subnet.address)
                continue
            vcn = (self._vcn_for(r, ("vcn_id", "vcn_ids", "manage_default_resource_id"))
                   or self._vcn_by_compartment(r) or self._single_vcn())
            if r.rtype in CONTROL_TYPES:
                if vcn is not None:
                    vcn["controls"].append(item)
                    self._register(item, r, vcn["address"], None)
                continue
            item["regional"] = is_regional_type(r.rtype)
            if vcn is not None:
                vcn["services"].append(item)
                self._register(item, r, vcn["address"], None)
            else:
                self.model["services"].append(item)
                self._register(item, r, "", None)

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

    def _register(self, item: dict, r: Res, vcn_addr: str, subnet_addr: Optional[str]) -> None:
        self.item_place[item["address"]] = (vcn_addr, subnet_addr)
        self.item_type[item["address"]] = r.rtype
        self.item_index[item["address"]] = item

    # -- edges ---------------------------------------------------------------------
    def _listener_ports(self, lb_address: str) -> List[str]:
        ports: List[str] = []
        for r in self.resources:
            if r.rtype not in LB_LISTENER_TYPES:
                continue
            lb = self.first_ref(r, ("load_balancer_id", "network_load_balancer_id"), rtypes=LB_TYPES)
            if lb is not None and lb.address == lb_address and r.attrs.get("port") is not None:
                port = str(r.attrs["port"])
                if port not in ports:
                    ports.append(port)
        return ports

    def _build_edges(self) -> None:
        edges: List[dict] = []
        # explicit LB backends -> compute
        for r in self.resources:
            if r.rtype not in LB_BACKEND_TYPES:
                continue
            lb = self.first_ref(r, ("load_balancer_id", "network_load_balancer_id"), rtypes=LB_TYPES)
            if lb is None or lb.address not in self.item_index:
                continue
            targets = self.all_refs(r, ("ip_address", "target_id"))
            for t in targets:
                if t.address in self.item_index:
                    port = r.attrs.get("port")
                    edges.append(new_edge(lb.address, t.address, str(port) if port is not None else "", "data", False))
                    self.explicit_lb_targets[lb.address] = True
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
        if self.inferred_edges:
            edges.extend(self._heuristic_edges())
        self.model["edges"] = dedupe_edges(edges)

    def _items_in_vcn(self, vcn_addr: str, rtypes: frozenset, tiers: Optional[Iterable[str]] = None,
                      exclude_subnet: Optional[str] = None) -> List[str]:
        out: List[str] = []
        for addr, (v_addr, s_addr) in self.item_place.items():
            if v_addr != vcn_addr or self.item_type.get(addr) not in rtypes:
                continue
            if tiers is not None:
                if s_addr is None or s_addr == exclude_subnet:
                    continue
                subnet = self.subnet_by_addr.get(s_addr)
                if subnet is None:
                    continue
                if subnet["tier"] not in tiers and "web" not in _tokens(subnet["name"]):
                    continue
            out.append(addr)
        return out

    def _heuristic_edges(self) -> List[dict]:
        edges: List[dict] = []
        db_types = frozenset(DB_PORTS)
        for addr, (vcn_addr, subnet_addr) in self.item_place.items():
            rtype = self.item_type[addr]
            if rtype in LB_TYPES and not self.explicit_lb_targets.get(addr) and vcn_addr:
                ports = self._listener_ports(addr)
                label = "/".join(ports) if ports else "HTTP(S)"
                for target in self._items_in_vcn(vcn_addr, COMPUTE_TYPES, ("app",), exclude_subnet=subnet_addr):
                    edges.append(new_edge(addr, target, label, "data", True))
            elif rtype in COMPUTE_TYPES and vcn_addr and subnet_addr:
                subnet = self.subnet_by_addr.get(subnet_addr)
                if subnet is None or subnet["tier"] not in ("app", "compute"):
                    continue
                for target in self._items_in_vcn(vcn_addr, db_types):
                    t_subnet = self.item_place[target][1]
                    if t_subnet is not None and self.subnet_by_addr[t_subnet]["tier"] not in ("data", "other"):
                        continue
                    edges.append(new_edge(addr, target, DB_PORTS[self.item_type[target]], "data", True))
        return edges

    # -- loose tfvars VCNs -----------------------------------------------------------
    def _merge_loose(self) -> None:
        if not self.loose_vcns:
            return
        by_name = {v["name"].lower(): v for v in self.model["vcns"] if not v.get("_unresolved")}
        placeholders = [v for v in self.model["vcns"] if v.get("_unresolved") and v.get("_dynamic")]
        appended = False
        for loose in self.loose_vcns:
            target = by_name.get(loose["name"].lower())
            if target is None and len(placeholders) == 1 and len(self.loose_vcns) == 1:
                target = placeholders[0]
                target["name"] = loose["name"]
                target.pop("_unresolved", None)
                target.pop("_dynamic", None)
                target["subnets"] = [s for s in target["subnets"] if not s.get("_unresolved")]
                placeholders = []
            if target is None:
                self.model["vcns"].append(loose)
                appended = True
                continue
            target["cidr"] = target["cidr"] or loose["cidr"]
            existing = {s["name"].lower() for s in target["subnets"]}
            for sn in loose["subnets"]:
                if sn["name"].lower() not in existing:
                    target["subnets"].append(sn)
        if appended and placeholders:
            # A for_each-driven VCN resource whose names live in tfvars: drop the placeholder,
            # keep its non-dynamic content elsewhere.
            for ph in placeholders:
                self.model["vcns"].remove(ph)
                for sn in ph["subnets"]:
                    self.model["services"].extend(_with_regional(it) for it in sn["items"])
                self.model["services"].extend(_with_regional(it) for it in ph["services"])
            keep = set(model_addresses(self.model))
            self.model["edges"] = [e for e in self.model["edges"] if e["source"] in keep and e["target"] in keep]

    # -- finish ------------------------------------------------------------------------
    def _resolve_attachment_vcns(self) -> None:
        """Snapshot each VCN attachment's VCN name now that ``_merge_loose()`` has run.

        ``_build_drgs()`` runs before the tfvars merge, so a ``for_each`` placeholder VCN may
        since have been renamed from its resource key to its tfvars ``display_name`` - or dropped
        altogether. Attachments whose VCN is gone are dropped with it.
        """
        if not self.att_vcns:
            return
        live = {id(v) for v in self.model["vcns"]}
        by_att = {id(att): (vcn, derived) for att, vcn, derived in self.att_vcns}
        for drg in self.model["drgs"]:
            kept = []
            for att in drg["attachments"]:
                hit = by_att.get(id(att))
                if hit is None:
                    kept.append(att)
                    continue
                vcn, derived = hit
                if id(vcn) not in live:
                    continue
                att["vcn"] = vcn["name"]
                if derived:
                    att["label"] = f"VCN attachment\n{vcn['name']}"
                kept.append(att)
            drg["attachments"] = kept

    def _finish(self) -> None:
        self._resolve_attachment_vcns()
        for vcn in self.model["vcns"]:
            vcn.pop("_unresolved", None)
            vcn.pop("_dynamic", None)
            for sn in vcn["subnets"]:
                sn.pop("_unresolved", None)
        if len(self.model["vcns"]) == 1:
            self.model["subject"] = self.model["vcns"][0]["name"]
        if self.model["compartments"] and self.model["compartment"] is None:
            self.model["compartment"] = self.model["compartments"][0]

    def build(self) -> dict:
        self._build_compartments()
        self._build_vcns()
        self._build_subnets()
        self._build_gateways()
        self._build_drgs()
        self._build_hub()
        self._build_drg_links()
        self._build_items()
        self._build_vnic_nsgs()
        self._build_edges()
        self._merge_loose()
        self._finish()
        return self.model


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def parse_terraform_dir(tf_dir, inferred_edges: bool = True) -> dict:
    """Build the MODEL from the ``*.tf`` / tfvars files directly inside ``tf_dir``."""
    tf_dir = Path(tf_dir)
    ctx = ds.TerraformContext(tf_dir)
    resources = collect_hcl_resources(ctx)
    loose = loose_vcn_models(ctx)
    builder = ModelBuilder(resources, tf_dir.resolve().name or "OCI Architecture", _hcl_region(ctx),
                           "hcl", str(tf_dir), inferred_edges, loose)
    return builder.build()


def parse_show_json(path, mode: Optional[str] = None, tf_dir=None, inferred_edges: bool = True) -> dict:
    """Build the MODEL from ``terraform show -json`` output (plan or state)."""
    doc = load_show_json(path)
    if mode is None:
        mode = "plan" if "planned_values" in doc else "state"
    resources = collect_json_resources(doc)
    region = _json_region(doc)
    subject = Path(path).stem
    if tf_dir is not None:
        ctx = ds.TerraformContext(Path(tf_dir))
        region = region or _hcl_region(ctx)
        subject = Path(tf_dir).resolve().name or subject
    builder = ModelBuilder(resources, subject, region, mode, str(path), inferred_edges)
    return builder.build()


def _builder_icon_keys() -> Optional[set]:
    try:
        import drawio_builder  # noqa: WPS433 - optional, same directory
    except Exception:  # noqa: BLE001 - icon check is best effort
        return None
    keys = set(getattr(drawio_builder, "ICON_MAP", {}) or {})
    keys.update(getattr(drawio_builder, "ICON_ALIASES", {}) or {})
    return keys or None


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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="parse_terraform.py",
        description="Normalise OCI Terraform (HCL directory, plan JSON or state JSON) into the diagram MODEL.",
        epilog="Exit codes: 0 success, 1 nothing recognisable, 2 bad path / unreadable input.",
    )
    parser.add_argument("tf_dir", nargs="?", help="Terraform directory (default: auto-detect, else '.')")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--plan-json", metavar="FILE", help="'terraform show -json tfplan' output")
    group.add_argument("--state-json", metavar="FILE", help="'terraform show -json' state output")
    parser.add_argument("--vcn", metavar="NAME", help="keep only this VCN (name or address)")
    parser.add_argument("--out", metavar="FILE", help="write the model JSON here instead of stdout")
    parser.add_argument("--no-inferred-edges", action="store_true",
                        help="emit only edges backed by explicit references")
    args = parser.parse_args(argv)

    tf_dir: Optional[Path] = None
    if args.tf_dir is not None:
        tf_dir = Path(args.tf_dir).expanduser()
        if not tf_dir.is_dir():
            print(f"Error: Terraform directory does not exist: {args.tf_dir}", file=sys.stderr)
            return 2
    json_path = args.plan_json or args.state_json
    if json_path is not None and not Path(json_path).expanduser().is_file():
        print(f"Error: JSON file does not exist: {json_path}", file=sys.stderr)
        return 2

    inferred = not args.no_inferred_edges
    try:
        if json_path is not None:
            mode = "plan" if args.plan_json else "state"
            model = parse_show_json(Path(json_path).expanduser(), mode, tf_dir, inferred)
        else:
            if tf_dir is None:
                tf_dir = ds.find_terraform_dir() or Path(".")
            model = parse_terraform_dir(tf_dir, inferred)
    except InputError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if model_is_empty(model):
        where = json_path or str(tf_dir)
        print(f"No OCI resources recognised in {where}.", file=sys.stderr)
        return 1
    if args.vcn and not select_vcn(model, args.vcn):
        names = ", ".join(v["name"] for v in model["vcns"]) or "none"
        print(f"No VCN matches {args.vcn!r}. Available: {names}", file=sys.stderr)
        return 1

    problems = validate_model(model, _builder_icon_keys())
    if problems:
        print("Model failed schema validation:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    text = json.dumps(model, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).expanduser().write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    print(summarise(model), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
