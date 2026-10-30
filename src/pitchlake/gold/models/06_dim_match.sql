-- description: Matches with teams, result, venue, officials and data-lineage attributes
SELECT
    sk('sb:match', m.match_id)                                         AS match_key,
    m.match_id                                                         AS sb_match_id,
    CAST(strftime(m.match_date, '%Y%m%d') AS INTEGER)                  AS date_key,
    sk('sb:competition_season', m.competition_id || '_' || m.season_id) AS competition_season_key,
    sk('sb:team', m.home_team_id)                                      AS home_team_key,
    sk('sb:team', m.away_team_id)                                      AS away_team_key,
    m.match_date,
    m.kick_off,
    m.competition_stage_name                                           AS stage,
    m.match_week,
    m.home_team_name || ' v ' || m.away_team_name                      AS fixture,
    m.home_team_name || ' ' || m.home_score || '-' || m.away_score || ' ' || m.away_team_name AS fixture_result,
    m.home_score,
    m.away_score,
    CASE WHEN m.home_score > m.away_score THEN 'Home win'
         WHEN m.home_score < m.away_score THEN 'Away win' ELSE 'Draw' END AS result_90_120,
    m.stadium_name,
    m.stadium_country,
    m.referee_name,
    m.home_manager_name,
    m.away_manager_name,
    m.data_version,
    m.match_status_360 = 'available'                                   AS has_360_data,
    m.last_updated                                                     AS source_last_updated
FROM silver_matches m
WHERE m.match_status = 'available'
