"""The assistant's tools: typed, read-only functions over the release 1 workbench.

Each tool is defined once, in this module. The assistant calls the tools in its
own process through ``Toolbox.call``; ``ipw.agent.mcp_server`` serves the same
definitions to any other MCP client.

Conventions (docs/AGENT_DESIGN.md, AD-3):

* Read-only. A tool calculates and returns. None writes a file or changes the book.
* Typed. Allowed values (groupings, scenario names, limit ids, position measures)
  are read from the loaded configuration, so a wrong argument is rejected before
  the engine runs.
* Self-describing. A result carries its id, the market date, the tool and its
  arguments, and tables in which every column has a unit.
* Errors are data. A rejected argument or an engine error comes back as a result
  holding a one-line message, never as an exception.

The language model never computes: arithmetic across results is the job of the
``aggregate`` tool.
"""

# No postponed evaluation of annotations in this module: pydantic reads the
# argument types, and several of them are built at run time from the configuration.

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cached_property
from typing import Annotated, Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ipw.classic.render import NII_LABELS, SPEC, cell
from ipw.core.hedging import par_swaps
from ipw.core.workbench import GROUPINGS, Workbench

USD_MM = "USD millions"
USD_K_BP = "USD thousands per bp"
PER_ROW = "see the unit column"  # the unit differs by row and is given in the table's own unit column
TEXT = "text"

# Errors the engine raises on purpose, each with a one-line message (as in ipw.classic.cli.main).
ENGINE_ERRORS = (KeyError, ValueError, FileNotFoundError)

# Position columns a ranking can use; the key-rate columns are added from the configured key tenors.
POSITION_MEASURES = (
    "current_face_mm", "book_value_mm", "market_value_mm", "unrealized_mm", "price", "book_price",
    "coupon", "wac", "orig_year", "yield_pct", "book_yield_pct", "zv_spread_bp", "wal_years",
    "cpr_1y_pct", "eff_duration", "eff_convexity", "dv01_k",
)  # fmt: skip

_UNITS = {
    "positions": "count",
    "breaches_after": "count",
    "coupon": "%",
    "wac": "%",
    "fixed_rate": "%",
    "price": "per 100 of face",
    "book_price": "per 100 of face",
    "eff_duration": "years",
    "net_duration": "years",
    "wal_years": "years",
    "remaining_years": "years",
    "orig_year": "year",
    "eff_convexity": "convexity (divided by 100)",
}
_UNIT_ALIASES = {"$mm": USD_MM, "$k per bp": USD_K_BP, "": "number"}

_SUMMARY_COLUMNS = ["positions", "current_face_mm", "book_value_mm", "market_value_mm", "unrealized_mm",
                    "book_price", "price", "coupon", "book_yield_pct", "yield_pct"]  # fmt: skip
_SCENARIO_COLUMNS = ["description", "d_value_mm", "d_value_pct", "d_afs_mm", "d_htm_mm", "d_hedges_mm",
                     "d_aoci_mm", "nii_mm", "d_nii_mm", "net_duration"]  # fmt: skip
_LIMIT_COLUMNS = ["name", "value", "min", "max", "unit", "utilisation_pct", "status", "policy_ref"]
_LIMIT_UNITS = {"value": PER_ROW, "min": PER_ROW, "max": PER_ROW, "headroom": PER_ROW}
_TRADE_COLUMNS = ["direction", "notional_mm", "fixed_rate", "remaining_years"]


def column_unit(column: str) -> str:
    """Unit of a numeric column, from the engine's naming convention."""
    if column in _UNITS:
        return _UNITS[column]
    if column.endswith("_mm"):
        return USD_MM
    if column.endswith("_pct") or column.startswith("cpr_"):
        return "%"
    if column.endswith("_bp"):
        return "bp"
    if column.endswith("_k"):
        return USD_K_BP
    return "number"


# ====================================================================== results
@dataclass(frozen=True)
class Table:
    """One table of a result. A cell is addressed by its row label and its column."""

    name: str  # key of the table inside its result
    title: str
    index: str  # what the row labels are, for example "bucket" or "scenario"
    units: dict[str, str]  # column -> unit, for every column
    rows: dict[str, dict[str, Any]]  # row label -> column -> number, text or None
    default_format: str = "{:,.2f}"

    @property
    def columns(self) -> list[str]:
        return list(self.units)

    def unit(self, row: str, column: str) -> str:
        """Unit of one cell, resolved through the unit column where units differ by row."""
        unit = self.units[column]
        if unit == PER_ROW:
            unit = str(self.rows[row].get("unit") or "")
        return _UNIT_ALIASES.get(unit, unit)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "index": self.index,
            "units": dict(self.units),
            "rows": {label: dict(row) for label, row in self.rows.items()},
        }

    def to_text(self) -> str:
        """The table as the language model reads it: figures rounded as release 1 shows them."""
        lines = [f"table {self.name}: {self.title}"]
        units = set(self.units.values())
        if len(units) == 1 and len(self.units) > 1 and not units & {TEXT, PER_ROW}:
            lines.append(f"every figure in {units.pop()}")  # a shared unit is said once, not in every header
            shown = list(self.units)
        else:
            shown = [c if u in (TEXT, PER_ROW) else f"{c} [{u}]" for c, u in self.units.items()]
        lines.append(" | ".join([self.index, *shown]))
        for label in self.rows:
            lines.append(" | ".join([label, *(self.shown(label, column) for column in self.units)]))
        return "\n".join(lines)

    def shown(self, row: str, column: str) -> str:
        """One cell as the language model reads it."""
        # where the unit differs by row, a row named after an engine column is formatted as that column
        key = row if self.units[column] == PER_ROW and row in SPEC else column
        return cell(key, self.rows[row][column], self.default_format)


@dataclass(frozen=True)
class ToolResult:
    """What one tool call returned: tables, or an error message."""

    id: str  # "r1", "r2", ... in the order of the calls of one run
    tool: str
    arguments: dict[str, Any]
    as_of: str  # market date
    tables: tuple[Table, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def table(self, name: str | None = None) -> Table:
        names = [table.name for table in self.tables]
        if name is None:
            if len(self.tables) != 1:
                raise KeyError(f"result {self.id} has tables {', '.join(names)}; name the one you mean")
            return self.tables[0]
        if name not in names:
            raise KeyError(f"result {self.id} has no table {name!r}; tables: {', '.join(names)}")
        return self.tables[names.index(name)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "arguments": self.arguments,
            "as_of": self.as_of,
            "tables": [table.to_dict() for table in self.tables],
            "error": self.error,
        }

    def digest(self) -> str:
        """A short hash of what the call returned, for the run log. Figures are rounded so machines agree."""
        tables = [
            (table.name, [(label, [(c, round(v, 8) if isinstance(v, float) else v) for c, v in row.items()])
                          for label, row in table.rows.items()])
            for table in self.tables
        ]  # fmt: skip
        content = json.dumps([self.tool, self.arguments, tables, self.error], sort_keys=True)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def to_text(self) -> str:
        head = f"result {self.id}: {self.tool} {json.dumps(self.arguments)}, market date {self.as_of}"
        if self.error is not None:
            return f"{head}\nerror: {self.error}"
        return "\n\n".join([head, *(table.to_text() for table in self.tables)])


# ====================================================================== definitions
class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


@dataclass(frozen=True)
class ToolSpec:
    """One tool: its name, what the model is told about it, its argument type and its function."""

    name: str
    description: str
    args: type[BaseModel]
    run: Callable[["Toolbox", Any], list[Table]]
    proposal: bool = False  # the result is a sized trade or a changed book: indicative, never a decision

    @cached_property
    def parameters(self) -> dict[str, Any]:
        """JSON schema of the arguments, as given to the model and to MCP clients."""
        return _json_schema(self.args)

    def as_function(self) -> dict[str, Any]:
        """The definition as a chat model takes a tool: a function with a name, a description, parameters."""
        function = {"name": self.name, "description": self.description, "parameters": self.parameters}
        return {"type": "function", "function": function}


class Toolbox:
    """The tools bound to one workbench, and the results of one run.

    A run is one question to the assistant, or one session of the MCP server.
    Results are numbered in call order so that ``aggregate``, the check and the
    run log can refer to them.
    """

    def __init__(self, wb: Workbench):
        self.wb = wb
        self.as_of = wb.market.as_of.isoformat()
        self.specs: tuple[ToolSpec, ...] = build_specs(wb)
        self.results: list[ToolResult] = []
        self._by_name = {spec.name: spec for spec in self.specs}

    def spec(self, name: str) -> ToolSpec:
        return self._by_name[name]

    def call(self, name: str, arguments: Mapping[str, Any] | None = None) -> ToolResult:
        """Check the arguments, run the tool and record the result. A bad call is a result too."""
        raw = dict(arguments or {})
        spec = self._by_name.get(name)
        if spec is None:
            return self._record(name, raw, error=f"unknown tool {name!r}; tools: {', '.join(self._by_name)}")
        try:
            args = spec.args.model_validate(raw)
        except ValidationError as err:
            return self._record(name, raw, error=f"invalid arguments: {_validation_message(err)}")
        checked = args.model_dump(mode="json", exclude_none=True)
        try:
            tables = spec.run(self, args)
        except ENGINE_ERRORS as err:
            return self._record(name, checked, error=str(err.args[0]) if err.args else str(err))
        return self._record(name, checked, tables=tuple(tables))

    def cell(self, result: str, row: str, column: str, table: str | None = None) -> tuple[float, str]:
        """Value and unit of one numeric cell of an earlier result of this run."""
        found = next((r for r in self.results if r.id == result), None)
        if found is None:
            known = ", ".join(r.id for r in self.results) or "none yet"
            raise KeyError(f"no result {result!r} in this run; results: {known}")
        if not found.ok:
            raise ValueError(f"result {result} is an error and has no cells")
        source = found.table(table)
        if row not in source.rows:
            raise KeyError(f"result {result} has no row {row!r}; rows: {_listing(source.rows)}")
        if column not in source.units:
            raise KeyError(f"result {result} has no column {column!r}; columns: {_listing(source.units)}")
        value = source.rows[row][column]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"cell {row!r}, {column!r} of result {result} is not a number")
        return float(value), source.unit(row, column)

    def _record(
        self, tool: str, arguments: dict[str, Any], tables=(), error: str | None = None
    ) -> ToolResult:
        result = ToolResult(f"r{len(self.results) + 1}", tool, arguments, self.as_of, tables, error)
        self.results.append(result)
        return result


# ====================================================================== helpers
def _listing(names, most: int = 12) -> str:
    names = list(names)
    return ", ".join(names[:most]) + (f", and {len(names) - most} more" if len(names) > most else "")


def _validation_message(err: ValidationError) -> str:
    parts = []
    for item in err.errors(include_url=False):
        where = ".".join(str(step) for step in item["loc"])
        message = item["msg"].removeprefix("Value error, ")
        parts.append(f"{where}: {message}" if where else message)
    return "; ".join(parts)


def _json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The schema pydantic derives, flattened for a small model: no references, null options or titles."""
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def tidy(node: Any) -> Any:
        if isinstance(node, list):
            return [tidy(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            node = {**definitions[node.pop("$ref").rsplit("/", 1)[-1]], **node}
        if "anyOf" in node:
            options = [option for option in node["anyOf"] if option != {"type": "null"}]
            node = {**node, "anyOf": options}
            if len(options) == 1:
                node.pop("anyOf")
                node = {**options[0], **node}
        out = {}
        for key, value in node.items():
            if key == "title" or (key == "default" and value is None):
                continue
            # the keys of "properties" are argument names, not schema keywords
            out[key] = {k: tidy(v) for k, v in value.items()} if key == "properties" else tidy(value)
        return out

    return tidy(schema)


def _plain(value: Any) -> Any:
    """A cell as a JSON value: text, a finite number, or None."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    return None if pd.isna(value) else str(value)


def _label(value: Any) -> str:
    return f"{value:g}" if isinstance(value, (float, np.floating)) else str(value)


def _table(
    name: str,
    title: str,
    frame: pd.DataFrame,
    *,
    columns: list[str] | None = None,
    index: str | None = None,
    default: str = "{:,.2f}",
    units: Mapping[str, str] | None = None,
) -> Table:
    """A workbench table as a result table: plain values, and a unit for every column."""
    shown = frame[columns] if columns is not None else frame
    names = [str(column) for column in shown.columns]
    rows: dict[str, dict[str, Any]] = {}
    for label, values in zip(shown.index, shown.itertuples(index=False, name=None)):
        key = _label(label)
        while key in rows:  # labels address cells, so they must differ
            key += " (again)"
        rows[key] = {column: _plain(value) for column, value in zip(names, values)}
    resolved = {}
    for column in names:
        if units and column in units:
            resolved[column] = units[column]
        elif any(isinstance(row[column], str) for row in rows.values()):
            resolved[column] = TEXT
        else:
            resolved[column] = column_unit(column)
    return Table(name, title, index or str(shown.index.name or "row"), resolved, rows, default)


def _one_unit(frame: pd.DataFrame, unit: str) -> dict[str, str]:
    return {str(column): unit for column in frame.columns}


def _label_unit(label: str) -> str:
    """Unit written in brackets at the end of a row label, for example "Net duration (years)"."""
    match = re.search(r"\(([^()]+)\)$", label)
    return match.group(1) if match else ""


def _different(values: list[float]) -> list[float]:
    if len(set(values)) != len(values):
        raise ValueError("give each tenor once")
    return values


# ====================================================================== the tools
def build_specs(wb: Workbench) -> tuple[ToolSpec, ...]:
    """The tool definitions for one workbench. Allowed values come from its configuration only."""
    limit_ids = tuple(limit.id for limit in wb.limits)
    rankable = (*POSITION_MEASURES, *(f"kr01_{tenor:g}y_k" for tenor in wb.model.risk.key_tenors))

    Grouping = Literal[GROUPINGS]
    ScenarioName = Literal[("base", *wb.scenarios)]
    LimitId = Literal[limit_ids] if limit_ids else str
    Measure = Literal[rankable]
    Shock = Annotated[float, Field(ge=-500, le=500)]
    Tenor = Annotated[float, Field(ge=1, le=30)]

    by_bucket = Field("bucket", description="How to group the rows.")
    names_help = "Configured scenario names."
    shocks_help = "Parallel shocks of the Treasury curve in bp, from -500 to 500."
    tenors_help = "Swap tenors in years, from 1 to 30."

    # ------------------------------------------------------------------ portfolio views
    class Summary(_Args):
        by: Grouping = by_bucket

    def summary(tb: Toolbox, a: Summary) -> list[Table]:
        title = f"Portfolio as of {tb.as_of} ($mm)"
        return [_table("summary", title, tb.wb.summary(a.by), columns=_SUMMARY_COLUMNS, index=a.by)]

    class Risk(_Args):
        by: Grouping = by_bucket

    def risk(tb: Toolbox, a: Risk) -> list[Table]:
        title = "Interest-rate risk (bump and revalue, prepayments re-projected)"
        return [_table("risk", title, tb.wb.risk_table(a.by), index=a.by)]

    class KeyRates(_Args):
        by: Grouping = Field("designation", description="How to group the rows.")
        unit: Literal["years", "k"] = Field(
            "years", description="years: contribution to duration. k: USD thousands per bp."
        )

    def key_rates(tb: Toolbox, a: KeyRates) -> list[Table]:
        years = a.unit == "years"
        frame = tb.wb.key_rate_table(a.by, a.unit)
        title = "Key-rate durations (years)" if years else "Key-rate DV01 ($k per bp)"
        units = _one_unit(frame, "years" if years else USD_K_BP)
        default = "{:.2f}" if years else "{:,.0f}"
        return [_table("key_rates", title, frame, index=a.by, default=default, units=units)]

    class Top(_Args):
        metric: Measure = Field("dv01_k", description="The position measure to rank by.")
        count: int = Field(10, ge=1, le=25, description="Number of positions.")
        direction: Literal["largest", "smallest"] = Field(
            "largest", description="smallest gives the most negative first, for example the largest losses."
        )

    def top(tb: Toolbox, a: Top) -> list[Table]:
        frame = tb.wb.top(a.metric, a.count, ascending=a.direction == "smallest")
        return [_table("top", f"Top {a.count} positions by {a.metric}", frame)]

    class Position(_Args):
        position_id: str = Field(description="A position id, for example FN30-2.5-001.")

    def position(tb: Toolbox, a: Position) -> list[Table]:
        details, flows = tb.wb.position(a.position_id)
        measures = details.to_frame("value")
        measures["unit"] = [TEXT if isinstance(v, str) else column_unit(str(m)) for m, v in details.items()]
        by_row = {"value": PER_ROW}
        return [
            _table("measures", f"Position {a.position_id}", measures, index="measure", units=by_row),
            _table("cash_flows", "Projected cash flows by year ($mm)", flows.head(15)),
        ]

    # ------------------------------------------------------------------ scenarios
    class Scenarios(_Args):
        scenarios: list[ScenarioName] = Field([], description=names_help)
        shocks_bp: list[Shock] = Field([], description=shocks_help)

    def chosen(tb: Toolbox, a: Scenarios) -> list:
        picked = [tb.wb.scenario(name) for name in a.scenarios] + [tb.wb.scenario(bp) for bp in a.shocks_bp]
        return list(dict.fromkeys(picked))  # a scenario asked for twice is run and shown once

    def scenarios(tb: Toolbox, a: Scenarios) -> list[Table]:
        title = "Scenarios: instantaneous shocks ($mm; AOCI after tax, net of hedges)"
        frame = tb.wb.scenario_table(chosen(tb, a) or None)
        return [_table("scenarios", title, frame, columns=_SCENARIO_COLUMNS, index="scenario")]

    class Breakdown(_Args):
        scenario: ScenarioName | None = Field(None, description="A configured scenario name.")
        shock_bp: Shock | None = Field(None, description="Or one parallel shock in bp, from -500 to 500.")
        by: Grouping = by_bucket

        @model_validator(mode="after")
        def _one_scenario(self):
            if (self.scenario is None) == (self.shock_bp is None):
                raise ValueError("give either scenario or shock_bp, one of the two")
            return self

    def breakdown(tb: Toolbox, a: Breakdown) -> list[Table]:
        scenario = tb.wb.scenario(a.scenario if a.scenario is not None else a.shock_bp)
        title = f"{scenario.description}: value change by {a.by} ($mm)"
        return [_table("breakdown", title, tb.wb.scenario_detail(scenario, a.by), index=a.by)]

    def income(tb: Toolbox, a: Scenarios) -> list[Table]:
        frame = tb.wb.nii_table(chosen(tb, a) or (-100, "base", 100)).rename(index=NII_LABELS)
        title = "Net interest income, next 12 months ($mm)"
        units = _one_unit(frame, USD_MM)
        return [_table("income", title, frame, index="component", default="{:,.1f}", units=units)]

    class Prepayment(_Args):
        shocks_bp: list[Shock] = Field([-100.0, 0.0, 100.0], description=shocks_help + " 0 is today.")
        by: Grouping = by_bucket

    def prepayment(tb: Toolbox, a: Prepayment) -> list[Table]:
        title = f"Prepayment outlook by {a.by} (CPR in %, projected 12 months)"
        frame = tb.wb.prepay_table(a.shocks_bp, a.by)
        return [_table("prepayment", title, frame, index=a.by, default="{:.1f}")]

    # ------------------------------------------------------------------ explain and limits
    class Explain(_Args):
        positions: int = Field(5, ge=1, le=20, description="Number of largest position moves to list.")

    def explain(tb: Toolbox, a: Explain) -> list[Table]:
        ex = tb.wb.explain()
        order = ex.by_position["total_mm"].abs().sort_values(ascending=False).index
        moves = ex.by_position.reindex(order).head(a.positions).set_index("position_id")
        by_tenor = ex.by_key_rate.set_index("tenor")
        rates = pd.DataFrame(
            {
                "move_bp": {
                    "30-year mortgage rate": ex.mortgage_rate_move_bp,
                    "Mortgage basis to the 10-year": ex.mortgage_basis_move_bp,
                }
            }
        )
        drivers = f"Change in value by driver, {ex.prior_as_of} to {ex.as_of} ($mm)"
        in_usd = _one_unit(ex.by_driver, USD_MM)
        return [
            _table("drivers", drivers, ex.by_driver, index="driver", default="{:+,.2f}", units=in_usd),
            _table("key_rates", "Curve move and first-order P&L by key rate", by_tenor),
            _table("positions", f"Largest {a.positions} position moves ($mm)", moves),
            _table("mortgage_rate", "Mortgage rate moves since the prior close (bp)", rates, index="rate"),
        ]

    class NoArguments(_Args):
        pass

    def limits(tb: Toolbox, a: NoArguments) -> list[Table]:
        title = "Policy limits (config/limits.yaml)"
        frame = tb.wb.limit_table()[_LIMIT_COLUMNS]
        # the engine's distance from each value to its nearest bound; the release 1 table does not show it
        frame.insert(4, "headroom", [result.headroom for result in tb.wb.limit_report()])
        return [_table("limits", title, frame, units=_LIMIT_UNITS)]

    # ------------------------------------------------------------------ proposals (indicative)
    class Remedy(_Args):
        limit: LimitId = Field(description="The limit to bring back inside.")
        tenors: list[Tenor] = Field([2.0, 5.0, 10.0], min_length=1, max_length=6, description=tenors_help)
        target: float | None = Field(
            None, description="Value of the limit metric to aim for. Leave out to aim for the breached bound."
        )

        @model_validator(mode="after")
        def _tenors_differ(self):
            _different(self.tenors)
            return self

    def remedy(tb: Toolbox, a: Remedy) -> list[Table]:
        rows, unit = {}, ""
        for tenor in a.tenors:
            fix = tb.wb.fix_limit(a.limit, tenor, a.target)
            trade = fix.trades.iloc[0]
            statuses = [r.status for r in fix.result.limit_report()]
            unit = fix.limit.unit
            rows[f"{trade['direction']} {tenor:g}Y"] = {
                "notional_mm": trade["notional_mm"],
                "fixed_rate": trade["fixed_rate"],
                "before": fix.before.value,
                "after": fix.after.value,
                "utilisation_pct": fix.after.utilisation * 100.0,
                "net_duration": fix.result.headline()["net_duration"],
                "d_nii_mm": fix.carry_12m_mm,
                "breaches_after": float(statuses.count("BREACH")),
            }
        aim = "its limit" if a.target is None else f"{a.target:g}"
        title = f"Swap options to bring {a.limit} to {aim} (indicative)"
        units = dict.fromkeys(("before", "after"), _UNIT_ALIASES.get(unit, unit))
        return [_table("options", title, pd.DataFrame(rows).T, index="option", units=units)]

    class Hedge(_Args):
        target_duration: float = Field(description="Net effective duration to reach, in years.")
        mode: Literal["duration", "krd"] = Field(
            "duration", description="duration: one swap tenor. krd: several tenors, keeps the curve shape."
        )
        tenors: list[Tenor] = Field([5.0], min_length=1, max_length=6, description=tenors_help)

        @model_validator(mode="after")
        def _tenors_differ(self):
            _different(self.tenors)
            return self

    def hedge(tb: Toolbox, a: Hedge) -> list[Table]:
        h = tb.wb.hedge(a.target_duration, a.mode, a.tenors)
        profile = pd.DataFrame({"before": h.kr01_before_k, "after": h.kr01_after_k}).T
        profile["Sum"] = profile.sum(axis=1)
        duration = pd.DataFrame(
            {
                "net_duration": {
                    "before": h.duration_before,
                    "after": h.duration_after,
                    "target": h.target_duration,
                }
            }
        )
        title = (
            f"Proposed trades ({a.mode} mode, indicative): net duration "
            f"{h.duration_before:.2f} -> {h.duration_after:.2f}"
        )
        in_k = _one_unit(profile, USD_K_BP)
        return [
            _table("trades", title, h.trades.set_index("swap_id"), columns=_TRADE_COLUMNS),
            _table(
                "key_rate_dv01",
                "Net key-rate DV01 ($k per bp)",
                profile,
                index="state",
                default="{:,.0f}",
                units=in_k,
            ),
            _table("duration", "Net effective duration (years)", duration, index="state"),
        ]

    class Swap(_Args):
        direction: Literal["PAY_FIXED", "RECEIVE_FIXED"] = Field(
            description="Paying fixed shortens duration."
        )
        tenor_years: Tenor = Field(description="Swap tenor in years, from 1 to 30.")
        notional_mm: float = Field(gt=0, description="Notional in USD millions.")

    class WhatIf(_Args):
        drop: list[str] = Field([], description="Position ids to sell.")
        swaps: list[Swap] = Field([], description="Par swaps to add.")

        @model_validator(mode="after")
        def _a_change(self):
            if not self.drop and not self.swaps:
                raise ValueError("give at least one position to drop or one swap to add")
            return self

    def what_if(tb: Toolbox, a: WhatIf) -> list[Table]:
        book = tb.wb
        legs = [
            par_swaps(book.engine, (leg.tenor_years,), leg.direction).assign(notional_mm=leg.notional_mm)
            for leg in a.swaps
        ]
        after = book.what_if(drop=a.drop, add_swaps=pd.concat(legs, ignore_index=True) if legs else None)
        comparison = book.compare(after)
        units = [_label_unit(str(label)) for label in comparison.index]
        comparison["unit"] = [_UNIT_ALIASES.get(unit, unit) for unit in units]
        title = "What-if: headline numbers and limit metrics (indicative)"
        by_row = dict.fromkeys(("before", "after", "change"), PER_ROW)
        columns = _LIMIT_COLUMNS[:-1]  # the policy reference is in limit_status
        return [
            _table("comparison", title, comparison, index="measure", units=by_row),
            _table(
                "limits_after",
                "Limits after the change",
                after.limit_table(),
                columns=columns,
                units=_LIMIT_UNITS,
            ),
        ]

    # ------------------------------------------------------------------ arithmetic
    class Cell(_Args):
        result: str = Field(description="Id of an earlier result, for example r2.")
        row: str = Field(description="Row label, exactly as in that result.")
        column: str = Field(description="Column name, exactly as in that result.")
        table: str | None = Field(
            None, description="Table name; needed only if the result has several tables."
        )

    class Aggregate(_Args):
        operation: Literal["sum", "difference", "ratio"] = Field(
            description="sum: all cells added. difference: first minus second. ratio: first over second."
        )
        cells: list[Cell] = Field(min_length=2, max_length=30, description="The cells, in order.")
        as_percent: bool = Field(False, description="For a ratio: multiply by 100, to state a share in %.")
        label: str = Field("", description="A short name for the figure.")

        @model_validator(mode="after")
        def _shape(self):
            if self.operation != "sum" and len(self.cells) != 2:
                raise ValueError(f"a {self.operation} takes exactly two cells")
            if self.as_percent and self.operation != "ratio":
                raise ValueError("as_percent applies to a ratio only")
            return self

    def aggregate(tb: Toolbox, a: Aggregate) -> list[Table]:
        picked = [tb.cell(c.result, c.row, c.column, c.table) for c in a.cells]
        values, units = [value for value, _ in picked], [unit for _, unit in picked]
        same = len(set(units)) == 1
        if a.operation == "ratio":
            if values[1] == 0:
                raise ValueError("ratio: the second cell is zero")
            if a.as_percent and not same:
                raise ValueError(f"a percentage needs two cells in one unit; got {units[0]} and {units[1]}")
            value = values[0] / values[1] * (100.0 if a.as_percent else 1.0)
            unit = "%" if a.as_percent else "ratio" if same else f"{units[0]} per {units[1]}"
        elif not same:
            raise ValueError(f"cannot take a {a.operation} across units: {', '.join(dict.fromkeys(units))}")
        else:
            value = math.fsum(values) if a.operation == "sum" else values[0] - values[1]
            unit = units[0]
        label = a.label.strip() or f"{a.operation} of {len(values)} cells"
        title = f"{a.operation.capitalize()} of {len(values)} cells"
        return [Table("aggregate", title, "figure", {"value": unit}, {label: {"value": value}})]

    return (
        ToolSpec(
            "portfolio_summary",
            "Composition and valuation of the securities by group, with a Total row: number of positions, "
            "face, book value, market value, unrealized gain or loss, prices, coupon and yields.",
            Summary,
            summary,
        ),
        ToolSpec(
            "risk_report",
            "Interest-rate risk by group, then rows for Securities, Hedges and Net: market value, WAL, "
            "projected CPR, spread, effective duration, convexity and DV01. The net duration of the book "
            "is eff_duration in the Net row.",
            Risk,
            risk,
        ),
        ToolSpec(
            "key_rate_report",
            "Key-rate profile on the Treasury par curve by group, then rows for Securities, Hedges and Net: "
            "where on the curve the exposure sits.",
            KeyRates,
            key_rates,
        ),
        ToolSpec(
            "top_positions",
            "The largest or smallest positions by one measure, for example dv01_k, unrealized_mm or "
            "eff_duration.",
            Top,
            top,
        ),
        ToolSpec(
            "position_detail",
            "Every measure of one position, and its projected cash flows by year.",
            Position,
            position,
        ),
        ToolSpec(
            "run_scenarios",
            "Revalue the book under scenarios, one row each: change in value (all securities, AFS, HTM, "
            "hedges), change in AOCI after tax and net of hedges, 12-month NII and its change, and net "
            "duration after the shock. With no arguments: every configured scenario.",
            Scenarios,
            scenarios,
        ),
        ToolSpec(
            "scenario_breakdown",
            "Where the change in securities value under one scenario comes from, by group, with each "
            "group's share of the total.",
            Breakdown,
            breakdown,
        ),
        ToolSpec(
            "income_report",
            "Net interest income over the next 12 months by component, one column per scenario. With no "
            "arguments: -100bp, base and +100bp.",
            Scenarios,
            income,
        ),
        ToolSpec(
            "prepayment_outlook",
            "Refinancing incentive and projected one-year CPR of the MBS by group, today and under "
            "parallel shocks.",
            Prepayment,
            prepayment,
        ),
        ToolSpec(
            "explain_change",
            "Why market value changed since the prior close: by driver (curve, mortgage rate basis, MBS "
            "spreads), by key rate, and the largest position moves.",
            Explain,
            explain,
        ),
        ToolSpec(
            "limit_status",
            "Every policy limit: value, bounds, headroom (distance to the nearest bound, negative when "
            "breached), utilisation, status (OK, WARN or BREACH) and the policy section that sets it.",
            NoArguments,
            limits,
        ),
        ToolSpec(
            "limit_remedy",
            "Indicative only; nothing is traded. Size a par swap that brings one limit to its breached "
            "bound, or to a target, one option per tenor: notional, the limit before and after, net "
            "duration, change in 12-month NII and the number of limits still breached.",
            Remedy,
            remedy,
            proposal=True,
        ),
        ToolSpec(
            "size_hedge",
            "Indicative only; nothing is traded. Size par swaps that bring net effective duration to a "
            "target, checked by full revaluation: the trades, and net key-rate DV01 and net duration "
            "before and after.",
            Hedge,
            hedge,
            proposal=True,
        ),
        ToolSpec(
            "what_if",
            "Indicative only; nothing is booked. Compare the book before and after selling positions "
            "and adding par swaps: headline numbers, limit metrics, and the limits after the change.",
            WhatIf,
            what_if,
            proposal=True,
        ),
        ToolSpec(
            "aggregate",
            "Arithmetic on figures of earlier results: a sum, a difference or a ratio of cells. Use it "
            "for every total, difference or share that is not already a cell of a result.",
            Aggregate,
            aggregate,
        ),
    )
