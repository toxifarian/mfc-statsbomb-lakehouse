from collections import Counter

import pytest

from pitchlake.silver import flatten as f

BOUNDS_90 = {1: (0, 47 * 60), 2: (45 * 60, 95 * 60)}
BOUNDS_ET = {1: (0, 2938.2), 2: (2700, 5821.3), 3: (5400, 6370.9), 4: (6300, 7274.3)}


@pytest.mark.parametrize(
    "clock,expected", [("70:48", 4248.0), ("00:03:39.851", 219.851), (None, None), ("105:00", 6300.0)]
)
def test_clock_to_seconds(clock, expected):
    assert (
        f.clock_to_seconds(clock) == pytest.approx(expected)
        if expected
        else f.clock_to_seconds(clock) is None
    )


def test_full_match_starter():
    assert f.seconds_played("00:00", None, 1, None, BOUNDS_90) == pytest.approx(47 * 60 + 50 * 60)


def test_substitute_spanning_halftime_counts_stoppage_correctly():
    # on at 40:00 (1st half), off at 60:00 (2nd half): 7 mins of 1st half (incl. stoppage) + 15 of 2nd
    assert f.seconds_played("40:00", "60:00", 1, 2, BOUNDS_90) == pytest.approx(7 * 60 + 15 * 60)


def test_rebuild_stints_fixes_string_sorted_extra_time_chain():
    """Real Kyle Walker data, England 2-1 Slovakia aet (Euro 2024 R16): stints chained in string order."""
    scrambled = [
        {
            "position": "Right Back",
            "from": "00:00",
            "to": "105:00",
            "from_period": 1,
            "to_period": 4,
            "end_reason": "Tactical Shift",
        },
        {
            "position": "Right Center Back",
            "from": "105:00",
            "to": "65:08",
            "from_period": 4,
            "to_period": 2,
            "end_reason": "Tactical Shift",
        },
        {
            "position": "Right Back",
            "from": "65:08",
            "to": "90:00",
            "from_period": 2,
            "to_period": 3,
            "end_reason": "Tactical Shift",
        },
        {
            "position": "Right Center Back",
            "from": "90:00",
            "to": "93:54",
            "from_period": 3,
            "to_period": 2,
            "end_reason": "Tactical Shift",
        },
        {
            "position": "Right Back",
            "from": "93:54",
            "to": None,
            "from_period": 2,
            "to_period": None,
            "end_reason": "Final Whistle",
        },
    ]
    naive = sum(
        f.seconds_played(s["from"], s["to"], s["from_period"], s["to_period"], BOUNDS_ET) for s in scrambled
    )
    rebuilt = f.rebuild_stints(scrambled, BOUNDS_ET)
    total = sum(secs for _, secs, _ in rebuilt)
    match_length = sum(e - s for s, e in BOUNDS_ET.values())
    assert naive / 60 > 250  # the bug: ~286 minutes
    assert total == pytest.approx(match_length)  # fixed: exactly the match length
    assert sum(c for *_, c in rebuilt) == 5  # every stint except the first needed re-chaining


def test_player_off_for_treatment_leaves_gap():
    stints = [
        {"from": "00:00", "to": "30:00", "from_period": 1, "to_period": 1, "end_reason": "Player Off"},
        {"from": "33:00", "to": None, "from_period": 1, "to_period": None, "end_reason": "Final Whistle"},
    ]
    total = sum(s for _, s, _ in f.rebuild_stints(stints, BOUNDS_90))
    assert total == pytest.approx((47 * 60 + 50 * 60) - 180)


def _event(**kw):
    base = {
        "id": "e1",
        "index": 1,
        "period": 1,
        "timestamp": "00:01:00.000",
        "minute": 1,
        "second": 0,
        "type": {"id": 30, "name": "Pass"},
        "possession": 1,
        "possession_team": {"id": 1, "name": "A"},
        "play_pattern": {"id": 1, "name": "Regular Play"},
        "team": {"id": 1, "name": "A"},
        "player": {"id": 10, "name": "P"},
        "position": {"id": 5, "name": "LCB"},
        "location": [40.0, 30.0],
        "pass": {
            "length": 20.0,
            "angle": 0.1,
            "height": {"id": 1, "name": "Ground Pass"},
            "end_location": [60.0, 30.0],
        },
    }
    base.update(kw)
    return base


def test_missing_pass_outcome_means_complete_and_flags_default_false():
    rows, _, _ = f.flatten_events([_event()], 1, 55, 282, "p", None, Counter())
    r = rows[0]
    assert r["pass_outcome_name"] is None
    assert r["pass_cross"] is False and r["under_pressure"] is False
    assert r["shot_first_time"] is None  # not applicable to a pass
    assert (r["location_x"], r["pass_end_x"]) == (40.0, 60.0)


def test_schema_drift_is_detected_and_preserved():
    drift = Counter()
    ev = _event()
    ev["pass"]["backheel"] = True
    ev["brand_new_block"] = {"speed": 7.1}
    rows, _, _ = f.flatten_events([ev], 1, 55, 282, "p", None, drift)
    assert set(drift) == {"pass.backheel", "brand_new_block.speed"}
    assert '"pass.backheel": true' in rows[0]["extra_json"]


def test_shot_3d_end_location_and_freeze_frame_child_rows():
    shot = _event(id="s1", type={"id": 16, "name": "Shot"}, location=[110.0, 40.0])
    del shot["pass"]
    shot["shot"] = {
        "statsbomb_xg": 0.3,
        "end_location": [120.0, 38.0, 1.2],
        "outcome": {"id": 97, "name": "Goal"},
        "freeze_frame": [
            {
                "location": [115.0, 40.0],
                "player": {"id": 2, "name": "GK"},
                "position": {"id": 1, "name": "Goalkeeper"},
                "teammate": False,
            }
        ],
    }
    rows, freeze, _ = f.flatten_events([shot], 1, 55, 282, "p", None, Counter())
    assert rows[0]["shot_end_z"] == 1.2
    assert len(freeze) == 1 and freeze[0]["shot_event_id"] == "s1"


def test_exit_attached_to_wrong_stint_is_honoured():
    """Real Harry Kane data, same match: subbed off at 105:00 but the exit sits on the first stint."""
    stints = [
        {
            "from": "00:00",
            "to": "105:00",
            "from_period": 1,
            "to_period": 4,
            "end_reason": "Substitution - Off (Tactical)",
        },
        {"from": "65:08", "to": "90:00", "from_period": 2, "to_period": 3, "end_reason": "Tactical Shift"},
        {"from": "90:00", "to": None, "from_period": 3, "to_period": None, "end_reason": "Final Whistle"},
    ]
    total = sum(secs for _, secs, _ in f.rebuild_stints(stints, BOUNDS_ET))
    first_three_periods = sum(e - s for p, (s, e) in BOUNDS_ET.items() if p < 4)
    assert total == pytest.approx(first_three_periods)


def test_red_card_followed_by_phantom_stint():
    stints = [
        {
            "from": "00:00",
            "to": "41:07",
            "from_period": 1,
            "to_period": 1,
            "end_reason": "Foul Committed (Red Card)",
        },
        {"from": "41:07", "to": None, "from_period": 1, "to_period": None, "end_reason": "Final Whistle"},
    ]
    total = sum(secs for _, secs, _ in f.rebuild_stints(stints, BOUNDS_90))
    assert total == pytest.approx(41 * 60 + 7)
