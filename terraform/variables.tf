# =============================================================================
# Project Configuration
# =============================================================================

variable "project_id" {
  description = "GCP project ID"
  type        = string
  default     = "plant-health-summary"
}

variable "region" {
  description = "GCP region for resources"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Environment name (e.g., dev, staging, prod)"
  type        = string
  default     = "dev"
}

# =============================================================================
# Application Settings
# =============================================================================

variable "app_name" {
  description = "Application name used for resource naming"
  type        = string
  default     = "plant-health"
}

variable "use_vertex_ai" {
  description = "Use Vertex AI instead of API key authentication"
  type        = bool
  default     = true
}

variable "gemini_api_key" {
  description = "Gemini API key (stored in Secret Manager)"
  type        = string
  sensitive   = true
  default     = ""
}

# =============================================================================
# Scaling Configuration
# =============================================================================

variable "min_instances" {
  description = "Minimum number of Cloud Run instances (1+ recommended for Chainlit sessions)"
  type        = number
  default     = 1
}

variable "max_instances" {
  description = "Maximum number of Cloud Run instances"
  type        = number
  default     = 2
}

# =============================================================================
# Evaluation Settings
# =============================================================================

variable "eval_sample_rate" {
  description = "Fraction of requests to sample for evaluation (0.0 to 1.0)"
  type        = number
  default     = 0.05
}

# =============================================================================
# GitHub Settings (for Cloud Build 2nd Gen Connection)
# =============================================================================

variable "github_connection" {
  description = "Name of the Cloud Build GitHub connection (created manually in Console)"
  type        = string
  default     = "github-connection"
}

variable "github_repo" {
  description = "GitHub repository name (as it appears in the connection)"
  type        = string
}