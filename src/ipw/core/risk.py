"""Interest-rate risk by bump-and-revalue.

Every measure here is a difference of full revaluations with prepayments
re-projected, so the mortgage option shows up as shorter cash flows when
rates fall and longer ones when they rise.

    effective duration  = (PV- - PV+) / (2 * PV0 * dy)
    effective convexity = (PV- + PV+ - 2 * PV0) / (PV0 * dy^2) / 100
    DV01                = (PV- - PV+) / (2 * bump in bp)            [$ per bp]
    KR01_k              = DV01 for a hat-shaped bump at key tenor k

Convexity is scaled by 1/100 (market convention), so for a 100bp move
    % price change ~= -duration + 0.5 * convexity.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ipw.core.curve import key_rate_shock, parallel_shock
from ipw.core.engine import Engine, Valuation
from ipw.core.scenarios import BASE, Scenario


@dataclass
class RiskResult:
    bump_bp: float
    key_tenors: tuple[float, ...]
    base: Valuation
    pv_up: np.ndarray  # (n,) securities, parallel +bump
    pv_dn: np.ndarray
    swap_up: np.ndarray  # (m,) swaps
    swap_dn: np.ndarray
    kr01: np.ndarray  # (n, K) $mm per bp; empty if key rates were not requested
    swap_kr01: np.ndarray  # (m, K)

    @property
    def dv01(self) -> np.ndarray:
        """$mm lost per +1bp parallel move, per security."""
        return (self.pv_dn - self.pv_up) / (2.0 * self.bump_bp)

    @property
    def swap_dv01(self) -> np.ndarray:
        return (self.swap_dn - self.swap_up) / (2.0 * self.bump_bp)

    def duration(self, mask: np.ndarray | None = None, with_swaps: bool = False) -> float:
        """Effective duration of a subset of securities, optionally net of all swaps."""
        sel = slice(None) if mask is None else mask
        dv01 = self.dv01[sel].sum() + (self.swap_dv01.sum() if with_swaps else 0.0)
        return float(dv01 * 1e4 / self.base.pv[sel].sum())

    def convexity(self, mask: np.ndarray | None = None, with_swaps: bool = False) -> float:
        sel = slice(None) if mask is None else mask
        curvature = (self.pv_up[sel] + self.pv_dn[sel] - 2.0 * self.base.pv[sel]).sum()
        if with_swaps:
            curvature += (self.swap_up + self.swap_dn - 2.0 * self.base.swap_pv).sum()
        dy = self.bump_bp / 1e4
        return float(curvature / (self.base.pv[sel].sum() * dy * dy) / 100.0)


def compute_risk(engine: Engine, scenario: Scenario = BASE, key_rates: bool = True) -> RiskResult:
    """Parallel and key-rate sensitivities around ``scenario`` (default: today)."""
    params = engine.model.risk
    bump = params.bump_bp
    base = engine.base if scenario == BASE else engine.value(scenario)
    up = engine.value(scenario, parallel_shock(bump))
    dn = engine.value(scenario, parallel_shock(-bump))

    tenors = params.key_tenors if key_rates else ()
    kr01 = np.zeros((len(base.pv), len(tenors)))
    swap_kr01 = np.zeros((len(base.swap_pv), len(tenors)))
    for k in range(len(tenors)):
        k_up = engine.value(scenario, key_rate_shock(tenors, k, bump))
        k_dn = engine.value(scenario, key_rate_shock(tenors, k, -bump))
        kr01[:, k] = (k_dn.pv - k_up.pv) / (2.0 * bump)
        swap_kr01[:, k] = (k_dn.swap_pv - k_up.swap_pv) / (2.0 * bump)
    return RiskResult(bump, tuple(tenors), base, up.pv, dn.pv, up.swap_pv, dn.swap_pv, kr01, swap_kr01)
