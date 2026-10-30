"""Fabric platform behaviour, with notebookutils faked (it only exists inside Fabric)."""

import sys
import types

from pitchlake.config import load_settings
from pitchlake.platform import FabricPlatform, LocalPlatform


def _fake_notebookutils(monkeypatch, ctx):
    nbu = types.SimpleNamespace(
        runtime=types.SimpleNamespace(context=ctx),
        credentials=types.SimpleNamespace(
            getToken=lambda aud: f"token-for-{aud}", getSecret=lambda kv, name: f"{name}@{kv}"
        ),
    )
    monkeypatch.setitem(sys.modules, "notebookutils", nbu)


def test_fabric_platform_uses_onelake_abfss(tmp_path, monkeypatch):
    _fake_notebookutils(monkeypatch, {"defaultLakehouseWorkspaceId": "ws-1", "defaultLakehouseId": "lh-2"})
    s = load_settings(
        "fabric",
        overrides={"platform": {"mount_root": str(tmp_path)}, "lakehouse": {"table_layout": "schema"}},
    )
    p = FabricPlatform(s)
    assert (
        p.table_uri("silver", "events")
        == "abfss://ws-1@onelake.dfs.fabric.microsoft.com/lh-2/Tables/silver/events"
    )
    assert p.storage_options() == {"bearer_token": "token-for-storage", "use_fabric_endpoint": "true"}
    assert p.files_path("bronze", "x.json") == tmp_path / "Files" / "bronze" / "x.json"


def test_fabric_platform_falls_back_to_mount_and_prefix_layout(tmp_path, monkeypatch):
    _fake_notebookutils(monkeypatch, {})
    s = load_settings(
        "fabric",
        overrides={"platform": {"mount_root": str(tmp_path)}, "lakehouse": {"table_layout": "prefix"}},
    )
    p = FabricPlatform(s)
    assert p.table_uri("gold", "dim_player") == f"{tmp_path}/Tables/gold_dim_player"
    assert p.storage_options() == {"allow_unsafe_rename": "true"}


def test_secrets_come_from_key_vault_in_fabric(tmp_path, monkeypatch):
    _fake_notebookutils(monkeypatch, {})
    s = load_settings("fabric-prod", overrides={"platform": {"mount_root": str(tmp_path)}})
    assert FabricPlatform(s).secret("statsbomb-api-username").startswith("statsbomb-api-username@https://kv-")


def test_local_secret_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PITCHLAKE_ROOT", str(tmp_path))
    monkeypatch.setenv("STATSBOMB_API_USERNAME", "me")
    assert LocalPlatform(load_settings("local")).secret("statsbomb-api-username") == "me"
