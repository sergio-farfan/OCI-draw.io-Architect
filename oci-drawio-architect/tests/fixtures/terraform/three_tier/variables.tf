variable "region" {
  type    = string
  default = "eu-frankfurt-1"
}

variable "tenancy_ocid" {
  type = string
}

variable "compartment_ocid" {
  type = string
}

variable "vcn_name" {
  type    = string
  default = "vcn-default"
}

variable "vcn_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "app_shape" {
  type    = string
  default = "VM.Standard.E4.Flex"
}

variable "image_ocid" {
  type = string
}

locals {
  subnet_cidrs = {
    lb  = cidrsubnet(var.vcn_cidr, 8, 0)
    app = cidrsubnet(var.vcn_cidr, 8, 1)
    db  = "10.0.2.0/24"
  }
  common_tags = {
    Project = "shop"
  }
}
