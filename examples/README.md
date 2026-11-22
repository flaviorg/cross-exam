# Examples

## `demo/`

The inputs `cross-exam demo` generates, so you can run the check by hand:

```bash
cross-exam check -c examples/demo/criteria.md -m examples/demo/session.jsonl \
  -r examples/demo/repo --diff examples/demo/change.diff --model fake
```

- `repo/`: `slugkit` right after the scripted agent's change (one of its tests fails on purpose)
- `criteria.md`: the task's acceptance criteria
- `summary.md` / `session.jsonl`: the agent's final message, as markdown and as a Claude Code session
- `change.diff`: the agent's change

These files are generated from `src/cross_exam/fixture.py`, and a test checks they match it.

## `hooks/stop_hook.py`

A Claude Code Stop hook. See the docstring and the README section "Claude Code Stop hook".
