"""Release 2, build step 4: the evaluation (docs/AGENT_DESIGN.md, AD-8).

The task set is checked against the engine and against release 1, the scoring
is checked on written examples, and the whole evaluation is run once on the
mock model that follows the reference path of each task. That run shows that
tasks, scoring and report fit together. It says nothing about a real model.
"""

import dataclasses
import json
import re
import shlex
import subprocess

import pytest
from typer.testing import CliRunner

from ipw.agent import cli
from ipw.classic import cli as classic

evals = pytest.importorskip("ipw.agent.evals", reason='needs the agent extra: pip install -e ".[agent]"')
evalreport = pytest.importorskip("ipw.agent.evalreport")
graph = pytest.importorskip("ipw.agent.graph")
kb = pytest.importorskip("ipw.agent.kb")
models = pytest.importorskip("ipw.agent.models")
retrieval = pytest.importorskip("ipw.agent.retrieval")
tools = pytest.importorskip("ipw.agent.tools")
messages = pytest.importorskip("langchain_core.messages")


@pytest.fixture(scope="session")
def tasks(root):
    return evals.load_tasks(root / evals.TASK_SET)


@pytest.fixture(scope="session")
def questions(root):
    return evals.load_retrieval_questions(root / evals.RETRIEVAL_SET)


@pytest.fixture(scope="session")
def specs(wb):
    return {spec.name: spec for spec in tools.Toolbox(wb).specs}


@pytest.fixture(scope="session")
def expected(wb, tasks):
    """The reference pairs of every task, resolved on the engine."""
    return {task.id: evals.resolve(task, tools.Toolbox(wb)) for task in tasks}


def assistant_for(wb, config, knowledge_base, chat, log=None):
    retriever = retrieval.Retriever(knowledge_base, config.retrieval)
    return graph.Assistant(wb, config, chat, retriever, log)


@pytest.fixture(scope="session")
def evaluation(wb, agent_config, knowledge_base, tasks, questions):
    """The whole evaluation, once, on the mock model that follows the reference paths."""
    known = [*tasks, *evals.investigation_tasks(wb)]
    chat = evals.reference_model(known, lambda: tools.Toolbox(wb))
    assistant = assistant_for(wb, agent_config, knowledge_base, chat)
    lines: list[str] = []
    result = evals.evaluate(assistant, knowledge_base, tasks, questions, progress=lines.append)
    meta = evalreport.environment(agent_config, mock=True, as_of=tools.Toolbox(wb).as_of)
    return {"meta": meta} | result | {"progress": lines}


# --------------------------------------------------------------------------- the task set


def test_the_set_is_forty_tasks_in_three_classes_with_a_benchmark_of_thirty(tasks, specs, kb_config):
    assert {kind: sum(task.kind == kind for task in tasks) for kind in evals.CLASSES} == {
        "routine": 20,
        "composed": 10,
        "documents": 10,
    }
    benchmark = [task for task in tasks if task.benchmark]
    assert {kind: sum(task.kind == kind for task in benchmark) for kind in evals.CLASSES} == {
        "routine": 10,
        "composed": 10,
        "documents": 10,
    }
    assert {task.release1 for task in tasks if task.kind == "routine"} == {"one command"}
    assert {task.release1 for task in tasks if task.kind == "composed"} == {"commands and work by hand"}
    assert {task.release1 for task in tasks if task.kind == "documents"} == {"no"}

    sections = {passage.ref for passage in kb.load_passages(kb_config)}
    for task in tasks:
        assert set(task.cites) <= sections, task.id  # a section to cite is a section that exists
        for way in task.calls:
            for call in way:
                specs[call.tool].args.model_validate(call.arguments)  # every accepted call is a valid call
    used = {call.tool for task in tasks for call in task.path}
    assert used == set(specs)  # every tool is needed by some task


def test_every_reference_path_runs_and_every_reference_value_is_read_from_the_engine(wb, tasks, expected):
    for task in tasks:
        assert expected[task.id] and all(item.wording for item in expected[task.id]), task.id
    first = {item.wording: item.values for item in expected["T01"]}
    risk = tools.Toolbox(wb).call("risk_report", {}).table()
    assert first == {"Net eff_duration: 5.30": (risk.rows["Net"]["eff_duration"],)}
    by_rank = expected["T18"]  # three row labels, then the figure of the first row, labelled by that row
    assert [item.wording for item in by_rank[:3]] == ["G230-2.0-003", "G230-2.0-004", "G230-2.0-006"]
    assert by_rank[3].labels == ("G230-2.0-003",) and by_rank[3].wording.startswith(
        "G230-2.0-003 unrealized_mm:"
    )
    assert expected["T07"][0].labels == ()  # a figure without a label is looked for anywhere in the answer
    either = expected["C07"][1]  # the change in income, or income after the trade
    assert either.labels == ("NII", "income") and len(either.values) == 2
    from_a_document = expected["D01"][0]
    assert (from_a_document.values, from_a_document.document, from_a_document.wording) == (
        (210.0,),
        True,
        "AOCI: 210",
    )


def test_a_composed_task_that_copies_a_figure_into_its_next_call_copies_the_right_one(wb, tasks):
    by_id = {task.id: task for task in tasks}
    toolbox = tools.Toolbox(wb)
    evals.resolve(by_id["C06"], toolbox)
    largest_losses, sold = toolbox.results
    assert sold.arguments["drop"] == list(largest_losses.table().rows)
    assert by_id["C06"].classic[1].endswith(",".join(largest_losses.table().rows))

    toolbox = tools.Toolbox(wb)
    evals.resolve(by_id["C07"], toolbox)
    sized, added = toolbox.results
    notional = sized.table("trades").rows["NEW-10Y"]["notional_mm"]
    assert added.arguments["swaps"][0]["notional_mm"] == pytest.approx(notional, abs=0.05)
    assert by_id["C07"].classic[1] == f"ipw whatif --pay-fixed 10:{notional:.1f}"

    toolbox = tools.Toolbox(wb)
    evals.resolve(by_id["C05"], toolbox)
    largest, total = toolbox.results
    assert [cell["row"] for cell in total.arguments["cells"]] == list(largest.table().rows)


def test_release_1_shows_the_figures_of_a_routine_task_with_one_command(root, tasks, expected):
    """And for a composed task it does not, or not with one command: that is what work by hand means."""
    runner = CliRunner()

    def shown_by_release_1(task) -> bool:
        output = ""
        for command in task.classic:
            done = runner.invoke(classic.app, ["--root", str(root), "-f", "json", *shlex.split(command)[1:]])
            assert done.exit_code == 0, f"{task.id}: {command}: {done.output}"
            output += done.output
        printed = [abs(float(number)) for number in re.findall(r"-?\d+\.?\d*(?:e-?\d+)?", output)]

        def has(item) -> bool:
            if not item.values:
                return any(label.lower() in output.lower() for label in item.labels)
            return any(abs(n - abs(v)) <= 1e-6 * max(1.0, abs(v)) for n in printed for v in item.values)

        return all(has(item) for item in expected[task.id])

    for task in tasks:
        if task.kind == "routine":
            assert len(task.classic) == 1 and shown_by_release_1(task), task.id
        elif task.kind == "composed":
            assert task.by_hand and (len(task.classic) > 1 or not shown_by_release_1(task)), task.id
        else:
            assert not task.classic and not task.by_hand, task.id


BAD_TASKS = [
    ("tasks: [{id: X, class: routine, question: q}]", "needs id, class, question and answer"),
    ("tasks: [{id: X, class: other, question: q, answer: [{text: [a]}]}]", "class is one of routine"),
    ("tasks: [{id: X, class: composed, question: q, answer: [{text: [a]}], extra: 1}]", "has the keys"),
    ("tasks: [{id: X, class: routine, question: q, answer: [{text: [a]}]}]", "needs calls and the release 1"),
    ("tasks: [{id: X, class: documents, question: q, answer: [{text: [a]}]}]", "names the sections to cite"),
    (
        "tasks: [{id: X, class: composed, question: q, answer: [{cell: {result: r1, row: a, column: b}}]}]",
        "needs the calls that produce it",
    ),
    (
        "tasks: [{id: X, class: composed, question: q, answer: [{number: 5}]}]",
        "a number item needs a label",
    ),
    (
        "tasks: [{id: X, class: composed, question: q, answer: [{text: [a], number: 5}]}]",
        "exactly one of cell, number, text and rows",
    ),
    (
        "tasks: [{id: X, class: composed, question: q, calls: [[{t: {}}]], "
        "answer: [{cell: {result: r1, row: a, position: 1, column: b}}]}]",
        "either a row or a position",
    ),
    (
        "tasks: [{id: X, class: composed, question: q, classic: [risk], answer: [{text: [a]}]}]",
        "commands that start with ipw",
    ),
    (
        "tasks: [{id: X, class: composed, question: q, answer: [{text: [a]}]}, "
        "{id: X, class: composed, question: other, answer: [{text: [a]}]}]",
        "task ids must be different",
    ),
    ("questions: []", "one list named tasks"),
]


@pytest.mark.parametrize(("text", "message"), BAD_TASKS, ids=[message for _, message in BAD_TASKS])
def test_a_task_file_with_a_mistake_is_rejected_with_the_task_and_the_reason(tmp_path, text, message):
    path = tmp_path / "tasks.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=re.escape(message)) as stop:
        evals.load_tasks(path)
    assert str(stop.value).startswith("tasks.yaml: ")


def test_a_reference_that_the_engine_cannot_give_is_an_error_that_names_the_task(wb, tasks):
    by_id = {task.id: task for task in tasks}

    def broken(**changes):
        return dataclasses.replace(by_id["T01"], **changes)

    no_row = evals.Reference(cells=({"result": "r1", "row": "Gross", "column": "eff_duration"},))
    with pytest.raises(ValueError, match="task T01: result r1 has no figure in row 'Gross'"):
        evals.resolve(broken(answer=(no_row,)), tools.Toolbox(wb))
    no_result = evals.Reference(cells=({"result": "r2", "row": "Net", "column": "eff_duration"},))
    with pytest.raises(ValueError, match="task T01: the reference path has no result 'r2'"):
        evals.resolve(broken(answer=(no_result,)), tools.Toolbox(wb))
    bad_call = ((evals.Call("risk_report", {"by": "nothing"}),),)
    with pytest.raises(
        ValueError, match="task T01: the reference call risk_report failed: invalid arguments"
    ):
        evals.resolve(broken(calls=bad_call), tools.Toolbox(wb))


# --------------------------------------------------------------------------- scoring an answer


def pair(*labels: str, values: tuple[float, ...] = ()) -> "evals.Expected":
    return evals.Expected(tuple(labels), values, "the pair")


CONTAINS = [
    ("Net effective duration is 5.30 years.", pair("duration", values=(5.2996,))),
    ("Net effective duration is 5.3 years.", pair("duration", values=(5.2996,))),  # one decimal shown
    ("The value of the securities falls by USD 992.2 million.", pair(values=(-992.2133,))),  # sign in words
    ("Market value: $8,909.3 million; unrealized loss: (1,240.1).", pair("unrealized", values=(-1240.0534,))),
    ("- **MBS_30Y**: 78.6% of the loss\n- MBS_15Y: 11.0%", pair("15", values=(10.9632,))),  # line by line
    ("| HTM | 4,907.9 |\n| AFS | 4,001.4 |", pair("AFS", "available", values=(4001.3666,))),
    ("The swap needs a notional of 1,614.", pair(values=(1614.0,))),  # a whole number within 1%
    ("NII falls to 101.6.", pair("NII", "income", values=(-1.9938, 101.646))),  # either figure
    ("Two limits need attention: AOCI_UP200 and DUR_BAND.", pair("DUR_BAND", "Net effective duration")),
    ("Remediation is by hedging the available-for-sale book.", pair("AFS", "available-for-sale")),
]

LACKS = [
    ("Net effective duration is about 5 years.", pair("duration", values=(5.2996,))),  # too coarse
    ("Net effective duration is 5.4 years.", pair("duration", values=(5.2996,))),
    ("A 5-year swap is the usual choice.", pair(values=(5.2996,))),
    ("Duration is high. The DV01 is 5.30.", pair("duration", values=(5.2996,))),  # label in another sentence
    ("MBS_30Y: 78.6%\nMBS_15Y: 12.0%", pair("15", values=(10.9632,))),
    ("The limit is breached.", pair("DUR_BAND", "Net effective duration")),
    ("", pair(values=(1.0,))),
]


@pytest.mark.parametrize(("answer", "wanted"), CONTAINS, ids=lambda value: str(value)[:40])
def test_an_answer_contains_a_pair_when_value_and_label_share_a_sentence_or_line(answer, wanted):
    assert evals.contains(answer, wanted)


@pytest.mark.parametrize(("answer", "wanted"), LACKS, ids=lambda value: str(value)[:40])
def test_an_answer_lacks_a_pair_when_the_value_or_its_label_is_not_there(answer, wanted):
    assert not evals.contains(answer, wanted)


def test_a_correct_answer_lacks_nothing_and_a_wrong_one_is_told_what(expected):
    wanted = expected["D05"]  # the tax rate from the accounting note, the AOCI change from a tool
    good = "The analytics apply a tax rate of 24% [ACCT 3.2]. After tax, AOCI changes by -226.0 under up_200."
    assert evals.missing(good, wanted, ["ACCT 3.2", "SPEC FR-8"]) == []
    assert evals.missing(good.replace("[ACCT 3.2]", "(ACCT 3.2)"), wanted, ["ACCT 3.2"]) == []
    assert evals.missing(good.replace("[ACCT 3.2]", "[ACCT 3]"), wanted, ["ACCT 3.2", "SPEC FR-8"]) == [
        "a citation of [ACCT 3.2] or [SPEC FR-8]"
    ]
    assert evals.missing("The tax rate is 24% [ACCT 3.2].", wanted, ["ACCT 3.2"]) == [
        "up_200 d_aoci_mm: -226.0"
    ]
    assert evals.segments("One. Two; three\n- four: 4.5 and five") == [
        "One.",
        "Two;",
        "three",
        "- four: 4.5 and five",
    ]


NATURAL = [
    ("T01", "The net effective duration of the book is **5.30 years**.", True),
    ("T01", "Net effective duration measures the sensitivity of value to rates.", False),  # a definition
    ("T02", "Total market value: 8,909.3\nTotal unrealized: -1,240.1", True),
    ("T02", "The securities have a total market value of USD 8,909.3 million.", False),  # half the answer
    ("T04", "The net key-rate duration is largest at the 20Y point, at 1.95 years.", True),
    ("T04", "It is largest at the 10Y point (1.83).", False),
    ("T05", "They are UST10-4.375-007, UST10-4.250-008, FR30-2.5-006, FN30-2.5-008 and G230-2.0-003.", True),
    ("T05", "The largest are UST10-4.375-007 and UST10-4.250-008.", False),
    ("T07", "If rates rise by 200bp, the value of the securities falls by USD 992.2 million.", True),
    ("T07", "The value of the securities falls by about 11.12%.", False),  # not what was asked
    ("T08", "30-year MBS: 78.6%\n15-year MBS: 11.0%\nTreasuries: 10.4%", True),
    ("T10", "AOCI_UP200 is in BREACH and DUR_BAND is in WARN; all other limits are OK.", True),
    ("T10", "No limit is breached.", False),
    (
        "T12",
        "Market value fell by 38.80: -29.29 from the first-order curve effect, -9.49 from MBS spreads.",
        True,
    ),
    ("T13", "| Tenor | Notional |\n|---|---|\n| 2Y | 570.0 |\n| 5Y | 260.0 |\n| 10Y | 150.0 |", True),
    ("T17", "The net key-rate DV01 at the 10-year point is 1,636 thousand USD per bp.", True),
    ("C01", "HTM securities lose 158.93 more than AFS securities.", True),
    ("C01", "HTM securities lose 575.57 and AFS securities 416.64.", False),  # the difference was asked for
    ("C02", "About 67.9% of the market value is in 30-year MBS.", True),
    ("C02", "Roughly two thirds.", False),
    ("C04", "The limit is 15.99 outside its bound. A 5-year pay-fixed swap of 260.0 restores it.", True),
    (
        "C07",
        "A 10-year swap of 339.2 notional. It lowers 12-month NII by 1.99; AOCI_UP200 becomes -188.97.",
        True,
    ),
    (
        "C10",
        "The 30Y low (<=3.0) bucket loses most. Its effective duration is 7.10 and its DV01 is 2,110.",
        True,
    ),
    (
        "D01",
        "The after-tax AOCI loss may not exceed USD 210 million [IPS 4.3]. Only AFS securities count.",
        True,
    ),
    ("D01", "The limit is USD 210 million and covers AFS securities.", False),  # no citation, no label
    (
        "D03",
        "A limit is in warning when utilisation reaches 80% [IPS 5.2]. Today DUR_BAND is in warning.",
        True,
    ),
    ("D04", "No. Under hedge accounting an HTM security cannot be the hedged item [HEDGE 3.2].", True),
    ("D05", "The tax rate is 24% [ACCT 3.2]. Under +200bp the after-tax change in AOCI is -226.0.", True),
    ("D07", "No: swaps do not hedge it [SCEN 4]. Under basis_widen_25 the securities lose 118.0.", True),
    ("D10", "Hedging AFS securities with swaps, or selling them [IPS 5.4]. A 5-year swap of 260.0.", True),
    (
        "D10",
        "Hedging with swaps [IPS 5.4]. A 5-year swap of 260.0 restores the limit.",
        False,
    ),  # half the policy
]


@pytest.mark.parametrize(("task_id", "answer", "correct"), NATURAL, ids=lambda value: str(value)[:32])
def test_an_answer_in_natural_wording_is_scored_as_a_reader_would_score_it(
    tasks, expected, task_id, answer, correct
):
    task = next(task for task in tasks if task.id == task_id)
    lacking = evals.missing(answer, expected[task_id], task.cites)
    assert (not lacking) == correct, lacking


# --------------------------------------------------------------------------- tool selection


def test_tool_selection_compares_the_calls_that_ran_with_the_accepted_ways(wb, tasks, specs):
    by_id = {task.id: task for task in tasks}

    def chosen(task_id: str, *calls: tuple[str, dict]) -> bool:
        toolbox = tools.Toolbox(wb)
        for name, arguments in calls:
            toolbox.call(name, arguments)
        return evals.selected(by_id[task_id], toolbox.results, specs)

    assert chosen("T01", ("risk_report", {}))
    assert chosen("T01", ("risk_report", {"by": "designation"}))  # an argument the reference leaves free
    assert chosen("T01", ("limit_status", {}))  # another accepted way
    assert not chosen("T01", ("portfolio_summary", {}))
    assert not chosen("T01", ("risk_report", {}), ("portfolio_summary", {}))  # a call too many
    assert chosen(
        "T01", ("risk_report", {"by": "nothing"}), ("risk_report", {})
    )  # a failed call is not counted
    assert not chosen("T01")

    assert chosen("T03", ("portfolio_summary", {"by": "designation"}))
    assert not chosen("T03", ("portfolio_summary", {}))  # the default groups by bucket
    assert chosen("T04", ("key_rate_report", {}))  # the default is the reference value
    assert not chosen("T04", ("key_rate_report", {"unit": "k"}))
    assert chosen("T07", ("run_scenarios", {"shocks_bp": [200]}))
    assert chosen("T07", ("run_scenarios", {}))  # every configured scenario
    assert not chosen("T07", ("run_scenarios", {"scenarios": ["up_100"]}))
    assert chosen("T09", ("income_report", {"scenarios": ["up_100", "base"]}))  # a list in any order
    assert chosen("T13", ("limit_remedy", {"limit": "AOCI_UP200", "tenors": [10, 5, 2]}))
    assert not chosen("T13", ("limit_remedy", {"limit": "AOCI_UP200", "tenors": [5]}))
    assert chosen("T15", ("what_if", {"drop": ["FN30-2.5-001"]}))
    assert not chosen("T15", ("what_if", {"drop": ["FN30-2.5-001", "FN30-2.5-008"]}))


# --------------------------------------------------------------------------- the evaluation on the mock model


def test_the_mock_model_answers_every_tool_task_correctly_along_its_reference_path(evaluation, tasks):
    records = {record["id"]: record for record in evaluation["tasks"]}
    assert list(records) == [task.id for task in tasks]
    for task in tasks:
        run = records[task.id]["release2"]
        assert run["status"] == "answered" and run["first_draft_passed"], (task.id, run)
        assert [call["tool"] for call in run["tool_calls"]] == [call.tool for call in task.path], task.id
        assert all(call["ok"] for call in run["tool_calls"]), task.id
        if task.kind == "routine":
            assert run["tools_selected"] is True, task.id
        else:
            assert run["tools_selected"] is None
        retrieved = bool(set(task.cites) & set(run["passages"]))
        if task.kind != "documents" or retrieved:
            assert run["correct"] and run["missing"] == [], (task.id, run["missing"], run["answer"])
        else:  # without the passage the mock says so, and the answer lacks what the document holds
            assert not run["correct"] and "does not cover this" in run["answer"], task.id
    assert sum(records[task.id]["release2"]["correct"] for task in tasks if task.kind == "documents") >= 8


def test_the_measures_are_those_of_the_design(evaluation):
    measured = evaluation["measures"]
    benchmark = measured["benchmark"]
    assert benchmark["tasks"] == 30 and measured["not_run"] == 0 and benchmark["errors"] == 0
    assert measured["tool_selection"] == {"count": 20, "of": 20, "share": 1.0}
    assert benchmark["first_draft_passed"]["count"] == 30 and benchmark["blocked"]["count"] == 0
    assert benchmark["correct"]["of"] == 30 and benchmark["correct"]["count"] >= 28
    assert benchmark["release1"] == {"one command": 10, "commands and work by hand": 10, "no": 10}
    assert {kind: part["tasks"] for kind, part in measured["classes"].items()} == {
        "routine": 10,
        "composed": 10,
        "documents": 10,
    }
    assert measured["classes"]["routine"]["correct"]["share"] == 1.0
    assert measured["classes"]["composed"]["correct"]["share"] == 1.0
    times = benchmark["seconds"]
    assert times["runs"] == 30 and 0.0 < times["median"] <= times["p90"]
    assert measured["classes"]["routine"]["release1_seconds"]["runs"] == 10  # the commands were run and timed
    assert measured["classes"]["documents"]["release1_seconds"]["runs"] == 0
    assert all(record["release1"]["error"] is None for record in evaluation["tasks"])

    assert evaluation["refusal"] == {"count": 10, "of": 10, "share": 1.0}  # the mock refuses what is no task
    assert [record["id"] for record in evaluation["refusals"]] == [f"N{n:02d}" for n in range(1, 11)]

    found = evaluation["retrieval"]
    vector, fused, reranked = found["methods"]
    assert (vector["method"], vector["default"], vector["installed"]) == ("Vector search", True, True)
    assert vector["hits"] + len(vector["misses"]) == vector["in_scope"] == 30 and vector["out_of_scope"] == 10
    assert fused["keyword"] and not fused["default"] and 0.0 <= fused["hit_rate"] <= 1.0
    assert reranked["rerank"] and (reranked["installed"] or "hit_rate" not in reranked)
    assert found["refuse_below"] == 0.15 and len(found["questions"]) == 40
    assert found["similarity"]["in_scope"]["min"] <= found["similarity"]["in_scope"]["max"]

    said = evaluation["progress"]
    assert said[0] == "Retrieval: 40 questions" and "Tasks: 40" in said
    assert any(re.fullmatch(r" 1/40  T01  routine    correct    +\d+\.\ds", line) for line in said), said[13]


def record_of(status: str, **run) -> dict:
    release1 = {"verdict": "one command", "seconds": 0.5, "error": None}
    return {"id": "X", "class": "routine", "benchmark": True, "release1": release1} | {
        "release2": {"status": status, "seconds": run.pop("seconds", None)} | run
    }


def test_a_failed_run_counts_against_every_share_and_a_task_not_run_is_left_out():
    answered = {"correct": True, "first_draft_passed": True, "tools_selected": True}
    records = [
        record_of("answered", seconds=10.0, **answered),
        record_of("answered", seconds=20.0, correct=False, first_draft_passed=False, tools_selected=False),
        record_of("blocked", seconds=40.0, correct=False, first_draft_passed=False, tools_selected=True),
        record_of("error", seconds=1.0),
        record_of("not run"),
    ]
    measured = evals.measures(records)
    benchmark = measured["benchmark"]
    assert (measured["not_run"], benchmark["tasks"], benchmark["errors"]) == (1, 4, 1)
    assert benchmark["correct"] == {"count": 1, "of": 4, "share": 0.25}
    assert benchmark["first_draft_passed"]["count"] == 1 and benchmark["blocked"]["count"] == 1
    assert measured["tool_selection"] == {"count": 2, "of": 4, "share": 0.5}
    assert benchmark["seconds"] == {
        "runs": 3,
        "median": 20.0,
        "p90": pytest.approx(36.0),
    }  # the error is not timed
    assert evals.measures([])["benchmark"]["seconds"] == {"runs": 0, "median": None, "p90": None}
    assert evals.measures([])["tool_selection"]["share"] is None


def test_a_run_that_fails_is_reported_with_its_task_and_the_evaluation_goes_on(
    wb, agent_config, knowledge_base, tasks
):
    def say(text: str):
        return messages.AIMessage(content=text)

    # the first task: a figure without a tool call fails the check, and the redraft gives no figure
    script = [say("Net duration is 5.30 years."), say("I do not know."), say("Still nothing.")]
    chat = models.ScriptedChatModel(script=script)  # the third task finds the script used up
    assistant = assistant_for(wb, agent_config, knowledge_base, chat)
    lines: list[str] = []
    first, second, third = evals.run_tasks(assistant, tasks[:3], classic=False, progress=lines.append)

    assert (first["release2"]["status"], first["release2"]["answer"]) == ("answered", "I do not know.")
    assert not first["release2"]["correct"] and not first["release2"]["first_draft_passed"]
    assert first["release2"]["missing"] == ["Net eff_duration: 5.30"]
    assert first["release2"]["tools_selected"] is False and first["release2"]["tool_calls"] == []
    assert second["release2"]["first_draft_passed"] and second["release2"]["missing"] == [
        "market value, Total market_value_mm: 8,909.3",
        "Total unrealized_mm: -1,240.1",
    ]
    assert third["release2"]["status"] == "error" and "ValueError: the script" in third["release2"]["error"]
    assert third["release2"]["seconds"] >= 0.0 and "answer" not in third["release2"]
    assert first["release1"]["seconds"] is None  # release 1 was not timed
    assert [line.split()[3] for line in lines] == ["incorrect", "incorrect", "error"]
    measured = evals.measures([first, second, third])
    assert measured["benchmark"]["errors"] == 1 and measured["benchmark"]["correct"]["count"] == 0


def test_stopping_the_run_keeps_the_tasks_that_were_done(
    wb, agent_config, knowledge_base, tasks, monkeypatch
):
    chat = evals.reference_model(tasks, lambda: tools.Toolbox(wb))
    assistant = assistant_for(wb, agent_config, knowledge_base, chat)
    ask = assistant.ask

    def stop_at_the_third(question, **kwargs):
        if question == tasks[2].question:
            raise KeyboardInterrupt
        return ask(question, **kwargs)

    monkeypatch.setattr(assistant, "ask", stop_at_the_third)
    lines: list[str] = []
    records = evals.run_tasks(assistant, tasks[:5], classic=False, progress=lines.append)
    assert [record["release2"]["status"] for record in records] == ["answered", "answered", *["not run"] * 3]
    assert lines[-1].startswith("Stopped:") and evals.measures(records)["not_run"] == 3


# --------------------------------------------------------------------------- the investigation


def test_the_investigation_of_a_breached_limit_is_a_task_whose_reference_path_is_the_playbook(wb):
    (task,) = evals.investigation_tasks(wb)  # one limit is in breach on the market date
    limit = next(limit for limit in wb.limits if limit.id == "AOCI_UP200")
    assert (task.id, task.kind, task.cites) == ("AOCI_UP200", "investigation", ("IPS 4.3",))
    assert task.question == graph.playbook(limit)
    assert [(call.tool, call.arguments) for call in task.path] == graph.playbook_calls(limit)
    headroom, option = evals.resolve(task, tools.Toolbox(wb))
    assert headroom.wording == "AOCI_UP200 headroom: -15.99" and headroom.labels == ()
    assert option.values == (570.0, 260.0, 150.0)  # any one of the sized options

    for limit in wb.limits:  # the calls are the steps of the instruction, in its order
        text, at = graph.playbook(limit), 0
        for tool, _ in graph.playbook_calls(limit):
            at = text.index(tool, at) + 1
    unscenarioed = next(limit for limit in wb.limits if not limit.scenario)
    assert graph.playbook_calls(unscenarioed)[1] == ("risk_report", {"by": "bucket"})


def test_the_evaluation_runs_the_playbook_and_reports_the_steps_that_were_done(evaluation):
    (record,) = evaluation["investigations"]
    assert record["limit"] == "AOCI_UP200" and record["status"] == "answered"
    assert [step["tool"] for step in record["steps"]] == [
        "limit_status",
        "scenario_breakdown",
        "top_positions",
        "key_rate_report",
        "explain_change",
        "limit_remedy",
    ]
    assert all(step["done"] for step in record["steps"]) and record["first_draft_passed"]
    assert record["correct"] and record["missing"] == [] and record["passages"][0] == "IPS 4.3"
    assert record["answer"].startswith("Indicative only: not approved, no action taken.")
    assert evaluation["progress"][-2] == "Investigation of each limit in breach"
    assert evaluation["progress"][-1].startswith("AOCI_UP200  answered   6 of 6 steps")

    report = evalreport.render(evaluation)
    assert "**AOCI_UP200**" in report and "- Playbook steps done: 6 of 6" in report
    assert "- Reference in the answer: yes" in report and "> AOCI_UP200 headroom: -15.99." in report


def test_a_playbook_step_that_was_skipped_is_named(wb, agent_config, knowledge_base, evaluation):
    def tool_call(name: str, **arguments):
        made = [{"name": name, "args": arguments, "id": f"call-{name}"}]
        return messages.AIMessage(content="", tool_calls=made)

    script = [
        tool_call("limit_status"),
        tool_call("limit_remedy", limit="AOCI_UP200", tenors=[5]),
        messages.AIMessage(content="AOCI_UP200 is 15.99 outside its bound. A swap of 260.0 restores it."),
    ]
    assistant = assistant_for(wb, agent_config, knowledge_base, models.ScriptedChatModel(script=script))
    lines: list[str] = []
    (record,) = evals.run_investigations(assistant, lines.append)
    assert [step["tool"] for step in record["steps"] if not step["done"]] == [
        "scenario_breakdown",
        "top_positions",
        "key_rate_report",
        "explain_change",
    ]
    assert record["status"] == "answered" and not record["correct"]
    assert record["missing"] == ["a citation of [IPS 4.3]"]
    assert lines == [lines[0]] and lines[0].startswith("AOCI_UP200  answered   2 of 6 steps")
    report = evalreport.render(evaluation | {"investigations": [record]})
    assert (
        "- Playbook steps done: 2 of 6; not done: scenario_breakdown, top_positions, key_rate_report,"
        in report
    )
    assert "- Reference in the answer: no; missing: a citation of [IPS 4.3]" in report


# --------------------------------------------------------------------------- the report


def test_the_report_states_the_run_the_measures_and_every_task(evaluation, tasks):
    report = evalreport.render(evaluation)
    headings = [line for line in report.splitlines() if line.startswith("## ")]
    assert headings == [
        "## 1. The run",
        "## 2. Measures",
        "## 3. Retrieval",
        "## 4. Release 1 against release 2",
        "## 5. Tasks",
        "## 6. Questions outside the knowledge base",
        "## 7. Investigation of each limit in breach",
    ]
    assert f"**{evalreport.MOCK_NOTICE}**" in report
    assert "| Chat model | mock model that follows the reference path; temperature 0, seed 42," in report
    assert "context 16384 tokens, replies up to 2048 tokens, reasoning off |" in report
    assert "| Embedding model | word-hash vectors |" in report
    assert "| Retrieval | 4 passages from 20 candidates; refuse below 0.15; keyword fusion off;" in report
    assert "| Market date | 2026-11-09 |" in report and "| Tool-call budget | 8 |" in report
    for measure, value, _ in evalreport.summary(evaluation):
        assert f"| {measure} | {value} |" in report
    assert [measure for measure, *_ in evalreport.summary(evaluation)] == [
        "Retrieval hit rate at 4",
        "Refusal correctness, the assistant",
        "Refusal correctness, the threshold alone",
        "Tool-selection accuracy",
        "First-draft pass rate",
        "Block rate",
        "Answer correctness",
        "Time to answer",
    ]
    assert "| Tool-selection accuracy | 100.0% (20 of 20) | 20 routine tasks |" in report
    assert "| routine | 10 | 10 | 0 | 0 | 100.0% (10 of 10) | 0 | 10 |" in report
    assert "| composed | 10 | 0 | 10 | 0 | 100.0% (10 of 10) | 0 | 10 |" in report
    assert (
        "| With fusion and reranking | not installed | not installed |" in report or "reranking |" in report
    )
    for task in tasks:
        assert f"| {task.id} | {task.kind} |" in report
    assert (
        "| T01 | routine | yes | What is the net effective duration of the book? | one command | correct |"
        in report
    )
    assert (
        "| N08 | What is the weather forecast for New York tomorrow? |" in report and "| refused |" in report
    )


def test_the_report_shows_what_went_wrong_with_a_task(evaluation):
    result = json.loads(json.dumps(evaluation, default=str))  # a copy, as the data file holds it
    wrong, blocked, failed, other = (record["release2"] for record in result["tasks"][:4])
    wrong |= {
        "correct": False,
        "missing": ["Net eff_duration: 5.30"],
        "answer": "Net duration is 6.1 | high.",
    }
    blocked |= {"status": "blocked", "correct": False, "answer": "not shown"}
    blocked["drafts"] = [
        {
            "passed": False,
            "problems": ["15.99: not a figure of any tool result"],
            "text": "It is 15.99 over.",
        },
    ] * 2
    failed |= {"status": "error", "error": "ResponseError: model stopped", "correct": False}
    other["tools_selected"] = False
    result["refusals"][0] |= {"refused": False, "answer": "The ratio is 12%."}
    result["measures"] = evals.measures(result["tasks"])
    report = evalreport.render(result)

    assert "### Tasks not answered correctly" in report
    assert (
        "- Not in the answer: Net eff_duration: 5.30" in report and "> Net duration is 6.1 | high." in report
    )
    assert (
        "| T01 | routine | yes | What is the net effective duration of the book? | one command | incorrect |"
        in report
    )
    assert "- Draft 2 failed the check: 15.99: not a figure of any tool result" in report
    assert "The last draft, which was not shown:" in report and "> It is 15.99 over." in report
    assert "- Outcome: error (ResponseError: model stopped)" in report
    assert "Runs that ended in an error: 1 of the benchmark tasks" in report
    assert "### Routine tasks answered correctly with other tool calls than the reference" in report
    assert (
        "| T04 | At which key rate" in report
        and "key_rate_report {'by': 'designation', 'unit': 'years'}" in report
    )
    assert "**N01** What is the bank's common equity tier 1 capital ratio?" in report
    assert "> The ratio is 12%." in report


def test_the_run_is_described_by_what_the_machine_and_the_server_report(
    agent_config, fake_ollama, monkeypatch
):
    fake_ollama.tags = [
        {
            "model": "qwen3:8b",
            "digest": "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41",
            "size": 5200000000,
            "details": {"parameter_size": "8.2B", "quantization_level": "Q4_K_M"},
        },
        {"model": "nomic-embed-text:latest", "digest": "0a109f422b47", "size": 274000000, "details": {}},
    ]
    fake_ollama.running = [{"model": "qwen3:8b", "size": 8000000000, "size_vram": 6000000000}]
    served = dataclasses.replace(
        agent_config,
        chat=dataclasses.replace(agent_config.chat, base_url=fake_ollama.url),
        embedding=dataclasses.replace(agent_config.embedding, provider="ollama", base_url=fake_ollama.url),
    )

    def nvidia_smi(command, **kwargs):
        assert command[0] == "nvidia-smi"
        return subprocess.CompletedProcess(
            command, 0, stdout="NVIDIA GeForce RTX 3060, 12288 MiB\n", stderr=""
        )

    monkeypatch.setattr(evalreport.subprocess, "run", nvidia_smi)
    meta = evalreport.environment(served, mock=False, as_of="2026-11-09")
    assert meta["gpu"] == "NVIDIA GeForce RTX 3060, 12288 MiB" and meta["mock"] is False
    assert meta["chat"]["model"] == "qwen3:8b"
    assert meta["chat"]["served"] == "8.2B, Q4_K_M, digest 500a1f067a9f, 75% in GPU memory"
    assert meta["embedding"] == {"model": "nomic-embed-text", "served": "digest 0a109f422b47"}
    assert meta["retrieval"]["refuse_below"] == 0.15 and meta["packages"]["langgraph"]

    def missing_program(command, **kwargs):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(evalreport.subprocess, "run", missing_program)
    unreachable = dataclasses.replace(
        served, chat=dataclasses.replace(served.chat, base_url="http://127.0.0.1:9")
    )
    bare = evalreport.environment(unreachable, mock=False, as_of="2026-11-09")
    assert bare["gpu"] is None and bare["chat"]["served"] is None  # the report is written without them


# --------------------------------------------------------------------------- the command


def test_the_command_runs_the_evaluation_on_the_mock_model_and_writes_the_report(tmp_path, monkeypatch, root):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(cli._state, "root", None)
    done = CliRunner().invoke(cli.app, ["--root", str(root), "eval", "--mock", "--out", "out/evaluation"])
    assert done.exit_code == 0, done.output
    shown = " ".join(done.output.split())
    assert "It says nothing about the quality of a real model." in shown
    assert "40/40 D10 documents" in shown and "Tool-selection accuracy 100.0% (20 of 20)" in shown

    report = (tmp_path / "out" / "evaluation.md").read_text(encoding="utf-8")
    data = json.loads((tmp_path / "out" / "evaluation.json").read_text(encoding="utf-8"))
    runs = (tmp_path / "out" / "evaluation_runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert report.startswith("# Evaluation report") and "## 5. Tasks" in report
    assert set(data) == {"meta", "retrieval", "refusals", "refusal", "tasks", "measures", "investigations"}
    assert [record["limit"] for record in data["investigations"]] == ["AOCI_UP200"]
    assert data["meta"]["mock"] is True and len(data["tasks"]) == 40
    assert data["tasks"][0]["release2"]["answer"] and data["tasks"][0]["release2"]["tool_calls"]
    logged = [json.loads(line)["question"] for line in runs]  # one line a run: 10 + 40 + 1
    assert len(logged) == 51 and logged[-2:] == [
        data["tasks"][-1]["question"],
        "Investigate the limit AOCI_UP200",
    ]
    assert not (root / "logs" / "evaluation_runs.jsonl").exists()


def test_the_real_chat_class_is_loaded_once_before_the_runs_are_timed(
    wb, agent_config, knowledge_base, tasks, fake_ollama
):
    fake_ollama.replies = [
        {"role": "assistant", "content": "ready"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "risk_report", "arguments": {}}}],
        },
        {"role": "assistant", "content": "Net effective duration is 5.30 years."},
    ]
    chat = models.chat(dataclasses.replace(agent_config.chat, base_url=fake_ollama.url))
    assistant = assistant_for(wb, agent_config, knowledge_base, chat)
    assistant.warm_up()
    (record,) = evals.run_tasks(assistant, tasks[:1], classic=False)
    assert record["release2"]["correct"] and record["release2"]["tools_selected"]
    assert record["release2"]["tokens"] == {"input_tokens": 2400, "output_tokens": 80}
    warm_up, first, second = fake_ollama.requests
    assert [message["role"] for message in warm_up["messages"]] == ["user"] and not warm_up.get("tools")
    # the same settings as a run: a different context length would make the server load the model again
    assert warm_up["options"] == first["options"] and warm_up["think"] is False
    assert first["messages"][1]["content"] == tasks[0].question and len(second["messages"]) == 4
