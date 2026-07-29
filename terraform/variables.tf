# Variables for the stack. Every secret is `sensitive` and has NO default — provide them via
# environment variables (never a committed .tfvars):
#
#   export TF_VAR_render_api_key=...      TF_VAR_render_owner_id=...
#   export TF_VAR_neon_api_key=...        TF_VAR_vercel_api_token=...
#   export TF_VAR_anthropic_api_key=...   TF_VAR_openai_api_key=...
#   export TF_VAR_database_url=...
#
# The same discipline as the rest of the project: secrets live only in the environment, never in code.

# --- Provider credentials ---
variable "render_api_key" {
  type      = string
  sensitive = true
}

variable "render_owner_id" {
  type        = string
  description = "Render owner/team id the service belongs to."
}

variable "neon_api_key" {
  type      = string
  sensitive = true
}

variable "vercel_api_token" {
  type      = string
  sensitive = true
}

# --- Application secrets injected into the Render service ---
variable "anthropic_api_key" {
  type      = string
  sensitive = true
}

variable "openai_api_key" {
  type      = string
  sensitive = true
}

variable "database_url" {
  type        = string
  sensitive   = true
  description = "Neon Postgres connection string used by the app (kept in sync with the Neon project)."
}
