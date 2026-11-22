"""The fixed set of verifier tools. Each one runs a check and returns a verdict decided by code.

Checks run inside a throwaway copy of the repo (``Sandbox``) with a scrubbed environment and a
timeout. Anything that goes wrong while checking (bad regex, unknown program, timeout, a test that
does not exist) is ``UNVERIFIABLE``, never ``VERIFIED``.
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from cross_exam.inputs import added_lines
from cross_exam.models import Check, Evidence, Verdict

DEFAULT_ALLOWLIST: tuple[str, ...] = ("pytest", "ruff", "mypy", "ls", "wc", "grep", "cat", "head")
IGNORED_DIRS = (".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".cross-exam")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
SAFE_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "PYTHONPATH")
MAX_DETAIL = 2000


@dataclass
class Outcome:
    verdict: Verdict
    evidence: Evidence


def _out(verdict: Verdict, summary: str, detail: str = "", code: int | None = None, started: float = 0.0) -> Outcome:
    seconds = round(time.monotonic() - started, 3) if started else 0.0
    return Outcome(verdict, Evidence(summary=summary, detail=detail[-MAX_DETAIL:], exit_code=code, seconds=seconds))


@dataclass
class Sandbox:
    """A copy of the repo the checks may run (and scribble) in. ``close()`` removes it."""

    repo: Path
    diff: str = ""
    python: str = sys.executable
    allowlist: tuple[str, ...] = DEFAULT_ALLOWLIST
    timeout: float = 60.0
    root: Path = field(init=False)

    def __post_init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cross-exam-")
        self.root = Path(self._tmp.name) / "repo"
        shutil.copytree(self.repo, self.root, ignore=shutil.ignore_patterns(*IGNORED_DIRS), symlinks=True)

    def close(self) -> None:
        self._tmp.cleanup()

    def __enter__(self) -> Sandbox:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def env(self) -> dict[str, str]:
        """Only harmless variables reach the checks: no API keys, tokens or cloud credentials."""
        env = {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}
        env.update({"PYTHONDONTWRITEBYTECODE": "1", "CROSS_EXAM": "1", "NO_COLOR": "1"})
        return env

    def inside(self, rel: str) -> Path | None:
        """Resolve a repo-relative path, refusing anything that escapes the copy."""
        if not rel or Path(rel).is_absolute():
            return None
        path = (self.root / rel).resolve()
        root = self.root.resolve()
        return path if path == root or root in path.parents else None

    async def exec(self, argv: list[str]) -> tuple[int | None, str]:
        """Run argv (no shell) in the copy. ``None`` exit code means it timed out and was killed."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=self.root,
                env=self.env(),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            return -1, f"could not start {argv[0]}: {exc}"
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), self.timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return None, f"killed after {self.timeout:g}s"
        return proc.returncode, out.decode("utf-8", "replace")

    # ---- the tools ---------------------------------------------------------------------------

    async def run(self, check: Check) -> Outcome:
        handler = {
            "run_test": self.run_test,
            "grep_diff": self.grep_diff,
            "file_exists": self.file_exists,
            "run_command": self.run_command,
            "http_check": self.http_check,
        }.get(check.tool)
        if handler is None:
            return _out("UNVERIFIABLE", f"no tool can check this: {check.reason or 'model gave no check'}")
        return await handler(check)

    async def run_test(self, check: Check) -> Outcome:
        started = time.monotonic()
        expect = (check.expect or "pass").lower()
        if expect not in ("pass", "fail"):
            return _out("UNVERIFIABLE", f"run_test expects 'pass' or 'fail', not {check.expect!r}")
        target = check.target.strip()
        if target and (target.startswith("-") or self.inside(target.split("::", 1)[0]) is None):
            return _out("UNVERIFIABLE", f"not a test inside the repo: {target!r}")
        argv = [
            self.python,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--color=no",
            *([target] if target else []),
        ]
        code, output = await self.exec(argv)
        label = target or "the whole test suite"
        if code is None:
            return _out("UNVERIFIABLE", f"{label} timed out", output, None, started)
        if code < 0:  # could not start, or killed by a signal
            return _out("UNVERIFIABLE", f"pytest could not run {label}: {output[-200:]}", output, code, started)
        if code not in (0, 1):  # 2 interrupted, 3 internal error, 4 usage error, 5 no tests collected
            return _out("UNVERIFIABLE", f"pytest could not run {label} (exit {code})", output, code, started)
        passed = code == 0
        tail = _pytest_tail(output)
        if passed == (expect == "pass"):
            return _out("VERIFIED", f"{label}: {tail}", output, code, started)
        return _out("CONTRADICTED", f"{label}: {tail}", output, code, started)

    async def grep_diff(self, check: Check) -> Outcome:
        started = time.monotonic()
        expect = (check.expect or "present").lower()
        if expect not in ("present", "absent"):
            return _out("UNVERIFIABLE", f"grep_diff expects 'present' or 'absent', not {check.expect!r}")
        if not self.diff.strip():
            return _out("UNVERIFIABLE", "no diff was given, so the change cannot be inspected")
        try:
            pattern = re.compile(check.target)
        except re.error as exc:
            return _out("UNVERIFIABLE", f"bad regex {check.target!r}: {exc}")
        if not check.target:
            return _out("UNVERIFIABLE", "empty pattern")
        hits = [line for line in added_lines(self.diff) if pattern.search(line)]
        found = bool(hits)
        detail = "\n".join(hits[:20])
        summary = (
            f"{len(hits)} added line(s) match /{check.target}/" if found else f"no added line matches /{check.target}/"
        )
        verdict: Verdict = "VERIFIED" if found == (expect == "present") else "CONTRADICTED"
        return _out(verdict, summary, detail, None, started)

    async def file_exists(self, check: Check) -> Outcome:
        expect = (check.expect or "present").lower()
        if expect not in ("present", "absent"):
            return _out("UNVERIFIABLE", f"file_exists expects 'present' or 'absent', not {check.expect!r}")
        path = self.inside(check.target)
        if path is None:
            return _out("UNVERIFIABLE", f"not a path inside the repo: {check.target!r}")
        exists = path.exists()
        verdict: Verdict = "VERIFIED" if exists == (expect == "present") else "CONTRADICTED"
        return _out(verdict, f"{check.target} {'exists' if exists else 'does not exist'}")

    async def run_command(self, check: Check) -> Outcome:
        started = time.monotonic()
        expect = (check.expect or "pass").lower()
        if expect not in ("pass", "fail"):
            return _out("UNVERIFIABLE", f"run_command expects 'pass' or 'fail', not {check.expect!r}")
        try:
            argv = shlex.split(check.target)
        except ValueError as exc:
            return _out("UNVERIFIABLE", f"cannot parse command {check.target!r}: {exc}")
        if not argv:
            return _out("UNVERIFIABLE", "empty command")
        program = argv[0]
        if "/" in program or program not in self.allowlist:
            return _out("UNVERIFIABLE", f"{program!r} is not on the allowlist ({', '.join(self.allowlist)})")
        resolved = shutil.which(program, path=self.env().get("PATH"))
        if resolved is None:
            return _out("UNVERIFIABLE", f"{program!r} is not installed")
        code, output = await self.exec([resolved, *argv[1:]])
        if code is None:
            return _out("UNVERIFIABLE", f"`{check.target}` timed out", output, None, started)
        if code < 0:
            return _out("UNVERIFIABLE", f"`{check.target}` did not run: {output[-200:]}", output, code, started)
        ok = code == 0
        verdict: Verdict = "VERIFIED" if ok == (expect == "pass") else "CONTRADICTED"
        return _out(verdict, f"`{check.target}` exited {code}", output, code, started)

    async def http_check(self, check: Check) -> Outcome:
        started = time.monotonic()
        url = urlparse(check.target)
        if url.scheme not in ("http", "https") or (url.hostname or "") not in LOCAL_HOSTS:
            return _out("UNVERIFIABLE", f"http_check only talks to localhost, not {check.target!r}")
        try:
            want = int(check.expect or "200")
        except ValueError:
            return _out("UNVERIFIABLE", f"http_check expects a status code, not {check.expect!r}")
        status = await asyncio.to_thread(_http_status, check.target, self.timeout)
        if status is None:
            return _out("UNVERIFIABLE", f"nothing answered at {check.target}", "", None, started)
        verdict: Verdict = "VERIFIED" if status == want else "CONTRADICTED"
        return _out(verdict, f"GET {check.target} -> {status} (expected {want})", "", None, started)


def _http_status(url: str, timeout: float) -> int | None:
    request = urllib.request.Request(url, method="GET")  # noqa: S310 - scheme and host checked by the caller
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, OSError, ValueError):
        return None


_COUNT = re.compile(r"\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b")


def _pytest_tail(output: str) -> str:
    """'1 failed, 3 passed' out of pytest's summary line (warnings dropped), else the last line."""
    lines = [line for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        if re.search(r" in [\d.]+s\b", line) and (counts := _COUNT.findall(line)):
            return ", ".join(counts)
    return lines[-1].strip(" =") if lines else "no output"
