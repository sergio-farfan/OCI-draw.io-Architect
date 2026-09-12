terraform {
  required_version = ">= 1.3"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 5.0"
    }
  }
  backend "s3" {
    bucket = "tf-state"
    region = "us-east-1" # AWS region - must be ignored
  }
}

# provider "oci" {
#   region = "us-phoenix-1"
# }

// region = "ap-tokyo-1"

provider "aws" {
  region = "eu-west-1"
}

provider "oci" {
  alias               = "home"
  region              = "us-ashburn-1"
  config_file_profile = "HOME"
}

provider "oci" {
  region              = var.region // primary provider
  config_file_profile = var.profile
  /* tenancy_ocid = "ocid1.tenancy.oc1..commentedout" */
  auth = "SecurityToken"
}
