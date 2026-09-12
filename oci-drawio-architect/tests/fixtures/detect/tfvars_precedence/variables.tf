variable "region" {
  default = "us-ashburn-1"
}
variable "tenancy_ocid" {
  type = string
}
variable "compartment_ocid" {
  type = string
}
variable "vcns" {
  type    = map(any)
  default = {}
}
