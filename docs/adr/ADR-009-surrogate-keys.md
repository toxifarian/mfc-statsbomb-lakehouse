# ADR-009 · Deterministic hash surrogate keys

**Decision.** `sk(namespace, natural_key) = first 60 bits of md5('sb:player:<id>')` as BIGINT; `-1` = unknown
member (e.g. team-level events with no player).

**Why.** Stable across full rebuilds and environments (no identity-column state), computable in any engine
(DuckDB, Spark, T-SQL), integer keys for Direct Lake efficiency, namespaced so other providers can't collide.
Collision probability at our scale (~10⁵ keys in 2⁶⁰) is negligible and is guarded by DQ uniqueness rules.
