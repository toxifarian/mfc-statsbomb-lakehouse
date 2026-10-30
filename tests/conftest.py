"""Shared fixtures: an offline StatsBomb 'server' backed by tests/fixtures/open-data."""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path

import pytest

from pitchlake.pipeline import Pipeline
from pitchlake.sources.http import HttpClient, HttpResponse, NotFound

FIXTURES = Path(__file__).parent / "fixtures" / "open-data"
OPEN_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"


class FakeOpenData:
    """Serves fixture files for open-data URLs; payloads can be mutated per test."""

    def __init__(self):
        self.overrides: dict[str, object] = {}
        self.calls: list[str] = []

    def payload(self, rel: str):
        if rel in self.overrides:
            return copy.deepcopy(self.overrides[rel])
        path = FIXTURES / (rel + ".gz")
        if not path.exists():
            return None
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)

    def get(self, _client, url: str) -> HttpResponse:
        self.calls.append(url)
        rel = url.replace(OPEN_BASE + "/", "")
        data = self.payload(rel)
        if data is None:
            raise NotFound(url, 404, "not found")
        return HttpResponse(url, 200, json.dumps(data).encode(), 0.0, 1)


@pytest.fixture
def fake_source(monkeypatch):
    fake = FakeOpenData()
    monkeypatch.setattr(HttpClient, "get", lambda self, url: fake.get(self, url))
    return fake


@pytest.fixture
def pipeline(tmp_path, monkeypatch, fake_source):
    monkeypatch.setenv("PITCHLAKE_ROOT", str(tmp_path / "lakehouse"))
    return Pipeline.from_env(
        "local", overrides={"sources": {"statsbomb": {"http": {"requests_per_second": 0}}}}
    )
