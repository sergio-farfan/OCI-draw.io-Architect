resource "oci_core_instance" "app" {
  count               = 2
  compartment_id      = oci_identity_compartment.app.id
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
  display_name        = "app-server"
  shape               = var.app_shape

  shape_config {
    ocpus         = 2
    memory_in_gbs = 16
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.app.id
    assign_public_ip = false
    nsg_ids          = [oci_core_network_security_group.app.id]
  }

  source_details {
    source_type = "image"
    source_id   = var.image_ocid
  }

  metadata = {
    ssh_authorized_keys = file("~/.ssh/id_rsa.pub")
    user_data           = base64encode(<<-CLOUDINIT
      #cloud-config
      packages: [nginx]   # not a comment: inside a heredoc { with braces }
    CLOUDINIT
    )
  }
}

resource "oci_load_balancer_load_balancer" "public" {
  compartment_id = oci_identity_compartment.app.id
  display_name   = "lb-shop"
  shape          = "flexible"
  subnet_ids     = [oci_core_subnet.lb.id]
  is_private     = false
  network_security_group_ids = [oci_core_network_security_group.lb.id]

  shape_details {
    minimum_bandwidth_in_mbps = 10
    maximum_bandwidth_in_mbps = 100
  }
}

resource "oci_load_balancer_backend_set" "app" {
  load_balancer_id = oci_load_balancer_load_balancer.public.id
  name             = "bs-app"
  policy           = "ROUND_ROBIN"
  health_checker {
    protocol = "HTTP"
    port     = 8080
    url_path = "/health"
  }
}

resource "oci_load_balancer_listener" "https" {
  load_balancer_id         = oci_load_balancer_load_balancer.public.id
  name                     = "https"
  default_backend_set_name = oci_load_balancer_backend_set.app.name
  port                     = 443
  protocol                 = "HTTP"
}

resource "oci_database_autonomous_database" "shop" {
  compartment_id           = oci_identity_compartment.app.id
  display_name             = "adb-shop"
  db_name                  = "SHOP"
  db_workload              = "OLTP"
  cpu_core_count           = 1
  data_storage_size_in_tbs = 1
  subnet_id                = oci_core_subnet.db.id
  nsg_ids                  = [oci_core_network_security_group.app.id]
}

resource "oci_objectstorage_bucket" "assets" {
  compartment_id = oci_identity_compartment.app.id
  namespace      = data.oci_objectstorage_namespace.ns.namespace
  name           = "shop-assets"
  access_type    = "NoPublicAccess"
}

resource "oci_kms_vault" "shop" {
  compartment_id = oci_identity_compartment.app.id
  display_name   = "vault-shop"
  vault_type     = "DEFAULT"
}

# Secondary VNIC: its NSGs join the instance's NSG badge (oci_core_instance.app[0] resolves to the base address).
resource "oci_core_vnic_attachment" "app_mgmt" {
  instance_id  = oci_core_instance.app[0].id
  display_name = "vnic-mgmt"
  create_vnic_details {
    subnet_id = oci_core_subnet.app.id
    nsg_ids   = [oci_core_network_security_group.mgmt.id, oci_core_network_security_group.app.id]
  }
}
