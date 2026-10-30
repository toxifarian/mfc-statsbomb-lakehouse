import pyarrow as pa
import pytest

from pitchlake.config import load_settings
from pitchlake.platform import LocalPlatform
from pitchlake.quality.engine import DataQualityError, DQEngine
from pitchlake.tables import TableStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PITCHLAKE_ROOT", str(tmp_path))
    return TableStore(LocalPlatform(load_settings("local")))


def test_full_overwrite_replaces_schema(store):
    store.write("gold", "t", pa.table({"a": [1], "old_col": ["x"]}))
    store.write("gold", "t", pa.table({"a": [2]}))
    assert store.read("gold", "t").column_names == ["a"]  # dropped columns don't linger as nulls


def test_replace_where_evolves_schema_and_keeps_other_slices(store):
    store.write("silver", "t", pa.table({"match_id": [1, 2], "v": [1, 2]}))
    store.write(
        "silver", "t", pa.table({"match_id": [1], "v": [9], "new": ["n"]}), replace_where="match_id IN (1)"
    )
    rows = sorted(store.read("silver", "t").to_pylist(), key=lambda r: r["match_id"])
    assert rows == [{"match_id": 1, "v": 9, "new": "n"}, {"match_id": 2, "v": 2, "new": None}]


def test_dq_missing_table_fails_unless_optional(store):
    settings = load_settings("local")
    engine = DQEngine(settings, store, "run-1")
    engine.rules = {
        "silver": [
            {
                "id": "needs_table",
                "type": "not_null",
                "table": "silver.nope",
                "columns": ["x"],
                "severity": "error",
            },
            {
                "id": "optional_one",
                "type": "sql",
                "query": "SELECT * FROM silver_nope",
                "severity": "warn",
                "optional": True,
            },
        ]
    }
    with pytest.raises(DataQualityError):
        engine.run({}, layer="silver")
    res = {r["rule_id"]: r for r in store.read("meta", "dq_results").to_pylist()}
    assert res["needs_table"]["passed"] is False
    assert res["optional_one"]["passed"] is None and res["optional_one"]["description"].startswith("skipped")
