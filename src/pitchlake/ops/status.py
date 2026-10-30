"""Human-readable operational status (CLI `pitchlake status`)."""

from __future__ import annotations

import duckdb

from pitchlake.tables import TableStore


def status_report(store: TableStore) -> str:
    con = duckdb.connect()
    lines = []
    for name in ("pipeline_runs", "ingestion_state", "dq_results", "bronze_manifest", "schema_drift"):
        ds = store.dataset("meta", name)
        if ds is not None:
            con.register(name, ds)
    tables = {r[0] for r in con.sql("SHOW TABLES").fetchall()}

    if "pipeline_runs" in tables:
        lines.append("== Last 10 step executions ==")
        lines.append(
            str(
                con.sql("""
            SELECT run_id, step, status, round(duration_s,1) AS secs, rows_in, rows_out, left(error, 60) AS error
            FROM pipeline_runs ORDER BY started_at DESC LIMIT 10""")
            )
        )
    if "ingestion_state" in tables:
        lines.append("== Watermarks ==")
        lines.append(
            str(
                con.sql("""
            SELECT competition_id, season_id, count(*) AS matches, count(*) FILTER (WHERE has_360) AS with_360,
                   max(last_updated) AS max_source_updated, max(bronze_ingested_at) AS last_bronze,
                   count(*) FILTER (WHERE silver_processed_at IS NULL OR silver_processed_at < bronze_ingested_at)
                       AS silver_pending
            FROM ingestion_state GROUP BY ALL""")
            )
        )
    if "bronze_manifest" in tables:
        lines.append("== Bronze landings by entity ==")
        lines.append(
            str(
                con.sql("""
            SELECT entity, status, count(*) AS files, round(sum(bytes)/1e6,1) AS mb
            FROM bronze_manifest GROUP BY ALL ORDER BY 1, 2""")
            )
        )
    if "dq_results" in tables:
        lines.append("== Latest DQ results ==")
        lines.append(
            str(
                con.sql("""
            WITH last AS (SELECT max(run_id) AS run_id FROM dq_results)
            SELECT rule_id, severity, passed, failed_count, total_count
            FROM dq_results JOIN last USING (run_id) ORDER BY passed, severity, rule_id""")
            )
        )
    if "schema_drift" in tables:
        lines.append("== Schema drift (all time) ==")
        lines.append(
            str(
                con.sql("""
            SELECT entity, json_path, sum(occurrences) AS occurrences, min(detected_at) AS first_seen
            FROM schema_drift GROUP BY ALL ORDER BY occurrences DESC LIMIT 20""")
            )
        )
    return "\n".join(lines) if lines else "No runs yet."
