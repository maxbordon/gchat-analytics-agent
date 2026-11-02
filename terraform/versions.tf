terraform {
  required_version = ">= 1.9.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }

  # Remote state: create the bucket once, then uncomment.
  # backend "gcs" {
  #   bucket = "<your-tf-state-bucket>"
  #   prefix = "gchat-analytics-agent"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
