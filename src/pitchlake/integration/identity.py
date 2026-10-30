"""Cross-source player identity resolution.

Every system names players differently:

    StatsBomb     "Jude Victor William Bellingham"  (nickname "Jude Bellingham")
    Catapult      "J. Bellingham" / "BELLINGHAM, Jude"
    Transfermarkt "Jude Bellingham"

Joining on names would silently drop or duplicate players, so we resolve
identities once into a governed cross-reference table that every gold model
uses:

    silver.xref_player(sb_player_id, source_system, source_id, score, method, status)

Algorithm
---------
1. Normalise names (strip accents, punctuation, case, "Surname, Forename").
2. Block candidates (same squad / nationality) to avoid N x M comparisons.
3. Score = best of several fuzzy comparisons against full name AND nickname,
   plus an initial+surname rule for "J. Bellingham", plus a jersey bonus.
4. Greedy one-to-one assignment by descending score.
5. >= auto threshold  -> ``auto``; review band -> ``review`` (queue for a human);
   below -> ``unmatched``. Manual overrides (CSV, version-controlled, with an
   approver) always win -> ``manual``.

Only ``auto`` and ``manual`` links flow into gold.
"""

from __future__ import annotations

import csv
import logging
import re
import unicodedata

import pyarrow as pa
from rapidfuzz import fuzz

from pitchlake.config import Settings, conf_path
from pitchlake.ops.runlog import StepMetrics, utcnow
from pitchlake.tables import TableStore

log = logging.getLogger(__name__)

XREF_SCHEMA = pa.schema(
    [
        ("sb_player_id", pa.int64()),
        ("source_system", pa.string()),
        ("source_id", pa.string()),
        ("source_name", pa.string()),
        ("sb_name", pa.string()),
        ("match_score", pa.float64()),
        ("match_method", pa.string()),
        ("status", pa.string()),
        ("resolved_at", pa.timestamp("us", tz="UTC")),
    ]
)


def normalise(name: str | None) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    if "," in s:  # "kane, harry" -> "harry kane"
        last, _, first = s.partition(",")
        s = f"{first} {last}"
    s = re.sub(r"[^a-z\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def name_score(candidate: str, full_name: str, nickname: str | None) -> tuple[float, str]:
    """Best similarity (0-100) of an external name against StatsBomb full name / nickname."""
    cand = normalise(candidate)
    if not cand:
        return 0.0, "empty"
    best, method = 0.0, "none"
    for label, target in (("nickname", normalise(nickname)), ("full_name", normalise(full_name))):
        if not target:
            continue
        for fn_name, fn in (
            ("token_sort", fuzz.token_sort_ratio),
            ("token_set", fuzz.token_set_ratio),
            ("ratio", fuzz.ratio),
        ):
            score = fn(cand, target)
            # token_set rewards subsets – a lone surname shouldn't auto-match
            if fn_name == "token_set" and len(cand.split()) < 2:
                score = min(score, 80)
            if score > best:
                best, method = score, f"{fn_name}:{label}"
        # "h kane" vs "harry kane": initial + surname rule
        ct, tt = cand.split(), target.split()
        if len(ct) >= 2 and len(ct[0]) == 1 and tt and ct[0] == tt[0][0] and ct[-1] == tt[-1] and best < 93:
            best, method = 93.0, f"initial_surname:{label}"
    return float(best), method


class IdentityResolver:
    def __init__(self, settings: Settings, store: TableStore, run_id: str):
        self.cfg = settings.identity
        self.store = store
        self.run_id = run_id
        self.auto = float(self.cfg.get("auto_match_threshold", 90))
        self.review = float(self.cfg.get("review_threshold", 75))

    def _overrides(self) -> list[dict]:
        path = conf_path(self.cfg.get("overrides_file", "reference/xref_player_overrides.csv"))
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as fh:
            return [r for r in csv.DictReader(fh) if r.get("sb_player_id")]

    def _resolve(self, system: str, external: list[dict], sb_players: list[dict], block_key) -> list[dict]:
        now = utcnow()
        pairs = []
        for ext in external:
            for sb in sb_players:
                if block_key(ext, sb) is False:
                    continue
                score, method = name_score(ext["name"], sb["player_name"], sb["player_nickname"])
                if ext.get("jersey") is not None and ext.get("jersey") == sb.get("jersey_number"):
                    score, method = min(100.0, score + 5), method + "+jersey"
                pairs.append((score, method, ext, sb))
        pairs.sort(key=lambda p: -p[0])
        used_ext, used_sb, out = set(), set(), []
        for score, method, ext, sb in pairs:
            if ext["id"] in used_ext or sb["player_id"] in used_sb or score < self.review:
                continue
            used_ext.add(ext["id"])
            used_sb.add(sb["player_id"])
            out.append(
                {
                    "sb_player_id": sb["player_id"],
                    "source_system": system,
                    "source_id": str(ext["id"]),
                    "source_name": ext["name"],
                    "sb_name": sb["player_nickname"] or sb["player_name"],
                    "match_score": round(score, 1),
                    "match_method": method,
                    "status": "auto" if score >= self.auto else "review",
                    "resolved_at": now,
                }
            )
        for ext in external:
            if ext["id"] not in used_ext:
                out.append(
                    {
                        "sb_player_id": None,
                        "source_system": system,
                        "source_id": str(ext["id"]),
                        "source_name": ext["name"],
                        "sb_name": None,
                        "match_score": None,
                        "match_method": None,
                        "status": "unmatched",
                        "resolved_at": now,
                    }
                )
        return out

    def run(self, metrics: StepMetrics) -> StepMetrics:
        lineups = self.store.read("silver", "lineups").to_pylist()
        sb_players: dict[int, dict] = {}
        for r in lineups:
            sb_players[r["player_id"]] = r
        sb_list = list(sb_players.values())
        rows: list[dict] = []

        if self.store.exists("silver", "catapult_athletes"):
            ath = self.store.read("silver", "catapult_athletes").to_pylist()
            squad_team = {a["squad"].replace(" Senior", "") for a in ath}
            ext = [{"id": a["athlete_id"], "name": a["athlete_name"], "jersey": a["jersey"]} for a in ath]
            rows += self._resolve("catapult", ext, sb_list, lambda e, s: s["team_name"] in squad_team)
        if self.store.exists("silver", "transfermarkt_players"):
            tm = self.store.read("silver", "transfermarkt_players").to_pylist()
            ext = [
                {"id": t["tm_player_id"], "name": t["player_name"], "citizenship": t["citizenship"]}
                for t in tm
            ]
            rows += self._resolve(
                "transfermarkt", ext, sb_list, lambda e, s: e["citizenship"] == s["country_name"]
            )

        # manual overrides win
        overrides = self._overrides()
        now = utcnow()
        for ov in overrides:
            rows = [
                r
                for r in rows
                if not (r["source_system"] == ov["source_system"] and r["source_id"] == ov["source_id"])
            ]
            sb = sb_players.get(int(ov["sb_player_id"]))
            rows.append(
                {
                    "sb_player_id": int(ov["sb_player_id"]),
                    "source_system": ov["source_system"],
                    "source_id": ov["source_id"],
                    "source_name": ov.get("source_name"),
                    "sb_name": (sb or {}).get("player_nickname") or (sb or {}).get("player_name"),
                    "match_score": 100.0,
                    "match_method": f"manual:{ov.get('approved_by', 'unknown')}",
                    "status": "manual",
                    "resolved_at": now,
                }
            )

        table = pa.Table.from_pylist(rows, XREF_SCHEMA)
        self.store.write("silver", "xref_player", table)
        counts: dict[str, int] = {}
        for r in rows:
            counts[f"{r['source_system']}:{r['status']}"] = (
                counts.get(f"{r['source_system']}:{r['status']}", 0) + 1
            )
        metrics.update(rows_out=len(rows), link_status=counts, overrides=len(overrides))
        review = [r for r in rows if r["status"] in ("review", "unmatched")]
        if review:
            log.warning(
                "%s identities need human review (see silver.xref_player status='review'/'unmatched')",
                len(review),
            )
        return metrics
