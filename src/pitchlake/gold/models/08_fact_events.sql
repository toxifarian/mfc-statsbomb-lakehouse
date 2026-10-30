-- description: One row per StatsBomb event (all types) – the atomic grain for ad-hoc analysis
SELECT
    e.event_id,
    sk('sb:match', e.match_id)                  AS match_key,
    CAST(strftime(m.match_date, '%Y%m%d') AS INTEGER) AS date_key,
    sk('sb:team', e.team_id)                    AS team_key,
    sk('sb:team', e.possession_team_id)         AS possession_team_key,
    sk('sb:player', e.player_id)                AS player_key,
    sk('sb:position', e.position_id)            AS position_key,
    sk('sb:event_type', e.type_id)              AS event_type_key,
    e.event_index,
    e.period,
    e.minute,
    e.second,
    e.timestamp_seconds,
    e.possession,
    e.play_pattern_name                         AS play_pattern,
    e.location_x, e.location_y,
    coalesce(e.pass_end_x, e.carry_end_x, e.shot_end_x, e.goalkeeper_end_x) AS end_x,
    coalesce(e.pass_end_y, e.carry_end_y, e.shot_end_y, e.goalkeeper_end_y) AS end_y,
    sb_x_to_m(e.location_x)                     AS location_x_m,   -- tracking-compatible metres
    sb_y_to_m(e.location_y)                     AS location_y_m,
    e.duration,
    e.under_pressure,
    e.counterpress,
    coalesce(e.pass_outcome_name, e.shot_outcome_name, e.dribble_outcome_name, e.duel_outcome_name,
             e.interception_outcome_name, e.goalkeeper_outcome_name, e.fifty_fifty_outcome_name,
             e.ball_receipt_outcome_name,
             CASE WHEN e.type_name = 'Pass' THEN 'Complete' END)     AS outcome,
    e.shot_statsbomb_xg                         AS xg,
    e.period = 5                                AS is_penalty_shootout
FROM silver_events e
JOIN silver_matches m USING (match_id)
