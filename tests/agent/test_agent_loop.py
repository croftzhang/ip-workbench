"""Release 2, build step 3: the loop on the mock model (docs/AGENT_DESIGN.md, AD-4, AD-6, AD-7).

The four kinds of request, a blocked answer and the proposal label, as the
build plan asks; then the budget, the refusal path and the run log. The mock
model replies from a script, so these tests show that the loop, the check and
the log work. They say nothing about how well a real model chooses tools.
"""

import dataclasses
import json

import pytest

graph = pytest.importorskip("ipw.agent.graph", reason='needs the agent extra: pip install -e ".[agent]"')
models = pytest.importorskip("ipw.agent.models")
retrieval = pytest.importorskip("ipw.agent.retrieval")
runlog = pytest.importorskip("ipw.agent.runlog")
messages = pytest.importorskip("langchain_core.messages")


def tool_call(name: str, **arguments):
    """A reply of the mock model that asks for one tool."""
    return messages.AIMessage(
        content="", tool_calls=[{"name": name, "args": arguments, "id": f"call-{name}"}]
    )


def say(text: str):
    """A reply of the mock model that is a draft answer."""
    return messages.AIMessage(content=text)


@pytest.fixture
def assistant(wb, agent_config, knowledge_base, tmp_path):
    """A factory: the loop on a scripted model, with the knowledge base and a run log in a temporary file."""

    def build(script, config=agent_config, with_knowledge_base=True):
        model = models.ScriptedChatModel(script=script)
        retriever = retrieval.Retriever(knowledge_base, config.retrieval) if with_knowledge_base else None
        built = graph.Assistant(wb, config, model, retriever, runlog.RunLog(tmp_path / "runs.jsonl"))
        built.model = model  # the tests look at what the model was sent
        return built

    return build


BREAKDOWN = {"scenario": "up_200", "by": "designation"}
GAP = {
    "operation": "difference",
    "label": "HTM less AFS",
    "cells": [
        {"result": "r1", "row": "HTM", "column": "d_value_mm"},
        {"result": "r1", "row": "AFS", "column": "d_value_mm"},
    ],
}
PLAYBOOK = [
    tool_call("limit_status"),
    tool_call("scenario_breakdown", scenario="up_200", by="bucket"),
    tool_call("top_positions", metric="dv01_k"),
    tool_call("key_rate_report"),
    tool_call("explain_change"),
    tool_call("limit_remedy", limit="AOCI_UP200"),
]
FINDINGS = (
    "AOCI_UP200 is in BREACH: -225.99 against a floor of -210.00. The policy allows a loss of at most "
    "USD 210 million [IPS 4.3]. A PAY_FIXED 5Y swap of 260.0 brings the limit to -209.40."
)


# --------------------------------------------------------------------------- the graph


def test_the_graph_is_four_nodes_joined_as_the_design_draws_them(assistant):
    drawn = assistant([]).graph.get_graph()
    assert set(drawn.nodes) == {"__start__", "retrieve", "model", "tools", "check", "__end__"}
    assert {(edge.source, edge.target) for edge in drawn.edges} == {
        ("__start__", "retrieve"),
        ("retrieve", "model"),
        ("model", "tools"),
        ("tools", "model"),
        ("model", "check"),
        ("check", "model"),  # the one redraft
        ("check", "__end__"),
    }


# --------------------------------------------------------------------------- the four kinds of request


def test_a_routine_question_is_one_tool_call_and_a_checked_answer(assistant, wb):
    loop = assistant(
        [tool_call("risk_report", by="designation"), say("Net effective duration is 5.30 years.")]
    )
    answer = loop.ask("What is net duration?")
    assert (answer.status, answer.proposal) == ("answered", False)
    assert answer.text == "Net effective duration is 5.30 years."
    assert [result.tool for result in answer.results] == ["risk_report"] and answer.model_calls == 2
    assert [draft.check.ok for draft in answer.drafts] == [True]
    assert answer.as_of == wb.market.as_of.isoformat() and len(answer.run_id) == 12

    first, second = loop.model.calls
    assert first["tools"] and second["tools"]  # the tools are offered while the budget lasts
    system, question = first["messages"]
    assert "The market date is 2026-11-09." in system.content and "Never calculate." in system.content
    assert (
        "call the tool that reports the measure and give the figure. A definition alone is not"
        in system.content
    )
    assert "call the aggregate tool; if you do not, leave that figure out." in system.content
    assert "You may make at most 8 tool calls" in system.content
    assert question.content == "What is net duration?"
    reply = second["messages"][-1]  # the model reads the result as text, with its id
    assert (
        reply.type == "tool"
        and reply.content == answer.results[0].to_text()
        and reply.content.startswith("result r1:")
    )


def test_a_composed_analysis_uses_several_tools_and_aggregate(assistant):
    loop = assistant(
        [
            tool_call("scenario_breakdown", **BREAKDOWN),
            tool_call("aggregate", **GAP),
            say("In the +200bp scenario HTM securities lose 158.9 more than AFS securities."),
        ]
    )
    answer = loop.ask("How much more do HTM securities lose than AFS securities in a +200bp shock?")
    assert answer.status == "answered" and [result.tool for result in answer.results] == [
        "scenario_breakdown",
        "aggregate",
    ]
    gap = answer.results[1].table().rows["HTM less AFS"]["value"]
    assert f"{abs(gap):.1f}" == "158.9"  # the figure of the answer is the cell aggregate produced


def test_a_question_about_the_documents_is_answered_from_passages_with_a_citation(assistant):
    loop = assistant(
        [say("The after-tax AOCI loss in a 200bp rise may not exceed USD 210 million [IPS 4.3].")]
    )
    answer = loop.ask("Which limit applies to the after-tax AOCI loss in a 200bp sell-off?")
    assert answer.status == "answered" and answer.results == () and answer.retrieval.covered
    assert answer.hits[0].passage.ref == "IPS 4.3" and len(answer.hits) == 4
    system = loop.model.calls[0]["messages"][0].content
    assert "Passages from the knowledge base:\n\n[IPS 4.3]\nInvestment Policy Statement > " in system
    assert "may not be a loss of more than USD 210 million" in " ".join(system.split())


def test_an_investigation_follows_the_playbook_and_is_labelled_a_proposal(assistant):
    loop = assistant([*PLAYBOOK, say(FINDINGS)])
    answer = loop.investigate("AOCI_UP200")
    assert answer.status == "answered" and answer.proposal
    assert answer.text.splitlines()[0] == "Indicative only: not approved, no action taken."
    assert answer.text.endswith(FINDINGS)
    assert [result.tool for result in answer.results] == [
        "limit_status",
        "scenario_breakdown",
        "top_positions",
        "key_rate_report",
        "explain_change",
        "limit_remedy",
    ]
    assert answer.question == "Investigate the limit AOCI_UP200"
    steps = [line for line in answer.task.splitlines() if line[:2] in {f"{n}." for n in range(1, 8)}]
    assert len(steps) == 7 and steps[1].startswith("2. scenario_breakdown for scenario up_200")
    assert steps[5] == "6. The policy clause IPS 4.3, from the passages."
    assert (
        answer.hits[0].passage.ref == "IPS 4.3" and answer.hits[0].similarity is None
    )  # the clause is always given
    assert loop.model.calls[0]["messages"][1].content == answer.task


def test_the_playbook_fits_any_limit(wb, assistant):
    limits = {limit.id: limit for limit in wb.limits}
    assert "2. risk_report by bucket" in graph.playbook(
        limits["DUR_BAND"]
    )  # a limit measured on today's market
    assert "6. The policy clause IPS 3.2, from the passages." in graph.playbook(limits["HTM_SHARE"])
    with pytest.raises(KeyError, match="unknown limit 'AOCI_UP300'; limits: DUR_BAND"):
        assistant([]).investigate("AOCI_UP300")


# --------------------------------------------------------------------------- the check in the loop


def test_a_draft_that_fails_is_redrafted_once_with_the_list_of_problems(assistant):
    loop = assistant(
        [
            tool_call("limit_status"),
            say("AOCI_UP200 is breached: the loss is 1.076 times its floor."),  # the model's own division
            say("AOCI_UP200 is in BREACH: -225.99 against a floor of -210.00."),
        ]
    )
    answer = loop.ask("Is the AOCI limit breached, and by how much?")
    assert (
        answer.status == "answered"
        and answer.text == "AOCI_UP200 is in BREACH: -225.99 against a floor of -210.00."
    )
    assert [draft.check.ok for draft in answer.drafts] == [False, True]
    assert [problem.text for problem in answer.drafts[0].check.problems] == ["1.076"]
    feedback = loop.model.calls[2]["messages"][-1]
    assert feedback.type == "human" and feedback.content == answer.drafts[0].check.feedback()
    assert (
        "- 1.076: not a figure of any tool result. Leave it out, or call the aggregate tool"
        in feedback.content
    )


def test_an_answer_that_fails_twice_is_blocked_and_only_the_tool_results_are_shown(assistant):
    loop = assistant(
        [tool_call("limit_status"), say("The loss is 300.5 million."), say("The loss is 999 million.")]
    )
    answer = loop.ask("How large is the AOCI loss?")
    assert answer.status == "blocked"
    assert answer.text == (
        "The draft answer did not pass the check of its figures and citations, so it is not shown. "
        "The tool results follow."
    )
    assert "300.5" not in answer.text and "999" not in answer.text  # never the unverified text
    assert [draft.check.ok for draft in answer.drafts] == [False, False] and answer.model_calls == 3
    assert [result.tool for result in answer.results] == ["limit_status"]

    nothing = assistant([say("It is 12345."), say("It is 67890.")]).ask("How large is it?")
    assert nothing.status == "blocked" and nothing.text == graph.BLOCKED and nothing.results == ()


def test_a_proposal_is_labelled_by_code_whatever_the_model_writes(assistant):
    sized = assistant([tool_call("size_hedge", target_duration=4.5), say("A pay-fixed swap is sized.")])
    assert sized.ask("Size a hedge to a duration of 4.5").text.startswith(graph.PROPOSAL_LABEL + "\n\n")
    whatif = assistant(
        [tool_call("what_if", drop=["FN30-2.5-001"]), say("Wrong: 1.23."), say("Still wrong: 4.56.")]
    )
    blocked = whatif.ask("What if FN30-2.5-001 is sold?")
    assert blocked.status == "blocked" and blocked.proposal and blocked.text.startswith(graph.PROPOSAL_LABEL)
    refused = assistant([tool_call("limit_remedy", limit="NII_UP100"), say("That limit is not breached.")])
    answer = refused.ask("Fix NII_UP100")  # the engine refused, so nothing was proposed
    assert not answer.proposal and answer.text == "That limit is not breached." and answer.results == ()
    assert [call.error for call in answer.calls] == [
        "limit NII_UP100 is not breached; pass a target value to size a hedge anyway"
    ]


def test_a_thinking_block_never_reaches_the_answer(assistant):
    loop = assistant(
        [tool_call("limit_status"), say("<think>notes 777</think>Net effective duration is 5.30 years.")]
    )
    assert loop.ask("What is net duration?").text == "Net effective duration is 5.30 years."


# --------------------------------------------------------------------------- budget and errors


def test_after_eight_tool_calls_the_model_must_answer_with_what_it_has(assistant):
    loop = assistant([*[tool_call("limit_status")] * 8, say("AOCI_UP200 is in BREACH at -225.99.")])
    answer = loop.ask("Keep looking at the limits")
    assert answer.status == "answered" and len(answer.calls) == 8 and answer.model_calls == 9
    assert [call["tools"] for call in loop.model.calls] == [True] * 8 + [
        False
    ]  # no tools once the budget is spent
    last = loop.model.calls[-1]["messages"][-1]
    assert (
        last.type == "human"
        and last.content == "The tool budget is used up. Answer now from the results you have."
    )


def test_tool_calls_beyond_the_budget_are_not_run(assistant, agent_config):
    small = dataclasses.replace(
        agent_config, assistant=dataclasses.replace(agent_config.assistant, tool_calls=2)
    )
    three = messages.AIMessage(
        content="",
        tool_calls=[{"name": "limit_status", "args": {}, "id": f"call-{n}"} for n in range(3)],
    )
    loop = assistant([three, say("AOCI_UP200 is in BREACH at -225.99.")], config=small)
    answer = loop.ask("Look three times")
    assert [call.id for call in answer.calls] == ["r1", "r2"] and answer.status == "answered"
    replies = [m.content for m in loop.model.calls[1]["messages"] if m.type == "tool"]
    assert replies[2] == "not run: the budget of 2 tool calls is used up"
    assert "You may make at most 2 tool calls" in loop.model.calls[0]["messages"][0].content


def test_a_rejected_tool_call_goes_back_to_the_model_as_data(assistant):
    loop = assistant(
        [
            tool_call("portfolio_summary", by="sector"),
            tool_call("no_such_tool"),
            tool_call("portfolio_summary", by="bucket"),
            say("Total market value is 8,909.3."),
        ]
    )
    answer = loop.ask("What is the market value of the portfolio?")
    assert answer.status == "answered" and [call.ok for call in answer.calls] == [False, False, True]
    assert [result.id for result in answer.results] == ["r3"]
    told = [m.content for m in loop.model.calls[2]["messages"] if m.type == "tool"]
    assert "error: invalid arguments: by: Input should be 'bucket'" in told[0]
    assert "error: unknown tool 'no_such_tool'" in told[1]


def test_a_tool_call_written_out_as_text_is_run_as_a_tool_call(assistant):
    """Small local models sometimes spell a call out as JSON in the reply instead of returning a call."""
    loop = assistant(
        [
            say('<tool_call>\n{"name": "risk_report", "arguments": {"by": "designation"}}\n</tool_call>'),
            say('```json\n{"name": "limit_status", "parameters": {}}\n```'),
            say("Net effective duration is 5.30 years and AOCI_UP200 is in BREACH."),
        ]
    )
    answer = loop.ask("What is net duration, and is any limit breached?")
    assert answer.status == "answered" and [result.tool for result in answer.results] == [
        "risk_report",
        "limit_status",
    ]
    assert answer.results[0].arguments == {"by": "designation"} and len(answer.drafts) == 1

    known = {"risk_report", "limit_status"}
    assert (
        graph.written_tool_calls('{"name": "limit_status", "arguments": {}}', known)[0]["name"]
        == "limit_status"
    )
    for not_a_call in (
        "Net duration is 5.30 years.",
        'I would call {"name": "limit_status", "arguments": {}} next.',  # prose around it: an answer
        '<tool_call>{"name": "delete_everything", "arguments": {}}</tool_call>',  # not a tool that exists
        '<tool_call>{"name": "limit_status", "arguments": "all"}</tool_call>',
        "<tool_call>{not json}</tool_call>",
        "{}",
    ):
        assert graph.written_tool_calls(not_a_call, known) == [], not_a_call


# --------------------------------------------------------------------------- refusal


def test_a_question_the_knowledge_base_does_not_cover_gets_no_passages(assistant):
    loop = assistant([say("The knowledge base does not cover this.")])
    answer = loop.ask("Wie spaet ist es jetzt?")
    assert answer.status == "answered" and answer.text == "The knowledge base does not cover this."
    assert not answer.retrieval.covered and answer.hits == ()
    system = loop.model.calls[0]["messages"][0].content
    assert system.endswith("Passages from the knowledge base: none. No passage matches this question.")
    assert 'reply: "The knowledge base does not cover this."' in system


def test_a_citation_cannot_be_invented_when_nothing_was_retrieved(assistant):
    loop = assistant([say("The limit is set in [IPS 4.3]."), say("The knowledge base does not cover this.")])
    answer = loop.ask("Wie spaet ist es jetzt?")
    assert [draft.check.ok for draft in answer.drafts] == [False, True]
    assert answer.drafts[0].check.problems[0].detail == (
        "not a passage of this answer; cite only: none: no passage was retrieved"
    )


def test_the_loop_runs_without_a_knowledge_base(assistant):
    loop = assistant([tool_call("limit_status"), say("DUR_BAND is at 5.30.")], with_knowledge_base=False)
    answer = loop.ask("Where is the duration limit?")
    assert answer.status == "answered" and answer.hits == () and answer.retrieval.method == "none"


# --------------------------------------------------------------------------- the run log


def test_every_run_is_one_line_of_the_log_with_what_the_design_lists(assistant, agent_config):
    loop = assistant([*PLAYBOOK, say("The loss is 1.076 times its floor."), say(FINDINGS)])
    answer = loop.investigate("AOCI_UP200")
    second = assistant([say("The knowledge base does not cover this.")]).ask("Wie spaet ist es jetzt?")

    lines = loop.log.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and loop.log.read() == [json.loads(line) for line in lines]
    first, last = loop.log.read()
    assert (first["run_id"], last["run_id"]) == (answer.run_id, second.run_id)
    assert first["time"].endswith("+00:00") and first["market_date"] == "2026-11-09"
    assert first["question"] == "Investigate the limit AOCI_UP200" and first["task"] == answer.task

    assert [(call["result"], call["tool"], call["ok"]) for call in first["tool_calls"]] == [
        (f"r{n}", result.tool, True) for n, result in enumerate(answer.calls, start=1)
    ]
    assert [call["hash"] for call in first["tool_calls"]] == [result.digest() for result in answer.calls]
    assert first["tool_calls"][5]["arguments"] == {"limit": "AOCI_UP200", "tenors": [2.0, 5.0, 10.0]}

    found = first["retrieval"]
    assert found["method"] == "vector" and found["refuse_below"] == 0.15
    assert found["passages"][0] == {"id": "IPS 4.3#1", "ref": "IPS 4.3", "score": 0.0, "similarity": None}
    assert all(0.0 < passage["similarity"] <= 1.0 for passage in found["passages"][1:])

    assert first["models"] == {
        "chat": {
            "model": "qwen3:8b",
            "temperature": 0.0,
            "seed": 42,
            "num_ctx": 16384,
            "num_predict": 2048,
            "reasoning": False,
        },
        "embedding": {"provider": "hashing", "model": "nomic-embed-text"},
    }
    assert [(draft["passed"], [p["text"] for p in draft["problems"]]) for draft in first["drafts"]] == [
        (False, ["1.076"]),
        (True, []),
    ]
    assert first["drafts"][1]["text"] == FINDINGS and first["answer"] == answer.text
    assert (first["status"], first["proposal"], first["model_calls"]) == ("answered", True, 8)
    assert (last["status"], last["proposal"], last["tool_calls"], last["retrieval"]["covered"]) == (
        "answered",
        False,
        [],
        False,
    )


def test_the_same_tool_call_gives_the_same_hash_and_a_different_one_does_not(wb):
    tools = pytest.importorskip("ipw.agent.tools")
    toolbox = tools.Toolbox(wb)
    first, again, other = (
        toolbox.call("scenario_breakdown", BREAKDOWN),
        toolbox.call("scenario_breakdown", BREAKDOWN),
        toolbox.call("scenario_breakdown", {**BREAKDOWN, "scenario": "up_100"}),
    )
    assert first.digest() == again.digest() != other.digest() and len(first.digest()) == 16
    assert toolbox.call("position_detail", {"position_id": "NOPE"}).digest() != first.digest()
