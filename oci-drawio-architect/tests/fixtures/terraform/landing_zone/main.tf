resource "oci_identity_compartment" "enclosing" {
  compartment_id = var.tenancy_ocid
  name           = "enclosing"
  description    = "Enclosing compartment of the landing zone"
}

resource "oci_identity_compartment" "network" {
  compartment_id = oci_identity_compartment.enclosing.id
  name           = "network"
  description    = "Network compartment: both VCNs and the DRG"
}

resource "oci_core_vcn" "hub" {
  compartment_id = oci_identity_compartment.network.id
  display_name   = "vcn-hub"
  cidr_blocks    = [var.hub_cidr]
}

resource "oci_core_vcn" "spoke" {
  compartment_id = oci_identity_compartment.network.id
  display_name   = "vcn-spoke"
  cidr_blocks    = [var.spoke_cidr]
}

resource "oci_core_subnet" "web" {
  compartment_id             = oci_identity_compartment.network.id
  vcn_id                     = oci_core_vcn.hub.id
  display_name               = "sn-web"
  cidr_block                 = local.subnet_cidrs["web"]
  prohibit_public_ip_on_vnic = false
}

resource "oci_core_subnet" "app" {
  compartment_id             = oci_identity_compartment.network.id
  vcn_id                     = oci_core_vcn.spoke.id
  display_name               = "sn-app"
  cidr_block                 = local.subnet_cidrs["app"]
  prohibit_public_ip_on_vnic = true
}

resource "oci_core_internet_gateway" "hub" {
  compartment_id = oci_identity_compartment.network.id
  vcn_id         = oci_core_vcn.hub.id
  display_name   = "igw-hub"
}

resource "oci_load_balancer_load_balancer" "web" {
  compartment_id = oci_identity_compartment.network.id
  display_name   = "lb-web"
  shape          = "flexible"
  subnet_ids     = [oci_core_subnet.web.id]
}

resource "oci_containerengine_cluster" "main" {
  compartment_id     = oci_identity_compartment.network.id
  vcn_id             = oci_core_vcn.spoke.id
  name               = "oke-main"
  kubernetes_version = "v1.29.1"
  endpoint_config {
    subnet_id = oci_core_subnet.app.id
  }
}

resource "oci_containerengine_node_pool" "system" {
  compartment_id     = oci_identity_compartment.network.id
  cluster_id         = oci_containerengine_cluster.main.id
  name               = "np-system"
  kubernetes_version = "v1.29.1"
  node_shape         = "VM.Standard.E4.Flex"
  node_config_details {
    size = 3
    placement_configs {
      subnet_id = oci_core_subnet.app.id
    }
  }
}

resource "oci_containerengine_node_pool" "apps" {
  compartment_id     = oci_identity_compartment.network.id
  cluster_id         = oci_containerengine_cluster.main.id
  name               = "np-apps"
  kubernetes_version = "v1.29.1"
  node_shape         = "VM.Standard.E4.Flex"
  node_config_details {
    size = 2
    placement_configs {
      subnet_id = oci_core_subnet.app.id
    }
  }
}

resource "oci_core_drg" "lz" {
  compartment_id = oci_identity_compartment.network.id
  display_name   = "drg-lz"
}

resource "oci_core_drg_route_table" "vcn" {
  drg_id       = oci_core_drg.lz.id
  display_name = "drg-rt-vcn"
}

resource "oci_core_drg_route_table" "other" {
  drg_id       = oci_core_drg.lz.id
  display_name = "drg-rt-other"
}

resource "oci_core_drg_attachment" "hub" {
  drg_id       = oci_core_drg.lz.id
  display_name = "att-hub"
  network_details {
    id   = oci_core_vcn.hub.id
    type = "VCN"
  }
}

resource "oci_core_drg_attachment" "spoke" {
  drg_id       = oci_core_drg.lz.id
  display_name = "att-spoke"
  network_details {
    id   = oci_core_vcn.spoke.id
    type = "VCN"
  }
}
