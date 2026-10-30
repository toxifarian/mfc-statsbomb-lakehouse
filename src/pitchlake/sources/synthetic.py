"""SYNTHETIC stand-ins for the club's existing systems.

The brief says the platform already holds Catapult GPS, Transfermarkt, VALD,
Kitman, etc. We obviously don't have that data, so to *prove* the integration
pattern end-to-end we generate deterministic, clearly-labelled fake extracts
for one focus team, shaped like the real exports:

* ``silver.catapult_athletes``        – athlete master as Catapult OpenField holds it
* ``silver.catapult_match_sessions``  – per-athlete match-day GPS summary
* ``silver.transfermarkt_players``    – player profile as scraped/licensed from Transfermarkt

The *names deliberately disagree* with StatsBomb (abbreviations, missing
accents, "Surname, Forename", nicknames) because that is the real-world
problem identity resolution has to solve. Every row carries ``is_synthetic``.
No physical numbers here describe any real player.
"""

from __future__ import annotations

import hashlib
import logging
import random
import unicodedata

import pyarrow as pa
import pyarrow.compute as pc

from pitchlake.config import Settings
from pitchlake.ops.runlog import StepMetrics
from pitchlake.tables import TableStore

log = logging.getLogger(__name__)

CATAPULT_ATHLETES = pa.schema(
    [
        ("athlete_id", pa.string()),
        ("athlete_name", pa.string()),
        ("jersey", pa.int64()),
        ("position_group", pa.string()),
        ("squad", pa.string()),
        ("is_synthetic", pa.bool_()),
    ]
)
CATAPULT_SESSIONS = pa.schema(
    [
        ("session_id", pa.string()),
        ("athlete_id", pa.string()),
        ("session_date", pa.date32()),
        ("session_type", pa.string()),
        ("opponent", pa.string()),
        ("duration_min", pa.float64()),
        ("total_distance_m", pa.float64()),
        ("hsr_distance_m", pa.float64()),
        ("sprint_distance_m", pa.float64()),
        ("sprint_efforts", pa.int64()),
        ("max_speed_kmh", pa.float64()),
        ("accelerations", pa.int64()),
        ("decelerations", pa.int64()),
        ("player_load", pa.float64()),
        ("is_synthetic", pa.bool_()),
    ]
)
TM_PLAYERS = pa.schema(
    [
        ("tm_player_id", pa.int64()),
        ("player_name", pa.string()),
        ("citizenship", pa.string()),
        ("main_position", pa.string()),
        ("current_club_name", pa.string()),
        ("profile_url", pa.string()),
        ("is_synthetic", pa.bool_()),
    ]
)

POSITION_GROUP = (
    {1: "GK"}
    | {i: "DEF" for i in range(2, 9)}
    | {i: "MID" for i in range(9, 21)}
    | {i: "FWD" for i in (17, 21, 22, 23, 24, 25)}
)
BASE_PER_90 = {  # distance m, hsr m, sprint m, sprints, vmax
    "GK": (5600, 120, 15, 1, 25.0),
    "DEF": (9900, 520, 140, 9, 31.5),
    "MID": (11300, 820, 190, 12, 31.0),
    "FWD": (10200, 780, 260, 16, 32.5),
}


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _stable_id(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()


def catapult_name(sb_name: str, nickname: str | None, rnd: random.Random) -> str:
    """Catapult names are typed by sports scientists – abbreviated, accent-free, inconsistent."""
    base = _ascii(nickname or sb_name)
    tokens = base.split()
    style = rnd.random()
    if len(tokens) >= 2 and style < 0.35:
        return f"{tokens[0][0]}. {tokens[-1]}"  # "H. Kane"
    if len(tokens) >= 2 and style < 0.6:
        return f"{tokens[-1].upper()}, {tokens[0]}"  # "KANE, Harry"
    return base  # "Harry Kane"


class SyntheticClubSources:
    def __init__(self, settings: Settings, store: TableStore):
        self.cfg = settings.synthetic
        self.store = store

    def run(self, metrics: StepMetrics) -> StepMetrics:
        rnd = random.Random(self.cfg.get("seed", 1876))
        team = self.cfg.get("focus_team", "England")
        lineups = self.store.read("silver", "lineups")
        matches = self.store.read("silver", "matches").to_pylist()
        positions = self.store.read("silver", "lineup_positions").to_pylist()
        team_lineups = lineups.filter(pc.equal(lineups["team_name"], team)).to_pylist()
        if not team_lineups:
            log.warning("focus team %s not found in silver.lineups – no synthetic data generated", team)
            metrics.update(rows_out=0)
            return metrics

        # primary position per player = most seconds played
        pos_secs: dict[int, dict[int, float]] = {}
        for p in positions:
            pos_secs.setdefault(p["player_id"], {}).setdefault(p["position_id"], 0.0)
            pos_secs[p["player_id"]][p["position_id"]] += p["seconds_played"] or 0
        players = {}
        for r in sorted(team_lineups, key=lambda r: r["match_id"]):
            players[r["player_id"]] = r
        athletes, tm_rows = [], []
        athlete_by_player: dict[int, dict] = {}
        for pid, r in sorted(players.items()):
            secs = pos_secs.get(pid) or {}
            pos_id = max(secs, key=secs.get) if secs else 13
            group = POSITION_GROUP.get(pos_id, "MID")
            a = {
                "athlete_id": _stable_id("catapult", pid)[:8] + "-" + _stable_id("catapult", pid)[8:12],
                "athlete_name": catapult_name(r["player_name"], r["player_nickname"], rnd),
                "jersey": r["jersey_number"],
                "position_group": group,
                "squad": f"{team} Senior",
                "is_synthetic": True,
            }
            athletes.append(a)
            athlete_by_player[pid] = a
            tm_name = r["player_nickname"] or r["player_name"]
            if rnd.random() < 0.3:
                tm_name = _ascii(tm_name)
            tm_rows.append(
                {
                    "tm_player_id": 100000 + int(_stable_id("tm", pid)[:6], 16) % 900000,
                    "player_name": tm_name,
                    "citizenship": r["country_name"],
                    "main_position": group,
                    "current_club_name": None,
                    "profile_url": None,
                    "is_synthetic": True,
                }
            )

        # one hard case each, so the resolver's review queue / overrides have something to do
        if len(athletes) > 3:
            athletes[2]["athlete_name"] = (
                athletes[2]["athlete_name"].split()[-1].strip(",").title()
            )  # surname only
            tm_rows[3]["player_name"] = "".join(ch for ch in tm_rows[3]["player_name"] if ch != " ")[:9]

        # GPS session per appearance
        match_by_id = {m["match_id"]: m for m in matches}
        sessions = []
        for r in team_lineups:
            if not r["appeared"] or not r["minutes_played"]:
                continue
            m = match_by_id.get(r["match_id"])
            if not m:
                continue
            a = athlete_by_player[r["player_id"]]
            dist, hsr, spr, n_spr, vmax = BASE_PER_90[a["position_group"]]
            f = r["minutes_played"] / 90.0
            j = lambda x: x * rnd.uniform(0.88, 1.12)  # noqa: E731
            opponent = m["away_team_name"] if m["home_team_name"] == team else m["home_team_name"]
            sessions.append(
                {
                    "session_id": _stable_id("session", r["match_id"], r["player_id"])[:16],
                    "athlete_id": a["athlete_id"],
                    "session_date": m["match_date"],
                    "session_type": "Match",
                    "opponent": opponent,
                    "duration_min": round(r["minutes_played"], 1),
                    "total_distance_m": round(j(dist) * f, 0),
                    "hsr_distance_m": round(j(hsr) * f, 0),
                    "sprint_distance_m": round(j(spr) * f, 0),
                    "sprint_efforts": int(round(j(n_spr) * f)),
                    "max_speed_kmh": round(j(vmax) * (0.95 if f < 0.4 else 1.0), 1),
                    "accelerations": int(round(j(55) * f)),
                    "decelerations": int(round(j(60) * f)),
                    "player_load": round(j(dist) * f / 95.0, 1),
                    "is_synthetic": True,
                }
            )

        self.store.write("silver", "catapult_athletes", pa.Table.from_pylist(athletes, CATAPULT_ATHLETES))
        self.store.write(
            "silver", "catapult_match_sessions", pa.Table.from_pylist(sessions, CATAPULT_SESSIONS)
        )
        self.store.write("silver", "transfermarkt_players", pa.Table.from_pylist(tm_rows, TM_PLAYERS))
        metrics.update(
            rows_out=len(sessions), athletes=len(athletes), sessions=len(sessions), focus_team=team
        )
        return metrics
