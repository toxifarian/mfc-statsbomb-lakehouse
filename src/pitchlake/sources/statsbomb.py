"""StatsBomb source adapter.

One adapter, two transports, identical payloads:

* ``open`` – the public StatsBomb open-data repository (GitHub raw files)
* ``api``  – the licensed Hudl StatsBomb API (HTTP basic auth)

The adapter only knows how to *address and fetch* resources. Deciding *what*
to fetch (incremental logic) lives in ``pitchlake.bronze``; turning JSON into
tables lives in ``pitchlake.silver``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from pitchlake.config import Settings
from pitchlake.platform import Platform
from pitchlake.sources.http import HttpClient, HttpResponse

log = logging.getLogger(__name__)

SOURCE_NAME = "statsbomb"

OPEN_PATHS = {
    "competitions": "competitions.json",
    "matches": "matches/{competition_id}/{season_id}.json",
    "lineups": "lineups/{match_id}.json",
    "events": "events/{match_id}.json",
    "frames_360": "three-sixty/{match_id}.json",
}

API_PATHS = {
    "competitions": "{v}/competitions",
    "matches": "{v}/competitions/{competition_id}/seasons/{season_id}/matches",
    "lineups": "{v}/lineups/{match_id}",
    "events": "{v}/events/{match_id}",
    "frames_360": "{v}/360-frames/{match_id}",
}

# endpoint-versions keys returned by the licensed API -> our entity names
API_VERSION_KEYS = {
    "api_competitions": "competitions",
    "api_matches": "matches",
    "api_lineups": "lineups",
    "api_events": "events",
    "api_360_freeze_frames": "frames_360",
}

MATCH_ENTITIES = ("lineups", "events", "frames_360")


@dataclass(frozen=True)
class Resource:
    entity: str
    key: str
    url: str
    competition_id: int | None = None
    season_id: int | None = None
    match_id: int | None = None
    source_updated_at: str | None = None
    optional: bool = False  # a 404 is acceptable (e.g. 360 not yet published)
    extra: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def partition(self) -> str:
        if self.competition_id is not None and self.season_id is not None:
            return f"competition_id={self.competition_id}/season_id={self.season_id}"
        return "_all"


class StatsBombSource:
    name = SOURCE_NAME

    def __init__(self, settings: Settings, platform: Platform):
        self.cfg = settings.statsbomb
        self.mode = self.cfg.get("mode", "open")
        http_cfg = self.cfg.get("http", {})
        auth = None
        if self.mode == "api":
            creds = self.cfg.get("credentials", {})
            user = platform.secret(creds.get("username_secret", "statsbomb-api-username"))
            pwd = platform.secret(creds.get("password_secret", "statsbomb-api-password"))
            if not user or not pwd:
                raise RuntimeError("StatsBomb API mode requires credentials (Key Vault secret or env var)")
            auth = (user, pwd)
        self.http = HttpClient(
            timeout_s=http_cfg.get("timeout_s", 60),
            max_retries=http_cfg.get("max_retries", 5),
            backoff_base_s=http_cfg.get("backoff_base_s", 1.0),
            requests_per_second=http_cfg.get("requests_per_second", 8),
            pool_size=max(8, http_cfg.get("max_concurrency", 8) * 2),
            auth=auth,
        )
        self.max_concurrency = http_cfg.get("max_concurrency", 8)

    # ---------------------------------------------------------------- address
    def url(self, entity: str, **ids) -> str:
        if self.mode == "open":
            return f"{self.cfg['open_base_url'].rstrip('/')}/{OPEN_PATHS[entity].format(**ids)}"
        version = self.cfg.get("api_versions", {}).get(entity)
        return f"{self.cfg['api_base_url'].rstrip('/')}/{API_PATHS[entity].format(v=version, **ids)}"

    def competitions_resource(self) -> Resource:
        return Resource("competitions", "competitions", self.url("competitions"))

    def matches_resource(
        self, competition_id: int, season_id: int, updated_at: str | None = None
    ) -> Resource:
        return Resource(
            "matches",
            f"{competition_id}_{season_id}",
            self.url("matches", competition_id=competition_id, season_id=season_id),
            competition_id=competition_id,
            season_id=season_id,
            source_updated_at=updated_at,
        )

    def match_resource(self, entity: str, match: dict) -> Resource:
        updated = match.get("last_updated_360") if entity == "frames_360" else match.get("last_updated")
        return Resource(
            entity,
            str(match["match_id"]),
            self.url(entity, match_id=match["match_id"]),
            competition_id=match["competition"]["competition_id"],
            season_id=match["season"]["season_id"],
            match_id=match["match_id"],
            source_updated_at=updated,
            optional=entity == "frames_360",
        )

    # ------------------------------------------------------------------ fetch
    def fetch(self, resource: Resource) -> HttpResponse:
        return self.http.get(resource.url)

    @staticmethod
    def parse(content: bytes):
        return json.loads(content)

    # ---------------------------------------------------- contract monitoring
    def check_api_versions(self) -> dict:
        """Compare pinned endpoint versions with what the licensed API serves."""
        pinned = self.cfg.get("api_versions", {})
        if self.mode != "api":
            return {"mode": self.mode, "pinned": pinned, "live": None, "drift": []}
        resp = self.http.get(f"{self.cfg['api_base_url'].rstrip('/')}/endpoint-versions")
        live_raw = json.loads(resp.content)
        live = {API_VERSION_KEYS[k]: f"v{v}" for k, v in live_raw.items() if k in API_VERSION_KEYS}
        drift = [
            {"entity": e, "pinned": pinned.get(e), "live": v}
            for e, v in live.items()
            if pinned.get(e) and pinned.get(e) != v
        ]
        return {"mode": self.mode, "pinned": pinned, "live": live, "drift": drift}
