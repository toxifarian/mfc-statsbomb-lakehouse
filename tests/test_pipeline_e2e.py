"""End-to-end: bronze -> silver -> integrate -> DQ -> gold on real (fixture) StatsBomb data, offline."""

import pyarrow.compute as pc
import pytest

from pitchlake.quality.engine import DataQualityError


def _count(store, layer, table):
    return store.read(layer, table).num_rows


def _match_events(pipeline, match_id):
    ev = pipeline.store.read("silver", "events", columns=["match_id"])
    return pc.sum(pc.equal(ev["match_id"], match_id)).as_py()


def test_full_pipeline_builds_star_schema(pipeline, fake_source):
    ctx = pipeline.run()
    assert all(s["status"] == "succeeded" for s in ctx.steps)
    store = pipeline.store
    expected_events = sum(len(fake_source.payload(f"events/{m}.json")) for m in (3930166, 3941017))
    assert _count(store, "silver", "events") == expected_events
    for t in ("dim_player", "dim_match", "fact_shots", "fact_passes", "fact_player_match", "fact_team_match"):
        assert _count(store, "gold", t) > 0, t
    # cross-source integration worked: England players have GPS rows conformed to StatsBomb keys
    assert _count(store, "gold", "fact_player_match_physical") > 0
    dq = store.read("meta", "dq_results").to_pylist()
    assert not [r for r in dq if r["severity"] == "error" and not r["passed"]]


def test_extra_time_minutes_are_sane(pipeline):
    pipeline.run(steps=["bronze", "silver"])
    worst = pc.max(pipeline.store.read("silver", "lineups")["minutes_played"]).as_py()
    assert 120 < worst < 140  # extra-time match, never the 286 the naive calculation gives


def test_incremental_run_fetches_nothing_when_source_unchanged(pipeline, fake_source):
    pipeline.run(steps=["bronze", "silver"])
    fake_source.calls.clear()
    ctx = pipeline.run(steps=["bronze", "silver"])
    bronze = ctx.summary()[0]
    assert bronze["matches_changed"] == 0
    assert all("events" not in u for u in fake_source.calls)  # only competitions + matches polled


def test_reissued_match_replaces_events_atomically(pipeline, fake_source):
    pipeline.run(steps=["bronze", "silver"])
    n_before = _match_events(pipeline, 3930166)

    # vendor re-issues match 3930166: bumps last_updated and drops 10 events
    matches = fake_source.payload("matches/55/282.json")
    for m in matches:
        if m["match_id"] == 3930166:
            m["last_updated"] = "2099-01-01T00:00:00"
    fake_source.overrides["matches/55/282.json"] = matches
    fake_source.overrides["events/3930166.json"] = fake_source.payload("events/3930166.json")[:-10]

    ctx = pipeline.run(steps=["bronze", "silver", "dq_silver"])
    assert ctx.summary()[0]["matches_changed"] == 1
    n_after = _match_events(pipeline, 3930166)
    assert n_after == n_before - 10  # deleted upstream -> deleted here (no orphans)


def test_dq_gate_blocks_bad_data(pipeline, fake_source):
    events = fake_source.payload("events/3930166.json")
    events[5]["location"] = [999.0, 40.0]  # impossible coordinate
    fake_source.overrides["events/3930166.json"] = events
    with pytest.raises(DataQualityError):
        pipeline.run(steps=["bronze", "silver", "dq_silver", "gold"])
    assert not pipeline.store.exists("gold", "fact_events")  # never promoted


def test_failed_resource_is_retried_next_run(pipeline, fake_source, monkeypatch):
    from pitchlake.sources.http import SourceHTTPError

    original = fake_source.get

    def flaky(client, url):
        if url.endswith("events/3941017.json"):
            raise SourceHTTPError(url, 503, "down")
        return original(client, url)

    monkeypatch.setattr(fake_source, "get", flaky)
    ctx = pipeline.run(steps=["bronze"])
    assert ctx.summary()[0]["matches_failed"] == 1
    monkeypatch.setattr(fake_source, "get", original)
    ctx = pipeline.run(steps=["bronze"])
    assert ctx.summary()[0]["matches_changed"] == 1  # only the failed one is picked up again
