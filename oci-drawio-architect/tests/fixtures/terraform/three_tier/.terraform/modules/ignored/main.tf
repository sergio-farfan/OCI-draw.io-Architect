resource "oci_core_vcn" "ignored" {
  display_name = "must-not-appear"
  cidr_block   = "192.0.2.0/24"
}
