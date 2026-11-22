"""Pick the examiner model from flags and environment. No key means the scripted fake: fully offline."""

from __future__ import annotations

import os

from cross_exam.llm.port import LLM

DEFAULT_ANTHROPIC_MODEL = "anthropic:claude-sonnet-5-5"


def resolve_model(flag: str | None = None, env: dict[str, str] | None = None) -> str:
    """``--model`` > ``CROSS_EXAM_MODEL`` > Anthropic default if a key exists > ``fake``."""
    env = dict(os.environ) if env is None else env
    for value in (flag, env.get("CROSS_EXAM_MODEL")):
        if value:
            return value
    if env.get("ANTHROPIC_API_KEY"):
        return DEFAULT_ANTHROPIC_MODEL
    return "fake"


def make_llm(model: str) -> LLM:
    if model == "fake":
        from cross_exam.llm.demo_script import demo_llm

        return demo_llm()
    from cross_exam.llm.real import LangChainLLM

    return LangChainLLM(model)
