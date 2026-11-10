"""Stylised agency prepayment model.

    CPR = turnover + refinancing

    turnover   = base x seasoning ramp x seasonality x lock-in
    refinancing = S-curve(incentive) x seasoning ramp x loan-size x burnout

``incentive`` is the pool's gross WAC minus the prevailing mortgage rate, in
percentage points. The model is deliberately small: every term is one line and
every parameter lives in ``config/model.yaml``. It is *not* calibrated to pool
data. Formulas and sources: docs/FUNCTIONAL_SPEC.md, FR-3.1. Limitations: docs/MODEL.md.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ipw.core.config import PrepayParams


@dataclass(frozen=True)
class PrepayAdjustments:
    """Scenario multipliers used for prepayment-model stress tests."""

    refi: float = 1.0
    turnover: float = 1.0


def cpr_to_smm(cpr: np.ndarray) -> np.ndarray:
    return 1.0 - (1.0 - cpr) ** (1.0 / 12.0)


class PrepayModel:
    def __init__(self, params: PrepayParams):
        self.p = params
        self.seasonality = np.asarray(params.seasonality, dtype=float)
        if self.seasonality.size != 12:
            raise ValueError("seasonality needs 12 monthly multipliers (Jan..Dec)")

    # ------------------------------------------------------------------ components
    def lock_in(self, incentive_pct: np.ndarray) -> np.ndarray:
        """Turnover multiplier: borrowers far below the market rate move less often."""
        depth = np.clip(-incentive_pct / self.p.lock_in_full_incentive_pct, 0.0, 1.0)
        return 1.0 - self.p.lock_in_max_reduction * depth

    def turnover_cpr(self, incentive_pct, age_months, season=1.0) -> np.ndarray:
        ramp = np.minimum(1.0, age_months / self.p.turnover_ramp_months)
        return self.p.turnover_cpr_pct / 100.0 * ramp * season * self.lock_in(incentive_pct)

    def loan_size_multiplier(self, loan_size_k: np.ndarray) -> np.ndarray:
        """Larger loans save more dollars per point of rate, so they refinance more readily."""
        mult = 1.0 + self.p.loan_size_elasticity * (loan_size_k / self.p.loan_size_ref_k - 1.0)
        return np.clip(mult, self.p.loan_size_min_mult, self.p.loan_size_max_mult)

    def refi_cpr(self, incentive_pct, age_months, loan_size_k) -> np.ndarray:
        """Refinancing CPR before burnout: logistic S-curve in the rate incentive."""
        s_curve = (
            self.p.refi_max_cpr_pct
            / 100.0
            / (1.0 + np.exp(-(incentive_pct - self.p.refi_midpoint_pct) / self.p.refi_slope_pct))
        )
        ramp = np.minimum(1.0, age_months / self.p.refi_ramp_months)
        return s_curve * ramp * self.loan_size_multiplier(loan_size_k)

    def initial_refi_survival(self, wac_pct, wala, wam, factor) -> np.ndarray:
        """Share of the pool's rate-sensitive borrowers still present today.

        Heuristic: compare the pool factor with what scheduled amortisation and
        base turnover alone would have left. A pool that has paid down faster
        than that has already lost refinancers, so its future response is damped.
        """
        r = wac_pct / 1200.0
        scheduled = (1.0 - (1.0 + r) ** (-wam)) / (1.0 - (1.0 + r) ** (-(wala + wam)))
        ramp = self.p.turnover_ramp_months
        eff_months = np.where(wala >= ramp, wala - (ramp - 1) / 2.0, wala * (wala + 1) / (2.0 * ramp))
        turnover_survival = (1.0 - cpr_to_smm(self.p.turnover_cpr_pct / 100.0)) ** eff_months
        return np.clip(factor / (scheduled * turnover_survival), self.p.burnout_floor, 1.0)

    # ------------------------------------------------------------------ projection
    def project(
        self,
        wac_pct: np.ndarray,
        wala: np.ndarray,
        wam: np.ndarray,
        factor: np.ndarray,
        loan_size_k: np.ndarray,
        mortgage_rate: np.ndarray,
        as_of_month: int,
        adj: PrepayAdjustments = PrepayAdjustments(),
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Project speeds for n pools over T months.

        ``mortgage_rate`` is (n, T), decimal; column j is the rate that drives
        prepayments paid in month j+1. Returns (smm, turnover_cpr, refi_cpr),
        each (n, T).
        """
        n, horizon = mortgage_rate.shape
        t = np.arange(1, horizon + 1)
        age = wala[:, None] + t[None, :] - 1
        incentive = wac_pct[:, None] - mortgage_rate * 100.0
        season = self.seasonality[(as_of_month + t - 1) % 12][None, :]

        turnover = self.turnover_cpr(incentive, age, season) * adj.turnover
        refi_base = self.refi_cpr(incentive, age, loan_size_k[:, None]) * adj.refi

        # Burnout is path dependent: each month's refinancing removes the most
        # rate-sensitive borrowers, which damps the response in later months.
        cap = self.p.max_cpr_pct / 100.0
        survival = self.initial_refi_survival(wac_pct, wala, wam, factor)
        refi = np.empty((n, horizon))
        for j in range(horizon):
            refi[:, j] = np.minimum(refi_base[:, j] * survival**self.p.burnout_exponent, cap)
            survival = survival * (1.0 - refi[:, j]) ** (1.0 / 12.0)

        cpr = np.minimum(turnover + refi, cap)
        return cpr_to_smm(cpr), turnover, refi

    def s_curve(self, incentives_pct, age_months: float = 36.0) -> dict[str, np.ndarray]:
        """Model speeds for a seasoned, unburned, average-size loan (for display)."""
        x = np.asarray(incentives_pct, dtype=float)
        turnover = self.turnover_cpr(x, age_months)
        refi = self.refi_cpr(x, age_months, np.asarray(self.p.loan_size_ref_k))
        return {"incentive_pct": x, "turnover_cpr": turnover, "refi_cpr": refi}
