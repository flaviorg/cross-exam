"""Command line: ``check``, ``board``, ``demo``, ``graph``, ``version``."""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from cross_exam import __version__, fixture
from cross_exam.graph import ExamDeps
from cross_exam.inputs import git_diff, parse_criteria, read_claims
from cross_exam.llm.factory import make_llm, resolve_model
from cross_exam.models import Report
from cross_exam.runner import examine
from cross_exam.store import Board
from cross_exam.verifiers import DEFAULT_ALLOWLIST, Sandbox

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    help="Cross-examine a coding agent's \"done!\" claim against the task's acceptance criteria.",
)
console = Console(highlight=False)
err = Console(stderr=True, highlight=False)

DEFAULT_DB = Path(".cross-exam/board.db")
COLOURS = {"VERIFIED": "green", "CONTRADICTED": "red", "UNVERIFIABLE": "yellow", "SKIPPED": "magenta"}
DbOpt = Annotated[Path, typer.Option("--db", help="Scoreboard SQLite database.")]


def _v(verdict: str) -> str:
    return f"[{COLOURS.get(verdict, 'white')}]{verdict}[/]"


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x:.0%}"


def task_name(criteria_text: str, fallback: str) -> str:
    for line in criteria_text.splitlines():
        m = re.match(r"^#+\s+(?:Task:\s*)?(.+?)\s*$", line)
        if m:
            return m.group(1)
    return fallback


def print_report(r: Report) -> None:
    t = Table(title=f"Claims ({r.agent})", title_justify="left", show_lines=False)
    for col in ("id", "verdict", "criteria", "claim", "evidence"):
        t.add_column(col, overflow="fold")
    for c in r.claims:
        who = " [dim](human)[/]" if c.source == "human" else ""
        t.add_row(
            c.claim.id,
            _v(c.verdict) + who,
            ", ".join(c.claim.criteria) or "[magenta]scope creep[/]",
            escape(c.claim.quote),
            f"[dim]{c.claim.check.tool}[/] " + escape(c.evidence.summary),
        )
    console.print(t)
    ct = Table(title="Acceptance criteria", title_justify="left")
    for col in ("id", "verdict", "criterion", "claims"):
        ct.add_column(col, overflow="fold")
    for c in r.criteria:
        label = "[magenta]silently skipped[/]" if c.verdict == "SKIPPED" else ", ".join(c.claims)
        ct.add_row(c.criterion.id, _v(c.verdict), escape(c.criterion.text), label)
    console.print(ct)
    for d in r.dropped:
        console.print(f"[dim]dropped claim: {escape(d)}[/]")
    s = r.scores
    console.print(
        f"lie rate [bold]{_pct(s.lie_rate)}[/] "
        f"({s.contradicted}/{s.verified + s.contradicted} checkable claims false)  "
        f"skip rate [bold]{_pct(s.skip_rate)}[/] ({s.skipped}/{s.criteria} criteria)  "
        f"scope creep {s.scope_creep}  unverifiable {s.unverifiable}  overclaim [bold]{s.overclaim:.2f}[/]"
    )
    verdict = "[green]claim holds up[/]" if r.honest else '[red]the agent\'s "done" does not hold up[/]'
    console.print(f"verdict: {verdict}")


def ask_human(payload: dict[str, Any]) -> dict[str, Any]:
    """Interactive resume value for the review interrupt."""
    if payload.get("error"):
        err.print(f"[red]{escape(payload['error'])}[/]")
    err.print(f"[bold]{escape(payload['question'])}[/]")
    overrules: dict[str, Any] = {}
    for c in payload["claims"]:
        err.print(f"\n{c['id']}: {escape(c['quote'])}\n  [dim]{escape(c['why'])}[/]")
        choice = typer.prompt("  [v]erified / [c]ontradicted / [enter] keep UNVERIFIABLE", default="", err=True)
        verdict = {"v": "VERIFIED", "c": "CONTRADICTED"}.get(choice.strip().lower()[:1])
        if verdict:
            reason = typer.prompt("  why (evidence you saw)", err=True)
            overrules[c["id"]] = {"verdict": verdict, "reason": reason}
    return {"overrules": overrules}


def run_check(
    *,
    criteria_path: Path,
    claims_path: Path,
    repo: Path,
    diff_path: Path | None,
    base: str | None,
    agent: str | None,
    model: str | None,
    board: Board | None,
    interactive: bool,
    timeout: float,
    allow: list[str],
    python: str | None,
    on_event: Any = None,
    resolve: Any = None,
) -> Report:
    criteria_text = criteria_path.read_text(encoding="utf-8")
    criteria = parse_criteria(criteria_text)
    message = read_claims(claims_path)
    if not message.text.strip():
        raise typer.BadParameter(f"no agent message found in {claims_path}")
    if diff_path and base:
        raise typer.BadParameter("use --diff or --base, not both")
    diff = diff_path.read_text(encoding="utf-8") if diff_path else (git_diff(repo, base) if base else "")
    who = agent or (f"claude-code/{message.model}" if message.model else "unknown")
    llm = make_llm(resolve_model(model))
    allowlist = tuple(dict.fromkeys((*DEFAULT_ALLOWLIST, *allow)))
    kwargs: dict[str, Any] = {}
    if python:  # a relative interpreter path means relative to where you ran cross-exam, not the copy
        kwargs["python"] = str(Path(python).absolute()) if ("/" in python or "\\" in python) else python
    with Sandbox(repo, diff=diff, allowlist=allowlist, timeout=timeout, **kwargs) as sandbox:
        deps = ExamDeps(llm=llm, sandbox=sandbox, board=board, interactive=interactive, node_timeout=timeout + 30)
        if on_event is not None:
            deps.on_event = on_event
        return asyncio.run(
            examine(
                deps,
                criteria=criteria,
                summary=message.text,
                diff=diff,
                agent=who,
                task=task_name(criteria_text, criteria_path.stem),
                resolve=resolve or (ask_human if interactive else None),
            )
        )


@app.command()
def check(
    criteria: Annotated[
        Path,
        typer.Option(
            "--criteria",
            "-c",
            exists=True,
            dir_okay=False,
            help="Acceptance criteria (markdown checklist or issue body).",
        ),
    ],
    claims: Annotated[
        Path,
        typer.Option(
            "--claims",
            "-m",
            exists=True,
            dir_okay=False,
            help="Agent's final message (.md/.txt) or a Claude Code session (.jsonl).",
        ),
    ],
    repo: Annotated[
        Path, typer.Option("--repo", "-r", exists=True, file_okay=False, help="Repo the agent worked in.")
    ] = Path("."),
    diff: Annotated[
        Path | None, typer.Option("--diff", exists=True, dir_okay=False, help="Unified diff of the agent's change.")
    ] = None,
    base: Annotated[str | None, typer.Option("--base", help="Compute the diff with `git diff BASE` in --repo.")] = None,
    agent: Annotated[
        str | None, typer.Option("--agent", help="Name for the examined agent/model on the board.")
    ] = None,
    model: Annotated[str | None, typer.Option("--model", help="Examiner model (provider:id) or 'fake'.")] = None,
    db: DbOpt = DEFAULT_DB,
    no_record: Annotated[bool, typer.Option("--no-record", help="Do not add this run to the board.")] = False,
    interactive: Annotated[
        bool, typer.Option("--interactive", "-i", help="Ask a human to overrule UNVERIFIABLE verdicts.")
    ] = False,
    timeout: Annotated[float, typer.Option("--timeout", help="Seconds per check.")] = 60.0,
    allow: Annotated[
        list[str] | None, typer.Option("--allow", help="Extra program for run_command (repeatable).")
    ] = None,
    python: Annotated[str | None, typer.Option("--python", help="Python used to run the repo's tests.")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the report as JSON.")] = False,
    strict: Annotated[
        bool, typer.Option("--strict/--no-strict", help="Exit 1 on a contradicted claim or skipped criterion.")
    ] = True,
) -> None:
    """Split the agent's summary into claims, verify each one, and report per-criterion verdicts."""
    board = None if no_record else Board(db)
    try:
        report = run_check(
            criteria_path=criteria, claims_path=claims, repo=repo, diff_path=diff, base=base, agent=agent,
            model=model, board=board, interactive=interactive, timeout=timeout, allow=allow or [], python=python,
        )  # fmt: skip
    except ValueError as exc:
        err.print(f"[red]error:[/] {escape(str(exc))}")
        raise typer.Exit(2) from exc
    finally:
        if board is not None:
            board.close()
    if as_json:
        print(report.model_dump_json(indent=2))
    else:
        print_report(report)
    if strict and not report.honest:
        raise typer.Exit(1)


@app.command("board")
def board_cmd(
    db: DbOpt = DEFAULT_DB,
    history: Annotated[int, typer.Option("--history", help="Also list the last N runs.")] = 0,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Lie rate and skip rate per agent/model across every recorded run."""
    if not db.exists():
        err.print(f"no board at {db} yet: run `cross-exam check` first")
        raise typer.Exit(1)
    b = Board(db)
    try:
        rows, runs = b.board(), (b.history(limit=history) if history else [])
    finally:
        b.close()
    if as_json:
        print(json.dumps({"board": rows, "history": runs}, indent=2))
        return
    print_board(rows)
    if runs:
        h = Table(title="Recent runs", title_justify="left")
        for col in ("id", "when", "agent", "task", "claims", "false", "skipped", "overclaim"):
            h.add_column(col)
        for r in runs:
            when = datetime.fromtimestamp(r["ts"], UTC).strftime("%Y-%m-%d %H:%M")
            h.add_row(str(r["id"]), when, escape(r["agent"]), escape(r["task"]), str(r["claims"]),
                      str(r["contradicted"]), str(r["skipped"]), f"{r['overclaim']:.2f}")  # fmt: skip
        console.print(h)


def print_board(rows: list[dict[str, Any]]) -> None:
    t = Table(title="Scoreboard (lower is better)", title_justify="left")
    for col, just in (("agent", "left"), ("runs", "right"), ("claims", "right"), ("lie rate", "right"),
                      ("skip rate", "right"), ("scope creep", "right"), ("unverifiable", "right"),
                      ("overruled", "right"), ("overclaim", "right")):  # fmt: skip
        t.add_column(col, justify=just)  # type: ignore[arg-type]
    for r in rows:
        t.add_row(
            escape(r["agent"]), str(r["runs"]), str(r["claims"]), _pct(r["lie_rate"]), _pct(r["skip_rate"]),
            str(r["scope_creep"]), str(r["unverifiable"]), str(r["overruled"]), f"{r['overclaim']:.2f}",
        )  # fmt: skip
    console.print(t)


@app.command()
def demo(
    interactive: Annotated[
        bool, typer.Option("--interactive", "-i", help="Overrule the UNVERIFIABLE claim yourself.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    keep: Annotated[
        Path | None, typer.Option("--keep", help="Write the demo files here instead of a temp dir.")
    ] = None,
) -> None:
    """Offline demo: a scripted agent says "All tests pass" while one test fails."""
    with tempfile.TemporaryDirectory(prefix="cross-exam-demo-") as tmp:
        dest = keep or Path(tmp)
        files = fixture.build(dest)
        board = Board()
        report = run_check(
            criteria_path=files["criteria"], claims_path=files["transcript"], repo=files["repo"],
            diff_path=files["diff"], base=None, agent=None, model="fake", board=board, interactive=interactive,
            timeout=60.0, allow=[], python=None,
        )  # fmt: skip
        rows = board.board()
        board.close()
    if as_json:
        print(json.dumps({"report": report.model_dump(), "board": rows}, indent=2))
        return
    if keep:
        console.print(f"[dim]demo files in {keep}[/]")
    print_report(report)
    console.print()
    print_board(rows)


@app.command()
def graph() -> None:
    """Print the graph as Mermaid."""
    from cross_exam.graphs import mermaid

    print(mermaid())


@app.command()
def version() -> None:
    """Print the version."""
    print(__version__)
