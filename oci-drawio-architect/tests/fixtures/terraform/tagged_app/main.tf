# Two applications and two environments in one VCN: the fixture that drives
# filtering, participating mode and the label modes end to end.
#
# Three shapes here are load-bearing and must not be "tidied":
#   * a multi-entry tag map is written MULTI-LINE - detect_settings splits HCL
#     statements on newlines, so "a = 1, b = 2" on one line is unparseable and
#     the tags would silently vanish. A single-entry inline map is fine.
#   * every compartment_id REFERENCES oci_identity_compartment.app - the
#     ModelBuilder resolves a compartment name only through that reference, and
#     a literal OCID yields no metadata.compartment at all.
#   * the compute instances place themselves through create_vnic_details, which
#     is the non-deprecated form and the one every other fixture uses.
variable "app_tag" { default = "payments" }
variable "unresolved_env" {}

resource "oci_identity_compartment" "app" {
  name           = "app-prod"
  description    = "Application compartment"
  compartment_id = "ocid1.tenancy.oc1..aaaaexample"
}

resource "oci_core_vcn" "app" {
  compartment_id = oci_identity_compartment.app.id
  display_name   = "vcn-app"
  cidr_block     = "10.0.0.0/16"
  freeform_tags  = { "Application" = var.app_tag }
}

resource "oci_core_subnet" "web" {
  vcn_id         = oci_core_vcn.app.id
  display_name   = "sn-web"
  cidr_block     = "10.0.1.0/24"
  compartment_id = oci_identity_compartment.app.id
}

resource "oci_core_subnet" "app" {
  vcn_id                     = oci_core_vcn.app.id
  display_name               = "sn-app"
  cidr_block                 = "10.0.3.0/24"
  compartment_id             = oci_identity_compartment.app.id
  prohibit_public_ip_on_vnic = true
}

resource "oci_core_instance" "broker" {
  display_name        = "App Broker VM"
  compartment_id      = oci_identity_compartment.app.id
  shape               = "VM.Standard.E5.Flex"
  availability_domain = "Uocm:PHX-AD-1"
  fault_domain        = "FAULT-DOMAIN-2"

  create_vnic_details {
    subnet_id      = oci_core_subnet.web.id
    hostname_label = "broker"
  }

  freeform_tags = {
    "Application" = "payments"
    "Environment" = "prod"
  }
  defined_tags = { "Ops.Tier" = "gold" }
}

resource "oci_core_instance" "batch" {
  display_name   = "Batch VM"
  compartment_id = oci_identity_compartment.app.id
  shape          = "VM.Standard.E4.Flex"

  create_vnic_details {
    subnet_id      = oci_core_subnet.app.id
    hostname_label = "batch"
  }

  freeform_tags = {
    "Application" = "reporting"
    "Environment" = var.unresolved_env
  }
}

resource "oci_load_balancer_load_balancer" "web" {
  display_name   = "Web LB"
  subnet_ids     = [oci_core_subnet.web.id]
  compartment_id = oci_identity_compartment.app.id
  freeform_tags  = { "Application" = "payments" }
}

resource "oci_load_balancer_listener" "https" {
  load_balancer_id = oci_load_balancer_load_balancer.web.id
  name             = "https"
  port             = 443
  protocol         = "HTTP"
}

resource "oci_database_autonomous_database" "core" {
  display_name   = "Core ADB"
  subnet_id      = oci_core_subnet.app.id
  db_name        = "coredb"
  compartment_id = oci_identity_compartment.app.id
  freeform_tags  = { "Application" = "payments" }
}

# A genuine config reference between two DRAWN items, so the "config"
# provenance of 6.8 has something to produce in this fixture. The cluster's
# endpoint and the node pool sit in DIFFERENT subnets on purpose: an
# oke_cluster group box is only built when they share one, and Step 8's
# _config_edges deliberately skips a pair that is already inside the same box.
resource "oci_containerengine_cluster" "app" {
  name               = "app-oke"
  compartment_id     = oci_identity_compartment.app.id
  vcn_id             = oci_core_vcn.app.id
  kubernetes_version = "v1.29.1"
  freeform_tags      = { "Application" = "payments" }
  endpoint_config {
    subnet_id = oci_core_subnet.web.id
  }
}

resource "oci_containerengine_node_pool" "app" {
  name               = "app-pool"
  compartment_id     = oci_identity_compartment.app.id
  cluster_id         = oci_containerengine_cluster.app.id
  kubernetes_version = "v1.29.1"
  node_shape         = "VM.Standard.E4.Flex"
  freeform_tags      = { "Application" = "payments" }
  node_config_details {
    size = 2
    placement_configs {
      subnet_id = oci_core_subnet.app.id
    }
  }
}
