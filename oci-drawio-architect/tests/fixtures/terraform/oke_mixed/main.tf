# An OKE cluster that shares its subnet with an unrelated instance, twice over:
# in sn-app the cluster and its one node pool fill a whole row of the icon grid,
# so the group box is drawn around them; in sn-mgmt the cluster and its two node
# pools do not, so no box is drawn and the parser warns.

resource "oci_core_vcn" "apps" {
  compartment_id = "ocid1.compartment.oc1..aaaafixture"
  display_name   = "vcn-apps"
  cidr_blocks    = ["10.5.0.0/16"]
}

resource "oci_core_subnet" "app" {
  compartment_id             = "ocid1.compartment.oc1..aaaafixture"
  vcn_id                     = oci_core_vcn.apps.id
  display_name               = "sn-app"
  cidr_block                 = "10.5.1.0/24"
  prohibit_public_ip_on_vnic = true
}

resource "oci_core_subnet" "mgmt" {
  compartment_id             = "ocid1.compartment.oc1..aaaafixture"
  vcn_id                     = oci_core_vcn.apps.id
  display_name               = "sn-mgmt"
  cidr_block                 = "10.5.2.0/24"
  prohibit_public_ip_on_vnic = true
}

# declared BEFORE the cluster on purpose: the parser has to move it behind the
# cluster's members for the group box to fill whole rows
resource "oci_core_instance" "bastion" {
  compartment_id      = "ocid1.compartment.oc1..aaaafixture"
  availability_domain = "fixture-AD-1"
  display_name        = "bastion"
  shape               = "VM.Standard.E4.Flex"
  create_vnic_details {
    subnet_id = oci_core_subnet.app.id
  }
}

resource "oci_containerengine_cluster" "app" {
  compartment_id     = "ocid1.compartment.oc1..aaaafixture"
  vcn_id             = oci_core_vcn.apps.id
  name               = "oke-app"
  kubernetes_version = "v1.29.1"
  endpoint_config {
    subnet_id = oci_core_subnet.app.id
  }
}

resource "oci_containerengine_node_pool" "app" {
  compartment_id     = "ocid1.compartment.oc1..aaaafixture"
  cluster_id         = oci_containerengine_cluster.app.id
  name               = "np-app"
  kubernetes_version = "v1.29.1"
  node_shape         = "VM.Standard.E4.Flex"
  node_config_details {
    size = 3
    placement_configs {
      subnet_id = oci_core_subnet.app.id
    }
  }
}

resource "oci_core_instance" "jump" {
  compartment_id      = "ocid1.compartment.oc1..aaaafixture"
  availability_domain = "fixture-AD-1"
  display_name        = "jump"
  shape               = "VM.Standard.E4.Flex"
  create_vnic_details {
    subnet_id = oci_core_subnet.mgmt.id
  }
}

resource "oci_containerengine_cluster" "mgmt" {
  compartment_id     = "ocid1.compartment.oc1..aaaafixture"
  vcn_id             = oci_core_vcn.apps.id
  name               = "oke-mgmt"
  kubernetes_version = "v1.29.1"
  endpoint_config {
    subnet_id = oci_core_subnet.mgmt.id
  }
}

resource "oci_containerengine_node_pool" "mgmt_a" {
  compartment_id     = "ocid1.compartment.oc1..aaaafixture"
  cluster_id         = oci_containerengine_cluster.mgmt.id
  name               = "np-mgmt-a"
  kubernetes_version = "v1.29.1"
  node_shape         = "VM.Standard.E4.Flex"
  node_config_details {
    size = 2
    placement_configs {
      subnet_id = oci_core_subnet.mgmt.id
    }
  }
}

resource "oci_containerengine_node_pool" "mgmt_b" {
  compartment_id     = "ocid1.compartment.oc1..aaaafixture"
  cluster_id         = oci_containerengine_cluster.mgmt.id
  name               = "np-mgmt-b"
  kubernetes_version = "v1.29.1"
  node_shape         = "VM.Standard.E4.Flex"
  node_config_details {
    size = 2
    placement_configs {
      subnet_id = oci_core_subnet.mgmt.id
    }
  }
}
