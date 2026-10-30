# Infrastructure as code (Terraform)

Declares the Fabric workspace(s), the schema-enabled lakehouse, the notebooks, workspace role
assignments (Entra groups) and the Key Vault holding StatsBomb API credentials, for one environment.

```bash
cd infra/terraform
terraform init
terraform plan  -var-file=dev.tfvars
terraform apply -var-file=dev.tfvars
```

Notes
* Uses the official `microsoft/fabric` provider; auth via `az login` or service principal env vars.
* Not applied for the interview PoC (a Fabric trial capacity was used and items were imported via the
  runbook) – it shows how the platform would be managed once there are dev/test/prod workspaces.
* A separate restricted workspace for medical data enforces GDPR special-category separation.
* Secret values are never in Git or state (`ignore_changes` + set out of band).
