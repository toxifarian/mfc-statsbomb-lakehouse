"""Configuration loading.

Settings are layered:  base (conf/pitchlake.yml)  <-  environment file  <-  runtime overrides
so the same code runs locally, in CI and in Fabric with only YAML differences.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

CONF_PACKAGE = "pitchlake.conf"


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def conf_path(relative: str) -> Path:
    """Resolve a file shipped inside the package's conf directory."""
    return Path(str(resources.files(CONF_PACKAGE).joinpath(relative)))


def _read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@dataclass
class Settings:
    raw: dict
    env: str
    overrides: dict = field(default_factory=dict)

    # convenience accessors -------------------------------------------------
    @property
    def statsbomb(self) -> dict:
        return self.raw["sources"]["statsbomb"]

    @property
    def platform(self) -> dict:
        return self.raw["platform"]

    @property
    def quality(self) -> dict:
        return self.raw.get("quality", {})

    @property
    def lakehouse(self) -> dict:
        return self.raw.get("lakehouse", {})

    @property
    def synthetic(self) -> dict:
        return self.raw.get("synthetic_sources", {"enabled": False})

    @property
    def identity(self) -> dict:
        return self.raw.get("integration", {}).get("identity", {})

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def load_settings(
    env: str | None = None, config_file: str | None = None, overrides: dict | None = None
) -> Settings:
    """Load settings for an environment.

    env:          local | fabric | fabric-prod | <custom>  (default: $PITCHLAKE_ENV or local)
    config_file:  optional extra YAML (e.g. a scope file checked into the repo)
    overrides:    dict merged last (used by notebook parameters / CLI flags)
    """
    env = env or os.environ.get("PITCHLAKE_ENV", "local")
    raw = _read_yaml(conf_path("pitchlake.yml"))
    env_file = conf_path(f"environments/{env}.yml")
    if env_file.exists():
        raw = _deep_merge(raw, _read_yaml(env_file))
    elif not config_file:
        raise FileNotFoundError(f"Unknown environment '{env}' (no {env_file.name})")
    if config_file:
        raw = _deep_merge(raw, _read_yaml(Path(config_file)))
    if overrides:
        raw = _deep_merge(raw, overrides)
    return Settings(raw=raw, env=env, overrides=overrides or {})
