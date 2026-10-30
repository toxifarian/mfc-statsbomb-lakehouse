# Runbook · Deploying & operating on Microsoft Fabric

This gets the platform running in a Fabric workspace (≈ 30–40 minutes the first time) and covers day-2 operations.

> Use a **personal / trial Fabric tenant** for the interview demo — not an employer's tenant.
> A free Fabric trial capacity can be started from https://app.fabric.microsoft.com (needs a work/school Entra
> account; check the current trial terms there).

## 0 · Prerequisites
* GitHub repo pushed (public, so Fabric can `pip install` the tagged release) and tagged: `git tag v1.0.0 && git push --tags`.
* In `scripts/build_notebooks.py` replace `<GITHUB_USER>` with your GitHub username, then
  `python scripts/build_notebooks.py` and commit (CI does this automatically on tag via `deploy-fabric.yml`).

## 1 · Workspace & lakehouse (5 min)
1. **Workspaces → New workspace** → `ws-football-data-dev` → License: *Trial* (or your F-SKU).
2. **New item → Lakehouse** → name `lh_football` → tick **Lakehouse schemas**.
3. In the lakehouse explorer, **New schema** × 3: `silver`, `gold`, `meta`.
   *(If tables later appear under "Unidentified", set `lakehouse.table_layout: prefix` — tables become
   `dbo.silver_events` etc. — see `conf/pitchlake.yml`.)*

## 2 · Notebooks (5 min)
1. Workspace → **Import → Notebook → From this computer** → select the four files in `fabric/notebooks/`.
2. Open `nb_01_run_pipeline` → **Lakehouses → Add → Existing lakehouse → lh_football** (makes it the default,
   mounted at `/lakehouse/default`).
3. Check the language selector shows **Python** (not PySpark). If not, switch it — the code runs on either, Python
   is cheaper and starts in seconds.
4. Repeat 2–3 for `nb_03_monitoring`. (`nb_02` does not need a lakehouse.)

*Automated alternative:* `az login && python scripts/deploy_fabric.py --workspace-id <guid>` creates the lakehouse
and notebooks via the REST API and binds the default lakehouse; or `terraform apply` in `infra/terraform`.

## 3 · First run (3–6 min)
Run `nb_01_run_pipeline` with defaults (Euro 2024, with 360). For a faster first demo set
`include_360 = False` (≈ 1 min). Expected output: 7 steps `succeeded`; warnings for the identity review queue and
corrected lineup stints (by design — they are real findings).

Verify in the lakehouse explorer: `Files/bronze/statsbomb/...`, and tables under `silver`, `gold`, `meta`.

## 4 · Serving layer (10 min)
1. **SQL analytics endpoint** of `lh_football` → New SQL query → paste `fabric/sql/analyst_views.sql` → run.
2. Run `nb_02_semantic_model` → creates **sm_football_performance** (Direct Lake) with relationships + measures.
3. Open the model → **Create report → Auto-create** for a quick start, or build:
   * table: Player · Minutes · xG · npxG + xA per 90 · Progressive Passes per 90 (filter Minutes ≥ 270)
   * scatter: HSR per 90 (m) vs Pressures per 90 by Player (Physical × technical)
   * matrix: Team · Team xG · Team xGA · xG Difference · Avg PPDA
4. If `nb_02` fails on your tenant (preview APIs change): Lakehouse → **New semantic model**, tick the gold tables,
   then rerun only the second code cell of `nb_02` to add relationships and measures.

## 5 · Orchestration (5 min)
Build `pl_statsbomb_daily` as described in `fabric/pipeline/README.md` (3 notebook activities chained on success,
model refresh, failure alert) and add a daily schedule.

## 6 · Optional: Git integration
Workspace settings → **Git integration** → GitHub → this repo, branch `main`, folder `fabric/workspace` — Fabric
then serialises item definitions into Git so notebook/pipeline/model changes go through PRs.

## 7 · Optional: hosted Streamlit demo
share.streamlit.io → New app → this repo → main file `app/streamlit_app.py` → Deploy. On first open use
**Run the pipeline** in the sidebar (Euro 2024 without 360 ≈ 1 minute).

---

## Day-2 operations

| Situation | Action |
|---|---|
| Daily run failed at bronze (API down / 5xx) | Nothing — retried by the activity policy; watermarks didn't advance so the next run catches up |
| DQ `error` stopped the run | `nb_03_monitoring` → failing rule + `sample_json`; fix code/contract or, if vendor data, raise with StatsBomb; rerun from silver (`steps="silver,…"`) — no API calls needed |
| Schema drift warning | Inspect `meta.schema_drift`; data is preserved in `extra_json`; add the path to `silver/contracts.py` via PR; rerun silver with `full_refresh=True` (re-flattens from bronze) |
| Identity review queue non-empty | Analyst checks `silver.xref_player` (status `review`/`unmatched`); add approved rows to `conf/reference/xref_player_overrides.csv` via PR; rerun `integrate,dq_silver,gold,dq_gold` |
| New competition / season licensed | Add to `sources.statsbomb.scope` in config (PR) → next run backfills it |
| Backfill a single match | `match_ids` via CLI (`pitchlake run --match-ids 3943043 --full-refresh`) |
| StatsBomb API version bump | `pitchlake check-api` flags it (nightly CI); test the new version against the contract in dev before changing the pin |
| Table maintenance | weekly `pitchlake maintain` (OPTIMIZE compaction + VACUUM 7 days) |
