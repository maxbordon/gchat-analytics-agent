locals {
  name = "${var.service_name}-${var.environment}"
  labels = {
    app         = var.service_name
    environment = var.environment
  }

  required_apis = toset([
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "chat.googleapis.com",
    "cloudaicompanion.googleapis.com",
    "geminidataanalytics.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
    "storage.googleapis.com",
  ])

  # Least privilege for the runtime identity.
  runtime_roles = toset([
    "roles/bigquery.dataViewer",
    "roles/bigquery.jobUser",
    "roles/cloudaicompanion.user",
    "roles/geminidataanalytics.dataAgentUser",
  ])

  developer_roles = toset([
    "roles/logging.viewer",
    "roles/run.viewer",
  ])
}

# --- APIs ----------------------------------------------------------------------
resource "google_project_service" "required" {
  for_each           = local.required_apis
  service            = each.value
  disable_on_destroy = false
}

# --- Runtime service account ---------------------------------------------------
resource "google_service_account" "runtime" {
  account_id   = substr("${var.service_name}-${var.environment}", 0, 30)
  display_name = "Runtime identity for ${local.name}"
}

resource "google_project_iam_member" "runtime" {
  for_each = local.runtime_roles
  project  = var.project_id
  role     = each.value
  member   = google_service_account.runtime.member
}

# Lets the service sign GCS URLs through the IAM API (no key files).
resource "google_service_account_iam_member" "runtime_sign_self" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = google_service_account.runtime.member
}

resource "google_project_iam_member" "developers" {
  for_each = {
    for pair in setproduct(var.developers, local.developer_roles) : "${pair[0]}|${pair[1]}" => pair
  }
  project = var.project_id
  member  = each.value[0]
  role    = each.value[1]
}

# --- BigQuery dataset (tables loaded by scripts/load_bigquery.sh) --------------------
resource "google_bigquery_dataset" "retail" {
  dataset_id    = var.bigquery_dataset
  location      = "US"
  description   = "Synthetic retail data for the analytics agent demo."
  labels        = local.labels
  depends_on    = [google_project_service.required]
}

# --- Container registry ---------------------------------------------------------
resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = var.service_name
  format        = "DOCKER"
  labels        = local.labels

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }

  depends_on = [google_project_service.required]
}

# --- Chart images: private bucket, auto-deleted, served via signed URLs ---------------
resource "google_storage_bucket" "charts" {
  name                        = "${var.project_id}-${local.name}-charts"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.environment != "prod"
  labels                      = local.labels

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age = 5
    }
  }
}

resource "google_storage_bucket_iam_member" "runtime_charts" {
  bucket = google_storage_bucket.charts.name
  role   = "roles/storage.objectUser"
  member = google_service_account.runtime.member
}

# --- Cloud Run ----------------------------------------------------------------
resource "google_cloud_run_v2_service" "bot" {
  name     = local.name
  location = var.region
  labels   = local.labels

  # Google Chat must reach the service; requests are authenticated in the app
  # by verifying Chat's OIDC token (see app/auth.py).
  invoker_iam_disabled = true
  deletion_protection  = var.environment == "prod"

  template {
    service_account = google_service_account.runtime.email
    timeout         = "120s"

    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    containers {
      image = var.image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        # Keep CPU allocated after the response so background answers finish.
        cpu_idle          = false
        startup_cpu_boost = true
      }

      env {
        name  = "AGENT_MODE"
        value = "gemini"
      }
      env {
        name  = "GOOGLE_CHAT_ISSUER_EMAIL"
        value = var.chat_issuer_email
      }
      env {
        name  = "DATA_AGENT_PROJECT"
        value = var.project_id
      }
      env {
        name  = "DATA_AGENT_ID"
        value = var.data_agent_id
      }
      env {
        name  = "CHARTS_BUCKET"
        value = google_storage_bucket.charts.name
      }
      # GOOGLE_CHAT_AUDIENCE must equal the service URL. It is only known after the
      # first apply, so set it with: gcloud run services update ... (see README).
    }
  }

  lifecycle {
    # CI owns the image and the audience env var after the first deploy.
    ignore_changes = [
      template[0].containers[0].image,
      template[0].containers[0].env,
      client,
      client_version,
    ]
  }

  depends_on = [google_project_service.required, google_project_iam_member.runtime]
}
