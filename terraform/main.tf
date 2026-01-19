# infra/main.tf

resource "google_cloud_run_v2_service" "plant_health" {
  name     = "plant-health-api"
  location = var.region

  template {
    containers {
      image = var.image_url
    }
  }
}

resource "google_pubsub_topic" "eval_queue" {
  name = "eval-queue"
}

resource "google_cloudfunctions2_function" "async_eval" {
  name     = "async-evaluator"
  location = var.region
  # ...
}