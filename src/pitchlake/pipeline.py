"""Pipeline orchestration – one entry point for CLI, CI and Fabric notebooks.

    bronze -> silver -> [synthetic club sources] -> integrate -> dq(silver) -> gold -> dq(gold)

Each step is independently runnable and idempotent, so a Fabric pipeline can
retry any single activity without side effects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pitchlake.config import Settings, load_settings
from pitchlake.ops.runlog import RunContext
from pitchlake.platform import Platform, get_platform
from pitchlake.tables import TableStore

log = logging.getLogger(__name__)

ALL_STEPS = ["bronze", "silver", "synthetic", "integrate", "dq_silver", "gold", "dq_gold"]


@dataclass
class Pipeline:
    settings: Settings
    platform: Platform = field(init=False)
    store: TableStore = field(init=False)

    def __post_init__(self):
        self.platform = get_platform(self.settings)
        self.store = TableStore(self.platform)

    @classmethod
    def from_env(cls, env: str | None = None, config_file: str | None = None, overrides: dict | None = None):
        return cls(load_settings(env, config_file, overrides))

    # ------------------------------------------------------------------ steps
    def bronze(self, ctx: RunContext, full_refresh: bool = False, match_ids: list[int] | None = None):
        from pitchlake.bronze import BronzeIngestor
        from pitchlake.sources.statsbomb import StatsBombSource

        with ctx.step("bronze") as m:
            source = StatsBombSource(self.settings, self.platform)
            BronzeIngestor(self.settings, self.platform, self.store, source, ctx.run_id).run(
                m, full_refresh=full_refresh, match_ids=match_ids
            )

    def silver(self, ctx: RunContext, full_refresh: bool = False):
        from pitchlake.silver.build import SilverBuilder

        with ctx.step("silver") as m:
            SilverBuilder(self.settings, self.platform, self.store, ctx.run_id).run(
                m, full_refresh=full_refresh
            )

    def synthetic(self, ctx: RunContext):
        if not self.settings.synthetic.get("enabled"):
            log.info("synthetic sources disabled – skipping")
            return
        from pitchlake.sources.synthetic import SyntheticClubSources

        with ctx.step("synthetic") as m:
            SyntheticClubSources(self.settings, self.store).run(m)

    def integrate(self, ctx: RunContext):
        from pitchlake.integration.identity import IdentityResolver

        with ctx.step("integrate") as m:
            IdentityResolver(self.settings, self.store, ctx.run_id).run(m)

    def dq(self, ctx: RunContext, layer: str):
        from pitchlake.quality.engine import DQEngine

        with ctx.step(f"dq_{layer}") as m:
            DQEngine(self.settings, self.store, ctx.run_id).run(m, layer=layer)

    def gold(self, ctx: RunContext):
        from pitchlake.gold.build import GoldBuilder

        with ctx.step("gold") as m:
            GoldBuilder(self.settings, self.store).run(m)

    def maintain(self, ctx: RunContext):
        with ctx.step("maintenance") as m:
            results = []
            for layer, names in {
                "silver": ["events", "frames_360", "lineups", "shot_freeze_frames"],
                "meta": ["bronze_manifest", "pipeline_runs", "dq_results"],
            }.items():
                for n in names:
                    results.append(self.store.optimize_and_vacuum(layer, n))
            m["tables"] = [r for r in results if r]

    # -------------------------------------------------------------------- run
    def run(
        self,
        steps: list[str] | None = None,
        full_refresh: bool = False,
        match_ids: list[int] | None = None,
        trigger: str = "manual",
        run_id: str | None = None,
    ) -> RunContext:
        steps = steps or ALL_STEPS
        unknown = set(steps) - set(ALL_STEPS) - {"maintenance"}
        if unknown:
            raise ValueError(f"Unknown steps: {unknown}")
        ctx = RunContext(self.store, self.settings.env, trigger=trigger, run_id=run_id)
        log.info("run %s on %s: %s", ctx.run_id, self.platform.describe(), steps)
        for step in ALL_STEPS + ["maintenance"]:
            if step not in steps:
                continue
            if step == "bronze":
                self.bronze(ctx, full_refresh, match_ids)
            elif step == "silver":
                self.silver(ctx, full_refresh)
            elif step == "synthetic":
                self.synthetic(ctx)
            elif step == "integrate":
                self.integrate(ctx)
            elif step == "dq_silver":
                self.dq(ctx, "silver")
            elif step == "gold":
                self.gold(ctx)
            elif step == "dq_gold":
                self.dq(ctx, "gold")
            elif step == "maintenance":
                self.maintain(ctx)
        return ctx
