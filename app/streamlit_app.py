"""pitchlake demo app – a thin consumption layer over the gold star schema.

Run locally:      streamlit run app/streamlit_app.py
Hosted:           Streamlit Community Cloud -> main file app/streamlit_app.py
In production the same gold tables are served by a Direct Lake Power BI model;
this app exists so the whole flow can be demonstrated anywhere, live.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
os.environ.setdefault("PITCHLAKE_ROOT", str(REPO / "lakehouse"))

from mplsoccer import Pitch, VerticalPitch  # noqa: E402

from pitchlake.gold.build import list_models  # noqa: E402
from pitchlake.ops.logging_setup import configure_logging  # noqa: E402
from pitchlake.pipeline import Pipeline  # noqa: E402

st.set_page_config(page_title="pitchlake · StatsBomb on a lakehouse", page_icon="⚽", layout="wide")

RED, NAVY, GREY, GOLD = "#d7192d", "#1d2a44", "#9aa3ad", "#c9a227"


# ----------------------------------------------------------------- data access
@st.cache_resource
def pipeline() -> Pipeline:
    configure_logging("WARNING")
    return Pipeline.from_env("local")


def table(layer: str, name: str, columns: list[str] | None = None) -> pd.DataFrame:
    store = pipeline().store
    version = store.fingerprint(layer, name)
    return _cached_table(layer, name, tuple(columns) if columns else None, version)


@st.cache_data(show_spinner=False, max_entries=64)
def _cached_table(layer: str, name: str, columns, version) -> pd.DataFrame:
    store = pipeline().store
    if version is None:
        return pd.DataFrame()
    return store.read(layer, name, columns=list(columns) if columns else None).to_pandas()


def gold_ready() -> bool:
    return pipeline().store.exists("gold", "fact_player_match")


# ----------------------------------------------------------------- sidebar
st.sidebar.title("⚽ pitchlake")
st.sidebar.caption("StatsBomb → Bronze → Silver → Gold, on Delta Lake.\nSame code runs in Microsoft Fabric.")

with st.sidebar.expander("Run the pipeline", expanded=not gold_ready()):
    scope = st.selectbox(
        "Competition-season",
        [
            "55:282 · UEFA Euro 2024",
            "43:106 · FIFA World Cup 2022",
            "53:315 · Women's Euro 2025",
            "37:4 · FA WSL 2018/19 (schema-drift demo)",
        ],
    )
    max_matches = st.number_input("Max new matches this run (0 = all)", 0, 400, 0)
    with_360 = st.checkbox("Include 360 freeze-frames (slower)", value=False)
    if st.button("▶ Run bronze → gold", type="primary"):
        cid, sid = scope.split(" · ")[0].split(":")
        overrides = {
            "sources": {
                "statsbomb": {
                    "scope": [{"competition_id": int(cid), "season_id": int(sid), "label": scope}],
                    "max_matches_per_run": int(max_matches) or None,
                    "entities": {"lineups": True, "events": True, "frames_360": with_360},
                }
            },
            "quality": {"mode": "warn"},
        }
        configure_logging("WARNING")
        p = Pipeline.from_env("local", overrides=overrides)
        t0 = time.time()
        with st.status("Running pipeline…", expanded=True) as status:
            ctx = p.run(trigger="streamlit")
            for s in ctx.summary():
                st.write(
                    f"**{s['step']}** · {s['status']} · {s['duration_s']}s · rows out {s.get('rows_out')}"
                )
            status.update(label=f"Done in {time.time() - t0:.0f}s – run {ctx.run_id}", state="complete")
        st.cache_data.clear()

if not gold_ready():
    st.title("No gold data yet")
    st.info(
        "Use **Run the pipeline** in the sidebar (Euro 2024 without 360 takes about a minute), "
        "or run `pitchlake run` from the repo root."
    )
    st.stop()

# ----------------------------------------------------------------- shared dims
dim_match = table("gold", "dim_match")
dim_team = table("gold", "dim_team")
dim_player = table("gold", "dim_player")
dim_cs = table("gold", "dim_competition_season")
team_name = dict(zip(dim_team.team_key, dim_team.team_name))
player_name = dict(zip(dim_player.player_key, dim_player.display_name))
dim_match = dim_match.merge(dim_cs[["competition_season_key", "competition_season_name"]], how="left")

tab_overview, tab_match, tab_player, tab_physical, tab_quality, tab_model = st.tabs(
    ["Overview", "Match centre", "Player", "Physical × technical", "Data quality & lineage", "Data model"]
)

# ================================================================= overview
with tab_overview:
    st.header("Platform overview")
    fpm = table("gold", "fact_player_match", ["player_key", "goals", "xg", "minutes_played"])
    runs = table("meta", "pipeline_runs")
    dq = table("meta", "dq_results")
    c = st.columns(5)
    c[0].metric("Matches", f"{len(dim_match):,}")
    c[1].metric("Events", f"{pipeline().store.read('gold', 'fact_events', ['event_id']).num_rows:,}")
    c[2].metric("Players", f"{(dim_player.player_key != -1).sum():,}")
    last_dq = dq[dq.run_id == dq.run_id.max()] if not dq.empty else dq
    c[3].metric(
        "DQ rules passing (last run)",
        f"{last_dq.passed.dropna().astype(bool).mean():.0%}" if not last_dq.empty else "–",
    )
    c[4].metric("Goals / xG", f"{int(fpm.goals.sum())} / {fpm.xg.sum():.1f}")

    st.subheader("Recent pipeline steps")
    if not runs.empty:
        recent = runs.sort_values("started_at", ascending=False).head(14)
        st.dataframe(
            recent[
                ["run_id", "step", "status", "duration_s", "rows_in", "rows_out", "trigger", "environment"]
            ],
            hide_index=True,
            use_container_width=True,
        )
    st.subheader("Competitions loaded")
    st.dataframe(
        dim_match.groupby("competition_season_name")
        .agg(
            matches=("match_key", "count"),
            first=("match_date", "min"),
            last=("match_date", "max"),
            source_last_updated=("source_last_updated", "max"),
        )
        .reset_index(),
        hide_index=True,
        use_container_width=True,
    )

# ================================================================= match centre
with tab_match:
    comps = sorted(dim_match.competition_season_name.dropna().unique())
    comp = st.selectbox("Competition", comps, key="m_comp")
    dm = dim_match[dim_match.competition_season_name == comp].sort_values("match_date", ascending=False)
    label = st.selectbox(
        "Match", dm.fixture_result + "  ·  " + dm.match_date.astype(str) + "  ·  " + dm.stage
    )
    m = dm.iloc[
        list(dm.fixture_result + "  ·  " + dm.match_date.astype(str) + "  ·  " + dm.stage).index(label)
    ]
    shots = table("gold", "fact_shots")
    s = shots[(shots.match_key == m.match_key) & (~shots.is_penalty_shootout)].copy()
    tm = table("gold", "fact_team_match")
    tm = tm[tm.match_key == m.match_key].copy()
    tm["team"] = tm.team_key.map(team_name)

    st.header(m.fixture_result)
    st.caption(
        f"{m.stage} · {m.match_date} · {m.stadium_name} · referee {m.referee_name} · data v{m.data_version}"
    )
    cols = st.columns(len(tm) or 1)
    for col, (_, r) in zip(cols, tm.sort_values("is_home", ascending=False).iterrows()):
        col.metric(r.team, f"{r.goals_for}", f"xG {r.xg:.2f}", delta_color="off")
        col.caption(
            f"Possession {r.possession_pct}% · shots {r.shots} ({r.shots_on_target} on target) · "
            f"PPDA {r.ppda} · open-play passes {r.open_play_passes}"
        )

    left, right = st.columns([3, 2])
    with left:
        pitch = Pitch(pitch_type="statsbomb", pitch_color="white", line_color=GREY)
        fig, ax = pitch.draw(figsize=(9, 6))
        home = m.home_team_key
        for _, r in s.iterrows():
            x, y = (
                (r.location_x, r.location_y)
                if r.team_key != home
                else (120 - r.location_x, 80 - r.location_y)
            )
            color = RED if r.team_key == home else NAVY
            pitch.scatter(
                x,
                y,
                s=60 + r.xg * 900,
                ax=ax,
                color=color if r.is_goal else "white",
                edgecolors=color,
                linewidth=1.5,
                alpha=0.9,
                zorder=3,
            )
        ax.set_title(
            f"Shot map (size = xG, filled = goal)  ·  {team_name[home]} ← | → {team_name[m.away_team_key]}",
            fontsize=10,
        )
        st.pyplot(fig, use_container_width=True)
    with right:
        fig, ax = plt.subplots(figsize=(5, 4))
        for tk, color in ((m.home_team_key, RED), (m.away_team_key, NAVY)):
            ts = s[s.team_key == tk].sort_values(["period", "minute", "second"])
            xs = [0] + list(ts.minute) + [max(90, int(s.minute.max() if len(s) else 90))]
            ys = [0] + list(ts.xg.cumsum()) + [ts.xg.sum()]
            ax.step(xs, ys, where="post", color=color, label=team_name[tk], linewidth=2)
            for _, g in ts[ts.is_goal].iterrows():
                ax.scatter(g.minute, ts[ts.minute <= g.minute].xg.sum(), color=color, s=40, zorder=3)
        ax.set_xlabel("minute")
        ax.set_ylabel("cumulative xG")
        ax.legend(frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_title("xG race", fontsize=10)
        st.pyplot(fig, use_container_width=True)
        top = s.sort_values("xg", ascending=False).head(8)
        st.dataframe(
            pd.DataFrame(
                {
                    "min": top.minute,
                    "player": top.player_key.map(player_name),
                    "xG": top.xg.round(2),
                    "outcome": top.outcome,
                    "assist": top.assist_type,
                    "defenders in cone": top.defenders_in_shot_cone,
                }
            ),
            hide_index=True,
            use_container_width=True,
        )

# ================================================================= player
with tab_player:
    fpm = table("gold", "fact_player_match")
    agg = (
        fpm.groupby("player_key")
        .agg(
            apps=("match_key", "count"),
            minutes=("minutes_played", "sum"),
            goals=("goals", "sum"),
            xg=("xg", "sum"),
            npxg=("npxg", "sum"),
            xa=("xa", "sum"),
            assists=("assists", "sum"),
            key_passes=("key_passes", "sum"),
            progressive_passes=("progressive_passes", "sum"),
            progressive_carries=("progressive_carries", "sum"),
            pressures=("pressures", "sum"),
            tackles_won=("tackles_won", "sum"),
            interceptions=("interceptions", "sum"),
        )
        .reset_index()
    )
    agg = agg.merge(dim_player[["player_key", "display_name", "latest_team", "primary_position_group"]])
    min_minutes = st.slider("Minimum minutes", 0, 600, 270, step=30)
    view = agg[agg.minutes >= min_minutes].copy()
    view[["minutes", "xg", "npxg", "xa"]] = view[["minutes", "xg", "npxg", "xa"]].round(2)
    per90 = [
        "goals",
        "xg",
        "npxg",
        "xa",
        "key_passes",
        "progressive_passes",
        "progressive_carries",
        "pressures",
        "tackles_won",
        "interceptions",
    ]
    for col in per90:
        view[f"{col}_p90"] = (view[col] / view.minutes * 90).round(2)
    metric = st.selectbox("Rank by (per 90)", [f"{c}_p90" for c in per90], index=1)
    pos = st.multiselect("Position group", sorted(view.primary_position_group.dropna().unique()))
    if pos:
        view = view[view.primary_position_group.isin(pos)]
    st.dataframe(
        view.sort_values(metric, ascending=False)[
            [
                "display_name",
                "latest_team",
                "primary_position_group",
                "apps",
                "minutes",
                metric,
                "goals",
                "xg",
                "xa",
            ]
        ].head(25),
        hide_index=True,
        use_container_width=True,
    )

    pick = st.selectbox("Player detail", view.sort_values(metric, ascending=False).display_name.head(60))
    pk = view[view.display_name == pick].player_key.iloc[0]
    passes = table(
        "gold",
        "fact_passes",
        [
            "player_key",
            "match_key",
            "location_x",
            "location_y",
            "end_x",
            "end_y",
            "is_complete",
            "is_progressive",
            "is_key_pass",
        ],
    )
    pp = passes[(passes.player_key == pk) & passes.is_progressive]
    c1, c2 = st.columns([3, 2])
    with c1:
        pitch = VerticalPitch(pitch_type="statsbomb", line_color=GREY, half=False)
        fig, ax = pitch.draw(figsize=(5, 7))
        pitch.arrows(pp.location_x, pp.location_y, pp.end_x, pp.end_y, ax=ax, color=RED, width=1.5, alpha=0.7)
        kp = passes[(passes.player_key == pk) & passes.is_key_pass]
        pitch.arrows(kp.location_x, kp.location_y, kp.end_x, kp.end_y, ax=ax, color=GOLD, width=2)
        ax.set_title(f"{pick}: progressive passes (red) & key passes (gold)", fontsize=9)
        st.pyplot(fig, use_container_width=True)
    with c2:
        mine = fpm[fpm.player_key == pk].merge(dim_match[["match_key", "fixture_result", "match_date"]])
        st.dataframe(
            mine.sort_values("match_date")[
                [
                    "match_date",
                    "fixture_result",
                    "minutes_played",
                    "goals",
                    "xg",
                    "xa",
                    "progressive_passes",
                    "pressures",
                ]
            ],
            hide_index=True,
            use_container_width=True,
        )

# ================================================================= physical x technical
with tab_physical:
    st.header("Cross-source integration: Catapult GPS × StatsBomb events")
    st.warning(
        "Physical data here is **SYNTHETIC** (generated by `pitchlake.sources.synthetic`) to demonstrate the "
        "integration pattern. It does not describe any real player.",
        icon="⚠️",
    )
    phys = table("gold", "fact_player_match_physical")
    if phys.empty:
        st.info("No physical data – enable `synthetic_sources` or connect the Catapult pipeline.")
    else:
        fpm = table("gold", "fact_player_match")
        j = (
            phys.merge(fpm, on=["match_key", "player_key"])
            .merge(dim_player[["player_key", "display_name", "primary_position_group"]])
            .merge(dim_match[["match_key", "fixture_result"]])
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("Player-matches joined", len(j))
        c2.metric("Linked via identity xref", int(dim_player.has_gps_data.sum()))
        xref = table("silver", "xref_player")
        c3.metric("Awaiting review", int(xref.status.isin(["review", "unmatched"]).sum()))
        j = j[j.minutes_played >= 30]  # per-90 rates are noise for short cameos
        fig, ax = plt.subplots(figsize=(8, 3.8))
        for grp, color in zip(["Defender", "Midfielder", "Forward", "Goalkeeper"], [NAVY, RED, GOLD, GREY]):
            g = j[j.primary_position_group == grp]
            ax.scatter(
                g.hsr_distance_m / g.minutes_played * 90,
                g.pressures / g.minutes_played * 90,
                label=grp,
                color=color,
                alpha=0.75,
            )
        ax.set_xlabel("High-speed running per 90 (m) – Catapult")
        ax.set_ylabel("Pressures per 90 – StatsBomb")
        ax.legend(frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        st.pyplot(fig, use_container_width=True)
        st.dataframe(
            j[
                [
                    "fixture_result",
                    "display_name",
                    "minutes_played",
                    "total_distance_m",
                    "hsr_distance_m",
                    "sprint_efforts",
                    "max_speed_kmh",
                    "pressures",
                    "progressive_carries",
                    "xg",
                ]
            ].sort_values("hsr_distance_m", ascending=False),
            hide_index=True,
            use_container_width=True,
        )

# ================================================================= quality
with tab_quality:
    st.header("Data quality, drift & lineage")
    dq = table("meta", "dq_results")
    if not dq.empty:
        last = dq[dq.evaluated_at >= dq.evaluated_at.max() - pd.Timedelta(minutes=30)]
        last = last.sort_values("evaluated_at").drop_duplicates("rule_id", keep="last")
        last["status"] = last.apply(
            lambda r: (
                "⏭ skipped"
                if pd.isna(r.passed)
                else ("✅ pass" if r.passed else ("❌ fail" if r.severity == "error" else "⚠️ warn"))
            ),
            axis=1,
        )
        st.dataframe(
            last[
                [
                    "status",
                    "rule_id",
                    "table_name",
                    "rule_type",
                    "severity",
                    "failed_count",
                    "total_count",
                    "description",
                ]
            ].sort_values(["status", "rule_id"]),
            hide_index=True,
            use_container_width=True,
        )
        failing = last[(last.passed == False) & last.sample_json.notna()]  # noqa: E712
        if not failing.empty:
            rule = st.selectbox("Inspect failing sample", failing.rule_id)
            st.json(json.loads(failing[failing.rule_id == rule].sample_json.iloc[0]))
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Identity review queue")
        xref = table("silver", "xref_player")
        if not xref.empty:
            st.dataframe(
                xref[xref.status.isin(["review", "unmatched"])][
                    ["source_system", "source_id", "source_name", "sb_name", "match_score", "status"]
                ],
                hide_index=True,
                use_container_width=True,
            )
            st.caption(
                "Approve by adding a row to `conf/reference/xref_player_overrides.csv` (reviewed via PR)."
            )
    with c2:
        st.subheader("Schema drift detected")
        drift = table("meta", "schema_drift")
        st.dataframe(
            drift.groupby("json_path")
            .agg(occurrences=("occurrences", "sum"), first_seen=("detected_at", "min"))
            .reset_index()
            if not drift.empty
            else pd.DataFrame({"json_path": [], "occurrences": []}),
            hide_index=True,
            use_container_width=True,
        )
    st.subheader("Incremental watermarks (meta.ingestion_state)")
    st.dataframe(
        table("meta", "ingestion_state").sort_values("bronze_ingested_at", ascending=False).head(60),
        hide_index=True,
        use_container_width=True,
    )
    st.subheader("Bronze manifest (latest landings)")
    man = table("meta", "bronze_manifest")
    st.dataframe(
        man.sort_values("ingested_at", ascending=False).head(60)[
            [
                "ingested_at",
                "entity",
                "resource_key",
                "status",
                "bytes",
                "record_count",
                "source_updated_at",
                "path",
            ]
        ],
        hide_index=True,
        use_container_width=True,
    )

# ================================================================= model
with tab_model:
    st.header("Gold star schema")
    st.markdown(
        "Facts share **conformed dimensions** (player, team, match, date) so StatsBomb events, Catapult GPS "
        "and any future source (VALD, Kitman, Second Spectrum) can be analysed together."
    )
    rows = []
    for name, desc, _ in list_models():
        t = pipeline().store.read("gold", name)
        rows.append(
            {"table": f"gold.{name}", "rows": t.num_rows, "columns": t.num_columns, "description": desc}
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.caption("Data: StatsBomb Open Data (Hudl StatsBomb). Physical data synthetic.")
