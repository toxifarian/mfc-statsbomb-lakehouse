"""Schemas for the operational ``meta`` tables.

These tables make the platform observable and auditable:

  meta.pipeline_runs     one row per step per run (status, duration, row counts, error)
  meta.bronze_manifest   every file landed: where, hash, size, source timestamp
  meta.ingestion_state   per-match watermarks driving incremental loads
  meta.dq_results        every data-quality rule evaluation
  meta.schema_drift      JSON paths seen in the source that the contract doesn't know
  meta.quarantine        payloads that could not be parsed/processed
"""

import pyarrow as pa

TS = pa.timestamp("us", tz="UTC")

PIPELINE_RUNS = pa.schema(
    [
        ("run_id", pa.string()),
        ("step", pa.string()),
        ("status", pa.string()),
        ("started_at", TS),
        ("ended_at", TS),
        ("duration_s", pa.float64()),
        ("rows_in", pa.int64()),
        ("rows_out", pa.int64()),
        ("metrics_json", pa.string()),
        ("error", pa.string()),
        ("environment", pa.string()),
        ("trigger", pa.string()),
    ]
)

BRONZE_MANIFEST = pa.schema(
    [
        ("run_id", pa.string()),
        ("source", pa.string()),
        ("entity", pa.string()),
        ("resource_key", pa.string()),
        ("competition_id", pa.int64()),
        ("season_id", pa.int64()),
        ("match_id", pa.int64()),
        ("path", pa.string()),
        ("bytes", pa.int64()),
        ("sha256", pa.string()),
        ("record_count", pa.int64()),
        ("source_updated_at", pa.string()),
        ("ingested_at", TS),
        ("http_attempts", pa.int32()),
        ("status", pa.string()),  # landed | unchanged | not_found | failed
        ("error", pa.string()),
    ]
)

INGESTION_STATE = pa.schema(
    [
        ("match_id", pa.int64()),
        ("competition_id", pa.int64()),
        ("season_id", pa.int64()),
        ("last_updated", pa.string()),
        ("last_updated_360", pa.string()),
        ("has_360", pa.bool_()),
        ("bronze_ingested_at", TS),
        ("silver_processed_at", TS),
    ]
)

DQ_RESULTS = pa.schema(
    [
        ("run_id", pa.string()),
        ("rule_id", pa.string()),
        ("table_name", pa.string()),
        ("rule_type", pa.string()),
        ("severity", pa.string()),
        ("description", pa.string()),
        ("passed", pa.bool_()),
        ("failed_count", pa.int64()),
        ("total_count", pa.int64()),
        ("sample_json", pa.string()),
        ("evaluated_at", TS),
    ]
)

SCHEMA_DRIFT = pa.schema(
    [
        ("run_id", pa.string()),
        ("entity", pa.string()),
        ("json_path", pa.string()),
        ("occurrences", pa.int64()),
        ("example_match_id", pa.int64()),
        ("detected_at", TS),
    ]
)

QUARANTINE = pa.schema(
    [
        ("run_id", pa.string()),
        ("entity", pa.string()),
        ("resource_key", pa.string()),
        ("path", pa.string()),
        ("error", pa.string()),
        ("quarantined_at", TS),
    ]
)


def rows_to_table(rows: list[dict], schema: pa.Schema) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=schema)
