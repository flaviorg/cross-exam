# Contributing

Thanks for taking a look. Issues and pull requests are welcome.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
make check        # ruff, format check, tests, graph-diagram drift check
```

Everything runs offline. The tests build the synthetic `slugkit` demo repo
(`src/cross_exam/fixture.py`) and use the scripted examiner in `src/cross_exam/llm/`.

## Ground rules

- **The model proposes; code decides.** The model only extracts claims, maps them and picks a
  check from the fixed menu. Verdicts live in `verifiers.py`, criterion verdicts and scores in
  `scoring.py`. Never let a model output become a verdict.
- **Fail closed.** Anything that goes wrong while checking is `UNVERIFIABLE`, never `VERIFIED`.
- **New verifier tools** need a sandbox story (paths stay inside the copy, no shell, timeouts, no
  secrets in the environment) and tests for the refusals as well as the happy path.
- **Keep the fake deterministic.** Scripted rules match prompt text, never call order.
- **If you change the graph,** run `python scripts/gen_graph.py` so the README and
  `docs/architecture.md` show the new diagram (CI checks this). If you change the demo fixture,
  regenerate `examples/demo/` with `cross-exam demo --keep examples/demo`.
- Keep pull requests focused, and add a line to `CHANGELOG.md` under an `Unreleased` heading.
