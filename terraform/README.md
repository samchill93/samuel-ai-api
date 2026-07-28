# Terraform — the stack as infrastructure-as-code (Module 8)

**Status: authored and validated, not yet applied.** This codifies the Living Portfolio
infrastructure — the Render backend, the Neon Postgres database, and the Vercel site — as
Terraform. `terraform init` + `terraform validate` **pass** against the real provider schemas
(render-oss/render 1.9.1, kislerdm/neon 0.14.0, vercel/vercel 2.15.1) — and validating caught and
fixed a real attribute-placement bug (Render's `start_command` is a top-level attribute, not
nested under `native_runtime`). It has **not** yet been `plan`ned or `apply`d — that needs real
provider credentials — and adopting the existing infra still needs `terraform import`. So the
roadmap does **not** mark Terraform shipped until an import + plan round-trips clean.

## The one thing to get right first

The Render service, Neon project, and Vercel project **already exist** — they were created by
hand as each module shipped. A fresh `terraform apply` would try to **create duplicates**. To
bring the *real* resources under Terraform, import them, then confirm the plan is empty:

```bash
# secrets come from the environment, never a committed .tfvars
export TF_VAR_render_api_key=...     TF_VAR_render_owner_id=...
export TF_VAR_neon_api_key=...       TF_VAR_vercel_api_token=...
export TF_VAR_anthropic_api_key=...  TF_VAR_openai_api_key=...
export TF_VAR_database_url=...

terraform init
terraform validate                       # confirm the provider attribute names first

# adopt existing infra (ids come from each provider's dashboard/API):
terraform import render_web_service.api   <render-service-id>
terraform import neon_project.portfolio   <neon-project-id>
terraform import vercel_project.site       <vercel-project-id>

terraform plan                           # goal: "No changes" once the config matches reality
```

Only once `plan` round-trips clean is it safe to let Terraform manage the stack. Until then,
adjust the resource attributes in `main.tf` to match what `import` pulls in.

## Files

- `main.tf` — providers (render-oss/render, kislerdm/neon, vercel/vercel) and the three resources.
- `variables.tf` — every credential and secret as a `sensitive`, defaultless variable (supplied
  via `TF_VAR_*`).

## Honest caveats

- **Validated (config), not applied.** `terraform validate` passes against the installed provider
  schemas, so the attribute names are confirmed correct. What's still unverified is only what needs
  real credentials and the live APIs: `plan`, `import`, and `apply`.
- **Schema is app-owned.** Terraform provisions the Neon database; the pgvector extension and the
  `documents` / `chunks` / `inquiries` tables are applied by `apply_schema.py`, not Terraform.
- **Secrets never in code.** No `.tfvars` is committed; the state file (which contains resolved
  secrets) must be stored in an encrypted backend, not in git.
