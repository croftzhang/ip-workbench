"""Hedge sizing with par interest-rate swaps.

Swap values are linear in notional, so sizing a hedge is linear algebra on
sensitivities that the risk module has already computed:

``duration`` mode  one swap tenor, notional chosen so that net DV01 hits the target.
``krd`` mode       several tenors, notionals chosen (non-negative least squares)
                   to scale the whole key-rate profile down in proportion, then
                   rescaled so that net DV01 hits the target exactly.

The proposal is indicative. The caller verifies it by adding the swaps to the
book and running the normal risk calculation (see ``Workbench.hedge``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import nnls

from ipw.core.curve import key_rate_shock, parallel_shock
from ipw.core.engine import Engine
from ipw.core.pricing import present_value
from ipw.core.risk import RiskResult


@dataclass
class HedgeProposal:
    mode: str
    target_duration: float
    duration_before: float
    duration_after: float  # filled in after verification by full revaluation
    trades: pd.DataFrame  # swap_id, direction, notional_mm, fixed_rate, remaining_years, hedged_book
    dv01_before_k: float
    dv01_after_k: float
    kr01_before_k: pd.Series  # by key tenor, $k per bp
    kr01_after_k: pd.Series


def par_swaps(engine: Engine, tenors: tuple[float, ...], direction: str = "PAY_FIXED") -> pd.DataFrame:
    """Unit-notional ($1mm) swaps struck at today's par rate for each tenor."""
    curve = engine.market.curve
    return pd.DataFrame(
        {
            "swap_id": [f"NEW-{t:g}Y" for t in tenors],
            "direction": direction,
            "notional_mm": 1.0,
            "fixed_rate": [curve.par_rate(t) * 100.0 for t in tenors],
            "remaining_years": [float(t) for t in tenors],
            "hedged_book": "AFS",
        }
    )


def swap_sensitivities(engine: Engine, swaps: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """(DV01, KR01 matrix) in $mm per bp for a table of swaps, using the engine's bumps."""
    params = engine.model.risk
    product = engine.product("SWAP")

    def value(bump: np.ndarray) -> np.ndarray:
        env = engine.environment(bump_bp=bump)
        return present_value(product.project(swaps, env).total, env.curve.df, np.zeros(len(swaps)))

    b = params.bump_bp
    dv01 = (value(parallel_shock(-b)) - value(parallel_shock(b))) / (2 * b)
    kr01 = np.column_stack(
        [
            (value(key_rate_shock(params.key_tenors, k, -b)) - value(key_rate_shock(params.key_tenors, k, b)))
            / (2 * b)
            for k in range(len(params.key_tenors))
        ]
    )
    return dv01, kr01


def propose_hedge(
    engine: Engine,
    risk: RiskResult,
    target_duration: float,
    mode: str = "duration",
    tenors: tuple[float, ...] = (5.0,),
) -> HedgeProposal:
    if mode not in ("duration", "krd"):
        raise ValueError("mode must be 'duration' or 'krd'")
    if mode == "duration" and len(tenors) != 1:
        raise ValueError("duration mode takes exactly one swap tenor; use krd mode for several")

    market_value = risk.base.pv.sum()
    net_dv01 = risk.dv01.sum() + risk.swap_dv01.sum()
    net_kr01 = risk.kr01.sum(axis=0) + risk.swap_kr01.sum(axis=0)
    to_remove = net_dv01 - target_duration * market_value / 1e4  # $mm per bp; >0 means pay fixed

    # Paying fixed lowers DV01 (unit DV01 < 0); receiving fixed raises it.
    direction = "PAY_FIXED" if to_remove >= 0 else "RECEIVE_FIXED"
    candidates = par_swaps(engine, tuple(tenors), direction)
    unit_dv01, unit_kr01 = swap_sensitivities(engine, candidates)  # per $1mm notional

    if mode == "duration":
        notionals = np.array([to_remove / -unit_dv01[0]])
    else:
        if net_dv01 <= 0:
            raise ValueError("krd mode needs a book with positive net DV01")
        wanted = net_kr01 * to_remove / net_dv01  # KR01 to take out of each bucket
        notionals, _ = nnls(-unit_kr01.T, wanted)
        if notionals.sum() == 0:
            raise ValueError("no non-negative combination of these tenors moves the key-rate profile")
        notionals = notionals * to_remove / (notionals @ -unit_dv01)

    notionals = np.round(notionals, 1)
    trades = candidates.assign(notional_mm=notionals)
    trades = trades[trades["notional_mm"] > 0].reset_index(drop=True)
    change = notionals @ unit_dv01
    kr_change = notionals @ unit_kr01
    labels = [f"{t:g}Y" for t in risk.key_tenors]
    return HedgeProposal(
        mode=mode,
        target_duration=target_duration,
        duration_before=float(net_dv01 * 1e4 / market_value),
        duration_after=float((net_dv01 + change) * 1e4 / market_value),
        trades=trades,
        dv01_before_k=float(net_dv01 * 1e3),
        dv01_after_k=float((net_dv01 + change) * 1e3),
        kr01_before_k=pd.Series(net_kr01 * 1e3, index=labels),
        kr01_after_k=pd.Series((net_kr01 + kr_change) * 1e3, index=labels),
    )
