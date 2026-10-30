-- description: Calendar dimension covering every match date (+/- 1 year) for time intelligence
WITH bounds AS (
    SELECT min(match_date) - INTERVAL 365 DAY AS d0, max(match_date) + INTERVAL 365 DAY AS d1 FROM silver_matches
)
SELECT
    CAST(strftime(d, '%Y%m%d') AS INTEGER)              AS date_key,
    CAST(d AS DATE)                                     AS date,
    year(d)                                             AS year,
    quarter(d)                                          AS quarter,
    month(d)                                            AS month_number,
    strftime(d, '%B')                                   AS month_name,
    strftime(d, '%Y-%m')                                AS year_month,
    dayofweek(d)                                        AS day_of_week_number,
    strftime(d, '%A')                                   AS day_name,
    -- football seasons run Jul -> Jun
    CASE WHEN month(d) >= 7 THEN year(d) || '/' || right(CAST(year(d) + 1 AS VARCHAR), 2)
         ELSE (year(d) - 1) || '/' || right(CAST(year(d) AS VARCHAR), 2) END AS football_season
FROM bounds, generate_series(d0, d1, INTERVAL 1 DAY) AS t(d)
