"""Gold: Kimball star schema built from version-controlled SQL models.

Each ``models/NN_<name>.sql`` file is a single SELECT. Files run in name
order; every model can reference silver tables as ``silver_<table>``, meta
tables as ``meta_<table>`` and previously built gold models as ``gold_<name>``.

DuckDB executes the SQL in-process over the Delta tables (Arrow, zero-copy),
which keeps the same models runnable on a laptop, in CI and in a Fabric
Python notebook. The models are plain ANSI-ish SQL, so moving them to dbt
(dbt-fabric / dbt-duckdb) later is a mechanical change – see ADR-004.
"""

from __future__ import annotations

import logging
import re
from importlib import resources
from pathlib import Path

import duckdb

from pitchlake.config import Settings
from pitchlake.duck import to_arrow
from pitchlake.integration.identity import XREF_SCHEMA
from pitchlake.ops.runlog import StepMetrics
from pitchlake.sources.synthetic import CATAPULT_ATHLETES, CATAPULT_SESSIONS, TM_PLAYERS
from pitchlake.tables import TableStore

log = logging.getLogger(__name__)

MODELS_PACKAGE = "pitchlake.gold.models"

SILVER_TABLES = [
    "competitions",
    "matches",
    "events",
    "lineups",
    "lineup_positions",
    "lineup_cards",
    "shot_freeze_frames",
    "tactics_lineups",
    "xref_player",
    "catapult_athletes",
    "catapult_match_sessions",
    "transfermarkt_players",
]
META_TABLES = ["ingestion_state"]

# Other club sources are optional: gold still builds (with empty physical facts) without them
OPTIONAL_SCHEMAS = {
    "xref_player": XREF_SCHEMA,
    "catapult_athletes": CATAPULT_ATHLETES,
    "catapult_match_sessions": CATAPULT_SESSIONS,
    "transfermarkt_players": TM_PLAYERS,
}

MACROS = [
    # deterministic 60-bit surrogate key: stable across rebuilds, environments and sources
    "CREATE OR REPLACE MACRO sk(ns, id) AS "
    "CASE WHEN id IS NULL THEN -1 ELSE ('0x' || left(md5(ns || ':' || CAST(id AS VARCHAR)), 15))::BIGINT END",
    # StatsBomb pitch is 120 x 80 yards-ish units, origin top-left, attacking left->right.
    # Tracking providers (Catapult/Second Spectrum) use metres from the centre spot.
    "CREATE OR REPLACE MACRO sb_x_to_m(x) AS round((x / 120.0) * 105.0 - 52.5, 2)",
    "CREATE OR REPLACE MACRO sb_y_to_m(y) AS round(34.0 - (y / 80.0) * 68.0, 2)",
    "CREATE OR REPLACE MACRO dist_to_goal(x, y) AS sqrt(power(120 - x, 2) + power(40 - y, 2))",
]


def list_models() -> list[tuple[str, str, str]]:
    """[(model_name, description, sql)] in execution order."""
    root = Path(str(resources.files(MODELS_PACKAGE)))
    out = []
    for path in sorted(root.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        name = re.sub(r"^\d+_", "", path.stem)
        desc_match = re.search(r"--\s*description:\s*(.+)", sql)
        out.append((name, desc_match.group(1).strip() if desc_match else "", sql))
    return out


class GoldBuilder:
    def __init__(self, settings: Settings, store: TableStore):
        self.settings = settings
        self.store = store

    def _connect(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect()
        for macro in MACROS:
            con.execute(macro)
        for layer, names in (("silver", SILVER_TABLES), ("meta", META_TABLES)):
            for name in names:
                ds = self.store.dataset(layer, name)
                if ds is None:
                    schema = OPTIONAL_SCHEMAS.get(name)
                    if schema is None:
                        raise FileNotFoundError(f"gold needs {layer}.{name} – run the upstream steps first")
                    log.info("gold: optional %s.%s not present – using an empty table", layer, name)
                    con.register(f"{layer}_{name}", schema.empty_table())
                    continue
                con.register(f"{layer}_{name}", ds)
        return con

    def run(self, metrics: StepMetrics) -> StepMetrics:
        con = self._connect()
        built = {}
        for name, description, sql in list_models():
            table = to_arrow(con, sql)
            self.store.write("gold", name, table, mode="overwrite", description=description)
            con.register(f"gold_{name}", table)
            built[name] = table.num_rows
        metrics.update(rows_out=sum(built.values()), models=built)
        return metrics
