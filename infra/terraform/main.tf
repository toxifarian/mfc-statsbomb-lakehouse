# -----------------------------------------------------------------------------
# Fabric workspace-as-code for the football data platform.
# One workspace per environment (dev / test / prod) from the same module;
# promotion of item *content* is done by Fabric deployment pipelines or
# scripts/deploy_fabric.py from CI, infrastructure by `terraform apply`.
#
# Auth: `az login` locally, or ARM_* / FABRIC_* service-principal env vars in CI.
# -----------------------------------------------------------------------------
terraform {
  required_version = ">= 1.8"
  required_providers {
    fabric = {
      source  = "microsoft/fabric"
      version = "~> 1.0"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "fabric" {}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

data "fabric_capacity" "this" {
  display_name = var.capacity_name
}

resource "fabric_workspace" "football" {
  display_name = "ws-football-data-${var.environment}"
  description  = "Football data platform (${var.environment}) – StatsBomb, Catapult, VALD, Kitman…"
  capacity_id  = data.fabric_capacity.this.id
}

# Single lakehouse with schemas: bronze lives in Files/, silver/gold/meta are schemas under Tables/
resource "fabric_lakehouse" "football" {
  display_name = "lh_football"
  workspace_id = fabric_workspace.football.id
  configuration = {
    enable_schemas = true
  }
}

# Medical / athlete-management data is special-category (GDPR Art. 9): isolated workspace,
# separate lakehouse, separate access list – never co-located with wide-access football data.
resource "fabric_workspace" "medical" {
  display_name = "ws-medical-restricted-${var.environment}"
  description  = "Restricted: Kitman Labs / ApolloV2 medical data. Access by named medical staff only."
  capacity_id  = data.fabric_capacity.this.id
}

locals {
  notebooks = {
    nb_00_explore_statsbomb = "nb_00_explore_statsbomb.ipynb"
    nb_01_run_pipeline      = "nb_01_run_pipeline.ipynb"
    nb_02_semantic_model    = "nb_02_semantic_model.ipynb"
    nb_03_monitoring        = "nb_03_monitoring.ipynb"
  }
}

resource "fabric_notebook" "this" {
  for_each                  = local.notebooks
  display_name              = each.key
  workspace_id              = fabric_workspace.football.id
  format                    = "ipynb"
  definition_update_enabled = true
  definition = {
    "notebook-content.ipynb" = {
      source = "${path.module}/../../fabric/notebooks/${each.value}"
    }
  }
}

# ---- access: least privilege, Entra groups not individuals --------------------
resource "fabric_workspace_role_assignment" "engineers" {
  workspace_id = fabric_workspace.football.id
  principal = {
    id   = var.data_engineers_group_id
    type = "Group"
  }
  role = "Contributor"
}

resource "fabric_workspace_role_assignment" "analysts" {
  workspace_id = fabric_workspace.football.id
  principal = {
    id   = var.analysts_group_id
    type = "Group"
  }
  role = "Viewer"
}

# ---- secrets: StatsBomb API credentials live in Key Vault, read via notebookutils
data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "data" {
  name     = "rg-football-data-${var.environment}"
  location = var.location
}

resource "azurerm_key_vault" "data" {
  name                       = "kv-mfc-data-${var.environment}"
  location                   = azurerm_resource_group.data.location
  resource_group_name        = azurerm_resource_group.data.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  enable_rbac_authorization  = true
  purge_protection_enabled   = true
  soft_delete_retention_days = 30
}

# Secret *values* are set out-of-band (portal / pipeline secret), never in state or Git
resource "azurerm_key_vault_secret" "statsbomb_user" {
  name         = "statsbomb-api-username"
  value        = "set-me-out-of-band"
  key_vault_id = azurerm_key_vault.data.id
  lifecycle { ignore_changes = [value] }
}

resource "azurerm_key_vault_secret" "statsbomb_password" {
  name         = "statsbomb-api-password"
  value        = "set-me-out-of-band"
  key_vault_id = azurerm_key_vault.data.id
  lifecycle { ignore_changes = [value] }
}
