"""Silver data contracts.

The event contract is an explicit, reviewed list of JSON paths (built from
profiling every Euro 2024 event; see docs/source_evaluation.md). It gives us:

* a stable, typed schema for analysts (no surprise columns),
* **schema drift detection** – any path the contract doesn't know is recorded
  in ``meta.schema_drift`` *and* preserved in ``extra_json`` so nothing is lost,
* one place to change when StatsBomb publishes a new data version.
"""

from __future__ import annotations

import pyarrow as pa

TS = pa.timestamp("us", tz="UTC")

# --------------------------------------------------------------------------
# Event contract: json path -> arrow type.  `{id,name}` objects are expanded
# automatically, coordinate arrays are listed explicitly.
# --------------------------------------------------------------------------
_REF = "ref"  # {id, name} object -> <col>_id (int64) + <col>_name (string)

EVENT_PATHS: dict[str, object] = {
    # core
    "id": pa.string(),
    "index": pa.int64(),
    "period": pa.int64(),
    "timestamp": pa.string(),
    "minute": pa.int64(),
    "second": pa.int64(),
    "type": _REF,
    "possession": pa.int64(),
    "possession_team": _REF,
    "play_pattern": _REF,
    "team": _REF,
    "player": _REF,
    "position": _REF,
    "duration": pa.float64(),
    "under_pressure": pa.bool_(),
    "counterpress": pa.bool_(),
    "off_camera": pa.bool_(),
    "out": pa.bool_(),
    # pass
    "pass.recipient": _REF,
    "pass.length": pa.float64(),
    "pass.angle": pa.float64(),
    "pass.height": _REF,
    "pass.outcome": _REF,
    "pass.body_part": _REF,
    "pass.type": _REF,
    "pass.technique": _REF,
    "pass.aerial_won": pa.bool_(),
    "pass.assisted_shot_id": pa.string(),
    "pass.cross": pa.bool_(),
    "pass.cut_back": pa.bool_(),
    "pass.deflected": pa.bool_(),
    "pass.goal_assist": pa.bool_(),
    "pass.inswinging": pa.bool_(),
    "pass.outswinging": pa.bool_(),
    "pass.straight": pa.bool_(),
    "pass.miscommunication": pa.bool_(),
    "pass.no_touch": pa.bool_(),
    "pass.shot_assist": pa.bool_(),
    "pass.switch": pa.bool_(),
    "pass.through_ball": pa.bool_(),
    # shot
    "shot.statsbomb_xg": pa.float64(),
    "shot.key_pass_id": pa.string(),
    "shot.technique": _REF,
    "shot.body_part": _REF,
    "shot.type": _REF,
    "shot.outcome": _REF,
    "shot.aerial_won": pa.bool_(),
    "shot.deflected": pa.bool_(),
    "shot.first_time": pa.bool_(),
    "shot.follows_dribble": pa.bool_(),
    "shot.one_on_one": pa.bool_(),
    "shot.open_goal": pa.bool_(),
    "shot.redirect": pa.bool_(),
    "shot.saved_off_target": pa.bool_(),
    "shot.saved_to_post": pa.bool_(),
    # carry / dribble / duel / misc on-ball
    "dribble.outcome": _REF,
    "dribble.nutmeg": pa.bool_(),
    "dribble.overrun": pa.bool_(),
    "dribble.no_touch": pa.bool_(),
    "duel.type": _REF,
    "duel.outcome": _REF,
    "ball_receipt.outcome": _REF,
    "ball_recovery.offensive": pa.bool_(),
    "ball_recovery.recovery_failure": pa.bool_(),
    "interception.outcome": _REF,
    "clearance.body_part": _REF,
    "clearance.aerial_won": pa.bool_(),
    "clearance.head": pa.bool_(),
    "clearance.left_foot": pa.bool_(),
    "clearance.right_foot": pa.bool_(),
    "clearance.other": pa.bool_(),
    "block.deflection": pa.bool_(),
    "block.offensive": pa.bool_(),
    "block.save_block": pa.bool_(),
    "miscontrol.aerial_won": pa.bool_(),
    "50_50.outcome": _REF,
    # goalkeeper
    "goalkeeper.type": _REF,
    "goalkeeper.outcome": _REF,
    "goalkeeper.position": _REF,
    "goalkeeper.technique": _REF,
    "goalkeeper.body_part": _REF,
    "goalkeeper.punched_out": pa.bool_(),
    "goalkeeper.success_in_play": pa.bool_(),
    "goalkeeper.shot_saved_off_target": pa.bool_(),
    "goalkeeper.shot_saved_to_post": pa.bool_(),
    "goalkeeper.penalty_saved_to_post": pa.bool_(),
    # discipline / stoppages
    "foul_committed.type": _REF,
    "foul_committed.card": _REF,
    "foul_committed.advantage": pa.bool_(),
    "foul_committed.offensive": pa.bool_(),
    "foul_committed.penalty": pa.bool_(),
    "foul_won.advantage": pa.bool_(),
    "foul_won.defensive": pa.bool_(),
    "foul_won.penalty": pa.bool_(),
    "bad_behaviour.card": _REF,
    "injury_stoppage.in_chain": pa.bool_(),
    "substitution.outcome": _REF,
    "substitution.replacement": _REF,
    "tactics.formation": pa.int64(),
}

# coordinate arrays: json path -> output column prefix and max dimensions
COORD_PATHS = {
    "location": ("location", 2),
    "pass.end_location": ("pass_end", 2),
    "carry.end_location": ("carry_end", 2),
    "shot.end_location": ("shot_end", 3),
    "goalkeeper.end_location": ("goalkeeper_end", 2),
}

# arrays of objects split into child tables (not flattened onto the event row)
CHILD_PATHS = {"shot.freeze_frame", "tactics.lineup", "related_events"}

# top-level booleans where "absent" means False for every event
TOP_LEVEL_FLAGS = {"under_pressure", "counterpress", "off_camera", "out"}

_AXES = "xyz"


def column_name(path: str) -> str:
    return path.replace("50_50", "fifty_fifty").replace(".", "_")


def _event_fields() -> list[pa.Field]:
    fields = [
        pa.field("match_id", pa.int64(), nullable=False),
        pa.field("competition_id", pa.int64()),
        pa.field("season_id", pa.int64()),
    ]
    for path, typ in EVENT_PATHS.items():
        col = "event_id" if path == "id" else ("event_index" if path == "index" else column_name(path))
        if typ == _REF:
            fields += [pa.field(f"{col}_id", pa.int64()), pa.field(f"{col}_name", pa.string())]
        else:
            fields.append(pa.field(col, typ))
    for prefix, dims in COORD_PATHS.values():
        fields += [pa.field(f"{prefix}_{_AXES[i]}", pa.float64()) for i in range(dims)]
    fields += [
        pa.field("timestamp_seconds", pa.float64()),
        pa.field("related_events", pa.list_(pa.string())),
        pa.field("extra_json", pa.string()),
        pa.field("_bronze_path", pa.string()),
        pa.field("_processed_at", TS),
    ]
    return fields


EVENTS = pa.schema(_event_fields())

SHOT_FREEZE_FRAMES = pa.schema(
    [
        ("match_id", pa.int64()),
        ("shot_event_id", pa.string()),
        ("player_id", pa.int64()),
        ("player_name", pa.string()),
        ("position_id", pa.int64()),
        ("position_name", pa.string()),
        ("teammate", pa.bool_()),
        ("location_x", pa.float64()),
        ("location_y", pa.float64()),
    ]
)

TACTICS_LINEUPS = pa.schema(
    [
        ("match_id", pa.int64()),
        ("event_id", pa.string()),
        ("event_type", pa.string()),
        ("team_id", pa.int64()),
        ("formation", pa.int64()),
        ("player_id", pa.int64()),
        ("player_name", pa.string()),
        ("position_id", pa.int64()),
        ("position_name", pa.string()),
        ("jersey_number", pa.int64()),
    ]
)

FRAMES_360 = pa.schema(
    [
        ("match_id", pa.int64()),
        ("event_id", pa.string()),
        ("frame_player_index", pa.int32()),
        ("teammate", pa.bool_()),
        ("actor", pa.bool_()),
        ("keeper", pa.bool_()),
        ("location_x", pa.float64()),
        ("location_y", pa.float64()),
        ("visible_area_points", pa.int32()),
    ]
)

FRAMES_360_VISIBLE_AREA = pa.schema(
    [
        ("match_id", pa.int64()),
        ("event_id", pa.string()),
        ("visible_area", pa.list_(pa.float64())),
    ]
)

LINEUPS = pa.schema(
    [
        ("match_id", pa.int64()),
        ("team_id", pa.int64()),
        ("team_name", pa.string()),
        ("player_id", pa.int64()),
        ("player_name", pa.string()),
        ("player_nickname", pa.string()),
        ("jersey_number", pa.int64()),
        ("country_id", pa.int64()),
        ("country_name", pa.string()),
        ("is_starter", pa.bool_()),
        ("appeared", pa.bool_()),
        ("seconds_played", pa.float64()),
        ("minutes_played", pa.float64()),
        ("_processed_at", TS),
    ]
)

LINEUP_POSITIONS = pa.schema(
    [
        ("match_id", pa.int64()),
        ("team_id", pa.int64()),
        ("player_id", pa.int64()),
        ("position_id", pa.int64()),
        ("position_name", pa.string()),
        ("from_clock", pa.string()),
        ("to_clock", pa.string()),
        ("from_period", pa.int64()),
        ("to_period", pa.int64()),
        ("start_reason", pa.string()),
        ("end_reason", pa.string()),
        ("seconds_played", pa.float64()),
        ("stint_corrected", pa.bool_()),
    ]
)

LINEUP_CARDS = pa.schema(
    [
        ("match_id", pa.int64()),
        ("team_id", pa.int64()),
        ("player_id", pa.int64()),
        ("card_time", pa.string()),
        ("card_type", pa.string()),
        ("reason", pa.string()),
        ("period", pa.int64()),
    ]
)

MATCHES = pa.schema(
    [
        ("match_id", pa.int64()),
        ("competition_id", pa.int64()),
        ("season_id", pa.int64()),
        ("competition_name", pa.string()),
        ("season_name", pa.string()),
        ("match_date", pa.date32()),
        ("kick_off", pa.string()),
        ("match_week", pa.int64()),
        ("competition_stage_id", pa.int64()),
        ("competition_stage_name", pa.string()),
        ("home_team_id", pa.int64()),
        ("home_team_name", pa.string()),
        ("home_team_gender", pa.string()),
        ("home_team_country", pa.string()),
        ("home_manager_id", pa.int64()),
        ("home_manager_name", pa.string()),
        ("away_team_id", pa.int64()),
        ("away_team_name", pa.string()),
        ("away_team_gender", pa.string()),
        ("away_team_country", pa.string()),
        ("away_manager_id", pa.int64()),
        ("away_manager_name", pa.string()),
        ("home_score", pa.int64()),
        ("away_score", pa.int64()),
        ("match_status", pa.string()),
        ("match_status_360", pa.string()),
        ("stadium_id", pa.int64()),
        ("stadium_name", pa.string()),
        ("stadium_country", pa.string()),
        ("referee_id", pa.int64()),
        ("referee_name", pa.string()),
        ("data_version", pa.string()),
        ("shot_fidelity_version", pa.string()),
        ("xy_fidelity_version", pa.string()),
        ("last_updated", pa.string()),
        ("last_updated_360", pa.string()),
        ("_bronze_path", pa.string()),
    ]
)

COMPETITIONS = pa.schema(
    [
        ("competition_id", pa.int64()),
        ("season_id", pa.int64()),
        ("country_name", pa.string()),
        ("competition_name", pa.string()),
        ("competition_gender", pa.string()),
        ("competition_youth", pa.bool_()),
        ("competition_international", pa.bool_()),
        ("season_name", pa.string()),
        ("match_updated", pa.string()),
        ("match_updated_360", pa.string()),
        ("match_available", pa.string()),
        ("match_available_360", pa.string()),
    ]
)
