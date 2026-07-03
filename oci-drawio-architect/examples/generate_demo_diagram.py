#!/usr/bin/env python3
"""Demo / smoke test for DrawioBuilder v1.1.0 — exercises every container
type, icon sizing, edge modes, metadata, and the overlap checker.

Builds a single-page architecture diagram:

    Tenancy
      +-- On-Premises (onprem)               -- cpe icon
      +-- Region
            +-- Availability Domain -> Fault Domain  -- vm icon
            +-- Compartment -> VCN -> Subnet (load_balancer + vm icons)
            |                      -> Subnet (autonomous_db, metadata+tooltip)
            +-- Services panel                 -- vault + buckets (explicit size)
            +-- Oracle Services Network panel  -- service_gateway icon

Edge modes exercised:
  - modern, same-container      (load_balancer -> vm, label "443")
  - modern, cross-container     (cpe -> load_balancer, parent=tenancy)
  - legacy, pinned + waypoints  (vm -> autonomous_db, parent=vcn)
  - modern, dashed               (vm -> vault, parent=region)

Layout discipline (see skills/oci-drawio-architect/references/gotchas.md
#11): every container's position is derived from a sibling's computed
right/bottom edge plus a gap constant - never a hardcoded coordinate that
could drift into an overlap. check_overlaps() is run as a mandatory gate
before the file is written.

Usage:
    python3 generate_demo_diagram.py [output_path]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from drawio_builder import DrawioBuilder, ICON_H, LABEL_GAP, LABEL_H

# ---------------------------------------------------------------------------
# Layout constants - every container/icon position below is derived from
# these plus a sibling's computed right/bottom edge. No magic coordinates.
# ---------------------------------------------------------------------------
PAD = 20                                    # inner padding + outer page margin
GAP = 30                                    # gap between sibling containers
ROW_Y = 50                                  # first icon row y (icon-only container)
NESTED_ROW_Y = 40                           # first child y (container-nesting container)
ICON_COL_W = 140                            # x-spacing between two icons in a row
ICON_ROW_H = ICON_H + LABEL_GAP + LABEL_H   # 95 + 2 + 45 = 142: one icon's footprint
ONE_ICON_ROW_H = ROW_Y + ICON_ROW_H         # 192: min height for a 1-icon-row container
ONE_ICON_PANEL_W = PAD + ICON_COL_W         # 160: width for a single-icon panel


def build(out_path: Path) -> None:
    # -- Fault Domain (single vm icon) --------------------------------------
    fd_w, fd_h = ONE_ICON_PANEL_W, ONE_ICON_ROW_H
    fd_icon_x, fd_icon_y = PAD, ROW_Y

    # -- Availability Domain (wraps the Fault Domain) -----------------------
    ad_w = PAD + fd_w + PAD
    ad_h = NESTED_ROW_Y + fd_h + PAD

    # -- Subnet 1: load_balancer + vm side by side ---------------------------
    sub1_icon1_x = PAD
    sub1_icon2_x = PAD + ICON_COL_W
    subnet1_w = sub1_icon2_x + ICON_COL_W
    subnet1_h = ONE_ICON_ROW_H
    subnet_icon_y = ROW_Y

    # -- Subnet 2: autonomous_db (metadata + tooltip) ------------------------
    subnet2_w = ONE_ICON_PANEL_W
    subnet2_h = ONE_ICON_ROW_H
    sub2_icon_x = PAD

    # -- VCN (wraps the two subnets, side by side) ---------------------------
    subnet1_x, subnet1_y = PAD, NESTED_ROW_Y
    subnet2_x = subnet1_x + subnet1_w + GAP
    subnet2_y = NESTED_ROW_Y
    vcn_w = subnet2_x + subnet2_w + PAD
    vcn_h = NESTED_ROW_Y + max(subnet1_h, subnet2_h) + PAD

    # -- Compartment (wraps the VCN) ------------------------------------------
    compartment_w = PAD + vcn_w + PAD
    compartment_h = NESTED_ROW_Y + vcn_h + PAD

    # -- Services panel: vault (derived size) + buckets (explicit 75x95) ----
    svc_icon1_x = PAD
    svc_icon2_x = PAD + ICON_COL_W
    services_w = svc_icon2_x + ICON_COL_W
    services_h = ONE_ICON_ROW_H
    services_icon_y = ROW_Y

    # -- Oracle Services Network panel: single service_gateway icon --------
    osn_w, osn_h = ONE_ICON_PANEL_W, ONE_ICON_ROW_H
    osn_icon_x, osn_icon_y = PAD, ROW_Y

    # -- Region row: Availability Domain, Compartment, Services, OSN --------
    ad_x, ad_y = PAD, NESTED_ROW_Y
    compartment_x = ad_x + ad_w + GAP
    compartment_y = NESTED_ROW_Y
    services_x = compartment_x + compartment_w + GAP
    services_y = NESTED_ROW_Y
    osn_x = services_x + services_w + GAP
    osn_y = NESTED_ROW_Y
    region_w = osn_x + osn_w + PAD
    region_h = NESTED_ROW_Y + max(ad_h, compartment_h, services_h, osn_h) + PAD

    # -- On-Premises panel: single cpe icon -----------------------------------
    onprem_w, onprem_h = ONE_ICON_PANEL_W, ONE_ICON_ROW_H
    onprem_icon_x, onprem_icon_y = PAD, ROW_Y

    # -- Tenancy row: On-Premises, Region --------------------------------------
    onprem_x, onprem_y = PAD, NESTED_ROW_Y
    region_x = onprem_x + onprem_w + GAP
    region_y = NESTED_ROW_Y
    tenancy_w = region_x + region_w + PAD
    tenancy_h = NESTED_ROW_Y + max(onprem_h, region_h) + PAD

    # -- Page: title, then the tenancy row -------------------------------------
    title_x, title_y, title_w, title_h = PAD, 10, 900, 30
    tenancy_x = PAD
    tenancy_y = title_y + title_h + GAP
    page_w = tenancy_x + tenancy_w + PAD
    page_h = tenancy_y + tenancy_h + PAD

    d = DrawioBuilder(page_name="DrawioBuilder v1.1.0 Demo", width=page_w, height=page_h)

    d.add_text(
        "DrawioBuilder v1.1.0 Demo Diagram",
        x=title_x, y=title_y, w=title_w, h=title_h,
        font_size=18, font_style=1,
    )

    tenancy = d.add_group("Tenancy: demo-tenancy", tenancy_x, tenancy_y,
                           tenancy_w, tenancy_h, group_type="tenancy")

    onprem = d.add_group("On-Premises", onprem_x, onprem_y, onprem_w, onprem_h,
                          parent=tenancy, group_type="onprem")
    cpe = d.add_icon("Customer Premises Equipment", "cpe",
                      onprem_icon_x, onprem_icon_y, parent=onprem)

    region = d.add_group("Region: us-ashburn-1", region_x, region_y,
                          region_w, region_h, parent=tenancy, group_type="region")

    ad = d.add_group("Availability Domain 1", ad_x, ad_y, ad_w, ad_h,
                      parent=region, group_type="availability_domain")
    fd = d.add_group("Fault Domain 1", PAD, NESTED_ROW_Y, fd_w, fd_h,
                      parent=ad, group_type="fault_domain")
    vm_fd = d.add_icon("App VM", "vm", fd_icon_x, fd_icon_y, parent=fd)

    compartment = d.add_group("Compartment: demo-compartment", compartment_x,
                               compartment_y, compartment_w, compartment_h,
                               parent=region, group_type="compartment")
    vcn = d.add_group("VCN: demo-vcn (10.0.0.0/16)", PAD, NESTED_ROW_Y,
                       vcn_w, vcn_h, parent=compartment, group_type="vcn")

    subnet1 = d.add_group("sn-public-1 (10.0.1.0/24)", subnet1_x, subnet1_y,
                           subnet1_w, subnet1_h, parent=vcn, group_type="subnet")
    lb = d.add_icon("Load Balancer", "load_balancer",
                     sub1_icon1_x, subnet_icon_y, parent=subnet1)
    vm_sn1 = d.add_icon("Web VM", "vm",
                         sub1_icon2_x, subnet_icon_y, parent=subnet1)

    subnet2 = d.add_group("sn-data-1 (10.0.2.0/24)", subnet2_x, subnet2_y,
                           subnet2_w, subnet2_h, parent=vcn, group_type="subnet")
    adb = d.add_icon(
        "Autonomous Database", "autonomous_db", sub2_icon_x, subnet_icon_y,
        parent=subnet2,
        metadata={"ocid": "ocid1.autonomousdatabase.oc1..demo", "workload": "OLTP"},
        tooltip="Autonomous DB (demo metadata)",
    )

    services = d.add_group("Services", services_x, services_y,
                            services_w, services_h, parent=region, group_type="services")
    vault = d.add_icon("Vault", "vault", svc_icon1_x, services_icon_y, parent=services)
    buckets = d.add_icon("Object Storage", "buckets", svc_icon2_x, services_icon_y,
                          parent=services, w=75, h=95)

    osn = d.add_group("Oracle Services Network", osn_x, osn_y, osn_w, osn_h,
                       parent=region, group_type="oracle_services_network")
    svc_gw = d.add_icon("Service Gateway", "service_gateway",
                         osn_icon_x, osn_icon_y, parent=osn)

    containers = [tenancy, onprem, region, ad, fd, compartment, vcn,
                  subnet1, subnet2, services, osn]
    icons = [cpe, vm_fd, lb, vm_sn1, adb, vault, buckets, svc_gw]

    # -- Edges ----------------------------------------------------------------
    # 1. Modern, same-container: load_balancer -> vm inside subnet 1.
    e1 = d.add_edge(lb, vm_sn1, "443", parent=subnet1)

    # 2. Modern, cross-container: cpe -> load_balancer. The common ancestor
    #    of cpe (tenancy/onprem) and load_balancer (tenancy/region/.../subnet1)
    #    is the tenancy container.
    e2 = d.add_edge(cpe, lb, "", parent=tenancy)

    # 3. Legacy, pinned + waypoints: vm (subnet 1) -> autonomous_db
    #    (subnet 2), routed through the gap between the two subnets.
    #    Coordinates are vcn-relative since parent=vcn.
    gap_x = (subnet1_x + subnet1_w + subnet2_x) / 2
    wp_y = subnet1_y + subnet_icon_y + ICON_H / 2
    e3 = d.add_edge(
        vm_sn1, adb, "", parent=vcn,
        exit_x=1.0, exit_y=0.5, entry_x=0.0, entry_y=0.5,
        waypoints=[(gap_x, wp_y)],
    )

    # 4. Modern, dashed: vm (fault domain) -> vault. parent=region is the
    #    common ancestor of the availability-domain and services branches.
    e4 = d.add_edge(vm_fd, vault, "", parent=region, dashed=True)

    edges = [e1, e2, e3, e4]

    # -- Optional logo: embed the first bundled PNG if Pillow + logos/ exist.
    logos_dir = Path(__file__).resolve().parent.parent / "logos"
    if logos_dir.is_dir():
        pngs = sorted(logos_dir.glob("*.png"))
        if pngs:
            try:
                d.add_image(pngs[0], x=page_w - PAD - 148, y=title_y, w=148, h=39)
            except ImportError:
                pass  # Pillow not installed - skip the logo, not an error

    # -- Mandatory overlap gate before writing --------------------------------
    problems = d.check_overlaps()
    if problems:
        for p in problems:
            print(p)
        raise SystemExit(1)

    d.write(out_path)
    print(
        f"{out_path} | page {page_w}x{page_h} | "
        f"{len(containers)} containers, {len(icons)} icons, {len(edges)} edges"
    )


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo_architecture.drawio")
    build(out)
