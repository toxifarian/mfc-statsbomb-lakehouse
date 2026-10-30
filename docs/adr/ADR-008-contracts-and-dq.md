# ADR-008 · Explicit contract, drift detection and a declarative DQ gate

**Decision.**
* Silver events follow an explicit contract (`silver/contracts.py`) derived from profiling; unknown JSON paths are
  counted into `meta.schema_drift` and preserved verbatim in `extra_json` — **nothing is dropped silently**.
* 25 declarative rules (`conf/dq_rules.yml`): keys, uniqueness, ranges, accepted values, referential integrity,
  bronze↔silver reconciliation, **goals = scoreline** reconciliation, minutes plausibility, 1:1 identity links.
* `error` rules **block promotion to gold** (`quality.mode: enforce`); `warn` rules are recorded and surfaced.
  Results, with failing samples, go to `meta.dq_results`.

**Evidence it earns its keep.** On first run the rules caught two genuine vendor issues: the extra-time lineup
ordering bug (286 "minutes" for a player) and an x = 120.1 coordinate. Tested: an impossible coordinate injected
into a payload stops the run before gold is touched.

**Next.** Promote frequently-violated warns to vendor tickets; add freshness SLAs per competition; publish rules
as a data contract with the provider.
