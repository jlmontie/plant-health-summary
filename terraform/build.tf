# =============================================================================
# Cloud Build Trigger (GitOps) - 2nd Gen GitHub Connection
# =============================================================================

# Note: The GitHub connection must be created manually first via:
# https://console.cloud.google.com/cloud-build/repositories
# This creates: projects/PROJECT/locations/REGION/connections/CONNECTION_NAME/repositories/REPO

resource "google_cloudbuild_trigger" "app" {
  name     = "${var.app_name}-deploy"
  location = var.region
  
  # 2nd gen GitHub connection format
  repository_event_config {
    repository = "projects/${var.project_id}/locations/${var.region}/connections/${var.github_connection}/repositories/${var.github_repo}"
    push {
      branch = "^main$"
    }
  }
  
  # Use cloudbuild.yaml from the repository
  filename = "cloudbuild.yaml"
  
  # Pass substitution variables
  substitutions = {
    _REGION       = var.region
    _REPO_NAME    = google_artifact_registry_repository.app.name
    _SERVICE_NAME = google_cloud_run_v2_service.app.name
  }
  
  # Service account for Cloud Build
  service_account = google_service_account.cloudbuild.id
  
  # CRITICAL: Artifact Registry must exist before trigger can push images
  depends_on = [
    google_project_service.required_apis,
    google_artifact_registry_repository.app,
  ]
}

# Dedicated service account for Cloud Build
resource "google_service_account" "cloudbuild" {
  account_id   = "${var.app_name}-cloudbuild-sa"
  display_name = "Cloud Build Service Account"
}

# Grant Cloud Build permissions to deploy
resource "google_project_iam_member" "cloudbuild_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.cloudbuild.email}"
}

resource "google_project_iam_member" "cloudbuild_sa_user" {
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${google_service_account.cloudbuild.email}"
}

resource "google_artifact_registry_repository_iam_member" "cloudbuild_writer" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.app.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.cloudbuild.email}"
}

resource "google_project_iam_member" "cloudbuild_vertex_ai" {
  count   = var.use_vertex_ai ? 1 : 0
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.cloudbuild.email}"
}

# Allow Cloud Build to write logs
resource "google_project_iam_member" "cloudbuild_logs_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.cloudbuild.email}"
}

# Allow Cloud Build to manage IAM (needed to grant invoker permissions during function deploy)
resource "google_project_iam_member" "cloudbuild_iam_admin" {
  project = var.project_id
  role    = "roles/resourcemanager.projectIamAdmin"
  member  = "serviceAccount:${google_service_account.cloudbuild.email}"
}

# Allow Cloud Build to deploy Cloud Functions
resource "google_project_iam_member" "cloudbuild_functions_admin" {
  project = var.project_id
  role    = "roles/cloudfunctions.admin"
  member  = "serviceAccount:${google_service_account.cloudbuild.email}"
}

# Allow Cloud Build to upload to the function source bucket
resource "google_storage_bucket_iam_member" "cloudbuild_function_source" {
  bucket = google_storage_bucket.function_source.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cloudbuild.email}"
}