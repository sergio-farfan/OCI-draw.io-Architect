variable "tenancy_ocid" {
  type = string
}

provider "oci" {
  region = "eu-frankfurt-1"
}

resource "oci_identity_compartment" "net" {
  compartment_id = var.tenancy_ocid
  name           = "network"
  description    = "Shared network"
}

resource "oci_core_vcn" "hub" {
  compartment_id = oci_identity_compartment.net.id
  display_name   = "vcn-hub"
  cidr_blocks    = ["10.10.0.0/16"]
}

resource "oci_core_vcn" "spoke" {
  compartment_id = oci_identity_compartment.net.id
  display_name   = "vcn-spoke"
  cidr_blocks    = ["10.20.0.0/16"]
}

resource "oci_core_subnet" "mgmt" {
  compartment_id             = oci_identity_compartment.net.id
  vcn_id                     = oci_core_vcn.hub.id
  display_name               = "sn-mgmt"
  cidr_block                 = "10.10.0.0/24"
  prohibit_public_ip_on_vnic = true
}

resource "oci_core_subnet" "app" {
  compartment_id             = oci_identity_compartment.net.id
  vcn_id                     = oci_core_vcn.spoke.id
  display_name               = "sn-app"
  cidr_block                 = "10.20.1.0/24"
  prohibit_public_ip_on_vnic = true
}

resource "oci_core_instance" "app" {
  compartment_id = oci_identity_compartment.net.id
  display_name   = "app-1"
  shape          = "VM.Standard.E4.Flex"
  create_vnic_details {
    subnet_id = oci_core_subnet.app.id
  }
}

resource "oci_core_service_gateway" "spoke" {
  compartment_id = oci_identity_compartment.net.id
  vcn_id         = oci_core_vcn.spoke.id
  display_name   = "sgw-spoke"
}

resource "oci_core_drg" "core" {
  compartment_id = oci_identity_compartment.net.id
  display_name   = "drg-core"
}

resource "oci_core_drg_attachment" "hub" {
  drg_id       = oci_core_drg.core.id
  display_name = "att-hub"
  network_details {
    id   = oci_core_vcn.hub.id
    type = "VCN"
  }
}

resource "oci_core_drg_attachment" "spoke" {
  drg_id       = oci_core_drg.core.id
  display_name = "att-spoke"
  network_details {
    id   = oci_core_vcn.spoke.id
    type = "VCN"
  }
}

resource "oci_core_local_peering_gateway" "hub" {
  compartment_id = oci_identity_compartment.net.id
  vcn_id         = oci_core_vcn.hub.id
  display_name   = "lpg-hub"
  peer_id        = oci_core_local_peering_gateway.spoke.id
}

resource "oci_core_local_peering_gateway" "spoke" {
  compartment_id = oci_identity_compartment.net.id
  vcn_id         = oci_core_vcn.spoke.id
  display_name   = "lpg-spoke"
}

resource "oci_core_virtual_circuit" "fc" {
  compartment_id = oci_identity_compartment.net.id
  display_name   = "fc-hq"
  type           = "PRIVATE"
  gateway_id     = oci_core_drg.core.id
}

resource "oci_core_remote_peering_connection" "dr" {
  compartment_id = oci_identity_compartment.net.id
  display_name   = "rpc-dr"
  drg_id         = oci_core_drg.core.id
}

resource "oci_logging_log_group" "app" {
  compartment_id = oci_identity_compartment.net.id
  display_name   = "lg-app"
}
