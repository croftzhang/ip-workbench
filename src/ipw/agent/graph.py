"""The assistant's loop: one LangGraph graph of four nodes (docs/AGENT_DESIGN.md, AD-4).

    retrieve -> model <-> tools
                  |  ^
                  v  |  one redraft
                check -> answer

* retrieve (code): the passages of the knowledge base that bear on the question;
* model (language model): a tool call, or a draft answer with citations;
* tools (code): runs the tool on the release 1 engine, within a budget of calls;
* check (code): verifies every figure and citation of the draft. A draft that
  fails goes back to the model once with the list of problems; if the second
  draft fails too, the answer is blocked and only the tool results are shown.

The graph keeps no state between runs: no checkpoints, no interrupts.
The same loop serves a routine question, a composed analysis, a question about
the documents and a breach investigation; the investigation is the loop started
with an instruction that lists the evidence to gather.
"""

from __future__ import annotations

import json
import operator
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from ipw.agent import runlog, verify
from ipw.agent.config import AgentConfig
from ipw.agent.retrieval import NOT_COVERED, Hit, Retrieval, Retriever
from ipw.agent.tools import Toolbox, ToolResult
from ipw.core.workbench import Workbench

PROPOSAL_LABEL = "Indicative only: not approved, no action taken."
BLOCKED = "The draft answer did not pass the check of its figures and citations, so it is not shown."
BUDGET_SPENT = "The tool budget is used up. Answer now from the results you have."

SYSTEM = """\
You are the analytics assistant of an Investment Portfolio desk: agency mortgage-backed securities \
and Treasuries, hedged with interest-rate swaps. The market date is {as_of}.

Rules:
1. Questions are about this portfolio on the market date. When a question asks for a measure of it (a \
value, a duration, an exposure, income, a limit, a position), call the tool that reports the measure and \
give the figure. A definition alone is not an answer.
2. Never calculate. Every figure in your answer is copied from a tool result, exactly as shown and in \
the same unit. For a sum, a difference or a share that is not already in a result, call the aggregate \
tool; if you do not, leave that figure out.
3. What the policy, the accounting note, the scenario definitions or the model documents say comes only \
from the passages below. Cite the passage right after the statement, like this: [IPS 4.3]. Cite only \
passages listed below.
4. If no tool and no passage answers the question, reply: "{not_covered}." You may add the nearest \
thing you can do. Do not answer from memory.
5. You may make at most {budget} tool calls; then you must answer.
6. The results of limit_remedy, size_hedge and what_if are indicative proposals: nothing is traded or booked.
7. Answer in English, in a few sentences. Do not repeat whole tables: the tables are shown under your answer.

{passages}"""

NO_PASSAGES = "Passages from the knowledge base: none. No passage matches this question."


def playbook(limit) -> str:
    """The instruction that starts a breach investigation: the evidence to gather, in order."""
    where = (
        f"scenario_breakdown for scenario {limit.scenario} by bucket: which buckets carry the change"
        if limit.scenario
        else "risk_report by bucket: which buckets carry the exposure"
    )
    return (
        f"Investigate the limit {limit.id} ({limit.name}). Gather the evidence in this order, then answer.\n"
        "1. limit_status: the value of the limit, its bound, its headroom, its status and its policy "
        "reference.\n"
        f"2. {where}.\n"
        "3. top_positions by dv01_k: the positions that contribute most.\n"
        "4. key_rate_report: where on the curve the exposure sits.\n"
        "5. explain_change: what moved since the prior close.\n"
        f"6. The policy clause {limit.policy_ref}, from the passages.\n"
        f"7. limit_remedy for {limit.id}: sized swap options and their cost to income.\n"
        "In the answer state: the limit and its headroom (how far it is inside or outside its bound); where "
        "the exposure comes from; what the policy requires; the options."
    )


def playbook_calls(limit) -> list[tuple[str, dict[str, Any]]]:
    """The tool calls the playbook asks for, in its order: tool and the arguments that matter."""
    where = (
        ("scenario_breakdown", {"scenario": limit.scenario, "by": "bucket"})
        if limit.scenario
        else ("risk_report", {"by": "bucket"})
    )
    return [
        ("limit_status", {}),
        where,
        ("top_positions", {"metric": "dv01_k"}),
        ("key_rate_report", {}),
        ("explain_change", {}),
        ("limit_remedy", {"limit": limit.id}),
    ]


@dataclass(frozen=True)
class Draft:
    text: str
    check: verify.Check


@dataclass(frozen=True)
class Answer:
    """What one run produced: the text that may be shown, and everything it rests on."""

    run_id: str
    time: str
    as_of: str  # market date
    question: str  # what the user asked
    task: str  # what the model was asked; differs from the question for an investigation
    text: (
        str  # the checked answer, or the notice that it was blocked; a proposal is labelled in its first line
    )
    status: str  # "answered" or "blocked"
    proposal: bool  # the run sized a trade or changed the book in a what-if: indicative
    retrieval: Retrieval
    hits: tuple[Hit, ...]  # the passages the model was given
    calls: tuple[ToolResult, ...]  # every tool call, errors included
    drafts: tuple[Draft, ...]
    model_calls: int
    tokens: dict[str, int]

    @property
    def results(self) -> tuple[ToolResult, ...]:
        """The tool results the answer rests on; they are shown under it."""
        return tuple(result for result in self.calls if result.ok)


class State(TypedDict):
    question: str
    task: str
    query: str  # what the knowledge base is asked
    pinned: tuple[str, ...]  # references that must be among the passages
    toolbox: Toolbox
    retrieval: Retrieval | None
    hits: tuple[Hit, ...]
    messages: Annotated[list[AnyMessage], add_messages]
    calls: int  # tool calls made so far
    drafts: Annotated[list[Draft], operator.add]


def _text(message: AnyMessage) -> str:
    return message.content if isinstance(message.content, str) else str(message.text)


_WRITTEN_CALL = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>|```(?:json)?\s*(\{.*?\})\s*```", flags=re.S
)


def written_tool_calls(text: str, known: set[str]) -> list[dict[str, Any]]:
    """Tool calls that a model wrote out as text, as JSON, instead of returning them as calls.

    Small local models do this now and then. Only a reply that is nothing but
    such calls is read this way, and only for the tools that exist.
    """
    text = verify.clean(text)
    found = [first or second for first, second in _WRITTEN_CALL.findall(text)]
    if not found and text.startswith("{") and text.endswith("}"):
        found = [text]
    if not found or _WRITTEN_CALL.sub("", text).strip() not in ("", text):
        return []
    calls = []
    for raw in found:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        arguments = data.get("arguments", data.get("parameters", {})) if isinstance(data, dict) else None
        if not isinstance(arguments, dict) or data.get("name") not in known:
            return []
        calls.append({"name": data["name"], "args": arguments, "id": f"written-{uuid.uuid4().hex[:8]}"})
    return calls


class Assistant:
    """The loop bound to a book, a chat model and, if given, a knowledge base."""

    def __init__(
        self,
        wb: Workbench,
        config: AgentConfig,
        chat: BaseChatModel,
        retriever: Retriever | None = None,
        log: runlog.RunLog | None = None,
    ):
        self.wb, self.config, self.retriever, self.log = wb, config, retriever, log
        self.budget = config.assistant.tool_calls
        specs = Toolbox(wb).specs
        self._tool_names = {spec.name for spec in specs}
        self._proposals = {spec.name for spec in specs if spec.proposal}
        self._chat = chat
        self._chat_with_tools = chat.bind_tools([spec.as_function() for spec in specs])
        self._codes = [source.code for source in config.knowledge_base.sources]
        self.graph = self._build()

    # ------------------------------------------------------------------ the graph
    def _build(self):
        graph = StateGraph(State)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("model", self._model)
        graph.add_node("tools", self._tools)
        graph.add_node("check", self._check)
        graph.add_edge(START, "retrieve")
        graph.add_edge("retrieve", "model")
        graph.add_conditional_edges("model", self._after_model, {"tools": "tools", "check": "check"})
        graph.add_edge("tools", "model")
        graph.add_conditional_edges("check", self._after_check, {"model": "model", "end": END})
        return graph.compile()

    def _retrieve(self, state: State) -> dict[str, Any]:
        """Code: the passages for the question, and the opening messages that carry them."""
        if self.retriever is None:
            found = Retrieval(state["query"], (), False, 0.0, "none")
            hits: tuple[Hit, ...] = ()
        else:
            found = self.retriever.retrieve(state["query"])
            wanted = [p for p in self.retriever.kb.passages.values() if p.ref in state["pinned"]]
            pinned = [Hit(passage, 0.0, None) for passage in wanted]
            others = [hit for hit in found.hits if hit.passage not in wanted]
            hits = tuple([*pinned, *others][: max(self.config.retrieval.top_k, len(pinned))])
        passages = NO_PASSAGES
        if hits:
            passages = "Passages from the knowledge base:\n\n" + "\n\n".join(
                f"[{hit.passage.ref}]\n{hit.passage.text}" for hit in hits
            )
        system = SYSTEM.format(
            as_of=state["toolbox"].as_of,
            budget=self.budget,
            not_covered=NOT_COVERED.capitalize(),
            passages=passages,
        )
        return {
            "retrieval": found,
            "hits": hits,
            "messages": [SystemMessage(system), HumanMessage(state["task"])],
        }

    def _model(self, state: State) -> dict[str, Any]:
        """Language model: a tool call or a draft. Once the budget is spent it is offered no tools."""
        if state["calls"] < self.budget:
            reply = self._chat_with_tools.invoke(state["messages"])
            written = [] if reply.tool_calls else written_tool_calls(_text(reply), self._tool_names)
            if written:  # the same reply, as the tool calls it spells out
                reply = AIMessage(
                    content="", tool_calls=written, id=reply.id, usage_metadata=reply.usage_metadata
                )
            return {"messages": [reply]}
        last = state["messages"][-1]
        told = isinstance(last, HumanMessage) and _text(last) == BUDGET_SPENT
        extra = [] if told else [HumanMessage(BUDGET_SPENT)]
        return {"messages": [*extra, self._chat.invoke([*state["messages"], *extra])]}

    def _after_model(self, state: State) -> str:
        last = state["messages"][-1]
        wants_tools = isinstance(last, AIMessage) and bool(last.tool_calls)
        return "tools" if wants_tools and state["calls"] < self.budget else "check"

    def _tools(self, state: State) -> dict[str, Any]:
        """Code: run the tools the model asked for, in order, until the budget is spent."""
        calls, replies = state["calls"], []
        for call in state["messages"][-1].tool_calls:
            if calls >= self.budget:
                text = f"not run: the budget of {self.budget} tool calls is used up"
            else:
                calls += 1
                arguments = call["args"] if isinstance(call["args"], dict) else {}
                text = state["toolbox"].call(call["name"], arguments).to_text()
            replies.append(ToolMessage(content=text, tool_call_id=call["id"], name=call["name"]))
        return {"messages": replies, "calls": calls}

    def _check(self, state: State) -> dict[str, Any]:
        """Code: verify the draft. A first failure goes back to the model with the list of problems."""
        last = state["messages"][-1]
        text = (
            verify.clean(_text(last)) if isinstance(last, AIMessage) else ""
        )  # only the model's words are a draft
        verdict = verify.check(
            text,
            question=state["question"],
            results=state["toolbox"].results,
            hits=state["hits"],
            codes=self._codes,
        )
        update: dict[str, Any] = {"drafts": [Draft(text, verdict)]}
        if not verdict.ok and not state["drafts"]:
            update["messages"] = [HumanMessage(verdict.feedback())]
        return update

    @staticmethod
    def _after_check(state: State) -> str:
        return "end" if state["drafts"][-1].check.ok or len(state["drafts"]) >= 2 else "model"

    # ------------------------------------------------------------------ running it
    def warm_up(self) -> None:
        """Make the chat model reply once, so that it is loaded before a run is timed."""
        self._chat.invoke([HumanMessage("Reply with the one word: ready")])

    def ask(
        self, question: str, *, task: str | None = None, query: str | None = None, pinned: Sequence[str] = ()
    ) -> Answer:
        """One question, one checked answer. The run is appended to the log."""
        toolbox = Toolbox(self.wb)
        start: State = {
            "question": question,
            "task": task or question,
            "query": query or question,
            "pinned": tuple(pinned),
            "toolbox": toolbox,
            "retrieval": None,
            "hits": (),
            "messages": [],
            "calls": 0,
            "drafts": [],
        }
        # every tool call is one visit to the model node and one to the tools node; two drafts at most
        end = self.graph.invoke(start, config={"recursion_limit": 2 * self.budget + 12})

        final = end["drafts"][-1]
        results = tuple(toolbox.results)
        shown = [result for result in results if result.ok]
        proposal = any(result.tool in self._proposals for result in shown)
        status = "answered" if final.check.ok else "blocked"
        text = final.text if final.check.ok else BLOCKED + (" The tool results follow." if shown else "")
        replies = [message for message in end["messages"] if isinstance(message, AIMessage)]
        usage = [message.usage_metadata for message in replies if message.usage_metadata]
        answer = Answer(
            run_id=uuid.uuid4().hex[:12],
            time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            as_of=toolbox.as_of,
            question=question,
            task=task or question,
            text=f"{PROPOSAL_LABEL}\n\n{text}" if proposal else text,
            status=status,
            proposal=proposal,
            retrieval=end["retrieval"],
            hits=end["hits"],
            calls=results,
            drafts=tuple(end["drafts"]),
            model_calls=len(replies),
            tokens={
                key: sum(item.get(key, 0) for item in usage) for key in ("input_tokens", "output_tokens")
            },
        )
        if self.log is not None:
            self.log.append(runlog.record(answer, self.config))
        return answer

    def investigate(self, limit_id: str) -> Answer:
        """The investigation playbook for one limit: the same loop, started with the evidence to gather."""
        limits = {limit.id: limit for limit in self.wb.limits}
        if limit_id not in limits:
            raise KeyError(f"unknown limit {limit_id!r}; limits: {', '.join(limits)}")
        limit = limits[limit_id]
        return self.ask(
            f"Investigate the limit {limit.id}",
            task=playbook(limit),
            query=f"{limit.policy_ref} {limit.name}: the limit, a breach and its remediation",
            pinned=(limit.policy_ref,),
        )
