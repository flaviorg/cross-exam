# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-22

### Added

- Cross-examination graph (LangGraph 1.2): `extract` (the only model call) proposes atomic claims,
  the claim → criterion mapping and one check per claim. `Send` fans out one async `verify` branch
  per claim with a node `timeout` and an `error_handler`, so a hung or crashing check only turns its
  own claim UNVERIFIABLE. A deferred `collect` gathers the branches, then `review`, `score` and
  `record` run as plain code.
- Five verifier tools with verdicts decided in code: `run_test` (pytest), `grep_diff` (added lines
  only), `file_exists`, `run_command` (no shell, allowlist) and `http_check` (localhost only). All
  run in a temp copy of the repo with a scrubbed environment and per-check timeouts.
- Guard against invented testimony: a claim whose quote is not in the agent's message is dropped,
  and unknown criterion ids are ignored.
- Deterministic scoring: criteria with no supporting claim are "silently skipped", claims with no
  criterion are "scope creep", plus lie rate, skip rate and an overclaim score.
- Human overrule of UNVERIFIABLE verdicts through `interrupt()`, with the resume value validated
  in code and re-asked on error. CONTRADICTED verdicts cannot be overruled.
- SQLite scoreboard keyed by the examined agent/model, and `cross-exam board` (pooled lie rate and
  skip rate, recent runs).
- Inputs: markdown checklist / issue body criteria, a markdown summary or a Claude Code session
  JSONL, and a diff file or `git diff --base`.
- CLI: `check`, `board`, `demo`, `graph`, `version`. `check` exits 1 on a contradicted claim or a
  skipped criterion.
- Offline demo with a scripted examiner: one true claim, one false ("All tests pass" while a test
  fails), one scope-creep claim, one unverifiable claim and one skipped criterion. A heuristic
  fallback keeps `--model fake` usable on other repos.
- Example Claude Code Stop hook that blocks a false "done" once and hands Claude the list.
- Real examiner models through LangChain: Anthropic, OpenAI or any OpenAI-compatible endpoint,
  OpenRouter.

[0.1.0]: https://github.com/flaviorg/cross-exam/releases/tag/v0.1.0
