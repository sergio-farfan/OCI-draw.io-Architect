#!/usr/bin/env python3
"""Demo / smoke test for oci-drawio-architect v1.3.1.

Page 1 "Architecture": the layout recipe (oci_layout.build_diagram) on a two-VCN
hybrid model - on-premises panel with a CPE, a region-level DRG with two VCN
attachments and one IPSec attachment (drg_style "icon"), IGW / NAT on the hub
VCN's bottom border, the Service Gateway on the spoke VCN's right border, an
Oracle Services Network panel with the regional services, the four connector
kinds (data, control, association, attachment) and the legend. Route tables and
security lists appear as badges on the subnets' top-right corners and NSGs as
shield badges on the load balancer, the app VM and the database.
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

from drawio_builder import PAD, __version__, build_cell_registry, is_warning, render  # noqa: E402
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
            {"name": "sn-public", "cidr": "10.0.1.0/24", "tier": "lb", "public": True, "route_table": "rt-public",
             "security_lists": ["sl-public"], "items": [
                {"icon": "load_balancer", "label": "Public LB", "address": "lb", "nsgs": ["nsg-lb"]},
                {"icon": "waf", "label": "WAF", "address": "waf"}]},
            {"name": "sn-mgmt", "cidr": "10.0.2.0/24", "tier": "mgmt", "items": [
                {"icon": "bastion", "label": "Bastion", "address": "bastion"}]}],
         "gateways": [{"icon": "internet_gateway", "type": "igw", "label": "Internet\nGateway", "address": "igw"},
                      {"icon": "nat_gateway", "type": "nat", "label": "NAT\nGateway", "address": "nat"}]},
        {"name": "vcn-spoke", "cidr": "10.1.0.0/16", "subnets": [
            {"name": "sn-app", "cidr": "10.1.1.0/24", "tier": "app", "route_table": "rt-private",
             "security_lists": ["sl-app"], "items": [
                {"icon": "vm", "label": "App VM\n10.1.1.5", "address": "app",
                 "metadata": {"ocid": "ocid1.instance.oc1..demo"}, "tooltip": "primary app node",
                 "nsgs": ["nsg-app"]}]},
            {"name": "sn-data", "cidr": "10.1.2.0/24", "tier": "data", "items": [
                {"icon": "autonomous_db", "label": "Autonomous\nDatabase", "address": "adb",
                 "nsgs": ["nsg-db"]}]}],
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
    errors = [p for p in problems if not is_warning(p)]
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
