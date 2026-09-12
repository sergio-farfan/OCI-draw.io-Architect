terraform {
  required_version = ">= 1.3"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 5.0"
    }
  }
}

# Primary provider; the alias is for the home region only (ignored by the parser).
provider "oci" {
  region              = var.region
  tenancy_ocid        = var.tenancy_ocid
  config_file_profile = "DEFAULT"
}

provider "oci" {
  alias  = "home"
  region = "eu-frankfurt-1"
}
