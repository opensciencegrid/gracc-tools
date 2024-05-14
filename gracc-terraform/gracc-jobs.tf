resource "opensearch_user" "gracc-writer" {
  username    = "gracc-writer"
  password    = ""
  description = "Read and Write to GRACC indexes"
  lifecycle {
    ignore_changes = [password]
  }
}

# And a full user, role and role mapping example:
resource "opensearch_role" "gracc-writer" {
  role_name   = "gracc-writer"
  description = "GRACC Jobs Writer"


  index_permissions {
    index_patterns  = ["gracc.osg*"]
    allowed_actions = ["get", "read", "search", "write", "create", "index", "manage"]
  }
}

resource "opensearch_roles_mapping" "gracc-writer" {
  role_name     = "gracc-writer"
  backend_roles = [opensearch_role.gracc-writer.role_name]
  users         = ["gracc-writer"]
}

resource "opensearch_user" "gracc-ingest" {
  username    = "gracc-ingest"
  password    = ""
  description = "Read and Write to GRACC indexes"
  lifecycle {
    ignore_changes = [password]
  }
}

# And a full user, role and role mapping example:
resource "opensearch_role" "gracc-ingest" {
  role_name   = "gracc-ingest"
  description = "GRACC Ingester"

  cluster_permissions = ["cluster_monitor", "cluster_composite_ops_ro"]

  index_permissions {
    index_patterns  = ["gracc.osg*"]
    allowed_actions = ["get", "read", "write", "create", "index", "update", "indices:admin/create"]
  }
}

resource "opensearch_roles_mapping" "gracc-ingest" {
  role_name     = "gracc-ingest"
  backend_roles = [opensearch_role.gracc-ingest.role_name]
  users         = ["gracc-ingest"]
}


# Install index template
resource "opensearch_index_template" "gracc-jobs-raw" {
  name = "gracc-jobs-raw"
  body = file("${path.module}/resources/gracc-raw-jobs-template.json")
}

# Install index template
resource "opensearch_index_template" "gracc-jobs-summary" {
  name = "gracc-jobs-summary"
  body = file("${path.module}/resources/gracc-summary-jobs-template.json")
}
