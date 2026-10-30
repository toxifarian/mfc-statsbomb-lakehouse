"""Generate the Fabric notebooks in fabric/notebooks from the cell sources below.

Notebooks are generated (not hand-edited) so their logic stays reviewable in a
.py diff and they never drift from the package: every notebook is a thin
shell that installs a *pinned* version of `pitchlake` and calls it.

    python scripts/build_notebooks.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "fabric" / "notebooks"

FABRIC_PY_META = {
    "kernel_info": {"name": "jupyter", "jupyter_kernel_name": "python3.11"},
    "kernelspec": {"name": "jupyter", "display_name": "Jupyter"},
    "language_info": {"name": "python"},
    "microsoft": {"language": "python", "language_group": "jupyter_python"},
    "dependencies": {"lakehouse": {"default_lakehouse_name": "lh_football"}},
}


def md(src: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": src.strip("\n").splitlines(keepends=True)}


def code(src: str, parameters: bool = False) -> dict:
    meta = {"tags": ["parameters"]} if parameters else {}
    return {
        "cell_type": "code",
        "metadata": meta,
        "execution_count": None,
        "outputs": [],
        "source": src.strip("\n").splitlines(keepends=True),
    }


def notebook(cells: list[dict]) -> dict:
    return {"cells": cells, "metadata": FABRIC_PY_META, "nbformat": 4, "nbformat_minor": 5}


INSTALL = code("""
# Install the framework at a pinned, tagged version (same code as CI tested).
%pip install -q "{package_source}"
""")

PARAMS_RUN = code(
    """
# ---- parameters (overridden by the Data Pipeline activity) ----
steps = "bronze,silver,synthetic,integrate,dq_silver,gold,dq_gold"   # comma-separated
scope = "55:282"                 # competition_id:season_id[,cid:sid...]
max_matches = 0                  # 0 = no limit
include_360 = True
full_refresh = False
dq_mode = "enforce"              # enforce | warn
environment = "fabric"           # fabric | fabric-prod
# Pinned release of the framework. A GitHub tag archive needs no git client in the runtime.
# Alternative: upload the wheel from CI to Files/libs and use "/lakehouse/default/Files/libs/pitchlake-1.0.0-py3-none-any.whl"
package_source = "https://github.com/<GITHUB_USER>/mfc-statsbomb-lakehouse/archive/refs/tags/v1.0.0.zip"
""",
    parameters=True,
)

RUN = code("""
import json, os
from pitchlake.ops.logging_setup import configure_logging
from pitchlake.pipeline import Pipeline

configure_logging("INFO")
overrides = {
    "sources": {"statsbomb": {
        "scope": [{"competition_id": int(c), "season_id": int(s), "label": f"{c}:{s}"}
                  for c, s in (x.split(":") for x in scope.split(","))],
        "max_matches_per_run": int(max_matches) or None,
        "entities": {"lineups": True, "events": True, "frames_360": bool(include_360)},
    }},
    "quality": {"mode": dq_mode},
}
pipe = Pipeline.from_env(environment, overrides=overrides)
print(pipe.platform.describe())
ctx = pipe.run(steps=[s.strip() for s in steps.split(",") if s.strip()],
               full_refresh=bool(full_refresh), trigger="fabric")
summary = {"run_id": ctx.run_id, "steps": ctx.summary()}
print(json.dumps(summary, indent=2, default=str))
""")

EXIT = code("""
# Return a compact result to the calling Data Pipeline (visible in the activity output)
notebookutils.notebook.exit(json.dumps({"run_id": ctx.run_id,
                                        "failed": [s["step"] for s in ctx.summary() if s["status"] != "succeeded"]}))
""")

NB_RUN = notebook(
    [
        md("""
# pitchlake · run pipeline

Parameterised entry point used by the **pl_statsbomb_daily** Data Pipeline (one activity per stage)
and for ad-hoc runs. Attach the **lh_football** lakehouse as the default lakehouse.

| layer | where |
|---|---|
| bronze | `Files/bronze/statsbomb/<entity>/<partition>/<key>/<ts>_<sha>.json` |
| silver / gold / meta | `Tables/silver.*`, `Tables/gold.*`, `Tables/meta.*` (Delta) |
"""),
        PARAMS_RUN,
        INSTALL,
        RUN,
        EXIT,
    ]
)

NB_EXPLORE = notebook(
    [
        md("""
# 00 · Evaluate the source (StatsBomb)

First contact with an unfamiliar source: what entities exist, how big are they, how nested,
how often do they change, and what quirks will bite downstream? Uses **statsbombpy** (as suggested
in the brief) for quick exploration – production ingestion lands raw JSON instead (see ADR-001).
"""),
        code("%pip install -q statsbombpy"),
        code("""
import warnings, collections
import pandas as pd
from statsbombpy import sb
warnings.filterwarnings("ignore")   # "credentials were not supplied. open data access only"

comps = sb.competitions()
display(comps[["competition_id", "season_id", "competition_name", "season_name", "match_updated",
               "match_available_360"]].sort_values("match_updated", ascending=False).head(20))
"""),
        code("""
matches = sb.matches(competition_id=55, season_id=282)   # UEFA Euro 2024
print(len(matches), "matches;", matches["last_updated"].min(), "->", matches["last_updated"].max())
display(matches[["match_id", "match_date", "home_team", "away_team", "home_score", "away_score",
                 "competition_stage", "last_updated", "last_updated_360"]].head())
"""),
        code("""
events = sb.events(match_id=3943043)   # the final
print(events.shape, "rows x cols  <- statsbombpy flattens nested JSON into ~100+ sparse columns")
display(events["type"].value_counts().head(15))
print("share of nulls per column (top 15):")
display(events.isna().mean().sort_values(ascending=False).head(15))
"""),
        md("""
### Findings that shaped the design
* **Optional keys are omitted**, not null – a pass with no `outcome` is *complete*; absent flags mean `False`.
* **Variable shapes** – `shot.end_location` is 2-D or 3-D; freeze-frames & tactics are nested arrays → child tables.
* **Data is revised long after the match** – Euro 2024 `last_updated` values are from 2026 → watermark-based incremental loads.
* **Clock quirks** – timestamps restart each period; extra-time lineup stints are chained in string order (bug) → minutes rebuilt.
* **No DOB / external IDs in open-data lineups** → identity resolution against Catapult / Transfermarkt is required.
* **statsbombpy swallows HTTP errors** (returns `[]`) → production client raises on non-200s.
* **Coordinates**: 120×80 units, each team attacking left→right; tracking providers use metres from centre → conversion macros.
"""),
    ]
)

PARAMS_SM = code(
    """
semantic_model_name = "sm_football_performance"
lakehouse_name = "lh_football"
overwrite = False
""",
    parameters=True,
)

NB_SEMANTIC = notebook(
    [
        md("""
# 02 · Direct Lake semantic model (as code)

Creates/updates the Power BI semantic model over the gold star schema: tables, relationships,
DAX measures and formatting – idempotent, so it can run after every deployment.
Direct Lake reads the Delta tables in OneLake directly: no import refresh, no duplicate copy.
"""),
        PARAMS_SM,
        code("%pip install -q semantic-link-labs"),
        code("""
import sempy_labs as labs
from sempy_labs.tom import connect_semantic_model
import sempy.fabric as fabric

TABLES = {  # friendly name -> lakehouse table
    "Date": "gold.dim_date", "Competition": "gold.dim_competition_season", "Team": "gold.dim_team",
    "Player": "gold.dim_player", "Position": "gold.dim_position",
    "Match": "gold.dim_match", "Event Type": "gold.dim_event_type",
    "Events": "gold.fact_events", "Shots": "gold.fact_shots", "Passes": "gold.fact_passes",
    "Player Match": "gold.fact_player_match", "Team Match": "gold.fact_team_match",
    "Physical": "gold.fact_player_match_physical",
}
existing = fabric.list_datasets()["Dataset Name"].tolist()
if semantic_model_name not in existing or overwrite:
    labs.directlake.generate_direct_lake_semantic_model(
        dataset=semantic_model_name, tables=TABLES, source=lakehouse_name, source_type="Lakehouse",
        overwrite=overwrite, refresh=False)
"""),
        code("""
RELATIONSHIPS = [  # (from table, from col, to table, to col, active)
    ("Match", "date_key", "Date", "date_key", True),
    ("Match", "competition_season_key", "Competition", "competition_season_key", True),
    ("Events", "match_key", "Match", "match_key", True), ("Events", "player_key", "Player", "player_key", True),
    ("Events", "team_key", "Team", "team_key", True), ("Events", "event_type_key", "Event Type", "event_type_key", True),
    ("Events", "position_key", "Position", "position_key", True),
    ("Shots", "match_key", "Match", "match_key", True), ("Shots", "player_key", "Player", "player_key", True),
    ("Shots", "team_key", "Team", "team_key", True),
    ("Passes", "match_key", "Match", "match_key", True), ("Passes", "player_key", "Player", "player_key", True),
    ("Passes", "team_key", "Team", "team_key", True),
    ("Player Match", "match_key", "Match", "match_key", True), ("Player Match", "player_key", "Player", "player_key", True),
    ("Player Match", "team_key", "Team", "team_key", True),
    ("Team Match", "match_key", "Match", "match_key", True), ("Team Match", "team_key", "Team", "team_key", True),
    ("Physical", "match_key", "Match", "match_key", True), ("Physical", "player_key", "Player", "player_key", True),
]

MEASURES = {  # table: [(name, DAX, format, folder)]
    "Player Match": [
        ("Minutes", "SUM('Player Match'[minutes_played])", "#,0", "Volume"),
        ("Appearances", "COUNTROWS('Player Match')", "#,0", "Volume"),
        ("Goals", "SUM('Player Match'[goals])", "#,0", "Attacking"),
        ("xG", "SUM('Player Match'[xg])", "0.00", "Attacking"),
        ("npxG", "SUM('Player Match'[npxg])", "0.00", "Attacking"),
        ("xA", "SUM('Player Match'[xa])", "0.00", "Attacking"),
        ("Goals - xG", "[Goals] - [xG]", "+0.00;-0.00;0.00", "Attacking"),
        ("xG per 90", "DIVIDE([xG], [Minutes]) * 90", "0.00", "Per 90"),
        ("npxG + xA per 90", "DIVIDE([npxG] + [xA], [Minutes]) * 90", "0.00", "Per 90"),
        ("Progressive Passes per 90", "DIVIDE(SUM('Player Match'[progressive_passes]), [Minutes]) * 90", "0.0", "Per 90"),
        ("Pressures per 90", "DIVIDE(SUM('Player Match'[pressures]), [Minutes]) * 90", "0.0", "Per 90"),
        ("Pass Completion %", "DIVIDE(SUM('Player Match'[passes_completed]), SUM('Player Match'[passes_attempted]))", "0.0%", "Passing"),
    ],
    "Team Match": [
        ("Team Goals", "SUM('Team Match'[goals_for])", "#,0", "Team"),
        ("Team xG", "SUM('Team Match'[xg])", "0.00", "Team"),
        ("Team xGA", "SUM('Team Match'[xg_against])", "0.00", "Team"),
        ("xG Difference", "[Team xG] - [Team xGA]", "+0.00;-0.00;0.00", "Team"),
        ("Points", "SUM('Team Match'[points])", "#,0", "Team"),
        ("Avg Possession %", "AVERAGE('Team Match'[possession_pct]) / 100", "0.0%", "Team"),
        ("Avg PPDA", "AVERAGE('Team Match'[ppda])", "0.0", "Team"),
    ],
    "Shots": [
        ("Shots", "COUNTROWS(FILTER('Shots', NOT 'Shots'[is_penalty_shootout]))", "#,0", "Shooting"),
        ("Shots on Target %", "DIVIDE(CALCULATE([Shots], 'Shots'[is_on_target]), [Shots])", "0.0%", "Shooting"),
        ("xG per Shot", "DIVIDE(CALCULATE(SUM('Shots'[xg]), NOT 'Shots'[is_penalty_shootout]), [Shots])", "0.000", "Shooting"),
    ],
    "Physical": [
        ("Total Distance (km)", "SUM('Physical'[total_distance_m]) / 1000", "0.0", "Physical"),
        ("HSR per 90 (m)", "DIVIDE(SUM('Physical'[hsr_distance_m]), SUM('Physical'[duration_min])) * 90", "#,0", "Physical"),
        # numerator restricted to players who have GPS data, so both sides cover the same population
        ("Pressures per 1km HSR", "DIVIDE(CALCULATE(SUM('Player Match'[pressures]), 'Player'[has_gps_data]), SUM('Physical'[hsr_distance_m]) / 1000)", "0.0", "Physical x Technical"),
    ],
}

with connect_semantic_model(dataset=semantic_model_name, readonly=False) as tom:
    have = {(r.FromTable.Name, r.FromColumn.Name, r.ToTable.Name) for r in tom.model.Relationships}
    for ft, fc, tt, tc, active in RELATIONSHIPS:
        if (ft, fc, tt) not in have:
            tom.add_relationship(from_table=ft, from_column=fc, to_table=tt, to_column=tc,
                                 from_cardinality="Many", to_cardinality="One", is_active=active)
    have_m = {m.Name: m for m in tom.all_measures()}
    for table, measures in MEASURES.items():
        for name, dax, fmt, folder in measures:
            if name in have_m:   # idempotent: keep definitions in sync with this notebook
                m = have_m[name]
                m.Expression, m.FormatString, m.DisplayFolder = dax, fmt, folder
            else:
                tom.add_measure(table_name=table, measure_name=name, expression=dax,
                                format_string=fmt, display_folder=folder)
    tom.mark_as_date_table(table_name="Date", column_name="date")
    # hide surrogate keys from report authors
    for c in tom.all_columns():
        if c.Name.endswith("_key"):
            c.IsHidden = True
print("semantic model ready")
"""),
        code("labs.refresh_semantic_model(dataset=semantic_model_name)"),
    ]
)

NB_MONITOR = notebook(
    [
        md("""
# 03 · Operational monitoring

What a data engineer checks each morning: did the runs succeed, what changed upstream,
is quality holding, and is anything waiting for a human (identity review, schema drift)?
"""),
        code("""
%pip install -q duckdb deltalake
"""),
        code("""
import duckdb
from deltalake import DeltaTable
ROOT = "/lakehouse/default/Tables"
con = duckdb.connect()
for t in ["pipeline_runs", "dq_results", "ingestion_state", "schema_drift", "bronze_manifest"]:
    try:
        con.register(t, DeltaTable(f"{ROOT}/meta/{t}").to_pyarrow_dataset())
    except Exception as e:
        print("missing", t, e)
"""),
        code('''
con.sql("""SELECT run_id, step, status, round(duration_s,1) secs, rows_out, left(error,80) error
           FROM pipeline_runs ORDER BY started_at DESC LIMIT 20""").show()
'''),
        code('''
con.sql("""WITH last AS (SELECT max(run_id) run_id FROM dq_results)
           SELECT rule_id, severity, passed, failed_count FROM dq_results JOIN last USING (run_id)
           ORDER BY passed, severity""").show()
'''),
        code('''
con.sql("""SELECT competition_id, season_id, count(*) matches, max(last_updated) newest_source_change,
                  count(*) FILTER (WHERE silver_processed_at < bronze_ingested_at OR silver_processed_at IS NULL) pending
           FROM ingestion_state GROUP BY ALL""").show()
con.sql("SELECT json_path, sum(occurrences) n, min(detected_at) first_seen FROM schema_drift GROUP BY ALL").show()
'''),
    ]
)

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, nb in {
        "nb_00_explore_statsbomb.ipynb": NB_EXPLORE,
        "nb_01_run_pipeline.ipynb": NB_RUN,
        "nb_02_semantic_model.ipynb": NB_SEMANTIC,
        "nb_03_monitoring.ipynb": NB_MONITOR,
    }.items():
        (OUT / name).write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", OUT / name)
