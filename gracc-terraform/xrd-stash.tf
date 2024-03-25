#resource "opensearch_user" "xrd-stash-write" {
#  username    = "xrd-stash"
#  password    = ""
#  description = "Read and Write to xrd-stash"
#}


# And a full user, role and role mapping example:
resource "opensearch_role" "xrd-stash-write" {
  role_name   = "xrd-stash-write"
  description = "XRootD Stash Writer"


  index_permissions {
    index_patterns  = ["xrd-stash*"]
    allowed_actions = ["get", "read", "search", "write", "create", "index", "manage"]
  }
}

resource "opensearch_roles_mapping" "xrd-stash-write" {
  role_name     = "xrd-stash-write"
  backend_roles = [opensearch_role.xrd-stash-write.role_name]
  users         = [opensearch_user.xrd-stash-write.username]
}

#resource "opensearch_user" "xcache-ingest" {
#  username    = "xcache-ingest"
#  password    = ""
#  description = "Read and Write to XCache Indexes"
#}

# And a full user, role and role mapping example:
resource "opensearch_role" "xcache-ingest" {
  role_name   = "xcache-ingest"
  description = "XCache Ingester"

  cluster_permissions = ["cluster_monitor", "cluster_composite_ops_ro"]

  index_permissions {
    index_patterns  = ["xrd-stash*"]
    allowed_actions = ["get", "read", "write", "create", "index", "update", "indices:admin/create"]
  }
}

resource "opensearch_roles_mapping" "xcache-ingest" {
  role_name     = "xcache-ingest"
  backend_roles = [opensearch_role.xcache-ingest.role_name]
  users         = [opensearch_user.xcache-ingest.username]
}

# Install index template
resource "opensearch_index_template" "xrd-stash" {
  name = "xrd-stash"
  body = file("${path.module}/resources/xrd-stash-template.json")
}

# Set the ILM policy
resource "opensearch_ism_policy" "xrd-stash" {
  policy_id = "xrd-stash"
  body      = file("${path.module}/resources/xrd-stash-ilm.json")
}
