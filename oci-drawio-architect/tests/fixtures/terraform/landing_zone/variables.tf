variable "region" {
  type    = string
  default = "eu-frankfurt-1"
}

variable "tenancy_ocid" {
  type = string
}

variable "hub_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "spoke_cidr" {
  type    = string
  default = "10.1.0.0/16"
}

locals {
  subnet_cidrs = {
    web = cidrsubnet(var.hub_cidr, 8, 0)
    app = cidrsubnet(var.spoke_cidr, 8, 1)
  }
}
