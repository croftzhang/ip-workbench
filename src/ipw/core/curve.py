"""Treasury par curve -> discount factors, forward rates and curve shocks.

Conventions
-----------
* Quotes are semi-annual bond-equivalent par yields.
* Quotes are interpolated linearly onto a semi-annual grid (flat before the
  first and after the last quoted tenor) and bootstrapped into discount factors.
* Monthly discount factors are log-linear between grid nodes, so the forward
  rate is constant inside each six-month period.
* Shocks are applied to the par yields on the grid, then the curve is
  re-bootstrapped. Key-rate shocks are hat functions that add up to a parallel
  shift, which is why key-rate durations add up to effective duration.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np

GRID_YEARS = np.arange(1, 101) * 0.5  # semi-annual nodes: 0.5y, 1.0y, ... 50y
MAX_MONTHS = 600


def _bootstrap(par: np.ndarray) -> np.ndarray:
    """Discount factors at the grid nodes from par yields (decimal) at the same nodes.

    A par bond maturing at node n pays c/2 at every node up to n and 1 at n:
        1 = c/2 * sum_{i<=n} P_i + P_n   =>   P_n = (1 - c/2 * sum_{i<n} P_i) / (1 + c/2)
    """
    df = np.empty_like(par)
    annuity = 0.0
    for i, c in enumerate(par):
        df[i] = (1.0 - 0.5 * c * annuity) / (1.0 + 0.5 * c)
        annuity += df[i]
    return df


class Curve:
    """A bootstrapped discount curve on a monthly grid out to 50 years."""

    def __init__(self, par_grid: np.ndarray):
        self.par_grid = np.asarray(par_grid, dtype=float)  # decimal, on GRID_YEARS
        if self.par_grid.shape != GRID_YEARS.shape:
            raise ValueError("par_grid must be defined on GRID_YEARS")
        node_months = np.arange(0, MAX_MONTHS + 1, 6)
        log_nodes = np.log(np.concatenate(([1.0], _bootstrap(self.par_grid))))
        #: df[m] is the discount factor for a cash flow m months from today
        self.df = np.exp(np.interp(np.arange(MAX_MONTHS + 1), node_months, log_nodes))

    @classmethod
    def from_quotes(cls, tenors_years: Sequence[float], yields_pct: Sequence[float]) -> Curve:
        tenors = np.asarray(tenors_years, dtype=float)
        yields = np.asarray(yields_pct, dtype=float)
        if tenors.size != yields.size or tenors.size < 2 or np.any(np.diff(tenors) <= 0):
            raise ValueError("par curve needs matching, strictly increasing tenors and yields")
        return cls(np.interp(GRID_YEARS, tenors, yields) / 100.0)

    def shifted(self, shock_bp: np.ndarray | float) -> Curve:
        """New curve with ``shock_bp`` (scalar or array on GRID_YEARS) added to the par yields."""
        return Curve(self.par_grid + np.asarray(shock_bp, dtype=float) / 1e4)

    def par_rate(self, tenor_years: float) -> float:
        """Spot par yield (decimal, semi-annual) for a whole number of half-years."""
        return float(self.forward_par(tenor_years, 0)[0])

    def forward_par(self, tenor_years: float, n_months: int) -> np.ndarray:
        """Forward par yield of a ``tenor_years`` bond starting in 0..n_months months."""
        k = int(round(tenor_years * 2))
        if k < 1 or n_months + 6 * k > MAX_MONTHS:
            raise ValueError("forward par rate outside the curve horizon")
        start = np.arange(n_months + 1)
        pay = start[:, None] + 6 * np.arange(1, k + 1)[None, :]
        annuity = self.df[pay].sum(axis=1)
        return 2.0 * (self.df[start] - self.df[start + 6 * k]) / annuity

    def short_rate(self, n_months: int) -> np.ndarray:
        """Simple annualised one-month forward rate for months 1..n_months."""
        return 12.0 * (self.df[:n_months] / self.df[1 : n_months + 1] - 1.0)


# --------------------------------------------------------------------------- shocks
def parallel_shock(bp: float) -> np.ndarray:
    return np.full(GRID_YEARS.size, float(bp))


def piecewise_shock(points: Iterable[tuple[float, float]]) -> np.ndarray:
    """Shock interpolated linearly between (tenor, bp) points, flat outside them."""
    pts = sorted((float(t), float(bp)) for t, bp in points)
    tenors, bps = zip(*pts)
    return np.interp(GRID_YEARS, tenors, bps)


def key_rate_shock(key_tenors: Sequence[float], index: int, bp: float) -> np.ndarray:
    """Hat-function shock centred on ``key_tenors[index]``.

    The first and last hats are flat towards the ends of the curve, so the
    shocks for all indices sum to a parallel shift of ``bp``.
    """
    unit = np.zeros(len(key_tenors))
    unit[index] = 1.0
    return np.interp(GRID_YEARS, np.asarray(key_tenors, dtype=float), unit) * float(bp)
