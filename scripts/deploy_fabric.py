"""Deploy the Fabric notebooks to a workspace via the Fabric REST API (used by CD).

    az login                                   # or a service principal in CI
    python scripts/deploy_fabric.py --workspace-id <guid> [--lakehouse lh_football]

* Creates the schema-enabled lakehouse if missing.
* Creates or updates each notebook in fabric/notebooks from its .ipynb definition.
Idempotent: safe to run on every merge to main. (For larger estates, Microsoft's
`fabric-cicd` library or Fabric deployment pipelines do the same with more item types.)
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

API = "https://api.fabric.microsoft.com/v1"
ROOT = Path(__file__).resolve().parents[1]


def token() -> str:
    out = subprocess.run(
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            "https://api.fabric.microsoft.com",
            "--query",
            "accessToken",
            "-o",
            "tsv",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


class Fabric:
    def __init__(self, workspace_id: str):
        self.ws = workspace_id
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})

    def _wait(self, resp: requests.Response) -> dict | None:
        """Handle Fabric long-running operations (202 + Location)."""
        if resp.status_code == 202 and "Location" in resp.headers:
            url = resp.headers["Location"]
            while True:
                time.sleep(int(resp.headers.get("Retry-After", 3)))
                resp = self.s.get(url)
                resp.raise_for_status()
                status = resp.json().get("status")
                if status in ("Succeeded", "Failed"):
                    if status == "Failed":
                        raise RuntimeError(resp.text)
                    return resp.json()
        resp.raise_for_status()
        return resp.json() if resp.content else None

    def items(self, item_type: str) -> dict[str, str]:
        r = self.s.get(f"{API}/workspaces/{self.ws}/items", params={"type": item_type})
        r.raise_for_status()
        return {i["displayName"]: i["id"] for i in r.json()["value"]}

    def ensure_lakehouse(self, name: str) -> str:
        existing = self.items("Lakehouse")
        if name in existing:
            print(f"lakehouse {name} exists")
            return existing[name]
        r = self.s.post(
            f"{API}/workspaces/{self.ws}/lakehouses",
            json={"displayName": name, "creationPayload": {"enableSchemas": True}},
        )
        self._wait(r)
        print(f"created lakehouse {name}")
        return self.items("Lakehouse")[name]

    def upsert_notebook(self, path: Path) -> None:
        name = path.stem
        definition = {
            "format": "ipynb",
            "parts": [
                {
                    "path": "notebook-content.ipynb",
                    "payload": base64.b64encode(path.read_bytes()).decode(),
                    "payloadType": "InlineBase64",
                }
            ],
        }
        existing = self.items("Notebook")
        if name in existing:
            r = self.s.post(
                f"{API}/workspaces/{self.ws}/notebooks/{existing[name]}/updateDefinition",
                json={"definition": definition},
            )
            action = "updated"
        else:
            r = self.s.post(
                f"{API}/workspaces/{self.ws}/notebooks", json={"displayName": name, "definition": definition}
            )
            action = "created"
        self._wait(r)
        print(f"{action} notebook {name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace-id", required=True)
    ap.add_argument("--lakehouse", default="lh_football")
    args = ap.parse_args()
    fab = Fabric(args.workspace_id)
    lh_id = fab.ensure_lakehouse(args.lakehouse)
    for nb in sorted((ROOT / "fabric" / "notebooks").glob("*.ipynb")):
        content = json.loads(nb.read_text())
        # bind the default lakehouse so /lakehouse/default is mounted at runtime
        content["metadata"].setdefault("dependencies", {})["lakehouse"] = {
            "default_lakehouse": lh_id,
            "default_lakehouse_name": args.lakehouse,
            "default_lakehouse_workspace_id": args.workspace_id,
        }
        tmp = ROOT / "build" / nb.name
        tmp.parent.mkdir(exist_ok=True)
        tmp.write_text(json.dumps(content))
        fab.upsert_notebook(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
