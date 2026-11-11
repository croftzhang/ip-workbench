"""Evaluation of the assistant: fixed question sets and deterministic measures (docs/AGENT_DESIGN.md, AD-8).

Two sets are kept in ``evals/``:

* ``retrieval.yaml``: questions with the sections that answer them, and
  questions the knowledge base does not answer;
* ``benchmark/tasks.yaml``: tasks with the accepted tool calls and the
  reference pairs of label and value of a correct answer.

The measures are code, not a judging model, so two runs on the same answers
give the same scores:

* retrieval hit rate at 4 and refusal correctness;
* tool-selection accuracy on the routine tasks;
* first-draft pass rate, block rate, answer correctness and time to answer on
  the benchmark tasks.

The investigation playbook is run as well, for every limit in breach: which of
its steps were done, and whether the answer passed the check.

No figure of the engine is stored with a task. The reference path of a task is
run on the engine when the evaluation runs, and the reference values are read
from its results.

``ReferenceChatModel`` is the mock model of the evaluation. It makes the calls
of the reference path and writes the reference answer, so a run with it shows
that the tasks, the scoring and the report work. It says nothing about the
quality of a real model.
"""

from __future__ import annotations

import dataclasses
import re
import shlex
import statistics
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from ipw.agent import graph, verify
from ipw.agent.config import AgentConfig, EmbeddingConfig
from ipw.agent.kb import KnowledgeBase
from ipw.agent.retrieval import NOT_COVERED, Retrieval, Retriever
from ipw.agent.tools import Toolbox, ToolResult, ToolSpec

Retrieve = Callable[[str], Retrieval]
Progress = Callable[[str], None]

RETRIEVAL_SET = "evals/retrieval.yaml"
TASK_SET = "evals/benchmark/tasks.yaml"
CLASSES = ("routine", "composed", "documents")
REFUSAL = NOT_COVERED.capitalize() + "."
HIT_RATE_TARGET = 0.85  # docs/PRD.md, roadmap


# ====================================================================== the retrieval question set
@dataclass(frozen=True)
class RetrievalQuestion:
    id: str
    question: str
    references: tuple[str, ...]  # sections that answer it, for example "IPS 4.3"; empty when out of scope

    @property
    def in_scope(self) -> bool:
        return bool(self.references)


def load_retrieval_questions(path: str | Path) -> list[RetrievalQuestion]:
    """Read the question set: ``in_scope`` questions with references, ``out_of_scope`` questions without."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    unknown = set(raw) - {"in_scope", "out_of_scope"}
    if unknown:
        raise ValueError(f"{path.name}: unknown sections {sorted(unknown)}")
    questions = []
    for section, needs_references in (("in_scope", True), ("out_of_scope", False)):
        for item in raw.get(section) or []:
            extra = set(item) - {"id", "question", "references"}
            references = tuple(item.get("references") or ())
            if extra or "id" not in item or "question" not in item or bool(references) != needs_references:
                raise ValueError(
                    f"{path.name}: {section} item {item.get('id')!r} needs an id, a question and "
                    f"{'at least one reference' if needs_references else 'no references'}"
                )
            questions.append(RetrievalQuestion(str(item["id"]), str(item["question"]), references))
    ids = [question.id for question in questions]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path.name}: question ids must be different")
    return questions


def hit_rate(questions: Iterable[RetrievalQuestion], retrieve: Retrieve) -> float:
    """Share of in-scope questions with a reference section among the passages returned."""
    asked = [question for question in questions if question.in_scope]
    hits = sum(bool(set(question.references) & set(retrieve(question.question).refs)) for question in asked)
    return hits / len(asked)


def refusal_correctness(questions: Iterable[RetrievalQuestion], retrieve: Retrieve) -> float:
    """Share of out-of-scope questions for which nothing is returned."""
    asked = [question for question in questions if not question.in_scope]
    return sum(not retrieve(question.question).covered for question in asked) / len(asked)


def suggest_threshold(in_scope: Sequence[float], out_of_scope: Sequence[float]) -> float:
    """The refusal threshold that classifies most questions correctly, from their best similarities.

    A question is refused when its best similarity is below the threshold.
    Candidates are the midpoints between neighbouring observed values; among
    equally good ones the lowest is returned, which refuses least.
    """
    values = sorted({*in_scope, *out_of_scope})
    candidates = [0.0, *((low + high) / 2.0 for low, high in zip(values, values[1:]))]

    def correct(threshold: float) -> int:
        return sum(v >= threshold for v in in_scope) + sum(v < threshold for v in out_of_scope)

    return max(candidates, key=lambda threshold: (correct(threshold), -threshold))


# ====================================================================== the benchmark tasks
@dataclass(frozen=True)
class Call:
    tool: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Reference:
    """One reference pair of label and value, as the task file writes it."""

    labels: tuple[str, ...] = ()  # the answer has to use one of them
    cells: tuple[dict[str, Any], ...] = ()  # figures of the reference path; any one of them is the value
    number: float | None = None  # a figure that stands in a document
    rows: dict[str, Any] | None = None  # the labels of the first rows of a result


@dataclass(frozen=True)
class Task:
    id: str
    kind: str  # one of CLASSES
    question: str
    benchmark: bool  # one of the thirty benchmark tasks
    classic: tuple[str, ...]  # the release 1 commands that show the figures of the answer
    by_hand: str  # what release 1 leaves to the user
    calls: tuple[tuple[Call, ...], ...]  # the accepted ways to answer; the first is the reference path
    answer: tuple[Reference, ...]
    cites: tuple[str, ...]  # the answer has to cite one of these sections

    @property
    def path(self) -> tuple[Call, ...]:
        """The reference path: the calls from whose results the reference figures are read."""
        return self.calls[0] if self.calls else ()

    @property
    def release1(self) -> str:
        """Whether release 1 answers the task without new code."""
        if not self.classic:
            return "no"
        return "one command" if len(self.classic) == 1 and not self.by_hand else "commands and work by hand"


_TASK_KEYS = {"id", "class", "benchmark", "question", "classic", "by_hand", "calls", "answer", "cites"}
_CELL_KEYS = {"result", "table", "row", "position", "column"}


def _reference(item: Any, fail: Callable[[str], None]) -> Reference:
    if not isinstance(item, Mapping) or set(item) - {"label", "cell", "number", "text", "rows"}:
        fail("an answer item has the keys label, cell, number, text and rows")
    if sum(key in item for key in ("cell", "number", "text", "rows")) != 1:
        fail("an answer item is exactly one of cell, number, text and rows")
    labels = tuple(str(label) for label in item.get("label") or ())
    if "text" in item:
        if labels or not item["text"]:
            fail("a text item lists its phrases and takes no label")
        return Reference(labels=tuple(str(phrase) for phrase in item["text"]))
    if "rows" in item:
        rows = item["rows"]
        if labels or not isinstance(rows, Mapping) or set(rows) - {"result", "table", "first"}:
            fail("a rows item names a result, optionally a table, and how many rows; it takes no label")
        if not {"result", "first"} <= set(rows):
            fail("a rows item needs result and first")
        return Reference(rows=dict(rows))
    if "number" in item:
        if not labels:
            fail("a number item needs a label")
        return Reference(labels=labels, number=float(item["number"]))
    cells = item["cell"] if isinstance(item["cell"], list) else [item["cell"]]
    for cell in cells:
        if not isinstance(cell, Mapping) or set(cell) - _CELL_KEYS or not {"result", "column"} <= set(cell):
            fail("a cell names result, column and a row or a position, and optionally a table")
        if ("row" in cell) == ("position" in cell):
            fail("a cell names either a row or a position")
    return Reference(labels=labels, cells=tuple(dict(cell) for cell in cells))


def _call(item: Any, fail: Callable[[str], None]) -> Call:
    if not isinstance(item, Mapping) or len(item) != 1:
        fail("a call is written {tool: {arguments}}")
    (tool, arguments), *_ = item.items()
    if arguments is not None and not isinstance(arguments, Mapping):
        fail(f"the arguments of {tool} are a mapping")
    return Call(str(tool), dict(arguments or {}))


def load_tasks(path: str | Path) -> list[Task]:
    """Read and check the benchmark tasks. The file itself documents its fields."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if set(raw) != {"tasks"} or not isinstance(raw["tasks"], list):
        raise ValueError(f"{path.name}: the file holds one list named tasks")
    tasks = []
    for item in raw["tasks"]:
        name = item.get("id") if isinstance(item, Mapping) else None

        def fail(message: str, name=name) -> None:
            raise ValueError(f"{path.name}: task {name!r}: {message}")

        if not isinstance(item, Mapping) or set(item) - _TASK_KEYS:
            fail(f"a task has the keys {', '.join(sorted(_TASK_KEYS))}")
        if not {"id", "class", "question", "answer"} <= set(item):
            fail("a task needs id, class, question and answer")
        kind = item["class"]
        if kind not in CLASSES:
            fail(f"class is one of {', '.join(CLASSES)}")
        classic = tuple(str(command) for command in item.get("classic") or ())
        if any(not command.startswith("ipw ") for command in classic):
            fail("classic lists commands that start with ipw")
        ways = item.get("calls") or []
        if any(not isinstance(way, list) or not way for way in ways):
            fail("calls lists the accepted ways to answer, each a list of calls")
        calls = tuple(tuple(_call(call, fail) for call in way) for way in ways)
        answer = tuple(_reference(reference, fail) for reference in item["answer"] or ())
        cites = tuple(str(ref) for ref in item.get("cites") or ())
        if not answer:
            fail("answer lists at least one reference")
        if kind == "routine" and not (calls and classic):
            fail("a routine task needs calls and the release 1 command")
        if kind == "documents" and not cites:
            fail("a documents task names the sections to cite")
        if any(reference.cells or reference.rows for reference in answer) and not calls:
            fail("a figure of a tool result needs the calls that produce it")
        benchmark = bool(item.get("benchmark", kind != "routine"))
        by_hand = str(item.get("by_hand") or "")
        tasks.append(
            Task(str(name), kind, str(item["question"]), benchmark, classic, by_hand, calls, answer, cites)
        )
    ids = [task.id for task in tasks]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path.name}: task ids must be different")
    if len({task.question for task in tasks}) != len(tasks):
        raise ValueError(f"{path.name}: task questions must be different")
    return tasks


def investigation_tasks(wb) -> list[Task]:
    """The investigation of every limit in breach, as a task whose reference path is the playbook.

    The answer has to state how far the limit is outside its bound and the
    notional of a sized option, and to cite the policy section of the limit.
    """
    tasks = []
    for result in wb.limit_report():
        if result.status != "BREACH":
            continue
        limit = result.limit
        calls = tuple(Call(tool, arguments) for tool, arguments in graph.playbook_calls(limit))
        last = f"r{len(calls)}"
        options = tuple({"result": last, "position": n, "column": "notional_mm"} for n in (1, 2, 3))
        answer = (
            Reference(cells=({"result": "r1", "row": limit.id, "column": "headroom"},)),
            Reference(labels=("notional", "swap", "option", "FIXED"), cells=options),
        )
        tasks.append(
            Task(
                id=limit.id,
                kind="investigation",
                question=graph.playbook(limit),
                benchmark=False,
                classic=(),
                by_hand="",
                calls=(calls,),
                answer=answer,
                cites=(limit.policy_ref,),
            )
        )
    return tasks


# ====================================================================== reference values
@dataclass(frozen=True)
class Expected:
    """One reference pair with its values as the engine gives them now."""

    labels: tuple[str, ...]
    values: tuple[float, ...]  # empty: the pair is wording only
    wording: str  # the pair written out, for the report and for the mock model
    document: bool = False  # the value stands in a document, not in a tool result


def resolve(task: Task, toolbox: Toolbox) -> list[Expected]:
    """Run the reference path of a task on the engine and read its reference values.

    ``toolbox`` is a fresh one; after the call it holds the results of the path.
    """
    for call in task.path:
        result = toolbox.call(call.tool, call.arguments)
        if not result.ok:
            raise ValueError(f"task {task.id}: the reference call {call.tool} failed: {result.error}")
    results = {result.id: result for result in toolbox.results}

    def table(where: Mapping[str, Any]):
        if where["result"] not in results:
            raise ValueError(f"task {task.id}: the reference path has no result {where['result']!r}")
        try:
            return results[where["result"]].table(where.get("table"))
        except KeyError as err:
            raise ValueError(f"task {task.id}: {err.args[0]}") from None

    expected = []
    for reference in task.answer:
        if reference.rows is not None:
            labels = list(table(reference.rows).rows)[: int(reference.rows["first"])]
            if len(labels) < int(reference.rows["first"]):
                raise ValueError(f"task {task.id}: result {reference.rows['result']} has too few rows")
            expected += [Expected((label,), (), label) for label in labels]
        elif reference.number is not None:
            wording = f"{reference.labels[0]}: {reference.number:g}"
            expected.append(Expected(reference.labels, (reference.number,), wording, document=True))
        elif not reference.cells:
            expected.append(Expected(reference.labels, (), reference.labels[0]))
        else:
            values, wordings, labels = [], [], reference.labels
            for cell in reference.cells:
                source = table(cell)
                rows = list(source.rows)
                if "position" in cell and not 1 <= int(cell["position"]) <= len(rows):
                    raise ValueError(f"task {task.id}: no row {cell['position']} in result {cell['result']}")
                row = rows[int(cell["position"]) - 1] if "position" in cell else str(cell["row"])
                column = str(cell["column"])
                value = source.rows.get(row, {}).get(column)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    where = f"row {row!r}, column {column!r}"
                    raise ValueError(f"task {task.id}: result {cell['result']} has no figure in {where}")
                if "position" in cell and row not in labels:
                    labels = (*labels, row)  # a figure picked by position may also be named by its row
                where = f"{row} {column}"
                named = not labels or any(label.lower() in where.lower() for label in labels)
                lead = "" if named else f"{labels[0]}, "
                values.append(float(value))
                wordings.append(f"{lead}{where}: {source.shown(row, column)}")
            expected.append(Expected(labels, tuple(values), wordings[0]))
    return expected


# ====================================================================== scoring
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+")


def segments(text: str) -> list[str]:
    """The lines of a text, and the sentences inside each line."""
    return [part for line in text.splitlines() for part in _SENTENCE_END.split(line) if part.strip()]


def _is_value(written: float, decimals: int, value: float) -> bool:
    """A written number states a value when it is the value rounded to the decimals shown.

    The sign is not compared: "a loss of 226.0" states -225.99. A whole number
    has to be within 1% as well, so the 5 of "a 5-year swap" does not state 5.30.
    """
    gap = abs(written - abs(value))
    return gap <= 0.5 * 10.0**-decimals + 1e-9 and (decimals >= 1 or gap <= 0.01 * abs(value) + 1e-9)


def contains(answer: str, expected: Expected) -> bool:
    """Whether an answer contains a reference pair: the value, and a label in the same sentence or line."""
    for segment in segments(answer):
        lowered = segment.lower()
        if expected.labels and not any(label.lower() in lowered for label in expected.labels):
            continue
        if not expected.values:
            return True
        written = verify.numbers(segment)
        if any(
            _is_value(number, decimals, value)
            for number, decimals, *_ in written
            for value in expected.values
        ):
            return True
    return False


def missing(answer: str, expected: Sequence[Expected], cites: Sequence[str] = ()) -> list[str]:
    """What a correct answer holds and this one does not. Empty: the answer is correct."""
    lacking = [item.wording for item in expected if not contains(answer, item)]
    if cites and not any(verify.cites(answer, ref) for ref in cites):
        lacking.append("a citation of " + " or ".join(f"[{ref}]" for ref in cites))
    return lacking


def _same(wanted: Any, given: Any) -> bool:
    """Whether an argument has its reference value. Plain lists compare in any order."""
    if isinstance(wanted, Mapping):
        return isinstance(given, Mapping) and all(
            _same(value, given.get(key)) for key, value in wanted.items()
        )
    if isinstance(wanted, list):
        if not isinstance(given, list) or len(given) != len(wanted):
            return False
        if all(not isinstance(value, (Mapping, list)) for value in [*wanted, *given]):
            wanted, given = sorted(wanted, key=repr), sorted(given, key=repr)
        return all(_same(a, b) for a, b in zip(wanted, given))
    return wanted == given


def accepts(call: Call, result: ToolResult, specs: Mapping[str, ToolSpec]) -> bool:
    """Whether a call the assistant made is a reference call: same tool, same named arguments."""
    if result.tool != call.tool or call.tool not in specs:
        return False
    wanted = specs[call.tool].args.model_validate(call.arguments).model_dump(mode="json", exclude_none=True)
    return all(_same(wanted[name], result.arguments.get(name)) for name in call.arguments if name in wanted)


def selected(task: Task, results: Sequence[ToolResult], specs: Mapping[str, ToolSpec]) -> bool:
    """Tool selection: the calls that returned a result are the calls of one accepted way, and all of them."""
    ran = [result for result in results if result.ok]
    if not ran:
        return False
    for way in task.calls:
        every_call_made = all(any(accepts(call, result, specs) for result in ran) for call in way)
        no_other_call = all(any(accepts(call, result, specs) for call in way) for result in ran)
        if every_call_made and no_other_call:
            return True
    return False


# ====================================================================== the mock model of the evaluation
@dataclass(frozen=True)
class Plan:
    calls: tuple[Call, ...]
    expected: tuple[Expected, ...]
    cites: tuple[str, ...]


_PASSAGE = re.compile(r"(?ms)^\[([^\]\n]+)\]\n(.*?)(?=\n\n\[[^\]\n]+\]\n|\Z)")


class ReferenceChatModel(BaseChatModel):
    """The mock model of the evaluation: it follows the reference path of the task it is asked.

    One call a turn, then the reference answer. What stands in a document is
    written only when a section the task names was retrieved, and is cited to
    it. A question that is not a task is answered "not covered".
    """

    plans: dict[str, Any] = Field(default_factory=dict)  # question -> Plan

    @property
    def _llm_type(self) -> str:
        return "reference"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any):
        return self.bind(tools=list(tools), **kwargs)

    def _generate(
        self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        question = next((str(m.content) for m in messages if m.type == "human"), "")
        plan = self.plans.get(question)
        done = sum(isinstance(m, ToolMessage) for m in messages)
        if plan is None:
            reply = AIMessage(REFUSAL)
        elif done < len(plan.calls) and kwargs.get("tools"):
            call = plan.calls[done]
            made = {"name": call.tool, "args": call.arguments, "id": f"reference-{done + 1}"}
            reply = AIMessage(content="", tool_calls=[made])
        else:
            reply = AIMessage(self._answer(plan, messages))
        return ChatResult(generations=[ChatGeneration(message=reply)])

    @staticmethod
    def _answer(plan: Plan, messages: Sequence[BaseMessage]) -> str:
        system = next((str(m.content) for m in messages if m.type == "system"), "")
        passages: dict[str, str] = {}
        for ref, text in _PASSAGE.findall(system):
            passages[ref] = passages.get(ref, "") + "\n" + text
        given = [ref for ref in plan.cites if ref in passages]
        results = "\n".join(str(m.content) for m in messages if isinstance(m, ToolMessage)).lower()

        def stands_in(text: str) -> tuple[str, str] | None:
            """The first wording of an item that stands in a passage the task names, with that passage."""
            return next(
                ((w, ref) for w in item.labels for ref in given if w.lower() in text[ref].lower()), None
            )

        lines = []
        for item in plan.expected:
            in_results = next((label for label in item.labels if label.lower() in results), None)
            if item.document:  # a figure of a document, cited to the passage it stands in
                source = next((ref for ref in given if f"{item.values[0]:g}" in passages[ref]), None)
                if source:
                    lines.append(f"{item.wording} [{source}].")
            elif item.values:
                lines.append(f"{item.wording}.")  # a figure of a tool result
            elif found := stands_in(passages):
                lines.append(f"{found[0]} [{found[1]}].")  # wording of a document
            elif in_results:
                lines.append(f"{in_results}.")  # a label of a tool result
            elif given:
                lines.append(f"{item.labels[0]} [{given[0]}].")
        if plan.cites and not given:
            lines.append(REFUSAL)
        elif given and not any(f"[{ref}]" in line for line in lines for ref in given):
            lines.append(f"The section is [{given[0]}].")
        return "\n".join(lines) or REFUSAL


def reference_model(tasks: Sequence[Task], toolbox_factory: Callable[[], Toolbox]) -> ReferenceChatModel:
    """The mock model for a set of tasks, with the reference values of the engine as it is now."""
    plans = {
        task.question: Plan(task.path, tuple(resolve(task, toolbox_factory())), task.cites) for task in tasks
    }
    return ReferenceChatModel(plans=plans)


def mock_config(config: AgentConfig, index_dir: str | Path) -> AgentConfig:
    """The configuration of a run without models: word-hash embeddings, their own index and threshold."""
    return dataclasses.replace(
        config,
        embedding=EmbeddingConfig(provider="hashing"),
        knowledge_base=dataclasses.replace(config.knowledge_base, index_dir=str(index_dir)),
        retrieval=dataclasses.replace(config.retrieval, refuse_below=0.15),  # suits the word-hash vectors
    )


# ====================================================================== running the evaluation
def evaluate_retrieval(
    config: AgentConfig, knowledge_base: KnowledgeBase, questions: Sequence[RetrievalQuestion]
) -> dict[str, Any]:
    """The retrieval table: vector search, with keyword fusion, and with reranking if it is installed."""
    from ipw.agent import models

    settings = config.retrieval
    stages = (
        ("Vector search", {"keyword": False, "rerank": False}),
        ("With keyword fusion", {"keyword": True, "rerank": False}),
        ("With fusion and reranking", {"keyword": True, "rerank": True}),
    )
    methods, detail = [], {}
    for name, switches in stages:
        row: dict[str, Any] = {"method": name, **switches}
        row["default"] = (settings.keyword, settings.rerank) == (switches["keyword"], switches["rerank"])
        reranker = None
        if switches["rerank"]:
            try:
                reranker = models.reranker(settings.reranker_model)
            except ValueError:
                methods.append({**row, "installed": False})
                continue
        retriever = Retriever(knowledge_base, dataclasses.replace(settings, **switches), reranker)
        found = {question.id: retriever.retrieve(question.question) for question in questions}
        by_question = {question.question: found[question.id] for question in questions}
        inside = [question for question in questions if question.in_scope]
        outside = [question for question in questions if not question.in_scope]
        misses = [q.id for q in inside if not set(q.references) & set(found[q.id].refs)]
        row |= {
            "installed": True,
            "hit_rate": hit_rate(questions, by_question.__getitem__),
            "hits": len(inside) - len(misses),
            "in_scope": len(inside),
            "misses": misses,
            "refusal": refusal_correctness(questions, by_question.__getitem__),
            "refused": sum(not found[q.id].covered for q in outside),
            "out_of_scope": len(outside),
        }
        methods.append(row)
        if not switches["keyword"]:  # similarities are those of vector search, whatever follows it
            detail = {q.id: found[q.id] for q in questions}

    inside = [detail[q.id].best_similarity for q in questions if q.in_scope]
    outside = [detail[q.id].best_similarity for q in questions if not q.in_scope]
    return {
        "methods": methods,
        "refuse_below": settings.refuse_below,
        "suggested_threshold": suggest_threshold(inside, outside),
        "similarity": {
            "in_scope": {"min": min(inside), "median": statistics.median(inside), "max": max(inside)},
            "out_of_scope": {"min": min(outside), "median": statistics.median(outside), "max": max(outside)},
        },
        "questions": [
            {
                "id": q.id,
                "question": q.question,
                "in_scope": q.in_scope,
                "references": list(q.references),
                "returned": list(detail[q.id].refs),
                "best_similarity": detail[q.id].best_similarity,
                "covered": detail[q.id].covered,
            }
            for q in questions
        ],
    }


def time_classic(commands: Sequence[str], root: Path) -> tuple[float, str | None]:
    """Run release 1 commands in this process: the seconds they took together, and the first failure."""
    from typer.testing import CliRunner

    from ipw.classic import cli as classic

    runner, seconds, error = CliRunner(), 0.0, None
    for command in commands:
        started = time.perf_counter()
        outcome = runner.invoke(classic.app, ["--root", str(root), *shlex.split(command)[1:]])
        seconds += time.perf_counter() - started
        if outcome.exit_code != 0 and error is None:
            error = f"{command}: exit code {outcome.exit_code}"
    return seconds, error


def _run(ask: Callable[[], Any]) -> dict[str, Any]:
    """One run of the assistant, timed. A run that fails is a result of the evaluation, not its end."""
    started = time.perf_counter()
    try:
        answer = ask()
    except Exception as err:  # whatever stopped the run is reported with its task
        seconds = time.perf_counter() - started
        return {
            "status": "error",
            "error": f"{type(err).__name__}: {err}",
            "seconds": seconds,
            "answer": None,
        }
    return {
        "status": answer.status,
        "error": None,
        "seconds": time.perf_counter() - started,
        "answer": answer,
    }


def _run_record(run: Mapping[str, Any]) -> dict[str, Any]:
    """What is kept of one run: enough to see how the answer came about and to score it again."""
    answer = run["answer"]
    record: dict[str, Any] = {"status": run["status"], "error": run["error"], "seconds": run["seconds"]}
    if answer is None:
        return record
    return record | {
        "run_id": answer.run_id,
        "answer": answer.text,
        "drafts": [
            {
                "passed": draft.check.ok,
                "problems": [f"{problem.text}: {problem.detail}" for problem in draft.check.problems],
                "text": draft.text,
            }
            for draft in answer.drafts
        ],
        "tool_calls": [
            {"tool": result.tool, "arguments": result.arguments, "ok": result.ok, "error": result.error}
            for result in answer.calls
        ],
        "passages": [hit.passage.ref for hit in answer.hits],
        "best_similarity": answer.retrieval.best_similarity,
        "model_calls": answer.model_calls,
        "tokens": answer.tokens,
    }


def run_tasks(
    assistant,
    tasks: Sequence[Task],
    *,
    classic: bool = True,
    progress: Progress = lambda line: None,
) -> list[dict[str, Any]]:
    """Run every task through the assistant and score it. Stopping the run keeps what was done."""
    specs = {spec.name: spec for spec in Toolbox(assistant.wb).specs}
    root = Path(assistant.config.root)
    if classic:
        time_classic(["ipw limits"], root)  # loads the book, so that no task carries the loading time
    records, stopped = [], False
    for number, task in enumerate(tasks, start=1):
        expected = resolve(task, Toolbox(assistant.wb))
        record: dict[str, Any] = {
            "id": task.id,
            "class": task.kind,
            "benchmark": task.benchmark,
            "question": task.question,
            "reference": [item.wording for item in expected],
            "cites": list(task.cites),
            "release1": {
                "verdict": task.release1,
                "commands": list(task.classic),
                "by_hand": task.by_hand,
                "seconds": None,
                "error": None,
            },
        }
        if stopped:
            record["release2"] = {"status": "not run", "error": None, "seconds": None}
            records.append(record)
            continue
        try:
            if classic and task.classic:
                seconds, error = time_classic(task.classic, root)
                record["release1"] |= {"seconds": seconds, "error": error}
            run = _run(lambda task=task: assistant.ask(task.question))
        except KeyboardInterrupt:
            stopped = True
            record["release2"] = {"status": "not run", "error": None, "seconds": None}
            records.append(record)
            progress("Stopped: the tasks that were run are reported, the others are marked not run.")
            continue
        answer = run["answer"]
        lacking = missing(answer.text, expected, task.cites) if answer else ["no answer"]
        correct = run["status"] == "answered" and not lacking
        record["release2"] = _run_record(run) | {
            "correct": correct,
            "missing": [] if run["status"] != "answered" else lacking,
            "first_draft_passed": bool(answer and answer.drafts and answer.drafts[0].check.ok),
            "tools_selected": selected(task, answer.calls, specs)
            if answer and task.kind == "routine"
            else None,
        }
        records.append(record)
        outcome = "correct" if correct else "incorrect" if run["status"] == "answered" else run["status"]
        progress(f"{number:>2}/{len(tasks)}  {task.id}  {task.kind:<9}  {outcome:<9}  {run['seconds']:6.1f}s")
    return records


def run_refusals(
    assistant, questions: Sequence[RetrievalQuestion], progress: Progress = lambda line: None
) -> list[dict[str, Any]]:
    """Ask the assistant the out-of-scope questions: a right answer says "not covered"."""
    records = []
    asked = [question for question in questions if not question.in_scope]
    for number, question in enumerate(asked, start=1):
        try:
            run = _run(lambda question=question: assistant.ask(question.question))
        except KeyboardInterrupt:
            progress("Stopped: the questions that were asked are reported.")
            break
        answer = run["answer"]
        refused = bool(answer) and run["status"] == "answered" and NOT_COVERED in answer.text.lower()
        records.append(
            {"id": question.id, "question": question.question, "refused": refused} | _run_record(run)
        )
        outcome = "refused" if refused else "answered" if run["status"] == "answered" else run["status"]
        progress(f"{number:>2}/{len(asked)}  {question.id}  {outcome:<9}  {run['seconds']:6.1f}s")
    return records


def run_investigations(assistant, progress: Progress = lambda line: None) -> list[dict[str, Any]]:
    """Run the investigation playbook for every limit in breach: the steps done, the check, the answer."""
    specs = {spec.name: spec for spec in Toolbox(assistant.wb).specs}
    records = []
    for task in investigation_tasks(assistant.wb):
        expected = resolve(task, Toolbox(assistant.wb))
        try:
            run = _run(lambda task=task: assistant.investigate(task.id))
        except KeyboardInterrupt:
            progress("Stopped: the investigations that were run are reported.")
            break
        answer = run["answer"]
        ran = [result for result in answer.calls if result.ok] if answer else []
        steps = [
            {"tool": call.tool, "done": any(accepts(call, result, specs) for result in ran)}
            for call in task.path
        ]
        lacking = missing(answer.text, expected, task.cites) if answer else ["no answer"]
        records.append(
            {"limit": task.id, "reference": [item.wording for item in expected], "cites": list(task.cites)}
            | _run_record(run)
            | {
                "steps": steps,
                "correct": run["status"] == "answered" and not lacking,
                "missing": [] if run["status"] != "answered" else lacking,
                "first_draft_passed": bool(answer and answer.drafts and answer.drafts[0].check.ok),
            }
        )
        done = sum(step["done"] for step in steps)
        progress(f"{task.id}  {run['status']:<9}  {done} of {len(steps)} steps  {run['seconds']:6.1f}s")
    return records


def _share(count: int, of: int) -> dict[str, Any]:
    return {"count": count, "of": of, "share": count / of if of else None}


def _times(seconds: Sequence[float]) -> dict[str, Any]:
    """Median and 90th percentile; the percentile is interpolated between the ordered values."""
    if not seconds:
        return {"runs": 0, "median": None, "p90": None}
    ordered = sorted(seconds)
    p90 = ordered[0] if len(ordered) == 1 else statistics.quantiles(ordered, n=10, method="inclusive")[-1]
    return {"runs": len(ordered), "median": statistics.median(ordered), "p90": p90}


def measures(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The measures of AD-8 from the task records. A task that was not run is left out of every measure."""
    ran = [record for record in records if record["release2"]["status"] != "not run"]

    def over(chosen: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        runs = [record["release2"] for record in chosen]
        timed = [run["seconds"] for run in runs if run["status"] in ("answered", "blocked")]
        classic = [r["release1"]["seconds"] for r in chosen if r["release1"]["seconds"] is not None]
        return {
            "tasks": len(chosen),
            "correct": _share(sum(bool(run.get("correct")) for run in runs), len(runs)),
            "first_draft_passed": _share(sum(bool(run.get("first_draft_passed")) for run in runs), len(runs)),
            "blocked": _share(sum(run["status"] == "blocked" for run in runs), len(runs)),
            "errors": sum(run["status"] == "error" for run in runs),
            "seconds": _times(timed),
            "release1": {
                verdict: sum(record["release1"]["verdict"] == verdict for record in chosen)
                for verdict in ("one command", "commands and work by hand", "no")
            },
            "release1_seconds": _times(classic),
        }

    benchmark = [record for record in ran if record["benchmark"]]
    routine = [record for record in ran if record["class"] == "routine"]
    return {
        "not_run": len(records) - len(ran),
        "benchmark": over(benchmark),
        "classes": {kind: over([r for r in benchmark if r["class"] == kind]) for kind in CLASSES},
        "tool_selection": _share(
            sum(bool(r["release2"].get("tools_selected")) for r in routine), len(routine)
        ),
    }


def evaluate(
    assistant,
    knowledge_base: KnowledgeBase,
    tasks: Sequence[Task],
    questions: Sequence[RetrievalQuestion],
    *,
    classic: bool = True,
    progress: Progress = lambda line: None,
) -> dict[str, Any]:
    """The whole evaluation, in the order it is reported: retrieval, refusal, the tasks."""
    progress(f"Retrieval: {len(questions)} questions")
    retrieval = evaluate_retrieval(assistant.config, knowledge_base, questions)
    progress("Loading the chat model")
    assistant.warm_up()  # the first reply of a model includes loading it; no task carries that time
    outside = sum(not question.in_scope for question in questions)
    progress(f"Refusal: {outside} questions outside the knowledge base")
    refusals = run_refusals(assistant, questions, progress)
    progress(f"Tasks: {len(tasks)}")
    records = run_tasks(assistant, tasks, classic=classic, progress=progress)
    progress("Investigation of each limit in breach")
    investigations = run_investigations(assistant, progress)
    return {
        "retrieval": retrieval,
        "refusals": refusals,
        "refusal": _share(sum(record["refused"] for record in refusals), len(refusals)),
        "tasks": records,
        "measures": measures(records),
        "investigations": investigations,
    }
