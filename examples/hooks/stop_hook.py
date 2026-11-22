#!/usr/bin/env python3
"""Claude Code Stop hook: cross-examine the agent before it is allowed to stop.

When Claude says it is done, this hook runs ``cross-exam check`` on the session transcript. If a
claim is CONTRADICTED or a criterion was silently skipped, it blocks the stop and tells Claude what
did not hold up, so it keeps working. It never blocks twice in a row (``stop_hook_active``), so it
cannot trap the session in a loop.

Setup (``.claude/settings.json`` in your project)::

    {"hooks": {"Stop": [{"hooks": [{"type": "command",
        "command": "python3 /path/to/cross-exam/examples/hooks/stop_hook.py"}]}]}}

Put the task's acceptance criteria in ``.cross-exam/criteria.md`` (or point ``CROSS_EXAM_CRITERIA``
at a file). No criteria file means the hook does nothing. ``CROSS_EXAM_BASE`` is the git ref the
diff is taken against (default ``HEAD``: uncommitted work).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if event.get("stop_hook_active"):
        return 0  # we already blocked once; let Claude stop
    cwd = Path(event.get("cwd") or ".")
    criteria = Path(os.environ.get("CROSS_EXAM_CRITERIA") or cwd / ".cross-exam" / "criteria.md")
    transcript = event.get("transcript_path")
    exe = shutil.which("cross-exam")
    if not criteria.is_file() or not transcript or not Path(transcript).is_file() or exe is None:
        return 0
    cmd = [exe, "check", "--criteria", str(criteria), "--claims", transcript, "--repo", str(cwd)]
    cmd += ["--base", os.environ.get("CROSS_EXAM_BASE", "HEAD"), "--json", "--no-strict"]
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, check=False)
    if out.returncode != 0:
        print(f"cross-exam failed: {out.stderr.strip()[-500:]}", file=sys.stderr)
        return 0  # never block on our own failure
    report = json.loads(out.stdout)
    problems = [
        f"- claim {c['claim']['id']} is CONTRADICTED: {c['claim']['quote']!r} ({c['evidence']['summary']})"
        for c in report["claims"]
        if c["verdict"] == "CONTRADICTED"
    ]
    problems += [
        f"- criterion {c['criterion']['id']} was not addressed: {c['criterion']['text']}"
        for c in report["criteria"]
        if c["verdict"] == "SKIPPED"
    ]
    if problems:
        reason = "cross-exam checked your summary against the acceptance criteria:\n" + "\n".join(problems)
        print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
