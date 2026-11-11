"""Release 2, build step 3: the ``ipw-ai`` command (docs/AGENT_DESIGN.md, AD-9).

The commands on the mock model, the one-line errors, and one test in which the
real Ollama chat class talks over HTTP to a local stand-in for the server: it
shows that the request carries the configured settings and the tool
definitions, and that a tool call in the reply drives the loop.
"""

import dataclasses
import json
import sys

import pytest
from typer.testing import CliRunner

from ipw.agent import cli

graph = pytest.importorskip("ipw.agent.graph", reason='needs the agent extra: pip install -e ".[agent]"')
models = pytest.importorskip("ipw.agent.models")
tools = pytest.importorskip("ipw.agent.tools")
messages = pytest.importorskip("langchain_core.messages")


def tool_call(name: str, **arguments):
    return messages.AIMessage(
        content="", tool_calls=[{"name": name, "args": arguments, "id": f"call-{name}"}]
    )


def say(text: str):
    return messages.AIMessage(content=text)


def words(text: str) -> str:
    """Output with its line breaks and padding removed: the terminal wraps long lines."""
    return " ".join(text.split())


@pytest.fixture
def run(monkeypatch, agent_config, knowledge_base):
    """Run ``ipw-ai`` on a scripted model, the test embeddings and the session's index."""

    def go(script, *arguments, config=agent_config):
        monkeypatch.setattr(cli, "_config", lambda: config)
        monkeypatch.setattr(cli, "_chat", lambda _config: models.ScriptedChatModel(script=script))
        return CliRunner().invoke(cli.app, list(arguments))

    return go


def fails(monkeypatch, capsys, *arguments) -> str:
    """Run the entry point as the installed command does, and return its one-line error."""
    monkeypatch.setattr(sys, "argv", ["ipw-ai", *arguments])
    with pytest.raises(SystemExit) as stop:
        cli.main()
    assert stop.value.code == 1
    return words(capsys.readouterr().err)


# --------------------------------------------------------------------------- the commands


def test_the_command_lists_what_ai_mode_does():
    shown = CliRunner().invoke(cli.app, ["--help"])
    assert shown.exit_code == 0 and "AI mode" in shown.output
    for command in ("ask", "investigate", "kb", "eval", "mcp"):
        assert f" {command} " in shown.output
    assert "build" in CliRunner().invoke(cli.app, ["kb", "--help"]).output


def test_ask_shows_the_checked_answer_then_the_tool_results_it_rests_on(run, agent_config):
    script = [tool_call("limit_status"), say("AOCI_UP200 is in BREACH: -225.99 against a floor of -210.00.")]
    shown = run(script, "ask", "Is the AOCI limit breached?")
    assert shown.exit_code == 0, shown.output
    text = words(shown.output)
    answer, table, footer = text.partition("r1 Policy limits (config/limits.yaml)")
    assert answer.strip() == "AOCI_UP200 is in BREACH: -225.99 against a floor of -210.00."
    assert "AOCI_UP200" in footer and "-225.99" in footer and "BREACH" in footer and "IPS 4.3" in footer
    assert "1 tool calls; check passed on draft 1. Logged to" in footer
    logged = json.loads(open(agent_config.assistant.run_log, encoding="utf-8").read().splitlines()[-1])
    assert logged["question"] == "Is the AOCI limit breached?" and f"Run {logged['run_id']}:" in footer


def test_ask_lists_the_passages_the_answer_cites(run):
    shown = run([say("The after-tax AOCI loss in a 200bp rise may not exceed USD 210 million [IPS 4.3].")],
                "ask", "Which limit applies to the after-tax AOCI loss in a 200bp sell-off?")  # fmt: skip
    text = words(shown.output)
    assert shown.exit_code == 0 and "may not exceed USD 210 million [IPS 4.3]. Sources" in text
    heading = "Investment Policy Statement > 4. Interest-rate risk limits > 4.3 AOCI sensitivity"
    assert (
        f"Sources [IPS 4.3] {heading} Run" in text
    )  # only the cited passage is listed; no tool table follows
    assert "0 tool calls; check passed on draft 1." in text


def test_investigate_puts_the_proposal_label_first(run):
    script = [
        tool_call("limit_status"),
        tool_call("limit_remedy", limit="AOCI_UP200", tenors=[5]),
        say(
            "AOCI_UP200 is in BREACH at -225.99 [IPS 4.3]. A PAY_FIXED 5Y swap of 260.0 brings it to -209.40."
        ),
    ]
    shown = run(script, "investigate", "AOCI_UP200")
    assert shown.exit_code == 0, shown.output
    first, second = [line.strip() for line in shown.output.strip().splitlines() if line.strip()][:2]
    assert first == "Indicative only: not approved, no action taken." and second.startswith(
        "AOCI_UP200 is in BREACH"
    )
    text = words(shown.output)
    assert "r2 Swap options to bring AOCI_UP200 to its limit (indicative)" in text and "PAY_FIXED 5Y" in text
    assert "2 tool calls; check passed on draft 1." in text
    sources = text.partition("Sources ")[2].partition(" r1 ")[0]
    assert (
        sources
        == "[IPS 4.3] Investment Policy Statement > 4. Interest-rate risk limits > 4.3 AOCI sensitivity"
    )
    assert (
        "[IPS 4] " not in text
    )  # the section above it was given to the model but is not what the answer cites


def test_a_blocked_answer_shows_the_notice_and_the_tables_never_the_draft(run):
    shown = run(
        [tool_call("limit_status"), say("The loss is 300.5."), say("The loss is 999.9.")], "ask", "How large?"
    )
    text = words(shown.output)
    assert shown.exit_code == 0
    assert text.startswith(
        "The draft answer did not pass the check of its figures and citations, so it is not shown."
    )
    assert "300.5" not in text and "999.9" not in text
    assert "r1 Policy limits" in text and "check the answer was blocked." in text


def test_kb_build_indexes_the_sources_and_a_question_builds_a_missing_index(run, agent_config, tmp_path):
    elsewhere = dataclasses.replace(
        agent_config,
        knowledge_base=dataclasses.replace(agent_config.knowledge_base, index_dir=str(tmp_path / "idx")),
    )
    asked = run(
        [say("The knowledge base does not cover this.")], "ask", "Wie spaet ist es jetzt?", config=elsewhere
    )
    assert asked.exit_code == 0, asked.output
    assert "the knowledge base index has not been built; building it now." in words(asked.output)
    again = run(
        [say("The knowledge base does not cover this.")], "ask", "Wie spaet ist es jetzt?", config=elsewhere
    )
    assert again.exit_code == 0 and "building it now" not in again.output  # built once, then opened

    built = run([], "kb", "build", config=elsewhere)
    assert built.exit_code == 0, built.output
    assert words(built.output).startswith("Indexed 130 passages from 8 documents with hashing into")


# --------------------------------------------------------------------------- one-line errors


def test_an_unknown_limit_is_a_one_line_error(monkeypatch, capsys, agent_config, knowledge_base):
    monkeypatch.setattr(cli, "_config", lambda: agent_config)
    monkeypatch.setattr(cli, "_chat", lambda _config: models.ScriptedChatModel(script=[]))
    message = fails(monkeypatch, capsys, "investigate", "AOCI_UP300")
    assert message.startswith("Error: unknown limit 'AOCI_UP300'; limits: DUR_BAND, ")


def test_ai_mode_without_its_extra_says_what_to_install(monkeypatch, capsys, agent_config):
    import ipw.agent

    monkeypatch.setattr(cli, "_config", lambda: agent_config)
    monkeypatch.delitem(sys.modules, "ipw.agent.graph")  # so that the command imports it afresh
    monkeypatch.delattr(ipw.agent, "graph")
    monkeypatch.setitem(sys.modules, "langgraph", None)  # makes "import langgraph" fail as if not installed
    monkeypatch.setitem(sys.modules, "langgraph.graph", None)
    message = fails(monkeypatch, capsys, "ask", "What is net duration?")
    assert message.startswith(
        'Error: AI mode is an optional install: pip install -e ".[agent]" (missing module: langgraph'
    )


def test_a_server_that_is_not_running_is_a_one_line_error(monkeypatch, capsys, agent_config, knowledge_base):
    unreachable = dataclasses.replace(
        agent_config, chat=dataclasses.replace(agent_config.chat, base_url="http://127.0.0.1:9")
    )
    monkeypatch.setattr(cli, "_config", lambda: unreachable)
    message = fails(monkeypatch, capsys, "ask", "What is net duration?")
    assert message.startswith("Error: cannot reach the Ollama server (") and "Traceback" not in message
    assert message.endswith("Start Ollama and try again.")


def test_a_model_that_has_not_been_pulled_is_a_one_line_error(
    monkeypatch, capsys, agent_config, knowledge_base, fake_ollama
):
    fake_ollama.error = (404, "model 'qwen3:8b' not found")
    served = dataclasses.replace(
        agent_config, chat=dataclasses.replace(agent_config.chat, base_url=fake_ollama.url)
    )
    monkeypatch.setattr(cli, "_config", lambda: served)
    message = fails(monkeypatch, capsys, "ask", "What is net duration?")
    assert message.startswith("Error: model 'qwen3:8b' not found") and "Traceback" not in message


# --------------------------------------------------------------------------- the real chat class


def test_the_real_chat_class_sends_the_settings_and_tools_and_follows_a_tool_call(
    monkeypatch, wb, agent_config, knowledge_base, fake_ollama
):
    """ChatOllama against a local stand-in for the server: no model, but the real client and wire format."""
    fake_ollama.replies = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "limit_status", "arguments": {}}}],
        },
        {"role": "assistant", "content": "AOCI_UP200 is in BREACH: -225.99 against a floor of -210.00."},
    ]
    served = dataclasses.replace(
        agent_config, chat=dataclasses.replace(agent_config.chat, base_url=fake_ollama.url)
    )
    monkeypatch.setattr(cli, "_config", lambda: served)
    shown = CliRunner().invoke(cli.app, ["ask", "Is the AOCI limit breached?"])
    assert shown.exit_code == 0, shown.output
    assert "AOCI_UP200 is in BREACH: -225.99 against a floor of -210.00." in words(shown.output)
    assert "1 tool calls; check passed on draft 1." in words(shown.output)

    first, second = fake_ollama.requests
    for request in (first, second):
        assert request["model"] == "qwen3:8b" and request["think"] is False  # thinking mode off
        assert request["options"] == {"num_ctx": 16384, "num_predict": 2048, "temperature": 0.0, "seed": 42}
        assert [tool["function"]["name"] for tool in request["tools"]] == [
            s.name for s in tools.Toolbox(wb).specs
        ]
    offered = {tool["function"]["name"]: tool["function"] for tool in first["tools"]}
    assert offered["limit_remedy"]["parameters"]["properties"]["limit"]["enum"] == [
        limit.id for limit in wb.limits
    ]
    assert offered["limit_status"]["description"] == tools.Toolbox(wb).spec("limit_status").description

    assert [message["role"] for message in first["messages"]] == ["system", "user"]
    assert first["messages"][1]["content"] == "Is the AOCI limit breached?"
    assert [message["role"] for message in second["messages"]] == ["system", "user", "assistant", "tool"]
    assert second["messages"][2]["tool_calls"][0]["function"] == {"name": "limit_status", "arguments": {}}
    assert second["messages"][3]["content"].startswith("result r1: limit_status {}, market date 2026-11-09")

    logged = json.loads(open(served.assistant.run_log, encoding="utf-8").read().splitlines()[-1])
    assert logged["tokens"] == {"input_tokens": 2400, "output_tokens": 80} and logged["model_calls"] == 2
