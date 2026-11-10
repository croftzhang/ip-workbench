"""ipw - classic command-line interface (version 1: deterministic, no LLM).

Each command is a thin wrapper: load the Workbench, call one method, print the
table it returns. All analytics live in ``ipw.core``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd
import typer
from rich.console import Console
from rich.markup import escape
from rich.measure import Measurement

from ipw.classic.brief import build_brief, write_brief
from ipw.classic.render import NII_LABELS, markdown_table, rich_table
from ipw.core.hedging import par_swaps
from ipw.core.workbench import GROUPINGS, Workbench

app = typer.Typer(
    help="Investment-portfolio analytics for agency MBS (classic, deterministic version).",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
console = Console()
_state: dict = {"root": None, "format": "table"}
BY_HELP = "Group by: " + ", ".join(GROUPINGS)


@app.callback()
def _options(
    root: Path = typer.Option(
        None, "--root", help="Folder holding config/ and data/ (default: auto-detect)."
    ),
    fmt: str = typer.Option("table", "--format", "-f", help="Output format: table, json or md."),
):
    if fmt not in ("table", "json", "md"):
        raise typer.BadParameter("format must be table, json or md")
    _state.update(root=root, format=fmt)


@lru_cache(maxsize=1)
def _load(root: Path | None) -> Workbench:
    return Workbench.load(root)


def wb() -> Workbench:
    return _load(_state["root"])


def emit(frame: pd.DataFrame, title: str, columns=None, index_label: str | None = None,
         default: str = "{:,.2f}") -> None:  # fmt: skip
    """Print a table in the selected format."""
    if _state["format"] == "json":
        shown = frame[list(columns)] if columns is not None else frame
        payload = {"title": title, "rows": json.loads(shown.reset_index().to_json(orient="records"))}
        print(json.dumps(payload, indent=2))
    elif _state["format"] == "md":
        print(f"**{title}**\n\n{markdown_table(frame, columns, index_label, default)}\n")
    else:
        table = rich_table(frame, None, columns, index_label, default)
        # Never truncate a number: if the table is wider than the window it is
        # printed at its full width and the terminal wraps the lines.
        needed = Measurement.get(console, console.options.update_width(10_000), table).maximum
        out = console if needed <= console.width else Console(width=needed)
        out.print(f"\n[bold]{escape(title)}[/]")
        out.print(table)


def _floats(text: str) -> tuple[float, ...]:
    return tuple(float(x) for x in text.split(",") if x.strip())


# --------------------------------------------------------------------------- portfolio views
@app.command()
def summary(by: str = typer.Option("bucket", help=BY_HELP)):
    """Composition and valuation: face, book value, market value, unrealized gain or loss."""
    cols = ["positions", "current_face_mm", "book_value_mm", "market_value_mm", "unrealized_mm",
            "book_price", "price", "coupon", "book_yield_pct", "yield_pct"]  # fmt: skip
    emit(wb().summary(by), f"Portfolio as of {wb().market.as_of} ($mm)", cols)


@app.command()
def risk(by: str = typer.Option("bucket", help=BY_HELP)):
    """Effective duration, convexity and DV01 by group, with hedges and the net position."""
    emit(wb().risk_table(by), "Interest-rate risk (bump and revalue, prepayments re-projected)",
         index_label=by.replace("_", " ").title())  # fmt: skip


@app.command()
def krd(
    by: str = typer.Option("designation", help=BY_HELP),
    unit: str = typer.Option("years", help="years (contribution to duration) or k ($ thousands per bp)."),
):
    """Key-rate profile on the Treasury par curve."""
    title = "Key-rate durations (years)" if unit == "years" else "Key-rate DV01 ($k per bp)"
    emit(wb().key_rate_table(by, unit), title, index_label=by.replace("_", " ").title(),
         default="{:.2f}" if unit == "years" else "{:,.0f}")  # fmt: skip


@app.command()
def position(position_id: str = typer.Argument(..., help="A position_id from data/portfolio.csv.")):
    """Everything about one position, plus its projected cash flows by year."""
    details, flows = wb().position(position_id)
    emit(details.to_frame("value"), f"Position {position_id}", index_label="Measure", default="{:,.3f}")
    emit(flows.head(15), "Projected cash flows by year ($mm)")


@app.command()
def top(
    metric: str = typer.Option(
        "dv01_k", help="Any position column, e.g. dv01_k, unrealized_mm, eff_duration."
    ),
    n: int = typer.Option(10, "-n", help="Number of positions."),
    asc: bool = typer.Option(False, "--asc", help="Smallest first (e.g. largest losses)."),
):
    """Largest positions by a chosen measure."""
    emit(wb().top(metric, n, ascending=asc), f"Top {n} positions by {metric}")


# --------------------------------------------------------------------------- scenarios
@app.command()
def scenario(
    name: list[str] = typer.Option(None, "--name", "-n", help="Configured scenario name; repeatable."),
    shock: list[float] = typer.Option(None, "--shock", "-s", help="Parallel shock in bp; repeatable."),
    by: str = typer.Option(None, help="Break one scenario down by group. " + BY_HELP),
    list_only: bool = typer.Option(False, "--list", help="List the configured scenarios and exit."),
):
    """Revalue the book under scenarios: value, AOCI, NII and duration after the shock."""
    if list_only:
        listing = pd.DataFrame({"description": {k: s.description for k, s in wb().scenarios.items()}})
        return emit(listing, "Configured scenarios (config/scenarios.yaml)", index_label="Scenario")
    chosen = [*(name or []), *(shock or [])]
    if by:
        if len(chosen) != 1:
            raise typer.BadParameter("--by needs exactly one scenario (--name or --shock)")
        s = wb().scenario(chosen[0])
        return emit(wb().scenario_detail(s, by), f"{s.description}: value change by {by} ($mm)",
                    index_label=by.replace("_", " ").title())  # fmt: skip
    cols = ["description", "d_value_mm", "d_value_pct", "d_afs_mm", "d_htm_mm", "d_hedges_mm",
            "d_aoci_mm", "nii_mm", "d_nii_mm", "net_duration"]  # fmt: skip
    title = "Scenarios: instantaneous shocks ($mm; AOCI after tax, net of hedges)"
    emit(wb().scenario_table(chosen or None), title, cols, index_label="Scenario")


@app.command()
def nii(
    scenario: list[str] = typer.Option(
        None, "--scenario", "-s", help="Scenario name or parallel bp; repeatable."
    ),
):
    """12-month net interest income, decomposed, for the base case and shocks."""
    table = wb().nii_table(scenario or (-100, "base", 100)).rename(index=NII_LABELS)
    emit(table, "Net interest income, next 12 months ($mm)", index_label="Component", default="{:,.1f}")


@app.command()
def prepay(
    s_curve: bool = typer.Option(
        False, "--s-curve", help="Show the model's S-curve instead of the portfolio."
    ),
    by: str = typer.Option("bucket", help=BY_HELP),
):
    """Refinancing incentive and projected speeds, today and under +/-100bp."""
    if s_curve:
        return emit(wb().s_curve(), "Prepayment model: speeds for a seasoned, average-size loan (% CPR)")
    emit(wb().prepay_table(by=by), f"Prepayment outlook by {by} (CPR in %, projected 12 months)",
         index_label=by.replace("_", " ").title(), default="{:.1f}")  # fmt: skip


@app.command()
def explain(n: int = typer.Option(5, "-n", help="Number of largest position moves to show.")):
    """Why market value changed since the prior close: curve, mortgage basis, spreads."""
    ex = wb().explain()
    if _state["format"] == "table":
        console.print(
            f"Prior close {ex.prior_as_of} -> {ex.as_of}. 30-year mortgage rate "
            f"{ex.mortgage_rate_move_bp:+.0f}bp, basis to the 10-year {ex.mortgage_basis_move_bp:+.0f}bp."
        )
    emit(ex.by_driver, "Change in value by driver ($mm)", index_label="Driver", default="{:+,.2f}")
    emit(ex.by_key_rate.set_index("tenor"), "Curve move and first-order P&L by key rate")
    moves = ex.by_position.reindex(ex.by_position["total_mm"].abs().sort_values(ascending=False).index).head(
        n
    )
    emit(moves.set_index("position_id"), f"Largest {n} position moves ($mm)")


# --------------------------------------------------------------------------- limits and hedging
@app.command()
def limits():
    """Policy limits: value, utilisation and status."""
    cols = ["name", "value", "min", "max", "unit", "utilisation_pct", "status", "policy_ref"]
    emit(wb().limit_table(), "Policy limits (config/limits.yaml)", cols, index_label="ID")


@app.command()
def fix(
    limit_id: str = typer.Argument(..., help="Limit id from `ipw limits`, e.g. AOCI_UP200."),
    tenors: str = typer.Option("2,5,10", help="Swap tenors to try, comma separated."),
    target: float = typer.Option(None, help="Metric value to aim for (default: the breached bound)."),
):
    """Size a swap that brings a limit back inside, one option per tenor."""
    rows = {}
    for tenor in _floats(tenors):
        f = wb().fix_limit(limit_id, tenor, target)
        trade = f.trades.iloc[0]
        statuses = pd.Series([r.status for r in f.result.limit_report()]).value_counts()
        rows[f"{trade['direction']} {tenor:g}Y"] = {
            "notional_mm": trade["notional_mm"],
            "fixed_rate": trade["fixed_rate"],
            "before": f.before.value,
            "after": f.after.value,
            "utilisation_pct": f.after.utilisation * 100.0,
            "net_duration": f.result.headline()["net_duration"],
            "d_nii_mm": f.carry_12m_mm,
            "breaches_after": float(statuses.get("BREACH", 0)),
        }
    emit(pd.DataFrame(rows).T, f"Swap options to bring {limit_id} to its limit (indicative)",
         index_label="Option")  # fmt: skip


@app.command()
def hedge(
    target_duration: float = typer.Option(
        ..., "--target-duration", "-t", help="Net effective duration to reach."
    ),
    mode: str = typer.Option(
        "duration", help="duration (one tenor) or krd (several tenors, keeps curve shape)."
    ),
    tenors: str = typer.Option("5", help="Swap tenors in years, comma separated."),
):
    """Size par swaps to reach a target net duration (verified by full revaluation)."""
    h = wb().hedge(target_duration, mode, _floats(tenors))
    emit(h.trades.set_index("swap_id"), f"Proposed trades ({mode} mode): net duration "
         f"{h.duration_before:.2f} -> {h.duration_after:.2f}",
         ["direction", "notional_mm", "fixed_rate", "remaining_years"], index_label="Swap")  # fmt: skip
    profile = pd.DataFrame({"before": h.kr01_before_k, "after": h.kr01_after_k}).T
    profile["Sum"] = profile.sum(axis=1)
    emit(profile, "Net key-rate DV01 ($k per bp)", index_label="", default="{:,.0f}")


@app.command()
def whatif(
    drop: str = typer.Option("", help="Position ids to sell, comma separated."),
    pay_fixed: list[str] = typer.Option(
        None, "--pay-fixed", help="TENOR:NOTIONAL_MM, e.g. 5:250; repeatable."
    ),
    receive_fixed: list[str] = typer.Option(None, "--receive-fixed", help="TENOR:NOTIONAL_MM; repeatable."),
):
    """Compare the book before and after selling positions and/or adding par swaps."""
    swaps = []
    for direction, items in (("PAY_FIXED", pay_fixed or []), ("RECEIVE_FIXED", receive_fixed or [])):
        for item in items:
            tenor, notional = item.split(":")
            swaps.append(
                par_swaps(wb().engine, (float(tenor),), direction).assign(notional_mm=float(notional))
            )
    after = wb().what_if(
        drop=[x.strip() for x in drop.split(",") if x.strip()],
        add_swaps=pd.concat(swaps, ignore_index=True) if swaps else None,
    )
    emit(wb().compare(after), "What-if: headline numbers and limit metrics", index_label="Measure")
    cols = ["name", "value", "min", "max", "unit", "utilisation_pct", "status"]
    emit(after.limit_table(), "Limits after the change", cols, index_label="ID")


# --------------------------------------------------------------------------- report
@app.command()
def brief(
    out: Path = typer.Option(Path("reports"), help="Folder for the Markdown file."),
    stdout: bool = typer.Option(False, "--stdout", help="Print the brief instead of writing a file."),
):
    """Write the daily risk brief (Markdown)."""
    if stdout:
        print(build_brief(wb()))
    else:
        console.print(f"Wrote {write_brief(wb(), out)}")


def main() -> None:
    """Entry point: turn expected errors into one-line messages instead of tracebacks."""
    try:
        app()
    except (KeyError, ValueError, FileNotFoundError) as err:
        message = err.args[0] if err.args else str(err)
        Console(stderr=True).print(f"[bold red]Error:[/] {message}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
