# Usage

## `cross-exam check`

```text
cross-exam check --criteria FILE --claims FILE [--repo DIR] [--diff FILE | --base REF] [options]
```

| option | meaning |
| --- | --- |
| `--criteria, -c` | acceptance criteria: a markdown checklist or issue body. With any `- [ ]` boxes, only boxes count; otherwise every bullet or numbered item does. Code blocks are ignored. |
| `--claims, -m` | the agent's final message (`.md`, `.txt`) or a Claude Code session (`.jsonl`: the last assistant text is used, and its `model` names the agent) |
| `--repo, -r` | the repo the agent worked in (default `.`); checks run in a temp copy of it |
| `--diff` | a unified diff of the agent's change |
| `--base` | compute the diff with `git diff BASE` in `--repo` (working tree vs BASE, so uncommitted work counts) |
| `--agent` | name on the scoreboard (default `claude-code/<model>` from a transcript, else `unknown`) |
| `--model` | examiner model: `anthropic:<id>`, `openai:<id>`, `openrouter:<vendor>/<id>`, or `fake` |
| `--timeout` | seconds per check (default 60); a slow test suite needs more |
| `--allow PROG` | add a program to the `run_command` allowlist (repeatable) |
| `--python` | interpreter used for `run_test` (e.g. the repo's `.venv/bin/python`) |
| `--interactive, -i` | ask a human to overrule UNVERIFIABLE verdicts |
| `--db` | scoreboard database (default `.cross-exam/board.db`); `--no-record` skips it |
| `--json` | print the full report as JSON |
| `--strict/--no-strict` | exit 1 on a contradicted claim or skipped criterion (default on) |

Exit codes: `0` the claim holds up (or `--no-strict`), `1` contradicted or skipped, `2` bad input.

Default `run_command` allowlist: `pytest ruff mypy ls wc grep cat head`.

## `cross-exam board`

```text
cross-exam board [--db FILE] [--history N] [--json]
```

Per agent: runs, claims, lie rate, skip rate, scope creep, unverifiable, overruled, mean overclaim.
Rates are pooled over all runs (total contradicted / total checkable), not averaged per run.

## `cross-exam demo`

Offline. `-i` to overrule the UNVERIFIABLE claim yourself, `--json` for the report, `--keep DIR` to
keep the generated repo and inputs.

## Models

No key and no `--model` means `fake`: scripted on the demo, a simple heuristic elsewhere. Model
choice: `--model` > `CROSS_EXAM_MODEL` > `anthropic:claude-sonnet-5-5` if `ANTHROPIC_API_KEY` is
set > `fake`. `OPENAI_BASE_URL` points `openai:` models at any OpenAI-compatible endpoint.

## The JSON report

```json
{
  "agent": "claude-code/scripted-agent",
  "examiner": "fake",
  "task": "add slugify() to slugkit",
  "claims": [{"claim": {"id": "K2", "quote": "All tests pass.", "criteria": ["C2"],
              "check": {"tool": "run_test", "target": "", "expect": "pass"}},
              "verdict": "CONTRADICTED",
              "evidence": {"summary": "the whole test suite: 1 failed, 3 passed", "exit_code": 1}}],
  "criteria": [{"criterion": {"id": "C3", "text": "Document `slugify()` in the README"},
                "verdict": "SKIPPED", "claims": []}],
  "scope_creep": ["K3"],
  "dropped": [],
  "scores": {"lie_rate": 0.3333, "skip_rate": 0.3333, "overclaim": 0.375}
}
```

(trimmed; every field is in `models.Report`.)
