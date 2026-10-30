# ADR-005 · One lakehouse with schemas; medical data isolated

**Decision.** `lh_football` (schemas enabled): bronze as **Files** (raw JSON), `silver`, `gold`, `meta` as
**schemas** of Delta tables. Medical/athlete-management data (Kitman, ApolloV2) lives in a **separate restricted
workspace**; only non-sensitive derived flags (e.g. availability status) would be shared via a shortcut.

**Alternatives.** Lakehouse-per-layer (clear boundaries but more items and shortcuts to manage);
Warehouse for gold (T-SQL writes, but duplicate storage and a second engine).

**Consequences.** Simple to operate and to permission (workspace roles + OneLake security on schemas/tables).
Config switch `table_layout: prefix` supports lakehouses without schemas. Dev/Test/Prod are separate workspaces
promoted with deployment pipelines.
