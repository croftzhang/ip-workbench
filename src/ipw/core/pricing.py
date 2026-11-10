"""Product-agnostic pricing: discount a cash-flow matrix on a curve plus a spread.

The pricer knows nothing about mortgages, bonds or swaps. Every product hands
over the same thing (cash per position per month) and gets a present value.
"""

from __future__ import annotations

import numpy as np


def discount_matrix(df: np.ndarray | None, spread: np.ndarray, horizon: int) -> np.ndarray:
    """(n, T) discount factors: curve df for month t times exp(-spread * t)."""
    t_years = np.arange(1, horizon + 1) / 12.0
    spread_part = np.exp(-np.outer(spread, t_years))
    return spread_part if df is None else df[1 : horizon + 1][None, :] * spread_part


def present_value(cash: np.ndarray, df: np.ndarray | None, spread: np.ndarray) -> np.ndarray:
    """Present value per row of ``cash`` (n, T) at a continuously compounded spread."""
    return (cash * discount_matrix(df, spread, cash.shape[1])).sum(axis=1)


def solve_rate(
    cash: np.ndarray,
    target: np.ndarray,
    df: np.ndarray | None = None,
    tol: float = 1e-12,
    max_iter: int = 100,
) -> np.ndarray:
    """Row-wise solve PV(cash; df, z) = target for the continuous rate z.

    With ``df`` given, z is the zero-volatility (static) spread to the curve.
    With ``df=None``, z is the internal rate of return (convert with ``bey``).
    Newton's method; PV is decreasing and convex in z for positive cash flows,
    so the iteration converges monotonically after the first step.
    """
    horizon = cash.shape[1]
    t_years = np.arange(1, horizon + 1) / 12.0
    base = cash if df is None else cash * df[1 : horizon + 1][None, :]
    z = np.zeros(cash.shape[0])
    for _ in range(max_iter):
        disc = base * np.exp(-np.outer(z, t_years))
        pv = disc.sum(axis=1)
        slope = -(disc * t_years[None, :]).sum(axis=1)
        step = (pv - target) / slope
        z = z - step
        if np.max(np.abs(step)) < tol:
            return z
    raise RuntimeError("solve_rate did not converge; check prices and cash flows")


def bey(z: np.ndarray) -> np.ndarray:
    """Continuous rate -> semi-annual bond-equivalent yield."""
    return 2.0 * (np.exp(z / 2.0) - 1.0)
