-- description: One row per shot with xG, context and shot-geometry features (shoot-outs flagged)
WITH ff AS (
    -- opponents inside the triangle ball -> posts (120,36) & (120,44): "defenders in the way"
    SELECT f.shot_event_id,
           count(*) FILTER (WHERE NOT f.teammate)                                  AS opponents_in_frame,
           count(*) FILTER (WHERE NOT f.teammate AND f.position_name <> 'Goalkeeper' AND (
               ((120 - s.location_x) * (f.location_y - s.location_y) - (36 - s.location_y) * (f.location_x - s.location_x)) *
               ((120 - s.location_x) * (f.location_y - s.location_y) - (44 - s.location_y) * (f.location_x - s.location_x)) <= 0
               AND f.location_x >= s.location_x))                                  AS defenders_in_shot_cone
    FROM silver_shot_freeze_frames f
    JOIN silver_events s ON s.event_id = f.shot_event_id
    GROUP BY f.shot_event_id
), assists AS (
    SELECT pass_assisted_shot_id AS shot_id, event_id AS assist_event_id, player_id AS assister_id,
           CASE WHEN pass_cross THEN 'Cross' WHEN pass_through_ball THEN 'Through ball'
                WHEN pass_cut_back THEN 'Cut back' ELSE coalesce(pass_type_name, 'Open play pass') END AS assist_type
    FROM silver_events
    WHERE pass_assisted_shot_id IS NOT NULL
)
SELECT
    s.event_id                                       AS shot_id,
    sk('sb:match', s.match_id)                       AS match_key,
    CAST(strftime(m.match_date, '%Y%m%d') AS INTEGER) AS date_key,
    sk('sb:team', s.team_id)                         AS team_key,
    sk('sb:team', CASE WHEN s.team_id = m.home_team_id THEN m.away_team_id ELSE m.home_team_id END) AS opponent_team_key,
    sk('sb:player', s.player_id)                     AS player_key,
    sk('sb:player', a.assister_id)                   AS assist_player_key,
    s.period, s.minute, s.second,
    s.play_pattern_name                              AS play_pattern,
    s.shot_type_name                                 AS shot_type,
    s.shot_outcome_name                              AS outcome,
    s.shot_body_part_name                            AS body_part,
    s.shot_technique_name                            AS technique,
    s.shot_statsbomb_xg                              AS xg,
    CASE WHEN s.shot_type_name = 'Penalty' THEN 0 ELSE s.shot_statsbomb_xg END AS npxg,
    s.shot_outcome_name = 'Goal'                     AS is_goal,
    lower(s.shot_outcome_name) IN ('goal', 'saved', 'saved to post') AS is_on_target,
    s.shot_type_name = 'Penalty'                     AS is_penalty,
    s.period = 5                                     AS is_penalty_shootout,
    s.shot_first_time                                AS is_first_time,
    s.shot_one_on_one                                AS is_one_on_one,
    s.under_pressure,
    s.location_x, s.location_y,
    s.shot_end_x AS end_x, s.shot_end_y AS end_y, s.shot_end_z AS end_z,
    round(dist_to_goal(s.location_x, s.location_y), 2) AS distance_to_goal,
    -- visible goal-mouth angle in degrees
    round(degrees(abs(atan2(44 - s.location_y, 120 - s.location_x) - atan2(36 - s.location_y, 120 - s.location_x))), 2) AS goal_angle_deg,
    s.location_x >= 102 AND s.location_y BETWEEN 18 AND 62 AS is_in_box,
    a.assist_type,
    ff.opponents_in_frame,
    ff.defenders_in_shot_cone
FROM silver_events s
JOIN silver_matches m USING (match_id)
LEFT JOIN assists a ON a.shot_id = s.event_id
LEFT JOIN ff ON ff.shot_event_id = s.event_id
WHERE s.type_name = 'Shot'
