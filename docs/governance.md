# Data quality, security & governance (incl. UK GDPR)

## Classification

| Data | Classification | Where it lives | Who can see it |
|---|---|---|---|
| StatsBomb events / lineups / 360 | **Personal data** (identifies players + performance), licensed third-party data | `lh_football` (silver/gold) | football analysis, coaching, recruitment, data team |
| Catapult GPS, VALD testing | Personal data (physical performance) | `lh_football` | performance staff, data team; coaches via aggregates |
| Kitman Labs / ApolloV2 medical | **Special category** (Art. 9 – health) | **separate restricted workspace** | named medical staff + DPO-approved roles only |
| Transfermarkt | Public-domain-ish, licensed/scraped terms apply | `lh_football` | all football staff |
| Meta tables (runs, DQ) | Operational | `lh_football.meta` | data team |

## Lawful basis & principles (to agree with the DPO)
* **Lawful basis**: legitimate interests (performance analysis) / contract (employment) for club players; licensed
  third-party data for opposition players under the provider's terms. Medical data: Art. 9(2)(b)/(h) via the
  club's medical function — never processed in the general platform.
* **Minimisation**: only fields needed downstream reach gold; medical data never joins wide-access tables —
  at most a derived, non-diagnostic availability flag.
* **Retention**: bronze history kept N months then pruned (`VACUUM` + file lifecycle); licence-driven retention for
  vendor data; erasure requests handled by player key across layers (bronze re-landing is reproducible).
* **Transparency/DPIA**: platform DPIA covering integration of tracking + medical + performance data.

## Access control (least privilege)
* Entra ID **groups**, never individuals: `Data Engineers` (Contributor), `Analysts` (Viewer + Build on model),
  `Coaches` (report app audience).
* **OneLake security / SQL endpoint permissions** at schema/table level: analysts see `gold` (+ `silver` read for
  data scientists), not `meta` or bronze files.
* **Row-level security** in the semantic model where needed (e.g. academy staff see academy squads only).
* **Secrets** (StatsBomb API credentials) in **Azure Key Vault**, read at runtime with
  `notebookutils.credentials.getSecret`; never in code, notebooks, Git or Terraform state.
* CI/CD uses **OIDC federated credentials** (no long-lived secrets in GitHub).

## Governance tooling
* **Microsoft Purview**: sensitivity labels (e.g. *Confidential – Player Personal Data*) inherited from lakehouse
  to model to reports/exports; lineage from Fabric items; data catalogue entries pointing at the
  [data dictionary](data_dictionary.md).
* **Endorsement**: the semantic model is *Certified* once DQ has been stable for a cycle — the signal to staff that
  it's the source of truth.
* **Audit**: `meta.pipeline_runs`, `meta.bronze_manifest` (what/when/hash), Fabric audit logs.

## Data quality operating model
* Rules live in YAML next to the code, reviewed via PR; analysts can propose rules.
* `error` → pipeline stops before gold (yesterday's trusted data stays live) + alert.
* `warn` → recorded, visible in monitoring; recurring vendor issues raised with StatsBomb (e.g. extra-time
  lineup ordering) with failing samples from `meta.dq_results.sample_json` as evidence.
* Identity review queue owned by the analysts (they know the players); approvals are PRs to
  `xref_player_overrides.csv` with an approver name.
