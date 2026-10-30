variable "environment" {
  description = "dev | test | prod"
  type        = string
  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment must be dev, test or prod"
  }
}

variable "capacity_name" {
  description = "Fabric capacity display name (F-SKU, or trial capacity for the PoC)"
  type        = string
}

variable "subscription_id" {
  description = "Azure subscription for Key Vault"
  type        = string
}

variable "location" {
  type    = string
  default = "uksouth"
}

variable "data_engineers_group_id" {
  description = "Entra ID group object id – Contributor on the workspace"
  type        = string
}

variable "analysts_group_id" {
  description = "Entra ID group object id – Viewer on the workspace (reads via SQL endpoint / Power BI)"
  type        = string
}
