provider "oci" {
  region              = var.region
  tenancy_ocid        = var.tenancy_ocid
  config_file_profile = "DEFAULT"
}
