# Data Pipeline: `pl_statsbomb_daily`

`pl_statsbomb_daily.json` is the reference definition (Fabric Data Factory JSON).
Replace the `<...>` placeholders, or build it in the UI in ~5 minutes:

1. **New item → Data pipeline** → `pl_statsbomb_daily`.
2. Add 3 **Notebook** activities, all pointing at `nb_01_run_pipeline`, chained *on success*, with base parameter `steps`:
   `bronze` → `silver,synthetic,integrate,dq_silver` → `gold,dq_gold`.
   Set *Retry = 2* on the bronze activity (network) – every step is idempotent so retries are safe.
3. Add **Semantic model refresh** (`sm_football_performance`) after gold.
4. Add an **Office 365 Outlook** or **Teams** activity wired to the *On fail* output of each notebook.
5. **Schedule**: daily 06:00 (Europe/London) – StatsBomb typically publishes/revises within hours of full time;
   on match days add a second trigger 2 hours after the final whistle.

Why three activities and not one? Isolation: a StatsBomb outage fails (and retries) only bronze;
a DQ failure stops before gold so Power BI keeps showing yesterday's *trusted* data.
