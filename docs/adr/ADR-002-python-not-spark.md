# ADR-002 · Python notebooks (delta-rs + DuckDB), not Spark

**Context.** A full tournament is ~190k events / 0.5 GB raw; a league season ~1.4 M events. Fabric offers Spark
notebooks and lighter **Python notebooks** (single node, 2 vCores by default, Polars/DuckDB/delta-rs available).

**Decision.** Implement transforms with **pyarrow + delta-rs** (write Delta) and **DuckDB** (SQL over Arrow),
packaged as a pip-installable library. Run it in Fabric Python notebooks.

**Why.** Start-up in seconds instead of a Spark session; a fraction of the capacity units; identical code runs on a
laptop and in CI (fast tests, real end-to-end runs in GitHub Actions); work is per-match so it parallelises
naturally if ever needed.

**Alternatives.** PySpark (great at TB scale, overkill here, slower dev loop); Dataflow Gen2 (low-code, weak for
nested JSON + testing).

**Consequences / exit ramp.** Tables are standard Delta in OneLake → Spark, the SQL endpoint and Direct Lake read
them unchanged. If volume grows (e.g. Second Spectrum tracking at 25 fps ≈ 3–4 M rows *per match*), that source
gets a Spark job; the framework's platform/table abstractions stay the same.
