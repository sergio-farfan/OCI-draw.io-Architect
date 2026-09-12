data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

data "oci_core_services" "all" {}

resource "oci_identity_compartment" "app" {
  compartment_id = var.tenancy_ocid
  name           = "shop-prod"
  description    = "Shop production workloads" // trailing comment
  enable_delete  = false
}

resource "oci_core_vcn" "main" {
  compartment_id = oci_identity_compartment.app.id
  display_name   = var.vcn_name
  cidr_blocks    = [var.vcn_cidr]
  dns_label      = "shop"
  freeform_tags  = local.common_tags
}

/* Public tier: load balancers only. */
resource "oci_core_subnet" "lb" {
  compartment_id             = oci_identity_compartment.app.id
  vcn_id                     = oci_core_vcn.main.id
  display_name               = "sn-lb-public"
  cidr_block                 = local.subnet_cidrs["lb"]
  prohibit_public_ip_on_vnic = false
  route_table_id             = oci_core_route_table.public.id
  security_list_ids          = [oci_core_security_list.app.id]
}

resource "oci_core_subnet" "app" {
  compartment_id             = oci_identity_compartment.app.id
  vcn_id                     = oci_core_vcn.main.id
  display_name               = "sn-app"
  cidr_block                 = local.subnet_cidrs.app
  prohibit_public_ip_on_vnic = true
}

resource "oci_core_subnet" "db" {
  compartment_id             = oci_identity_compartment.app.id
  vcn_id                     = oci_core_vcn.main.id
  display_name               = "sn-database"
  cidr_block                 = local.subnet_cidrs["db"]
  prohibit_public_ip_on_vnic = true
}

resource "oci_core_internet_gateway" "igw" {
  compartment_id = oci_identity_compartment.app.id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "igw-shop"
}

resource "oci_core_nat_gateway" "nat" {
  compartment_id = oci_identity_compartment.app.id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "nat-shop"
}

resource "oci_core_service_gateway" "sgw" {
  compartment_id = oci_identity_compartment.app.id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "sgw-shop"
  services {
    service_id = data.oci_core_services.all.services[0].id
  }
}

resource "oci_core_route_table" "public" {
  compartment_id = oci_identity_compartment.app.id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "rt-public"
  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.igw.id
  }
}

resource "oci_core_security_list" "app" {
  compartment_id = oci_identity_compartment.app.id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "sl-app"
  ingress_security_rules {
    protocol = "6"
    source   = "0.0.0.0/0"
    tcp_options {
      min = 443
      max = 443
    }
  }
}

resource "oci_core_network_security_group" "app" {
  compartment_id = oci_identity_compartment.app.id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "nsg-app"
}

resource "oci_core_drg" "drg" {
  compartment_id = oci_identity_compartment.app.id
  display_name   = "drg-shop"
}

resource "oci_core_drg_attachment" "vcn" {
  drg_id       = oci_core_drg.drg.id
  display_name = "drg-att-shop"
  network_details {
    id   = oci_core_vcn.main.id
    type = "VCN"
  }
}

resource "oci_core_cpe" "onprem" {
  compartment_id = oci_identity_compartment.app.id
  display_name   = "cpe-hq"
  ip_address     = "203.0.113.10"
}

resource "oci_core_ipsec" "vpn" {
  compartment_id = oci_identity_compartment.app.id
  cpe_id         = oci_core_cpe.onprem.id
  drg_id         = oci_core_drg.drg.id
  display_name   = "vpn-hq"
  static_routes  = ["192.168.0.0/16"]
}
