"""Delta Lake table IO (delta-rs), platform-agnostic.

Write patterns used by the framework:

* ``overwrite``           full rebuild (gold dimensions/facts)
* ``replace_where``       atomic replace of a slice, e.g. ``match_id IN (...)``.
                          This is how silver handles StatsBomb re-issuing a
                          match: the whole match is swapped in one commit, so
                          events deleted upstream disappear too (a row-level
                          MERGE would leave orphans behind).
* ``append``              logs (run log, DQ results)
* ``merge``               keyed upsert for small state tables (watermarks, xref)
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Sequence

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake
from deltalake.exceptions import TableNotFoundError

from pitchlake.platform import Platform

log = logging.getLogger(__name__)

_WRITE_PARAMS = set(inspect.signature(write_deltalake).parameters)


def _compat_kwargs(**kwargs) -> dict:
    """deltalake < 1.0 needs engine='rust' for predicates/schema evolution."""
    if "engine" in _WRITE_PARAMS:
        kwargs["engine"] = "rust"
    return {k: v for k, v in kwargs.items() if v is not None}


class TableStore:
    def __init__(self, platform: Platform):
        self.platform = platform

    # ---------------------------------------------------------------- helpers
    def uri(self, layer: str, name: str) -> str:
        return self.platform.table_uri(layer, name)

    def _dt(self, layer: str, name: str) -> DeltaTable | None:
        try:
            return DeltaTable(self.uri(layer, name), storage_options=self.platform.storage_options())
        except (TableNotFoundError, FileNotFoundError, OSError):
            return None
        except Exception as exc:  # deltalake raises generic errors for missing tables on some versions
            # be narrow: treating an auth/network error as "missing" could make a
            # replace_where write fall back to a full overwrite
            if (
                "not a Delta table" in str(exc)
                or "No such file" in str(exc)
                or "no log files" in str(exc).lower()
            ):
                return None
            raise

    def exists(self, layer: str, name: str) -> bool:
        return self._dt(layer, name) is not None

    # ------------------------------------------------------------------ reads
    def read(self, layer: str, name: str, columns: Sequence[str] | None = None) -> pa.Table:
        dt = self._dt(layer, name)
        if dt is None:
            raise FileNotFoundError(f"Delta table {layer}.{name} does not exist")
        return dt.to_pyarrow_table(columns=list(columns) if columns else None)

    def read_or_empty(self, layer: str, name: str, schema: pa.Schema | None = None) -> pa.Table:
        dt = self._dt(layer, name)
        if dt is None:
            return schema.empty_table() if schema is not None else pa.table({})
        return dt.to_pyarrow_table()

    def dataset(self, layer: str, name: str):
        dt = self._dt(layer, name)
        return None if dt is None else dt.to_pyarrow_dataset()

    def version(self, layer: str, name: str) -> int | None:
        dt = self._dt(layer, name)
        return None if dt is None else dt.version()

    def fingerprint(self, layer: str, name: str) -> str | None:
        """Version + last-commit time: a cache key that also changes if a table is dropped and recreated."""
        dt = self._dt(layer, name)
        if dt is None:
            return None
        last = dt.history(1)
        return f"{dt.version()}:{last[0].get('timestamp') if last else ''}"

    # ----------------------------------------------------------------- writes
    def write(
        self,
        layer: str,
        name: str,
        data: pa.Table,
        mode: str = "overwrite",
        replace_where: str | None = None,
        partition_by: Sequence[str] | None = None,
        description: str | None = None,
    ) -> int:
        """Write an Arrow table. Returns rows written."""
        uri = self.uri(layer, name)
        exists = self.exists(layer, name)
        predicate = replace_where if (replace_where and exists) else None
        if replace_where and not exists:
            mode = "overwrite"
        kwargs = _compat_kwargs(
            mode=mode,
            predicate=predicate,
            # full rebuilds replace the schema (dropped columns disappear); slices/appends evolve it
            schema_mode=("overwrite" if mode == "overwrite" and not predicate else "merge")
            if exists
            else None,
            partition_by=list(partition_by) if partition_by and not exists else None,
            description=description if not exists else None,
            storage_options=self.platform.storage_options(),
        )
        write_deltalake(uri, data, **kwargs)
        log.info(
            "delta write %s.%s mode=%s rows=%s%s",
            layer,
            name,
            mode,
            data.num_rows,
            f" where {predicate[:80]}" if predicate else "",
        )
        return data.num_rows

    def merge(self, layer: str, name: str, data: pa.Table, keys: Sequence[str]) -> int:
        """Upsert on business keys (small tables only)."""
        dt = self._dt(layer, name)
        if dt is None:
            return self.write(layer, name, data, mode="overwrite")
        predicate = " AND ".join(f"t.{k} = s.{k}" for k in keys)
        (
            dt.merge(source=data, predicate=predicate, source_alias="s", target_alias="t")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute()
        )
        log.info("delta merge %s.%s rows=%s keys=%s", layer, name, data.num_rows, list(keys))
        return data.num_rows

    # ------------------------------------------------------------ maintenance
    def optimize_and_vacuum(self, layer: str, name: str, retention_hours: int = 168) -> dict:
        dt = self._dt(layer, name)
        if dt is None:
            return {}
        metrics = dt.optimize.compact()
        dt.vacuum(retention_hours=retention_hours, dry_run=False, enforce_retention_duration=False)
        return {
            "table": f"{layer}.{name}",
            "files_removed": metrics.get("numFilesRemoved"),
            "files_added": metrics.get("numFilesAdded"),
        }
