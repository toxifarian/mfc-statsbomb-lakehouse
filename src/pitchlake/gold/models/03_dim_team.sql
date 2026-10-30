-- description: Teams (conformed across sources) with an unknown member for team-less events
WITH teams AS (
    SELECT home_team_id AS team_id, home_team_name AS team_name, home_team_gender AS gender, home_team_country AS country, match_date
    FROM silver_matches
    UNION ALL
    SELECT away_team_id, away_team_name, away_team_gender, away_team_country, match_date
    FROM silver_matches
), latest AS (
    SELECT *, row_number() OVER (PARTITION BY team_id ORDER BY match_date DESC) AS rn FROM teams
)
SELECT sk('sb:team', team_id) AS team_key, team_id AS sb_team_id, team_name, gender, country
FROM latest WHERE rn = 1
UNION ALL
SELECT -1, NULL, 'Unknown', NULL, NULL
