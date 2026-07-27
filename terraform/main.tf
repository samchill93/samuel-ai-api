# Infrastructure-as-code for the Living Portfolio stack (Module 8) — AUTHORED, NOT YET APPLIED.
#
# HONEST STATUS: this codifies the stack (Render web service, Neon Postgres, Vercel site) as
# Terraform, but it has NOT been `terraform validate`d, `plan`ned, or `apply`d in the authoring
# environment (Terraform isn't installed here, and applying needs real provider credentials). It
# is a reviewed starting point written from the providers' docs — confirm every attribute with
# `terraform validate` before relying on it.
#
# CRITICAL: the Render service, Neon project, and Vercel project ALREADY EXIST (they were created
# by hand as the modules shipped). A fresh `terraform apply` would try to CREATE DUPLICATES. To
# adopt the real infrastructure, `terraform import` each resource first (see terraform/README.md),
# then `plan` should show no changes. Do not apply against the live stack until an import + plan
# round-trips clean.
#
# Secrets are never in this file: they come from TF_VAR_* environment variables (see variables.tf).

terraform {
  required_version = ">= 1.6"
  required_providers {
    # Render's official provider. Docs: registry.terraform.io/providers/render-oss/render
    render = {
      source  = "render-oss/render"
      version = "~> 1.3"
    }
    # Neon community provider. Docs: registry.terraform.io/providers/kislerdm/neon
    neon = {
      source  = "kislerdm/neon"
      version = "~> 0.6"
    }
    # Vercel's official provider. Docs: registry.terraform.io/providers/vercel/vercel
    vercel = {
      source  = "vercel/vercel"
      version = "~> 2.0"
    }
  }
}

provider "render" {
  api_key  = var.render_api_key
  owner_id = var.render_owner_id
}

provider "neon" {
  api_key = var.neon_api_key
}

provider "vercel" {
  api_token = var.vercel_api_token
}

# --- Neon: the Postgres database behind the RAG vector store ------------------------------
resource "neon_project" "portfolio" {
  name       = "samuel-portfolio"
  region_id  = "aws-us-east-1"
  pg_version = 16
}

# The pgvector extension and the schema (documents / chunks / inquiries) are applied by
# apply_schema.py, not Terraform — Terraform provisions the database, the app owns its schema.

# --- Render: the FastAPI backend ---------------------------------------------------------
resource "render_web_service" "api" {
  name   = "samuel-ai-api"
  plan   = "free"
  region = "oregon"

  runtime_source = {
    native_runtime = {
      runtime       = "python"
      repo_url      = "https://github.com/samchill93/samuel-ai-api"
      branch        = "main"
      auto_deploy   = true
      build_command = "pip install -r requirements.txt"
      start_command = "uvicorn main:app --host 0.0.0.0 --port $PORT"
    }
  }

  # Secrets are injected here from variables, never committed. DATABASE_URL points at the Neon
  # project above (its exact connection-string attribute name is provider-specific — confirm it).
  env_vars = {
    ANTHROPIC_API_KEY = { value = var.anthropic_api_key }
    OPENAI_API_KEY    = { value = var.openai_api_key }
    DATABASE_URL      = { value = var.database_url }
    CORS_ORIGINS      = { value = var.cors_origins }
  }
}

# --- Vercel: the static portfolio site ---------------------------------------------------
resource "vercel_project" "site" {
  name      = "living-portfolio"
  framework = null # framework-free static HTML

  git_repository = {
    type              = "github"
    repo              = "samchill93/living-portfolio"
    production_branch = "main"
  }
}
