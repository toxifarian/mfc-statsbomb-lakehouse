# Data model

![star schema](diagrams/data_model.png)

Full column-level reference: [data_dictionary.md](data_dictionary.md).

## Facts and grains

| Fact | Grain | Key measures | Typical consumer |
|---|---|---|---|
| `fact_events` | one StatsBomb event | location (units + metres), outcome, xG | analysts, data science |
| `fact_shots` | one shot | xG, npxG, goal/on-target, distance, angle, **defenders in shot cone** (from freeze-frame), assist type | coaches, recruitment |
| `fact_passes` | one pass | complete, progressive, into final third/box, key pass, **xA** | analysts |
| `fact_player_match` | player × match | minutes (rebuilt), goals, xG, xA, progressive actions, pressures, tackles… | coaches, recruitment, execs |
| `fact_team_match` | team × match | goals, xG/xGA, possession %, **PPDA** | coaches, opposition analysis |
| `fact_player_match_physical` | player × match (Catapult) | distance, HSR, sprints, top speed, load | performance staff |

## Conformed dimensions
`dim_player` (with `catapult_athlete_id`, `transfermarkt_player_id` from the identity xref), `dim_team`,
`dim_match`, `dim_date` (with football season), `dim_competition_season`, `dim_position` (position groups),
`dim_event_type` (categories). Unknown member `-1` on every dimension.

## Metric definitions (agreed with analysts, single source in SQL/DAX)
* **Minutes played** — rebuilt from lineup stints in true time order, extra time included, shoot-out excluded.
* **npxG** — xG excluding penalties. **xA** — xG of the shot a pass directly assisted.
* **Progressive pass** — completed open-play pass from x ≥ 40 that ends ≥ 25 % closer to the centre of goal.
* **PPDA** — opponent open-play passes in their own 60 % ÷ our tackles + interceptions + fouls in that zone.
* **Possession %** — share of on-ball event duration by possession team.
* **Defenders in shot cone** — opponents (excl. GK) inside the triangle shot location → both posts.

## Star schema (Mermaid)

```mermaid
erDiagram
    dim_date ||--o{ dim_match : date_key
    dim_competition_season ||--o{ dim_match : competition_season_key
    dim_match ||--o{ fact_player_match : match_key
    dim_player ||--o{ fact_player_match : player_key
    dim_team ||--o{ fact_player_match : team_key
    dim_match ||--o{ fact_player_match_physical : match_key
    dim_player ||--o{ fact_player_match_physical : player_key
    dim_match ||--o{ fact_team_match : match_key
    dim_team ||--o{ fact_team_match : team_key
    dim_match ||--o{ fact_shots : match_key
    dim_player ||--o{ fact_shots : player_key
    dim_match ||--o{ fact_passes : match_key
    dim_player ||--o{ fact_passes : player_key
    dim_match ||--o{ fact_events : match_key
    dim_player ||--o{ fact_events : player_key
    dim_event_type ||--o{ fact_events : event_type_key
    dim_position ||--o{ fact_events : position_key
```
