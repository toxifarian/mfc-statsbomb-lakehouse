-- description: Event types grouped into analysis categories
SELECT
    sk('sb:event_type', type_id) AS event_type_key,
    type_id,
    any_value(type_name)         AS event_type,
    CASE
        WHEN any_value(type_name) IN ('Pass', 'Ball Receipt*', 'Carry', 'Dribble', 'Shot', 'Miscontrol', 'Dispossessed') THEN 'In possession'
        WHEN any_value(type_name) IN ('Pressure', 'Duel', 'Interception', 'Block', 'Clearance', 'Ball Recovery', 'Dribbled Past', '50/50', 'Shield') THEN 'Out of possession'
        WHEN any_value(type_name) IN ('Goal Keeper') THEN 'Goalkeeping'
        WHEN any_value(type_name) IN ('Foul Committed', 'Foul Won', 'Bad Behaviour', 'Offside', 'Error', 'Own Goal Against', 'Own Goal For') THEN 'Discipline & errors'
        ELSE 'Match administration'
    END                          AS event_category
FROM silver_events
GROUP BY type_id
