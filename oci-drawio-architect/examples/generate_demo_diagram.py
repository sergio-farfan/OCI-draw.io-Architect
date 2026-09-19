#!/usr/bin/env python3
"""Demo / smoke test for oci-drawio-architect v1.3.1.

Page 1 "Architecture": the layout recipe (oci_layout.build_diagram) on a two-VCN
hybrid model with the default outside canvas - On-Premises and Internet as
page-level boxes beside the region, a region-level DRG with two VCN attachments
and one IPSec attachment (drg_style "icon"), IGW / NAT on the hub VCN's border
facing the Internet box, the Service Gateway on the spoke VCN's bottom border
facing the Oracle Services Network band, the four connector kinds (data,
control, association, attachment) and the legend with its badge rows. Route
tables and security lists appear as badges on the subnets' top-right corners
and NSGs as shield badges on the load balancer, the app VM and the database.
Page 2 "DRG as a box": the same model with locations "nested" and drg_style
"box" - the 1.3.0 geometry, kept as the visual regression proof.
Page 3 "Compartments and OKE": two VCNs in nested compartment containers inside
a tenancy wrapper, an OKE cluster box inside a subnet, a tier band around a
subnet row and a DRG with its two route-table badges.
Page 4 "Security": an NSG rule table (custom DrawioBuilder API).

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

# Page 3: the 1.4.0 grouping features - compartment containers inside a tenancy
# wrapper, an OKE cluster box inside a subnet, a tier band around a subnet row,
# and a DRG with the two route tables Oracle creates by default.
COMPARTMENT_MODEL = {
    "subject": "demo-landing-zone", "region": "us-ashburn-1", "region_label": "Ashburn",
    "compartment": "Network", "tenancy_name": "demo-tenancy",
    "show_compartments": True,
    "compartments": [
        {"name": "Enclosing", "parent": None, "vcns": []},
        {"name": "Network", "parent": "Enclosing", "vcns": ["vcn-net"]},
        {"name": "App", "parent": "Enclosing", "vcns": ["vcn-app"]},
    ],
    "internet": {"name": "Internet", "items": [
        {"icon": "user", "label": "Customers", "address": "customers"}]},
    "drgs": [{"name": "drg-lz", "address": "drg-lz", "label": "DRG\ndrg-lz",
              "route_table": [{"name": "drg-rt-vcn", "address": "drg-rt-vcn"},
                              {"name": "drg-rt-other", "address": "drg-rt-other"}],
              "attachments": [
                  {"type": "vcn", "vcn": "vcn-net", "address": "att-net",
                   "label": "VCN attachment\nvcn-net"},
                  {"type": "vcn", "vcn": "vcn-app", "address": "att-app",
                   "label": "VCN attachment\nvcn-app"}]}],
    "vcns": [
        {"name": "vcn-net", "cidr": "10.10.0.0/16", "compartment": "Network", "subnets": [
            {"name": "sn-edge", "cidr": "10.10.1.0/24", "tier": "lb", "public": True, "items": [
                {"icon": "load_balancer", "label": "Edge LB", "address": "edge-lb"}]}],
         "gateways": [{"icon": "internet_gateway", "type": "igw", "label": "Internet\nGateway",
                       "address": "igw-net"},
                      {"icon": "nat_gateway", "type": "nat", "label": "NAT\nGateway",
                       "address": "nat-net"}]},
        {"name": "vcn-app", "cidr": "10.20.0.0/16", "compartment": "App",
         "groups": [{"type": "tier", "label": "Application Tier", "subnets": ["sn-app"],
                     "key": "tier-app"}],
         "subnets": [
            {"name": "sn-app", "cidr": "10.20.1.0/24", "tier": "app", "public": False,
             "groups": [{"type": "oke_cluster", "label": "Container Engine for\nKubernetes Cluster",
                         "items": ["oke-main", "np-a", "np-b"], "key": "oke-main-box"}],
             "items": [{"icon": "oke", "label": "OKE cluster\noke-main", "address": "oke-main"},
                       {"icon": "vm", "label": "Node pool\nnp-a", "address": "np-a"},
                       {"icon": "vm", "label": "Node pool\nnp-b", "address": "np-b"}]}],
         "services": [{"icon": "container_registry", "label": "OCIR", "address": "ocir"}],
         "gateways": [{"icon": "service_gateway", "type": "sgw", "label": "Service\nGateway",
                       "address": "sgw-app"}]},
    ],
    "edges": [
        {"source": "customers", "target": "igw-net", "label": "443", "kind": "data"},
        {"source": "edge-lb", "target": "oke-main-box", "label": "8080", "kind": "data"},
    ],
}


def build(out_path: Path, do_render: bool = False) -> None:
    d = build_diagram(DEMO_MODEL, page_name="Architecture", legend=True)
    box = build_diagram(DEMO_MODEL, page_name="DRG as a box", drg_style="box", legend=True,
                        locations="nested")
    d.append_pages(box)
    lz = build_diagram(COMPARTMENT_MODEL, page_name="Compartments and OKE", legend=True)
    d.append_pages(lz)

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
