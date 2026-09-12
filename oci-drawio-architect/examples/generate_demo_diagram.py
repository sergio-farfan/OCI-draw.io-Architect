#!/usr/bin/env python3
"""Demo / smoke test for DrawioBuilder v1.2.0 - exercises every container
type, the sizing helpers, all three edge modes, metadata/tooltips, a legend,
a rules table, a second page and the validation gate.

Page 1 "Architecture":
    Title block + optional logo
    Tenancy
      +-- On-Premises (onprem)                       cpe icon
      +-- Region
            +-- Availability Domain -> Fault Domain  vm icon
            +-- Compartment -> VCN -> Subnet (load_balancer + vm)
            |                      -> Subnet (autonomous_db, metadata+tooltip)
            +-- Services panel                       vault + buckets (explicit size)
            +-- Oracle Services Network panel        service_gateway icon
    Legend
Page 2 "Security": an NSG rule table.

Edge modes exercised:
  - auto  (default): load_balancer -> vm, cpe -> load_balancer, vm -> vault (dashed)
  - pinned + waypoints (legacy): vm -> autonomous_db through the subnet gap
  - direct (port-less orthogonal router): buckets -> service_gateway (adjacent panels)
  - auto, long cross-container route: autonomous_db -> service_gateway

Every container is sized with fit_to_children() after its children exist, the
page is sized with fit_page(), and validate() must return no errors before the
file is written.

Usage:
    python3 generate_demo_diagram.py [output_path] [--render]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from drawio_builder import (  # noqa: E402
    GAP, ICON_H, PAD, ROW1_Y, DrawioBuilder, __version__, render,
)

NESTED_Y = 40   # first child y inside a container that nests containers


def build(out_path: Path, do_render: bool = False) -> None:
    d = DrawioBuilder(page_name="Architecture")
    d.add_title(f"DrawioBuilder v{__version__} Demo", region_label="Ashburn",
                region="us-ashburn-1", compartment="demo-compartment", tenancy="demo-tenancy")

    # Containers are created with provisional sizes and fitted afterwards.
    tenancy = d.add_group("Tenancy: demo-tenancy", PAD, 75, 400, 300, group_type="tenancy", key="tenancy")
    onprem = d.add_group("On-Premises", PAD, NESTED_Y, 160, 200, parent=tenancy, group_type="onprem", key="onprem")
    cpe = d.add_icon("Customer Premises\nEquipment", "cpe", PAD, ROW1_Y, parent=onprem, key="cpe")
    d.fit_to_children(onprem)

    region = d.add_group("us-ashburn-1", 0, NESTED_Y, 400, 300, parent=tenancy, group_type="region", key="region")

    ad = d.add_group("Availability Domain 1", PAD, NESTED_Y, 200, 200, parent=region,
                     group_type="availability_domain", key="ad1")
    fd = d.add_group("Fault Domain 1", PAD, NESTED_Y, 160, 160, parent=ad, group_type="fault_domain", key="fd1")
    vm_fd = d.add_icon("App VM\n10.0.9.10", "vm", PAD, ROW1_Y, parent=fd, key="vm-fd")
    d.fit_to_children(fd)
    d.fit_to_children(ad)

    compartment = d.add_group("Compartment: demo-compartment", 0, NESTED_Y, 400, 300, parent=region,
                              group_type="compartment", key="compartment")
    vcn = d.add_group("VCN: demo-vcn (10.0.0.0/16)", PAD, NESTED_Y, 400, 300, parent=compartment,
                      group_type="vcn", key="vcn")
    subnet1 = d.add_group("sn-public-1 (10.0.1.0/24)", PAD, NESTED_Y, 300, 200, parent=vcn,
                          group_type="subnet", key="sn-public-1")
    (lb, vm_sn1), _ = d.place_icons(subnet1, [("Load Balancer", "load_balancer"), ("Web VM", "vm")], cols=2)
    d.fit_to_children(subnet1)

    subnet2 = d.add_group("sn-data-1 (10.0.2.0/24)", 0, NESTED_Y, 160, 200, parent=vcn,
                          group_type="subnet", key="sn-data-1")
    adb = d.add_icon(
        "Autonomous\nDatabase", "autonomous_db", PAD, ROW1_Y, parent=subnet2, key="adb",
        metadata={"ocid": "ocid1.autonomousdatabase.oc1..demo", "workload": "OLTP"},
        tooltip="Autonomous DB (demo metadata)",
    )
    d.fit_to_children(subnet2)
    # place subnet2 to the right of subnet1 now that subnet1 has its final width
    _, _, w1, _ = d.bbox(subnet1)
    d.resize(subnet2, x=PAD + w1 + GAP)
    d.fit_to_children(vcn)
    d.fit_to_children(compartment)

    _, _, ad_w, _ = d.bbox(ad)
    d.resize(compartment, x=PAD + ad_w + GAP)
    _, _, comp_w, _ = d.bbox(compartment)

    services = d.add_group("Services", PAD + ad_w + GAP + comp_w + GAP, NESTED_Y, 300, 200,
                           parent=region, group_type="services", key="services")
    vault = d.add_icon("Vault", "vault", PAD, ROW1_Y, parent=services, key="vault")
    buckets = d.add_icon("Object Storage", "buckets", PAD + 130, ROW1_Y, parent=services, key="buckets",
                         w=75, h=75)   # explicit size path
    d.fit_to_children(services)
    _, _, svc_w, _ = d.bbox(services)

    osn = d.add_group("Oracle Services Network", PAD + ad_w + GAP + comp_w + GAP + svc_w + GAP, NESTED_Y,
                      160, 200, parent=region, group_type="oracle_services_network", key="osn")
    svc_gw = d.add_icon("Service Gateway", "service_gateway", PAD, ROW1_Y, parent=osn, key="sgw")
    d.fit_to_children(osn)
    d.fit_to_children(region)

    _, _, onprem_w, _ = d.bbox(onprem)
    d.resize(region, x=PAD + onprem_w + GAP)
    d.fit_to_children(tenancy)

    # -- Edges ----------------------------------------------------------------
    d.add_edge(lb, vm_sn1, "443")                       # auto (same subnet, straight)
    d.add_edge(cpe, lb, "IPSec")                        # auto, cross-container, parent = tenancy
    d.add_edge(vm_fd, vault, "secrets", dashed=True)    # auto, dashed (management)
    gap_x = PAD + w1 + GAP / 2                          # legacy pinned + waypoint, vcn-relative
    d.add_edge(vm_sn1, adb, "1522", parent=vcn,
               exit_x=1.0, exit_y=0.5, entry_x=0.0, entry_y=0.5,
               waypoints=[(gap_x, NESTED_Y + ROW1_Y + ICON_H / 2)])
    d.add_edge(buckets, svc_gw, "OSN", dashed=True, route="direct")   # v1.1.0-style port-less router
    d.add_edge(adb, svc_gw, "OSN", dashed=True)                       # auto, long cross-container route

    # -- Legend under the tenancy ---------------------------------------------
    _, _, _, bottom = d.content_bbox()
    d.add_legend(PAD, bottom + GAP, entries=[
        ("edge", "solid", "Data flow"),
        ("edge", "dashed", "Management / API traffic"),
        ("group", "vcn", "VCN"),
        ("group", "subnet", "Subnet"),
    ])
    d.fit_page()

    # -- Page 2: security rules table -----------------------------------------
    d.add_page("Security", 800, 400)
    d.add_title("NSG rules - demo-vcn", region_label="Ashburn", region="us-ashburn-1", key="title2")
    d.add_table([
        ["Direction", "Source / Destination", "Protocol", "Ports", "Description"],
        ["Ingress", "0.0.0.0/0", "TCP", "443", "HTTPS from the internet"],
        ["Ingress", "10.0.1.0/24", "TCP", "1522", "App to Autonomous Database"],
        ["Egress", "all-iad-services", "TCP", "443", "OCI services via Service Gateway"],
    ], PAD, 75, col_widths=[80, 170, 80, 60, 260], title="nsg-app (3 rules)", key="nsg-table")
    d.fit_page()

    # -- Mandatory validation gate before writing -------------------------------
    problems = d.validate()
    errors = [p for p in problems if "WARNING" not in p.split("] ")[-1][:8]]
    for p in problems:
        print(p)
    if errors:
        raise SystemExit(1)

    d.write(out_path)
    n_groups = sum(1 for c in d._cells.values() if c["kind"] == "group")
    n_icons = sum(1 for c in d._cells.values() if c["kind"] == "icon")
    n_edges = sum(1 for c in d._cells.values() if c["kind"] == "edge" and c.get("source"))
    print(f"{out_path} | {len(d._pages)} pages | {n_groups} containers, {n_icons} icons, {n_edges} edges")
    if do_render:
        png = render(out_path, fmt="png")
        print(f"Rendered {png}" if png else "draw.io desktop not found; render skipped")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0]) if args else Path("demo_architecture.drawio")
    build(out, do_render="--render" in sys.argv)
