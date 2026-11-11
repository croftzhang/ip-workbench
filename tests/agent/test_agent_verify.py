"""Release 2, build step 3: the check on a draft answer (docs/AGENT_DESIGN.md, AD-6).

Every figure of a draft has to come from a tool result of the run, from the
question, or from a passage the draft cites; every citation has to refer to a
passage of the run. The drafts below are checked against real tool results.
"""

import pytest

verify = pytest.importorskip("ipw.agent.verify", reason='needs the agent extra: pip install -e ".[agent]"')
tools = pytest.importorskip("ipw.agent.tools")
kb = pytest.importorskip("ipw.agent.kb")
retrieval = pytest.importorskip("ipw.agent.retrieval")

CODES = ["IPS", "HEDGE", "ACCT", "SCEN", "MBS", "GLOSS", "SPEC", "MODEL"]
QUESTION = "Why is the AOCI limit breached?"


@pytest.fixture(scope="module")
def results(wb):
    """One run's worth of tool results: limits, a scenario, risk, a remedy and the top positions."""
    toolbox = tools.Toolbox(wb)
    toolbox.call("limit_status")
    toolbox.call("run_scenarios", {"scenarios": ["up_200"]})
    toolbox.call("risk_report", {"by": "bucket"})
    toolbox.call("limit_remedy", {"limit": "AOCI_UP200"})
    toolbox.call("top_positions", {"metric": "dv01_k", "count": 5})
    toolbox.call("position_detail", {"position_id": "NOPE"})  # an error result: it supports nothing
    return toolbox.results


def passage(ref: str, text: str):
    return retrieval.Hit(kb.Passage(f"{ref}#1", ref, "Document", ref.split()[1], "", text), 0.8, 0.8)


IPS = passage(
    "IPS 4.3",
    "In an instantaneous parallel rise of 200bp, the after-tax change in AOCI may not be a loss of more "
    "than USD 210 million (limit AOCI_UP200).",
)
ACCT = passage("ACCT 3.2", "The analytics apply a tax rate of 24% to the pre-tax change, so 76% remains.")
HITS = [IPS, ACCT]


def problems(draft: str, results, hits=HITS, question: str = QUESTION) -> list[tuple[str, str]]:
    verdict = verify.check(draft, question=question, results=results, hits=hits, codes=CODES)
    assert verdict.ok == (not verdict.problems)
    return [(problem.kind, problem.text) for problem in verdict.problems]


PASSES = [
    "The AOCI_UP200 limit is in BREACH: the change is -225.99 against a floor of -210.00 (utilisation 108%).",
    "AOCI falls by USD 226.0 million in the up_200 scenario (Parallel +200bp), or $226 million after tax.",
    "A loss of 225.99 million; the unicode minus −225.99 and the bracketed (225.99) are the same figure.",
    "The loss is 226.0, which is 15.99 beyond the limit of 210: the headroom is -15.99.",
    "Net effective duration is 5.30 years, or 5.3 years, inside the band of 3.00 to 5.50.",
    "As of 2026-11-09 net duration is 5.30 years. On November 9, 2026 it was reported the same.",
    "1. limit_status shows 1 limit in BREACH out of 9 limits.\n2. Three options were sized.\n3) See step 2.",
    "### 4. Findings\n**5.** The 2nd option is the 5Y swap.\n> 6. Done.",
    "The options are PAY_FIXED 2Y, PAY_FIXED 5Y and PAY_FIXED 10Y; the 5-year swap needs 260.0 of notional.",
    "The 5Y option costs 1.0 of income over the next 12 months; the 12-month NII change is -1.0.",
    "Position FN30-2.5-001 is among the top 5 by dv01_k; see r5. FR-11 specifies the remedy.",
    "The loss may not exceed USD 210 million [IPS 4.3], and the tax rate is 24% [ACCT 3.2].",
    "The limit is set in IPS 4.3 and reported after tax (ACCT 3.2).",
    "Both are cited together [IPS 4.3; ACCT 3.2].",
    'The policy says "the after-tax change in AOCI may not be a loss of more than USD 210 million".',
    "<think>the model's own notes, 123456</think>Net effective duration is 5.30 years.",
    "The knowledge base does not cover this.",
]


@pytest.mark.parametrize("draft", PASSES, ids=lambda draft: draft[:45])
def test_a_draft_that_only_uses_its_sources_passes(results, draft):
    assert problems(draft, results) == []


FAILS = [
    ("The loss is 226.0, which is 1.076 times the limit of 210.", [("figure", "1.076")]),
    ("AFS carries 41.5% of the loss.", [("figure", "41.5")]),
    (
        "Net duration is 5.3 years and would be 4.71 after a swap of 530 million.",
        [("figure", "4.71"), ("figure", "530")],
    ),
    ("The loss is -225.99 and, as said, -999.5; again -999.5.", [("figure", "-999.5")]),  # reported once
    ("The tax rate is 24%.", [("figure", "24")]),  # a figure from a passage needs its citation
    ("See [IPS 9.9] for details.", [("citation", "[IPS 9.9]")]),
    ("HEDGE 5.3 sets the step size.", [("citation", "[HEDGE 5.3]")]),
    ("Cited together [IPS 4.3; MODEL 3].", [("citation", "[MODEL 3]")]),
    ('The policy says "the loss may not exceed USD 300 million".', [("figure", "300")]),  # not a quotation
    ("Position NOPE has a DV01 of 77.7.", [("figure", "77.7")]),  # the failed call supports nothing
    ("", [("empty", "(no answer)")]),
    ("<think>only notes</think>", [("empty", "(no answer)")]),
]


@pytest.mark.parametrize(("draft", "expected"), FAILS, ids=lambda value: str(value)[:45])
def test_a_figure_or_citation_without_a_source_fails(results, draft, expected):
    assert problems(draft, results) == expected


def test_a_figure_is_compared_at_the_precision_the_draft_shows(results):
    # the cell is -225.991168: it supports 226, 226.0 and 225.99, not 225.9 or 226.1
    for written in ("226", "226.0", "225.99", "225.991", "-225.991168"):
        assert problems(f"The change is {written}.", results) == [], written
    for written in ("225.9", "226.1", "225.98", "227"):
        assert problems(f"The change is {written}.", results) == [("figure", written)], written
    assert problems("Market value is 8,909.3, that is 8909.27.", results) == []  # thousands separators


def test_numbers_of_the_question_and_of_tool_arguments_are_not_figures(results):
    assert problems("You asked about 77 and 1,250.", results, question="Compare 77 with 1,250") == []
    assert problems("You asked about 77.", results) == [("figure", "77")]
    assert problems("The top 5 positions were requested, for tenors 2, 5 and 10.", results) == []


def test_a_figure_from_a_passage_is_accepted_only_with_its_citation(results):
    assert problems("The tax rate is 24% [ACCT 3.2].", results) == []
    assert problems("The tax rate is 24% [IPS 4.3].", results) == [("figure", "24")]  # the wrong passage
    told = verify.check("The tax rate is 24%.", question=QUESTION, results=results, hits=HITS, codes=CODES)
    assert "passage [ACCT 3.2]; cite that passage" in told.problems[0].detail
    assert problems("The tax rate is 24% [ACCT 3.2].", results, hits=[IPS]) == [
        ("citation", "[ACCT 3.2]"),
        ("figure", "24"),
    ]


def test_a_section_named_by_a_tool_result_or_the_question_may_be_mentioned(results):
    assert problems("The limit refers to IPS 4.1 and IPS 4.3.", results, hits=[]) == []  # policy_ref cells
    assert problems("IPS 5.3 covers breaches.", results, hits=[]) == [("citation", "[IPS 5.3]")]
    assert problems("IPS 5.3 covers breaches.", results, hits=[], question="What does IPS 5.3 say?") == []
    assert problems("With no passages, [IPS 4.3] cannot be cited.", [], hits=[]) == [
        ("citation", "[IPS 4.3]")
    ]


def test_the_feedback_tells_the_model_what_to_correct(results):
    verdict = verify.check(
        "A loss of 300.5 [IPS 9.9].", question=QUESTION, results=results, hits=HITS, codes=CODES
    )
    assert not verdict.ok
    assert verdict.feedback().splitlines() == [
        "Your draft did not pass the check of its figures and citations. Correct it and answer again.",
        "- [IPS 9.9]: not a passage of this answer; cite only: [IPS 4.3], [ACCT 3.2]",
        "- 300.5: not a figure of any tool result. Leave it out, or call the aggregate tool to obtain it; "
        "do not work it out yourself",
    ]
    assert verify.Check().ok and verify.clean(" <think>x</think> text ") == "text"


def test_a_difference_is_accepted_once_aggregate_has_produced_it(wb):
    toolbox = tools.Toolbox(wb)
    breakdown = toolbox.call("scenario_breakdown", {"scenario": "up_200", "by": "designation"})
    rows = breakdown.table().rows
    gap = abs(rows["HTM"]["d_value_mm"] - rows["AFS"]["d_value_mm"])
    draft = f"HTM securities lose {gap:.1f} more than AFS securities."
    assert problems(draft, toolbox.results, hits=[]) == [
        ("figure", f"{gap:.1f}")
    ]  # the model's own arithmetic
    cells = [{"result": breakdown.id, "row": row, "column": "d_value_mm"} for row in ("HTM", "AFS")]
    assert toolbox.call("aggregate", {"operation": "difference", "cells": cells}).ok
    assert problems(draft, toolbox.results, hits=[]) == []
    assert (
        problems("AFS securities carry 42.0% of the loss.", toolbox.results, hits=[]) == []
    )  # share_pct is a cell
