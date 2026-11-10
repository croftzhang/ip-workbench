"""Daily risk brief: a deterministic Markdown report.

Every number comes from the Workbench and every sentence is a fixed template,
so the same inputs always give the same brief. This is the report the agent
version later annotates; it never replaces these numbers.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from ipw import __version__
from ipw.classic.render import NII_LABELS, markdown_table
from ipw.core.workbench import Workbench

REMEDIATION_TENORS = (2.0, 5.0, 10.0)


def usd(amount: float, signed: bool = False) -> str:
    sign = "-" if amount < 0 else "+" if signed else ""
    return f"{sign}${abs(amount):,.1f}mm"


def _status_counts(results) -> str:
    counts = Counter(r.status for r in results)
    return ", ".join(f"{counts.get(s, 0)} {s}" for s in ("OK", "WARN", "BREACH"))


def _headline(wb: Workbench) -> str:
    h = wb.headline()
    up, dn = wb.run(100), wb.run(-100)
    results = wb.limit_report()
    lines = [
        f"- **Value.** Market value {usd(h['market_value_mm'])} against book value "
        f"{usd(h['book_value_mm'])}. Unrealized {usd(h['unrealized_mm'], True)}: HTM "
        f"{usd(h['unrealized_htm_mm'], True)} (not recognised in equity), AFS "
        f"{usd(h['unrealized_afs_mm'], True)} ({usd(h['afs_unrealized_after_tax_mm'], True)} after tax, "
        "in AOCI).",
        f"- **Rate risk.** Net effective duration {h['net_duration']:.2f} years (securities "
        f"{h['securities_duration']:.2f}, hedges {h['net_duration'] - h['securities_duration']:+.2f}); "
        f"convexity {h['net_convexity']:+.2f}; DV01 ${h['net_dv01_k']:,.0f}k per bp.",
        f"- **Earnings.** Projected 12-month NII {usd(h['nii_12m_mm'])}; a +100bp shock changes it by "
        f"{usd(up.nii.total - h['nii_12m_mm'], True)}, a -100bp shock by "
        f"{usd(dn.nii.total - h['nii_12m_mm'], True)}.",
        f"- **Limits.** {_status_counts(results)}.",
    ]
    for r in results:
        if r.status != "OK":
            bound = " to ".join(f"{b:,.2f}" for b in (r.limit.min, r.limit.max) if b is not None)
            lines.append(
                f"  - **{r.status} {r.limit.id}** - {r.limit.name}: {r.value:,.2f} {r.limit.unit} against "
                f"{bound} ({r.utilisation * 100:.0f}% used; {r.limit.policy_ref})."
            )
    if wb.prior_market is not None:
        d = wb.explain().by_driver["Total"]
        curve = d.iloc[0] + d.iloc[1]
        lines.append(
            f"- **Since prior close ({wb.prior_market.as_of}).** Securities and hedges changed by "
            f"{usd(d['Total'], True)}: curve {usd(curve, True)}, MBS spreads {usd(d['MBS spreads'], True)}, "
            f"mortgage rate basis {usd(d['Mortgage rate basis'], True)}."
        )
    return "\n".join(lines)


def _limits(wb: Workbench) -> str:
    table = wb.limit_table()
    cols = ["name", "value", "min", "max", "unit", "utilisation_pct", "status", "policy_ref"]
    text = markdown_table(table, cols, index_label="ID")
    for r in wb.limit_report():
        if r.status != "BREACH":
            continue
        text += (
            f"\n\n**Indicative remediation for {r.limit.id}** "
            "(par swaps sized to the limit, rounded up to $10mm)\n\n"
        )
        rows = []
        for tenor in REMEDIATION_TENORS:
            try:
                fix = wb.fix_limit(r.limit.id, tenor)
            except ValueError as err:
                text += f"No swap remedy: {err}."
                break
            trade = fix.trades.iloc[0]
            rows.append(
                f"| {trade['direction'].replace('_', ' ').title()} {tenor:g}Y at {trade['fixed_rate']:.2f}% "
                f"| {trade['notional_mm']:,.0f} | {fix.after.value:,.1f} | {fix.after.utilisation * 100:.0f} "
                f"| {fix.result.headline()['net_duration']:.2f} | {fix.carry_12m_mm:+,.1f} "
                f"| {_status_counts(fix.result.limit_report())} |"
            )
        if rows:
            text += (
                f"| Option | Notional | {r.limit.id} after | Used % | Net dur after | 12m NII effect "
                "| All limits after |\n"
                "| :--- | ---: | ---: | ---: | ---: | ---: | :--- |\n" + "\n".join(rows)
            )
            text += (
                "\n\nIndicative sizes only. A trade needs portfolio-manager approval and hedge designation."
            )
    return text


def _composition(wb: Workbench) -> str:
    cols = ["positions", "current_face_mm", "book_value_mm", "market_value_mm", "unrealized_mm",
            "book_price", "price", "coupon", "book_yield_pct", "yield_pct"]  # fmt: skip
    return (
        markdown_table(wb.summary("bucket"), cols)
        + "\n\n"
        + markdown_table(wb.summary("designation"), cols, index_label="Designation")
    )


def _risk(wb: Workbench) -> str:
    cols = [
        "market_value_mm",
        "wal_years",
        "cpr_1y_pct",
        "zv_spread_bp",
        "eff_duration",
        "eff_convexity",
        "dv01_k",
    ]
    return (
        markdown_table(wb.risk_table("bucket"), cols, index_label="Bucket")
        + "\n\nKey-rate durations (years; rows add up to effective duration):\n\n"
        + markdown_table(wb.key_rate_table("designation"), index_label="Book")
    )


def _scenarios(wb: Workbench) -> str:
    cols = ["description", "d_value_mm", "d_value_pct", "d_afs_mm", "d_htm_mm", "d_hedges_mm", "d_aoci_mm",
            "d_nii_mm", "net_duration"]  # fmt: skip
    note = (
        "\n\nChg value is securities only; Chg AOCI is after tax and net of fair-value hedges on AFS; "
        "HTM changes do not reach equity. Net dur is the duration after the shock."
    )
    return markdown_table(wb.scenario_table(), cols, index_label="Scenario") + note


def _nii(wb: Workbench) -> str:
    table = wb.nii_table().rename(index=NII_LABELS)
    return markdown_table(table, index_label="$mm, next 12 months", default="{:,.1f}")


def _explain(wb: Workbench) -> str:
    ex = wb.explain()
    worst = ex.by_position.reindex(ex.by_position["total_mm"].abs().sort_values(ascending=False).index).head(
        5
    )
    return (
        f"Prior close {ex.prior_as_of}. 30-year mortgage rate {ex.mortgage_rate_move_bp:+.0f}bp; "
        f"mortgage rate basis to the 10-year {ex.mortgage_basis_move_bp:+.0f}bp.\n\n"
        + markdown_table(ex.by_driver, index_label="Driver ($mm)", default="{:+,.2f}")
        + "\n\n"
        + markdown_table(ex.by_key_rate.set_index("tenor"), index_label="Key rate")
        + "\n\nLargest position moves:\n\n"
        + markdown_table(
            worst.set_index("position_id"),
            ["bucket", "designation", "curve_mm", "basis_mm", "spread_mm", "total_mm", "spread_move_bp"],
        )  # fmt: skip
    )


def _prepay(wb: Workbench) -> str:
    table = wb.prepay_table()
    note = (
        "\n\nIncentive is WAC minus today's mortgage rate. "
        "CPR columns are projected 12-month speeds in percent."
    )
    return markdown_table(table, index_label="Bucket", default="{:.1f}") + note


def _exposures(wb: Workbench) -> str:
    cols = [
        "bucket",
        "designation",
        "current_face_mm",
        "market_value_mm",
        "unrealized_mm",
        "eff_duration",
        "dv01_k",
    ]
    detail = wb.scenario_detail(200, by="position_id").drop(index="Total")
    pos = wb.positions.set_index("position_id")
    afs = detail.loc[pos.index[pos["designation"] == "AFS"]].nsmallest(5, "d_value_mm")
    afs = afs.join(pos[["bucket", "eff_duration"]])
    return (
        "Largest DV01:\n\n"
        + markdown_table(wb.top("dv01_k", 5), cols)
        + "\n\nLargest unrealized losses:\n\n"
        + markdown_table(wb.top("unrealized_mm", 5, ascending=True), cols)
        + "\n\nLargest AFS losses under +200bp (these drive the AOCI limit):\n\n"
        + markdown_table(
            afs,
            ["bucket", "market_value_mm", "d_value_mm", "d_value_pct", "eff_duration"],
            index_label="Position",
        )  # fmt: skip
    )


def _hedges(wb: Workbench) -> str:
    if not len(wb.swaps):
        return "No hedges."
    cols = ["direction", "notional_mm", "fixed_rate", "remaining_years", "hedged_book", "value_mm", "dv01_k"]
    return markdown_table(wb.hedge_table(), cols, index_label="Swap")


METHOD = """\
- Cash flows are projected on one path in which today's forward rates are realised (zero volatility).
- MBS are discounted at a static spread calibrated to each position's market price and held constant in
  scenarios. The prepayment option is captured through re-projected cash flows, not through an
  option-adjusted spread, so durations of coupons near the refinancing threshold are longer than
  OAS-model durations.
- The prepayment model is stylised and not calibrated to pool data.
- Swaps are valued on the Treasury curve (swap spreads are ignored).
- NII uses a blended funding rate with a funding beta; AOCI is shown after tax and net of fair-value hedges.
- Formulas, sources and parameters: docs/FUNCTIONAL_SPEC.md.
- Assumptions, limitations and tests: docs/MODEL.md."""


def build_brief(wb: Workbench) -> str:
    sections = [
        ("Headline", _headline),
        ("Limits", _limits),
        ("Composition and valuation", _composition),
        ("Interest-rate risk", _risk),
        ("Scenarios", _scenarios),
        ("Net interest income", _nii),
        ("Change since prior close", _explain if wb.prior_market is not None else None),
        ("Prepayment outlook", _prepay),
        ("Largest exposures", _exposures),
        ("Hedge book", _hedges),
    ]
    out = [
        "# Investment Portfolio - Daily Risk Brief",
        f"**As of {wb.market.as_of}** | ipw {__version__}, classic engine (deterministic, no LLM) | "
        "$ millions unless stated\n\n> Illustrative portfolio and market data. Not investment advice.",
    ]
    number = 0
    for title, builder in sections:
        if builder is None:
            continue
        number += 1
        out.append(f"## {number}. {title}\n\n{builder(wb)}")
    out.append(f"## Method and limitations\n\n{METHOD}")
    return "\n\n".join(out) + "\n"


def write_brief(wb: Workbench, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"brief_{wb.market.as_of}.md"
    path.write_text(build_brief(wb), encoding="utf-8")
    return path
