import duckdb
import pytest

from pitchlake.quality.engine import compile_rule

RULES = [
    ({"type": "not_null", "table": "silver.t", "columns": ["a"]}, 1),
    ({"type": "unique", "table": "silver.t", "columns": ["a"]}, 1),
    ({"type": "accepted_values", "table": "silver.t", "column": "b", "values": ["x", "y"]}, 1),
    ({"type": "range", "table": "silver.t", "column": "c", "min": 0, "max": 1}, 2),
    ({"type": "expression", "table": "silver.t", "expression": "c >= 0"}, 1),
    (
        {
            "type": "relationship",
            "table": "silver.t",
            "column": "a",
            "ref_table": "silver.r",
            "ref_column": "a",
        },
        2,
    ),
    ({"type": "row_count_min", "table": "silver.t", "min": 10}, 1),
    ({"type": "sql", "query": "SELECT * FROM silver_t WHERE a = 2"}, 2),
]


@pytest.mark.parametrize("rule,expected_failures", RULES)
def test_rule_types_compile_and_detect(rule, expected_failures):
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE silver_t AS SELECT * FROM (VALUES (1,'x',0.5),(2,'y',0.2),(2,'z',-1.0),(NULL,'x',2.0)) v(a,b,c)"
    )
    con.execute("CREATE TABLE silver_r AS SELECT 1 AS a")
    failing, _ = compile_rule(rule)
    assert con.execute(f"SELECT count(*) FROM ({failing}) q").fetchone()[0] == expected_failures
