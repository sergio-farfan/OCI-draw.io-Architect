variable "compartment_ocid" {
  type = string
}

variable "vcns" {
  description = "Map of VCNs and their subnets; drives everything."
  type        = any
}

locals {
  subnets = merge([
    for vk, v in var.vcns : {
      for sk, s in v.subnets : "${vk}-${sk}" => merge(s, { vcn_key = vk })
    }
  ]...)
}

resource "oci_core_vcn" "this" {
  for_each       = var.vcns
  compartment_id = var.compartment_ocid
  display_name   = each.value.display_name
  cidr_blocks    = [each.value.cidr]
}

resource "oci_core_subnet" "this" {
  for_each                   = local.subnets
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.this[each.value.vcn_key].id
  display_name               = each.value.name
  cidr_block                 = each.value.cidr
  prohibit_public_ip_on_vnic = !each.value.is_public
}

resource "oci_bastion_bastion" "ops" {
  compartment_id   = var.compartment_ocid
  name             = "bastion-ops"
  bastion_type     = "STANDARD"
  target_subnet_id = oci_core_subnet.this["hub-mgmt"].id
}
