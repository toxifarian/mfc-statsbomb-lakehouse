/* ---------------------------------------------------------------------------
   Analyst-friendly views on the lakehouse SQL analytics endpoint (T-SQL).
   Run against: lh_football (SQL analytics endpoint). Views are read-only and
   pick up new data automatically – no copies.
--------------------------------------------------------------------------- */
CREATE SCHEMA analyst;
GO

/* Player season summary with per-90 rates (recruitment / opposition scouting) */
CREATE OR ALTER VIEW analyst.vw_player_season AS
SELECT
    p.display_name,
    p.latest_team,
    p.primary_position_group,
    cs.competition_season_name,
    COUNT(*)                                             AS appearances,
    SUM(f.minutes_played)                                AS minutes,
    SUM(f.goals)                                         AS goals,
    CAST(SUM(f.xg) AS DECIMAL(9,2))                      AS xg,
    CAST(SUM(f.xa) AS DECIMAL(9,2))                      AS xa,
    CAST(SUM(f.npxg) * 90.0 / NULLIF(SUM(f.minutes_played), 0) AS DECIMAL(9,2)) AS npxg_per90,
    CAST(SUM(f.xa)   * 90.0 / NULLIF(SUM(f.minutes_played), 0) AS DECIMAL(9,2)) AS xa_per90,
    CAST(SUM(f.progressive_passes) * 90.0 / NULLIF(SUM(f.minutes_played), 0) AS DECIMAL(9,2)) AS prog_passes_per90,
    CAST(SUM(f.pressures) * 90.0 / NULLIF(SUM(f.minutes_played), 0) AS DECIMAL(9,2)) AS pressures_per90
FROM gold.fact_player_match f
JOIN gold.dim_player p ON p.player_key = f.player_key
JOIN gold.dim_match  m ON m.match_key  = f.match_key
JOIN gold.dim_competition_season cs ON cs.competition_season_key = m.competition_season_key
GROUP BY p.display_name, p.latest_team, p.primary_position_group, cs.competition_season_name;
GO

/* Shot map feed (coach-facing visuals, Python/R notebooks) */
CREATE OR ALTER VIEW analyst.vw_shots AS
SELECT m.fixture_result, m.match_date, t.team_name, p.display_name AS player, s.minute, s.xg, s.outcome,
       s.is_goal, s.body_part, s.play_pattern, s.assist_type, s.location_x, s.location_y, s.distance_to_goal,
       s.goal_angle_deg, s.defenders_in_shot_cone
FROM gold.fact_shots s
JOIN gold.dim_match  m ON m.match_key  = s.match_key
JOIN gold.dim_team   t ON t.team_key   = s.team_key
JOIN gold.dim_player p ON p.player_key = s.player_key
WHERE s.is_penalty_shootout = 0;
GO

/* Physical x technical: one row per player-match where both sources exist */
CREATE OR ALTER VIEW analyst.vw_player_match_load AS
SELECT m.match_date, m.fixture_result, p.display_name, f.minutes_played, ph.total_distance_m, ph.hsr_distance_m,
       ph.sprint_efforts, ph.max_speed_kmh, f.pressures, f.progressive_carries, f.touches, ph.is_synthetic
FROM gold.fact_player_match f
JOIN gold.fact_player_match_physical ph ON ph.match_key = f.match_key AND ph.player_key = f.player_key
JOIN gold.dim_player p ON p.player_key = f.player_key
JOIN gold.dim_match  m ON m.match_key  = f.match_key;
GO

/* Team form table */
CREATE OR ALTER VIEW analyst.vw_team_form AS
SELECT t.team_name, cs.competition_season_name, COUNT(*) AS played, SUM(tm.points) AS points,
       SUM(tm.goals_for) AS gf, SUM(tm.goals_against) AS ga,
       CAST(SUM(tm.xg) AS DECIMAL(9,2)) AS xg, CAST(SUM(tm.xg_against) AS DECIMAL(9,2)) AS xga,
       CAST(AVG(tm.possession_pct) AS DECIMAL(5,1)) AS avg_possession_pct, CAST(AVG(tm.ppda) AS DECIMAL(6,2)) AS avg_ppda
FROM gold.fact_team_match tm
JOIN gold.dim_team t ON t.team_key = tm.team_key
JOIN gold.dim_match m ON m.match_key = tm.match_key
JOIN gold.dim_competition_season cs ON cs.competition_season_key = m.competition_season_key
GROUP BY t.team_name, cs.competition_season_name;
GO
