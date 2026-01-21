# =============================================================================
# Plant Health Demo - Terraform Configuration
# =============================================================================

terraform {
  required_version = ">= 1.0"
  
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# =============================================================================
# Enable Required APIs
# =============================================================================

resource "google_project_service" "required_apis" {
  for_each = toset([
    "run.googleapis.com",
    "cloudfunctions.googleapis.com",
    "cloudbuild.googleapis.com",
    "pubsub.googleapis.com",
    "bigquery.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "dlp.googleapis.com",  # Cloud DLP for PII redaction
  ])
  
  project = var.project_id
  service = each.value
  
  disable_on_destroy = false
}

# =============================================================================
# Artifact Registry (Container Storage)
# =============================================================================

resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = var.app_name  # Match the name used in cloudbuild.yaml
  description   = "Container images for ${var.app_name}"
  format        = "DOCKER"
  
  depends_on = [google_project_service.required_apis]
}

# =============================================================================
# Local Values
# =============================================================================

locals {
  # Use a placeholder image for initial deployment
  # Cloud Build will update this to the real image on first push
  container_image = "gcr.io/cloudrun/hello"
  
  # This is the actual image path Cloud Build will use
  real_image_path = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.name}/app:latest"
}

# =============================================================================
# Secret Manager (API Keys) - Only when not using Vertex AI
# =============================================================================

resource "google_secret_manager_secret" "gemini_api_key" {
  count     = var.use_vertex_ai ? 0 : 1
  secret_id = "${var.app_name}-gemini-api-key"
  
  replication {
    auto {}
  }
  
  depends_on = [google_project_service.required_apis]
}

resource "google_secret_manager_secret_version" "gemini_api_key" {
  count       = var.use_vertex_ai ? 0 : 1
  secret      = google_secret_manager_secret.gemini_api_key[0].id
  secret_data = var.gemini_api_key
}

# =============================================================================
# Pub/Sub (Async Evaluation Queue)
# =============================================================================

resource "google_pubsub_topic" "eval_queue" {
  name = "${var.app_name}-eval-queue"
  
  depends_on = [google_project_service.required_apis]
}

resource "google_pubsub_subscription" "eval_queue" {
  name  = "${var.app_name}-eval-queue-sub"
  topic = google_pubsub_topic.eval_queue.name
  
  # Acknowledge deadline - how long the function has to process
  ack_deadline_seconds = 60
  
  # Retry policy
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
  
  # Dead letter policy - after 5 failures, send to dead letter topic
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.eval_dead_letter.id
    max_delivery_attempts = 5
  }
}

resource "google_pubsub_topic" "eval_dead_letter" {
  name = "${var.app_name}-eval-dead-letter"
  
  depends_on = [google_project_service.required_apis]
}

# =============================================================================
# BigQuery (Evaluation Results Storage)
# =============================================================================

resource "google_bigquery_dataset" "evals" {
  dataset_id  = replace("${var.app_name}_evals", "-", "_")
  description = "Evaluation results for ${var.app_name}"
  location    = var.region
  
  depends_on = [google_project_service.required_apis]
}

resource "google_bigquery_table" "evaluations" {
  dataset_id = google_bigquery_dataset.evals.dataset_id
  table_id   = "evaluations"
  
  schema = jsonencode([
    {
      name = "request_id"
      type = "STRING"
      mode = "REQUIRED"
    },
    {
      name = "timestamp"
      type = "TIMESTAMP"
      mode = "REQUIRED"
    },
    {
      name = "plant_type"
      type = "STRING"
      mode = "REQUIRED"
    },
    {
      name = "accuracy_score"
      type = "INTEGER"
      mode = "NULLABLE"
    },
    {
      name = "relevance_score"
      type = "INTEGER"
      mode = "NULLABLE"
    },
    {
      name = "urgency_score"
      type = "INTEGER"
      mode = "NULLABLE"
    },
    {
      name = "overall_score"
      type = "INTEGER"
      mode = "NULLABLE"
    },
    {
      name = "hallucination_detected"
      type = "BOOLEAN"
      mode = "NULLABLE"
    },
    {
      name = "safety_passed"
      type = "BOOLEAN"
      mode = "NULLABLE"
    },
    {
      name = "model"
      type = "STRING"
      mode = "NULLABLE"
    },
    {
      name = "assessment"
      type = "STRING"
      mode = "NULLABLE"
    },
    {
      name = "evaluation_json"
      type = "JSON"
      mode = "NULLABLE"
    },
  ])
}

# =============================================================================
# Cloud Run (Main Application)
# =============================================================================

resource "google_cloud_run_v2_service" "app" {
  name     = "${var.app_name}-app"
  location = var.region
  
  template {
    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }
    
    service_account = google_service_account.app.email
    
    containers {
      image = local.container_image
      
      ports {
        container_port = 8080  # Cloud Run default, matches Dockerfile
      }
      
      env {
        name  = "USE_VERTEX_AI"
        value = tostring(var.use_vertex_ai)
      }
      
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      
      env {
        name  = "GCP_LOCATION"
        value = var.region
      }
      
      env {
        name  = "MODEL_NAME"
        value = "gemini-2.5-flash"
      }
      
      env {
        name  = "EVAL_SAMPLE_RATE"
        value = tostring(var.eval_sample_rate)
      }
      
      env {
        name  = "USE_LOCAL_EVAL"
        value = "false"
      }
      
      env {
        name  = "PUBSUB_TOPIC"
        value = google_pubsub_topic.eval_queue.id
      }
      
      env {
        name  = "USE_CLOUD_DLP"
        value = "true"  # Use Cloud DLP instead of Presidio in production
      }
      
      env {
        name  = "USE_PII_REDACTION"
        value = "true"
      }
      
      # Only include API key env var when not using Vertex AI
      dynamic "env" {
        for_each = var.use_vertex_ai ? [] : [1]
        content {
          name = "GEMINI_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.gemini_api_key[0].secret_id
              version = "latest"
            }
          }
        }
      }
      
              resources {
                limits = {
                  cpu    = "1"
                  memory = "512Mi"  # Cloud DLP used instead of Presidio - minimal memory
                }
              }
    }
  }
  
  depends_on = [
    google_project_service.required_apis,
  ]
  
  # CRITICAL: Ignore image changes - Cloud Build manages the image
  # Without this, terraform would revert to placeholder on every apply
  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }
}

# Allow unauthenticated access (public demo)
resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}