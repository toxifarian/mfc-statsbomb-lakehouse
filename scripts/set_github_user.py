"""Replace the <GITHUB_USER> placeholder everywhere and regenerate the notebooks.

python scripts/set_github_user.py your-github-username
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["README.md", "scripts/build_notebooks.py", "docs/runbook_fabric.md"]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    user = sys.argv[1]
    for rel in FILES:
        p = ROOT / rel
        text = p.read_text(encoding="utf-8")
        if "<GITHUB_USER>" in text:
            p.write_text(text.replace("<GITHUB_USER>", user), encoding="utf-8")
            print("updated", rel)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_notebooks.py")], check=True)
    print(f"Rebuild the deck with: GITHUB_USER={user} node presentation/build_deck.js")
    return 0


if __name__ == "__main__":
    sys.exit(main())
