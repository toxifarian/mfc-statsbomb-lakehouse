# Architecture Decision Records

Short records of the decisions that shaped the solution: context, decision, alternatives, consequences.

| ADR | Decision |
|---|---|
| [001](ADR-001-raw-json-bronze.md) | Land raw JSON in bronze; don't ingest via statsbombpy DataFrames |
| [002](ADR-002-python-not-spark.md) | Python notebooks (delta-rs + DuckDB) rather than Spark for this source |
| [003](ADR-003-incremental-watermarks.md) | Incremental by per-match `last_updated` watermarks; atomic per-match replace |
| [004](ADR-004-sql-models-duckdb.md) | Gold as version-controlled SQL models run by DuckDB (dbt-ready) |
| [005](ADR-005-single-lakehouse-schemas.md) | One lakehouse with schemas (bronze files, silver/gold/meta tables); medical isolated |
| [006](ADR-006-identity-resolution.md) | Governed player identity cross-reference with human review |
| [007](ADR-007-direct-lake.md) | Serve through a Direct Lake semantic model + SQL endpoint |
| [008](ADR-008-contracts-and-dq.md) | Explicit silver contract, drift detection, declarative DQ gate |
| [009](ADR-009-surrogate-keys.md) | Deterministic hash surrogate keys |
