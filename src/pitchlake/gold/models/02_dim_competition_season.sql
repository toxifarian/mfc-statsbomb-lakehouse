-- description: One row per competition-season available from StatsBomb
SELECT
    sk('sb:competition_season', competition_id || '_' || season_id) AS competition_season_key,
    competition_id,
    season_id,
    competition_name,
    season_name,
    competition_name || ' ' || season_name                          AS competition_season_name,
    country_name,
    competition_gender,
    competition_youth,
    competition_international,
    match_updated                                                   AS source_last_updated,
    match_available_360 IS NOT NULL                                 AS has_360_data
FROM silver_competitions
