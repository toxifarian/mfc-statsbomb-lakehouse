# ADR-006 · Governed player identity cross-reference

**Context.** StatsBomb, Catapult, Transfermarkt, VALD, Kitman and Second Spectrum each have their own player IDs
and spellings ("Jude Victor William Bellingham" / "J. Bellingham" / "BELLINGHAM, Jude"). Open-data lineups have no
DOB. Joining on names silently drops or duplicates players — the classic integration failure.

**Decision.** A dedicated integration step writes `silver.xref_player(sb_player_id, source_system, source_id,
score, method, status)`:
normalise (accents, punctuation, "Surname, Forename") → block (same squad / nationality) → score (token-sort/
token-set/ratio vs full name *and* nickname, initial+surname rule, jersey bonus) → greedy 1:1 assignment →
`auto` (≥ 90) / `review` (75–90) / `unmatched`. **Manual overrides** in a version-controlled CSV (with approver)
always win. Only `auto`/`manual` links reach gold; `dim_player` carries `catapult_athlete_id`,
`transfermarkt_player_id`.

**Consequences.** Demonstrated: 25/26 Catapult athletes auto-linked, 1 surname-only record ("Stones") correctly held
for review rather than guessed; DQ enforces 1:1 links. In production: add DOB and the vendor player-mapping
endpoint as deterministic match keys first, fuzzy second; master the club squad list as the golden record.
