output "service_url" {
  description = "Use this as the Chat app endpoint and as GOOGLE_CHAT_AUDIENCE."
  value       = google_cloud_run_v2_service.bot.uri
}

output "runtime_service_account" {
  value = google_service_account.runtime.email
}

output "docker_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}

output "charts_bucket" {
  value = google_storage_bucket.charts.name
}
