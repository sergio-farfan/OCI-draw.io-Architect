"""Reusable draw.io builder for OCI architecture diagrams (v1.2.0).

Requires Python 3.9+ and only the standard library. Pillow is optional and
is needed only for PNG/JPEG logos passed to ``add_image()``; SVG logos and
all bundled OCI icons work without it.

What this module gives you
--------------------------
* ``DrawioBuilder`` - builds a ``.drawio`` XML document page by page.
* Embedded OCI SVG icons (URL-encoded data URIs, viewBox cropped to the
  glyph so every icon renders at the same visual size).
* Oracle Redwood container styles (region, tenancy, compartment,
  availability_domain, fault_domain, vcn, subnet, services,
  oracle_services_network, onprem, other, metro_or_realm, third_party_cloud,
  internet); ``hub`` is a deprecated alias of ``onprem``.
* Layout helpers: ``place_icons()``, ``fit_to_children()``, ``fit_page()``,
  ``add_title()``, ``add_legend()``, ``add_table()``, ``add_page()``,
  ``add_layer()``.
* Edges that route themselves: ``add_edge()`` picks the common-ancestor
  parent, docking sides and gutter waypoints from the actual geometry so
  connectors do not cross unrelated icons or labels.
* ``validate()`` / ``check_overlaps()`` - referential integrity, container
  overlaps (any two containers, not just siblings), containment, foreign
  containment (icons inside a VCN/subnet they do not belong to; DRG inside
  a VCN), icon/label collisions, long labels and estimated edge crossings.
* ``render()`` - PNG/SVG/PDF export through the draw.io desktop CLI when it
  is installed.

Icon resolution
---------------
Icons are looked up in the first existing directory among: ``$OCI_SVG_DIR``,
``<this file>/../icons`` (plugin layout), ``<this file>/icons``,
``$CLAUDE_PLUGIN_ROOT/icons`` and the usual Claude Code plugin install
locations under ``~/.claude/plugins``. Call ``set_icon_dir(path)`` to
override at runtime. Every bundled SVG is addressable by its file stem
(``compute_virtual_machine_vm``) and the common ones also by a short alias
(``vm``); see ``ICON_ALIASES`` and ``add_icons_to_map()``.

Minimal usage
-------------
    import sys
    sys.path.insert(0, "<plugin>/scripts")          # or copy this file
    from pathlib import Path
    from drawio_builder import DrawioBuilder

    d = DrawioBuilder(page_name="My Diagram")
    d.add_title("app-prod - Architecture", region_label="Ashburn",
                region="us-ashburn-1", compartment="prod")
    region = d.add_group("us-ashburn-1", 20, 75, 800, 400, group_type="region")
    vcn = d.add_group("VCN: app (10.0.0.0/16)", 20, 40, 700, 300,
                      parent=region, group_type="vcn")
    sn = d.add_group("sn-app (10.0.1.0/24)", 20, 50, 400, 200,
                     parent=vcn, group_type="subnet")
    ids, box = d.place_icons(sn, [("Load Balancer", "load_balancer"),
                                  ("App VM\\n10.0.1.5", "vm")], cols=2)
    d.fit_to_children(sn); d.fit_to_children(vcn); d.fit_to_children(region)
    d.add_edge(ids[0], ids[1], "443")
    d.fit_page()
    problems = d.validate()
    if any(p.startswith("ERROR") for p in problems):
        raise SystemExit("\\n".join(problems))
    d.write(Path("output.drawio"))
"""

from __future__ import annotations

import base64
import difflib
import html as _html
import io
import math
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import Optional

__version__ = "1.2.0"

# ---------------------------------------------------------------------------
# Icon directory resolution
# ---------------------------------------------------------------------------
def _candidate_icon_dirs() -> list:
    """Ordered list of directories that may hold the OCI SVG icon set."""
    cands = []
    env = os.environ.get("OCI_SVG_DIR")
    if env:
        cands.append(Path(env).expanduser())
    here = Path(__file__).resolve().parent
    cands.append(here.parent / "icons")   # <plugin>/scripts/../icons
    cands.append(here / "icons")          # builder copied next to an icons/ dir
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if root:
        cands.append(Path(root).expanduser() / "icons")
    home = Path.home()
    try:
        cands.extend(sorted(home.glob(".claude/plugins/marketplaces/*/plugins/oci-drawio-architect/icons")))
        cands.extend(sorted(home.glob(".claude/plugins/cache/*/oci-drawio-architect/*/icons")))
        cands.extend(sorted(home.glob(".claude/plugins/cache/*/oci-drawio-architect/icons")))
    except OSError:
        pass
    cands.append(home / ".claude" / "plugins" / "oci-drawio-architect" / "icons")
    out, seen = [], set()
    for c in cands:
        if str(c) not in seen:
            seen.add(str(c))
            out.append(c)
    return out


def _resolve_icon_dir() -> Optional[Path]:
    for c in _candidate_icon_dirs():
        if c.is_dir():
            return c
    return None


OCI_SVG_DIR: Optional[Path] = _resolve_icon_dir()

# ---------------------------------------------------------------------------
# Redwood palette (OCI Architecture Diagram Toolkit v24.1/v24.2)
# ---------------------------------------------------------------------------
COLORS = {
    "region_fill": "#F5F4F2",    # Neutral 1 - region / on-prem group fill
    "region_stroke": "#9E9892",  # Neutral 3 - location-group borders
    "neutral_2": "#DFDCD8",      # Availability Domain fill
    "neutral_4": "#70736E",      # Neutral 4 - secondary text / connector labels
    "air": "#FCFBFA",            # Fault Domain / Oracle Services Network fill
    "vcn_stroke": "#AE562C",     # Sienna - VCN / subnet / compartment borders
    "vcn_label": "#AE562C",      # Sienna - VCN / subnet labels
    "text_primary": "#312D2A",   # Bark - text, services panel, connectors
    "rose": "#A36472",           # Oracle Services Network border / label
    "ivy": "#759C6C",            # OCI logical component border
    "ocean": "#2C5967",          # Icon ink colour
    "oracle_red": "#C74634",     # On-premises logical component border
    "edge_color": "#312D2A",     # Bark - default connector colour
    # Project extensions (not part of the official palette)
    "edge_accent": "#AE562C",
    "edge_purple": "#7B61FF",
}

# Oracle Sans is proprietary; the stack degrades to a sans-serif face instead
# of draw.io's serif default when it is not installed.
FONT_STACK = "Oracle Sans,Arial,Helvetica,sans-serif"
TITLE_FONT_STACK = FONT_STACK

# Icon slot geometry. The slot is what layout code reasons about; the glyph
# is fitted into GLYPH_W x GLYPH_H at the top of the slot and the caption
# starts LABEL_GAP below the slot.
ICON_W = 75
ICON_H = 95
GLYPH_W = 70
GLYPH_H = 70
GLYPH_TOP = 5
LABEL_GAP = 2
LABEL_W = 105
LABEL_H = 45
LABEL_FONT_SIZE = 11
LABEL_LINE_H = 14
ICON_FOOTPRINT_H = ICON_H + LABEL_GAP + LABEL_H   # 142
MAX_LABEL_LINES = 3

# Layout defaults shared with the skill's layout recipe
PAD = 20        # inner padding / outer page margin
ROW1_Y = 50     # first icon row inside a container (room for the title)
COL_W = 130     # icon column pitch
ROW_H = 160     # icon row pitch (95 + 2 + 45 + 18)
GAP = 20        # gap between sibling containers

# ---------------------------------------------------------------------------
# Icon keys. Every SVG under the icon directory is registered by file stem at
# import time; ICON_ALIASES adds short names for the common services.
# ---------------------------------------------------------------------------
ICON_ALIASES = {
    # compute
    "vm": "compute/compute_virtual_machine_vm.svg",
    "compute": "compute/compute_virtual_machine_vm.svg",
    "bare_metal": "compute/compute_bare_metal_compute.svg",
    "flex_vm": "compute/compute_flex_virtual_machine_flex_vm.svg",
    "burstable_vm": "compute/compute_burstable_virtual_machine_burstable_vm.svg",
    "functions": "compute/compute_functions.svg",
    "autoscaling": "compute/compute_autoscaling.svg",
    "instance_pool": "compute/compute_instance_pools.svg",
    "instance_pools": "compute/compute_instance_pools.svg",
    # storage
    "block_storage": "storage/storage_block_storage.svg",
    "block_volume": "storage/storage_block_storage.svg",
    "block_storage_cloning": "storage/storage_block_storage_cloning.svg",
    "buckets": "storage/storage_buckets.svg",
    "object_storage": "storage/storage_object_storage.svg",
    "file_storage": "storage/storage_file_storage.svg",
    "backup_restore": "storage/storage_back_up_restore.svg",
    "elastic_performance": "storage/storage_elastic_performance.svg",
    "local_storage": "storage/storage_local_storage.svg",
    "persistent_volume": "storage/storage_persistent_volume.svg",
    "storage_gateway": "storage/storage_service_gateway.svg",
    # database
    "autonomous_db": "database/database_autonomous_db.svg",
    "adb": "database/database_autonomous_db.svg",
    "adw": "database/database_autonomous_data_warehouse_adw.svg",
    "atp": "database/database_autonomous_transaction_processing_atp.svg",
    "adb_dedicated": "database/database_adb_d.svg",
    "adw_dedicated": "database/database_adw_d.svg",
    "atp_dedicated": "database/database_atp_d.svg",
    "db_system": "database/database_database_system.svg",
    "exadata": "database/database_exadata.svg",
    "exadata_cc": "database/database_exadata_c_c.svg",
    "rac": "database/database_rac.svg",
    "mysql": "database/database_mysql.svg",
    "nosql": "database/database_nosql.svg",
    "opensearch": "database/database_opensearch.svg",
    "data_safe": "database/database_data_safe.svg",
    "goldengate": "database/database_goldengate.svg",
    # networking
    "vcn": "networking/networking_virtual_cloud_network_vcn.svg",
    "load_balancer": "networking/networking_load_balancer.svg",
    "lb": "networking/networking_load_balancer.svg",
    "flexible_load_balancer": "networking/networking_flexible_load_balancer.svg",
    "internet_gateway": "networking/networking_internet_gateway.svg",
    "igw": "networking/networking_internet_gateway.svg",
    "nat_gateway": "networking/networking_nat_gateway.svg",
    "service_gateway": "networking/networking_service_gateway.svg",
    "sgw": "networking/networking_service_gateway.svg",
    "drg": "networking/networking_dynamic_routing_gateway_drg.svg",
    "dynamic_routing_gateway": "networking/networking_dynamic_routing_gateway_drg.svg",
    "remote_peering_gateway": "networking/networking_remote_peering_gateway.svg",
    "rpg": "networking/networking_remote_peering_gateway.svg",
    "cpe": "networking/networking_customer_premises_equipment_cpe.svg",
    "customer_data_center": "networking/networking_customer_data_center.svg",
    "dns": "networking/networking_dns.svg",
    "cdn": "networking/networking_cdn.svg",
    "route_table": "networking/networking_route_table.svg",
    "backbone": "networking/networking_backbone.svg",
    "byoip": "networking/networking_byoip.svg",
    "ip_pools": "networking/networking_ip_pools.svg",
    "network_switch": "networking/networking_network_switch.svg",
    "vtap": "networking/networking_vtap.svg",
    # identity & security
    "nsg": "identity_and_security/identity_and_security_nsg.svg",
    "security_list": "identity_and_security/identity_and_security_security_lists.svg",
    "security_lists": "identity_and_security/identity_and_security_security_lists.svg",
    "vault": "identity_and_security/identity_and_security_vault.svg",
    "key_vault": "identity_and_security/identity_and_security_key_vault.svg",
    "key_management": "identity_and_security/identity_and_security_key_management.svg",
    "kms": "identity_and_security/identity_and_security_key_management.svg",
    "encryption": "identity_and_security/identity_and_security_encryption.svg",
    "certificates": "identity_and_security/identity_and_security_certificates.svg",
    "waf": "identity_and_security/identity_and_security_waf.svg",
    "firewall": "identity_and_security/identity_and_security_firewall.svg",
    "network_firewall": "identity_and_security/identity_and_security_firewall.svg",
    "bastion": "identity_and_security/identity_and_security_bastion.svg",
    "cloud_guard": "identity_and_security/identity_and_security_cloud_guard.svg",
    "compartments": "identity_and_security/identity_and_security_compartments.svg",
    "compartment": "identity_and_security/identity_and_security_compartments.svg",
    "ddos_protection": "identity_and_security/identity_and_security_ddos_protection.svg",
    "iam": "identity_and_security/identity_and_security_iam_identity_and_access_management.svg",
    "identity": "identity_and_security/identity_and_security_identity.svg",
    "policies": "identity_and_security/identity_and_security_policies.svg",
    "policy": "identity_and_security/identity_and_security_policies.svg",
    "user": "identity_and_security/identity_and_security_user.svg",
    "user_group": "identity_and_security/identity_and_security_user_group.svg",
    "active_directory": "identity_and_security/identity_and_security_active_directory.svg",
    "max_security_zone": "identity_and_security/identity_and_security_maximum_security_zone.svg",
    "threat_defense": "identity_and_security/identity_and_security_threat_defense.svg",
    "threat_intelligence": "identity_and_security/identity_and_security_threat_intelligence.svg",
    "vulnerability_scanning": "identity_and_security/identity_and_security_vulnerability_scanning.svg",
    # developer services
    "oke": "developer_services/developer_services_container_engine_for_kubernetes.svg",
    "kubernetes": "developer_services/developer_services_container_engine_for_kubernetes.svg",
    "container_registry": "developer_services/developer_services_container_registry.svg",
    "ocir": "developer_services/developer_services_container_registry.svg",
    "devops": "developer_services/developer_services_devops.svg",
    "api_gateway": "developer_services/developer_services_api_gateway.svg",
    "api_service": "developer_services/developer_services_api_service.svg",
    "apex": "developer_services/developer_services_apex.svg",
    "content_management": "developer_services/developer_services_content_management.svg",
    "email_delivery": "developer_services/developer_services_email_delivery.svg",
    "email": "developer_services/developer_services_email_delivery.svg",
    "integrations": "developer_services/developer_services_integrations.svg",
    "oic": "developer_services/developer_services_integrations.svg",
    "jet": "developer_services/developer_services_jet.svg",
    "notifications": "developer_services/developer_services_notifications.svg",
    "ons": "developer_services/developer_services_notifications.svg",
    "private_endpoint": "developer_services/developer_services_private_endpoint_ip.svg",
    "resource_manager": "developer_services/developer_services_resource_manager.svg",
    "service_mesh": "developer_services/developer_services_service_mesh.svg",
    "visual_builder": "developer_services/developer_services_visual_builder.svg",
    # observability & management
    "logging": "observability_and_management/observability_and_management_logging.svg",
    "logging_analytics": "observability_and_management/observability_and_management_logging_analytics.svg",
    "monitoring": "observability_and_management/observability_and_management_monitoring.svg",
    "alarms": "observability_and_management/observability_and_management_alarms.svg",
    "apm": "observability_and_management/observability_and_management_application_performance_management.svg",
    "auditing": "observability_and_management/observability_and_management_auditing.svg",
    "audit": "observability_and_management/observability_and_management_auditing.svg",
    "health_checks": "observability_and_management/observability_and_management_health_checks.svg",
    "operations_insights": "observability_and_management/observability_and_management_operations_insights.svg",
    "queuing": "observability_and_management/observability_and_management_queuing.svg",
    "queue": "observability_and_management/observability_and_management_queuing.svg",
    "search": "observability_and_management/observability_and_management_search.svg",
    "vcn_flow_logs": "observability_and_management/observability_and_management_vcn_flow_logs.svg",
    "workflow": "observability_and_management/observability_and_management_workflow.svg",
    # analytics & AI
    "ai": "analytics_and_ai/analytics_and_ai_artificial_intelligence.svg",
    "generative_ai": "analytics_and_ai/analytics_and_ai_artificial_intelligence.svg",
    "big_data": "analytics_and_ai/analytics_and_ai_big_data.svg",
    "analytics": "analytics_and_ai/analytics_and_ai_big_data.svg",
    "data_science": "analytics_and_ai/analytics_and_ai_data_science.svg",
    "digital_assistant": "analytics_and_ai/analytics_and_ai_digital_assistant.svg",
    "oda": "analytics_and_ai/analytics_and_ai_digital_assistant.svg",
    "essbase": "analytics_and_ai/analytics_and_ai_essbase.svg",
    "machine_learning": "analytics_and_ai/analytics_and_ai_machine_learning.svg",
    "ml": "analytics_and_ai/analytics_and_ai_machine_learning.svg",
    "message_listener": "analytics_and_ai/analytics_and_ai_message_listener.svg",
    "message_producer": "analytics_and_ai/analytics_and_ai_message_producer.svg",
    "service_connector_hub": "analytics_and_ai/analytics_and_ai_service_connector_hub.svg",
    "connector_hub": "analytics_and_ai/analytics_and_ai_service_connector_hub.svg",
    "streaming": "analytics_and_ai/analytics_and_ai_streaming.svg",
    # general
    "data_catalog": "general/data_catalog.svg",
    "data_flow": "general/data_flow.svg",
    "data_integration": "general/data_integration.svg",
    "events": "general/events.svg",
    "cloud": "general/cloud.svg",
    "container": "general/container.svg",
    "database_management": "general/database_management.svg",
    "generic_database": "general/database.svg",
    "digital_media": "general/digital_media.svg",
    "marketplace": "general/marketplace.svg",
    "media_flow": "general/media_flow.svg",
    "media_streams": "general/media_streams.svg",
    "analytics_general": "general/analytics_and_ai.svg",
    # governance
    "cloud_advisor": "governance_and_administration/governance_and_administration_cloud_advisor.svg",
    "license_manager": "governance_and_administration/governance_and_administration_license_manager.svg",
    "ocid": "governance_and_administration/governance_and_administration_oracle_cloud_identifier.svg",
    "organization": "governance_and_administration/governance_and_administration_organization.svg",
    "tagging": "governance_and_administration/governance_and_administration_tagging.svg",
    # migration
    "dedicated_region": "migration/migration_dedicated_region.svg",
    "roving_edge": "migration/migration_roving_edge_infrastructure.svg",
    # applications
    "erp": "applications/applications_erp.svg",
    "hcm": "applications/applications_hcm.svg",
    "epm": "applications/applications_epm.svg",
    "fusion": "applications/applications_fusion.svg",
    "e_business_suite": "applications/applications_e_business_suite.svg",
    "ebs": "applications/applications_e_business_suite.svg",
    # catalog short keys (generated from references/icon-catalog.md)
    "adb_d": "database/database_adb_d.svg",
    "adw_d": "database/database_adw_d.svg",
    "analytics_and_ai_general": "general/analytics_and_ai.svg",
    "atp_d": "database/database_atp_d.svg",
    "backup": "storage/storage_back_up_restore.svg",
    "bi_connector": "applications/applications_bi_cloud_connector.svg",
    "block_cloning": "storage/storage_block_storage_cloning.svg",
    "cloud_id": "governance_and_administration/governance_and_administration_oracle_cloud_identifier.svg",
    "content_mgmt": "developer_services/developer_services_content_management.svg",
    "cpq": "applications/applications_cpq.svg",
    "data_center": "networking/networking_customer_data_center.svg",
    "ddos": "identity_and_security/identity_and_security_ddos_protection.svg",
    "elastic_perf": "storage/storage_elastic_performance.svg",
    "engagement": "applications/applications_engagement.svg",
    "financials": "applications/applications_financials.svg",
    "flexible_lb": "networking/networking_flexible_load_balancer.svg",
    "flow_logs": "observability_and_management/observability_and_management_vcn_flow_logs.svg",
    "gg_adapter": "database/database_goldengate_application_adapter.svg",
    "gg_director": "database/database_goldengate_director.svg",
    "gg_hp_nonstop": "database/database_goldengate_hp_non_stop_guardian.svg",
    "gg_monitor": "database/database_goldengate_monitor.svg",
    "gg_on_premises": "database/database_goldengate_on_premises.svg",
    "gg_plugin": "database/database_goldengate_plug_in.svg",
    "gg_stream_analytics": "database/database_goldengate_stream_analytics.svg",
    "gg_studio": "database/database_goldengate_studio.svg",
    "gg_veridata": "database/database_goldengate_veridata.svg",
    "healthcare": "applications/applications_healthcare.svg",
    "innovation": "applications/applications_innovation_management.svg",
    "inventory": "applications/applications_inventory_management.svg",
    "key_mgmt": "identity_and_security/identity_and_security_key_management.svg",
    "license_mgr": "governance_and_administration/governance_and_administration_license_manager.svg",
    "manufacturing": "applications/applications_manufacturing.svg",
    "oco_subnet": "applications/applications_oco_subnet.svg",
    "ops_insights": "observability_and_management/observability_and_management_operations_insights.svg",
    "order_mgmt": "applications/applications_order_management.svg",
    "pdm": "applications/applications_product_master_data_management.svg",
    "persistent_vol": "storage/storage_persistent_volume.svg",
    "procurement": "applications/applications_procurement.svg",
    "project_financial": "applications/applications_project_financial_management.svg",
    "project_mgmt": "applications/applications_project_management.svg",
    "storage_sgw": "storage/storage_service_gateway.svg",
    "supply_chain": "applications/applications_supply_chain_planning.svg",
    "threat_intel": "identity_and_security/identity_and_security_threat_intelligence.svg",
    "vuln_scanning": "identity_and_security/identity_and_security_vulnerability_scanning.svg",
}

ICON_MAP: dict = dict(ICON_ALIASES)
_svg_cache: dict = {}


def _register_scanned_icons(icon_dir: Path) -> int:
    """Register every SVG under icon_dir by file stem (aliases win)."""
    n = 0
    try:
        files = sorted(icon_dir.rglob("*.svg"))
    except OSError:
        return 0
    for p in files:
        rel = p.relative_to(icon_dir).as_posix()
        if p.stem not in ICON_MAP:
            ICON_MAP[p.stem] = rel
            n += 1
    return n


if OCI_SVG_DIR is not None:
    _register_scanned_icons(OCI_SVG_DIR)


def set_icon_dir(path) -> Path:
    """Point the builder at a different icon directory (clears caches)."""
    global OCI_SVG_DIR
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise FileNotFoundError(f"Icon directory not found: {p}")
    OCI_SVG_DIR = p
    _svg_cache.clear()
    _register_scanned_icons(p)
    return p


def add_icons_to_map(new_icons: dict) -> None:
    """Add or override entries in ICON_MAP ({key: "category/file.svg"}).

    Values may also be absolute paths. Re-pointing an existing key
    invalidates the cached SVG for that key.
    """
    for key, rel in new_icons.items():
        ICON_MAP[key] = rel
    _svg_cache.clear()


def resolve_icon_path(icon_key: str) -> Path:
    """Map an icon key (alias, stem, relative or absolute path) to a file."""
    rel = ICON_MAP.get(icon_key)
    if rel is None:
        candidate = Path(icon_key)
        if candidate.suffix.lower() == ".svg" and candidate.is_file():
            return candidate.resolve()
        if OCI_SVG_DIR is not None and (OCI_SVG_DIR / icon_key).is_file():
            return (OCI_SVG_DIR / icon_key).resolve()
        suggestions = difflib.get_close_matches(icon_key, list(ICON_MAP), n=3)
        hint = f" Did you mean {', '.join(suggestions)}?" if suggestions else ""
        raise ValueError(
            f"Unknown icon_key {icon_key!r}.{hint} Every bundled SVG is available by "
            f"file stem (e.g. 'compute_virtual_machine_vm') or alias (e.g. 'vm'); "
            f"see references/icon-catalog.md or register a custom icon with "
            f"add_icons_to_map()."
        )
    p = Path(rel)
    if p.is_absolute():
        return p
    if OCI_SVG_DIR is None:
        cands = "\n  ".join(str(c) for c in _candidate_icon_dirs())
        raise FileNotFoundError(
            "OCI icon directory not found. Set the OCI_SVG_DIR environment "
            "variable (or call set_icon_dir()) to the plugin's icons/ folder. "
            f"Searched:\n  {cands}"
        )
    full = OCI_SVG_DIR / rel
    if not full.is_file():
        raise FileNotFoundError(
            f"Icon SVG not found: {full}. OCI_SVG_DIR is {OCI_SVG_DIR}; check the "
            f"icon set or override with the OCI_SVG_DIR env var."
        )
    return full


# ---------------------------------------------------------------------------
# SVG loading: strip stencil leftovers, crop the viewBox to the glyph
# ---------------------------------------------------------------------------
_SVG_OPEN_RE = re.compile(r"<svg\b[^>]*>", re.S)
_DRAWABLE_RE = re.compile(r"<(path|rect|circle|ellipse|polygon|polyline|line|image|text|use)\b")
_OTHER_SHAPE_RE = re.compile(r"<(rect|circle|ellipse|polygon|polyline|line|image|text|use)\b")
_GROUP_RE = re.compile(r"<g\b([^>]*)>(.*?)</g>", re.S)
_TRANSFORM_RE = re.compile(
    r"translate\(\s*(-?[\d.]+)[\s,]+(-?[\d.]+)\s*\)"
    r"(?:\s*scale\(\s*(-?[\d.]+)(?:[\s,]+(-?[\d.]+))?\s*\))?"
)
_PATH_D_RE = re.compile(r'<path\b[^>]*?\bd="([^"]+)"')
_NUM_RE = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
# The OCI Library stencil's empty caption box that leaked into 16 icons.
_PLACEHOLDER_RE = re.compile(
    r'<g\b[^>]*>\s*<path\b[^>]*?\bd="M 0 100 L 100 100 L 100 0 L 0 0 L 0 100"'
    r'[^>]*?fill="none"[^>]*?stroke="#000000"[^>]*/>\s*</g>\s*',
    re.S,
)


def _svg_content_bbox(svg_text: str):
    """Bounding box of all path coordinates in flat <g transform> groups.

    Returns (minx, miny, maxx, maxy) or None when the SVG is not in the
    simple form used by the OCI icon set (nested groups, non-path shapes or
    relative path commands), in which case the declared viewBox is kept.
    """
    open_m = _SVG_OPEN_RE.search(svg_text)
    body = svg_text[open_m.end():] if open_m else svg_text
    if _OTHER_SHAPE_RE.search(body):
        return None
    groups = list(_GROUP_RE.finditer(body))
    if not groups:
        return None
    if _PATH_D_RE.search(_GROUP_RE.sub("", body)):
        return None  # stray paths outside groups
    boxes = []
    for m in groups:
        attrs, inner = m.group(1), m.group(2)
        if "<g" in inner:
            return None
        tx = ty = 0.0
        sx = sy = 1.0
        tm = _TRANSFORM_RE.search(attrs)
        if tm:
            tx, ty = float(tm.group(1)), float(tm.group(2))
            if tm.group(3) is not None:
                sx = float(tm.group(3))
                sy = float(tm.group(4)) if tm.group(4) is not None else sx
        elif "transform=" in attrs:
            return None
        for d in _PATH_D_RE.findall(inner):
            letters = set(re.sub(r"[eE](?=[-+]?\d)", "", d)) & set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
            if letters - set("MLCZ"):
                return None
            nums = [float(n) for n in _NUM_RE.findall(d)]
            if len(nums) < 2:
                continue
            if len(nums) % 2:
                nums = nums[:-1]
            xs, ys = nums[0::2], nums[1::2]
            boxes.append((tx + min(xs) * sx, ty + min(ys) * sy,
                          tx + max(xs) * sx, ty + max(ys) * sy))
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _set_root_attr(open_tag: str, name: str, value: str) -> str:
    pattern = re.compile(r'\s' + re.escape(name) + r'="[^"]*"')
    if pattern.search(open_tag):
        return pattern.sub(f' {name}="{value}"', open_tag, count=1)
    return open_tag[:-1].rstrip("/") + f' {name}="{value}">' if not open_tag.endswith("/>") \
        else open_tag[:-2] + f' {name}="{value}"/>'


def _fmt_num(value) -> str:
    """Render a number as a plain int string when it is whole, else trimmed."""
    v = float(value)
    if v.is_integer():
        return str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _load_svg(icon_key: str):
    """Return (data_uri, view_w, view_h) for an icon, cropped to its glyph.

    Removes the OCI Library caption placeholder, computes the true content
    bounds from the path coordinates and rewrites only the root <svg>
    element's viewBox/width/height. Falls back to the declared viewBox for
    SVGs that are not in the simple OCI form. Raises ValueError for SVGs
    with no drawable content.
    """
    path = resolve_icon_path(icon_key)
    cache_key = str(path)
    if cache_key in _svg_cache:
        return _svg_cache[cache_key]

    svg_text = path.read_text(encoding="utf-8")
    if not _DRAWABLE_RE.search(svg_text):
        raise ValueError(f"Icon {icon_key!r} ({path}) has no drawable content")
    svg_text = _PLACEHOLDER_RE.sub("", svg_text)

    open_m = _SVG_OPEN_RE.search(svg_text)
    if not open_m:
        raise ValueError(f"Icon {icon_key!r} ({path}) is not an SVG document")
    open_tag = open_m.group(0)

    declared = None
    vb_m = re.search(r'viewBox="([^"]+)"', open_tag)
    if vb_m:
        parts = vb_m.group(1).replace(",", " ").split()
        if len(parts) == 4:
            try:
                declared = tuple(float(p) for p in parts)
            except ValueError:
                declared = None

    bbox = _svg_content_bbox(svg_text)
    if bbox and bbox[2] - bbox[0] > 1 and bbox[3] - bbox[1] > 1:
        pad = 1.0
        vb = (bbox[0] - pad, bbox[1] - pad,
              bbox[2] - bbox[0] + 2 * pad, bbox[3] - bbox[1] + 2 * pad)
    elif declared and declared[2] > 0 and declared[3] > 0:
        vb = declared
    else:
        w_m = re.search(r'\bwidth="([\d.]+)', open_tag)
        h_m = re.search(r'\bheight="([\d.]+)', open_tag)
        if w_m and h_m:
            vb = (0.0, 0.0, float(w_m.group(1)), float(h_m.group(1)))
        else:
            vb = (0.0, 0.0, float(ICON_W), float(ICON_H))

    new_open = _set_root_attr(open_tag, "viewBox", " ".join(_fmt_num(v) for v in vb))
    new_open = _set_root_attr(new_open, "width", _fmt_num(vb[2]))
    new_open = _set_root_attr(new_open, "height", _fmt_num(vb[3]))
    svg_text = svg_text[:open_m.start()] + new_open + svg_text[open_m.end():]

    encoded = urllib.parse.quote(svg_text, safe="")
    result = (f"data:image/svg+xml,{encoded}", float(vb[2]), float(vb[3]))
    _svg_cache[cache_key] = result
    return result


# ---------------------------------------------------------------------------
# Style profiles and container templates
# ---------------------------------------------------------------------------
STYLE_PROFILES = {
    # Reference look (the user's sample) with the official 12px container
    # labels; dashPattern 6 3 keeps dashed edges distinct from dashed borders.
    "default": dict(spacing_left=5, container_font=12, vcn_font=12, subnet_font=11,
                    arc_region=1, arc_ad=1, arc_fd=3, edge_width=1.5, edge_rounded=1,
                    edge_font=12, dash_pattern="6 3", dashed_arrow="none"),
    # Strict OCI Architecture Diagram Toolkit v24.2 values.
    "official": dict(spacing_left=5, container_font=12, vcn_font=12, subnet_font=12,
                     arc_region=1, arc_ad=8, arc_fd=7, edge_width=1, edge_rounded=0,
                     edge_font=10.5, dash_pattern=None, dashed_arrow="open"),
    # Byte-for-byte v1.0.0 sample styling.
    "v1.0": dict(spacing_left=3, container_font=12, vcn_font=13, subnet_font=11,
                 arc_region=1, arc_ad=1, arc_fd=3, edge_width=1.5, edge_rounded=1,
                 edge_font=12, dash_pattern="6 3", dashed_arrow="none"),
}
STYLE_PROFILES["sample"] = STYLE_PROFILES["v1.0"]

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

_CONTAINER_TAIL = "container=1;collapsible=0;expand=0;recursiveResize=0;"

BOX_STYLE = (
    "rounded=1;arcSize=12;whiteSpace=wrap;html=1;strokeWidth=1;"
    f"strokeColor={COLORS['ivy']};fillColor=#FFFFFF;fontFamily={{font}};fontSize=11;"
    f"fontColor={COLORS['text_primary']};align=center;verticalAlign=middle;"
)

GROUP_TYPES = (
    "region", "tenancy", "availability_domain", "fault_domain", "compartment",
    "vcn", "subnet", "services", "oracle_services_network", "onprem", "hub",
    "other", "metro_or_realm", "third_party_cloud", "internet", "drg",
)
DRG_ICON_STEM = "networking_dynamic_routing_gateway_drg"


def _build_group_styles(profile: dict, font: str) -> dict:
    c = dict(COLORS)
    p = profile
    common = f"whiteSpace=wrap;html=1;fontFamily={font};verticalAlign=top;"
    left = f"align=left;spacingLeft={p['spacing_left']};"
    location = (
        f"{common}rounded=1;arcSize={p['arc_region']};strokeWidth=1;"
        f"fillColor={c['region_fill']};strokeColor={c['region_stroke']};"
        f"fontSize={p['container_font']};fontStyle=1;fontColor={c['text_primary']};"
        f"{left}spacingRight=5;{_CONTAINER_TAIL}"
    )
    location_center = location.replace(left, "align=center;")
    styles = {
        "region": location,
        "onprem": location,
        "third_party_cloud": location_center,
        "internet": location_center,
        "tenancy": (
            f"{common}rounded=0;strokeWidth=1;dashed=1;fillColor=none;"
            f"strokeColor={c['region_stroke']};fontSize={p['container_font']};fontStyle=0;"
            f"fontColor={c['text_primary']};{left}{_CONTAINER_TAIL}"
        ),
        "availability_domain": (
            f"{common}rounded=1;arcSize={p['arc_ad']};strokeWidth=1;"
            f"fillColor={c['neutral_2']};strokeColor={c['region_stroke']};"
            f"fontSize={p['container_font']};fontStyle=1;fontColor={c['text_primary']};"
            f"align=center;{_CONTAINER_TAIL}"
        ),
        "fault_domain": (
            f"{common}rounded=1;arcSize={p['arc_fd']};strokeWidth=1;"
            f"fillColor={c['air']};strokeColor={c['region_stroke']};"
            f"fontSize={p['container_font']};fontStyle=1;fontColor={c['text_primary']};"
            f"align=center;{_CONTAINER_TAIL}"
        ),
        "compartment": (
            f"{common}rounded=0;strokeWidth=1;dashed=1;dashPattern=1 1;fillColor=none;"
            f"strokeColor={c['vcn_stroke']};fontSize={p['container_font']};fontStyle=1;"
            f"fontColor={c['text_primary']};{left}{_CONTAINER_TAIL}"
        ),
        "vcn": (
            f"{common}rounded=0;strokeWidth=2;dashed=1;fillColor=none;"
            f"strokeColor={c['vcn_stroke']};labelBackgroundColor=none;"
            f"fontSize={p['vcn_font']};fontStyle=1;fontColor={c['vcn_label']};"
            f"{left}{_CONTAINER_TAIL}"
        ),
        "subnet": (
            f"{common}rounded=0;strokeWidth=1;dashed=1;fillColor=none;"
            f"strokeColor={c['vcn_stroke']};fontSize={p['subnet_font']};fontStyle=1;"
            f"fontColor={c['vcn_label']};{left}{_CONTAINER_TAIL}"
        ),
        "services": (
            f"{common}rounded=0;strokeWidth=1;dashed=1;fillColor=none;"
            f"strokeColor={c['text_primary']};fontSize=11;fontStyle=1;"
            f"fontColor={c['text_primary']};{left}{_CONTAINER_TAIL}"
        ),
        "oracle_services_network": (
            f"{common}rounded=0;strokeWidth=1;dashed=1;fillColor={c['air']};"
            f"strokeColor={c['rose']};fontSize={p['container_font']};fontStyle=1;"
            f"fontColor={c['rose']};align=center;{_CONTAINER_TAIL}"
        ),
        "metro_or_realm": (
            f"{common}rounded=0;strokeWidth=2;dashed=1;fillColor=none;"
            f"strokeColor={c['region_stroke']};fontSize={p['container_font']};fontStyle=1;"
            f"fontColor={c['text_primary']};{left}{_CONTAINER_TAIL}"
        ),
        "other": (
            f"{common}rounded=1;arcSize=10;strokeWidth=1;dashed=1;fillColor=none;"
            f"strokeColor={c['text_primary']};fontSize=11;fontStyle=1;"
            f"fontColor={c['text_primary']};align=center;{_CONTAINER_TAIL}"
        ),
        "drg": (
            f"{common}rounded=1;arcSize=10;strokeWidth=1;dashed=1;fillColor=none;"
            f"strokeColor={c['text_primary']};fontSize=11;fontStyle=1;"
            f"fontColor={c['text_primary']};{left}{_CONTAINER_TAIL}"
        ),
    }
    styles["hub"] = styles["onprem"]  # deprecated alias
    # ``ociGroup`` lets validate_file() recognise VCNs / subnets in written files.
    return {gt: st.replace(_CONTAINER_TAIL, f"ociGroup={'onprem' if gt == 'hub' else gt};{_CONTAINER_TAIL}")
            for gt, st in styles.items()}


# Module-level view for documentation/tests (default profile, default font).
_GROUP_STYLES = _build_group_styles(STYLE_PROFILES["default"], FONT_STACK)


def _style_tokens(style: str) -> dict:
    """Parse 'k=v;k2=v2;flag;' into an ordered dict (last occurrence wins)."""
    out = {}
    for tok in (style or "").split(";"):
        if not tok:
            continue
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
        else:
            out[tok] = None
    return out


def _tokens_to_style(tokens: dict) -> str:
    parts = []
    for k, v in tokens.items():
        parts.append(k if v is None else f"{k}={v}")
    return ";".join(parts) + (";" if parts else "")


def _merge_style(base: str, extra: str) -> str:
    """Merge style strings; keys in extra override keys in base."""
    if not extra:
        return base
    tokens = _style_tokens(base)
    tokens.update(_style_tokens(extra))
    return _tokens_to_style(tokens)


_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>|\n", re.I)


def escape_label(text) -> str:
    """HTML-escape a plain-text label and turn newlines into <br>."""
    if text is None:
        return ""
    return _html.escape(str(text), quote=False).replace("\n", "<br>")


def label_lines(text: str, width_px: float, font_size: float = LABEL_FONT_SIZE) -> int:
    """Estimate how many lines an HTML/plain label needs at a given width."""
    if not text:
        return 1
    cw = max(1.0, font_size * 0.56)
    max_chars = max(1, int(width_px / cw))
    total = 0
    for para in _BR_RE.split(text):
        para = _html.unescape(_TAG_RE.sub("", para)).strip()
        if not para:
            total += 1
            continue
        n, cur = 1, 0
        for word in para.split():
            wl = len(word)
            if cur == 0:
                cur = wl
            elif cur + 1 + wl <= max_chars:
                cur += 1 + wl
            else:
                n += 1
                cur = wl
            while cur > max_chars:
                n += 1
                cur -= max_chars
        total += n
    return total


def _slug(key: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(key)).strip("-")
    if not s or s in ("0", "1"):
        raise ValueError(f"Invalid cell key {key!r}")
    return s


# ---------------------------------------------------------------------------
# Cell registry + validation (works on any mxGraphModel <root>)
# ---------------------------------------------------------------------------
_WRAPPERS = ("object", "UserObject")


def _iter_cells(root):
    """Yield (id, entry) for each cell under <root>, unwrapping objects."""
    for el in root:
        if el.tag == "mxCell":
            cell, value = el, el.get("value", "")
            cid = el.get("id")
        elif el.tag in _WRAPPERS:
            cell = el.find("mxCell")
            if cell is None:
                continue
            value = el.get("label", "")
            cid = el.get("id")
        else:
            continue
        if cid is None:
            continue
        geom = cell.find("mxGeometry")
        entry = {
            "value": value or "",
            "style": cell.get("style", "") or "",
            "parent": cell.get("parent"),
            "vertex": cell.get("vertex"),
            "edge": cell.get("edge"),
            "source": cell.get("source"),
            "target": cell.get("target"),
            "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0,
            "points": [],
            "rel_x": None,
        }
        if geom is not None:
            entry["x"] = float(geom.get("x", 0) or 0)
            entry["y"] = float(geom.get("y", 0) or 0)
            entry["w"] = float(geom.get("width", 0) or 0)
            entry["h"] = float(geom.get("height", 0) or 0)
            if geom.get("relative") == "1" and geom.get("x") is not None:
                entry["rel_x"] = float(geom.get("x"))
            arr = geom.find("Array")
            if arr is not None and arr.get("as") == "points":
                for pt in arr.findall("mxPoint"):
                    entry["points"].append((float(pt.get("x", 0) or 0), float(pt.get("y", 0) or 0)))
        yield cid, entry


def build_cell_registry(root) -> dict:
    """Map cell id -> entry for every mxCell/object/UserObject under <root>."""
    registry = {}
    for cid, entry in _iter_cells(root):
        registry[cid] = entry
    return registry


def _kind(entry: dict) -> str:
    if entry.get("edge") == "1":
        return "edge"
    tokens = _style_tokens(entry.get("style", ""))
    if entry.get("vertex") != "1":
        return "layer" if entry.get("parent") == "0" else "other"
    if tokens.get("container") == "1":
        return "group"
    if tokens.get("shape") == "image":
        return "icon"
    if "text" in tokens:
        return "text"
    return "other"


class _Box:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = float(x), float(y), float(w), float(h)

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    def intersects(self, o, tol=0.5) -> bool:
        return (self.x + tol < o.right and o.x + tol < self.right
                and self.y + tol < o.bottom and o.y + tol < self.bottom)

    def contains(self, o, tol=0.5) -> bool:
        return (o.x >= self.x - tol and o.y >= self.y - tol
                and o.right <= self.right + tol and o.bottom <= self.bottom + tol)

    def __repr__(self):
        return f"[x={_fmt_num(self.x)},y={_fmt_num(self.y)},w={_fmt_num(self.w)},h={_fmt_num(self.h)}]"


def _abs_boxes(registry: dict) -> dict:
    """Absolute bounding boxes for every vertex (page coordinates)."""
    cache = {}

    def origin(cid, depth=0):
        if cid in cache:
            return cache[cid]
        e = registry.get(cid)
        if e is None or cid in ("0", "1") or depth > 200:
            return (0.0, 0.0)
        if e.get("parent") in (None, "0"):   # layer
            cache[cid] = (0.0, 0.0)
            return cache[cid]
        px, py = origin(e["parent"], depth + 1)
        cache[cid] = (px + e["x"], py + e["y"])
        return cache[cid]

    boxes = {}
    for cid, e in registry.items():
        if e.get("vertex") == "1":
            ax, ay = origin(cid)
            boxes[cid] = _Box(ax, ay, e["w"], e["h"])
    return boxes


def _is_ancestor(registry, anc, cid) -> bool:
    cur = registry.get(cid, {}).get("parent")
    hops = 0
    while cur not in (None, "0", "1") and hops < 200:
        if cur == anc:
            return True
        cur = registry.get(cur, {}).get("parent")
        hops += 1
    return False


def _label_of(e: dict) -> str:
    v = _html.unescape(_TAG_RE.sub(" ", e.get("value", "") or ""))
    v = re.sub(r"\s+", " ", v).strip()
    if not v and e.get("caption"):
        return e["caption"][:60]
    return v[:60] if v else "(unlabelled)"


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


def _attach_captions(registry: dict, boxes: dict) -> None:
    """Name icon cells after the caption text cell sitting right below them."""
    texts = [(cid, e) for cid, e in registry.items()
             if e.get("vertex") == "1" and _kind(e) == "text" and cid in boxes]
    for cid, e in registry.items():
        if e.get("vertex") != "1" or _kind(e) != "icon" or cid not in boxes:
            continue
        ib = boxes[cid]
        best = None
        for tid, te in texts:
            if te.get("parent") != e.get("parent"):
                continue
            tb = boxes[tid]
            if tb.x - 1 <= ib.cx <= tb.right + 1 and -2 <= tb.y - ib.bottom <= 40:
                gap = tb.y - ib.bottom
                if best is None or gap < best[0]:
                    best = (gap, tid, te)
        if best is not None:
            _, tid, te = best
            e["caption"] = re.sub(r"\s+", " ", _html.unescape(_TAG_RE.sub(" ", te.get("value", "")))).strip()
            te["owner"] = cid


def _seg_hits_box(a, b, box: _Box, tol=0.5) -> bool:
    """Axis-aligned segment a->b intersects the interior of box."""
    (x1, y1), (x2, y2) = a, b
    if abs(y1 - y2) <= 1e-6:  # horizontal
        y = y1
        return (box.y + tol < y < box.bottom - tol
                and max(x1, x2) > box.x + tol and min(x1, x2) < box.right - tol)
    if abs(x1 - x2) <= 1e-6:  # vertical
        x = x1
        return (box.x + tol < x < box.right - tol
                and max(y1, y2) > box.y + tol and min(y1, y2) < box.bottom - tol)
    # diagonal: sample
    steps = 8
    for i in range(steps + 1):
        t = i / steps
        px, py = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
        if box.x + tol < px < box.right - tol and box.y + tol < py < box.bottom - tol:
            return True
    return False


def _orthogonalize(points, horizontal_first=True):
    poly = [points[0]]
    for a, b in zip(points, points[1:]):
        if abs(a[0] - b[0]) > 0.5 and abs(a[1] - b[1]) > 0.5:
            poly.append((b[0], a[1]) if horizontal_first else (a[0], b[1]))
        poly.append(b)
    return poly


def _edge_polyline(registry, boxes, e):
    """Estimate the polyline draw.io will draw for an edge (absolute coords)."""
    s, t = e.get("source"), e.get("target")
    if s not in boxes or t not in boxes:
        return None
    sb, tb = boxes[s], boxes[t]
    tok = _style_tokens(e.get("style", ""))

    def port(b, kx, ky):
        return (b.x + b.w * float(kx), b.y + b.h * float(ky))

    p0 = port(sb, tok["exitX"], tok["exitY"]) if tok.get("exitX") and tok.get("exitY") else None
    p1 = port(tb, tok["entryX"], tok["entryY"]) if tok.get("entryX") and tok.get("entryY") else None
    parent = e.get("parent")
    if parent in (None, "0", "1") or parent not in registry:
        ox, oy = 0.0, 0.0
    else:
        pb = boxes.get(parent)
        ox, oy = (pb.x, pb.y) if pb else (0.0, 0.0)
    pts = [(ox + px, oy + py) for px, py in e.get("points", [])]
    if p0 is None:
        p0 = (sb.cx, sb.cy) if not pts else _nearest_port(sb, pts[0])
    if p1 is None:
        p1 = (tb.cx, tb.cy) if not pts else _nearest_port(tb, pts[-1])
    if p0 is None or p1 is None:
        return None
    horizontal_first = tok.get("exitY") == "0.5" if tok.get("exitY") else abs(p1[0] - p0[0]) >= abs(p1[1] - p0[1])
    return _orthogonalize([p0] + pts + [p1], horizontal_first)


def _nearest_port(b: _Box, pt):
    cands = [(b.cx, b.y), (b.cx, b.bottom), (b.x, b.cy), (b.right, b.cy)]
    return min(cands, key=lambda c: (c[0] - pt[0]) ** 2 + (c[1] - pt[1]) ** 2)


def validate_registry(registry: dict, page: str = "", strict: bool = False,
                      max_label_lines: int = MAX_LABEL_LINES):
    """Validate one page's cell registry. Returns (errors, warnings)."""
    errors, warnings = [], []
    prefix = f"[page: {page}] " if page else ""
    kinds = {cid: _kind(e) for cid, e in registry.items() if cid not in ("0", "1")}
    boxes = _abs_boxes(registry)
    _attach_captions(registry, boxes)
    # Only vertices with geometry take part in the geometric checks
    kinds = {cid: k for cid, k in kinds.items()
             if k == "edge" or k == "layer" or cid in boxes}

    # 1. referential integrity
    for cid, e in registry.items():
        if cid in ("0", "1"):
            continue
        parent = e.get("parent")
        if parent not in ("0", "1") and parent not in registry:
            errors.append(f"{prefix}ERROR: cell '{_label_of(e)}' (id {cid}) has unknown parent id {parent!r}; "
                          f"draw.io drops the rest of the diagram when a parent is missing")
        if kinds.get(cid) == "edge":
            for end in ("source", "target"):
                ref = e.get(end)
                if ref is not None and ref not in registry:
                    errors.append(f"{prefix}ERROR: edge '{_label_of(e)}' (id {cid}) {end} id {ref!r} does not exist")
                elif ref is not None and kinds.get(ref) == "edge":
                    warnings.append(f"{prefix}WARNING: edge {cid} {end} is another edge ({ref})")

    # 2. container overlaps (any two containers not in an ancestor relation)
    containers = [cid for cid, k in kinds.items() if k == "group"]
    for i in range(len(containers)):
        for j in range(i + 1, len(containers)):
            a, b = containers[i], containers[j]
            if _is_ancestor(registry, a, b) or _is_ancestor(registry, b, a):
                continue
            ba, bb = boxes[a], boxes[b]
            if ba.intersects(bb):
                pa = registry[a]["parent"]
                where = "siblings" if pa == registry[b]["parent"] else "different parents"
                errors.append(
                    f"{prefix}OVERLAP: '{_label_of(registry[a])}' [abs {ba!r}] intersects "
                    f"'{_label_of(registry[b])}' [abs {bb!r}] ({where})")

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
            # Only a caption whose icon actually straddles the border is
            # excused; a caption that spills out of a parent its icon fits in
            # is the too-short-container defect fit_to_children() prevents.
            ob = _Box(owner["x"], owner["y"], owner["w"], owner["h"])
            if not pbox.contains(ob, tol=1.0) and _centre_within(pbox, ob, STRADDLE_TOL):
                continue
        errors.append(
            f"{prefix}ERROR: '{_label_of(e)}' [{local!r}] extends outside its parent "
            f"'{_label_of(registry[parent])}' [w={_fmt_num(pbox.w)},h={_fmt_num(pbox.h)}]")

    # 4. non-container vertex collisions (icons, captions, texts)
    leaves = [cid for cid, k in kinds.items() if k in ("icon", "text", "other")]
    for i in range(len(leaves)):
        for j in range(i + 1, len(leaves)):
            a, b = leaves[i], leaves[j]
            if _is_ancestor(registry, a, b) or _is_ancestor(registry, b, a):
                continue
            ba, bb = boxes[a], boxes[b]
            if ba.w <= 0 or bb.w <= 0:
                continue
            if ba.intersects(bb, tol=1.0):
                errors.append(
                    f"{prefix}ERROR: '{_label_of(registry[a])}' [abs {ba!r}] overlaps "
                    f"'{_label_of(registry[b])}' [abs {bb!r}]")

    # 5. long captions
    for cid, e in registry.items():
        if kinds.get(cid) != "text":
            continue
        tok = _style_tokens(e["style"])
        if tok.get("whiteSpace") != "wrap" or e["w"] <= 0:
            continue
        try:
            fs = float(tok.get("fontSize", LABEL_FONT_SIZE))
        except ValueError:
            fs = LABEL_FONT_SIZE
        n = label_lines(e["value"], e["w"] - 4, fs)
        if n > max_label_lines and e["h"] < n * fs * 1.25:
            warnings.append(
                f"{prefix}WARNING: caption '{_label_of(e)}' needs ~{n} lines at {_fmt_num(fs)}px in "
                f"{_fmt_num(e['w'])}px but its box is {_fmt_num(e['h'])}px tall")

    # 6. estimated edge crossings through icons/captions that are not endpoints
    obstacles = {cid: boxes[cid] for cid in leaves if boxes[cid].w > 0}
    for cid, e in registry.items():
        if kinds.get(cid) != "edge":
            continue
        poly = _edge_polyline(registry, boxes, e)
        if not poly:
            continue
        hit = []
        for oid, ob in obstacles.items():
            if oid in (e.get("source"), e.get("target")):
                continue
            if any(_seg_hits_box(a, b, ob) for a, b in zip(poly, poly[1:])):
                hit.append(_label_of(registry[oid]))
        if hit:
            msg = (f"{prefix}{'ERROR' if strict else 'WARNING'}: edge '{_label_of(e) or cid}' "
                   f"({_label_of(registry.get(e.get('source'), {}))} -> "
                   f"{_label_of(registry.get(e.get('target'), {}))}) is estimated to cross: "
                   + ", ".join(hit[:5]) + (" ..." if len(hit) > 5 else ""))
            (errors if strict else warnings).append(msg)

    # 7. foreign containment: a leaf drawn inside a VCN / subnet it does not
    #    belong to (the team's diagram guidelines: a box asserts location). A
    #    DRG inside any VCN box is an error even when its parent chain is right.
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

    if not any(k in ("group", "icon", "text") for k in kinds.values()):
        warnings.append(f"{prefix}WARNING: page has no containers, icons or text")
    return errors, warnings


def find_container_overlaps(root) -> list:
    """Compatibility wrapper: container overlaps + containment errors only."""
    errors, _ = validate_registry(build_cell_registry(root))
    return [e for e in errors if e.startswith(("OVERLAP", "ERROR"))]


def _decompress_diagram(text: str) -> str:
    data = base64.b64decode("".join(text.split()))
    try:
        raw = zlib.decompress(data, -15)
    except zlib.error:
        raw = zlib.decompress(data)
    return urllib.parse.unquote(raw.decode("utf-8"))


def validate_file(path, strict: bool = False):
    """Validate every page of a .drawio file.

    Returns (errors, warnings, pages, containers). Compressed pages are
    inflated transparently. Raises ET.ParseError / ValueError on bad input.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    mxfile = ET.fromstring(text)
    diagrams = mxfile.findall("diagram") if mxfile.tag == "mxfile" else []
    if not diagrams and mxfile.tag == "mxGraphModel":
        diagrams = [None]
    errors, warnings, containers = [], [], 0
    multi = len(diagrams) > 1
    for diagram in diagrams:
        if diagram is None:
            model, name = mxfile, ""
        else:
            name = (diagram.get("name") or diagram.get("id", "")) if multi else ""
            model = diagram.find("mxGraphModel")
            if model is None:
                inner = (diagram.text or "").strip()
                if not inner:
                    warnings.append(f"[page: {name}] WARNING: empty page" if name else "WARNING: empty page")
                    continue
                try:
                    model = ET.fromstring(_decompress_diagram(inner))
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(f"could not decode compressed diagram content: {exc}") from exc
        root = model.find("root")
        if root is None:
            warnings.append(f"[page: {name}] WARNING: no <root>" if name else "WARNING: no <root>")
            continue
        registry = build_cell_registry(root)
        containers += sum(1 for e in registry.values() if _kind(e) == "group")
        e, w = validate_registry(registry, page=name, strict=strict)
        errors.extend(e)
        warnings.extend(w)
    return errors, warnings, len(diagrams), containers


# ---------------------------------------------------------------------------
# draw.io desktop CLI rendering
# ---------------------------------------------------------------------------
def find_drawio_binary() -> Optional[str]:
    """Locate the draw.io desktop executable, if installed."""
    env = os.environ.get("DRAWIO_BIN")
    if env and Path(env).exists():
        return env
    for name in ("drawio", "draw.io"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        "/Applications/draw.io.app/Contents/MacOS/draw.io",
        str(Path.home() / "Applications/draw.io.app/Contents/MacOS/draw.io"),
        "/opt/drawio/drawio", "/usr/bin/drawio", "/snap/bin/drawio",
        r"C:\Program Files\draw.io\draw.io.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def render(drawio_path, fmt: str = "png", out=None, scale: float = 1.0,
           timeout: int = 120) -> Optional[Path]:
    """Export a .drawio file with the draw.io desktop CLI.

    Returns the output path, or None when no draw.io binary is available.
    Raises RuntimeError when the export fails.
    """
    binary = find_drawio_binary()
    if not binary:
        return None
    src = Path(drawio_path)
    out_path = Path(out) if out else src.with_suffix(f".{fmt}")
    cmd = [binary, "-x", "-f", fmt]
    if fmt in ("png", "jpg") and scale != 1.0:
        cmd += ["-s", str(scale)]
    cmd += ["-o", str(out_path), str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0 or not out_path.exists():
        raise RuntimeError(f"draw.io export failed ({proc.returncode}): {proc.stderr.strip()[-400:]}")
    return out_path


# ---------------------------------------------------------------------------
# XML builder
# ---------------------------------------------------------------------------
class DrawioBuilder:
    """Builds a draw.io XML document (one or more pages)."""

    _RESERVED_METADATA_KEYS = {"id", "label", "placeholders", "tooltip", "link"}
    _METADATA_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
    _PORTS = {"R": (1.0, 0.5), "L": (0.0, 0.5), "T": (0.5, 0.0), "B": (0.5, 1.0)}

    def __init__(self, page_name="Architecture", width=1600, height=1100,
                 style_profile="default", font_family=None):
        if style_profile not in STYLE_PROFILES:
            raise ValueError(f"Unknown style_profile {style_profile!r}; choose from {sorted(STYLE_PROFILES)}")
        self.profile_name = style_profile
        self.profile = STYLE_PROFILES[style_profile]
        self.font = font_family or FONT_STACK
        self._group_styles = _build_group_styles(self.profile, self.font)
        self._cell_id = 1
        self._ids = set()
        self._cells = {}          # id -> registry entry (kind, geometry, parent, page, ...)
        self._pending_routes = []
        self._pages = []
        self._page_idx = -1
        self.mxfile = ET.Element("mxfile", host="Python", type="device", compressed="false")
        self.add_page(page_name, width, height)

    # -- pages / layers ------------------------------------------------------
    @property
    def page(self) -> dict:
        return self._pages[self._page_idx]

    @property
    def root(self):
        return self.page["root"]

    @property
    def diagram(self):
        return self.page["diagram"]

    @property
    def model(self):
        return self.page["model"]

    def add_page(self, name: str, width: int = 1600, height: int = 1100) -> int:
        """Append a new page and make it current. Returns the page index."""
        idx = len(self._pages)
        diagram = ET.SubElement(self.mxfile, "diagram", id=f"page{idx + 1}", name=str(name))
        model = ET.SubElement(
            diagram, "mxGraphModel",
            dx="0", dy="0", grid="1", gridSize="10", guides="1", tooltips="1",
            connect="1", arrows="1", fold="1", page="1", pageScale="1",
            pageWidth=str(int(width)), pageHeight=str(int(height)),
            math="0", shadow="0", background="#FFFFFF",
        )
        root = ET.SubElement(model, "root")
        ET.SubElement(root, "mxCell", id="0")
        ET.SubElement(root, "mxCell", id="1", parent="0")
        self._pages.append({"name": str(name), "diagram": diagram, "model": model,
                            "root": root, "width": int(width), "height": int(height),
                            "layers": ["1"]})
        self._page_idx = idx
        return idx

    def use_page(self, index_or_name) -> int:
        """Make an existing page current (by index or name)."""
        if isinstance(index_or_name, int):
            if not 0 <= index_or_name < len(self._pages):
                raise IndexError(f"No page {index_or_name}")
            self._page_idx = index_or_name
        else:
            for i, p in enumerate(self._pages):
                if p["name"] == index_or_name:
                    self._page_idx = i
                    break
            else:
                raise KeyError(f"No page named {index_or_name!r}")
        return self._page_idx

    def add_layer(self, name: str, visible: bool = True, key=None) -> str:
        """Add a named layer to the current page; returns its id (use as parent)."""
        cid = self._new_id(key)
        attrs = {"id": cid, "value": str(name), "parent": "0"}
        if not visible:
            attrs["visible"] = "0"
        ET.SubElement(self.root, "mxCell", **attrs)
        self._cells[cid] = {"kind": "layer", "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0,
                            "parent": "0", "page": self._page_idx, "label": str(name)}
        self.page["layers"].append(cid)
        return cid

    # -- ids / registry ------------------------------------------------------
    def _new_id(self, key=None) -> str:
        if key is not None:
            cid = _slug(key)
            if cid in self._ids:
                raise ValueError(f"Duplicate cell key {key!r}")
            self._ids.add(cid)
            return cid
        while True:
            self._cell_id += 1
            cid = str(self._cell_id)
            if cid not in self._ids:
                self._ids.add(cid)
                return cid

    def _next_id(self) -> str:  # backwards compatibility
        return self._new_id()

    def _check_parent(self, parent, what: str) -> str:
        if parent is None:
            raise ValueError(f"{what}: parent must be a cell id (use '1' for the default layer)")
        parent = str(parent)
        if parent == "1":
            return parent
        entry = self._cells.get(parent)
        if entry is None:
            raise ValueError(f"{what}: unknown parent id {parent!r}. Pass the id returned by add_group()/add_layer()")
        if entry["kind"] == "edge":
            raise ValueError(f"{what}: parent {parent!r} is an edge")
        if entry["page"] != self._page_idx:
            raise ValueError(f"{what}: parent {parent!r} lives on another page")
        return parent

    def _register(self, cid, kind, x, y, w, h, parent, label="", **extra):
        entry = {"kind": kind, "x": float(x), "y": float(y), "w": float(w), "h": float(h),
                 "parent": parent, "page": self._page_idx, "label": label}
        entry.update(extra)
        self._cells[cid] = entry
        return entry

    def _origin(self, cid) -> tuple:
        ox = oy = 0.0
        cur = cid
        hops = 0
        while cur not in (None, "1") and hops < 200:
            e = self._cells.get(cur)
            if e is None or e["kind"] == "layer":
                break
            ox += e["x"]
            oy += e["y"]
            cur = e["parent"]
            hops += 1
        return ox, oy

    def _abs_cell(self, cid):
        """Absolute (x, y, w, h) of the cell's own geometry (icon: image cell)."""
        e = self._cells[cid]
        ox, oy = self._origin(e["parent"])
        return (ox + e["x"], oy + e["y"], e["w"], e["h"])

    def bbox(self, cid) -> tuple:
        """Local (x, y, w, h) of a cell (icon: its slot)."""
        e = self._cells[cid]
        if e["kind"] == "icon":
            return (e["slot_x"], e["slot_y"], e["slot_w"], e["slot_h"])
        return (e["x"], e["y"], e["w"], e["h"])

    def abs_bbox(self, cid) -> tuple:
        """Absolute page (x, y, w, h) of a cell (icon: its slot)."""
        e = self._cells[cid]
        x, y, w, h = self.bbox(cid)
        ox, oy = self._origin(e["parent"])
        return (ox + x, oy + y, w, h)

    def footprint(self, cid) -> tuple:
        """Local (x, y, w, h) covering an icon slot and its caption."""
        e = self._cells[cid]
        x, y, w, h = self.bbox(cid)
        lid = e.get("label_id")
        if lid and lid in self._cells:
            l = self._cells[lid]
            x0, y0 = min(x, l["x"]), min(y, l["y"])
            x1, y1 = max(x + w, l["x"] + l["w"]), max(y + h, l["y"] + l["h"])
            return (x0, y0, x1 - x0, y1 - y0)
        return (x, y, w, h)

    def _common_ancestor(self, a, b) -> str:
        def chain(cid):
            out = []
            cur = self._cells.get(cid, {}).get("parent")
            hops = 0
            while cur is not None and hops < 200:
                out.append(cur)
                if cur == "1":
                    break
                e = self._cells.get(cur)
                if e is None or e["kind"] == "layer":
                    break
                cur = e["parent"]
                hops += 1
            return out
        ca, cb = chain(a), set(chain(b))
        for cid in ca:
            if cid in cb:
                return cid
        return "1"

    # -- emitters ------------------------------------------------------------
    def _emit_vertex(self, value, style, parent, x, y, w, h,
                     metadata=None, tooltip=None, cid=None, link=None) -> str:
        cid = cid or self._new_id()
        value = "" if value is None else str(value)
        if metadata or tooltip is not None or link:
            obj_attrs = {"id": cid, "label": value, "placeholders": "1"}
            if tooltip is not None:
                obj_attrs["tooltip"] = str(tooltip)
            if link:
                obj_attrs["link"] = str(link)
            if metadata:
                for key, val in metadata.items():
                    if not self._METADATA_KEY_RE.fullmatch(str(key)) or key in self._RESERVED_METADATA_KEYS:
                        raise ValueError(
                            f"Invalid metadata key {key!r}: must match ^[A-Za-z_][A-Za-z0-9_-]*$ "
                            f"and not be one of {sorted(self._RESERVED_METADATA_KEYS)}")
                    obj_attrs[str(key)] = str(val)
            obj = ET.SubElement(self.root, "UserObject" if link else "object", **obj_attrs)
            cell = ET.SubElement(obj, "mxCell", style=style, vertex="1", parent=parent)
        else:
            cell = ET.SubElement(self.root, "mxCell", id=cid, value=value, style=style,
                                 vertex="1", parent=parent)
        ET.SubElement(cell, "mxGeometry", x=_fmt_num(x), y=_fmt_num(y),
                      width=_fmt_num(w), height=_fmt_num(h)).set("as", "geometry")
        return cid

    def _find_cell_element(self, cid):
        for el in self.root:
            if el.get("id") == cid:
                return el.find("mxCell") if el.tag in _WRAPPERS else el
        return None

    def _set_geometry(self, cid, **attrs):
        el = self._find_cell_element(cid)
        if el is None:
            return
        geom = el.find("mxGeometry")
        if geom is None:
            return
        for k, v in attrs.items():
            geom.set(k, _fmt_num(v) if isinstance(v, (int, float)) else str(v))

    # -- containers ----------------------------------------------------------
    def add_group(self, label, x, y, w, h, parent="1", group_type="region",
                  metadata=None, tooltip=None, label_position=None, style_extra="",
                  key=None, link=None, raw_html=False) -> str:
        """Add a container rectangle. Returns its cell id (use as parent).

        group_type: region, tenancy, availability_domain, fault_domain,
        compartment, vcn, subnet, services, oracle_services_network, onprem,
        other, metro_or_realm, third_party_cloud, internet, drg (hub = onprem).
        label_position: "left" or "center" to override the template.
        """
        if group_type not in self._group_styles:
            raise ValueError(f"Unknown group_type {group_type!r}. Valid group types: {sorted(GROUP_TYPES)}")
        parent = self._check_parent(parent, "add_group")
        if w <= 0 or h <= 0:
            raise ValueError(f"add_group({label!r}): width and height must be positive")
        style = self._group_styles[group_type]
        if label_position == "center":
            style = _merge_style(style, "align=center;")
            tokens = _style_tokens(style)
            tokens.pop("spacingLeft", None)
            style = _tokens_to_style(tokens)
        elif label_position == "left":
            style = _merge_style(style, f"align=left;spacingLeft={self.profile['spacing_left']};")
        elif label_position is not None:
            raise ValueError("label_position must be 'left', 'center' or None")
        style = _merge_style(style, style_extra)
        text = str(label) if raw_html else escape_label(label)
        cid = self._emit_vertex(text, style, parent, x, y, w, h,
                                metadata=metadata, tooltip=tooltip,
                                cid=self._new_id(key) if key is not None else None, link=link)
        self._register(cid, "group", x, y, w, h, parent, label=text, group_type=group_type)
        return cid

    # -- icons ----------------------------------------------------------------
    def add_icon(self, label, icon_key, x, y, parent="1", w=None, h=None,
                 metadata=None, tooltip=None, key=None, label_w=None, label_h=None,
                 raw_html=False, font_size=None, link=None, label_fill=None) -> str:
        """Add an OCI icon with a caption below. Returns the icon cell id.

        (x, y) is the top-left of a ICON_W x ICON_H slot; the glyph is fitted
        into GLYPH_W x GLYPH_H at the top of the slot so every icon renders
        at the same visual size, and the caption (a separate, non-connectable
        text cell) starts LABEL_GAP below the slot, centred on it. Passing
        w and/or h sizes the image cell explicitly instead (the caption then
        follows the cell).

        label_fill: opaque caption background (e.g. COLORS["region_fill"])
        for icons that straddle a dashed border.
        """
        parent = self._check_parent(parent, "add_icon")
        data_uri, nw, nh = _load_svg(icon_key)
        if nw <= 0 or nh <= 0:
            nw, nh = float(GLYPH_W), float(GLYPH_H)

        if w is None and h is None:
            scale = min(GLYPH_W / nw, GLYPH_H / nh)
            cell_w = max(1, round(nw * scale))
            cell_h = max(1, round(nh * scale))
            cell_x = x + round((ICON_W - cell_w) / 2)
            cell_y = y + GLYPH_TOP + round((GLYPH_H - cell_h) / 2)
            slot = (x, y, ICON_W, ICON_H)
        else:
            if h is None:
                cell_w, cell_h = w, max(1, round(w * nh / nw))
            elif w is None:
                cell_w, cell_h = max(1, round(h * nw / nh)), h
            else:
                cell_w, cell_h = w, h
            cell_x, cell_y = x, y
            slot = (x, y, cell_w, cell_h)

        role = ""
        try:
            if resolve_icon_path(icon_key).stem == DRG_ICON_STEM:
                role = "ociRole=drg;"
        except (KeyError, ValueError, FileNotFoundError):
            role = ""
        style = (
            "shape=image;verticalLabelPosition=bottom;verticalAlign=top;"
            f"imageAspect=1;aspect=fixed;{role}image={data_uri};"
        )
        cid = self._emit_vertex("", style, parent, cell_x, cell_y, cell_w, cell_h,
                                metadata=metadata, tooltip=tooltip,
                                cid=self._new_id(key) if key is not None else None, link=link)
        entry = self._register(cid, "icon", cell_x, cell_y, cell_w, cell_h, parent,
                               label="", icon_key=icon_key,
                               slot_x=slot[0], slot_y=slot[1], slot_w=slot[2], slot_h=slot[3],
                               label_id=None)

        text = str(label) if raw_html else escape_label(label)
        if text:
            fs = font_size or LABEL_FONT_SIZE
            lw = label_w if label_w is not None else (max(LABEL_W, cell_w + 30) if (w is not None or h is not None) else LABEL_W)
            lines = label_lines(text, lw - 4, fs)
            lh = label_h if label_h is not None else max(LABEL_H, lines * LABEL_LINE_H + 4)
            slot_cx = slot[0] + slot[2] / 2
            label_x = round(slot_cx - lw / 2)
            label_y = slot[1] + slot[3] + LABEL_GAP
            lid = self._new_id(f"{cid}-label" if key is not None else None)
            label_style = (
                f"text;html=1;strokeColor=none;fillColor={label_fill or 'none'};align=center;"
                "verticalAlign=top;whiteSpace=wrap;rounded=0;connectable=0;"
                f"fontFamily={self.font};fontSize={_fmt_num(fs)};fontStyle=0;"
                f"fontColor={COLORS['text_primary']};"
            )
            lc = ET.SubElement(self.root, "mxCell", id=lid, value=text, style=label_style,
                               vertex="1", parent=parent)
            ET.SubElement(lc, "mxGeometry", x=_fmt_num(label_x), y=_fmt_num(label_y),
                          width=_fmt_num(lw), height=_fmt_num(lh)).set("as", "geometry")
            self._register(lid, "text", label_x, label_y, lw, lh, parent, label=text,
                           owner=cid, lines=lines)
            entry["label_id"] = lid
            entry["lines"] = lines
        return cid

    def place_icons(self, parent, items, cols, x0=PAD, y0=ROW1_Y, col_w=COL_W,
                    row_h=ROW_H, **icon_kwargs):
        """Place icons on a grid inside parent. Returns (ids, (x, y, right, bottom)).

        items: iterable of (label, icon_key) tuples or dicts with keys
        label, icon and optionally metadata, tooltip, key, link. The bbox is
        in the parent's local coordinates and covers captions, so
        fit_to_children()/manual sizing can use it directly.
        """
        ids = []
        right = x0
        bottom = y0
        if cols < 1:
            raise ValueError("cols must be >= 1")
        for i, item in enumerate(items):
            if isinstance(item, dict):
                label, icon = item["label"], item["icon"]
                extra = {k: v for k, v in item.items() if k not in ("label", "icon")}
            else:
                label, icon = item[0], item[1]
                extra = {}
            kwargs = dict(icon_kwargs)
            kwargs.update(extra)
            ix = x0 + (i % cols) * col_w
            iy = y0 + (i // cols) * row_h
            cid = self.add_icon(label, icon, ix, iy, parent=parent, **kwargs)
            ids.append(cid)
            fx, fy, fw, fh = self.footprint(cid)
            right = max(right, fx + fw)
            bottom = max(bottom, fy + fh)
        return ids, (x0, y0, right, bottom)

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

    # -- images / text -------------------------------------------------------
    def add_image(self, image_path, x, y, w, h, parent="1", key=None) -> str:
        """Embed a logo (SVG directly; PNG/JPEG via Pillow) as an image cell."""
        parent = self._check_parent(parent, "add_image")
        img_path = Path(image_path)
        if not img_path.is_file():
            raise FileNotFoundError(f"Image not found: {img_path}")
        if img_path.suffix.lower() == ".svg":
            svg_text = img_path.read_text(encoding="utf-8")
            if not _DRAWABLE_RE.search(svg_text):
                raise ValueError(f"{img_path} has no drawable content")
            encoded = urllib.parse.quote(svg_text, safe="")
        else:
            try:
                from PIL import Image
            except ImportError as exc:
                raise ImportError(
                    "Pillow is required for PNG/JPEG logos: run `python3 -m pip install --user Pillow`, "
                    "or supply an SVG logo instead."
                ) from exc
            img = Image.open(img_path)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            if img.width > 300:
                ratio = 300 / img.width
                img = img.resize((300, max(1, int(img.height * ratio))), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            img_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            svg_wrapper = (
                f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'width="{img.width}" height="{img.height}">'
                f'<image width="{img.width}" height="{img.height}" '
                f'xlink:href="data:image/png;base64,{img_b64}"/></svg>'
            )
            encoded = urllib.parse.quote(svg_wrapper, safe="")
        style = (
            "shape=image;verticalLabelPosition=bottom;labelBackgroundColor=none;"
            f"verticalAlign=top;aspect=fixed;imageAspect=1;image=data:image/svg+xml,{encoded};"
        )
        cid = self._emit_vertex("", style, parent, x, y, w, h,
                                cid=self._new_id(key) if key is not None else None)
        self._register(cid, "other", x, y, w, h, parent, label="")
        return cid

    def add_text(self, label, x, y, w=200, h=30, parent="1", font_size=10, font_style=0,
                 align="left", font_color=None, font_family=None, key=None,
                 vertical_align="middle", raw_html=True, style_extra="") -> str:
        """Add a text-only cell. Labels are treated as HTML unless raw_html=False."""
        parent = self._check_parent(parent, "add_text")
        fc = font_color or COLORS["text_primary"]
        text = str(label) if raw_html else escape_label(label)
        style = (
            f"text;html=1;strokeColor=none;fillColor=none;align={align};"
            f"verticalAlign={vertical_align};whiteSpace=wrap;rounded=0;"
            f"fontFamily={font_family or self.font};fontSize={_fmt_num(font_size)};"
            f"fontStyle={font_style};fontColor={fc};"
        )
        style = _merge_style(style, style_extra)
        cid = self._emit_vertex(text, style, parent, x, y, w, h,
                                cid=self._new_id(key) if key is not None else None)
        self._register(cid, "text", x, y, w, h, parent, label=text)
        return cid

    def add_title(self, subject, region_label=None, region=None, compartment=None,
                  tenancy=None, x=PAD, y=8, w=600, h=55, font_size=18, font_family=None,
                  logo=None, logo_w=148, logo_h=39, page_w=None, key="title") -> dict:
        """Add the standard title block: bold subject + italic location line.

        Renders '<b>{tenancy - }subject</b><br/><i>{region_label} ({region}) -
        Compartment: {compartment}</i>'. If logo is given it is embedded at
        the top-right (a missing Pillow or file prints a warning instead of
        failing). Returns {"title": id, "logo": id or None}.
        """
        first = f"{tenancy} - {subject}" if tenancy else str(subject)
        parts = []
        if region_label and region:
            parts.append(f"{region_label} ({region})")
        elif region or region_label:
            parts.append(str(region or region_label))
        if compartment:
            parts.append(f"Compartment: {compartment}")
        html_label = f"<b>{escape_label(first)}</b>"
        if parts:
            html_label += f"<br/><i>{escape_label(' - '.join(parts))}</i>"
        tid = self.add_text(html_label, x, y, w, h, font_size=font_size, font_style=1,
                            font_family=font_family or TITLE_FONT_STACK, key=key)
        logo_id = None
        if logo:
            pw = page_w or self.page["width"]
            try:
                logo_id = self.add_image(logo, pw - logo_w - 22, y, logo_w, logo_h,
                                         key=(f"{key}-logo" if key else None))
            except (ImportError, FileNotFoundError, ValueError) as exc:
                print(f"WARNING: logo skipped: {exc}", file=sys.stderr)
        return {"title": tid, "logo": logo_id}

    def add_table(self, rows, x, y, parent="1", col_widths=None, header=True,
                  font_size=10, row_h=18, title=None, key=None) -> str:
        """Add an HTML table (e.g. NSG rules, route rules). Returns the cell id.

        rows: list of row lists (strings). The first row is a header when
        header=True. Width = sum(col_widths) (default 110px per column).
        """
        parent = self._check_parent(parent, "add_table")
        rows = [list(r) for r in rows]
        if not rows:
            raise ValueError("add_table: rows is empty")
        ncols = max(len(r) for r in rows)
        widths = list(col_widths) if col_widths else [110] * ncols
        if len(widths) < ncols:
            widths += [110] * (ncols - len(widths))
        total_w = sum(widths)
        border = COLORS["region_stroke"]
        cells = []
        if title:
            cells.append(f'<div style="font-weight:bold;margin-bottom:2px;">{escape_label(title)}</div>')
        cells.append(f'<table style="border-collapse:collapse;width:100%;font-size:{_fmt_num(font_size)}px;">')
        for ri, row in enumerate(rows):
            cells.append("<tr>")
            for ci in range(ncols):
                val = escape_label(row[ci]) if ci < len(row) else ""
                tag = "th" if (header and ri == 0) else "td"
                bg = f"background:{COLORS['region_fill']};" if tag == "th" else ""
                cells.append(f'<{tag} style="border:1px solid {border};padding:1px 4px;text-align:left;'
                             f'width:{widths[ci]}px;{bg}">{val}</{tag}>')
            cells.append("</tr>")
        cells.append("</table>")
        html_label = "".join(cells)
        h = row_h * len(rows) + (row_h if title else 0) + 6
        style = (
            "text;html=1;strokeColor=none;fillColor=#FFFFFF;align=left;verticalAlign=top;"
            f"whiteSpace=wrap;overflow=fill;rounded=0;spacing=2;fontFamily={self.font};"
            f"fontSize={_fmt_num(font_size)};fontColor={COLORS['text_primary']};"
        )
        cid = self._emit_vertex(html_label, style, parent, x, y, total_w + 6, h,
                                cid=self._new_id(key) if key is not None else None)
        self._register(cid, "text", x, y, total_w + 6, h, parent, label=title or "table")
        return cid

    def add_legend(self, x, y, parent="1", entries=None, title="Legend", width=230,
                   key=None) -> str:
        """Add a legend box explaining edge styles and container types.

        entries: list of ("edge", <style>, text) or ("group", <group_type>, text)
        where <style> is one of the EDGE_KIND_STYLES names ("data", "control",
        "association", "attachment") or a legacy alias ("solid", "dashed",
        "accent", "purple", "dotted", "thin").
        """
        parent = self._check_parent(parent, "add_legend")
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
        row_h = 22
        h = 30 + row_h * len(entries) + 8
        gid = self.add_group(title, x, y, width, h, parent=parent, group_type="other",
                             key=key, label_position="left")
        for i, (kind, spec, text) in enumerate(entries):
            ry = 30 + i * row_h
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
                eid = self._new_id()
                cell = ET.SubElement(self.root, "mxCell", id=eid, value="", style=style,
                                     edge="1", parent=gid)
                geom = ET.SubElement(cell, "mxGeometry", relative="1")
                geom.set("as", "geometry")
                ET.SubElement(geom, "mxPoint", x=_fmt_num(12), y=_fmt_num(ry + row_h / 2)).set("as", "sourcePoint")
                ET.SubElement(geom, "mxPoint", x=_fmt_num(52), y=_fmt_num(ry + row_h / 2)).set("as", "targetPoint")
                self._cells[eid] = {"kind": "edge", "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0,
                                    "parent": gid, "page": self._page_idx, "label": "",
                                    "source": None, "target": None}
            else:
                gstyle = self._group_styles.get(spec, self._group_styles["other"])
                tokens = _style_tokens(gstyle)
                for k in ("container", "collapsible", "expand", "recursiveResize"):
                    tokens.pop(k, None)
                sw_id = self._emit_vertex("", _tokens_to_style(tokens), gid, 14, ry + 3, 36, 16)
                self._register(sw_id, "other", 14, ry + 3, 36, 16, gid, label="swatch")
            self.add_text(escape_label(text), 60, ry, width - 66, row_h, parent=gid,
                          font_size=10, raw_html=True)
        return gid

    # -- edges -----------------------------------------------------------------
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

    def add_edge(self, source, target, label="", parent=None, dashed=False, color=None,
                 style_extra="", exit_x=None, exit_y=None, entry_x=None, entry_y=None,
                 waypoints=None, orthogonal=None, route=None, label_pos=None, arrow=None,
                 key=None, raw_html=False, kind=None) -> str:
        """Connect two cells. Returns the edge id.

        Routing modes (``route``):
        * ``"auto"`` (default when no ports/waypoints are given): the builder
          picks the common-ancestor parent, exit/entry sides and gutter
          waypoints from the geometry of all cells so the connector avoids
          unrelated icons and captions. Routes are computed lazily at
          validate()/write() time, so edges may be added in any order.
        * ``"direct"``: draw.io's orthogonal router, no fixed ports (the
          v1.1.0 default). Also selected by ``orthogonal=True`` without pins.
        * ``"pinned"``: legacy fixed exit/entry points and optional waypoints,
          router disabled (the v1.0.0 behaviour). Selected automatically when
          any of exit_x/exit_y/entry_x/entry_y or waypoints is passed
          (unless orthogonal=True, which keeps the router with the pins).

        ``parent`` defaults to the common ancestor of source and target.
        Waypoints are in the parent's coordinate space. ``label_pos`` (-1..1)
        places the label along the edge (0 = middle). Solid = data flow,
        dashed = management / user interaction.

        kind: "data" | "control" | "association" | "attachment" applies
        EDGE_KIND_STYLES (dashed / arrow / width / dash pattern); explicit
        arrow= still wins.
        """
        width = dash_pattern = None
        if kind is not None:
            spec = EDGE_KIND_STYLES.get(kind)
            if spec is None:
                raise ValueError(f"add_edge: unknown kind {kind!r}; choose from {sorted(EDGE_KIND_STYLES)}")
            dashed = spec["dashed"]
            arrow = spec["arrow"] if arrow is None else arrow
            width, dash_pattern = spec["width"], spec["dash_pattern"]
        source, target = str(source), str(target)
        for end, ref in (("source", source), ("target", target)):
            entry = self._cells.get(ref)
            if entry is None:
                raise ValueError(f"add_edge: unknown {end} id {ref!r}; pass the id returned by add_icon()/add_group()")
            if entry["kind"] in ("edge", "layer"):
                raise ValueError(f"add_edge: {end} {ref!r} is a {entry['kind']}, not a shape")
            if entry["page"] != self._page_idx:
                raise ValueError(f"add_edge: {end} {ref!r} is on another page")
        if parent is None:
            parent = self._common_ancestor(source, target)
        else:
            parent = self._check_parent(parent, "add_edge")

        ports_given = any(p is not None for p in (exit_x, exit_y, entry_x, entry_y))
        if route is None:
            if ports_given or waypoints:
                route = "pinned_router" if orthogonal else "pinned"
            elif orthogonal is False:
                route = "pinned"
            elif orthogonal is True:
                route = "direct"
            else:
                route = "auto"
        if route not in ("auto", "direct", "pinned", "pinned_router"):
            raise ValueError("route must be 'auto', 'direct' or 'pinned'")
        if route == "auto" and (ports_given or waypoints):
            route = "pinned_router"

        text = str(label) if raw_html else escape_label(label)
        cid = self._new_id(key)

        if route == "pinned":
            ex = 0.5 if exit_x is None else exit_x
            ey = 1.0 if exit_y is None else exit_y
            nx = 0.5 if entry_x is None else entry_x
            ny = 0.0 if entry_y is None else entry_y
            style = self._edge_base_style(color, dashed, style_extra, orthogonal=False, arrow=arrow,
                                          width=width, dash_pattern=dash_pattern)
            style += (f"exitX={_fmt_num(ex)};exitY={_fmt_num(ey)};exitDx=0;exitDy=0;"
                      f"entryX={_fmt_num(nx)};entryY={_fmt_num(ny)};entryDx=0;entryDy=0;")
        else:
            if (exit_x is None) != (exit_y is None):
                raise ValueError("exit_x and exit_y must be passed together")
            if (entry_x is None) != (entry_y is None):
                raise ValueError("entry_x and entry_y must be passed together")
            style = self._edge_base_style(color, dashed, style_extra, orthogonal=True, arrow=arrow,
                                          width=width, dash_pattern=dash_pattern)
            if exit_x is not None:
                style += f"exitX={_fmt_num(exit_x)};exitY={_fmt_num(exit_y)};exitDx=0;exitDy=0;"
            if entry_x is not None:
                style += f"entryX={_fmt_num(entry_x)};entryY={_fmt_num(entry_y)};entryDx=0;entryDy=0;"

        cell = ET.SubElement(self.root, "mxCell", id=cid, value=text, style=style,
                             edge="1", parent=parent, source=source, target=target)
        geom = ET.SubElement(cell, "mxGeometry", relative="1")
        geom.set("as", "geometry")
        if label_pos is not None:
            geom.set("x", _fmt_num(max(-1.0, min(1.0, float(label_pos)))))
            geom.set("y", "0")
        if waypoints:
            arr = ET.SubElement(geom, "Array")
            arr.set("as", "points")
            for wx, wy in waypoints:
                ET.SubElement(arr, "mxPoint", x=_fmt_num(wx), y=_fmt_num(wy))
        self._cells[cid] = {"kind": "edge", "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0,
                            "parent": parent, "page": self._page_idx, "label": text,
                            "source": source, "target": target, "route": route,
                            "points": list(waypoints or [])}
        if route == "auto":
            self._pending_routes.append({"id": cid, "cell": cell, "geom": geom,
                                         "label_pos": label_pos})
        return cid

    # -- automatic routing (orthogonal lattice + Dijkstra) ----------------------
    _OBSTACLE_COST = 1000.0   # crossing an icon / caption / text cell
    _FOREIGN_COST = 250.0     # running through a container that is not an ancestor
    _BEND_COST = 45.0         # each change of direction
    _LINE_MARGIN = 10.0       # corridor distance from container borders

    def _routing_shapes(self, page_idx):
        groups, obstacles = {}, {}
        for cid, e in self._cells.items():
            if e["page"] != page_idx:
                continue
            if e["kind"] == "group":
                ax, ay, w, h = self.abs_bbox(cid)
                groups[cid] = _Box(ax, ay, w, h)
                title = _html.unescape(_TAG_RE.sub(" ", e.get("label", "") or "")).strip()
                if title:
                    # the container's own title band is not a separate cell;
                    # model it as an obstacle so connectors do not run through it
                    tw = min(w, max(len(l) for l in title.split("\n")) * 7.0 + 12)
                    th = 18.0 * max(1, title.count("\n") + 1)
                    centered = "align=center" in self._group_styles.get(e.get("group_type", ""), "")
                    tx = ax + (w - tw) / 2 if centered else ax + 2
                    obstacles[f"{cid}#title"] = _Box(tx, ay + 1, tw, th)
            elif e["kind"] == "icon":
                # slot + caption as one block so connectors never squeeze
                # between a glyph and its caption; the caption is also kept
                # as its own obstacle so an edge never enters its endpoint
                # through the endpoint's caption
                ax, ay, w, h = self._abs_footprint(cid)
                if w > 0 and h > 0:
                    obstacles[cid] = _Box(ax, ay, w, h)
                # the slot (glyph + empty band) is kept as its own obstacle too,
                # so an endpoint's connector cannot run through the band
                # between its own glyph and caption
                ox, oy = self._origin(e["parent"])
                obstacles[f"{cid}#slot"] = _Box(ox + e["slot_x"], oy + e["slot_y"], e["slot_w"], e["slot_h"])
                lid = e.get("label_id")
                if lid and lid in self._cells:
                    lx, ly, lw, lh = self._abs_cell(lid)
                    if lw > 0 and lh > 0:
                        obstacles[f"{cid}#caption"] = _Box(lx, ly, lw, lh)
            elif e["kind"] in ("text", "other"):
                if e.get("owner"):
                    continue  # caption already covered by its icon's footprint
                ax, ay, w, h = self._abs_cell(cid)
                if w > 0 and h > 0:
                    obstacles[cid] = _Box(ax, ay, w, h)
        return groups, obstacles

    def _build_lattice(self, page_idx, port_points):
        """Candidate routing lines + per-segment costs for one page."""
        groups, obstacles = self._routing_shapes(page_idx)
        m = self._LINE_MARGIN
        xs, ys = set(), set()
        for b in groups.values():
            xs.update((b.x - m, b.x + m, b.right - m, b.right + m))
            ys.update((b.y - m, b.y + m, b.bottom - m, b.bottom + m))
        for b in obstacles.values():
            ys.update((b.y - 5, b.bottom + 5))
            xs.update((b.x - 5, b.right + 5))
        gl = list(groups.values())
        for i in range(len(gl)):
            for j in range(i + 1, len(gl)):
                a, b = gl[i], gl[j]
                if a.right <= b.x:
                    xs.add((a.right + b.x) / 2)
                if b.right <= a.x:
                    xs.add((b.right + a.x) / 2)
                if a.bottom <= b.y:
                    ys.add((a.bottom + b.y) / 2)
                if b.bottom <= a.y:
                    ys.add((b.bottom + a.y) / 2)
        for px, py in port_points:
            xs.add(px)
            ys.add(py)
        xs = sorted(set(round(v, 1) for v in xs))
        ys = sorted(set(round(v, 1) for v in ys))
        xi = {v: i for i, v in enumerate(xs)}
        yi = {v: i for i, v in enumerate(ys)}

        # Segment costs. h[j][i]: (xs[i]..xs[i+1]) at ys[j]; v[i][j]: (ys[j]..ys[j+1]) at xs[i]
        nx, ny = len(xs), len(ys)
        obs_items = list(obstacles.items())
        grp_items = list(groups.items())
        h_obs = [[()] * max(nx - 1, 0) for _ in range(ny)]
        h_grp = [[()] * max(nx - 1, 0) for _ in range(ny)]
        v_obs = [[()] * max(ny - 1, 0) for _ in range(nx)]
        v_grp = [[()] * max(ny - 1, 0) for _ in range(nx)]
        for j, y in enumerate(ys):
            row_obs = [(oid, b) for oid, b in obs_items if b.y + 0.5 < y < b.bottom - 0.5]
            row_grp = [(gid, b) for gid, b in grp_items if b.y + 0.5 < y < b.bottom - 0.5]
            for i in range(nx - 1):
                x0, x1 = xs[i], xs[i + 1]
                if row_obs:
                    h_obs[j][i] = tuple(oid for oid, b in row_obs if x1 > b.x + 0.5 and x0 < b.right - 0.5)
                if row_grp:
                    h_grp[j][i] = tuple(gid for gid, b in row_grp if x0 >= b.x - 0.5 and x1 <= b.right + 0.5)
        for i, x in enumerate(xs):
            col_obs = [(oid, b) for oid, b in obs_items if b.x + 0.5 < x < b.right - 0.5]
            col_grp = [(gid, b) for gid, b in grp_items if b.x + 0.5 < x < b.right - 0.5]
            for j in range(ny - 1):
                y0, y1 = ys[j], ys[j + 1]
                if col_obs:
                    v_obs[i][j] = tuple(oid for oid, b in col_obs if y1 > b.y + 0.5 and y0 < b.bottom - 0.5)
                if col_grp:
                    v_grp[i][j] = tuple(gid for gid, b in col_grp if y0 >= b.y - 0.5 and y1 <= b.bottom + 0.5)
        return {"xs": xs, "ys": ys, "xi": xi, "yi": yi, "h_obs": h_obs, "h_grp": h_grp,
                "v_obs": v_obs, "v_grp": v_grp, "groups": groups, "obstacles": obstacles}

    def _ancestors(self, cid):
        out = set()
        cur = self._cells.get(cid, {}).get("parent")
        hops = 0
        while cur not in (None, "0", "1") and hops < 200:
            out.add(cur)
            cur = self._cells.get(cur, {}).get("parent")
            hops += 1
        return out

    _SHARED_COST = 25.0       # re-using a corridor segment another edge already uses (below one bend)

    def _dijkstra(self, lat, starts, goals, allowed, endpoint_boxes, exclude_ids=frozenset()):
        """Cheapest orthogonal path on the lattice. starts/goals: {(i,j): side}."""
        import heapq
        xs, ys = lat["xs"], lat["ys"]
        nx, ny = len(xs), len(ys)
        h_obs, h_grp, v_obs, v_grp = lat["h_obs"], lat["h_grp"], lat["v_obs"], lat["v_grp"]
        used = lat.setdefault("used", {})
        OB, FO, BE, SH = self._OBSTACLE_COST, self._FOREIGN_COST, self._BEND_COST, self._SHARED_COST

        def seg_cost(i, j, horizontal, step):
            if horizontal:
                ii = i if step > 0 else i - 1
                length = xs[ii + 1] - xs[ii]
                obs = h_obs[j][ii]
                grp = h_grp[j][ii]
                mid = ((xs[ii] + xs[ii + 1]) / 2, ys[j])
                shared = used.get(("h", j, ii), 0)
            else:
                jj = j if step > 0 else j - 1
                length = ys[jj + 1] - ys[jj]
                obs = v_obs[i][jj]
                grp = v_grp[i][jj]
                mid = (xs[i], (ys[jj] + ys[jj + 1]) / 2)
                shared = used.get(("v", i, jj), 0)
            cost = length + SH * shared
            for o in obs:
                if o not in exclude_ids:
                    cost += OB
            for g in grp:
                if g not in allowed:
                    cost += FO
            for b in endpoint_boxes:   # never tunnel through the endpoints themselves
                if b.x + 0.5 < mid[0] < b.right - 0.5 and b.y + 0.5 < mid[1] < b.bottom - 0.5:
                    cost += OB
            return cost

        dist = {}
        prev = {}
        heap = []
        for (i, j), side in starts.items():
            d = 0 if side in ("L", "R") else 1
            dist[(i, j, d)] = 0.0
            heapq.heappush(heap, (0.0, i, j, d))
        best_goal = None
        while heap:
            cost, i, j, d = heapq.heappop(heap)
            if dist.get((i, j, d), float("inf")) < cost:
                continue
            if (i, j) in goals:
                best_goal = (i, j, d)
                break
            for nd in (0, 1):
                turn = 0.0 if nd == d else BE
                for step in (-1, 1):
                    if nd == 0:
                        ni, nj = i + step, j
                        if not 0 <= ni < nx:
                            continue
                    else:
                        ni, nj = i, j + step
                        if not 0 <= nj < ny:
                            continue
                    c = cost + turn + seg_cost(i, j, nd == 0, step)
                    key = (ni, nj, nd)
                    if c < dist.get(key, float("inf")):
                        dist[key] = c
                        prev[key] = (i, j, d)
                        heapq.heappush(heap, (c, ni, nj, nd))
        if best_goal is None:
            return None
        path = []
        cur = best_goal
        while cur in prev:
            path.append((cur[0], cur[1]))
            cur = prev[cur]
        path.append((cur[0], cur[1]))
        path.reverse()
        for (i0, j0), (i1, j1) in zip(path, path[1:]):
            if j0 == j1:
                key = ("h", j0, min(i0, i1))
            else:
                key = ("v", i0, min(j0, j1))
            used[key] = used.get(key, 0) + 1
        pts = [(xs[i], ys[j]) for i, j in path]
        # collapse collinear runs and duplicate points
        simplified = []
        for p in pts:
            if simplified and abs(p[0] - simplified[-1][0]) < 0.01 and abs(p[1] - simplified[-1][1]) < 0.01:
                continue
            if len(simplified) >= 2:
                a, b = simplified[-2], simplified[-1]
                if (abs(a[0] - b[0]) < 0.01 and abs(b[0] - p[0]) < 0.01) or \
                   (abs(a[1] - b[1]) < 0.01 and abs(b[1] - p[1]) < 0.01):
                    simplified[-1] = p
                    continue
            simplified.append(p)
        start_side = starts[path[0]]
        goal_side = goals[path[-1]]
        return simplified, start_side, goal_side, dist[best_goal]

    def _route_one(self, job, lat):
        cid = job["id"]
        e = self._cells[cid]
        src, tgt = e["source"], e["target"]
        if src not in self._cells or tgt not in self._cells:
            return
        sb = _Box(*self._abs_cell(src))
        tb = _Box(*self._abs_cell(tgt))
        xi, yi = lat["xi"], lat["yi"]

        def port_nodes(b):
            out = {}
            for side, (kx, ky) in self._PORTS.items():
                px, py = round(b.x + b.w * kx, 1), round(b.y + b.h * ky, 1)
                if px in xi and py in yi:
                    out[(xi[px], yi[py])] = side
            return out

        starts, goals = port_nodes(sb), port_nodes(tb)
        if not starts or not goals:
            return
        allowed = self._ancestors(src) | self._ancestors(tgt) | {src, tgt}
        result = self._dijkstra(lat, starts, goals, allowed, (sb, tb), exclude_ids={src, tgt})
        if result is None:
            return
        pts, es, ns, _cost = result
        ex, ey = self._PORTS[es]
        nx_, ny_ = self._PORTS[ns]
        cell, geom = job["cell"], job["geom"]
        style = cell.get("style")
        style = _merge_style(style, (
            f"exitX={_fmt_num(ex)};exitY={_fmt_num(ey)};exitDx=0;exitDy=0;"
            f"entryX={_fmt_num(nx_)};entryY={_fmt_num(ny_)};entryDx=0;entryDy=0;"))
        cell.set("style", style)
        ox, oy = self._origin(e["parent"])
        interior = pts[1:-1]
        for old in geom.findall("Array"):
            geom.remove(old)
        if interior:
            arr = ET.SubElement(geom, "Array")
            arr.set("as", "points")
            for wx, wy in interior:
                ET.SubElement(arr, "mxPoint", x=_fmt_num(round(wx - ox)), y=_fmt_num(round(wy - oy)))
        e["points"] = [(round(wx - ox), round(wy - oy)) for wx, wy in interior]
        e["polyline"] = pts
        if e["label"] and job.get("label_pos") is None:
            exclude = {src, tgt}
            pos, box = self._place_edge_label(pts, e["label"], lat["obstacles"], exclude)
            if box is not None:
                lat["obstacles"][f"{cid}#label"] = box
            if pos is not None and abs(pos) > 1e-6:
                geom.set("x", _fmt_num(pos))
                geom.set("y", "0")

    def _place_edge_label(self, pts, text, obstacles, exclude):
        lines = re.split(r"<br\s*/?>|\n", text)
        longest = max((len(_html.unescape(_TAG_RE.sub("", l))) for l in lines), default=1)
        lw = longest * self.profile["edge_font"] * 0.56 + 8
        lh = max(1, len(lines)) * (self.profile["edge_font"] + 3)
        segs = list(zip(pts, pts[1:]))
        lens = [abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in segs]
        total = sum(lens) or 1.0

        def point_at(t):
            d = t * total
            for (a, b), ln in zip(segs, lens):
                if d <= ln or (a, b) == segs[-1]:
                    f = d / ln if ln else 0
                    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
                d -= ln
            return pts[-1]

        first_box = None
        for t in (0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8, 0.12, 0.88):
            cx, cy = point_at(t)
            box = _Box(cx - lw / 2, cy - lh / 2, lw, lh)
            if first_box is None:
                first_box = box
            if not any(ob.intersects(box) for oid, ob in obstacles.items() if oid not in exclude):
                return 2 * t - 1, box
        return None, first_box

    def route_edges(self) -> int:
        """Resolve all pending auto-routed edges now. Returns the count."""
        if not self._pending_routes:
            return 0
        jobs, self._pending_routes = self._pending_routes, []
        by_page = {}
        for job in jobs:
            by_page.setdefault(self._cells[job["id"]]["page"], []).append(job)
        n = 0
        for page_idx, page_jobs in by_page.items():
            ports = []
            for job in page_jobs:
                e = self._cells[job["id"]]
                for end in (e["source"], e["target"]):
                    if end in self._cells:
                        b = _Box(*self._abs_cell(end))
                        for kx, ky in self._PORTS.values():
                            ports.append((round(b.x + b.w * kx, 1), round(b.y + b.h * ky, 1)))
            lat = self._build_lattice(page_idx, ports)
            for job in page_jobs:
                self._route_one(job, lat)
                n += 1
        return n

    # -- sizing helpers ----------------------------------------------------------
    def fit_to_children(self, cid, pad=PAD, min_w=None, min_h=None) -> tuple:
        """Resize a container so all children (incl. captions) fit. Returns (w, h).

        Call it after adding the container's children (and after fitting
        nested containers); the container's x/y are unchanged.
        """
        e = self._cells.get(cid)
        if e is None or e["kind"] != "group":
            raise ValueError(f"fit_to_children: {cid!r} is not a container")
        right = bottom = 0.0
        for kid, ke in self._cells.items():
            if ke["parent"] != cid or ke["kind"] in ("edge", "layer"):
                continue
            if ke["kind"] == "icon":
                x, y, w, h = self.footprint(kid)
            else:
                x, y, w, h = ke["x"], ke["y"], ke["w"], ke["h"]
            right = max(right, x + w)
            bottom = max(bottom, y + h)
        w = max(right + pad, min_w or 0, 60)
        h = max(bottom + pad, min_h or 0, 40)
        e["w"], e["h"] = float(w), float(h)
        self._set_geometry(cid, width=w, height=h)
        return (w, h)

    def resize(self, cid, w=None, h=None, x=None, y=None) -> None:
        """Change a container/text cell's geometry explicitly."""
        e = self._cells[cid]
        for name, val in (("x", x), ("y", y), ("w", w), ("h", h)):
            if val is not None:
                e[name] = float(val)
        self._set_geometry(cid, x=e["x"], y=e["y"], width=e["w"], height=e["h"])

    def content_bbox(self, page_idx=None) -> tuple:
        """Absolute (x, y, right, bottom) of everything on a page."""
        page_idx = self._page_idx if page_idx is None else page_idx
        x0 = y0 = float("inf")
        x1 = y1 = 0.0
        for cid, e in self._cells.items():
            if e["page"] != page_idx or e["kind"] in ("edge", "layer"):
                continue
            ax, ay, w, h = self.abs_bbox(cid) if e["kind"] != "icon" else self._abs_footprint(cid)
            x0, y0 = min(x0, ax), min(y0, ay)
            x1, y1 = max(x1, ax + w), max(y1, ay + h)
        if x0 == float("inf"):
            return (0.0, 0.0, 0.0, 0.0)
        return (x0, y0, x1, y1)

    def _abs_footprint(self, cid):
        e = self._cells[cid]
        x, y, w, h = self.footprint(cid)
        ox, oy = self._origin(e["parent"])
        return (ox + x, oy + y, w, h)

    def fit_page(self, margin=PAD) -> tuple:
        """Set the current page size from its content. Returns (w, h)."""
        _, _, right, bottom = self.content_bbox()
        w = int(math.ceil((right + margin) / 10.0) * 10)
        h = int(math.ceil((bottom + margin) / 10.0) * 10)
        self.model.set("pageWidth", str(w))
        self.model.set("pageHeight", str(h))
        self.page["width"], self.page["height"] = w, h
        return (w, h)

    # -- validation / output ---------------------------------------------------
    def validate(self, strict: bool = False) -> list:
        """Route pending edges and validate every page.

        Returns messages starting with 'ERROR:'/'OVERLAP:' (must fix) or
        'WARNING:' (review). Errors cover references, container overlaps,
        containment (icons may straddle their parent's border), foreign
        containment (icons inside a VCN/subnet they do not belong to; DRG
        inside a VCN) and leaf collisions. strict=True turns estimated edge
        crossings into errors. Empty list = clean.
        """
        self.route_edges()
        errors, warnings = [], []
        multi = len(self._pages) > 1
        for p in self._pages:
            registry = build_cell_registry(p["root"])
            e, w = validate_registry(registry, page=p["name"] if multi else "", strict=strict)
            errors.extend(e)
            warnings.extend(w)
            _, _, right, bottom = self._content_bbox_registry(registry)
            if right > p["width"] + 0.5 or bottom > p["height"] + 0.5:
                warnings.append(
                    (f"[page: {p['name']}] " if multi else "") +
                    f"WARNING: content ({_fmt_num(right)}x{_fmt_num(bottom)}) exceeds the page "
                    f"({p['width']}x{p['height']}); call fit_page()")
        return errors + warnings

    @staticmethod
    def _content_bbox_registry(registry):
        boxes = _abs_boxes(registry)
        right = max((b.right for b in boxes.values()), default=0.0)
        bottom = max((b.bottom for b in boxes.values()), default=0.0)
        return (0.0, 0.0, right, bottom)

    def check_overlaps(self, strict: bool = False) -> list:
        """Return blocking problems only (overlaps, containment, references)."""
        return [m for m in self.validate(strict=strict) if not m.lstrip("[page: ").split("] ")[-1].startswith("WARNING")]

    def write(self, path) -> Path:
        """Route pending edges and write the .drawio XML to disk."""
        self.route_edges()
        path = Path(path)
        tree = ET.ElementTree(self.mxfile)
        ET.indent(tree, space="  ")
        path.parent.mkdir(parents=True, exist_ok=True)
        tree.write(str(path), encoding="utf-8", xml_declaration=True)
        print(f"Wrote {path} ({path.stat().st_size:,} bytes)")
        return path

    def render(self, drawio_path, fmt="png", out=None, scale=1.0) -> Optional[Path]:
        """Export an already written file via draw.io desktop (None if absent)."""
        return render(drawio_path, fmt=fmt, out=out, scale=scale)


def _is_ancestor_builder(cells, anc, cid) -> bool:
    cur = cells.get(cid, {}).get("parent")
    hops = 0
    while cur not in (None, "0", "1") and hops < 200:
        if cur == anc:
            return True
        cur = cells.get(cur, {}).get("parent")
        hops += 1
    return False


__all__ = [
    "DrawioBuilder", "COLORS", "FONT_STACK", "ICON_MAP", "ICON_ALIASES", "GROUP_TYPES",
    "STYLE_PROFILES", "EDGE_KIND_STYLES", "ICON_W", "ICON_H", "GLYPH_W", "GLYPH_H", "LABEL_GAP", "LABEL_W",
    "LABEL_H", "ICON_FOOTPRINT_H", "PAD", "ROW1_Y", "COL_W", "ROW_H", "GAP", "BOX_STYLE", "DRG_ICON_STEM",
    "STRADDLE_TOL", "FOREIGN_TOL",
    "add_icons_to_map", "set_icon_dir", "resolve_icon_path", "escape_label", "label_lines",
    "build_cell_registry", "find_container_overlaps", "validate_registry", "validate_file",
    "find_drawio_binary", "render", "OCI_SVG_DIR",
]
