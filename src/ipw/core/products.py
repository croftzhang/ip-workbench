"""Products: each one turns a table of positions into cash flows on one rate path.

This is the extension point of the engine. A product only has to answer
"what does each position pay, month by month, in this rate environment?".
Pricing, risk, scenarios, AOCI, NII, hedging and limits never look inside a
product, so a new one (MSR, CMO, callable agency ...) plugs in by adding a
class here and registering its ``asset_types``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ipw.core.config import ModelConfig
from ipw.core.curve import Curve
from ipw.core.prepay import PrepayAdjustments, PrepayModel


@dataclass(frozen=True)
class RateEnvironment:
    """Everything a product may need to project cash flows on one deterministic path."""

    curve: Curve
    mortgage_30y: np.ndarray  # (T,) decimal; element j drives prepayments paid in month j+1
    mortgage_15y: np.ndarray
    short_rate: np.ndarray  # (T,) simple annualised one-month forward rate for month j+1
    as_of_month: int  # calendar month of the valuation date, 1..12
    prepay_adj: PrepayAdjustments = PrepayAdjustments()


@dataclass
class CashFlows:
    """Projected cash flows for n positions over T months ($mm)."""

    interest: np.ndarray  # (n, T) interest paid in month t = 1..T
    scheduled: np.ndarray  # (n, T) scheduled principal
    prepaid: np.ndarray  # (n, T) unscheduled principal
    balance: np.ndarray  # (n, T+1) balance outstanding; column 0 is today
    accrued: np.ndarray  # (n,) accrued interest today (part of the dirty value)
    cpr: np.ndarray  # (n, T) projected annualised prepayment speed (NaN if not applicable)

    @classmethod
    def empty(cls, n: int, horizon: int) -> CashFlows:
        z = np.zeros((n, horizon))
        return cls(z.copy(), z.copy(), z.copy(), np.zeros((n, horizon + 1)), np.zeros(n),
                   np.full((n, horizon), np.nan))  # fmt: skip

    @property
    def principal(self) -> np.ndarray:
        return self.scheduled + self.prepaid

    @property
    def total(self) -> np.ndarray:
        return self.interest + self.scheduled + self.prepaid

    def place(self, rows: np.ndarray, other: CashFlows) -> None:
        """Write ``other`` (cash flows of a subset) into the given rows."""
        for name in ("interest", "scheduled", "prepaid", "balance", "accrued", "cpr"):
            getattr(self, name)[rows] = getattr(other, name)


class Product(ABC):
    asset_types: tuple[str, ...] = ()

    def __init__(self, horizon: int):
        self.horizon = horizon

    @abstractmethod
    def project(self, positions: pd.DataFrame, env: RateEnvironment) -> CashFlows:
        """Cash flows for every row of ``positions`` in ``env``."""


# --------------------------------------------------------------------------- agency MBS
def passthrough_cashflows(balance0, coupon_pct, wac_pct, wam, smm) -> CashFlows:
    """Level-pay fixed-rate pass-through cash flows given monthly prepayment rates.

    A pool's balance factorises into scheduled amortisation times prepayment
    survival: B_t = B_0 * f_t * Q_t, with f_t the no-prepayment balance fraction
    and Q_t = prod(1 - SMM_s). Investors receive the net coupon; the difference
    between WAC and coupon is servicing and guarantee fee.
    """
    n, horizon = smm.shape
    r = (wac_pct / 1200.0)[:, None]
    wam = wam[:, None].astype(float)
    remaining = np.clip(wam - np.arange(horizon + 1)[None, :], 0.0, None)
    sched_fraction = (1.0 - (1.0 + r) ** (-remaining)) / (1.0 - (1.0 + r) ** (-wam))
    survival = np.concatenate([np.ones((n, 1)), np.cumprod(1.0 - smm, axis=1)], axis=1)
    balance = balance0[:, None] * sched_fraction * survival

    begin = balance[:, :-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        amort = np.where(
            sched_fraction[:, :-1] > 0, 1.0 - sched_fraction[:, 1:] / sched_fraction[:, :-1], 0.0
        )
    scheduled = begin * amort
    prepaid = (begin - scheduled) * smm
    interest = begin * (coupon_pct / 1200.0)[:, None]
    cpr = 1.0 - (1.0 - smm) ** 12
    return CashFlows(interest, scheduled, prepaid, balance, np.zeros(n), cpr)


class AgencyPassThrough(Product):
    """Fixed-rate agency pass-throughs (30-year and 15-year)."""

    asset_types = ("MBS_30Y", "MBS_15Y")

    def __init__(self, horizon: int, prepay: PrepayModel):
        super().__init__(horizon)
        self.prepay = prepay

    def project(self, positions: pd.DataFrame, env: RateEnvironment) -> CashFlows:
        col = lambda name: positions[name].to_numpy(dtype=float)  # noqa: E731
        is_15y = (col("term_years") <= 15)[:, None]
        mortgage = np.where(is_15y, env.mortgage_15y[None, :], env.mortgage_30y[None, :])
        smm, _, _ = self.prepay.project(
            col("wac"), col("wala_months"), col("wam_months"), col("factor"),
            col("avg_loan_size_k"), mortgage[:, : self.horizon], env.as_of_month, env.prepay_adj,
        )  # fmt: skip
        return passthrough_cashflows(
            col("current_face_mm"), col("coupon"), col("wac"), col("wam_months"), smm
        )


# --------------------------------------------------------------------------- Treasuries
class TreasuryBond(Product):
    """Semi-annual coupon bullet bonds; ``wam_months`` is the remaining term."""

    asset_types = ("UST",)

    def project(self, positions: pd.DataFrame, env: RateEnvironment) -> CashFlows:
        cf = CashFlows.empty(len(positions), self.horizon)
        rows = zip(positions["current_face_mm"], positions["coupon"], positions["wam_months"])
        for i, (face, coupon, remaining) in enumerate(rows):
            remaining = int(remaining)
            coupon_months = np.arange(remaining, 0, -6)  # count back from maturity
            cf.interest[i, coupon_months - 1] = face * coupon / 200.0
            cf.scheduled[i, remaining - 1] = face
            cf.balance[i, :remaining] = face
            cf.accrued[i] = face * coupon / 200.0 * (6 - coupon_months.min()) / 6.0
        return cf


# --------------------------------------------------------------------------- swaps
class FixedFloatSwap(Product):
    """Plain fixed-for-floating swaps on the same curve (single-curve simplification).

    The floating leg is projected at the curve's one-month forward rates, which
    reproduces the textbook value N * (1 - P(T)); the fixed leg pays semi-annually.
    ``PAY_FIXED`` receives floating and pays fixed.
    """

    asset_types = ("SWAP",)

    def project(self, positions: pd.DataFrame, env: RateEnvironment) -> CashFlows:
        cf = CashFlows.empty(len(positions), self.horizon)
        df = env.curve.df
        rows = zip(positions["direction"], positions["notional_mm"], positions["fixed_rate"],
                   positions["remaining_years"])  # fmt: skip
        for i, (direction, notional, fixed_rate, years) in enumerate(rows):
            months = int(round(float(years) * 12))
            sign = 1.0 if direction == "PAY_FIXED" else -1.0
            floating = notional * (df[:months] / df[1 : months + 1] - 1.0)
            fixed = np.zeros(months)
            fixed[5::6] = notional * fixed_rate / 200.0
            cf.interest[i, :months] = sign * (floating - fixed)
            cf.balance[i, :months] = notional
        return cf


def default_products(model: ModelConfig) -> list[Product]:
    horizon = model.horizon_months
    return [
        AgencyPassThrough(horizon, PrepayModel(model.prepay)),
        TreasuryBond(horizon),
        FixedFloatSwap(horizon),
    ]
