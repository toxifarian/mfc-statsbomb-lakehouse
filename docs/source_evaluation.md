# 1 · Evaluating the source: StatsBomb

> "How do you approach an unfamiliar data source?" — before designing anything, profile the real data.
> Everything below was measured on the **UEFA Euro 2024** open-data release (51 matches, with 360)
> using `fabric/notebooks/nb_00_explore_statsbomb.ipynb` and ad-hoc scripts, on 29 Oct 2026.

## What StatsBomb provides

| Entity | Endpoint (licensed API) | Open-data path | Grain | Notes |
|---|---|---|---|---|
| Competitions | `/api/v4/competitions` | `competitions.json` | competition × season | carries `match_updated`, `match_available_360` → cheap change signal |
| Matches | `/api/v6/competitions/{c}/seasons/{s}/matches` | `matches/{c}/{s}.json` | match | `last_updated`, `last_updated_360`, data/fidelity versions, stage, venue, officials, managers |
| Lineups | `/api/v5/lineups/{match}` | `lineups/{match}.json` | team → player → positions[] / cards[] | no DOB or external IDs in open data |
| Events | `/api/v11/events/{match}` | `events/{match}.json` | event (UUID) | the core: 33 event types, deeply nested, sparse |
| 360 frames | `/api/v2/360-frames/{match}` | `three-sixty/{match}.json` | event → visible players | freeze-frame of visible players + camera polygon |
| Aggregates | player/team match & season stats | – | – | licensed only; we derive our own (transparent, reproducible) |

The licensed API also exposes `/api/endpoint-versions` (incl. an `api_player_mapping` key) — we pin versions
explicitly and use that endpoint to **detect** new versions (`pitchlake check-api`) rather than auto-upgrade.

## Volumes (Euro 2024, 51 matches)

| | raw JSON | records | per match |
|---|---|---|---|
| events | 160 MB | 187,924 | 3,685 (min 2,880 · max 5,195) |
| 360 frames | 399 MB | 164,530 frames → 2.7 M player positions | ~3,200 frames |
| lineups | 1.2 MB | 2,587 player-matches | |
| **Delta (silver, zstd parquet)** | **76 MB** | | ~7× smaller than JSON |

A Premier League season (380 matches) is therefore ≈ 1.4 M events / ~4 GB raw with 360 —
**small data** for a lakehouse: it fits comfortably in a single-node Python process (see ADR-002).

## Shape & semantics — the things that bite

| # | Finding | Consequence in the design |
|---|---|---|
| 1 | **151 distinct JSON paths** across 33 event types; each event carries only its own sub-object (`pass`, `shot`, `carry`, …) | explicit silver contract (typed columns) + `extra_json` for anything unknown |
| 2 | **Optional keys are omitted, not null**. A pass with no `outcome` is *complete*; absent booleans mean `False` | normalised in silver (flags default to `False` only where applicable); `is_complete` derived in gold |
| 3 | `{id, name}` reference objects everywhere | split into `_id` / `_name`; ids drive dimensions |
| 4 | Coordinate arrays vary: `shot.end_location` is 2-D (467) or 3-D (873) | fixed x/y/z columns, z nullable |
| 5 | 120 × 80 pitch units, origin top-left, **every team attacks left→right** | SQL macros convert to metres-from-centre for tracking/GPS integration |
| 6 | Event `timestamp` restarts each period; periods 3–4 = extra time, **5 = penalty shoot-out** | shoot-outs excluded from xG/goals/minutes; flagged on shots |
| 7 | **Lineup stints for extra-time matches are chained in string order of the clock** (`"105:00" < "65:08"`) → naive minutes = 286 for a 133-minute match | stints re-chained by (period, clock) and clipped at the real exit (the sub-off / red card is often attached to the wrong stint); 117 corrections flagged `stint_corrected`; DQ warn + an error rule that team minutes ≤ 11 × match length; raise with vendor |
| 8 | **A coordinate of x = 120.1** exists (a shot on the goal line) | two-tier DQ: impossible values = error, boundary noise = warn |
| 9 | **Data is revised long after the match**: Euro 2024 files carry `last_updated` from **May 2026** | watermark-based incremental reloads per match; immutable bronze history |
| 10 | Revisions can *remove or re-index* events | silver replaces a whole match atomically (`replace_where`), never row-merges |
| 11 | 360 is published separately and later (`last_updated_360`), not for every event (~82% of events in a sampled match) and not for every competition | independent watermark; 404 on 360 is a valid state |
| 12 | Older/other competitions contain fields not in Euro 2024 (e.g. `pass.backheel` in FA WSL 2018/19) | schema drift detected, logged to `meta.schema_drift`, preserved — demonstrated live |
| 13 | Players carry full legal names (`"Álvaro Borja Morata Martín"`) + nickname; **no DOB / cross-provider IDs** in open data | identity resolution service (fuzzy + review + overrides); ask StatsBomb about the player-mapping endpoint |
| 14 | `statsbombpy` returns `[]` on *any* non-200 (401, 429, 503…) | our client raises; a silent empty load is the worst failure mode |
| 15 | `formation` encoded as int (`3412`), related events as UUID arrays | kept as-is in silver; related events usable for possession chains |

## Data contract & licence considerations

* **Licence**: open data is under the StatsBomb Open Data user agreement (attribution required); the club's
  licensed feed will have its own terms (competitions, redistribution, retention). Licence scope is captured in
  config (`scope`) and data is never committed to Git.
* **Personal data**: events identify players (names, performance) → personal data under UK GDPR (see
  [governance](governance.md)).
* **SLA questions for the vendor**: publication latency after full-time, revision policy & notification,
  rate limits, endpoint deprecation policy, availability of the player-mapping endpoint.

## Evaluation verdict

Rich, well-structured, *moderately* nested JSON, modest volume, **frequently revised**, with a handful of real
quality quirks. That favours: raw immutable landing → contract-driven flattening → per-match atomic replace →
strong DQ → a conformed star schema. Spark is not required at this scale.
