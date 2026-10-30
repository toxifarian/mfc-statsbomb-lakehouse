"""Bronze: land raw source payloads, immutably, with a manifest.

Principles
----------
* **Raw and lossless.** We store the exact bytes the vendor sent. Flattening
  happens in silver, so it can be re-run (e.g. after a contract change)
  without calling the API again.
* **Immutable + versioned.** Each landing is a new file
  ``<entity>/<partition>/<key>/<ingested_at>_<sha8>.json``. StatsBomb re-issues
  matches long after full-time (Euro 2024 matches were updated again in 2026),
  so history matters for audit and reproducibility.
* **Incremental by watermark.** ``matches`` carries ``last_updated`` and
  ``last_updated_360``; a match's events/lineups/360 are only fetched when its
  watermark moves past the one stored in ``meta.ingestion_state``.
* **Idempotent.** Identical payloads (same sha256) are not re-written.
* **Failure-isolated.** A failed match does not fail the run and its watermark
  is not advanced, so it is retried automatically next run.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from pitchlake.config import Settings
from pitchlake.ops import meta
from pitchlake.ops.runlog import StepMetrics, utcnow
from pitchlake.platform import Platform
from pitchlake.sources.http import NotFound, SourceHTTPError
from pitchlake.sources.statsbomb import Resource, StatsBombSource
from pitchlake.tables import TableStore

log = logging.getLogger(__name__)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


class BronzeIngestor:
    def __init__(
        self, settings: Settings, platform: Platform, store: TableStore, source: StatsBombSource, run_id: str
    ):
        self.settings = settings
        self.platform = platform
        self.store = store
        self.source = source
        self.run_id = run_id
        self.folder = settings.lakehouse.get("bronze_folder", "bronze/statsbomb")
        manifest = store.read_or_empty("meta", "bronze_manifest", meta.BRONZE_MANIFEST).to_pylist()
        # latest successful landing per (entity, key) -> used for change detection
        self.latest: dict[tuple[str, str], dict] = {}
        for row in sorted(manifest, key=lambda r: r["ingested_at"]):
            if row["status"] in ("landed", "unchanged"):
                self.latest[(row["entity"], row["resource_key"])] = row

    # ------------------------------------------------------------------ land
    def land(self, res: Resource) -> tuple[dict, object | None]:
        """Fetch + land one resource. Returns (manifest_row, parsed_payload)."""
        now = utcnow()
        row = {
            "run_id": self.run_id,
            "source": self.source.name,
            "entity": res.entity,
            "resource_key": res.key,
            "competition_id": res.competition_id,
            "season_id": res.season_id,
            "match_id": res.match_id,
            "path": None,
            "bytes": None,
            "sha256": None,
            "record_count": None,
            "source_updated_at": res.source_updated_at,
            "ingested_at": now,
            "http_attempts": None,
            "status": "failed",
            "error": None,
        }
        try:
            resp = self.source.fetch(res)
        except NotFound as exc:
            row["status"] = "not_found" if res.optional else "failed"
            row["error"] = str(exc)
            return row, None
        except SourceHTTPError as exc:
            row["error"] = str(exc)
            return row, None

        row["http_attempts"] = resp.attempts
        row["bytes"] = len(resp.content)
        row["sha256"] = _sha256(resp.content)
        try:
            parsed = self.source.parse(resp.content)
        except json.JSONDecodeError as exc:
            row["error"] = f"invalid JSON: {exc}"
            self._quarantine(res, resp.content, row["error"])
            return row, None
        row["record_count"] = len(parsed) if isinstance(parsed, list) else 1

        previous = self.latest.get((res.entity, res.key))
        if previous and previous["sha256"] == row["sha256"]:
            row["status"], row["path"] = "unchanged", previous["path"]
            return row, parsed

        rel = f"{self.folder}/{res.entity}/{res.partition}/{res.key}/{now:%Y%m%dT%H%M%S%fZ}_{row['sha256'][:8]}.json"
        _atomic_write(self.platform.files_path(rel), resp.content)
        row["path"], row["status"] = rel, "landed"
        return row, parsed

    def _quarantine(self, res: Resource, content: bytes, error: str) -> None:
        rel = f"quarantine/{self.source.name}/{res.entity}/{res.key}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.bin"
        _atomic_write(self.platform.files_path(rel), content)
        self.store.write(
            "meta",
            "quarantine",
            meta.rows_to_table(
                [
                    {
                        "run_id": self.run_id,
                        "entity": res.entity,
                        "resource_key": res.key,
                        "path": rel,
                        "error": error,
                        "quarantined_at": utcnow(),
                    }
                ],
                meta.QUARANTINE,
            ),
            mode="append",
        )

    # ------------------------------------------------------------------- plan
    def plan_match_resources(
        self, matches: list[dict], state: dict[int, dict], full_refresh: bool, only_match_ids: set[int] | None
    ) -> tuple[list[Resource], dict[int, dict]]:
        entities = self.settings.statsbomb.get("entities", {})
        planned: list[Resource] = []
        touched: dict[int, dict] = {}
        candidates = sorted(matches, key=lambda m: (m.get("match_date") or "", m["match_id"]))
        limit = self.settings.statsbomb.get("max_matches_per_run")

        for m in candidates:
            mid = m["match_id"]
            if only_match_ids and mid not in only_match_ids:
                continue
            if m.get("match_status") not in (None, "available"):
                continue
            prev = state.get(mid)
            need_core = (
                full_refresh or prev is None or (m.get("last_updated") or "") > (prev["last_updated"] or "")
            )
            has_360 = m.get("match_status_360") == "available"
            need_360 = (
                bool(entities.get("frames_360", True))
                and has_360
                and (
                    full_refresh
                    or prev is None
                    or (m.get("last_updated_360") or "") > (prev["last_updated_360"] or "")
                )
            )
            if not (need_core or need_360):
                continue
            if limit and len(touched) >= limit:
                break
            touched[mid] = m
            if need_core:
                for ent in ("lineups", "events"):
                    if entities.get(ent, True):
                        planned.append(self.source.match_resource(ent, m))
            if need_360:
                planned.append(self.source.match_resource("frames_360", m))
        return planned, touched

    # -------------------------------------------------------------------- run
    def run(
        self, metrics: StepMetrics, full_refresh: bool = False, match_ids: list[int] | None = None
    ) -> dict:
        manifest_rows: list[dict] = []

        # 1. competitions (tiny – always refreshed, validates scope)
        comp_row, competitions = self.land(self.source.competitions_resource())
        manifest_rows.append(comp_row)
        if competitions is None:
            self._flush(manifest_rows)
            raise RuntimeError(f"Could not fetch competitions: {comp_row['error']}")
        available = {(c["competition_id"], c["season_id"]): c for c in competitions}

        # 2. matches per scoped competition-season
        all_matches: list[dict] = []
        for scope in self.settings.statsbomb.get("scope", []):
            key = (scope["competition_id"], scope["season_id"])
            comp = available.get(key)
            if comp is None:
                log.error("Scope %s (%s) is not available from the source – skipped", key, scope.get("label"))
                continue
            row, matches = self.land(self.source.matches_resource(*key, updated_at=comp.get("match_updated")))
            manifest_rows.append(row)
            if matches:
                all_matches.extend(matches)

        # 3. decide which match-level resources changed since last run
        state_rows = self.store.read_or_empty("meta", "ingestion_state", meta.INGESTION_STATE).to_pylist()
        state = {r["match_id"]: r for r in state_rows}
        planned, touched = self.plan_match_resources(
            all_matches, state, full_refresh, set(match_ids) if match_ids else None
        )
        log.info(
            "bronze plan: %s matches in scope, %s new/changed, %s resources to fetch",
            len(all_matches),
            len(touched),
            len(planned),
        )

        # 4. fetch in parallel (bounded) – per-resource failure isolation
        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=self.source.max_concurrency) as pool:
            futures = {pool.submit(self.land, r): r for r in planned}
            for fut in as_completed(futures):
                row, _ = fut.result()
                results.append(row)
        manifest_rows.extend(results)

        # 5. advance watermarks only for matches whose required resources all succeeded
        by_match: dict[int, list[dict]] = {}
        for r in results:
            by_match.setdefault(r["match_id"], []).append(r)
        now = utcnow()
        new_state, failed_matches = [], []
        for mid, rows in by_match.items():
            if any(r["status"] == "failed" for r in rows):
                failed_matches.append(mid)
                continue
            m, prev = touched[mid], state.get(mid) or {}
            got_360 = any(
                r["entity"] == "frames_360" and r["status"] in ("landed", "unchanged") for r in rows
            )
            # a 404 on 360 is recorded against the watermark too: we only ask again when the vendor
            # bumps last_updated_360, instead of re-requesting a missing file every run
            tried_360 = got_360 or any(
                r["entity"] == "frames_360" and r["status"] == "not_found" for r in rows
            )
            new_state.append(
                {
                    "match_id": mid,
                    "competition_id": m["competition"]["competition_id"],
                    "season_id": m["season"]["season_id"],
                    "last_updated": m.get("last_updated"),
                    "last_updated_360": m.get("last_updated_360")
                    if tried_360
                    else prev.get("last_updated_360"),
                    "has_360": got_360 or bool(prev.get("has_360")),
                    "bronze_ingested_at": now,
                    "silver_processed_at": prev.get("silver_processed_at"),
                }
            )

        self._flush(manifest_rows)
        if new_state:
            self.store.merge(
                "meta",
                "ingestion_state",
                meta.rows_to_table(new_state, meta.INGESTION_STATE),
                keys=["match_id"],
            )

        status_counts: dict[str, int] = {}
        for r in manifest_rows:
            status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
        metrics.update(
            {
                "rows_in": len(planned),
                "rows_out": sum(1 for r in manifest_rows if r["status"] == "landed"),
                "matches_in_scope": len(all_matches),
                "matches_changed": len(touched),
                "matches_failed": len(failed_matches),
                "bytes_landed": sum(r["bytes"] or 0 for r in manifest_rows if r["status"] == "landed"),
                "status_counts": status_counts,
            }
        )
        if failed_matches:
            log.warning(
                "%s matches failed and will be retried next run: %s", len(failed_matches), failed_matches[:10]
            )
        return metrics

    def _flush(self, rows: list[dict]) -> None:
        if rows:
            self.store.write(
                "meta", "bronze_manifest", meta.rows_to_table(rows, meta.BRONZE_MANIFEST), mode="append"
            )
