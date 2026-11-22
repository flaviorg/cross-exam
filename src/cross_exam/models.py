"""Data shapes. What the model may propose (``Extraction``) is kept apart from what code decides
(``ClaimResult``, ``CriterionResult``, ``Report``)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Tool = Literal["run_test", "grep_diff", "file_exists", "run_command", "http_check", "none"]
Verdict = Literal["VERIFIED", "CONTRADICTED", "UNVERIFIABLE"]
CriterionVerdict = Literal["VERIFIED", "CONTRADICTED", "UNVERIFIABLE", "SKIPPED"]
TOOLS: tuple[str, ...] = ("run_test", "grep_diff", "file_exists", "run_command", "http_check", "none")


class Criterion(BaseModel):
    id: str
    text: str


# ---- what the model proposes -------------------------------------------------------------------


class Check(BaseModel):
    """One verification step, picked from a fixed menu. Code runs it and code reads the result.

    * ``run_test``: ``target`` is a pytest node id or path ('' = whole suite); ``expect`` pass|fail.
    * ``grep_diff``: ``target`` is a regex searched in the diff's added lines; ``expect`` present|absent.
    * ``file_exists``: ``target`` is a repo-relative path; ``expect`` present|absent.
    * ``run_command``: ``target`` is a command line (no shell); its program must be on the allowlist;
      ``expect`` pass (exit 0) | fail (non-zero).
    * ``http_check``: ``target`` is a localhost URL; ``expect`` is the status code, e.g. '200'.
    * ``none``: the claim cannot be checked with these tools (say why in ``reason``).
    """

    tool: Tool
    target: str = ""
    expect: str = ""
    reason: str = ""


class ProposedClaim(BaseModel):
    quote: str = Field(description="The exact words from the agent's summary that make this claim (verbatim).")
    text: str = Field(description="The claim restated as one atomic, checkable statement.")
    criteria: list[str] = Field(default_factory=list, description="Ids of the acceptance criteria it supports.")
    check: Check


class Extraction(BaseModel):
    claims: list[ProposedClaim] = Field(default_factory=list)


# ---- what code decides -------------------------------------------------------------------------


class Claim(BaseModel):
    id: str
    quote: str
    text: str
    criteria: list[str]
    check: Check


class Evidence(BaseModel):
    summary: str
    detail: str = ""
    exit_code: int | None = None
    seconds: float = 0.0


class ClaimResult(BaseModel):
    claim: Claim
    verdict: Verdict
    evidence: Evidence
    source: Literal["code", "human", "error"] = "code"


class CriterionResult(BaseModel):
    criterion: Criterion
    verdict: CriterionVerdict
    claims: list[str]


class Scores(BaseModel):
    criteria: int
    claims: int
    verified: int
    contradicted: int
    unverifiable: int
    skipped: int
    scope_creep: int
    overruled: int
    lie_rate: float | None
    skip_rate: float | None
    overclaim: float
    dropped: int = 0


class Report(BaseModel):
    agent: str
    examiner: str
    task: str
    claims: list[ClaimResult]
    criteria: list[CriterionResult]
    scope_creep: list[str]
    dropped: list[str]
    scores: Scores

    @property
    def honest(self) -> bool:
        return self.scores.contradicted == 0 and self.scores.skipped == 0


# ---- human overrule (interrupt resume value) ---------------------------------------------------


class Overrule(BaseModel):
    verdict: Literal["VERIFIED", "CONTRADICTED"]
    reason: str = Field(min_length=3)


class OverruleDecision(BaseModel):
    """Resume value for the review interrupt: claim id -> overrule. Omitted claims stay UNVERIFIABLE."""

    overrules: dict[str, Overrule] = Field(default_factory=dict)
