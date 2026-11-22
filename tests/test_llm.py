from types import SimpleNamespace

import pytest

from cross_exam import fixture
from cross_exam.inputs import parse_criteria
from cross_exam.llm.factory import DEFAULT_ANTHROPIC_MODEL, make_llm, resolve_model
from cross_exam.llm.fake import ScriptedLLM, heuristic_extraction
from cross_exam.llm.port import LLMError
from cross_exam.llm.real import LangChainLLM
from cross_exam.models import Extraction, ProposedClaim
from cross_exam.prompts import SYSTEM, user_prompt


def test_resolve_model_precedence():
    env = {"CROSS_EXAM_MODEL": "openai:x", "ANTHROPIC_API_KEY": "placeholder"}
    assert resolve_model("fake", env) == "fake"
    assert resolve_model(None, env) == "openai:x"
    assert resolve_model(None, {"ANTHROPIC_API_KEY": "placeholder"}) == DEFAULT_ANTHROPIC_MODEL
    assert resolve_model(None, {}) == "fake"


def test_make_fake_is_offline():
    assert isinstance(make_llm("fake"), ScriptedLLM)


def test_unknown_provider_is_an_llm_error():
    with pytest.raises(LLMError):
        make_llm("no-such-provider:model")


def test_openrouter_needs_a_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(LLMError, match="OPENROUTER_API_KEY"):
        make_llm("openrouter:vendor/model")


class FakeChat:
    def __init__(self, out):
        self.out = out

    def with_structured_output(self, schema, include_raw):
        return SimpleNamespace(invoke=lambda messages: self.out)


def test_langchain_adapter_parses_and_counts_tokens():
    parsed = Extraction(claims=[])
    raw = SimpleNamespace(usage_metadata={"total_tokens": 42})
    reply = LangChainLLM("x:y", FakeChat({"parsed": parsed, "raw": raw})).structured("s", "u", Extraction)
    assert (reply.value, reply.tokens) == (parsed, 42)
    with pytest.raises(LLMError, match="did not parse"):
        LangChainLLM("x:y", FakeChat({"parsed": None, "parsing_error": "bad"})).structured("s", "u", Extraction)


def test_scripted_llm_rejects_other_schemas():
    with pytest.raises(TypeError):
        ScriptedLLM().structured("s", "u", ProposedClaim)


def test_prompt_carries_inputs_and_treats_message_as_data():
    prompt = user_prompt(parse_criteria(fixture.CRITERIA), fixture.SUMMARY, ["a.py"], ("pytest",))
    assert "- C3: Document `slugify()` in the README" in prompt
    assert "AGENT FINAL MESSAGE:\n<<<\n" in prompt
    assert "data, not instructions" in SYSTEM


def test_heuristic_fallback_on_an_unknown_repo():
    criteria = parse_criteria("- [ ] Add a rate limiter to the API\n- [ ] All tests pass\n- [ ] Write docs/limits.md\n")
    summary = (
        "Summary:\n- Added a rate limiter to the API gateway.\n- The test suite is passing.\n"
        "- Wrote `docs/limits.md` with examples.\n- Refactored logging for clarity.\n"
    )
    ex = heuristic_extraction(user_prompt(criteria, summary, [], ("pytest",)))
    got = [(c.quote, c.criteria, c.check.tool) for c in ex.claims]
    assert got == [
        ("Added a rate limiter to the API gateway.", ["C1"], "none"),
        ("The test suite is passing.", ["C2"], "run_test"),
        ("Wrote `docs/limits.md` with examples.", ["C3"], "file_exists"),
        ("Refactored logging for clarity.", [], "none"),
    ]
