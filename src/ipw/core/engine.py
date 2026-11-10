"""Valuation engine: build a rate environment, project cash flows, discount them.

One call to :meth:`Engine.value` is one full revaluation of the book under a
scenario. Everything else (risk, AOCI, NII, hedging, limits, explain) is built
from differences between such revaluations.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import numpy as np
import pandas as pd

from ipw.core.config import Market, ModelConfig
from ipw.core.curve import Curve
from ipw.core.prepay import PrepayAdjustments
from ipw.core.pricing import present_value, solve_rate
from ipw.core.products import CashFlows, Product, RateEnvironment, default_products
from ipw.core.scenarios import BASE, Scenario


@dataclass
class Valuation:
    """Result of one revaluation. All values in $mm."""

    scenario: Scenario
    env: RateEnvironment
    cash: CashFlows  # securities, in portfolio row order
    swap_cash: CashFlows  # hedge swaps, in hedge-book row order
    spread: np.ndarray  # (n,) zero-volatility spread used for each security, decimal
    pv: np.ndarray  # (n,) dirty value of each security
    swap_pv: np.ndarray  # (m,) value of each swap

    @property
    def clean(self) -> np.ndarray:
        """Market value excluding accrued interest (comparable with book value)."""
        return self.pv - self.cash.accrued


class Engine:
    def __init__(
        self,
        securities: pd.DataFrame,
        swaps: pd.DataFrame,
        market: Market,
        model: ModelConfig,
        products: list[Product] | None = None,
    ):
        self.securities = securities
        self.swaps = swaps
        self.market = market
        self.model = model
        self.horizon = model.horizon_months
        self.products = products or default_products(model)
        self._by_type = {t: p for p in self.products for t in p.asset_types}
        unknown = set(securities["asset_type"]) - set(self._by_type)
        if unknown:
            raise ValueError(f"No product registered for asset_type(s) {sorted(unknown)}")
        self._is_mbs = securities["asset_type"].str.startswith("MBS").to_numpy()

    def product(self, asset_type: str) -> Product:
        return self._by_type[asset_type]

    # ------------------------------------------------------------------ environment
    def environment(
        self,
        scenario: Scenario = BASE,
        bump_bp: np.ndarray | None = None,
        *,
        curve: Curve | None = None,
        mortgage_spreads: tuple[float, float] | None = None,
    ) -> RateEnvironment:
        """Rate environment for ``scenario``, optionally with an extra par-curve bump.

        Mortgage rates follow the forward 10-year par yield plus a constant
        spread calibrated to today's primary rate. ``curve`` and
        ``mortgage_spreads`` override today's market (used by the explain).
        """
        shock = scenario.curve_shock() if bump_bp is None else scenario.curve_shock() + bump_bp
        shocked = (curve or self.market.curve).shifted(shock)
        spread_30y, spread_15y = mortgage_spreads or self.market.mortgage_spreads
        mortgage_30y = (
            shocked.forward_par(10.0, self.horizon)[: self.horizon]
            + spread_30y
            + scenario.mortgage_spread_bp / 1e4
        )
        return RateEnvironment(
            curve=shocked,
            mortgage_30y=mortgage_30y,
            mortgage_15y=mortgage_30y + spread_15y,
            short_rate=shocked.short_rate(self.horizon),
            as_of_month=self.market.as_of.month,
            prepay_adj=PrepayAdjustments(scenario.refi_multiplier, scenario.turnover_multiplier),
        )

    # ------------------------------------------------------------------ cash flows
    def project(self, env: RateEnvironment) -> tuple[CashFlows, CashFlows]:
        cash = CashFlows.empty(len(self.securities), self.horizon)
        types = self.securities["asset_type"].to_numpy()
        for product in self.products:
            rows = np.flatnonzero(np.isin(types, product.asset_types))
            if rows.size:
                cash.place(rows, product.project(self.securities.iloc[rows], env))
        if len(self.swaps):
            swap_cash = self.product("SWAP").project(self.swaps, env)
        else:
            swap_cash = CashFlows.empty(0, self.horizon)
        return cash, swap_cash

    # ------------------------------------------------------------------ calibration
    @cached_property
    def base(self) -> Valuation:
        """Today's valuation, with MBS spreads calibrated to market prices."""
        env = self.environment(BASE)
        cash, swap_cash = self.project(env)
        return self._discount(BASE, env, cash, swap_cash, self._calibrate(cash, env.curve))

    def _calibrate(self, cash: CashFlows, curve: Curve) -> np.ndarray:
        """Zero-volatility spread per security.

        An MBS is calibrated to its own mark; without a mark, to the quote for
        its sector and coupon; without either it gets the default spread.
        Treasuries sit on the curve (spread zero).
        """
        sec = self.securities
        spread = np.where(self._is_mbs, self.model.default_zv_spread_bp / 1e4, 0.0)
        rows = zip(sec["position_id"], sec["asset_type"], sec["coupon"], self._is_mbs)
        price = np.array(
            [self.market.price(pid, a, c) if mbs else None for pid, a, c, mbs in rows], dtype=float
        )  # no price -> NaN
        priced = ~np.isnan(price)
        if priced.any():
            target = price[priced] * sec["current_face_mm"].to_numpy()[priced] / 100.0
            spread[priced] = solve_rate(cash.total[priced], target, curve.df)
        return spread

    # ------------------------------------------------------------------ valuation
    def value(
        self,
        scenario: Scenario = BASE,
        bump_bp: np.ndarray | None = None,
        *,
        curve: Curve | None = None,
        mortgage_spreads: tuple[float, float] | None = None,
        spread: np.ndarray | None = None,
    ) -> Valuation:
        """Revalue the book under ``scenario`` at constant (base) spreads."""
        env = self.environment(scenario, bump_bp, curve=curve, mortgage_spreads=mortgage_spreads)
        cash, swap_cash = self.project(env)
        if spread is None:
            spread = self.base.spread
        return self._discount(scenario, env, cash, swap_cash, spread)

    def _discount(self, scenario, env, cash, swap_cash, spread) -> Valuation:
        shocked_spread = spread + np.where(self._is_mbs, scenario.zv_spread_bp / 1e4, 0.0)
        # Discounting every future cash flow gives the dirty value (accrued included).
        pv = present_value(cash.total, env.curve.df, shocked_spread)
        swap_pv = present_value(swap_cash.total, env.curve.df, np.zeros(len(self.swaps)))
        return Valuation(scenario, env, cash, swap_cash, spread, pv, swap_pv)
