# =============================================================================
# Service Accounts
# =============================================================================

# Service account for the Cloud Run application
resource "google_service_account" "app" {
  account_id   = "${var.app_name}-app-sa"
  display_name = "Plant Health App Service Account"
  description  = "Service account for the Cloud Run application"
}

# Service account for the Cloud Function evaluator
resource "google_service_account" "evaluator" {
  account_id   = "${var.app_name}-eval-sa"
  display_name = "Plant Health Evaluator Service Account"
  description  = "Service account for the async evaluation Cloud Function"
}

# =============================================================================
# Vertex AI Permissions (when using Vertex AI)
# =============================================================================

resource "google_project_iam_member" "app_vertex_ai" {
  count   = var.use_vertex_ai ? 1 : 0
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.app.email}"
}

resource "google_project_iam_member" "evaluator_vertex_ai" {
  count   = var.use_vertex_ai ? 1 : 0
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.evaluator.email}"
}

# =============================================================================
# App Service Account Permissions
# =============================================================================

# Publish to Pub/Sub
resource "google_pubsub_topic_iam_member" "app_publish" {
  topic  = google_pubsub_topic.eval_queue.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.app.email}"
}

# Read secrets (only when not using Vertex AI)
resource "google_secret_manager_secret_iam_member" "app_read_api_key" {
  count     = var.use_vertex_ai ? 0 : 1
  secret_id = google_secret_manager_secret.gemini_api_key[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

# =============================================================================
# Evaluator Service Account Permissions
# =============================================================================

# Read from Pub/Sub subscription
resource "google_pubsub_subscription_iam_member" "evaluator_subscribe" {
  subscription = google_pubsub_subscription.eval_queue.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.evaluator.email}"
}

# Write to BigQuery
resource "google_bigquery_dataset_iam_member" "evaluator_write" {
  dataset_id = google_bigquery_dataset.evals.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.evaluator.email}"
}

# Read secrets (for Gemini API key, only when not using Vertex AI)
resource "google_secret_manager_secret_iam_member" "evaluator_read_api_key" {
  count     = var.use_vertex_ai ? 0 : 1
  secret_id = google_secret_manager_secret.gemini_api_key[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.evaluator.email}"
}

# Acknowledge messages in dead letter topic
resource "google_pubsub_topic_iam_member" "evaluator_dead_letter" {
  topic  = google_pubsub_topic.eval_dead_letter.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.evaluator.email}"
}