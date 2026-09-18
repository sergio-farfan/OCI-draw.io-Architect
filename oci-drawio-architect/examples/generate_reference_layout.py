#!/usr/bin/env python3
"""Reference layout: rebuilds the Spoke-VCN-D sample diagram from a model dict.

This is the canonical example for the /drawio-architect workflow. The whole
diagram is described as data (MODEL below) and laid out by
scripts/oci_layout.py, so a generated script only has to fill in the model:
subnets in traffic order, icons per subnet, regional services (drawn in the
Oracle Services Network panel), gateways on the VCN border, the DRG with its
attachments, the on-premises panel and the edges. Security constructs are
badges, not workload icons: each NSG is listed in the "nsgs" field of the
resource it protects and drawn as a shield over that resource's icon.

Usage:
    python3 generate_reference_layout.py [output.drawio] [--render]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from oci_layout import write_diagram  # noqa: E402

MODEL = {
    "subject": "Spoke-VCN-D",
    "region": "us-ashburn-1",
    "region_label": "Ashburn",
    "compartment": "Spoke-VCN-D",
    "hub": {
        "name": "Hub Network\nHub-Network\n(Shared-Services)",
        "items": [
            {"icon": "firewall", "type": "oci_core_cpe", "label": "Corp VPN\n(10.0.0.0/8)",
             "address": "cpe"},
        ],
    },
    "drgs": [{
        "name": "drg", "address": "drg", "label": "Dynamic Routing\nGateway (DRG)",
        "attachments": [
            {"type": "vcn", "vcn": "Spoke-VCN-D", "address": "drg-att-spoke",
             "label": "VCN attachment\nSpoke-VCN-D"},
        ],
    }],
    "vcns": [{
        "name": "Spoke-VCN-D",
        "cidr": "10.0.0.0/16",
        "subnets": [
            {"name": "sn-priv-lb", "cidr": "10.0.0.0/24", "tier": "lb", "items": [
                {"icon": "load_balancer", "label": "Load Balancer\n10.0.0.23", "address": "lb",
                 "metadata": {"ip": "10.0.0.23"}, "tooltip": "Private load balancer",
                 "nsgs": ["nsg-priv-lb"]},
                {"icon": "certificates", "label": "SSL Certificate\n*.internal...", "address": "cert"},
                {"icon": "waf", "label": "OCI Edge WAF", "address": "waf"},
            ]},
            {"name": "sn-priv-app", "cidr": "10.0.1.0/24", "tier": "app", "items": [
                {"icon": "vm", "label": "App VM\n10.0.1.251\n16 OCPU / 96 GB", "address": "app-vm",
                 "nsgs": ["nsg-priv-app"]},
                {"icon": "functions", "label": "Functions App", "address": "fn"},
                {"icon": "block_storage", "label": "Block Volume\n500 GB", "address": "bv-app"},
            ]},
            {"name": "sn-priv-workers", "cidr": "10.0.2.0/24", "tier": "app", "items": [
                {"icon": "vm", "label": "Worker VM\n10.0.2.72\n8 OCPU / 64 GB", "address": "worker-vm",
                 "nsgs": ["nsg-priv-workers"]},
                {"icon": "block_storage", "label": "Block Volume\n300 GB", "address": "bv-worker"},
            ]},
            {"name": "sn-priv-data", "cidr": "10.0.3.0/24", "tier": "data", "items": [
                {"icon": "autonomous_db", "label": "ADB prod\napp-db\n16 ECPU / 4 TB", "address": "adb",
                 "nsgs": ["nsg-priv-data (21 rules)"]},
                {"icon": "nosql", "label": "Redis\n10.0.3.186", "address": "redis"},
                {"icon": "big_data", "label": "OAC\napp-oac\n1 OLPU", "address": "oac"},
                {"icon": "data_science", "label": "PAC\n10.0.3.99", "address": "pac"},
                {"icon": "data_science", "label": "AIDP\napp-oracle\n-mcp-aidp", "address": "aidp"},
                {"icon": "ai", "label": "GenAI\ncohere.embed\n-multilingual-v3", "address": "genai"},
                {"icon": "vault", "label": "Vault\n+ Master Key\n+ 4 Secrets", "address": "vault"},
            ]},
        ],
        "services": [
            {"icon": "devops", "label": "DevOps\nProject + CI/CD", "address": "devops"},
            {"icon": "container_registry", "label": "OCIR\n7 Repos", "address": "ocir"},
            {"icon": "buckets", "label": "Object Storage\n3 Buckets", "address": "buckets"},
            {"icon": "queuing", "label": "Queues (3)\njobs-queue\nbatch-queue", "address": "queues"},
            {"icon": "logging", "label": "Logging\n7 Logs", "address": "logging"},
            {"icon": "apm", "label": "APM", "address": "apm"},
            {"icon": "alarms", "label": "Alarms (4)\n+ ONS Topic", "address": "alarms"},
            {"icon": "dns", "label": "Private DNS\n*.internal...", "address": "dns"},
        ],
        "gateways": [
            {"icon": "service_gateway", "type": "sgw", "label": "Service\nGateway", "address": "sgw"},
            {"icon": "nat_gateway", "type": "nat", "label": "NAT Gateway\n(backup - unused)",
             "address": "nat"},
        ],
    }],
    "edges": [
        {"source": "cpe", "target": "drg", "label": "IPSec VPN", "kind": "data"},
        {"source": "drg", "target": "lb", "label": "", "kind": "data"},
        {"source": "lb", "target": "app-vm", "label": "3000 / 8000", "kind": "data"},
        {"source": "app-vm", "target": "worker-vm", "label": "443", "kind": "control"},
        {"source": "app-vm", "target": "adb", "label": "1522", "kind": "data"},
        {"source": "worker-vm", "target": "adb", "label": "1522", "kind": "data"},
        {"source": "oac", "target": "pac", "label": "", "kind": "analytics"},
        {"source": "pac", "target": "adb", "label": "1522 / 443 (PAC)", "kind": "analytics"},
        {"source": "aidp", "target": "adb", "label": "Lakehouse", "kind": "datalake"},
        {"source": "aidp", "target": "buckets", "label": "Data Lake files", "kind": "datalake"},
        {"source": "app-vm", "target": "sgw", "label": "OCI APIs", "kind": "control"},
        {"source": "worker-vm", "target": "sgw", "label": "OCI APIs (via DRG)", "kind": "control"},
    ],
}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0]) if args else Path("Spoke-VCN-D_Architecture.drawio")
    write_diagram(MODEL, out, render_fmt="png" if "--render" in sys.argv else None)
