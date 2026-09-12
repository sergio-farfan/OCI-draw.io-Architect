variable "tenancy_ocid" {}
variable "user_ocid" { default = "ocid1.user.oc1..aaaauser" }
variable "other_tenancy" {
  description = "A different tenancy - must never be reported as tenancy_ocid"
  default     = "ocid1.tenancy.oc1..aaaaother"
}
variable "compartment_ocid" {
  description = "Target compartment"
  default     = "ocid1.compartment.oc1..aaaacomp"
  }
variable "region" {
  type        = string
  description = "Region; the description has a # hash and // slashes and a /* block */"
  default     = "eu-frankfurt-1" # inline comment
  validation {
    condition     = length(var.region) > 0
    error_message = "region must be set"
  }
  }
variable "profile" { default = "FRANKFURT" }
variable "vcn_name" {
  default = "hub-vcn"
}
variable "spoke_vcns" {
  type = map(any)
  default = {
    spoke1 = {
      display_name = "spoke1-vcn"
      cidr_blocks  = ["10.1.0.0/16"]
    }
  }
}
