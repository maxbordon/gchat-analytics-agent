variable "project_id" {
  description = "GCP project to deploy into."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Artifact Registry and Storage."
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Environment name used in resource names and labels (dev, test, prod)."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment must be dev, test or prod."
  }
}

variable "service_name" {
  description = "Base name for the Cloud Run service and related resources."
  type        = string
  default     = "gchat-analytics-agent"
}

variable "data_agent_id" {
  description = "ID of the Conversational Analytics data agent (see scripts/create_data_agent.py)."
  type        = string
  default     = "retail-analytics-agent"
}

variable "bigquery_dataset" {
  description = "Dataset that holds the synthetic retail tables."
  type        = string
  default     = "retail_demo"
}

variable "chat_issuer_email" {
  description = "Email in the OIDC token Chat sends. For Workspace add-on apps it's the project's gsuiteaddons service agent."
  type        = string
  default     = "chat@system.gserviceaccount.com"
}

variable "image" {
  description = "Container image. CI deploys new revisions; Terraform only sets the initial one."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "developers" {
  description = "Principals (e.g. user:you@example.com) granted read access to logs and the service."
  type        = list(string)
  default     = []
}
