-- description: Players with cross-system identifiers (Catapult, Transfermarkt) from the governed xref
WITH appearances AS (
    SELECT l.*, m.match_date,
           row_number() OVER (PARTITION BY l.player_id ORDER BY m.match_date DESC, l.match_id DESC) AS rn
    FROM silver_lineups l
    JOIN silver_matches m USING (match_id)
), primary_pos AS (
    SELECT player_id, position_id,
           row_number() OVER (PARTITION BY player_id ORDER BY sum(seconds_played) DESC) AS rn
    FROM silver_lineup_positions
    GROUP BY player_id, position_id
), xref AS (
    SELECT sb_player_id,
           max(source_id) FILTER (WHERE source_system = 'catapult')      AS catapult_athlete_id,
           max(source_id) FILTER (WHERE source_system = 'transfermarkt') AS transfermarkt_player_id,
           min(match_score)                                              AS min_link_score
    FROM silver_xref_player
    WHERE status IN ('auto', 'manual')
    GROUP BY sb_player_id
)
SELECT
    sk('sb:player', a.player_id)                     AS player_key,
    a.player_id                                      AS sb_player_id,
    a.player_name                                    AS full_name,
    coalesce(a.player_nickname, a.player_name)       AS display_name,
    a.country_name                                   AS nationality,
    a.team_name                                      AS latest_team,
    a.jersey_number                                  AS latest_jersey_number,
    dp.position_name                                 AS primary_position,
    dp.position_group                                AS primary_position_group,
    x.catapult_athlete_id,
    TRY_CAST(x.transfermarkt_player_id AS BIGINT)   AS transfermarkt_player_id,
    x.catapult_athlete_id IS NOT NULL                AS has_gps_data,
    x.min_link_score
FROM appearances a
LEFT JOIN primary_pos pp ON pp.player_id = a.player_id AND pp.rn = 1
LEFT JOIN gold_dim_position dp ON dp.position_id = pp.position_id
LEFT JOIN xref x ON x.sb_player_id = a.player_id
WHERE a.rn = 1
UNION ALL
SELECT -1, NULL, 'Unknown', 'Unknown', NULL, NULL, NULL, NULL, NULL, NULL, NULL, FALSE, NULL
