-- description: StatsBomb positions with a coaching-friendly position group and line
WITH p AS (
    SELECT DISTINCT position_id, position_name FROM silver_lineup_positions WHERE position_id IS NOT NULL
    UNION
    SELECT DISTINCT position_id, position_name FROM silver_events WHERE position_id IS NOT NULL
)
SELECT
    sk('sb:position', position_id) AS position_key,
    position_id,
    any_value(position_name)       AS position_name,
    CASE WHEN position_id = 1 THEN 'Goalkeeper'
         WHEN position_id BETWEEN 2 AND 8 THEN 'Defender'
         WHEN position_id IN (17, 21) OR position_id BETWEEN 22 AND 25 THEN 'Forward'
         ELSE 'Midfielder' END     AS position_group,
    CASE WHEN position_id = 1 THEN 1 WHEN position_id BETWEEN 2 AND 8 THEN 2
         WHEN position_id IN (17, 21) OR position_id BETWEEN 22 AND 25 THEN 4 ELSE 3 END AS position_group_sort
FROM p
GROUP BY position_id
UNION ALL
SELECT -1, NULL, 'Unknown', 'Unknown', 9
