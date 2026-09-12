compartment_ocid = "ocid1.compartment.oc1..aaaamap"

vcns = {
  hub = {
    display_name = "vcn-hub"
    cidr         = "10.10.0.0/16"
    subnets = {
      mgmt = { name = "sn-mgmt", cidr = "10.10.0.0/24", is_public = false }
      web  = { name = "sn-web", cidr = "10.10.1.0/24", is_public = true }
    }
  }
  spoke = {
    display_name = "vcn-spoke-app"
    cidr         = "10.20.0.0/16"
    subnets = {
      app = { name = "sn-app", cidr = "10.20.1.0/24", is_public = false }
    }
  }
}
