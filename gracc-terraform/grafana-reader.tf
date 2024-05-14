#resource "opensearch_user" "grafana-reader" {
#  username    = "grafana-reader"
#  password    = ""
#  description = "Read all indexes required for Grafana, job and data indexes"
#}

# And a full user, role and role mapping example:
resource "opensearch_role" "grafana-reader" {
  role_name   = "grafana-reader"
  description = "Grafana Reader Role"

  cluster_permissions = ["cluster_monitor", "cluster_composite_ops_ro"]

  index_permissions {
    index_patterns  = ["gracc.osg*", "xrd-stash*"]
    allowed_actions = ["get", "read"]
  }
}

resource "opensearch_roles_mapping" "grafana-reader" {
  role_name     = "grafana-reader"
  backend_roles = [opensearch_role.grafana-reader.role_name]
  users         = [opensearch_user.grafana-reader.username]
}
