"""Platform abstraction.

The *only* place that knows whether we are running on a laptop/CI runner or
inside Microsoft Fabric. Everything else asks the platform for:

  * a filesystem path for raw files (bronze landing)        -> files_path()
  * a URI for a Delta table in a given layer                -> table_uri()
  * storage options for delta-rs (auth for OneLake)         -> storage_options()
  * secrets (API credentials)                               -> secret()

Both platforms use the same Files/ + Tables/ layout, so a local run is a
faithful rehearsal of the Fabric run.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path

from pitchlake.config import Settings

log = logging.getLogger(__name__)


class Platform(ABC):
    name: str = "abstract"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.table_layout = settings.lakehouse.get("table_layout", "schema")

    # ---- files ------------------------------------------------------------
    @property
    @abstractmethod
    def files_root(self) -> Path: ...

    def files_path(self, *parts: str) -> Path:
        return self.files_root.joinpath(*parts)

    # ---- tables -----------------------------------------------------------
    @property
    @abstractmethod
    def tables_root(self) -> str: ...

    def table_uri(self, layer: str, name: str) -> str:
        if self.table_layout == "prefix":
            return f"{self.tables_root}/{layer}_{name}"
        return f"{self.tables_root}/{layer}/{name}"

    def storage_options(self) -> dict | None:
        return None

    # ---- secrets ----------------------------------------------------------
    def secret(self, name: str) -> str | None:
        env_name = name.upper().replace("-", "_")
        return os.environ.get(env_name)

    def describe(self) -> dict:
        return {"platform": self.name, "files_root": str(self.files_root), "tables_root": self.tables_root}


class LocalPlatform(Platform):
    name = "local"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        root = settings.platform.get("root", "./lakehouse")
        self.root = Path(os.environ.get("PITCHLAKE_ROOT", root)).resolve()
        (self.root / "Files").mkdir(parents=True, exist_ok=True)
        (self.root / "Tables").mkdir(parents=True, exist_ok=True)

    @property
    def files_root(self) -> Path:
        return self.root / "Files"

    @property
    def tables_root(self) -> str:
        return str(self.root / "Tables")


class FabricPlatform(Platform):
    """Runs inside a Fabric notebook with a default lakehouse attached."""

    name = "fabric"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.mount_root = Path(settings.platform.get("mount_root", "/lakehouse/default"))
        self._abfss_root = settings.platform.get("abfss_root") or self._detect_abfss_root()
        if not self.mount_root.exists():
            raise RuntimeError(
                "No default lakehouse mounted at /lakehouse/default - attach the lakehouse to the notebook."
            )

    # notebookutils is injected into Fabric notebook sessions
    @staticmethod
    def _nbu():
        try:
            import notebookutils  # type: ignore

            return notebookutils
        except ImportError:  # pragma: no cover - only inside Fabric
            return None

    def _detect_abfss_root(self) -> str | None:
        nbu = self._nbu()
        if nbu is None:
            return None
        try:
            ctx = nbu.runtime.context
            ws = ctx.get("defaultLakehouseWorkspaceId") or ctx.get("currentWorkspaceId")
            lh = ctx.get("defaultLakehouseId")
            if ws and lh:
                return f"abfss://{ws}@onelake.dfs.fabric.microsoft.com/{lh}"
        except Exception as exc:  # pragma: no cover
            log.warning("Could not read Fabric runtime context: %s", exc)
        return None

    @property
    def files_root(self) -> Path:
        return self.mount_root / "Files"

    @property
    def tables_root(self) -> str:
        if self._abfss_root:
            return f"{self._abfss_root.rstrip('/')}/Tables"
        # Fallback: write through the FUSE mount
        return str(self.mount_root / "Tables")

    def storage_options(self) -> dict | None:
        if self._abfss_root:
            nbu = self._nbu()
            token = nbu.credentials.getToken("storage") if nbu else os.environ.get("ONELAKE_TOKEN")
            return {"bearer_token": token, "use_fabric_endpoint": "true"}
        # Mounted path: the FUSE mount does not support atomic rename
        return {"allow_unsafe_rename": "true"}

    def secret(self, name: str) -> str | None:
        kv = self.settings.platform.get("key_vault_url")
        nbu = self._nbu()
        if kv and nbu:
            return nbu.credentials.getSecret(kv, name)
        return super().secret(name)


def get_platform(settings: Settings) -> Platform:
    kind = settings.platform.get("kind", "local")
    if kind == "local":
        return LocalPlatform(settings)
    if kind == "fabric":
        return FabricPlatform(settings)
    raise ValueError(f"Unknown platform kind: {kind}")
