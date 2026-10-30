"""Small DuckDB helpers that work across duckdb 1.x (Fabric runtime) and 2.x."""

from __future__ import annotations

import duckdb
import pyarrow as pa


def to_arrow(con: duckdb.DuckDBPyConnection, sql: str) -> pa.Table:
    rel = con.sql(sql)
    for name in ("to_arrow_table", "fetch_arrow_table", "arrow"):  # 2.x, 1.x, 0.x naming
        if hasattr(type(rel), name):
            result = getattr(rel, name)()
            return result.read_all() if hasattr(result, "read_all") else result
    raise RuntimeError("Unsupported duckdb version")


def scalar(con: duckdb.DuckDBPyConnection, sql: str):
    rows = con.execute(sql).fetchall()  # fetchall completes the result (duckdb 2.x is strict)
    return rows[0][0] if rows else None


def records(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    # via Arrow: avoids duckdb's optional pytz dependency for tz-aware timestamps
    return to_arrow(con, sql).to_pylist()
