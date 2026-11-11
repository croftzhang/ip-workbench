"""ipw-ai: AI mode, the assistant on a local language model.

``ipw`` is classic mode: fixed commands on the deterministic engine. ``ipw-ai``
is AI mode: a question in plain English is answered by a local language model
that calls the same engine through typed tools and cites the desk's documents.
Every figure it shows has been checked against a tool result, and every run is
appended to a log.

    ipw-ai ask "What is net duration?"
    ipw-ai investigate AOCI_UP200
    ipw-ai kb build
    ipw-ai eval
    ipw-ai mcp

AI mode is an optional install. The libraries it needs are imported when a
command runs, so this module loads, and says what to install, without them.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import typer
from rich.console import Console
from rich.markup import escape
from rich.measure import Measurement

from ipw.classic.render import rich_table
from ipw.core.workbench import Workbench

INSTALL_HINT = 'AI mode is an optional install: pip install -e ".[agent]"'

app = typer.Typer(
    help="AI mode: ask the portfolio analytics in plain English, on a local language model.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
kb_app = typer.Typer(help="The knowledge base the assistant cites.", no_args_is_help=True)
app.add_typer(kb_app, name="kb")

console = Console()
_state: dict = {"root": None}


@app.callback()
def _options(
    root: Path = typer.Option(
        None, "--root", help="Folder holding config/, data/ and kb/ (default: auto-detect)."
    ),
) -> None:
    _state["root"] = root


# ---------------------------------------------------------------------- building the assistant
def _config():
    from ipw.agent.config import load_agent_config

    return load_agent_config(_state["root"])


def _chat(config):
    from ipw.agent import models

    return models.chat(config.chat)


def _knowledge_base(config):
    """Open the index; build it first if it is missing or older than its sources."""
    from ipw.agent import kb

    try:
        return kb.open_index(config)
    except (kb.IndexMissing, kb.IndexOutOfDate) as err:
        console.print(f"[dim]{escape(str(err))}; building it now.[/]")
        return kb.build_index(config)


def _assistant():
    from ipw.agent import graph, retrieval, runlog

    config = _config()
    return graph.Assistant(
        Workbench.load(config.root),
        config,
        _chat(config),
        retrieval.Retriever(_knowledge_base(config), config.retrieval),
        runlog.RunLog(Path(config.root, config.assistant.run_log)),
    )


# ---------------------------------------------------------------------- showing an answer
def _print_wide(renderable, title: str) -> None:
    """Never truncate a number: a table wider than the window is printed at its full width."""
    needed = Measurement.get(console, console.options.update_width(10_000), renderable).maximum
    out = console if needed <= console.width else Console(width=needed)
    out.print(f"\n[bold]{escape(title)}[/]")
    out.print(renderable)


def show(answer, log_path: str) -> None:
    """The checked answer, the passages it cites, the tool results it rests on, and a line about the run."""
    from ipw.agent import verify

    console.print()
    console.print(answer.text, markup=False, highlight=False)

    cited = [hit.passage for hit in answer.hits if verify.cites(answer.text, hit.passage.ref)]
    cited = list(dict.fromkeys(cited))
    if cited:
        console.print("\n[bold]Sources[/]")
        for passage in cited:
            where = " > ".join(part for part in (passage.document, passage.heading) if part)
            console.print(f"[{passage.ref}] {where}", markup=False, highlight=False)

    for result in answer.results:
        for table in result.tables:
            if table.rows:
                frame = pd.DataFrame.from_dict(table.rows, orient="index")
                shown = rich_table(frame, None, None, table.index, table.default_format)
                _print_wide(shown, f"{result.id}  {table.title}")

    drafts = len(answer.drafts)
    outcome = "the answer was blocked" if answer.status == "blocked" else f"passed on draft {drafts}"
    run = f"Run {answer.run_id}: {len(answer.calls)} tool calls; check {outcome}."
    console.print(f"\n[dim]{run} Logged to {escape(log_path)}.[/]")


# ---------------------------------------------------------------------- commands
@app.command()
def ask(question: str = typer.Argument(..., help="The question, in quotes.")) -> None:
    """One question, one checked answer."""
    assistant = _assistant()
    show(assistant.ask(question), assistant.config.assistant.run_log)


@app.command()
def investigate(limit: str = typer.Argument(..., help="A limit id, for example AOCI_UP200.")) -> None:
    """The investigation playbook for a limit: where it stands, why, what the policy says, the options."""
    assistant = _assistant()
    show(assistant.investigate(limit), assistant.config.assistant.run_log)


@kb_app.command("build")
def kb_build() -> None:
    """Split, embed and index the knowledge base."""
    from ipw.agent import kb

    config = _config()
    built = kb.build_index(config)
    documents = len(config.knowledge_base.sources)
    embedder = config.embedding.model if config.embedding.provider == "ollama" else config.embedding.provider
    console.print(
        f"Indexed {len(built.passages)} passages from {documents} documents with {embedder} "
        f"into {escape(config.knowledge_base.index_dir)}."
    )


@app.command("eval")
def evaluate(
    mock: bool = typer.Option(
        False, "--mock", help="Run without models, on the mock model: tests the evaluation, not a model."
    ),
    out: Path = typer.Option(
        Path("reports/evaluation"), "--out", help="The report is written to <out>.md and <out>.json."
    ),
) -> None:
    """The evaluation report: retrieval, refusal and the benchmark tasks, measured on this machine."""
    from ipw.agent import evalreport, evals, graph, kb, retrieval, runlog
    from ipw.agent.tools import Toolbox

    config = _config()
    root = Path(config.root)
    wb = Workbench.load(root)
    tasks = evals.load_tasks(root / evals.TASK_SET)
    questions = evals.load_retrieval_questions(root / evals.RETRIEVAL_SET)
    report, data, runs = (Path(f"{out}{ending}") for ending in (".md", ".json", "_runs.jsonl"))
    report.parent.mkdir(parents=True, exist_ok=True)
    runs.unlink(missing_ok=True)  # the runs of this evaluation only

    def progress(line: str) -> None:
        console.print(line, markup=False, highlight=False)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
        if mock:
            console.print(f"[dim]{escape(evalreport.MOCK_NOTICE)}[/]")
            config = evals.mock_config(config, scratch)
            known = [*tasks, *evals.investigation_tasks(wb)]
            chat = evals.reference_model(known, lambda: Toolbox(wb))
            knowledge_base = kb.build_index(config)
        else:
            chat = _chat(config)
            knowledge_base = _knowledge_base(config)
        retriever = retrieval.Retriever(knowledge_base, config.retrieval)
        assistant = graph.Assistant(wb, config, chat, retriever, runlog.RunLog(runs))
        result = evals.evaluate(assistant, knowledge_base, tasks, questions, progress=progress)
        meta = evalreport.environment(config, mock=mock, as_of=Toolbox(wb).as_of)
    result = {"meta": meta} | result
    report.write_text(evalreport.render(result), encoding="utf-8")
    data.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")

    console.print()
    for measure, value, _ in evalreport.summary(result):
        console.print(f"{measure:<42}{value}", markup=False, highlight=False)
    console.print(f"\nReport: {report}\nData:   {data}\nRuns:   {runs}", markup=False, highlight=False)


@app.command()
def mcp() -> None:
    """Optional: serve the same tools to any other MCP client, on standard input and output."""
    from ipw.agent import mcp_server

    mcp_server.run(_state["root"])


def _fail(message: str) -> None:
    Console(stderr=True).print(f"[bold red]Error:[/] {escape(message)}")
    raise SystemExit(1) from None


def main() -> None:
    """Entry point: turn expected errors into one-line messages instead of tracebacks."""
    expected: tuple = (KeyError, ValueError, FileNotFoundError, ConnectionError)
    unreachable: tuple = ()
    try:
        import httpx
        import ollama

        expected += (ollama.ResponseError,)  # for example: the model has not been pulled
        unreachable = (httpx.TransportError,)  # the server is not running, or stopped answering
    except ModuleNotFoundError:
        pass
    try:
        app()
    except ModuleNotFoundError as err:
        if (err.name or "").startswith("ipw"):
            raise
        _fail(f"{INSTALL_HINT} (missing module: {err.name})")
    except unreachable as err:
        _fail(f"cannot reach the Ollama server ({err}). Start Ollama and try again.")
    except expected as err:
        _fail(str(err.args[0]) if err.args else str(err))


if __name__ == "__main__":
    main()
