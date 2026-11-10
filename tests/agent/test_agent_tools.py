"""Release 2, build step 1: the typed tools (docs/AGENT_DESIGN.md, AD-3).

The evidence the build plan asks for: each tool returns the same figures as the
matching release 1 command, and the schema rejects bad arguments. Each
convention of AD-3 (read-only, typed, self-describing, errors are data) has a
test of its own, and so has the ``aggregate`` helper.
"""

import hashlib
import json
import re
from types import SimpleNamespace

import pandas as pd
import pytest
from typer.testing import CliRunner

from ipw import Workbench
from ipw.classic import cli
from ipw.core.scenarios import Scenario
from ipw.core.workbench import GROUPINGS

tools = pytest.importorskip("ipw.agent.tools", reason='needs the agent extra: pip install -e ".[agent]"')
Toolbox = tools.Toolbox

# Tool, its arguments, and the release 1 command that answers the same question.
SAME_AS_COMMAND = [
    ("portfolio_summary", {}, ["summary"]),
    ("portfolio_summary", {"by": "designation"}, ["summary", "--by", "designation"]),
    ("risk_report", {"by": "coupon"}, ["risk", "--by", "coupon"]),
    ("key_rate_report", {}, ["krd"]),
    ("key_rate_report", {"by": "bucket", "unit": "k"}, ["krd", "--by", "bucket", "--unit", "k"]),
    (
        "top_positions",
        {"metric": "unrealized_mm", "count": 3, "direction": "smallest"},
        ["top", "--metric", "unrealized_mm", "-n", "3", "--asc"],
    ),
    ("position_detail", {"position_id": "FN30-2.5-001"}, ["position", "FN30-2.5-001"]),
    ("run_scenarios", {}, ["scenario"]),
    (
        "run_scenarios",
        {"scenarios": ["up_100"], "shocks_bp": [-75]},
        ["scenario", "-n", "up_100", "-s", "-75"],
    ),
    ("scenario_breakdown", {"shock_bp": 200}, ["scenario", "-s", "200", "--by", "bucket"]),
    (
        "scenario_breakdown",
        {"scenario": "up_200", "by": "designation"},
        ["scenario", "-n", "up_200", "--by", "designation"],
    ),
    ("income_report", {}, ["nii"]),
    ("income_report", {"scenarios": ["base", "up_200"]}, ["nii", "-s", "base", "-s", "up_200"]),
    ("prepayment_outlook", {}, ["prepay"]),
    ("prepayment_outlook", {"by": "agency"}, ["prepay", "--by", "agency"]),
    ("explain_change", {}, ["explain"]),
    ("limit_status", {}, ["limits"]),
    ("limit_remedy", {"limit": "AOCI_UP200"}, ["fix", "AOCI_UP200"]),
    (
        "limit_remedy",
        {"limit": "DUR_BAND", "tenors": [5], "target": 5.0},
        ["fix", "DUR_BAND", "--tenors", "5", "--target", "5.0"],
    ),
    ("size_hedge", {"target_duration": 4.5}, ["hedge", "-t", "4.5"]),
    (
        "size_hedge",
        {"target_duration": 4.5, "mode": "krd", "tenors": [2, 5, 10]},
        ["hedge", "-t", "4.5", "--mode", "krd", "--tenors", "2,5,10"],
    ),
    (
        "what_if",
        {
            "drop": ["FN30-2.5-001"],
            "swaps": [{"direction": "PAY_FIXED", "tenor_years": 5, "notional_mm": 250}],
        },
        ["whatif", "--drop", "FN30-2.5-001", "--pay-fixed", "5:250"],
    ),
    (
        "what_if",
        {"swaps": [{"direction": "RECEIVE_FIXED", "tenor_years": 10, "notional_mm": 100}]},
        ["whatif", "--receive-fixed", "10:100"],
    ),
]


def call_id(case) -> str:
    return f"{case[0]} {json.dumps(case[1])}"


def printed_tables(output: str) -> list[dict]:
    """The JSON documents a release 1 command printed, one per table."""
    decoder, position, documents = json.JSONDecoder(), 0, []
    while position < len(output):
        if output[position].isspace():
            position += 1
            continue
        document, position = decoder.raw_decode(output, position)
        documents.append(document)
    return documents


def same(ours, printed) -> bool:
    """Equal, allowing for the ten decimals the command's JSON output keeps."""
    if isinstance(printed, (int, float)) and not isinstance(printed, bool) and ours is not None:
        return ours == pytest.approx(printed, rel=1e-9, abs=1e-8)
    return ours == printed


def cell_ref(result, row, column, table=None) -> dict:
    ref = {"result": result.id, "row": row, "column": column}
    return ref | {"table": table} if table else ref


# --------------------------------------------------------------------------- same figures as release 1


@pytest.mark.parametrize(("tool", "arguments", "command"), SAME_AS_COMMAND, ids=map(call_id, SAME_AS_COMMAND))
def test_tool_returns_the_figures_of_the_release_1_command(wb, root, tool, arguments, command):
    """Every cell the command prints is in the tool result, in the same row and column."""
    printed = CliRunner().invoke(cli.app, ["--root", str(root), "--format", "json", *command])
    assert printed.exit_code == 0, printed.output
    documents = printed_tables(printed.output)

    result = Toolbox(wb).call(tool, arguments)
    assert result.ok, result.error
    assert documents and len(result.tables) >= len(documents)

    figures = 0
    for document, table in zip(documents, result.tables):
        assert len(table.rows) == len(document["rows"]), table.name
        for record, (label, row) in zip(document["rows"], table.rows.items()):
            (_, printed_label), *cells = record.items()
            assert label == tools._label(printed_label)
            for column, value in cells:
                assert same(row[column], value), f"{table.name}, {label}, {column}"
                figures += isinstance(value, (int, float))
    assert figures


def test_the_tools_are_the_ones_the_design_lists(wb, root):
    """Names and order of the table in AD-3; the three tools that size a trade are marked as proposals."""
    design = (root / "docs" / "AGENT_DESIGN.md").read_text(encoding="utf-8")
    section = design.split("\n### AD-3.")[1].split("\n### AD-4.")[0]
    specs = Toolbox(wb).specs
    assert [spec.name for spec in specs] == re.findall(r"^\| `(\w+)` \|", section, flags=re.M)
    assert {spec.name for spec in specs if spec.proposal} == {"limit_remedy", "size_hedge", "what_if"}


def test_the_model_reads_figures_rounded_as_release_1_prints_them(wb):
    toolbox = Toolbox(wb)
    limits = toolbox.call("limit_status").to_text()
    assert "AOCI_UP200" in limits and "-225.99" in limits and "BREACH" in limits and "IPS 4.3" in limits
    scenario = toolbox.call("run_scenarios", {"scenarios": ["up_200"]}).to_text()
    assert "d_aoci_mm [USD millions]" in scenario and "-226.0" in scenario
    key_rates = toolbox.call("key_rate_report").to_text()
    assert "every figure in years" in key_rates and "5.30" in key_rates
    measures = toolbox.call("position_detail", {"position_id": "FN30-2.5-001"}).to_text()
    assert "orig_year | 2020 | year" in measures and "price | 79.19 | per 100 of face" in measures


# --------------------------------------------------------------------------- typed


class ConfigurationOnly:
    """Stands in for the workbench: it holds the configuration, and any use of the engine fails the test."""

    def __init__(self, wb: Workbench):
        self.scenarios, self.limits, self.model, self.market = wb.scenarios, wb.limits, wb.model, wb.market

    def __getattr__(self, name):
        raise AssertionError(f"the engine was reached: {name}")


CELL = {"result": "r1", "row": "Net", "column": "dv01_k"}
SWAP = {"direction": "PAY_FIXED", "tenor_years": 5, "notional_mm": 100}
BAD_ARGUMENTS = [
    ("portfolio_summary", {"by": "sector"}, "by: Input should be 'bucket', 'asset_type'"),
    ("portfolio_summary", {"group": "bucket"}, "group:"),
    ("key_rate_report", {"unit": "bp"}, "unit: Input should be 'years' or 'k'"),
    ("top_positions", {"metric": "_pv"}, "metric:"),
    ("top_positions", {"count": 0}, "count:"),
    ("position_detail", {}, "position_id:"),
    ("run_scenarios", {"scenarios": ["up_300"]}, "scenarios.0: Input should be 'base', 'dn_200'"),
    ("run_scenarios", {"shocks_bp": [5000]}, "shocks_bp.0:"),
    ("scenario_breakdown", {}, "give either scenario or shock_bp"),
    ("scenario_breakdown", {"scenario": "up_200", "shock_bp": 200}, "give either scenario or shock_bp"),
    ("prepayment_outlook", {"shocks_bp": "all"}, "shocks_bp:"),
    ("explain_change", {"positions": 500}, "positions:"),
    ("limit_remedy", {"limit": "AOCI_UP300"}, "limit: Input should be 'DUR_BAND'"),
    ("limit_remedy", {"limit": "AOCI_UP200", "tenors": [40]}, "tenors.0:"),
    ("limit_remedy", {"limit": "AOCI_UP200", "tenors": [5, 5]}, "give each tenor once"),
    ("size_hedge", {}, "target_duration:"),
    ("size_hedge", {"target_duration": "shorter"}, "target_duration:"),
    ("size_hedge", {"target_duration": 4.5, "mode": "dv01"}, "mode: Input should be 'duration' or 'krd'"),
    ("what_if", {}, "give at least one position to drop or one swap to add"),
    ("what_if", {"swaps": [SWAP | {"direction": "PAY"}]}, "swaps.0.direction:"),
    ("what_if", {"swaps": [SWAP | {"notional_mm": -100}]}, "swaps.0.notional_mm:"),
    ("aggregate", {"operation": "product", "cells": [CELL, CELL]}, "operation:"),
    ("aggregate", {"operation": "sum", "cells": [CELL]}, "cells:"),
    (
        "aggregate",
        {"operation": "difference", "cells": [CELL, CELL, CELL]},
        "a difference takes exactly two cells",
    ),
    (
        "aggregate",
        {"operation": "sum", "cells": [CELL, CELL], "as_percent": True},
        "as_percent applies to a ratio",
    ),
    ("no_such_tool", {}, "unknown tool 'no_such_tool'; tools: portfolio_summary"),
]


@pytest.mark.parametrize(("tool", "arguments", "message"), BAD_ARGUMENTS, ids=map(call_id, BAD_ARGUMENTS))
def test_a_bad_argument_is_rejected_before_the_engine_runs(wb, tool, arguments, message):
    result = Toolbox(ConfigurationOnly(wb)).call(tool, arguments)
    assert not result.ok and result.tables == ()
    assert message in result.error and "\n" not in result.error
    assert result.id == "r1" and result.tool == tool and result.arguments == arguments


def test_allowed_values_come_from_the_configuration(wb):
    toolbox = Toolbox(wb)

    def arguments(tool: str) -> dict:
        return toolbox.spec(tool).parameters["properties"]

    assert arguments("portfolio_summary")["by"]["enum"] == list(GROUPINGS)
    assert arguments("run_scenarios")["scenarios"]["items"]["enum"] == ["base", *wb.scenarios]
    assert arguments("scenario_breakdown")["scenario"]["enum"] == ["base", *wb.scenarios]
    assert arguments("limit_remedy")["limit"]["enum"] == [limit.id for limit in wb.limits]
    positions = wb.positions
    rankable = [c for c in positions if not c.startswith("_") and pd.api.types.is_numeric_dtype(positions[c])]
    assert sorted(arguments("top_positions")["metric"]["enum"]) == sorted(rankable)


def test_another_configuration_gives_another_schema(wb):
    other = SimpleNamespace(
        scenarios={"house_view": Scenario(name="house_view")},
        limits=wb.limits[:2],
        model=wb.model,
        market=wb.market,
    )
    toolbox = Toolbox(other)
    assert toolbox.spec("income_report").parameters["properties"]["scenarios"]["items"]["enum"] == [
        "base",
        "house_view",
    ]
    assert toolbox.spec("limit_remedy").parameters["properties"]["limit"]["enum"] == [
        "DUR_BAND",
        "DUR_DRIFT_DN100",
    ]
    rejected = toolbox.call("run_scenarios", {"scenarios": ["up_200"]})
    assert rejected.error == "invalid arguments: scenarios.0: Input should be 'base' or 'house_view'"


def test_schemas_are_flat_and_every_argument_is_described(wb):
    """Nothing a small model has to resolve: no references, no null alternatives, no titles."""
    for spec in Toolbox(wb).specs:
        schema = spec.parameters
        assert spec.description and schema["type"] == "object" and schema["additionalProperties"] is False
        text = json.dumps(schema)
        for keyword in ('"$ref"', '"$defs"', '"anyOf"', '"title"', '"null"'):
            assert keyword not in text, f"{spec.name}: {keyword}"
        undescribed = [
            name for name, argument in schema["properties"].items() if not argument.get("description")
        ]
        assert not undescribed, f"{spec.name}: {undescribed}"


# --------------------------------------------------------------------------- self-describing


def test_results_describe_themselves(wb):
    """Id, market date, tool, checked arguments, and a unit for every column of every table."""
    toolbox = Toolbox(wb)
    for number, (tool, arguments, _) in enumerate(SAME_AS_COMMAND, start=1):
        result = toolbox.call(tool, arguments)
        assert (result.id, result.tool, result.as_of) == (f"r{number}", tool, wb.market.as_of.isoformat())
        assert all(result.arguments[name] == value for name, value in arguments.items())
        assert result.tables and len({table.name for table in result.tables}) == len(result.tables)
        for table in result.tables:
            assert table.title and table.index and table.rows, table.name
            assert all(isinstance(unit, str) and unit for unit in table.units.values()), table.name
            assert all(list(row) == table.columns for row in table.rows.values()), table.name
        assert json.loads(json.dumps(result.to_dict(), allow_nan=False))["id"] == result.id
        assert result.to_text().startswith(f"result r{number}: {tool} ")
    assert toolbox.results[0].arguments == {"by": "bucket"}  # defaults are written out
    assert [result.id for result in toolbox.results] == [f"r{n}" for n in range(1, len(SAME_AS_COMMAND) + 1)]


def test_units_follow_the_column_and_where_they_differ_the_row(wb):
    toolbox = Toolbox(wb)
    scenarios = toolbox.call("run_scenarios", {"scenarios": ["up_200"]}).table()
    assert scenarios.units == {
        "description": "text",
        "d_value_mm": "USD millions",
        "d_value_pct": "%",
        "d_afs_mm": "USD millions",
        "d_htm_mm": "USD millions",
        "d_hedges_mm": "USD millions",
        "d_aoci_mm": "USD millions",
        "nii_mm": "USD millions",
        "d_nii_mm": "USD millions",
        "net_duration": "years",
    }
    limits = toolbox.call("limit_status").table()
    assert limits.unit("DUR_BAND", "value") == "years" and limits.unit("AOCI_UP200", "min") == "USD millions"
    assert limits.unit("EVE_UP200", "value") == "%" and limits.unit("CONVEXITY", "value") == "number"
    assert set(toolbox.call("key_rate_report", {"unit": "k"}).table().units.values()) == {
        "USD thousands per bp"
    }
    options = toolbox.call("limit_remedy", {"limit": "AOCI_UP200", "tenors": [5]}).table()
    assert options.units["after"] == "USD millions" and options.units["net_duration"] == "years"
    comparison = toolbox.call("what_if", {"drop": ["FN30-2.5-001"]}).table("comparison")
    assert comparison.unit("Net duration (years)", "change") == "years"
    assert comparison.unit("Net DV01 ($k per bp)", "after") == "USD thousands per bp"


# --------------------------------------------------------------------------- errors are data

ENGINE_REFUSALS = [
    ("position_detail", {"position_id": "NOPE"}, "unknown position_id 'NOPE'"),
    ("limit_remedy", {"limit": "NII_UP100"}, "limit NII_UP100 is not breached"),
    ("limit_remedy", {"limit": "HTM_SHARE", "target": 50}, "limit HTM_SHARE does not respond to swaps"),
    ("size_hedge", {"target_duration": 4.5, "tenors": [2, 5]}, "duration mode takes exactly one swap tenor"),
    ("what_if", {"drop": ["NOPE"]}, "unknown position_id(s): ['NOPE']"),
]


@pytest.mark.parametrize(("tool", "arguments", "message"), ENGINE_REFUSALS, ids=map(call_id, ENGINE_REFUSALS))
def test_an_engine_error_comes_back_as_a_one_line_result(wb, tool, arguments, message):
    toolbox = Toolbox(wb)
    result = toolbox.call(tool, arguments)
    assert not result.ok and result.tables == ()
    assert message in result.error and "\n" not in result.error and "Traceback" not in result.to_text()
    assert toolbox.call("limit_status").ok  # the run goes on


def test_explaining_without_a_prior_close_is_an_error_result(wb):
    no_prior = Workbench(wb.securities, wb.swaps, wb.market, wb.model, wb.scenarios, wb.limits)
    result = Toolbox(no_prior).call("explain_change")
    assert not result.ok and "no prior close found" in result.error


# --------------------------------------------------------------------------- read-only


def test_tools_leave_the_book_and_the_files_alone(wb, root, tmp_path, monkeypatch):
    def fingerprints() -> dict:
        files = [path for folder in ("config", "data") for path in sorted((root / folder).rglob("*"))]
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files if path.is_file()}

    monkeypatch.chdir(tmp_path)
    securities, swaps, files = wb.securities.copy(), wb.swaps.copy(), fingerprints()
    limits_before = wb.limit_table()

    toolbox = Toolbox(wb)
    for tool, arguments, _ in SAME_AS_COMMAND:
        assert toolbox.call(tool, arguments).ok

    pd.testing.assert_frame_equal(wb.securities, securities)
    pd.testing.assert_frame_equal(wb.swaps, swaps)
    pd.testing.assert_frame_equal(wb.limit_table(), limits_before)
    assert fingerprints() == files
    assert not list(tmp_path.iterdir())


# --------------------------------------------------------------------------- aggregate


def test_aggregate_adds_subtracts_and_takes_shares_of_earlier_cells(wb):
    toolbox = Toolbox(wb)
    by_book = toolbox.call("scenario_breakdown", {"scenario": "up_200", "by": "designation"})
    table = by_book.table()

    cells = [cell_ref(by_book, "AFS", "d_value_mm"), cell_ref(by_book, "HTM", "d_value_mm")]
    total = toolbox.call("aggregate", {"operation": "sum", "cells": cells, "label": "AFS and HTM"})
    assert total.table().rows == {"AFS and HTM": {"value": pytest.approx(table.rows["Total"]["d_value_mm"])}}
    assert total.table().units == {"value": "USD millions"}

    gap = toolbox.call("aggregate", {"operation": "difference", "cells": cells}).table()
    assert gap.rows["difference of 2 cells"]["value"] == pytest.approx(
        table.rows["AFS"]["d_value_mm"] - table.rows["HTM"]["d_value_mm"]
    )

    share = [cell_ref(by_book, "AFS", "d_value_mm"), cell_ref(by_book, "Total", "d_value_mm")]
    as_percent = toolbox.call("aggregate", {"operation": "ratio", "cells": share, "as_percent": True}).table()
    assert as_percent.units == {"value": "%"}
    assert as_percent.rows["ratio of 2 cells"]["value"] == pytest.approx(table.rows["AFS"]["share_pct"])
    plain = toolbox.call("aggregate", {"operation": "ratio", "cells": share}).table()
    assert plain.units == {"value": "ratio"}
    assert plain.rows["ratio of 2 cells"]["value"] == pytest.approx(table.rows["AFS"]["share_pct"] / 100.0)


def test_aggregate_works_across_results_and_on_its_own_results(wb):
    toolbox = Toolbox(wb)
    limits = toolbox.call("limit_status")
    scenario = toolbox.call("run_scenarios", {"scenarios": ["up_200"]})
    cells = [cell_ref(limits, "AOCI_UP200", "value"), cell_ref(scenario, "up_200", "d_aoci_mm")]
    same_figure = toolbox.call("aggregate", {"operation": "difference", "cells": cells, "label": "check"})
    assert same_figure.table().rows["check"]["value"] == pytest.approx(0.0, abs=1e-9)

    breach = [cell_ref(limits, "AOCI_UP200", "value"), cell_ref(limits, "AOCI_UP200", "min")]
    excess = toolbox.call("aggregate", {"operation": "difference", "cells": breach, "label": "excess"})
    doubled = [cell_ref(excess, "excess", "value"), cell_ref(excess, "excess", "value")]
    twice = toolbox.call("aggregate", {"operation": "sum", "cells": doubled}).table()
    assert twice.rows["sum of 2 cells"]["value"] == pytest.approx(2 * (-225.991168 + 210.0), abs=1e-5)

    per_bp = [cell_ref(limits, "AOCI_UP200", "value"), cell_ref(limits, "DUR_BAND", "value")]
    assert toolbox.call("aggregate", {"operation": "ratio", "cells": per_bp}).table().units == {
        "value": "USD millions per years"
    }


def test_aggregate_refuses_what_it_cannot_do_honestly(wb):
    toolbox = Toolbox(wb)
    risk = toolbox.call("risk_report", {"by": "designation"})
    position = toolbox.call("position_detail", {"position_id": "FN30-2.5-001"})
    failed = toolbox.call("position_detail", {"position_id": "NOPE"})
    net_dv01, net_duration = cell_ref(risk, "Net", "dv01_k"), cell_ref(risk, "Net", "eff_duration")

    def refusal(operation: str, cells: list, **more) -> str:
        result = toolbox.call("aggregate", {"operation": operation, "cells": cells, **more})
        assert not result.ok and "\n" not in result.error
        return result.error

    assert refusal("sum", [net_dv01, net_duration]) == (
        "cannot take a sum across units: USD thousands per bp, years"
    )
    assert "a percentage needs two cells in one unit" in refusal(
        "ratio", [net_dv01, net_duration], as_percent=True
    )
    assert "no result 'r9' in this run; results: r1, r2, r3" in refusal(
        "sum", [net_dv01, CELL | {"result": "r9"}]
    )
    assert "has no row 'Gross'; rows: AFS, HTM, Securities, Hedges, Net" in refusal(
        "sum", [net_dv01, cell_ref(risk, "Gross", "dv01_k")]
    )
    assert "has no column 'dv01'; columns: market_value_mm" in refusal(
        "sum", [net_dv01, cell_ref(risk, "Net", "dv01")]
    )
    assert "is not a number" in refusal("sum", [net_dv01, cell_ref(risk, "Hedges", "wal_years")])
    assert "has tables measures, cash_flows; name the one you mean" in refusal(
        "sum", [net_dv01, cell_ref(position, "dv01_k", "value")]
    )
    assert "has no table 'flows'; tables: measures, cash_flows" in refusal(
        "sum", [net_dv01, cell_ref(position, "dv01_k", "value", table="flows")]
    )
    assert f"result {failed.id} is an error and has no cells" in refusal(
        "sum", [net_dv01, cell_ref(failed, "dv01_k", "value")]
    )
    flat = toolbox.call("scenario_breakdown", {"scenario": "base"})
    zero = cell_ref(flat, "Total", "d_value_mm")
    assert refusal("ratio", [net_dv01, zero]) == "ratio: the second cell is zero"

    in_named_table = cell_ref(position, "dv01_k", "value", table="measures")
    assert toolbox.call("aggregate", {"operation": "difference", "cells": [net_dv01, in_named_table]}).ok
