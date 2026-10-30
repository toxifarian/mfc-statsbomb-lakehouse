# Assumptions, trade-offs & future enhancements

## Assumptions
* The club's platform is (or will be) Microsoft Fabric on OneLake with Entra ID, per the job description.
* The licensed StatsBomb feed matches the open-data JSON shape (same entities, versioned endpoints) — the adapter
  switches with `mode: api` + Key Vault credentials.
* Daily batch (plus a post-match trigger) is sufficient; StatsBomb is not a live in-match feed for this use.
* Other sources (Catapult, Transfermarkt…) already land in the platform; here they are **synthetic** stand-ins with
  realistic shapes and name mismatches, clearly flagged `is_synthetic`.
* Euro 2024 stands in for the club's competitions (open data doesn't include Middlesbrough's leagues).

## Trade-offs made deliberately
| Chose | Over | Because |
|---|---|---|
| Python + delta-rs + DuckDB | Spark | data size; cost; speed; testability (ADR-002) |
| Raw JSON bronze | statsbombpy DataFrames | lossless, replayable, failure-visible (ADR-001) |
| Per-match atomic replace | row MERGE | vendor deletes/re-indexes events (ADR-003) |
| SQL models in DuckDB | dbt on day one | fewer moving parts for a PoC; dbt-ready (ADR-004) |
| Full gold rebuild | incremental gold | seconds at this scale; simpler & always consistent |
| Fuzzy identity + review queue | name joins / fully manual mapping | accuracy with human control (ADR-006) |
| Own derived metrics | vendor aggregate endpoints | transparent definitions, consistent across sources |

## What I'd do next (prioritised)
1. **Licensed API cut-over** in dev: credentials in Key Vault, rate-limit tuning, `check-api` in nightly CI.
2. **Club competitions + backfill** (EFL Championship history) — config only.
3. **dbt** (`dbt-fabric`/`dbt-duckdb`) for lineage docs and model tests once models > ~30.
4. **Second Spectrum tracking** as a Spark job (25 fps volume), joined to events via match clock sync → physical
   context for every event; link 360 freeze-frames to tracking for validation.
5. **Golden player record**: DOB + vendor player-mapping endpoint as deterministic keys; squad master from the
   club's systems; SCD2 on player-club history.
6. **Features for data science**: possession chains (related events), xT/VAEP, pressing sequences, a feature
   table for ML in OneLake.
7. **Event-driven triggers**: post-match trigger (Data Activator / schedule after full-time) for next-morning reports.
8. **Observability**: push `meta` metrics to a Fabric Real-Time dashboard; SLA alerts on freshness.
9. **Self-service**: Fabric data agent over the semantic model so staff can ask "who pressed most in the final third?".
