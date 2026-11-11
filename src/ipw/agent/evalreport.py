"""The evaluation report: the result of ``ipw.agent.evals.evaluate`` as a Markdown document.

The report states where and with what it was measured, the measures of
docs/AGENT_DESIGN.md (AD-8), the retrieval table, the table of release 1
against release 2, every task with its outcome, the text of every answer that
was not correct, and the investigation of each limit in breach. Results below
target are reported as measured.
"""

from __future__ import annotations

import platform
import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime
from importlib import metadata
from typing import Any

from ipw.agent.config import AgentConfig
from ipw.agent.evals import CLASSES, HIT_RATE_TARGET

PACKAGES = ("langgraph", "langchain-core", "langchain-ollama", "langchain-chroma", "chromadb", "ollama")
MOCK_NOTICE = (
    "This run used the mock model and word-hash embeddings. It shows that the evaluation works. "
    "It says nothing about the quality of a real model."
)


# ====================================================================== where and with what
def _gpu() -> str | None:
    """Name and memory of the graphics cards, from nvidia-smi if it is there."""
    query = ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"]
    try:
        found = subprocess.run(query, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = [line.strip() for line in found.stdout.splitlines() if line.strip()]
    return "; ".join(lines) if found.returncode == 0 and lines else None


def _served(model: str, base_url: str | None) -> str | None:
    """What the Ollama server says about a model: size, quantisation, digest, share held in GPU memory."""
    try:
        import ollama

        client = ollama.Client(host=base_url)
        names = (model, f"{model}:latest")
        listed = next((m for m in client.list().models if m.model in names), None)
        loaded = next((m for m in client.ps().models if m.model in names), None)
    except Exception:  # the report is written without these details
        return None
    parts = []
    details = getattr(listed, "details", None)
    if details is not None:
        parts += [text for text in (details.parameter_size, details.quantization_level) if text]
    if listed is not None and listed.digest:
        parts.append(f"digest {listed.digest[:12]}")
    if loaded is not None and loaded.size and loaded.size_vram is not None:
        parts.append(f"{100.0 * int(loaded.size_vram) / int(loaded.size):.0f}% in GPU memory")
    return ", ".join(parts) or None


def environment(config: AgentConfig, *, mock: bool, as_of: str) -> dict[str, Any]:
    """Where and with what a run was measured. Call it right after the run: the chat model is still loaded."""
    packages = {}
    for name in PACKAGES:
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    chat, embedding, retrieval = config.chat, config.embedding, config.retrieval
    return {
        "date": datetime.now().astimezone().isoformat(timespec="minutes"),
        "market_date": as_of,
        "mock": mock,
        "system": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "gpu": None if mock else _gpu(),
        "python": platform.python_version(),
        "packages": packages,
        "chat": {
            "model": "mock model that follows the reference path" if mock else chat.model,
            "temperature": chat.temperature,
            "seed": chat.seed,
            "num_ctx": chat.num_ctx,
            "num_predict": chat.num_predict,
            "reasoning": chat.reasoning,
            "served": None if mock else _served(chat.model, chat.base_url),
        },
        "embedding": {
            "model": "word-hash vectors" if embedding.provider == "hashing" else embedding.model,
            "served": None if mock else _served(embedding.model, embedding.base_url),
        },
        "retrieval": {
            "top_k": retrieval.top_k,
            "candidates": retrieval.candidates,
            "refuse_below": retrieval.refuse_below,
            "keyword": retrieval.keyword,
            "rerank": retrieval.rerank,
        },
        "tool_calls": config.assistant.tool_calls,
    }


# ====================================================================== formatting
def _percent(share: Mapping[str, Any]) -> str:
    if not share["of"]:
        return "not measured"
    return f"{100.0 * share['count'] / share['of']:.1f}% ({share['count']} of {share['of']})"


def _seconds(value: float | None, decimals: int = 1) -> str:
    return "-" if value is None else f"{value:.{decimals}f}"


def _times(times: Mapping[str, Any]) -> str:
    if not times["runs"]:
        return "not measured"
    return f"median {times['median']:.1f} s; 90th percentile {times['p90']:.1f} s"


def _row(cells: Sequence[Any]) -> str:
    return "| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells) + " |"


def _table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    return [_row(header), "|" + "---|" * len(header), *(_row(row) for row in rows), ""]


def _quote(text: str, limit: int = 1500) -> list[str]:
    text = text if len(text) <= limit else text[:limit].rstrip() + " [...]"
    return [f"> {line}" if line.strip() else ">" for line in text.splitlines()] + [""]


def _on(switch: bool) -> str:
    return "on" if switch else "off"


def summary(result: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """The measures of AD-8: name, result, and the set it was measured on."""
    found, tasks = result["retrieval"], result["measures"]
    vector = found["methods"][0]
    hits = {"count": vector["hits"], "of": vector["in_scope"]}
    by_threshold = {"count": vector["refused"], "of": vector["out_of_scope"]}
    benchmark = tasks["benchmark"]
    on_benchmark = f"{benchmark['tasks']} benchmark tasks"
    return [
        (
            "Retrieval hit rate at 4",
            _percent(hits),
            f"{vector['in_scope']} questions with reference sections; target at least {HIT_RATE_TARGET:.0%}",
        ),
        (
            "Refusal correctness, the assistant",
            _percent(result["refusal"]),
            f"{vector['out_of_scope']} questions outside the knowledge base, asked of the assistant",
        ),
        (
            "Refusal correctness, the threshold alone",
            _percent(by_threshold),
            "The same questions: refused by the similarity threshold, before the model is asked",
        ),
        (
            "Tool-selection accuracy",
            _percent(tasks["tool_selection"]),
            f"{tasks['tool_selection']['of']} routine tasks",
        ),
        ("First-draft pass rate", _percent(benchmark["first_draft_passed"]), on_benchmark),
        ("Block rate", _percent(benchmark["blocked"]), on_benchmark),
        ("Answer correctness", _percent(benchmark["correct"]), on_benchmark),
        ("Time to answer", _times(benchmark["seconds"]), on_benchmark),
    ]


def _outcome(run: Mapping[str, Any]) -> str:
    if run["status"] == "answered":
        return "correct" if run["correct"] else "incorrect"
    return run["status"]


def _check(run: Mapping[str, Any]) -> str:
    if run["status"] not in ("answered", "blocked"):
        return "-"
    return "blocked" if run["status"] == "blocked" else f"passed on draft {len(run['drafts'])}"


def _calls(run: Mapping[str, Any]) -> str:
    made = [
        f"{call['tool']} {call['arguments']}" + ("" if call["ok"] else f" -> error: {call['error']}")
        for call in run.get("tool_calls") or []
    ]
    return "; ".join(made) or "none"


# ====================================================================== the report
def render(result: Mapping[str, Any]) -> str:
    meta, found, measured = result["meta"], result["retrieval"], result["measures"]
    lines = ["# Evaluation report", "", "Written by `ipw-ai eval`.", ""]
    if meta["mock"]:
        lines += [f"**{MOCK_NOTICE}**", ""]

    # ------------------------------------------------------------------ 1. the run
    chat, embedding, settings = meta["chat"], meta["embedding"], meta["retrieval"]
    machine = "; ".join(part for part in (meta["system"], meta["processor"]) if part)
    chat_line = (
        f"{chat['model']}; temperature {chat['temperature']:g}, seed {chat['seed']}, "
        f"context {chat['num_ctx']} tokens, replies up to {chat['num_predict']} tokens, "
        f"reasoning {_on(chat['reasoning'])}"
    )
    retrieval_line = (
        f"{settings['top_k']} passages from {settings['candidates']} candidates; "
        f"refuse below {settings['refuse_below']:g}; keyword fusion {_on(settings['keyword'])}; "
        f"reranking {_on(settings['rerank'])}"
    )
    tasks = result["tasks"]
    sets = (
        f"{sum(q['in_scope'] for q in found['questions'])} retrieval questions and "
        f"{sum(not q['in_scope'] for q in found['questions'])} outside the knowledge base; "
        f"{len(tasks)} tasks, {sum(task['benchmark'] for task in tasks)} of them the benchmark"
    )
    lines += ["## 1. The run", ""]
    lines += _table(
        ["", ""],
        [
            ("Date", meta["date"]),
            ("Market date", meta["market_date"]),
            ("Machine", machine),
            ("GPU", meta["gpu"] or "not reported"),
            ("Python", meta["python"]),
            ("Chat model", chat_line + (f" ({chat['served']})" if chat["served"] else "")),
            (
                "Embedding model",
                embedding["model"] + (f" ({embedding['served']})" if embedding["served"] else ""),
            ),
            ("Retrieval", retrieval_line),
            ("Tool-call budget", meta["tool_calls"]),
            ("Packages", ", ".join(f"{name} {version}" for name, version in meta["packages"].items())),
            ("Sets", sets),
        ],
    )

    # ------------------------------------------------------------------ 2. measures
    lines += ["## 2. Measures", ""]
    lines += _table(["Measure", "Result", "Set"], summary(result))
    lines += [
        "A figure is shown only in an answer that passed the check. When the second draft fails too, "
        "the answer is blocked and only the tool results are shown.",
        "",
    ]
    benchmark = measured["benchmark"]
    if benchmark["errors"] or measured["not_run"]:
        lines += [
            f"Runs that ended in an error: {benchmark['errors']} of the benchmark tasks; they count as not "
            f"correct. Tasks not run: {measured['not_run']}; they are left out of every measure.",
            "",
        ]

    # ------------------------------------------------------------------ 3. retrieval
    lines += ["## 3. Retrieval", ""]
    rows = []
    for method in found["methods"]:
        name = method["method"] + (" (the setting in use)" if method["default"] else "")
        if not method["installed"]:
            rows.append((name, "not installed", "not installed"))
            continue
        hits = {"count": method["hits"], "of": method["in_scope"]}
        refused = f"{method['refused']} of {method['out_of_scope']}"
        rows.append((name, _percent(hits), refused))
    lines += _table(["Method", "Hit rate at 4", "Refused by the threshold, outside the knowledge base"], rows)
    by_id = {question["id"]: question for question in found["questions"]}
    misses = [by_id[name] for name in found["methods"][0]["misses"]]
    if misses:
        lines += ["Questions for which vector search returned no reference section:", ""]
        lines += _table(
            ["Id", "Question", "Reference sections", "Sections returned"],
            [(q["id"], q["question"], ", ".join(q["references"]), ", ".join(q["returned"])) for q in misses],
        )
    similar = found["similarity"]
    lines += ["Best similarity of a question to a passage, vector search:", ""]
    lines += _table(
        ["Questions", "Lowest", "Median", "Highest"],
        [
            (name, *(f"{similar[key][stat]:.3f}" for stat in ("min", "median", "max")))
            for name, key in (
                ("With an answer in the knowledge base", "in_scope"),
                ("Outside the knowledge base", "out_of_scope"),
            )
        ],
    )
    lines += [
        f"Threshold in use: {found['refuse_below']:g}. The threshold that separates these questions best: "
        f"{found['suggested_threshold']:.3f}.",
        "",
    ]

    # ------------------------------------------------------------------ 4. release 1 against release 2
    lines += ["## 4. Release 1 against release 2", ""]
    rows = []
    for name, part in [*((kind, measured["classes"][kind]) for kind in CLASSES), ("all", benchmark)]:
        release1 = part["release1"]
        rows.append(
            (
                name,
                part["tasks"],
                release1["one command"],
                release1["commands and work by hand"],
                release1["no"],
                _percent(part["correct"]),
                part["blocked"]["count"],
                part["first_draft_passed"]["count"],
                _seconds(part["seconds"]["median"]),
                _seconds(part["release1_seconds"]["median"], 2),
            )
        )
    lines += _table(
        [
            "Class",
            "Tasks",
            "Release 1: one command",
            "Release 1: commands and work by hand",
            "Release 1: cannot",
            "Release 2 correct",
            "Release 2 blocked",
            "First draft passed",
            "Seconds, release 2 (median)",
            "Seconds, release 1 commands (median)",
        ],
        rows,
    )
    lines += [
        "Release 1 answers a task when its commands show the figures of the answer. The seconds of release 1 "
        "are those of the commands, run in this process with the book loaded; work by hand is not timed. "
        "The seconds of release 2 are from the question to the checked answer, with the models loaded.",
        "",
    ]

    # ------------------------------------------------------------------ 5. tasks
    lines += ["## 5. Tasks", ""]
    rows = []
    for task in tasks:
        run, release1 = task["release2"], task["release1"]
        tools = (
            "-" if run.get("tools_selected") is None else "reference" if run["tools_selected"] else "other"
        )
        in_benchmark = "yes" if task["benchmark"] else "no"
        rows.append(
            (
                task["id"],
                task["class"],
                in_benchmark,
                task["question"],
                release1["verdict"] + (f" (failed: {release1['error']})" if release1["error"] else ""),
                _outcome(run),
                _check(run),
                tools,
                _seconds(run["seconds"]),
            )
        )
    lines += _table(
        [
            "Task",
            "Class",
            "Benchmark",
            "Question",
            "Release 1",
            "Release 2",
            "Check",
            "Tool calls",
            "Seconds",
        ],
        rows,
    )
    lines += [
        "Tool calls are compared with the reference for routine tasks only: the calls that returned a result "
        "have to be the calls of one accepted way to answer.",
        "",
    ]

    failed = [task for task in tasks if _outcome(task["release2"]) not in ("correct", "not run")]
    wrong_tools = [task for task in tasks if task["release2"].get("tools_selected") is False]
    if failed:
        lines += ["### Tasks not answered correctly", ""]
    for task in failed:
        run = task["release2"]
        lines += [f"**{task['id']}** {task['question']}", ""]
        lines += [f"- Outcome: {_outcome(run)}" + (f" ({run['error']})" if run["error"] else "")]
        if run["status"] == "error":
            lines += [""]
            continue
        lines += [f"- Reference: {'; '.join(task['reference'])}" + _cited(task)]
        if run["missing"]:
            lines += [f"- Not in the answer: {'; '.join(run['missing'])}"]
        lines += [f"- Tool calls: {_calls(run)}"]
        lines += [f"- Passages given: {', '.join(run['passages']) or 'none'}"]
        for number, draft in enumerate(run["drafts"], start=1):
            if not draft["passed"]:
                lines += [f"- Draft {number} failed the check: {'; '.join(draft['problems'])}"]
        lines += [""]
        if run["status"] == "blocked":
            lines += ["The last draft, which was not shown:", ""]
            lines += _quote(run["drafts"][-1]["text"] or "(empty)")
        else:
            lines += ["The answer:", ""]
            lines += _quote(run["answer"])
    only_tools = [task for task in wrong_tools if task not in failed]
    if only_tools:
        lines += ["### Routine tasks answered correctly with other tool calls than the reference", ""]
        lines += _table(
            ["Task", "Question", "Tool calls made"],
            [(task["id"], task["question"], _calls(task["release2"])) for task in only_tools],
        )

    # ------------------------------------------------------------------ 6. refusal
    lines += ["## 6. Questions outside the knowledge base", ""]
    rows = []
    for record in result["refusals"]:
        if record["status"] == "error":
            rows.append((record["id"], record["question"], "-", "-", f"error: {record['error']}"))
            continue
        outcome = "refused" if record["refused"] else record["status"]
        similarity = f"{record['best_similarity']:.3f}"
        rows.append((record["id"], record["question"], similarity, len(record["passages"]), outcome))
    lines += _table(["Id", "Question", "Best similarity", "Passages given", "The assistant"], rows)
    for record in result["refusals"]:
        if record["status"] == "answered" and not record["refused"]:
            lines += [f"**{record['id']}** {record['question']}", ""]
            lines += [f"- Tool calls: {_calls(record)}", ""]
            lines += _quote(record["answer"])

    # ------------------------------------------------------------------ 7. investigation
    lines += ["## 7. Investigation of each limit in breach", ""]
    lines += [
        "The investigation playbook is run for every limit whose status is BREACH. A step is done when the "
        "tool it names returned a result. The reference is the headroom of the limit, the notional of a "
        "sized option and a citation of the policy section of the limit.",
        "",
    ]
    if not result["investigations"]:
        lines += ["No limit is in breach, or the run was stopped before this part.", ""]
    for record in result["investigations"]:
        lines += [f"**{record['limit']}**", ""]
        if record["status"] == "error":
            lines += [f"- Outcome: error ({record['error']})", ""]
            continue
        steps = record["steps"]
        skipped = [step["tool"] for step in steps if not step["done"]]
        done = f"{len(steps) - len(skipped)} of {len(steps)}"
        lines += [f"- Playbook steps done: {done}" + (f"; not done: {', '.join(skipped)}" if skipped else "")]
        lines += [f"- Check: {_check(record)}"]
        for number, draft in enumerate(record["drafts"], start=1):
            if not draft["passed"]:
                lines += [f"- Draft {number} failed the check: {'; '.join(draft['problems'])}"]
        if record["status"] == "answered":
            lacking = "; ".join(record["missing"])
            lines += ["- Reference in the answer: " + (f"no; missing: {lacking}" if lacking else "yes")]
        lines += [f"- Tool calls: {_calls(record)}"]
        lines += [f"- Passages given: {', '.join(record['passages']) or 'none'}"]
        lines += [f"- Seconds: {_seconds(record['seconds'])}", ""]
        if record["status"] == "blocked":
            lines += ["The last draft, which was not shown:", ""]
            lines += _quote(record["drafts"][-1]["text"] or "(empty)", limit=4000)
        else:
            lines += ["The answer:", ""]
            lines += _quote(record["answer"], limit=4000)
    return "\n".join(lines).rstrip() + "\n"


def _cited(task: Mapping[str, Any]) -> str:
    return f"; a citation of {' or '.join(task['cites'])}" if task["cites"] else ""
