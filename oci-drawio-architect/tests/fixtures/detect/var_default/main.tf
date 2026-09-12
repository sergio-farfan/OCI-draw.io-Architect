locals {
  mgmt_cidr = "10.20.0.0/16"
}

resource "oci_core_vcn" "hub" {
  compartment_id = var.compartment_ocid
  display_name   = var.vcn_name
  cidr_blocks    = ["10.10.0.0/16", "10.11.0.0/16"]
  dns_label      = "hub"
}

resource "oci_core_vcn" "mgmt" {
  compartment_id = var.compartment_ocid
  display_name   = "mgmt-vcn"
  cidr_block     = local.mgmt_cidr
}

resource "oci_core_vcn" "dynamic" {
  for_each       = var.spoke_vcns
  compartment_id = var.compartment_ocid
  display_name   = each.value.display_name
  cidr_blocks    = each.value.cidr_blocks
}

resource "oci_identity_compartment" "network" {
  compartment_id = var.tenancy_ocid
  name           = "network"
  description    = "Network compartment"
}

resource "oci_core_instance" "bastion" {
  compartment_id = var.compartment_ocid
  metadata = {
    user_data = base64encode(<<-EOT
      #!/bin/bash
      echo "unbalanced quote # not a comment
      EOT
    )
  }
}
