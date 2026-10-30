-- description: Catapult GPS match load per player x match, conformed to StatsBomb player & match keys via the identity xref
WITH links AS (
    SELECT source_id AS athlete_id, sb_player_id
    FROM silver_xref_player
    WHERE source_system = 'catapult' AND status IN ('auto', 'manual')
), player_matches AS (
    SELECT l.player_id, l.match_id, m.match_date
    FROM silver_lineups l JOIN silver_matches m USING (match_id)
    WHERE l.appeared
)
SELECT
    sk('sb:match', pm.match_id)                    AS match_key,
    CAST(strftime(s.session_date, '%Y%m%d') AS INTEGER) AS date_key,
    sk('sb:player', k.sb_player_id)                AS player_key,
    s.session_id,
    s.duration_min,
    s.total_distance_m,
    s.hsr_distance_m,
    s.sprint_distance_m,
    s.sprint_efforts,
    s.max_speed_kmh,
    s.accelerations,
    s.decelerations,
    s.player_load,
    round(s.total_distance_m / nullif(s.duration_min, 0), 1) AS metres_per_minute,
    s.is_synthetic
FROM silver_catapult_match_sessions s
JOIN links k ON k.athlete_id = s.athlete_id
-- a GPS session is attributed to the match the player appeared in on that date
JOIN player_matches pm ON pm.player_id = k.sb_player_id AND pm.match_date = s.session_date
WHERE s.session_type = 'Match'
