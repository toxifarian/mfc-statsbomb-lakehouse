"""Pure functions: StatsBomb JSON -> contract-shaped rows.

Kept free of IO so they are trivially unit-testable.

Source semantics handled here (all found while profiling the data):
* Optional keys are *omitted*, not null. A pass with no ``outcome`` is a
  completed pass; a missing boolean flag means ``False``.
* ``{id, name}`` reference objects are split into ``*_id`` / ``*_name``.
* Coordinate arrays vary in length (``shot.end_location`` is 2-D or 3-D).
* The match clock restarts each period and stoppage time overlaps the next
  period's clock (first-half 47:10 vs second-half start 45:00), so minutes
  played must be computed per period, not by subtracting clock strings.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from datetime import date

from pitchlake.silver import contracts as c

PERIOD_START_S = {1: 0, 2: 45 * 60, 3: 90 * 60, 4: 105 * 60, 5: 120 * 60}

_REF_PATHS = {p for p, t in c.EVENT_PATHS.items() if t == c._REF}
_SCALAR_PATHS = {p: t for p, t in c.EVENT_PATHS.items() if t != c._REF}
_BOOL_PATHS = {p for p, t in _SCALAR_PATHS.items() if str(t) == "bool"}
_KNOWN_PREFIXES = set(c.EVENT_PATHS) | set(c.COORD_PATHS) | c.CHILD_PATHS


def _get(d: dict, path: str):
    node = d
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _leaf_paths(obj, prefix: str = "") -> Iterable[str]:
    """Yield leaf paths, treating {id,name} refs, coordinate arrays and child arrays as leaves."""
    if isinstance(obj, dict):
        if prefix and set(obj) <= {"id", "name"} and "id" in obj:
            yield prefix
            return
        for key, value in obj.items():
            yield from _leaf_paths(value, f"{prefix}.{key}" if prefix else key)
    else:
        yield prefix


def clock_to_seconds(clock: str | None) -> float | None:
    """'70:48' -> 4248.0 ; '00:03:39.851' -> 219.851"""
    if not clock:
        return None
    parts = [float(p) for p in clock.split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


# ============================================================== events
def flatten_events(
    events: list[dict],
    match_id: int,
    competition_id: int,
    season_id: int,
    bronze_path: str,
    processed_at,
    drift: Counter,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Returns (event_rows, shot_freeze_frame_rows, tactics_lineup_rows); updates `drift` counter."""
    rows, freeze, tactics = [], [], []
    for ev in events:
        row: dict = {"match_id": match_id, "competition_id": competition_id, "season_id": season_id}
        sub_objects = {k for k, v in ev.items() if isinstance(v, dict)}

        for path in _SCALAR_PATHS:
            col = "event_id" if path == "id" else ("event_index" if path == "index" else c.column_name(path))
            value = _get(ev, path)
            if value is None and path in _BOOL_PATHS:
                head = path.split(".")[0]
                if path in c.TOP_LEVEL_FLAGS or head in sub_objects:
                    value = False
            row[col] = value
        for path in _REF_PATHS:
            col = c.column_name(path)
            ref = _get(ev, path)
            row[f"{col}_id"] = ref.get("id") if isinstance(ref, dict) else None
            row[f"{col}_name"] = ref.get("name") if isinstance(ref, dict) else None
        for path, (prefix, dims) in c.COORD_PATHS.items():
            coords = _get(ev, path) or []
            for i in range(dims):
                row[f"{prefix}_{'xyz'[i]}"] = float(coords[i]) if i < len(coords) else None

        row["timestamp_seconds"] = clock_to_seconds(ev.get("timestamp"))
        row["related_events"] = ev.get("related_events") or []

        # ---- schema drift: anything the contract does not know is kept + reported
        extra = {}
        for leaf in _leaf_paths(ev):
            if leaf in _KNOWN_PREFIXES or leaf in c.COORD_PATHS:
                continue
            if any(leaf.startswith(child + ".") for child in c.CHILD_PATHS):
                continue
            parent, _, last = leaf.rpartition(".")
            if parent in _REF_PATHS and last in ("id", "name"):
                continue  # a ref object that gained extra keys: id/name still mapped
            drift[leaf] += 1
            extra[leaf] = _get(ev, leaf)
        row["extra_json"] = json.dumps(extra, ensure_ascii=False) if extra else None
        row["_bronze_path"] = bronze_path
        row["_processed_at"] = processed_at
        rows.append(row)

        # ---- child arrays
        for ff in _get(ev, "shot.freeze_frame") or []:
            loc = ff.get("location") or [None, None]
            freeze.append(
                {
                    "match_id": match_id,
                    "shot_event_id": ev["id"],
                    "player_id": (ff.get("player") or {}).get("id"),
                    "player_name": (ff.get("player") or {}).get("name"),
                    "position_id": (ff.get("position") or {}).get("id"),
                    "position_name": (ff.get("position") or {}).get("name"),
                    "teammate": ff.get("teammate"),
                    "location_x": loc[0],
                    "location_y": loc[1],
                }
            )
        tac = ev.get("tactics")
        if tac:
            for p in tac.get("lineup") or []:
                tactics.append(
                    {
                        "match_id": match_id,
                        "event_id": ev["id"],
                        "event_type": ev["type"]["name"],
                        "team_id": ev["team"]["id"],
                        "formation": tac.get("formation"),
                        "player_id": p["player"]["id"],
                        "player_name": p["player"]["name"],
                        "position_id": p["position"]["id"],
                        "position_name": p["position"]["name"],
                        "jersey_number": p.get("jersey_number"),
                    }
                )
    return rows, freeze, tactics


def period_bounds(events: list[dict]) -> dict[int, tuple[float, float]]:
    """Match-clock (start, end) seconds per period, derived from the events themselves."""
    ends: dict[int, float] = {}
    for ev in events:
        p = ev.get("period")
        if p is None or p >= 5:
            continue
        clock = PERIOD_START_S[p] + clock_to_seconds(ev.get("timestamp") or "0:0")
        ends[p] = max(ends.get(p, 0.0), clock)
    return {p: (PERIOD_START_S[p], end) for p, end in ends.items()}


def span_seconds(
    start: tuple[int, float], end: tuple[int, float | None], bounds: dict[int, tuple[float, float]]
) -> float:
    """Playing seconds between two (period, match-clock seconds) points; end clock None = end of that period."""
    (fp, fs), (tp, ts) = start, end
    if fp not in bounds or tp not in bounds:
        return 0.0
    te = bounds[tp][1] if ts is None else ts
    if fp == tp:
        return max(0.0, te - fs)
    total = max(0.0, bounds[fp][1] - fs)
    for p in range(fp + 1, tp):
        if p in bounds:
            total += bounds[p][1] - bounds[p][0]
    return total + max(0.0, te - bounds[tp][0])


def seconds_played(
    from_clock, to_clock, from_period, to_period, bounds: dict[int, tuple[float, float]]
) -> float:
    """Seconds on the pitch for a single stint (penalty shoot-outs excluded)."""
    if not bounds:
        return 0.0
    last = max(bounds)
    fp = from_period or 1
    tp = min(to_period or last, last)
    ts = clock_to_seconds(to_clock) if to_clock and (to_period or 0) <= last else None
    return span_seconds((fp, clock_to_seconds(from_clock) or 0.0), (tp, ts), bounds)


def rebuild_stints(
    stints: list[dict], bounds: dict[int, tuple[float, float]]
) -> list[tuple[dict, float, bool]]:
    """Return [(stint, seconds, corrected)] with stints re-chained in true time order.

    Found while profiling: for extra-time matches the source chains a player's
    positions in *string* order of the clock ("105:00" < "65:08"), so the
    from/to pairs overlap and naive maths gives 286 minutes for a 120-minute
    match. We therefore sort stints by (period, clock) and end each stint at
    the next one's start, unless its own end is valid and earlier (e.g.
    "Player Off" for treatment, which legitimately leaves a gap).
    """
    if not bounds:
        return [(s, 0.0, False) for s in stints]
    last = max(bounds)

    def start_of(s):
        return (s.get("from_period") or 1, clock_to_seconds(s.get("from")) or 0.0)

    def own_end(s):
        if not s.get("to"):
            return None
        tp = s.get("to_period") or last
        if tp > last:  # ended during the shoot-out
            return None
        return (tp, clock_to_seconds(s["to"]))

    ordered = sorted(stints, key=start_of)
    match_end = (last, bounds[last][1])

    # The player's real exit (substitution off / dismissal) is reliable even when the chain
    # is scrambled: the source attaches it to *some* stint, often not the last one. Every
    # stint is clipped at that point (fixes e.g. subs at 105:00 and sending-offs followed by
    # a phantom "Tactical Shift -> Final Whistle" stint).
    exits = [own_end(s) for s in ordered if _is_exit(s.get("end_reason")) and own_end(s) is not None]
    exit_point = min(exits) if exits else match_end

    out = []
    for i, s in enumerate(ordered):
        st = start_of(s)
        if st[0] not in bounds:  # appeared only in the shoot-out
            out.append((s, 0.0, False))
            continue
        oe = own_end(s)
        valid_own = oe is not None and oe >= st
        nxt = start_of(ordered[i + 1]) if i + 1 < len(ordered) else None
        if nxt is not None:
            end = oe if valid_own and oe <= nxt else nxt
        else:
            end = oe if valid_own else match_end
        end = min(end, exit_point)
        corrected = (oe is not None and end != oe) or (oe is None and end != match_end)
        out.append((s, span_seconds(st, end, bounds) if end > st else 0.0, corrected))
    return out


def _is_exit(reason: str | None) -> bool:
    r = (reason or "").lower()
    return r.startswith("substitution - off") or "red card" in r or "second yellow" in r


# ============================================================== lineups
def flatten_lineups(lineups: list[dict], match_id: int, bounds: dict, processed_at):
    players, positions, cards = [], [], []
    for team in lineups:
        for p in team.get("lineup", []):
            stints = p.get("positions") or []
            total = 0.0
            for st, secs, corrected in rebuild_stints(stints, bounds):
                total += secs
                positions.append(
                    {
                        "match_id": match_id,
                        "team_id": team["team_id"],
                        "player_id": p["player_id"],
                        "position_id": st.get("position_id"),
                        "position_name": st.get("position"),
                        "from_clock": st.get("from"),
                        "to_clock": st.get("to"),
                        "from_period": st.get("from_period"),
                        "to_period": st.get("to_period"),
                        "start_reason": st.get("start_reason"),
                        "end_reason": st.get("end_reason"),
                        "seconds_played": round(secs, 1),
                        "stint_corrected": corrected,
                    }
                )
            for card in p.get("cards") or []:
                cards.append(
                    {
                        "match_id": match_id,
                        "team_id": team["team_id"],
                        "player_id": p["player_id"],
                        "card_time": card.get("time"),
                        "card_type": card.get("card_type"),
                        "reason": card.get("reason"),
                        "period": card.get("period"),
                    }
                )
            country = p.get("country") or {}
            players.append(
                {
                    "match_id": match_id,
                    "team_id": team["team_id"],
                    "team_name": team.get("team_name"),
                    "player_id": p["player_id"],
                    "player_name": p.get("player_name"),
                    "player_nickname": p.get("player_nickname"),
                    "jersey_number": p.get("jersey_number"),
                    "country_id": country.get("id"),
                    "country_name": country.get("name"),
                    "is_starter": any(s.get("start_reason") == "Starting XI" for s in stints),
                    "appeared": bool(stints),
                    "seconds_played": round(total, 1),
                    "minutes_played": round(total / 60.0, 2),
                    "_processed_at": processed_at,
                }
            )
    return players, positions, cards


# ============================================================== 360
def flatten_frames_360(frames: list[dict], match_id: int):
    players, areas = [], []
    for fr in frames:
        va = fr.get("visible_area") or []
        areas.append(
            {"match_id": match_id, "event_id": fr["event_uuid"], "visible_area": [float(v) for v in va]}
        )
        for i, ff in enumerate(fr.get("freeze_frame") or []):
            loc = ff.get("location") or [None, None]
            players.append(
                {
                    "match_id": match_id,
                    "event_id": fr["event_uuid"],
                    "frame_player_index": i,
                    "teammate": ff.get("teammate"),
                    "actor": ff.get("actor"),
                    "keeper": ff.get("keeper"),
                    "location_x": loc[0],
                    "location_y": loc[1],
                    "visible_area_points": len(va) // 2,
                }
            )
    return players, areas


# ============================================================== matches & competitions
def _first(lst):
    return (lst or [None])[0] or {}


def flatten_matches(matches: list[dict], bronze_path: str) -> list[dict]:
    out = []
    for m in matches:
        home, away = m.get("home_team") or {}, m.get("away_team") or {}
        md = m.get("metadata") or {}
        out.append(
            {
                "match_id": m["match_id"],
                "competition_id": m["competition"]["competition_id"],
                "season_id": m["season"]["season_id"],
                "competition_name": m["competition"].get("competition_name"),
                "season_name": m["season"].get("season_name"),
                "match_date": date.fromisoformat(m["match_date"]) if m.get("match_date") else None,
                "kick_off": m.get("kick_off"),
                "match_week": m.get("match_week"),
                "competition_stage_id": (m.get("competition_stage") or {}).get("id"),
                "competition_stage_name": (m.get("competition_stage") or {}).get("name"),
                "home_team_id": home.get("home_team_id"),
                "home_team_name": home.get("home_team_name"),
                "home_team_gender": home.get("home_team_gender"),
                "home_team_country": (home.get("country") or {}).get("name"),
                "home_manager_id": _first(home.get("managers")).get("id"),
                "home_manager_name": _first(home.get("managers")).get("name"),
                "away_team_id": away.get("away_team_id"),
                "away_team_name": away.get("away_team_name"),
                "away_team_gender": away.get("away_team_gender"),
                "away_team_country": (away.get("country") or {}).get("name"),
                "away_manager_id": _first(away.get("managers")).get("id"),
                "away_manager_name": _first(away.get("managers")).get("name"),
                "home_score": m.get("home_score"),
                "away_score": m.get("away_score"),
                "match_status": m.get("match_status"),
                "match_status_360": m.get("match_status_360"),
                "stadium_id": (m.get("stadium") or {}).get("id"),
                "stadium_name": (m.get("stadium") or {}).get("name"),
                "stadium_country": ((m.get("stadium") or {}).get("country") or {}).get("name"),
                "referee_id": (m.get("referee") or {}).get("id"),
                "referee_name": (m.get("referee") or {}).get("name"),
                "data_version": md.get("data_version"),
                "shot_fidelity_version": md.get("shot_fidelity_version"),
                "xy_fidelity_version": md.get("xy_fidelity_version"),
                "last_updated": m.get("last_updated"),
                "last_updated_360": m.get("last_updated_360"),
                "_bronze_path": bronze_path,
            }
        )
    return out


def flatten_competitions(comps: list[dict]) -> list[dict]:
    keys = [f.name for f in c.COMPETITIONS]
    return [{k: comp.get(k) for k in keys} for comp in comps]
