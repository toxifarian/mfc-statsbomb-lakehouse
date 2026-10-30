# ADR-003 · Incremental loads by per-match watermarks; atomic per-match replace

**Context.** StatsBomb revises matches long after full-time (Euro 2024 files were updated again in 2026), and 360
data arrives separately. A revision may add, change, **delete** or re-index events.

**Decision.**
1. Each run polls `competitions` and `matches` (two tiny calls per competition-season).
2. A match's events + lineups are fetched only when `last_updated` > the watermark in `meta.ingestion_state`;
   360 only when `last_updated_360` moves. A 404 on 360 is recorded so it isn't re-requested every run.
3. Watermarks advance **only** for matches whose required resources all landed — failures retry automatically.
4. Silver replaces a match **atomically** (`DELETE+INSERT` in one Delta commit via `replace_where match_id IN (…)`).

**Alternatives.** Date-window reloads (re-fetches too much, misses old revisions); row-level MERGE on event UUID
(leaves orphans when the vendor deletes events); full reloads (simple, wasteful on API quota).

**Consequences.** Steady-state run = 2 HTTP calls + ~4 s. Tested: unchanged source → zero match fetches; a
re-issued match with 10 deleted events → exactly those 10 disappear; a failed fetch → retried next run.
