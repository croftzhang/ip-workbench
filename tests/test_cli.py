"""Command-line interface and daily brief."""

import json
import re

import pytest
from typer.testing import CliRunner

from ipw.classic import cli
from ipw.classic.brief import build_brief, usd, write_brief

runner = CliRunner()

COMMANDS = [
    ["summary"],
    ["summary", "--by", "designation"],
    ["risk", "--by", "coupon"],
    ["krd"],
    ["krd", "--unit", "k", "--by", "bucket"],
    ["position", "FN30-2.5-001"],
    ["top", "--metric", "unrealized_mm", "--asc", "-n", "3"],
    ["scenario"],
    ["scenario", "--list"],
    ["scenario", "-n", "up_100", "-s", "-75"],
    ["scenario", "-s", "200", "--by", "bucket"],
    ["nii"],
    ["prepay"],
    ["prepay", "--s-curve"],
    ["explain"],
    ["limits"],
    ["fix", "AOCI_UP200", "--tenors", "5"],
    ["hedge", "-t", "4.5"],
    ["hedge", "-t", "4.5", "--mode", "krd", "--tenors", "2,5,10"],
    ["whatif", "--drop", "FN30-2.5-001", "--pay-fixed", "5:250"],
    ["brief", "--stdout"],
]


@pytest.fixture(autouse=True)
def _use_repository_root(root):
    cli._load.cache_clear()
    yield


@pytest.mark.parametrize("args", COMMANDS, ids=lambda a: " ".join(a))
def test_every_command_runs(root, args):
    result = runner.invoke(cli.app, ["--root", str(root), *args])
    assert result.exit_code == 0, result.output
    assert result.output.strip()
    assert (
        "\u2026" not in result.output
    )  # no cell is ever truncated with an ellipsis, however narrow the window


def test_json_output_is_machine_readable(root):
    result = runner.invoke(cli.app, ["--root", str(root), "--format", "json", "limits"])
    payload = json.loads(result.output)
    rows = {row["limit"]: row for row in payload["rows"]}
    assert rows["AOCI_UP200"]["status"] == "BREACH" and rows["DUR_BAND"]["status"] == "WARN"


def test_markdown_output(root):
    result = runner.invoke(cli.app, ["--root", str(root), "-f", "md", "summary"])
    assert result.exit_code == 0 and "| Bucket |" in result.output and "| Total |" in result.output


def test_bad_input_gives_a_clean_error(root, monkeypatch, capsys):
    for args in (["position", "NOPE"], ["scenario", "-n", "no_such"], ["fix", "NII_UP100"]):
        monkeypatch.setattr("sys.argv", ["ipw", "--root", str(root), *args])
        with pytest.raises(SystemExit) as exit_info:
            cli.main()
        assert exit_info.value.code == 1
        assert "Error:" in capsys.readouterr().err


def test_missing_root_is_reported(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["ipw", "--root", str(tmp_path), "summary"])
    with pytest.raises(SystemExit):
        cli.main()
    assert "does not contain config/market.yaml" in " ".join(capsys.readouterr().err.split())


# --------------------------------------------------------------------------- brief
def test_us5_brief_has_every_section_and_the_same_numbers_as_the_workbench(wb):
    """US-5: the brief is complete and its figures are the workbench's figures."""
    text = build_brief(wb)
    titles = re.findall(r"^## (.+)$", text, flags=re.M)
    assert titles == [
        "1. Headline", "2. Limits", "3. Composition and valuation", "4. Interest-rate risk", "5. Scenarios",
        "6. Net interest income", "7. Change since prior close", "8. Prepayment outlook",
        "9. Largest exposures", "10. Hedge book", "Method and limitations",
    ]  # fmt: skip
    headline = wb.headline()
    assert usd(headline["market_value_mm"]) in text
    assert f"Net effective duration {headline['net_duration']:.2f} years" in text
    assert f"{wb.run('up_200').aoci.after_tax:,.2f} $mm" in text
    assert "**BREACH AOCI_UP200**" in text and "**WARN DUR_BAND**" in text
    assert "Indicative remediation for AOCI_UP200" in text
    assert text.isascii()  # safe on any Windows console or code page


def test_brief_is_deterministic_and_written_to_disk(wb, tmp_path):
    path = write_brief(wb, tmp_path)
    assert path.name == f"brief_{wb.market.as_of}.md"
    assert path.read_text(encoding="utf-8") == build_brief(wb)


def test_brief_without_prior_close_skips_the_explain(wb):
    from ipw import Workbench

    today_only = Workbench(wb.securities, wb.swaps, wb.market, wb.model, wb.scenarios, wb.limits)
    text = build_brief(today_only)
    assert "Change since prior close" not in text and "## 9. Hedge book" in text
