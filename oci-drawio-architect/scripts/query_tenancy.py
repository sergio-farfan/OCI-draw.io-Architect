#!/usr/bin/env python3
"""EXPERIMENTAL - build the diagram MODEL from a live OCI tenancy ("as-built" mode).

Status
------
This script has been exercised ONLY against the hand-written fixture JSON under
``tests/fixtures/tenancy/``; it has not yet been run against a live tenancy.  The
CLI response shapes it expects are documented below - if a real response differs,
save it with ``--save-raw`` and adjust ``normalise_entity()``.  Treat live-mode
output as a starting point to review, not as an authoritative inventory.

Sources (OCI CLI via subprocess, ``--output json``, 30 s timeout per call)
---------------------------------------------------------------------------
* ``oci network vcn-topology get --compartment-id C --vcn-id V`` (when ``--vcn-id`` is given)
* ``oci network networking-topology get --compartment-id C``
* ``oci search resource structured-search --query-text "query all resources where compartmentId = 'C'"``

Topology responses look like ``{"data": {"type": "VCN"|"NETWORKING", "entities": [...],
"relationships": [...]}}``.  Each entity is the resource JSON (``id``,
``display-name``/``displayName``, ``cidr-block``, ``subnet-id``, ``vcn-id`` ...);
its kind comes from an explicit ``type`` key when present (``Vcn``, ``Subnet``,
``Instance``, ``InternetGateway``, ``Drg`` ...) and otherwise from the OCID
(``ocid1.natgateway.`` -> NAT gateway).  Relationships are
``{"type": "CONTAINS"|"ASSOCIATED_WITH"|"ROUTES_TO", "id1": ..., "id2": ...}``.
Search responses look like ``{"data": {"items": [{"resource-type": "Bucket",
"identifier": "ocid1...", "display-name": ..., "lifecycle-state": ...}]}}``.  Both
kebab-case and camelCase keys are accepted everywhere.

``--from-json FILE`` bypasses the CLI.  The file may be one response or a bundle
``{"vcn_topology": ..., "networking_topology": ..., "search": ...}`` such as the one
``--save-raw FILE`` writes.

Output: the same MODEL schema as ``parse_terraform.py`` (``source.mode = "tenancy"``);
OCIDs are the item addresses.  Everything is delegated to
``parse_terraform.ModelBuilder`` after entities are converted to its resource
representation, so placement and edge rules are identical to Terraform mode.
Additional edges come from ``ROUTES_TO`` relationships (subnet -> gateway); DRGs and their
attachments are reported in ``drgs[]`` (schema 2), the hub holds the on-premises side only.
Subnet ``routeTableId`` / ``securityListIds`` and VNIC / load balancer ``nsgIds`` /
``networkSecurityGroupIds`` become the badge fields ``route_table``, ``security_lists`` and ``nsgs``
(NSGs of a resource whose VNIC the topology does not return are only captured when the resource
entity itself carries the field).

Privacy: stderr summaries never print more than the first 12 characters of an OCID.

Filtering and mode (v1.5.0)
---------------------------
``--mode`` defaults to ``participating`` here, unlike ``parse_terraform.py``, which defaults to
``all``: a Terraform configuration is a curated set, a tenancy dump is not.  Every ``--filter`` /
``--tag`` / ``--resource-type`` / ``--subnet-id`` expression is applied CLIENT-side by
``oci_view.filter_model`` after the model is built, so correctness never depends on the search
query.  Server-side narrowing of ``oci search resource structured-search`` by tag was checked
against the Search service's query-language reference and is deliberately NOT emitted: a tag
predicate is one namespace / key / value triple per query
(``where (definedTags.namespace = 'ns' && definedTags.key = 'k' && definedTags.value = 'v')``,
``where (freeformTags.key = 'k' && freeformTags.value = 'v')``), whose conditions are ANDed
independently rather than correlated as a pair, so two tag expressions cross-match and a
multi-expression filter cannot be pushed down without changing its meaning.
Sources: https://docs.oracle.com/en-us/iaas/Content/Search/Concepts/querysyntax.htm and
https://docs.oracle.com/en-us/iaas/Content/Search/Tasks/queryingresources_topic-To_run_a_custom_freeform_query_to_find_a_resource.htm

Usage
-----
    python3 query_tenancy.py --compartment-id OCID [--vcn-id OCID] [--profile P] [--region R]
                             [--from-json FILE] [--save-raw FILE] [--out model.json]
                             [--no-inferred-edges] [--mode all|participating]
                             [--filter EXPR ...] [--tag K=V] [--resource-type TYPE]
                             [--subnet-id OCID] [--discovery K,K] [--relationships FILE]

Exit codes: 0 success, 1 nothing recognisable / CLI unavailable, 2 bad path / unreadable file.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import detect_settings as ds  # noqa: E402
import oci_view as ov  # noqa: E402
import parse_terraform as pt  # noqa: E402

CLI_TIMEOUT = 30.0
OCID_RE = re.compile(r"ocid1(?:\.[A-Za-z0-9_-]*){1,5}")
DEAD_STATES = frozenset({"TERMINATED", "TERMINATING", "DELETED", "DELETING", "FAILED"})

# OCID region key (3-letter) -> region identifier, for OCIDs that use the short form.
_REGION_KEYS: Dict[str, str] = {
    "iad": "us-ashburn-1", "phx": "us-phoenix-1", "sjc": "us-sanjose-1", "ord": "us-chicago-1",
    "fra": "eu-frankfurt-1", "lhr": "uk-london-1", "ams": "eu-amsterdam-1", "zrh": "eu-zurich-1",
    "mad": "eu-madrid-1", "mrs": "eu-marseille-1", "lin": "eu-milan-1", "cdg": "eu-paris-1",
    "arn": "eu-stockholm-1", "cwl": "uk-cardiff-1", "yyz": "ca-toronto-1", "yul": "ca-montreal-1",
    "gru": "sa-saopaulo-1", "vcp": "sa-vinhedo-1", "scl": "sa-santiago-1", "bog": "sa-bogota-1",
    "qro": "mx-queretaro-1", "mty": "mx-monterrey-1", "nrt": "ap-tokyo-1", "kix": "ap-osaka-1",
    "icn": "ap-seoul-1", "yny": "ap-chuncheon-1", "bom": "ap-mumbai-1", "hyd": "ap-hyderabad-1",
    "sin": "ap-singapore-1", "syd": "ap-sydney-1", "mel": "ap-melbourne-1", "jed": "me-jeddah-1",
    "dxb": "me-dubai-1", "auh": "me-abudhabi-1", "mtz": "il-jerusalem-1", "jnb": "af-johannesburg-1",
}

# Normalised entity kind (lower-case, no separators) -> Terraform resource type understood by
# parse_terraform.ModelBuilder.  Kinds come from ``type`` / ``resource-type`` or the OCID.
ENTITY_TF_TYPES: Dict[str, str] = {
    "vcn": pt.VCN_TYPE,
    "subnet": pt.SUBNET_TYPE,
    "compartment": pt.COMPARTMENT_TYPE,
    # compute
    "instance": "oci_core_instance",
    "instancepool": "oci_core_instance_pool",
    "cluster": "oci_containerengine_cluster",
    "okecluster": "oci_containerengine_cluster",
    "containerenginecluster": "oci_containerengine_cluster",
    "nodepool": "oci_containerengine_node_pool",
    "functionsapplication": "oci_functions_application",
    "fnapplication": "oci_functions_application",
    # storage
    "volume": "oci_core_volume",
    "filesystem": "oci_file_storage_file_system",
    "mounttarget": "oci_file_storage_mount_target",
    "bucket": "oci_objectstorage_bucket",
    # database
    "autonomousdatabase": "oci_database_autonomous_database",
    "dbsystem": "oci_database_db_system",
    "mysqldbsystem": "oci_mysql_mysql_db_system",
    "nosqltable": "oci_nosql_table",
    "rediscluster": "oci_redis_redis_cluster",
    # networking
    "loadbalancer": "oci_load_balancer_load_balancer",
    "networkloadbalancer": "oci_network_load_balancer_network_load_balancer",
    "internetgateway": "oci_core_internet_gateway",
    "natgateway": "oci_core_nat_gateway",
    "servicegateway": "oci_core_service_gateway",
    "drg": "oci_core_drg",
    "drgattachment": "oci_core_drg_attachment",
    "drgroutetable": pt.DRG_ROUTE_TABLE_TYPE,
    "localpeeringgateway": "oci_core_local_peering_gateway",
    "remotepeeringconnection": "oci_core_remote_peering_connection",
    "cpe": "oci_core_cpe",
    "ipsecconnection": "oci_core_ipsec",
    "ipsec": "oci_core_ipsec",
    "virtualcircuit": "oci_core_virtual_circuit",
    "dnszone": "oci_dns_zone",
    "dnsresolver": "oci_dns_resolver",
    "resolver": "oci_dns_resolver",
    "routetable": "oci_core_route_table",
    "securitylist": "oci_core_security_list",
    "networksecuritygroup": "oci_core_network_security_group",
    # identity & security
    "vault": "oci_kms_vault",
    "key": "oci_kms_key",
    "certificate": "oci_certificates_management_certificate",
    "webappfirewall": "oci_waf_web_app_firewall",
    "networkfirewall": "oci_network_firewall_network_firewall",
    "bastion": "oci_bastion_bastion",
    # observability & messaging
    "loggroup": "oci_logging_log_group",
    "alarm": "oci_monitoring_alarm",
    "apmdomain": "oci_apm_apm_domain",
    "stream": "oci_streaming_stream",
    "queue": "oci_queue_queue",
    "eventrule": "oci_events_rule",
    "serviceconnector": "oci_sch_service_connector",
    "onstopic": "oci_ons_notification_topic",
    "topic": "oci_ons_notification_topic",
    # analytics / developer services
    "datascienceproject": "oci_datascience_project",
    "analyticsinstance": "oci_analytics_analytics_instance",
    "apigateway": "oci_apigateway_gateway",
    "devopsproject": "oci_devops_project",
    "containerrepo": "oci_artifacts_container_repository",
    "containerrepository": "oci_artifacts_container_repository",
}
# Entities kept for placement only (never drawn).
HELPER_KINDS = frozenset({"vnic", "vnicattachment", "privateip"})

# Entity attribute (snake_case; kebab/camel variants are derived) -> Res attribute.
_SCALAR_FIELDS = (
    ("display_name", "display_name"), ("name", "name"), ("db_name", "db_name"),
    ("shape", "shape"), ("shape_name", "shape_name"), ("availability_domain", "availability_domain"),
    ("fault_domain", "fault_domain"), ("prohibit_public_ip_on_vnic", "prohibit_public_ip_on_vnic"),
    ("is_private", "is_private"), ("db_workload", "db_workload"), ("lifecycle_state", "lifecycle_state"),
    ("ip_address", "ip_address"), ("mysql_version", "mysql_version"), ("kubernetes_version", "kubernetes_version"),
    ("port", "port"), ("type", "type"),               # virtual circuit PUBLIC / PRIVATE (no DRG when PUBLIC)
    # 6.3 / 9: the fields the label modes render. private_ip and public_ip are
    # VNIC attributes and reach their host through apply_relationships below.
    ("private_ip", "private_ip"), ("public_ip", "public_ip"),
    ("hostname_label", "hostname_label"), ("fqdn", "fqdn"), ("domain_name", "fqdn"),
)
_REF_FIELDS = (
    ("subnet_id", "subnet_id"), ("subnet_ids", "subnet_ids"), ("target_subnet_id", "target_subnet_id"),
    ("vcn_id", "vcn_id"), ("compartment_id", "compartment_id"), ("drg_id", "drg_id"), ("cpe_id", "cpe_id"),
    ("drg_route_table_id", "drg_route_table_id"), ("cluster_id", "cluster_id"),
    ("gateway_id", "gateway_id"), ("route_table_id", "route_table_id"), ("network_entity_id", "network_entity_id"),
    ("peer_id", "peer_id"),
    ("security_list_ids", "security_list_ids"), ("nsg_ids", "nsg_ids"),
    ("network_security_group_ids", "network_security_group_ids"),
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def short_ocid(text: str) -> str:
    """Truncate every OCID in ``text`` to its first 12 characters (for stderr output)."""
    return OCID_RE.sub(lambda m: m.group(0)[:12] + "...", text or "")


def _variants(name: str) -> Tuple[str, ...]:
    parts = name.split("_")
    camel = parts[0] + "".join(p.capitalize() for p in parts[1:])
    return (name, "-".join(parts), camel)


def get(d: dict, *names: str, default=None):
    """Read ``d[name]`` tolerating snake_case, kebab-case and camelCase spellings."""
    if not isinstance(d, dict):
        return default
    for name in names:
        for variant in _variants(name):
            value = d.get(variant)
            if value is not None:
                return value
    return default


def entity_kind(entity: dict) -> str:
    """Normalised kind: ``Vcn`` -> ``vcn``; ``ocid1.natgateway.oc1...`` -> ``natgateway``."""
    raw = get(entity, "type", "resource_type", "entity_type")
    if isinstance(raw, str) and raw.strip():
        return re.sub(r"[^a-z0-9]", "", raw.lower())
    ident = get(entity, "id", "identifier")
    m = re.match(r"^ocid1\.([a-z0-9]+)\.", str(ident or ""))
    return m.group(1) if m else ""


def region_from_ocid(ocid: str) -> Optional[str]:
    parts = str(ocid or "").split(".")
    if len(parts) < 5:
        return None
    key = parts[3].lower()
    if ds.REGION_ID_RE.match(key):
        return key
    return _REGION_KEYS.get(key)


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------

def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def classify_response(resp) -> Optional[str]:
    """``vcn_topology`` / ``networking_topology`` / ``search`` for one CLI response, else None."""
    if not isinstance(resp, dict):
        return None
    data = resp.get("data", resp)
    if isinstance(data, dict) and "entities" in data:
        return "networking_topology" if str(data.get("type", "")).upper() == "NETWORKING" else "vcn_topology"
    if isinstance(data, dict) and "items" in data:
        return "search"
    if isinstance(data, list) and data and all(isinstance(x, dict) and get(x, "resource_type") for x in data):
        return "search"
    return None


def load_bundle(path) -> Dict[str, list]:
    """Read one response, a list of responses or a saved bundle into ``{kind: [responses]}``."""
    p = Path(path)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise pt.InputError(f"cannot read {p}: {exc}") from exc
    bundle: Dict[str, list] = {"vcn_topology": [], "networking_topology": [], "search": []}
    candidates: list
    if isinstance(doc, dict) and any(k in doc for k in bundle):
        for kind in bundle:
            bundle[kind].extend(r for r in _as_list(doc.get(kind)) if isinstance(r, dict))
        return bundle
    candidates = doc if isinstance(doc, list) else [doc]
    for resp in candidates:
        kind = classify_response(resp)
        if kind:
            bundle[kind].append(resp)
    if not any(bundle.values()):
        raise pt.InputError(f"{p}: no topology or search response recognised")
    return bundle


def _topology_parts(resp: dict) -> Tuple[List[dict], List[dict]]:
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    ents = [e for e in _as_list(data.get("entities")) if isinstance(e, dict)]
    rels = [r for r in _as_list(data.get("relationships")) if isinstance(r, dict)]
    return ents, rels


def _search_items(resp: dict) -> List[dict]:
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    items = data.get("items") if isinstance(data, dict) else data
    out: List[dict] = []
    for it in _as_list(items):
        if not isinstance(it, dict):
            continue
        ident = get(it, "identifier", "id")
        if not ident:
            continue
        ent = {"id": ident, "type": get(it, "resource_type", "type")}
        for key in ("display_name", "compartment_id", "lifecycle_state", "availability_domain"):
            val = get(it, key)
            if val is not None:
                ent[key] = val
        out.append(ent)
    return out


# ---------------------------------------------------------------------------
# Entities -> parse_terraform.Res
# ---------------------------------------------------------------------------

def normalise_entity(entity: dict) -> Optional[dict]:
    """Flatten one entity into ``{id, kind, attrs, refs}`` (None when it has no id)."""
    ident = get(entity, "id", "identifier")
    if not isinstance(ident, str) or not ident:
        return None
    kind = entity_kind(entity)
    attrs: Dict[str, Any] = {}
    for src, dst in _SCALAR_FIELDS:
        val = get(entity, src)
        if isinstance(val, (str, int, float, bool)):
            attrs[dst] = val
    cidr = get(entity, "cidr_block")
    if not isinstance(cidr, str):
        blocks = get(entity, "cidr_blocks")
        cidr = blocks[0] if isinstance(blocks, list) and blocks and isinstance(blocks[0], str) else None
    if isinstance(cidr, str):
        attrs["cidr"] = cidr
    # 6.5 / 9: tags if and only if the response carries them; otherwise the model
    # simply has none and a tag: filter reports zero matches with a warning.
    tags = {"freeform": {}, "defined": {}}
    free = get(entity, "freeform_tags")
    if isinstance(free, dict):
        tags["freeform"] = {str(k): str(v) for k, v in free.items() if v is not None}
    defined = get(entity, "defined_tags")
    if isinstance(defined, dict):
        for namespace, values in defined.items():
            if isinstance(values, dict):
                for k, v in values.items():
                    if v is not None:
                        tags["defined"][f"{namespace}.{k}"] = str(v)
    refs: Dict[str, List[str]] = {}
    for src, dst in _REF_FIELDS:
        val = get(entity, src)
        ids = [v for v in (val if isinstance(val, list) else [val]) if isinstance(v, str) and v.startswith("ocid1.")]
        if ids:
            refs[dst] = ids
    return {"id": ident, "kind": kind, "attrs": attrs, "refs": refs, "tags": tags}


def _merge(into: dict, other: dict) -> None:
    if not into["kind"] and other["kind"]:
        into["kind"] = other["kind"]
    for k, v in other["attrs"].items():
        into["attrs"].setdefault(k, v)
    for k, v in other["refs"].items():
        into["refs"].setdefault(k, list(v))
    for bucket in ("freeform", "defined"):
        into.setdefault("tags", {"freeform": {}, "defined": {}})
        for k, v in (other.get("tags") or {}).get(bucket, {}).items():
            into["tags"].setdefault(bucket, {}).setdefault(k, v)


def _alive(ent: dict) -> bool:
    state = str(ent["attrs"].get("lifecycle_state", "")).upper()
    return state not in DEAD_STATES


def collect_entities(bundle: Dict[str, list]) -> Tuple[Dict[str, dict], List[dict]]:
    """Merge every entity (topology first, then search) by OCID; return ``(entities, relationships)``."""
    ents: Dict[str, dict] = {}
    rels: List[dict] = []
    for kind in ("vcn_topology", "networking_topology"):
        for resp in bundle.get(kind) or []:
            raw_ents, raw_rels = _topology_parts(resp)
            for raw in raw_ents:
                norm = normalise_entity(raw)
                if norm is None:
                    continue
                if norm["id"] in ents:
                    _merge(ents[norm["id"]], norm)
                else:
                    ents[norm["id"]] = norm
            rels.extend(raw_rels)
    for resp in bundle.get("search") or []:
        for raw in _search_items(resp):
            norm = normalise_entity(raw)
            if norm is None:
                continue
            if norm["id"] in ents:
                _merge(ents[norm["id"]], norm)
            else:
                ents[norm["id"]] = norm
    return ents, rels


def apply_relationships(ents: Dict[str, dict], rels: List[dict]) -> List[dict]:
    """Fold CONTAINS / ASSOCIATED_WITH into refs; return synthetic DRG attachments to add."""
    synthetic: List[dict] = []
    attached: set = set()
    for e in ents.values():
        if e["kind"] == "drgattachment":
            for d in e["refs"].get("drg_id", []):
                for v in e["refs"].get("vcn_id", []):
                    attached.add((d, v))

    def kind_of(oid: str) -> str:
        return ents[oid]["kind"] if oid in ents else ""

    for rel in rels:
        rtype = str(get(rel, "type") or "").upper()
        id1, id2 = get(rel, "id1"), get(rel, "id2")
        if not (isinstance(id1, str) and isinstance(id2, str)) or id1 not in ents or id2 not in ents:
            continue
        k1, k2 = kind_of(id1), kind_of(id2)
        if rtype == "CONTAINS":
            if k1 == "vcn":
                ents[id2]["refs"].setdefault("vcn_id", [id1])
            elif k1 == "subnet":
                ents[id2]["refs"].setdefault("subnet_id", [id1])
        if rtype in ("CONTAINS", "ASSOCIATED_WITH"):
            pairs = ((id1, k1, id2, k2), (id2, k2, id1, k1))
            for a, ka, b, kb in pairs:
                if ka == "vnic" and kb not in HELPER_KINDS:
                    for field in ("subnet_id", "nsg_ids"):      # the VNIC places its host and carries its NSGs
                        if field in ents[a]["refs"]:
                            ents[b]["refs"].setdefault(field, list(ents[a]["refs"][field]))
                    # 9 / 6.3: and it carries the addresses the caption renders.
                    for field in ("private_ip", "public_ip", "hostname_label", "fqdn"):
                        if field in ents[a]["attrs"]:
                            ents[b]["attrs"].setdefault(field, ents[a]["attrs"][field])
                if ka == "vcn" and kb == "drg" and (b, a) not in attached:
                    attached.add((b, a))
                    synthetic.append({"id": f"{b}@{a}", "kind": "drgattachment", "attrs": {},
                                      "refs": {"drg_id": [b], "vcn_id": [a]}})
                if ka in ("ipsecconnection", "ipsec"):
                    if kb == "cpe":
                        ents[a]["refs"].setdefault("cpe_id", [b])
                    elif kb == "drg":
                        ents[a]["refs"].setdefault("drg_id", [b])
                if ka == "virtualcircuit" and kb == "drg":
                    ents[a]["refs"].setdefault("gateway_id", [b])
    return synthetic


def entities_to_resources(ents: Dict[str, dict]) -> List[pt.Res]:
    resources: List[pt.Res] = []
    for ent in ents.values():
        if not _alive(ent):
            continue
        tf_type = ENTITY_TF_TYPES.get(ent["kind"])
        if tf_type is None:
            continue
        attrs = dict(ent["attrs"])
        if "display_name" not in attrs and isinstance(attrs.get("name"), str):
            attrs["display_name"] = attrs["name"]
        name = attrs.get("display_name") or ent["id"]
        resources.append(pt.Res(ent["id"], tf_type, str(name), attrs,
                                {k: list(v) for k, v in ent["refs"].items()},
                                tags=ent.get("tags")))
    return resources


def _route_edges(model: dict, ents: Dict[str, dict], rels: List[dict]) -> List[dict]:
    """``ROUTES_TO`` relationships as subnet -> gateway control edges."""
    addresses = set(pt.model_addresses(model))
    subnets_by_rt: Dict[str, List[str]] = {}
    for ent in ents.values():
        if ent["kind"] == "subnet":
            for rt in ent["refs"].get("route_table_id", []):
                subnets_by_rt.setdefault(rt, []).append(ent["id"])
    for rel in rels:
        if str(get(rel, "type") or "").upper() == "ASSOCIATED_WITH":
            id1, id2 = get(rel, "id1"), get(rel, "id2")
            for sn, rt in ((id1, id2), (id2, id1)):
                if sn in ents and rt in ents and ents[sn]["kind"] == "subnet" and ents[rt]["kind"] == "routetable":
                    subnets_by_rt.setdefault(rt, [])
                    if sn not in subnets_by_rt[rt]:
                        subnets_by_rt[rt].append(sn)
    edges: List[dict] = []
    for rel in rels:
        if str(get(rel, "type") or "").upper() != "ROUTES_TO":
            continue
        id1, id2 = get(rel, "id1"), get(rel, "id2")
        if not (isinstance(id1, str) and isinstance(id2, str)) or id2 not in addresses:
            continue
        details = get(rel, "route_rule_details") or {}
        label = get(details, "destination") if isinstance(details, dict) else None
        label = label if isinstance(label, str) else "route"
        kind1 = ents[id1]["kind"] if id1 in ents else ""
        sources = [id1] if kind1 == "subnet" else subnets_by_rt.get(id1, [])
        for src in sources:
            if src in addresses:
                # 6.8: derived from routing, not an explicit association - this
                # is the value the 1.4.0 code mislabelled as inferred=False.
                edges.append(pt.new_edge(src, id2, label, "control", discovery="reachability"))
    return edges


# A1: a tenancy dump is not curated - it is the input the guidelines' "do not
# show every discovered OCI resource by default" is about. parse_terraform.py
# defaults to "all" instead.
DEFAULT_MODE = "participating"


def build_model(bundle: Dict[str, list], compartment_id: Optional[str] = None, vcn_id: Optional[str] = None,
                region: Optional[str] = None, inferred_edges: bool = True,
                source_path: Optional[str] = None, mode: Optional[str] = None,
                filter_spec=None, discovery=None) -> Optional[dict]:
    """Bundle of CLI responses -> MODEL (None when ``--vcn-id`` matches no VCN).

    ``mode`` defaults to ``participating`` (A1): a tenancy dump routinely holds
    dozens of regional services with no edge, and they are the main reason a
    live-tenancy diagram is unreadable.
    """
    ents, rels = collect_entities(bundle)
    for syn in apply_relationships(ents, rels):
        ents.setdefault(syn["id"], syn)
    resources = entities_to_resources(ents)

    if region is None:
        for r in resources:
            region = region_from_ocid(r.address)
            if region:
                break
    compartment_name = None
    for r in resources:
        if r.rtype == pt.COMPARTMENT_TYPE and compartment_id and r.address == compartment_id:
            compartment_name = r.label()
    subject = compartment_name or "OCI tenancy"

    builder = pt.ModelBuilder(resources, subject, region, "tenancy", source_path, inferred_edges)
    model = builder.build()
    if compartment_name:
        model["compartment"] = compartment_name
    model["edges"] = pt.dedupe_edges(model["edges"] + _route_edges(model, ents, rels))
    if vcn_id and not pt.select_vcn(model, vcn_id):
        return None
    mode = mode or DEFAULT_MODE
    if not inferred_edges and discovery is None:
        discovery = ov.NO_INFERRED_DISCOVERY
    parsed = ov.parse_filter(filter_spec)
    if any(e["dim"] in ("tag", "ftag", "dtag", "env", "app")
           for e in parsed["include"] + parsed["exclude"]):
        has_tags = any((e.get("tags") or {}).get("freeform") or (e.get("tags") or {}).get("defined")
                       for e in ents.values())
        if not has_tags:
            model.setdefault("warnings", []).append(
                "WARNING: a tag filter was given but the search response carried no tags; "
                "nothing can match. Re-run with --mode all to see the whole compartment.")
    model, report = ov.filter_model(model, filter_spec, mode=mode, discovery=discovery)
    model["mode"] = mode
    if report["include"] or report["exclude"]:
        model["filter"] = {"include": list(report["include"]), "exclude": list(report["exclude"])}
    model["filter_report"] = dict(report)
    return model


# ---------------------------------------------------------------------------
# Live OCI CLI access
# ---------------------------------------------------------------------------

def run_oci(args: List[str], profile: Optional[str] = None, region: Optional[str] = None,
            timeout: float = CLI_TIMEOUT) -> Tuple[Optional[dict], Optional[str]]:
    """Run ``oci <args> --output json``; return ``(parsed_json, warning)``."""
    exe = shutil.which("oci")
    if not exe:
        return None, "oci CLI not found on PATH"
    cmd = [exe, *args, "--output", "json"]
    if profile:
        cmd += ["--profile", profile]
    if region:
        cmd += ["--region", region]
    label = short_ocid(" ".join(args[:4]))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"'{label}' timed out after {timeout:.0f}s"
    except OSError as exc:
        return None, f"'{label}' failed to start: {exc}"
    if proc.returncode != 0:
        first = (proc.stderr or proc.stdout or "").strip().splitlines()
        return None, f"'{label}' exited {proc.returncode}: {short_ocid(first[0] if first else '')}"
    try:
        return json.loads(proc.stdout or "{}"), None
    except ValueError:
        return None, f"'{label}' returned invalid JSON"


def fetch_live(compartment_id: str, vcn_id: Optional[str] = None, profile: Optional[str] = None,
               region: Optional[str] = None) -> Tuple[Dict[str, list], List[str]]:
    """Query the three CLI sources; failures are collected as warnings, not raised."""
    bundle: Dict[str, list] = {"vcn_topology": [], "networking_topology": [], "search": []}
    warnings: List[str] = []
    calls: List[Tuple[str, List[str]]] = []
    if vcn_id:
        calls.append(("vcn_topology", ["network", "vcn-topology", "get",
                                       "--compartment-id", compartment_id, "--vcn-id", vcn_id]))
    calls.append(("networking_topology", ["network", "networking-topology", "get",
                                          "--compartment-id", compartment_id]))
    calls.append(("search", ["search", "resource", "structured-search", "--query-text",
                             f"query all resources where compartmentId = '{compartment_id}'"]))
    for kind, args in calls:
        data, warning = run_oci(args, profile, region)
        if data is not None:
            bundle[kind].append(data)
        elif warning:
            warnings.append(warning)
            if "not found on PATH" in warning:
                break
    return bundle, warnings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="query_tenancy.py",
        description="EXPERIMENTAL: build the diagram MODEL from a live OCI compartment via the OCI CLI "
                    "(or from saved topology JSON with --from-json).",
        epilog="Exit codes: 0 success, 1 nothing recognisable / CLI unavailable, 2 bad path.",
    )
    parser.add_argument("--compartment-id", required=True, metavar="OCID")
    parser.add_argument("--vcn-id", metavar="OCID", help="restrict to this VCN (also queries vcn-topology)")
    parser.add_argument("--profile", metavar="P", help="OCI CLI profile")
    parser.add_argument("--region", metavar="R", help="OCI region (also passed to the CLI)")
    parser.add_argument("--from-json", metavar="FILE", help="saved topology/search JSON instead of the CLI")
    parser.add_argument("--save-raw", metavar="FILE", help="save the raw CLI responses as a bundle")
    parser.add_argument("--out", metavar="FILE", help="write the model JSON here instead of stdout")
    parser.add_argument("--no-inferred-edges", action="store_true",
                        help="emit only edges backed by explicit relationships (an alias for "
                             "--discovery " + ",".join(ov.NO_INFERRED_DISCOVERY) + ")")
    parser.add_argument("--subnet-id", action="append", default=None, metavar="OCID",
                        help="sugar for --filter subnet=OCID")
    parser.add_argument("--filter", action="append", default=None, metavar="EXPR",
                        help="keep only what matches '[!]<dimension>[:<key>]<op><value>'; "
                             f"dimensions: {','.join(ov.FILTER_DIMENSIONS)}. Repeatable")
    parser.add_argument("--tag", action="append", default=None, metavar="K=V",
                        help="sugar for --filter tag:K=V (client-side; see the note on "
                             "server-side narrowing in this module's docstring)")
    parser.add_argument("--resource-type", action="append", default=None, metavar="TYPE",
                        help="sugar for --filter type=TYPE")
    parser.add_argument("--mode", default=DEFAULT_MODE, choices=ov.MODES,
                        help="participating (default for a live tenancy) or all")
    parser.add_argument("--discovery", default=None, metavar="K,K",
                        help=f"keep only edges discovered this way: {','.join(ov.DISCOVERY_KINDS)}")
    parser.add_argument("--relationships", default=None, metavar="FILE",
                        help="JSON sidecar of extra edges, merged with discovery='user'")
    args = parser.parse_args(argv)

    if args.from_json:
        src = Path(args.from_json).expanduser()
        if not src.is_file():
            print(f"Error: file does not exist: {args.from_json}", file=sys.stderr)
            return 2
        try:
            bundle = load_bundle(src)
        except pt.InputError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        source_path = str(src)
    else:
        bundle, warnings = fetch_live(args.compartment_id, args.vcn_id, args.profile, args.region)
        for w in warnings:
            print(f"Warning: {w}", file=sys.stderr)
        if not any(bundle.values()):
            print(f"No data returned by the OCI CLI for compartment {short_ocid(args.compartment_id)}.",
                  file=sys.stderr)
            return 1
        source_path = f"oci-cli:{short_ocid(args.compartment_id)}"
        if args.save_raw:
            Path(args.save_raw).expanduser().write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
            print(f"Saved raw responses to {args.save_raw}", file=sys.stderr)

    include = list(args.filter or [])
    include += [f"tag:{t}" for t in (args.tag or [])]
    include += [f"type={t}" for t in (args.resource_type or [])]
    include += [f"subnet={s}" for s in (args.subnet_id or [])]
    try:
        model = build_model(bundle, args.compartment_id, args.vcn_id, args.region,
                            not args.no_inferred_edges, source_path, mode=args.mode,
                            filter_spec=include,
                            discovery=args.discovery.split(",") if args.discovery else None)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if model is not None and args.relationships:
        try:
            model["edges"] = pt.dedupe_edges(list(model["edges"])
                                             + pt.load_relationships(args.relationships))
        except pt.InputError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
    if model is None:
        print(f"No VCN matches {short_ocid(args.vcn_id or '')}.", file=sys.stderr)
        return 1
    if pt.model_is_empty(model):
        # A filter or the participating mode can empty the model itself, and the
        # warning that says so is the only thing that explains the exit code.
        for warning in model.get("warnings") or []:
            print(short_ocid(warning), file=sys.stderr)
        print("No recognisable resources in the topology/search data.", file=sys.stderr)
        return 1
    problems = pt.validate_model(model, pt._builder_icon_keys())
    if problems:
        print("Model failed schema validation:", file=sys.stderr)
        for p in problems:
            print(f"  - {short_ocid(p)}", file=sys.stderr)
        return 1

    summary = short_ocid(pt.summarise(model))
    model.pop("filter_report", None)          # a report, not a schema key
    text = json.dumps(model, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).expanduser().write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    for text in model.get("warnings") or []:
        print(short_ocid(text), file=sys.stderr)
    print(summary, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
