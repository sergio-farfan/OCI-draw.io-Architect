region       = "eu-frankfurt-1"
tenancy_ocid = "ocid1.tenancy.oc1..aaaatf" # real tenancy
# tenancy_ocid = "ocid1.tenancy.oc1..commented"

vcns = {
  hub = {
    display_name = "hub-vcn"
    cidr         = "10.0.0.0/16"
  }
  spoke = { display_name = "spoke-vcn", cidr_blocks = ["10.1.0.0/16"] }
}
