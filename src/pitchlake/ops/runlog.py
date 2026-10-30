"""Run context + step instrumentation.

Every step writes its own row to ``meta.pipeline_runs`` the moment it finishes
(success *or* failure), so a crashed run still leaves an audit trail and the
monitoring report / Fabric alert can point at the exact failing step.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from pitchlake.ops import meta
from pitchlake.tables import TableStore

log = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StepMetrics(dict):
    """Mutable bag a step fills in: rows_in, rows_out + anything else."""


class RunContext:
    def __init__(
        self, store: TableStore, environment: str, trigger: str = "manual", run_id: str | None = None
    ):
        self.store = store
        self.environment = environment
        self.trigger = trigger
        self.run_id = run_id or f"{utcnow():%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
        self.steps: list[dict] = []

    @contextmanager
    def step(self, name: str):
        metrics = StepMetrics()
        started = utcnow()
        t0 = time.monotonic()
        status, error = "succeeded", None
        log.info("▶ step %s (run %s)", name, self.run_id)
        try:
            yield metrics
        except Exception as exc:
            status = "failed"
            error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}"
            raise
        finally:
            row = {
                "run_id": self.run_id,
                "step": name,
                "status": status,
                "started_at": started,
                "ended_at": utcnow(),
                "duration_s": round(time.monotonic() - t0, 3),
                "rows_in": metrics.pop("rows_in", None),
                "rows_out": metrics.pop("rows_out", None),
                "metrics_json": json.dumps(metrics, default=str),
                "error": error,
                "environment": self.environment,
                "trigger": self.trigger,
            }
            self.steps.append(row)
            try:
                self.store.write(
                    "meta", "pipeline_runs", meta.rows_to_table([row], meta.PIPELINE_RUNS), mode="append"
                )
            except Exception as log_exc:  # never let logging mask the real error
                log.error("could not persist run log: %s", log_exc)
            log.info("■ step %s %s in %.1fs %s", name, status, row["duration_s"], metrics or "")

    def summary(self) -> list[dict]:
        return [
            {k: r[k] for k in ("step", "status", "duration_s", "rows_in", "rows_out")}
            | json.loads(r["metrics_json"])
            for r in self.steps
        ]
