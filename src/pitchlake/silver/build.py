"""Silver: typed, conformed, contract-checked Delta tables.

Unit of work = one match. Pending matches are those whose bronze landing is
newer than their last silver processing (``meta.ingestion_state``), so silver
can be re-run independently of bronze (e.g. after a contract change, run with
``full_refresh`` and no API calls are made).

Each batch of matches is written with ``replace_where match_id IN (...)`` – an
atomic swap per match, which correctly handles StatsBomb deleting or
re-indexing events when it re-issues a match.
"""

from __future__ import annotations

import json
import logging
from collections import Counter

import pyarrow as pa

from pitchlake.config import Settings
from pitchlake.ops import meta
from pitchlake.ops.runlog import StepMetrics, utcnow
from pitchlake.platform import Platform
from pitchlake.silver import contracts as c
from pitchlake.silver import flatten as f
from pitchlake.tables import TableStore

log = logging.getLogger(__name__)

BATCH_SIZE = 20


def _tbl(rows: list[dict], schema: pa.Schema) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=schema)


class SilverBuilder:
    def __init__(self, settings: Settings, platform: Platform, store: TableStore, run_id: str):
        self.settings, self.platform, self.store, self.run_id = settings, platform, store, run_id

    # ------------------------------------------------------------ bronze IO
    def _latest_paths(self) -> dict[tuple[str, str], str]:
        manifest = self.store.read_or_empty("meta", "bronze_manifest", meta.BRONZE_MANIFEST).to_pylist()
        latest: dict[tuple[str, str], tuple] = {}
        for r in manifest:
            if r["status"] not in ("landed", "unchanged") or not r["path"]:
                continue
            k = (r["entity"], r["resource_key"])
            if k not in latest or r["ingested_at"] > latest[k][0]:
                latest[k] = (r["ingested_at"], r["path"])
        return {k: v[1] for k, v in latest.items()}

    def _load(self, rel_path: str):
        with open(self.platform.files_path(rel_path), "rb") as fh:
            return json.loads(fh.read())

    # ------------------------------------------------------------------ run
    def run(self, metrics: StepMetrics, full_refresh: bool = False) -> StepMetrics:
        now = utcnow()
        paths = self._latest_paths()

        # --- reference entities: small, rebuilt every run
        comps = self._load(paths[("competitions", "competitions")])
        self.store.write("silver", "competitions", _tbl(f.flatten_competitions(comps), c.COMPETITIONS))

        # every competition-season ever landed (scope controls ingestion, not retention)
        match_rows, match_lookup = [], {}
        for (entity, _key), p in sorted(paths.items()):
            if entity != "matches":
                continue
            raw = self._load(p)
            match_rows.extend(f.flatten_matches(raw, p))
            match_lookup.update({m["match_id"]: m for m in raw})
        self.store.write("silver", "matches", _tbl(match_rows, c.MATCHES))

        # --- match-level entities: incremental
        state = self.store.read_or_empty("meta", "ingestion_state", meta.INGESTION_STATE).to_pylist()
        pending = [
            s
            for s in state
            if s["match_id"] in match_lookup
            and (
                full_refresh
                or s["silver_processed_at"] is None
                or s["silver_processed_at"] < s["bronze_ingested_at"]
            )
        ]
        log.info("silver: %s matches pending", len(pending))

        drift: Counter = Counter()
        drift_example: dict[str, int] = {}
        totals = Counter()
        done_state = []
        for i in range(0, len(pending), BATCH_SIZE):
            batch = pending[i : i + BATCH_SIZE]
            buf: dict[str, list] = {
                k: []
                for k in ("events", "freeze", "tactics", "lineups", "positions", "cards", "frames", "areas")
            }
            ok_ids = []
            for s in batch:
                mid = s["match_id"]
                ev_path = paths.get(("events", str(mid)))
                if not ev_path:
                    log.warning("match %s has no events in bronze – skipped", mid)
                    continue
                events = self._load(ev_path)
                before = Counter(drift)
                ev, fz, tac = f.flatten_events(
                    events, mid, s["competition_id"], s["season_id"], ev_path, now, drift
                )
                for k in drift - before:
                    drift_example.setdefault(k, mid)
                buf["events"] += ev
                buf["freeze"] += fz
                buf["tactics"] += tac
                bounds = f.period_bounds(events)
                lu_path = paths.get(("lineups", str(mid)))
                if lu_path:
                    pl, pos, cards = f.flatten_lineups(self._load(lu_path), mid, bounds, now)
                    buf["lineups"] += pl
                    buf["positions"] += pos
                    buf["cards"] += cards
                fr_path = paths.get(("frames_360", str(mid)))
                if fr_path and s.get("has_360"):
                    fr, ar = f.flatten_frames_360(self._load(fr_path), mid)
                    buf["frames"] += fr
                    buf["areas"] += ar
                ok_ids.append(mid)
            if not ok_ids:
                continue
            where = f"match_id IN ({', '.join(str(m) for m in ok_ids)})"
            for table, key, schema in (
                ("events", "events", c.EVENTS),
                ("shot_freeze_frames", "freeze", c.SHOT_FREEZE_FRAMES),
                ("tactics_lineups", "tactics", c.TACTICS_LINEUPS),
                ("lineups", "lineups", c.LINEUPS),
                ("lineup_positions", "positions", c.LINEUP_POSITIONS),
                ("lineup_cards", "cards", c.LINEUP_CARDS),
                ("frames_360", "frames", c.FRAMES_360),
                ("frames_360_visible_area", "areas", c.FRAMES_360_VISIBLE_AREA),
            ):
                self.store.write("silver", table, _tbl(buf[key], schema), replace_where=where)
                totals[table] += len(buf[key])
            for s in batch:
                if s["match_id"] in ok_ids:
                    done_state.append(dict(s, silver_processed_at=utcnow()))
            log.info(
                "silver batch %s-%s: %s matches, %s events",
                i,
                i + len(batch),
                len(ok_ids),
                len(buf["events"]),
            )

        if done_state:
            self.store.merge(
                "meta", "ingestion_state", _tbl(done_state, meta.INGESTION_STATE), keys=["match_id"]
            )
        if drift:
            log.warning(
                "schema drift: %s unknown JSON paths – preserved in extra_json: %s",
                len(drift),
                list(drift)[:10],
            )
            self.store.write(
                "meta",
                "schema_drift",
                _tbl(
                    [
                        {
                            "run_id": self.run_id,
                            "entity": "events",
                            "json_path": k,
                            "occurrences": v,
                            "example_match_id": drift_example.get(k),
                            "detected_at": now,
                        }
                        for k, v in drift.items()
                    ],
                    meta.SCHEMA_DRIFT,
                ),
                mode="append",
            )

        metrics.update(
            {
                "rows_in": len(pending),
                "rows_out": totals["events"],
                "matches_processed": len(done_state),
                "table_rows": dict(totals),
                "drift_paths": len(drift),
            }
        )
        return metrics
