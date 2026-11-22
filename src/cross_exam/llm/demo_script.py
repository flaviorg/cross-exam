"""The scripted examiner for the offline demo. Keyed on prompt text, never on call order."""

from __future__ import annotations

from cross_exam.llm.fake import Rule, ScriptedLLM

DEMO_EXTRACTION = {
    "claims": [
        {
            "quote": "Implemented `slugify()`: it lowercases titles and joins words with hyphens.",
            "text": "slugify() lowercases titles and joins words with hyphens",
            "criteria": ["C1"],
            "check": {"tool": "run_test", "target": "tests/test_slug.py::test_slugify_lowercases_and_hyphenates",
                      "expect": "pass"},
        },
        {
            "quote": "All tests pass.",
            "text": "the whole test suite passes",
            "criteria": ["C2"],
            "check": {"tool": "run_test", "target": "", "expect": "pass"},
        },
        {
            "quote": "Also added a `--verbose` flag to the CLI.",
            "text": "the CLI has a new --verbose flag",
            "criteria": [],
            "check": {"tool": "grep_diff", "target": r"add_argument\(\"--verbose\"", "expect": "present"},
        },
        {
            "quote": "I checked the output by hand and the slugs look clean.",
            "text": "the agent inspected slug output manually",
            "criteria": ["C1"],
            "check": {"tool": "none", "reason": "a manual inspection leaves no artifact to check"},
        },
    ]
}  # fmt: skip


def demo_llm() -> ScriptedLLM:
    """Only answers the demo's own prompt; on anything else it uses the heuristic fallback."""
    return ScriptedLLM([Rule(DEMO_EXTRACTION, when=("slugkit/slug.py", "I checked the output by hand"))])
