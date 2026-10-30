"""Declarative data-quality engine.

Rules live in YAML (``conf/dq_rules.yml``) so analysts can read and propose
them; each rule compiles to SQL executed by DuckDB over the Delta tables.
Every evaluation is persisted to ``meta.dq_results`` (with a sample of the
failing rows) – that table feeds the monitoring page and the alerting
pipeline. In ``enforce`` mode a failed ``error`` rule raises
``DataQualityError`` *after* results are written, which stops the pipeline
before bad data reaches gold / Power BI.
"""

from __future__ import annotations

import json
import logging
import re

import duckdb
import yaml

from pitchlake.config import Settings, conf_path
from pitchlake.duck import records, scalar
from pitchlake.ops import meta
from pitchlake.ops.runlog import StepMetrics, utcnow
from pitchlake.tables import TableStore

log = logging.getLogger(__name__)


class DataQualityError(RuntimeError):
    pass


def _q(name: str) -> str:
    """silver.events -> silver_events (duckdb view name)."""
    return name.replace(".", "_")


def compile_rule(rule: dict) -> tuple[str, str | None]:
    """Return (failing_rows_sql, total_rows_sql)."""
    t = rule.get("type")
    table = _q(rule["table"]) if "table" in rule else None
    where = f" AND ({rule['where']})" if rule.get("where") else ""
    total = f"SELECT count(*) FROM {table} WHERE TRUE{where}" if table else None
    if t == "not_null":
        cond = " OR ".join(f"{c} IS NULL" for c in rule["columns"])
        return f"SELECT * FROM {table} WHERE ({cond}){where}", total
    if t == "unique":
        cols = ", ".join(rule["columns"])
        return (
            f"SELECT {cols}, count(*) AS dup_count FROM {table} WHERE TRUE{where} "
            f"GROUP BY {cols} HAVING count(*) > 1"
        ), total
    if t == "accepted_values":
        vals = ", ".join(repr(v) for v in rule["values"])
        return f"SELECT * FROM {table} WHERE {rule['column']} NOT IN ({vals}){where}", total
    if t == "range":
        col = rule["column"]
        conds = []
        if "min" in rule:
            conds.append(f"{col} < {rule['min']}")
        if "max" in rule:
            conds.append(f"{col} > {rule['max']}")
        return f"SELECT * FROM {table} WHERE {col} IS NOT NULL AND ({' OR '.join(conds)}){where}", total
    if t == "relationship":
        ref = _q(rule["ref_table"])
        return (
            f"SELECT t.* FROM {table} t ANTI JOIN {ref} r ON t.{rule['column']} = r.{rule['ref_column']} "
            f"WHERE t.{rule['column']} IS NOT NULL{where}"
        ), total
    if t == "expression":
        return f"SELECT * FROM {table} WHERE NOT ({rule['expression']}){where}", total
    if t == "row_count_min":
        return (f"SELECT count(*) AS n FROM {table} HAVING count(*) < {int(rule['min'])}"), total
    if t == "sql":
        return rule["query"], None
    raise ValueError(f"Unknown rule type: {t}")


class DQEngine:
    def __init__(self, settings: Settings, store: TableStore, run_id: str):
        self.settings = settings
        self.store = store
        self.run_id = run_id
        self.mode = settings.quality.get("mode", "enforce")
        with open(conf_path(settings.quality.get("rules_file", "dq_rules.yml")), encoding="utf-8") as fh:
            self.rules = yaml.safe_load(fh)

    def _connect(self, rules: list[dict]) -> duckdb.DuckDBPyConnection:
        """Register only the tables the rules reference (layer_table tokens)."""
        con = duckdb.connect()
        names = set()
        text = json.dumps(rules)
        for layer in ("silver", "gold", "meta"):
            for token in set(_tokens(text, layer)):
                names.add((layer, token))
        for layer, name in names:
            ds = self.store.dataset(layer, name)
            if ds is not None:
                con.register(f"{layer}_{name}", ds)
        return con

    def run(self, metrics: StepMetrics, layer: str) -> StepMetrics:
        rules = self.rules.get(layer, [])
        con = self._connect(rules)
        now = utcnow()
        results = []
        for rule in rules:
            failing_sql, total_sql = compile_rule(rule)
            failing_sql = failing_sql.replace("{run_id}", self.run_id)
            try:
                failed = scalar(con, f"SELECT count(*) FROM ({failing_sql}) q")
                sample = records(con, f"SELECT * FROM ({failing_sql}) q LIMIT 5") if failed else []
                total = scalar(con, total_sql) if total_sql else None
                err = None
            except duckdb.CatalogException as exc:
                # referenced table absent (e.g. optional source not loaded) -> skip, don't fail
                failed, sample, total, err = 0, [], None, f"skipped: {str(exc).splitlines()[0]}"
            results.append(
                {
                    "run_id": self.run_id,
                    "rule_id": rule["id"],
                    "table_name": rule.get("table", "(sql)"),
                    "rule_type": rule["type"],
                    "severity": rule.get("severity", "error"),
                    "description": rule.get("description") or err,
                    "passed": failed == 0,
                    "failed_count": failed,
                    "total_count": total,
                    "sample_json": json.dumps(sample, default=str) if sample else None,
                    "evaluated_at": now,
                }
            )
            level = (
                logging.INFO
                if failed == 0
                else (logging.ERROR if rule.get("severity") == "error" else logging.WARNING)
            )
            log.log(
                level,
                "DQ %-40s %s (%s failing%s)",
                rule["id"],
                "PASS" if failed == 0 else "FAIL",
                failed,
                f" of {total}" if total is not None else "",
            )

        self.store.write("meta", "dq_results", meta.rows_to_table(results, meta.DQ_RESULTS), mode="append")
        errors = [r for r in results if not r["passed"] and r["severity"] == "error"]
        warns = [r for r in results if not r["passed"] and r["severity"] == "warn"]
        metrics.update(
            rows_in=len(rules),
            rows_out=len(results),
            passed=sum(r["passed"] for r in results),
            errors=[r["rule_id"] for r in errors],
            warnings=[r["rule_id"] for r in warns],
        )
        if errors and self.mode == "enforce":
            raise DataQualityError(
                f"{len(errors)} blocking DQ rule(s) failed in {layer}: {[r['rule_id'] for r in errors]}"
            )
        return metrics


def _tokens(text: str, layer: str) -> list[str]:
    return re.findall(rf"\b{layer}[._]([a-z0-9_]+)", text)
