resource "opensearch_role" "anonymous_backendrole" {
  role_name   = "anonymous_backendrole"
  description = "Anonymous use"

  cluster_permissions = ["cluster_monitor", "cluster_composite_ops_ro"]

  index_permissions {
    index_patterns  = ["gracc.osg.summary*", "xrd-stash*", ".kibana", "gracc.corrections*", "gracc.osg.raw*"]
    allowed_actions = ["get", "read", "indices:admin/mappings/get", "indices:data/read/scroll/clear"]
  }

  tenant_permissions {
    tenant_patterns = ["global_tenant"]
    allowed_actions = ["kibana_all_read"]
  }
}

resource "opensearch_roles_mapping" "anonymous_backendrole" {
  role_name     = "anonymous_backendrole"
  backend_roles = ["opendistro_security_anonymous_backendrole"]
}

resource "opensearch_roles_mapping" "anonymous_user" {
  role_name = "anonymous_backendrole"
  users     = ["*"]
}
