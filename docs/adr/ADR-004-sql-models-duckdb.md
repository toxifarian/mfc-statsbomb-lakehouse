# ADR-004 · Gold as version-controlled SQL models (DuckDB), dbt-ready

**Context.** Analysts must be able to read and review business logic (what is a "progressive pass"? PPDA?).

**Decision.** Each gold table is one `SELECT` in `src/pitchlake/gold/models/NN_<name>.sql`, executed in order by
DuckDB over Arrow views of silver, written as Delta. Shared logic lives in SQL macros (surrogate keys, coordinate
conversion, distance to goal).

**Alternatives.** dbt-fabric on a Warehouse (great lineage/docs; adds a second engine + T-SQL dialect + a
Warehouse copy of the data); Spark SQL (needs Spark); pandas (logic hidden in Python).

**Consequences.** Logic is diffable and testable; models can be ported to `dbt-duckdb`/`dbt-fabric` mechanically
(same SELECTs, `ref()` instead of `gold_<name>`) once the model count justifies dbt's tooling — that's the planned
next step, not a day-one requirement.
