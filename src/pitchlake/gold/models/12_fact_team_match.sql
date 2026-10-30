-- description: Team x match summary incl. possession share and PPDA (pressing intensity)
WITH ev AS (SELECT * FROM silver_events WHERE period < 5),
teams AS (
    SELECT match_id, home_team_id AS team_id, away_team_id AS opp_id, home_score AS gf, away_score AS ga, TRUE AS is_home FROM silver_matches
    UNION ALL
    SELECT match_id, away_team_id, home_team_id, away_score, home_score, FALSE FROM silver_matches
), poss AS (
    SELECT match_id, possession_team_id AS team_id, sum(coalesce(duration, 0)) AS poss_s
    FROM ev WHERE type_name IN ('Pass','Carry','Ball Receipt*','Dribble','Shot') GROUP BY ALL
), shots AS (
    SELECT match_id, team_id, count(*) AS shots, sum(shot_statsbomb_xg) AS xg,
           sum(shot_statsbomb_xg) FILTER (WHERE shot_type_name <> 'Penalty') AS npxg,
           count(*) FILTER (WHERE lower(shot_outcome_name) IN ('goal','saved','saved to post')) AS shots_on_target
    FROM ev WHERE type_name = 'Shot' GROUP BY ALL
), passes AS (
    SELECT match_id, team_id, count(*) AS passes, count(*) FILTER (WHERE pass_outcome_name IS NULL) AS passes_completed,
           -- passes in own defensive 60% (StatsBomb normalises every team to attack left->right)
           count(*) FILTER (WHERE location_x <= 72) AS passes_own_60pct
    FROM ev WHERE type_name = 'Pass' AND coalesce(pass_type_name, 'Open Play') IN ('Open Play', 'Recovery', 'Interception') GROUP BY ALL
), def_actions AS (
    -- defensive actions in the opponent's 60% of the pitch (x >= 48 from the defending team's view)
    SELECT match_id, team_id, count(*) AS def_actions_high
    FROM ev
    WHERE location_x >= 48 AND (type_name IN ('Interception', 'Foul Committed') OR (type_name = 'Duel' AND duel_type_name = 'Tackle'))
    GROUP BY ALL
)
SELECT
    sk('sb:match', t.match_id)                     AS match_key,
    CAST(strftime(m.match_date, '%Y%m%d') AS INTEGER) AS date_key,
    sk('sb:team', t.team_id)                       AS team_key,
    sk('sb:team', t.opp_id)                        AS opponent_team_key,
    t.is_home,
    t.gf AS goals_for, t.ga AS goals_against,
    CASE WHEN t.gf > t.ga THEN 'W' WHEN t.gf < t.ga THEN 'L' ELSE 'D' END AS result,
    CASE WHEN t.gf > t.ga THEN 3 WHEN t.gf = t.ga THEN 1 ELSE 0 END      AS points,
    coalesce(s.shots, 0) AS shots, coalesce(s.shots_on_target, 0) AS shots_on_target,
    round(coalesce(s.xg, 0), 3) AS xg, round(coalesce(so.xg, 0), 3) AS xg_against,
    round(coalesce(s.npxg, 0), 3) AS npxg,
    coalesce(p.passes, 0) AS open_play_passes, coalesce(p.passes_completed, 0) AS open_play_passes_completed,
    round(100.0 * po.poss_s / nullif(po.poss_s + coalesce(pp.poss_s, 0), 0), 1)   AS possession_pct,
    round(coalesce(po2.passes_own_60pct, 0) / nullif(d.def_actions_high, 0), 2)     AS ppda
FROM teams t
JOIN silver_matches m ON m.match_id = t.match_id
LEFT JOIN shots s ON s.match_id = t.match_id AND s.team_id = t.team_id
LEFT JOIN shots so ON so.match_id = t.match_id AND so.team_id = t.opp_id
LEFT JOIN passes p ON p.match_id = t.match_id AND p.team_id = t.team_id
LEFT JOIN passes po2 ON po2.match_id = t.match_id AND po2.team_id = t.opp_id
LEFT JOIN def_actions d ON d.match_id = t.match_id AND d.team_id = t.team_id
LEFT JOIN poss po ON po.match_id = t.match_id AND po.team_id = t.team_id
LEFT JOIN poss pp ON pp.match_id = t.match_id AND pp.team_id = t.opp_id
WHERE m.match_status = 'available'
  AND t.match_id IN (SELECT DISTINCT match_id FROM silver_events)   -- only matches whose events are loaded
