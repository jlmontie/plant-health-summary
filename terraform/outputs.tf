# =============================================================================
# Outputs
# =============================================================================

output "app_url" {
  description = "URL of the deployed Cloud Run application"
  value       = google_cloud_run_v2_service.app.uri
}

output "artifact_registry_url" {
  description = "URL for pushing container images"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.name}"
}

output "pubsub_topic" {
  description = "Pub/Sub topic for evaluation requests"
  value       = google_pubsub_topic.eval_queue.id
}

output "bigquery_table" {
  description = "BigQuery table for evaluation results"
  value       = "${var.project_id}.${google_bigquery_dataset.evals.dataset_id}.${google_bigquery_table.evaluations.table_id}"
}

output "app_service_account" {
  description = "Service account email for the Cloud Run app"
  value       = google_service_account.app.email
}

output "evaluator_service_account" {
  description = "Service account email for the evaluator function"
  value       = google_service_account.evaluator.email
}

# =============================================================================
# Deployment Instructions
# =============================================================================

output "deployment_instructions" {
  description = "Instructions for deploying the application"
  value       = <<-EOT
    
    Deployment Steps:
    
    1. Build and push the container:
       docker build -t ${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.name}/app:latest .
       docker push ${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.name}/app:latest
    
    2. The Cloud Run service will automatically use the new image.
    
    3. Access the app at: ${google_cloud_run_v2_service.app.uri}
    
  EOT
}