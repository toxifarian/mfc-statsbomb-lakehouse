-- description: One row per pass with completion, progression and chance-creation flags
WITH shots AS (
    SELECT event_id, shot_statsbomb_xg, shot_outcome_name FROM silver_events WHERE type_name = 'Shot'
)
SELECT
    p.event_id                                     AS pass_id,
    sk('sb:match', p.match_id)                     AS match_key,
    CAST(strftime(m.match_date, '%Y%m%d') AS INTEGER) AS date_key,
    sk('sb:team', p.team_id)                       AS team_key,
    sk('sb:player', p.player_id)                   AS player_key,
    sk('sb:player', p.pass_recipient_id)           AS recipient_player_key,
    p.period, p.minute, p.second,
    p.play_pattern_name                            AS play_pattern,
    p.pass_height_name                             AS height,
    p.pass_body_part_name                          AS body_part,
    coalesce(p.pass_type_name, 'Open Play')        AS pass_type,
    coalesce(p.pass_outcome_name, 'Complete')      AS outcome,
    p.pass_outcome_name IS NULL                    AS is_complete,      -- StatsBomb: no outcome == completed
    p.pass_length                                  AS length,
    p.pass_angle                                   AS angle,
    p.location_x, p.location_y, p.pass_end_x AS end_x, p.pass_end_y AS end_y,
    p.under_pressure,
    -- progressive: completed open-play pass that moves the ball >= 25% closer to goal centre
    (p.pass_outcome_name IS NULL AND p.pass_type_name IS NULL AND p.location_x >= 40
        AND dist_to_goal(p.pass_end_x, p.pass_end_y) <= 0.75 * dist_to_goal(p.location_x, p.location_y)) AS is_progressive,
    (p.pass_outcome_name IS NULL AND p.location_x < 80 AND p.pass_end_x >= 80)                         AS is_into_final_third,
    (p.pass_outcome_name IS NULL AND p.pass_end_x >= 102 AND p.pass_end_y BETWEEN 18 AND 62
        AND NOT (p.location_x >= 102 AND p.location_y BETWEEN 18 AND 62))                                 AS is_into_box,
    p.pass_cross                                   AS is_cross,
    p.pass_switch                                  AS is_switch,
    p.pass_through_ball                            AS is_through_ball,
    p.pass_shot_assist OR p.pass_goal_assist       AS is_key_pass,
    p.pass_goal_assist                             AS is_assist,
    coalesce(s.shot_statsbomb_xg, 0)               AS xa                -- xG of the shot this pass created
FROM silver_events p
JOIN silver_matches m USING (match_id)
LEFT JOIN shots s ON s.event_id = p.pass_assisted_shot_id
WHERE p.type_name = 'Pass'
