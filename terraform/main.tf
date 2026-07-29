# Infrastructure-as-code for the Living Portfolio stack (Module 8) — MANAGING THE LIVE STACK.
#
# STATUS: this codifies the running stack (Render web service, Neon Postgres, Vercel site) as
# Terraform across the three real providers. All three resources have been `terraform import`ed
# into state, and `terraform plan` round-trips clean ("No changes.") against the live
# infrastructure — so Terraform now manages the real stack.
#
# No `terraform apply` was run against production: the resources predate Terraform (they were
# created by hand as the modules shipped), so they were ADOPTED via import rather than created,
# and a clean plan means there is nothing to apply. See terraform/README.md to reproduce the
# import + plan; provider versions are pinned in .terraform.lock.hcl.
#
# Two attributes are intentionally under `ignore_changes` (documented inline at each resource):
# Render's `environment_id` (assigned by Render's environments feature, not hydrated on import)
# and Vercel's `vercel_authentication` (the provider reads the API's value "all_except_custom_
# domains" but only accepts its own enum "standard_protection" — same setting, two vocabularies).
#
# Secrets are never in this file: they come from TF_VAR_* environment variables (see variables.tf).
# terraform.tfstate is git-ignored because it holds resolved secret values.

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
  name                      = "samuel-ai-api"
  region_id                 = "aws-us-east-1"
  pg_version                = 18
  history_retention_seconds = 21600 # match the live project (6h); the provider default is 24h
}

# The pgvector extension and the schema (documents / chunks / inquiries) are applied by
# apply_schema.py, not Terraform — Terraform provisions the database, the app owns its schema.

# --- Render: the FastAPI backend ---------------------------------------------------------
resource "render_web_service" "api" {
  name          = "samuel-ai-api"
  plan          = "starter"
  region        = "oregon"
  start_command = "uvicorn main:app --host 0.0.0.0 --port $PORT" # top-level per the render provider schema

  runtime_source = {
    native_runtime = {
      runtime       = "python"
      repo_url      = "https://github.com/samchill93/samuel-ai-api"
      branch        = "main"
      auto_deploy   = true
      build_command = "pip install -r requirements.txt"
    }
  }

  # Secrets are injected here from variables, never committed. DATABASE_URL points at the Neon
  # project above. These four keys mirror the live service exactly (CORS_ORIGINS is deliberately
  # unset in production, which locks CORS to the built-in allowlist).
  env_vars = {
    ANTHROPIC_API_KEY = { value = var.anthropic_api_key }
    OPENAI_API_KEY    = { value = var.openai_api_key }
    DATABASE_URL      = { value = var.database_url }
    PYTHON_VERSION    = { value = "3.13.4" }
  }

  # environment_id is assigned by Render's "environments" feature and isn't hydrated on import;
  # leave it as the platform set it so an adopted service round-trips clean (the other
  # computed attributes only showed "known after apply" as a reaction to this one real diff).
  lifecycle {
    ignore_changes = [environment_id]
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

  # Mirror the live project's protection settings so an import + plan round-trips clean.
  # The provider's "standard_protection" is Vercel's "all deployments except production
  # custom domains" (API deploymentType: all_except_custom_domains).
  vercel_authentication = {
    deployment_type = "standard_protection"
  }
  oidc_token_config = {
    enabled     = true
    issuer_mode = "team"
  }

  enable_affected_projects_deployments = true

  # The provider reads Vercel's API value ("all_except_custom_domains") into state but only
  # accepts its own enum ("standard_protection") in config — the same setting, two vocabularies.
  # Ignore drift on it so the adopted project round-trips clean instead of showing a perpetual diff.
  lifecycle {
    ignore_changes = [vercel_authentication]
  }
}
