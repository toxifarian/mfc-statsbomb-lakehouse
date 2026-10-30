-- description: Player x match performance summary (the main grain for coaching & recruitment reporting)
WITH ev AS (
    SELECT * FROM silver_events WHERE period < 5 AND player_id IS NOT NULL
), agg AS (
    SELECT
        match_id, player_id, any_value(team_id) AS team_id,
        count(*) FILTER (WHERE type_name IN ('Pass','Carry','Dribble','Shot','Ball Receipt*','Miscontrol','Clearance','Interception','Ball Recovery','Block','Duel')) AS touches,
        count(*) FILTER (WHERE type_name = 'Shot')                                              AS shots,
        count(*) FILTER (WHERE type_name = 'Shot' AND lower(shot_outcome_name) IN ('goal','saved','saved to post')) AS shots_on_target,
        count(*) FILTER (WHERE type_name = 'Shot' AND shot_outcome_name = 'Goal')               AS goals,
        count(*) FILTER (WHERE type_name = 'Shot' AND shot_outcome_name = 'Goal' AND shot_type_name <> 'Penalty') AS non_penalty_goals,
        coalesce(sum(shot_statsbomb_xg), 0)                                                     AS xg,
        coalesce(sum(shot_statsbomb_xg) FILTER (WHERE shot_type_name <> 'Penalty'), 0)          AS npxg,
        count(*) FILTER (WHERE type_name = 'Pass')                                              AS passes_attempted,
        count(*) FILTER (WHERE type_name = 'Pass' AND pass_outcome_name IS NULL)                AS passes_completed,
        count(*) FILTER (WHERE pass_shot_assist OR pass_goal_assist)                            AS key_passes,
        count(*) FILTER (WHERE pass_goal_assist)                                                AS assists,
        count(*) FILTER (WHERE type_name = 'Carry')                                             AS carries,
        count(*) FILTER (WHERE type_name = 'Carry' AND carry_end_x - location_x >= 10 AND location_x >= 40) AS progressive_carries,
        count(*) FILTER (WHERE type_name = 'Dribble')                                           AS dribbles_attempted,
        count(*) FILTER (WHERE type_name = 'Dribble' AND dribble_outcome_name = 'Complete')    AS dribbles_completed,
        count(*) FILTER (WHERE type_name = 'Pressure')                                          AS pressures,
        count(*) FILTER (WHERE type_name = 'Pressure' AND location_x >= 80)                     AS final_third_pressures,
        count(*) FILTER (WHERE type_name = 'Duel' AND duel_type_name = 'Tackle')                AS tackles,
        count(*) FILTER (WHERE type_name = 'Duel' AND duel_type_name = 'Tackle' AND duel_outcome_name IN ('Won','Success In Play','Success Out')) AS tackles_won,
        count(*) FILTER (WHERE type_name = 'Interception')                                      AS interceptions,
        count(*) FILTER (WHERE type_name = 'Ball Recovery' AND NOT coalesce(ball_recovery_recovery_failure, FALSE)) AS ball_recoveries,
        count(*) FILTER (WHERE type_name = 'Clearance')                                         AS clearances,
        count(*) FILTER (WHERE type_name = 'Block')                                             AS blocks,
        count(*) FILTER (WHERE type_name = 'Foul Committed')                                    AS fouls_committed,
        count(*) FILTER (WHERE type_name = 'Foul Won')                                          AS fouls_won,
        count(*) FILTER (WHERE type_name IN ('Miscontrol','Dispossessed'))                      AS turnovers
    FROM ev
    GROUP BY match_id, player_id
), passes AS (
    SELECT match_key, player_key, sum(xa) AS xa, count(*) FILTER (WHERE is_progressive) AS progressive_passes,
           count(*) FILTER (WHERE is_into_box) AS passes_into_box
    FROM gold_fact_passes GROUP BY ALL
), cards AS (
    SELECT match_id, player_id,
           count(*) FILTER (WHERE card_type = 'Yellow Card')                       AS yellow_cards,
           count(*) FILTER (WHERE card_type IN ('Red Card', 'Second Yellow'))      AS red_cards
    FROM silver_lineup_cards GROUP BY ALL
)
SELECT
    sk('sb:match', l.match_id)                         AS match_key,
    CAST(strftime(m.match_date, '%Y%m%d') AS INTEGER)  AS date_key,
    sk('sb:player', l.player_id)                       AS player_key,
    sk('sb:team', l.team_id)                           AS team_key,
    sk('sb:team', CASE WHEN l.team_id = m.home_team_id THEN m.away_team_id ELSE m.home_team_id END) AS opponent_team_key,
    l.is_starter,
    l.minutes_played,
    coalesce(a.touches, 0) AS touches, coalesce(a.shots, 0) AS shots, coalesce(a.shots_on_target, 0) AS shots_on_target,
    coalesce(a.goals, 0) AS goals, coalesce(a.non_penalty_goals, 0) AS non_penalty_goals,
    round(coalesce(a.xg, 0), 4) AS xg, round(coalesce(a.npxg, 0), 4) AS npxg, round(coalesce(p.xa, 0), 4) AS xa,
    coalesce(a.assists, 0) AS assists, coalesce(a.key_passes, 0) AS key_passes,
    coalesce(a.passes_attempted, 0) AS passes_attempted, coalesce(a.passes_completed, 0) AS passes_completed,
    coalesce(p.progressive_passes, 0) AS progressive_passes, coalesce(p.passes_into_box, 0) AS passes_into_box,
    coalesce(a.carries, 0) AS carries, coalesce(a.progressive_carries, 0) AS progressive_carries,
    coalesce(a.dribbles_attempted, 0) AS dribbles_attempted, coalesce(a.dribbles_completed, 0) AS dribbles_completed,
    coalesce(a.pressures, 0) AS pressures, coalesce(a.final_third_pressures, 0) AS final_third_pressures,
    coalesce(a.tackles, 0) AS tackles, coalesce(a.tackles_won, 0) AS tackles_won,
    coalesce(a.interceptions, 0) AS interceptions, coalesce(a.ball_recoveries, 0) AS ball_recoveries,
    coalesce(a.clearances, 0) AS clearances, coalesce(a.blocks, 0) AS blocks,
    coalesce(a.fouls_committed, 0) AS fouls_committed, coalesce(a.fouls_won, 0) AS fouls_won,
    coalesce(a.turnovers, 0) AS turnovers,
    coalesce(c.yellow_cards, 0) AS yellow_cards, coalesce(c.red_cards, 0) AS red_cards
FROM silver_lineups l
JOIN silver_matches m USING (match_id)
LEFT JOIN agg a ON a.match_id = l.match_id AND a.player_id = l.player_id
LEFT JOIN passes p ON p.match_key = sk('sb:match', l.match_id) AND p.player_key = sk('sb:player', l.player_id)
LEFT JOIN cards c ON c.match_id = l.match_id AND c.player_id = l.player_id
WHERE l.appeared
