"""Render the graph as Mermaid from the compiled graph and paste it into the docs.

python scripts/gen_graph.py          # rewrite docs/graph.mmd, README.md, docs/architecture.md
python scripts/gen_graph.py --check  # exit 1 if any of them drifted from the code
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from cross_exam.graphs import mermaid

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "README.md", ROOT / "docs" / "architecture.md"]
PATTERN = re.compile(r"(<!-- graph:start -->)\n?.*?\n?(<!-- graph:end -->)", re.DOTALL)


def main(check: bool) -> int:
    graph = mermaid()
    drifted: list[str] = []
    mmd = ROOT / "docs" / "graph.mmd"
    if not mmd.exists() or mmd.read_text() != graph + "\n":
        drifted.append("docs/graph.mmd")
        if not check:
            mmd.write_text(graph + "\n")
    for path in TARGETS:
        text = path.read_text()
        if not PATTERN.search(text):
            print(f"{path.name}: missing graph markers", file=sys.stderr)
            return 1
        updated = PATTERN.sub(lambda m: f"{m.group(1)}\n```mermaid\n{graph}\n```\n{m.group(2)}", text)
        if updated != text:
            drifted.append(str(path.relative_to(ROOT)))
            if not check:
                path.write_text(updated)
    if check and drifted:
        print("graph diagram out of date in: " + ", ".join(drifted) + " (run scripts/gen_graph.py)", file=sys.stderr)
        return 1
    print("graph diagram " + ("up to date" if not drifted else "updated: " + ", ".join(drifted)))
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
