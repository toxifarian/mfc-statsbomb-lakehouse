"""Smoke test against the real public endpoint (run with: pytest -m live)."""

import pytest

from pitchlake.config import load_settings
from pitchlake.platform import get_platform
from pitchlake.sources.statsbomb import StatsBombSource


@pytest.mark.live
def test_open_data_competitions_reachable(tmp_path, monkeypatch):
    monkeypatch.setenv("PITCHLAKE_ROOT", str(tmp_path))
    settings = load_settings("local")
    src = StatsBombSource(settings, get_platform(settings))
    comps = src.parse(src.fetch(src.competitions_resource()).content)
    assert any(c["competition_id"] == 55 and c["season_id"] == 282 for c in comps)
