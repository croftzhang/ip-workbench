"""Day-over-day explain: why did market value change since the prior close?

Positions are held fixed and the market is moved from the prior close to
today in three steps, revaluing the whole book after each one:

1. Treasury curve      (mortgage rates follow the 10-year; spreads unchanged)
2. Mortgage rate basis (primary mortgage rate vs the 10-year; changes prepayments)
3. MBS spreads         (zero-volatility spreads re-calibrated to today's prices)

The curve step is split into a first-order part predicted by yesterday's
key-rate exposures and a remainder (convexity and curve-shape detail). A large
remainder means the linear risk report did not describe the day well.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from ipw.core.config import Market
from ipw.core.engine import Engine
from ipw.core.risk import compute_risk

DRIVERS = [
    "Curve: key-rate exposure (first order)",
    "Curve: convexity and residual",
    "Mortgage rate basis",
    "MBS spreads",
]


@dataclass
class ExplainResult:
    prior_as_of: date
    as_of: date
    by_driver: pd.DataFrame  # rows DRIVERS + Total; columns AFS, HTM, Hedges, Total ($mm)
    by_key_rate: pd.DataFrame  # tenor, prior_pct, today_pct, move_bp, kr01_k, pnl_mm
    by_position: pd.DataFrame  # position_id, curve_mm, basis_mm, spread_mm, total_mm, spread_move_bp
    mortgage_rate_move_bp: float
    mortgage_basis_move_bp: float


def explain(today: Engine, prior_market: Market) -> ExplainResult:
    prior = Engine(today.securities, today.swaps, prior_market, today.model)
    curve, spreads = today.market.curve, today.market.mortgage_spreads
    steps = [
        prior.base,
        prior.value(curve=curve),
        prior.value(curve=curve, mortgage_spreads=spreads),
        today.base,
    ]

    risk = compute_risk(prior)
    tenors = risk.key_tenors
    prior_par = np.array([prior_market.curve.par_rate(t) for t in tenors])
    today_par = np.array([curve.par_rate(t) for t in tenors])
    move_bp = (today_par - prior_par) * 1e4
    first_order = -risk.kr01 @ move_bp
    first_order_swaps = -risk.swap_kr01 @ move_bp

    sec = today.securities
    step_sec = [b.pv - a.pv for a, b in zip(steps, steps[1:])]
    step_swap = [b.swap_pv - a.swap_pv for a, b in zip(steps, steps[1:])]
    parts_sec = [first_order, step_sec[0] - first_order, step_sec[1], step_sec[2]]
    parts_swap = [first_order_swaps, step_swap[0] - first_order_swaps, step_swap[1], step_swap[2]]

    afs = (sec["designation"] == "AFS").to_numpy()
    by_driver = pd.DataFrame(
        {
            "AFS": [p[afs].sum() for p in parts_sec],
            "HTM": [p[~afs].sum() for p in parts_sec],
            "Hedges": [p.sum() for p in parts_swap],
        },
        index=DRIVERS,
    )
    by_driver["Total"] = by_driver.sum(axis=1)
    by_driver.loc["Total"] = by_driver.sum(axis=0)

    kr01_total = risk.kr01.sum(axis=0) + risk.swap_kr01.sum(axis=0)
    by_key_rate = pd.DataFrame(
        {
            "tenor": [f"{t:g}Y" for t in tenors],
            "prior_pct": prior_par * 100.0,
            "today_pct": today_par * 100.0,
            "move_bp": move_bp,
            "kr01_k": kr01_total * 1e3,
            "pnl_mm": -kr01_total * move_bp,
        }
    )

    by_position = pd.DataFrame(
        {
            "position_id": sec["position_id"].to_numpy(),
            "bucket": sec["bucket"].to_numpy(),
            "designation": sec["designation"].to_numpy(),
            "curve_mm": step_sec[0],
            "basis_mm": step_sec[1],
            "spread_mm": step_sec[2],
            "total_mm": steps[-1].pv - steps[0].pv,
            "spread_move_bp": (today.base.spread - prior.base.spread) * 1e4,
        }
    )
    return ExplainResult(
        prior_as_of=prior_market.as_of,
        as_of=today.market.as_of,
        by_driver=by_driver,
        by_key_rate=by_key_rate,
        by_position=by_position,
        mortgage_rate_move_bp=(today.market.mortgage_rate_30y_pct - prior_market.mortgage_rate_30y_pct)
        * 100.0,
        mortgage_basis_move_bp=(spreads[0] - prior_market.mortgage_spreads[0]) * 1e4,
    )
