output "workspace_id" {
  value = fabric_workspace.football.id
}

output "lakehouse_id" {
  value = fabric_lakehouse.football.id
}

output "key_vault_uri" {
  value = azurerm_key_vault.data.vault_uri
}
