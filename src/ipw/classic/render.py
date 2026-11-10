"""Presentation shared by the terminal tables and the Markdown brief.

One place decides how a column is labelled and formatted, so a number looks
the same on screen and in the brief. Amounts are $ millions unless the label
says otherwise.
"""

from __future__ import annotations

import math

import pandas as pd
from rich import box
from rich.markup import escape
from rich.table import Table

# column -> (label, number format)
SPEC: dict[str, tuple[str, str]] = {
    "positions": ("Pos", "{:,.0f}"),
    "current_face_mm": ("Face", "{:,.1f}"),
    "face_mm": ("Face", "{:,.1f}"),
    "book_value_mm": ("Book value", "{:,.1f}"),
    "market_value_mm": ("Mkt value", "{:,.1f}"),
    "unrealized_mm": ("Unrealized", "{:+,.1f}"),
    "book_price": ("Book px", "{:.2f}"),
    "price": ("Mkt px", "{:.2f}"),
    "coupon": ("Coupon", "{:.2f}"),
    "wac": ("WAC", "{:.2f}"),
    "book_yield_pct": ("Book yld %", "{:.2f}"),
    "yield_pct": ("Mkt yld %", "{:.2f}"),
    "zv_spread_bp": ("ZV sprd bp", "{:.0f}"),
    "wal_years": ("WAL yrs", "{:.1f}"),
    "cpr_1y_pct": ("CPR 1y %", "{:.1f}"),
    "cpr_1y_shocked_pct": ("CPR 1y % shocked", "{:.1f}"),
    "eff_duration": ("Eff dur", "{:.2f}"),
    "eff_convexity": ("Convexity", "{:+.2f}"),
    "dv01_k": ("DV01 $k", "{:,.0f}"),
    "description": ("Description", "{}"),
    "d_value_mm": ("Chg value", "{:+,.1f}"),
    "d_value_pct": ("Chg %", "{:+.2f}"),
    "share_pct": ("Share %", "{:.1f}"),
    "d_afs_mm": ("Chg AFS", "{:+,.1f}"),
    "d_htm_mm": ("Chg HTM", "{:+,.1f}"),
    "d_hedges_mm": ("Chg hedges", "{:+,.1f}"),
    "d_aoci_mm": ("Chg AOCI a/t", "{:+,.1f}"),
    "nii_mm": ("NII 12m", "{:,.1f}"),
    "d_nii_mm": ("Chg NII", "{:+,.1f}"),
    "net_duration": ("Net dur", "{:.2f}"),
    "incentive_pct": ("Incentive %", "{:+.2f}"),
    "turnover_cpr": ("Turnover CPR %", "{:.1f}"),
    "refi_cpr": ("Refi CPR %", "{:.1f}"),
    "total_cpr": ("Total CPR %", "{:.1f}"),
    "name": ("Limit", "{}"),
    "value": ("Value", "{:,.2f}"),
    "min": ("Min", "{:,.2f}"),
    "max": ("Max", "{:,.2f}"),
    "unit": ("Unit", "{}"),
    "utilisation_pct": ("Used %", "{:.0f}"),
    "status": ("Status", "{}"),
    "policy_ref": ("Policy", "{}"),
    "tenor": ("Tenor", "{}"),
    "prior_pct": ("Prior %", "{:.2f}"),
    "today_pct": ("Today %", "{:.2f}"),
    "move_bp": ("Move bp", "{:+.1f}"),
    "kr01_k": ("KR01 $k", "{:,.0f}"),
    "pnl_mm": ("P&L", "{:+,.2f}"),
    "swap_id": ("Swap", "{}"),
    "direction": ("Direction", "{}"),
    "notional_mm": ("Notional", "{:,.1f}"),
    "fixed_rate": ("Fixed %", "{:.3f}"),
    "remaining_years": ("Years", "{:.1f}"),
    "hedged_book": ("Hedges", "{}"),
    "value_mm": ("Value", "{:+,.2f}"),
    "bucket": ("Bucket", "{}"),
    "designation": ("Desig", "{}"),
    "asset_type": ("Type", "{}"),
    "agency": ("Agency", "{}"),
    "orig_year": ("Vintage", "{:.0f}"),
    "position_id": ("Position", "{}"),
    "interest_mm": ("Interest", "{:,.2f}"),
    "scheduled_mm": ("Sched prin", "{:,.2f}"),
    "prepaid_mm": ("Prepaid", "{:,.2f}"),
    "cpr_pct": ("CPR %", "{:.1f}"),
    "end_balance_mm": ("End balance", "{:,.1f}"),
    "year": ("Year", "{:.0f}"),
    "curve_mm": ("Curve", "{:+,.2f}"),
    "basis_mm": ("Mtg basis", "{:+,.2f}"),
    "spread_mm": ("Spread", "{:+,.2f}"),
    "total_mm": ("Total", "{:+,.2f}"),
    "spread_move_bp": ("Sprd move bp", "{:+.1f}"),
    "before": ("Before", "{:,.2f}"),
    "after": ("After", "{:,.2f}"),
    "change": ("Change", "{:+,.2f}"),
    "breaches_after": ("Breaches after", "{:.0f}"),
}
NII_LABELS = {
    "coupon_income": "Coupon income",
    "amortization": "Premium amortisation, net",
    "interest_income": "Interest income",
    "reinvestment": "Reinvestment of principal",
    "hedge_carry": "Hedge carry",
    "funding_cost": "Funding cost",
    "total": "Net interest income",
}
STATUS_STYLE = {"OK": "green", "WARN": "yellow", "BREACH": "bold red"}


def label(column: str) -> str:
    if column in SPEC:
        return SPEC[column][0]
    text = str(column)
    return "CPR " + text[4:] if text.startswith("cpr_") else text


def cell(column: str, value, default: str = "{:,.2f}") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    if isinstance(value, str):
        return value
    return SPEC.get(column, ("", default))[1].format(value)


def _grid(frame: pd.DataFrame, columns, index_label, default):
    """Headers, formatted rows and a numeric flag per column (index first)."""
    columns = list(columns) if columns is not None else list(frame.columns)
    headers = [index_label or label(frame.index.name or "")] + [label(c) for c in columns]
    numeric = [False] + [pd.api.types.is_numeric_dtype(frame[c]) for c in columns]
    rows = [
        [cell(frame.index.name or "", idx)] + [cell(c, frame.at[idx, c], default) for c in columns]
        for idx in frame.index
    ]
    return headers, rows, numeric


def rich_table(frame: pd.DataFrame, title: str | None = None, columns=None, index_label: str | None = None,
               default: str = "{:,.2f}") -> Table:  # fmt: skip
    headers, rows, numeric = _grid(frame, columns, index_label, default)
    table = Table(title=title, box=box.SIMPLE_HEAD, title_justify="left", title_style="bold", pad_edge=False)
    for i, (header, is_number) in enumerate(zip(headers, numeric)):
        # Numbers never wrap; long text (scenario descriptions) wraps inside its cell.
        wraps = not is_number and i > 0
        table.add_column(
            header,
            justify="right" if is_number else "left",
            no_wrap=not wraps,
            max_width=44 if wraps else None,
        )
    emphasised = {"Total", "Securities", "Net", "total"}
    for row in rows:
        style = "bold" if row[0] in emphasised else None
        table.add_row(
            *[f"[{STATUS_STYLE[c]}]{c}[/]" if c in STATUS_STYLE else escape(c) for c in row], style=style
        )
    return table


def markdown_table(frame: pd.DataFrame, columns=None, index_label: str | None = None,
                   default: str = "{:,.2f}") -> str:  # fmt: skip
    headers, rows, numeric = _grid(frame, columns, index_label, default)
    align = ["---:" if is_number else ":---" for is_number in numeric]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(align) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)
