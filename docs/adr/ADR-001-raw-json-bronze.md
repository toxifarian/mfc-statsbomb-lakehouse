# ADR-001 · Land raw JSON in bronze

**Context.** The brief points to `statsbombpy`, which returns flattened pandas DataFrames. Flattening is lossy
and opinionated (column naming, list handling), couples storage to a library version, and the library swallows
HTTP errors (returns `[]`).

**Decision.** Fetch with our own resilient client and store the **exact bytes** returned, immutably, one file per
landing: `Files/bronze/statsbomb/<entity>/competition_id=…/season_id=…/<key>/<ts>_<sha8>.json`, recorded in
`meta.bronze_manifest` (size, sha256, record count, source `last_updated`, HTTP attempts, status).

**Alternatives.** statsbombpy → Delta directly (fast to build, lossy, hides failures); store JSON in a Delta
string column (queryable but awkward for large files).

**Consequences.** + Re-process silver any time without calling the API (contract change, bug fix, backfill).
+ Full audit/version history of vendor revisions. + Byte-identical payloads are skipped by hash.
− Storage cost (~0.5 GB per tournament with 360 — negligible on OneLake); retention policy needed (e.g. keep
latest + 12 months of history).
