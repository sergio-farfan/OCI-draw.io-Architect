# OCI SVG Icon Catalog

Icons bundled at: `${CLAUDE_PLUGIN_ROOT}/icons/` (override with `OCI_SVG_DIR` env var)

## Pre-Mapped Icons (ICON_MAP)

These 27 keys are ready to use with `add_icon()`:

| Key | SVG Path | Description |
|-----|----------|-------------|
| `load_balancer` | `networking/networking_load_balancer.svg` | Load Balancer |
| `vm` | `compute/compute_virtual_machine_vm.svg` | Compute VM |
| `block_storage` | `storage/storage_block_storage.svg` | Block Volume |
| `functions` | `compute/compute_functions.svg` | Functions |
| `autonomous_db` | `database/database_autonomous_db.svg` | Autonomous Database |
| `nosql` | `database/database_nosql.svg` | NoSQL / Redis |
| `nsg` | `identity_and_security/identity_and_security_nsg.svg` | Network Security Group |
| `big_data` | `analytics_and_ai/analytics_and_ai_big_data.svg` | OAC / Big Data |
| `service_gateway` | `networking/networking_service_gateway.svg` | Service Gateway |
| `data_science` | `analytics_and_ai/analytics_and_ai_data_science.svg` | Data Science / AIDP |
| `ai` | `analytics_and_ai/analytics_and_ai_artificial_intelligence.svg` | GenAI / AI |
| `vault` | `identity_and_security/identity_and_security_vault.svg` | Vault |
| `waf` | `identity_and_security/identity_and_security_waf.svg` | WAF |
| `certificates` | `identity_and_security/identity_and_security_certificates.svg` | SSL Certificates |
| `devops` | `developer_services/developer_services_devops.svg` | DevOps |
| `container_registry` | `developer_services/developer_services_container_registry.svg` | OCIR |
| `buckets` | `storage/storage_buckets.svg` | Object Storage Buckets |
| `queuing` | `observability_and_management/observability_and_management_queuing.svg` | Queues |
| `logging` | `observability_and_management/observability_and_management_logging.svg` | Logging |
| `apm` | `observability_and_management/observability_and_management_application_performance_management.svg` | APM |
| `alarms` | `observability_and_management/observability_and_management_alarms.svg` | Alarms |
| `dns` | `networking/networking_dns.svg` | DNS |
| `cpe` | `networking/networking_customer_premises_equipment_cpe.svg` | CPE / VPN |
| `drg` | `networking/networking_dynamic_routing_gateway_drg.svg` | DRG |
| `nat_gateway` | `networking/networking_nat_gateway.svg` | NAT Gateway |
| `firewall` | `identity_and_security/identity_and_security_firewall.svg` | Firewall |
| `internet_gateway` | `networking/networking_internet_gateway.svg` | Internet Gateway |

Add more with `add_icons_to_map({"key": "category/filename.svg"})`.

---

## Full Icon Inventory by Category

### Analytics & AI (10 icons)
| Suggested Key | SVG Path | Description |
|---------------|----------|-------------|
| `ai` | `analytics_and_ai/analytics_and_ai_artificial_intelligence.svg` | Artificial Intelligence |
| `big_data` | `analytics_and_ai/analytics_and_ai_big_data.svg` | Big Data / Analytics |
| `data_science` | `analytics_and_ai/analytics_and_ai_data_science.svg` | Data Science |
| `digital_assistant` | `analytics_and_ai/analytics_and_ai_digital_assistant.svg` | Digital Assistant (ODA) |
| `essbase` | `analytics_and_ai/analytics_and_ai_essbase.svg` | Essbase |
| `ml` | `analytics_and_ai/analytics_and_ai_machine_learning.svg` | Machine Learning |
| `message_listener` | `analytics_and_ai/analytics_and_ai_message_listener.svg` | Message Listener |
| `message_producer` | `analytics_and_ai/analytics_and_ai_message_producer.svg` | Message Producer |
| `connector_hub` | `analytics_and_ai/analytics_and_ai_service_connector_hub.svg` | Service Connector Hub |
| `streaming` | `analytics_and_ai/analytics_and_ai_streaming.svg` | Streaming |

### Applications (20 icons)
| Suggested Key | SVG Path | Description |
|---------------|----------|-------------|
| `bi_connector` | `applications/applications_bi_cloud_connector.svg` | BI Cloud Connector |
| `cpq` | `applications/applications_cpq.svg` | CPQ |
| `ebs` | `applications/applications_e_business_suite.svg` | E-Business Suite |
| `engagement` | `applications/applications_engagement.svg` | Engagement |
| `epm` | `applications/applications_epm.svg` | EPM |
| `erp` | `applications/applications_erp.svg` | ERP |
| `financials` | `applications/applications_financials.svg` | Financials |
| `fusion` | `applications/applications_fusion.svg` | Fusion |
| `hcm` | `applications/applications_hcm.svg` | HCM |
| `healthcare` | `applications/applications_healthcare.svg` | Healthcare |
| `innovation` | `applications/applications_innovation_management.svg` | Innovation Management |
| `inventory` | `applications/applications_inventory_management.svg` | Inventory Management |
| `manufacturing` | `applications/applications_manufacturing.svg` | Manufacturing |
| `oco_subnet` | `applications/applications_oco_subnet.svg` | OCO Subnet |
| `order_mgmt` | `applications/applications_order_management.svg` | Order Management |
| `procurement` | `applications/applications_procurement.svg` | Procurement |
| `pdm` | `applications/applications_product_master_data_management.svg` | Product Master Data |
| `project_financial` | `applications/applications_project_financial_management.svg` | Project Financial Mgmt |
| `project_mgmt` | `applications/applications_project_management.svg` | Project Management |
| `supply_chain` | `applications/applications_supply_chain_planning.svg` | Supply Chain Planning |

### Compute (7 icons)
| Suggested Key | SVG Path | Description |
|---------------|----------|-------------|
| `autoscaling` | `compute/compute_autoscaling.svg` | Autoscaling |
| `bare_metal` | `compute/compute_bare_metal_compute.svg` | Bare Metal |
| `burstable_vm` | `compute/compute_burstable_virtual_machine_burstable_vm.svg` | Burstable VM |
| `flex_vm` | `compute/compute_flex_virtual_machine_flex_vm.svg` | Flex VM |
| `functions` | `compute/compute_functions.svg` | Functions |
| `instance_pools` | `compute/compute_instance_pools.svg` | Instance Pools |
| `vm` | `compute/compute_virtual_machine_vm.svg` | VM |

### Database (18 icons)
| Suggested Key | SVG Path | Description |
|---------------|----------|-------------|
| `adb_d` | `database/database_adb_d.svg` | ADB Dedicated |
| `adw_d` | `database/database_adw_d.svg` | ADW Dedicated |
| `atp_d` | `database/database_atp_d.svg` | ATP Dedicated |
| `adw` | `database/database_autonomous_data_warehouse_adw.svg` | Autonomous Data Warehouse |
| `autonomous_db` | `database/database_autonomous_db.svg` | Autonomous Database |
| `atp` | `database/database_autonomous_transaction_processing_atp.svg` | ATP |
| `data_safe` | `database/database_data_safe.svg` | Data Safe |
| `db_system` | `database/database_database_system.svg` | DB System |
| `exadata` | `database/database_exadata.svg` | Exadata |
| `exadata_cc` | `database/database_exadata_c_c.svg` | Exadata Cloud@Customer |
| `goldengate` | `database/database_goldengate.svg` | GoldenGate |
| `gg_adapter` | `database/database_goldengate_application_adapter.svg` | GoldenGate Adapter |
| `gg_director` | `database/database_goldengate_director.svg` | GoldenGate Director |
| `mysql` | `database/database_mysql.svg` | MySQL |
| `nosql` | `database/database_nosql.svg` | NoSQL |
| `opensearch` | `database/database_opensearch.svg` | OpenSearch |
| `rac` | `database/database_rac.svg` | RAC |
| *(+ 5 more GoldenGate variants)* | | |

### Developer Services (15 icons)
| Suggested Key | SVG Path | Description |
|---------------|----------|-------------|
| `apex` | `developer_services/developer_services_apex.svg` | APEX |
| `api_gateway` | `developer_services/developer_services_api_gateway.svg` | API Gateway |
| `api_service` | `developer_services/developer_services_api_service.svg` | API Service |
| `oke` | `developer_services/developer_services_container_engine_for_kubernetes.svg` | OKE |
| `container_registry` | `developer_services/developer_services_container_registry.svg` | Container Registry |
| `content_mgmt` | `developer_services/developer_services_content_management.svg` | Content Management |
| `devops` | `developer_services/developer_services_devops.svg` | DevOps |
| `email` | `developer_services/developer_services_email_delivery.svg` | Email Delivery |
| `integrations` | `developer_services/developer_services_integrations.svg` | Integrations (OIC) |
| `jet` | `developer_services/developer_services_jet.svg` | JET |
| `notifications` | `developer_services/developer_services_notifications.svg` | Notifications |
| `private_endpoint` | `developer_services/developer_services_private_endpoint_ip.svg` | Private Endpoint |
| `resource_manager` | `developer_services/developer_services_resource_manager.svg` | Resource Manager |
| `service_mesh` | `developer_services/developer_services_service_mesh.svg` | Service Mesh |
| `visual_builder` | `developer_services/developer_services_visual_builder.svg` | Visual Builder |

### Governance & Administration (5 icons)
| Suggested Key | SVG Path | Description |
|---------------|----------|-------------|
| `cloud_advisor` | `governance_and_administration/governance_and_administration_cloud_advisor.svg` | Cloud Advisor |
| `license_mgr` | `governance_and_administration/governance_and_administration_license_manager.svg` | License Manager |
| `cloud_id` | `governance_and_administration/governance_and_administration_oracle_cloud_identifier.svg` | Oracle Cloud ID |
| `organization` | `governance_and_administration/governance_and_administration_organization.svg` | Organization |
| `tagging` | `governance_and_administration/governance_and_administration_tagging.svg` | Tagging |

### Identity & Security (22 icons)
| Suggested Key | SVG Path | Description |
|---------------|----------|-------------|
| `active_directory` | `identity_and_security/identity_and_security_active_directory.svg` | Active Directory |
| `bastion` | `identity_and_security/identity_and_security_bastion.svg` | Bastion |
| `certificates` | `identity_and_security/identity_and_security_certificates.svg` | Certificates |
| `cloud_guard` | `identity_and_security/identity_and_security_cloud_guard.svg` | Cloud Guard |
| `compartments` | `identity_and_security/identity_and_security_compartments.svg` | Compartments |
| `ddos` | `identity_and_security/identity_and_security_ddos_protection.svg` | DDoS Protection |
| `encryption` | `identity_and_security/identity_and_security_encryption.svg` | Encryption |
| `firewall` | `identity_and_security/identity_and_security_firewall.svg` | Firewall |
| `iam` | `identity_and_security/identity_and_security_iam_identity_and_access_management.svg` | IAM |
| `identity` | `identity_and_security/identity_and_security_identity.svg` | Identity |
| `key_mgmt` | `identity_and_security/identity_and_security_key_management.svg` | Key Management |
| `key_vault` | `identity_and_security/identity_and_security_key_vault.svg` | Key Vault |
| `max_security_zone` | `identity_and_security/identity_and_security_maximum_security_zone.svg` | Max Security Zone |
| `nsg` | `identity_and_security/identity_and_security_nsg.svg` | NSG |
| `policies` | `identity_and_security/identity_and_security_policies.svg` | Policies |
| `security_lists` | `identity_and_security/identity_and_security_security_lists.svg` | Security Lists |
| `threat_defense` | `identity_and_security/identity_and_security_threat_defense.svg` | Threat Defense |
| `threat_intel` | `identity_and_security/identity_and_security_threat_intelligence.svg` | Threat Intelligence |
| `user` | `identity_and_security/identity_and_security_user.svg` | User |
| `user_group` | `identity_and_security/identity_and_security_user_group.svg` | User Group |
| `vault` | `identity_and_security/identity_and_security_vault.svg` | Vault |
| `vuln_scanning` | `identity_and_security/identity_and_security_vulnerability_scanning.svg` | Vulnerability Scanning |
| `waf` | `identity_and_security/identity_and_security_waf.svg` | WAF |

### Networking (18 icons)
| Suggested Key | SVG Path | Description |
|---------------|----------|-------------|
| `backbone` | `networking/networking_backbone.svg` | Backbone |
| `byoip` | `networking/networking_byoip.svg` | BYOIP |
| `cdn` | `networking/networking_cdn.svg` | CDN |
| `data_center` | `networking/networking_customer_data_center.svg` | Customer Data Center |
| `cpe` | `networking/networking_customer_premises_equipment_cpe.svg` | CPE |
| `dns` | `networking/networking_dns.svg` | DNS |
| `drg` | `networking/networking_dynamic_routing_gateway_drg.svg` | DRG |
| `flexible_lb` | `networking/networking_flexible_load_balancer.svg` | Flexible LB |
| `internet_gateway` | `networking/networking_internet_gateway.svg` | Internet Gateway |
| `ip_pools` | `networking/networking_ip_pools.svg` | IP Pools |
| `load_balancer` | `networking/networking_load_balancer.svg` | Load Balancer |
| `nat_gateway` | `networking/networking_nat_gateway.svg` | NAT Gateway |
| `network_switch` | `networking/networking_network_switch.svg` | Network Switch |
| `rpg` | `networking/networking_remote_peering_gateway.svg` | Remote Peering |
| `route_table` | `networking/networking_route_table.svg` | Route Table |
| `service_gateway` | `networking/networking_service_gateway.svg` | Service Gateway |
| `vcn` | `networking/networking_virtual_cloud_network_vcn.svg` | VCN |
| `vtap` | `networking/networking_vtap.svg` | VTAP |

### Observability & Management (12 icons)
| Suggested Key | SVG Path | Description |
|---------------|----------|-------------|
| `alarms` | `observability_and_management/observability_and_management_alarms.svg` | Alarms |
| `apm` | `observability_and_management/observability_and_management_application_performance_management.svg` | APM |
| `auditing` | `observability_and_management/observability_and_management_auditing.svg` | Auditing |
| `health_checks` | `observability_and_management/observability_and_management_health_checks.svg` | Health Checks |
| `logging` | `observability_and_management/observability_and_management_logging.svg` | Logging |
| `logging_analytics` | `observability_and_management/observability_and_management_logging_analytics.svg` | Logging Analytics |
| `monitoring` | `observability_and_management/observability_and_management_monitoring.svg` | Monitoring |
| `ops_insights` | `observability_and_management/observability_and_management_operations_insights.svg` | Operations Insights |
| `queuing` | `observability_and_management/observability_and_management_queuing.svg` | Queuing |
| `search` | `observability_and_management/observability_and_management_search.svg` | Search |
| `flow_logs` | `observability_and_management/observability_and_management_vcn_flow_logs.svg` | VCN Flow Logs |
| `workflow` | `observability_and_management/observability_and_management_workflow.svg` | Workflow |

### Storage (10 icons)
| Suggested Key | SVG Path | Description |
|---------------|----------|-------------|
| `backup` | `storage/storage_back_up_restore.svg` | Backup/Restore |
| `block_storage` | `storage/storage_block_storage.svg` | Block Storage |
| `block_cloning` | `storage/storage_block_storage_cloning.svg` | Block Cloning |
| `buckets` | `storage/storage_buckets.svg` | Buckets |
| `elastic_perf` | `storage/storage_elastic_performance.svg` | Elastic Performance |
| `file_storage` | `storage/storage_file_storage.svg` | File Storage |
| `local_storage` | `storage/storage_local_storage.svg` | Local Storage |
| `object_storage` | `storage/storage_object_storage.svg` | Object Storage |
| `persistent_vol` | `storage/storage_persistent_volume.svg` | Persistent Volume |
| `storage_sgw` | `storage/storage_service_gateway.svg` | Storage Service GW |

### General (13 icons)
Utility icons in `general/` - includes generic cloud, container, database, marketplace, and media icons. Most diagrams use category-specific icons instead.

### Migration (2 icons)
| Suggested Key | SVG Path | Description |
|---------------|----------|-------------|
| `dedicated_region` | `migration/migration_dedicated_region.svg` | Dedicated Region |
| `roving_edge` | `migration/migration_roving_edge_infrastructure.svg` | Roving Edge |

### Physical & Logical
Template/layout icons in `physical/` and `logical/` - grouping shapes (tenancy, AD, fault domain, VCN), connectors, and example layouts. Rarely used in programmatic generation.
