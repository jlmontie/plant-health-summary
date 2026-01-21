# =============================================================================
# Cloud Build Trigger (GitOps)
# =============================================================================

# Connect to GitHub repository
# Note: First-time setup requires manual OAuth in Cloud Console
resource "google_cloudbuild_trigger" "app" {
  name     = "${var.app_name}-deploy"
  location = var.region
  
  # Trigger on push to main branch
  github {
    owner = var.github_owner
    name  = var.github_repo
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