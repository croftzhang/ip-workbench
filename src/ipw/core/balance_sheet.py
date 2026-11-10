"""Accounting views of a revaluation: AOCI and 12-month net interest income.

AOCI
    Only available-for-sale (AFS) securities are carried at fair value through
    other comprehensive income. Held-to-maturity (HTM) securities stay at
    amortised cost, so their value changes are reported but never reach AOCI.
    Swaps designated as fair-value hedges of AFS securities offset the hedged
    item, so the AOCI sensitivity shown here is net of those swaps.

Net interest income (NII)
    interest income   effective-yield method: each security earns its
                      prospective book yield on amortised cost. Faster
                      prepayments shorten premium bonds and lower that yield.
    reinvestment      principal received is reinvested at the forward par
                      yield for a chosen tenor plus a spread.
    hedge carry       floating received minus fixed paid on the swaps.
    funding cost      book value funded at a blended rate that moves with the
                      short rate times a funding beta.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from ipw.core.config import BalanceSheetParams
from ipw.core.engine import Valuation
from ipw.core.pricing import solve_rate


@dataclass(frozen=True)
class AociImpact:
    afs_securities: float  # change in AFS market value, $mm pre-tax
    hedges: float  # change in value of swaps hedging AFS, $mm pre-tax
    tax_rate: float

    @property
    def pre_tax(self) -> float:
        return self.afs_securities + self.hedges

    @property
    def after_tax(self) -> float:
        return self.pre_tax * (1.0 - self.tax_rate)


def aoci_impact(
    base: Valuation, shocked: Valuation, securities: pd.DataFrame, swaps: pd.DataFrame, tax_rate: float
) -> AociImpact:
    afs = (securities["designation"] == "AFS").to_numpy()
    hedging_afs = (swaps["hedged_book"] == "AFS").to_numpy()
    return AociImpact(
        afs_securities=float((shocked.pv - base.pv)[afs].sum()),
        hedges=float((shocked.swap_pv - base.swap_pv)[hedging_afs].sum()),
        tax_rate=tax_rate,
    )


@dataclass(frozen=True)
class NetInterestIncome:
    """Projected income over the NII horizon, $mm."""

    coupon_income: float
    amortization: float  # premium amortisation (negative) net of discount accretion
    reinvestment: float
    hedge_carry: float
    funding_cost: float  # negative

    @property
    def interest_income(self) -> float:
        return self.coupon_income + self.amortization

    @property
    def total(self) -> float:
        return self.interest_income + self.reinvestment + self.hedge_carry + self.funding_cost

    def as_dict(self) -> dict[str, float]:
        return {**asdict(self), "interest_income": self.interest_income, "total": self.total}


def book_yield(val: Valuation, securities: pd.DataFrame) -> np.ndarray:
    """Prospective effective yield (continuous) of each security on amortised cost."""
    amortised_cost = securities["book_value_mm"].to_numpy() + val.cash.accrued
    return solve_rate(val.cash.total, amortised_cost)


def net_interest_income(
    val: Valuation,
    securities: pd.DataFrame,
    swaps: pd.DataFrame,
    params: BalanceSheetParams,
    base_short_rate: float,
) -> NetInterestIncome:
    """NII over the next ``params.nii_horizon_months`` months for one valuation.

    ``base_short_rate`` is today's short rate in the unshocked market; the
    funding rate moves away from ``funding_rate_pct`` by beta times the
    difference between the scenario's short-rate path and that level.
    """
    months = params.nii_horizon_months
    cash = val.cash
    book = securities["book_value_mm"].to_numpy()

    # Interest income: roll amortised cost forward at the effective yield.
    growth = np.exp(book_yield(val, securities) / 12.0)
    amortised_cost = book + cash.accrued
    income = np.zeros_like(book)
    for t in range(months):
        income += amortised_cost * (growth - 1.0)
        amortised_cost = amortised_cost * growth - cash.total[:, t]
    coupon = (cash.balance[:, :months] * securities["coupon"].to_numpy()[:, None] / 1200.0).sum()

    # Reinvestment: principal paid in month t earns the new-money yield for the rest of the horizon.
    new_money = (
        val.env.curve.forward_par(params.reinvest_tenor_years, months)[1:] + params.reinvest_spread_bp / 1e4
    )
    months_left = (months - np.arange(1, months + 1)) / 12.0
    reinvestment = float((cash.principal[:, :months].sum(axis=0) * new_money * months_left).sum())

    short = val.env.short_rate[:months]
    funding_rate = params.funding_rate_pct / 100.0 + params.funding_beta * (short - base_short_rate)
    funding = -float(book.sum() * funding_rate.sum() / 12.0)

    # Hedge carry on an accrual basis: (floating - fixed) on the notional still outstanding.
    carry = 0.0
    if len(swaps):
        sign = np.where(swaps["direction"] == "PAY_FIXED", 1.0, -1.0)[:, None]
        fixed = swaps["fixed_rate"].to_numpy(dtype=float)[:, None] / 100.0
        alive = val.swap_cash.balance[:, :months]
        carry = float((sign * alive * (short[None, :] - fixed) / 12.0).sum())

    return NetInterestIncome(
        coupon_income=float(coupon),
        amortization=float(income.sum() - coupon),
        reinvestment=reinvestment,
        hedge_carry=carry,
        funding_cost=funding,
    )
