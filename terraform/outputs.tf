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

output "evaluator_function_name" {
  description = "Name of the evaluator Cloud Function (deployed by Cloud Build)"
  value       = "${var.app_name}-evaluator"
}

output "function_source_bucket" {
  description = "GCS bucket for Cloud Function source code"
  value       = google_storage_bucket.function_source.name
}

# =============================================================================
# Deployment Instructions
# =============================================================================

output "deployment_instructions" {
  description = "Instructions for deploying the application"
  value       = <<-EOT
    
    Deployment Steps:
    
    1. Push to main branch - Cloud Build will automatically:
       - Build and push the container image
       - Deploy to Cloud Run
       - Package and deploy the evaluator Cloud Function
    
    2. Or deploy manually:
       
       # App (Cloud Run)
       docker build -t ${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.name}/app:latest .
       docker push ${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.name}/app:latest
       gcloud run deploy ${var.app_name}-app --image ${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.name}/app:latest --region ${var.region}
       
       # Evaluator (Cloud Function)
       zip -r function-source.zip eval/ src/ prompts/ data/ requirements.txt
       gsutil cp function-source.zip gs://${var.project_id}-function-source/
       gcloud functions deploy ${var.app_name}-evaluator --gen2 --region=${var.region} --runtime=python312 \
         --source=gs://${var.project_id}-function-source/function-source.zip \
         --entry-point=evaluate_pubsub --trigger-topic=${var.app_name}-eval-queue \
         --service-account=${var.app_name}-eval-sa@${var.project_id}.iam.gserviceaccount.com
    
    3. Access the app at: ${google_cloud_run_v2_service.app.uri}
    
  EOT
}