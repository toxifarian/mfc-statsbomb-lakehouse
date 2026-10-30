"""Command line interface.

pitchlake run                         # full pipeline, local environment
pitchlake run --steps bronze silver   # selected steps
pitchlake run --max-matches 5         # demo-sized run
pitchlake run --full-refresh          # rebuild silver from bronze (no API calls) / re-fetch all
pitchlake status                      # last runs, watermarks, DQ summary
pitchlake check-api                   # pinned vs live StatsBomb endpoint versions
pitchlake maintain                    # OPTIMIZE + VACUUM
"""

from __future__ import annotations

import argparse
import json
import sys

from pitchlake.ops.logging_setup import configure_logging
from pitchlake.pipeline import ALL_STEPS, Pipeline


def _overrides(args) -> dict:
    o: dict = {}
    sb: dict = {}
    if getattr(args, "max_matches", None):
        sb["max_matches_per_run"] = args.max_matches
    if getattr(args, "scope", None):
        cid, sid = args.scope.split(":")
        sb["scope"] = [{"competition_id": int(cid), "season_id": int(sid), "label": args.scope}]
    if getattr(args, "no_360", False):
        sb["entities"] = {"lineups": True, "events": True, "frames_360": False}
    if sb:
        o["sources"] = {"statsbomb": sb}
    if getattr(args, "dq_mode", None):
        o["quality"] = {"mode": args.dq_mode}
    return o


def cmd_run(args) -> int:
    p = Pipeline.from_env(args.env, args.config, _overrides(args))
    ctx = p.run(steps=args.steps, full_refresh=args.full_refresh, match_ids=args.match_ids, trigger="cli")
    print(json.dumps({"run_id": ctx.run_id, "steps": ctx.summary()}, indent=2, default=str))
    return 0


def cmd_status(args) -> int:
    from pitchlake.ops.status import status_report

    p = Pipeline.from_env(args.env, args.config)
    print(status_report(p.store))
    return 0


def cmd_check_api(args) -> int:
    from pitchlake.sources.statsbomb import StatsBombSource

    p = Pipeline.from_env(args.env, args.config)
    result = StatsBombSource(p.settings, p.platform).check_api_versions()
    print(json.dumps(result, indent=2))
    return 1 if result.get("drift") else 0


def cmd_maintain(args) -> int:
    p = Pipeline.from_env(args.env, args.config)
    ctx = p.run(steps=["maintenance"], trigger="cli")
    print(json.dumps(ctx.summary(), indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pitchlake", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--env", default=None, help="environment: local | fabric | fabric-prod")
    parser.add_argument("--config", default=None, help="extra YAML overlay (e.g. a scope file)")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--json-logs", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run pipeline steps")
    run.add_argument("--steps", nargs="+", choices=ALL_STEPS + ["maintenance"], default=None)
    run.add_argument("--full-refresh", action="store_true")
    run.add_argument("--match-ids", nargs="+", type=int, default=None)
    run.add_argument("--max-matches", type=int, default=None)
    run.add_argument("--scope", default=None, help="competition_id:season_id, e.g. 55:282")
    run.add_argument("--no-360", action="store_true", help="skip 360 freeze-frame data")
    run.add_argument("--dq-mode", choices=["enforce", "warn"], default=None)
    run.set_defaults(func=cmd_run)

    sub.add_parser("status", help="show run log, watermarks and DQ").set_defaults(func=cmd_status)
    sub.add_parser("check-api", help="compare pinned vs live API versions").set_defaults(func=cmd_check_api)
    sub.add_parser("maintain", help="optimize + vacuum Delta tables").set_defaults(func=cmd_maintain)

    args = parser.parse_args(argv)
    configure_logging(args.log_level, args.json_logs)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
