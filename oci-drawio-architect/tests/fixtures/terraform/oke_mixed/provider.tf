terraform {
  required_version = ">= 1.3"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 5.0"
    }
  }
}

provider "oci" {
  region       = "eu-frankfurt-1"
  tenancy_ocid = "ocid1.tenancy.oc1..aaaafixture"
}
