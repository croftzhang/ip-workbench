"""Independent replication of the valuation chain for single positions.

The reference below is written from docs/FUNCTIONAL_SPEC.md in plain Python: no numpy,
no vectorisation, nothing imported from the engine. It rebuilds the curve,
the mortgage-rate path, the prepayment speeds and the cash flows month by
month, then discounts at the spread the engine calibrated. If the engine and
the documentation ever disagree, the reference price stops matching the mark.
"""

import math

import pytest


def reference_price(row, market, model, spread: float, parallel_bp: float = 0.0) -> tuple[float, float]:
    """(clean price, first-year CPR in percent) of one pass-through position."""
    # --- curve (FR-1, equations 1.1 to 1.4)
    tenors, yields = market.quote_tenors, market.quote_yields_pct

    def quoted_par(t: float) -> float:
        if t <= tenors[0]:
            return yields[0]
        if t >= tenors[-1]:
            return yields[-1]
        for (t0, y0), (t1, y1) in zip(zip(tenors, yields), zip(tenors[1:], yields[1:])):
            if t0 <= t <= t1:
                return y0 + (y1 - y0) * (t - t0) / (t1 - t0)
        raise AssertionError

    nodes, annuity = [], 0.0
    for i in range(1, 101):
        c = (quoted_par(0.5 * i) + parallel_bp / 100.0) / 100.0
        p = (1.0 - 0.5 * c * annuity) / (1.0 + 0.5 * c)
        nodes.append(p)
        annuity += p

    def df(month: int) -> float:
        k, rem = divmod(month, 6)
        lo = 1.0 if k == 0 else nodes[k - 1]
        return lo if rem == 0 else lo * (nodes[k] / lo) ** (rem / 6.0)

    def forward_par_10y(month: int) -> float:
        return 2.0 * (df(month) - df(month + 120)) / sum(df(month + 6 * i) for i in range(1, 21))

    # --- mortgage rate path (FR-2): the spread is fixed on the unshocked curve
    spread_30y, spread_15y = market.mortgage_spreads
    is_15y = row["term_years"] <= 15

    # --- prepayment model (FR-3.1, equations 3.1 to 3.13)
    p = model.prepay
    wac, wala, wam = row["wac"], int(row["wala_months"]), int(row["wam_months"])
    r = wac / 1200.0

    def smm_of(cpr: float) -> float:
        return 1.0 - (1.0 - cpr) ** (1.0 / 12.0)

    scheduled_factor = (1.0 - (1.0 + r) ** -wam) / (1.0 - (1.0 + r) ** -(wala + wam))
    ramp = p.turnover_ramp_months
    eff_months = wala - (ramp - 1) / 2.0 if wala >= ramp else wala * (wala + 1) / (2.0 * ramp)
    turnover_survival = (1.0 - smm_of(p.turnover_cpr_pct / 100.0)) ** eff_months
    survival = min(1.0, max(p.burnout_floor, row["factor"] / (scheduled_factor * turnover_survival)))
    size_mult = 1.0 + p.loan_size_elasticity * (row["avg_loan_size_k"] / p.loan_size_ref_k - 1.0)
    size_mult = min(p.loan_size_max_mult, max(p.loan_size_min_mult, size_mult))

    # --- cash flows (equations 3.14 to 3.18) and pricing (FR-4, equation 4.1)
    balance, pv, first_year_survival = row["current_face_mm"], 0.0, 1.0
    for t in range(1, wam + 1):
        mortgage = forward_par_10y(t - 1) + spread_30y + (spread_15y if is_15y else 0.0)
        x = wac - mortgage * 100.0
        age = wala + t - 1
        season = p.seasonality[(market.as_of.month + t - 1) % 12]
        lock_in = 1.0 - p.lock_in_max_reduction * min(1.0, max(0.0, -x / p.lock_in_full_incentive_pct))
        turnover = p.turnover_cpr_pct / 100.0 * min(1.0, age / ramp) * season * lock_in
        s_curve = p.refi_max_cpr_pct / 100.0 / (1.0 + math.exp(-(x - p.refi_midpoint_pct) / p.refi_slope_pct))
        refi = s_curve * min(1.0, age / p.refi_ramp_months) * size_mult * survival**p.burnout_exponent
        refi = min(refi, p.max_cpr_pct / 100.0)
        survival *= (1.0 - refi) ** (1.0 / 12.0)
        smm = smm_of(min(turnover + refi, p.max_cpr_pct / 100.0))
        if t <= 12:
            first_year_survival *= 1.0 - smm

        remaining = wam - t + 1
        payment = balance * r / (1.0 - (1.0 + r) ** -remaining)
        scheduled = payment - balance * r
        prepaid = (balance - scheduled) * smm
        cash = balance * row["coupon"] / 1200.0 + scheduled + prepaid
        pv += cash * df(t) * math.exp(-spread * t / 12.0)
        balance -= scheduled + prepaid

    return pv / row["current_face_mm"] * 100.0, (1.0 - first_year_survival) * 100.0


@pytest.mark.parametrize("position_id", ["FN30-2.5-001", "FN30-6.5-029", "G230-6.0-014", "FN15-2.5-035"])
def test_engine_price_and_speed_match_the_independent_reference(wb, position_id):
    i = wb.securities.index[wb.securities["position_id"] == position_id][0]
    row = wb.securities.loc[i]
    engine = wb.positions.loc[i]

    price, cpr = reference_price(row, wb.market, wb.model, wb.engine.base.spread[i])
    assert price == pytest.approx(wb.market.marks[position_id], abs=1e-7)
    assert price == pytest.approx(engine["price"], abs=1e-7)
    assert cpr == pytest.approx(engine["cpr_1y_pct"], abs=1e-8)


@pytest.mark.parametrize("position_id", ["FN30-2.5-001", "FN30-6.5-029"])
@pytest.mark.parametrize("shock", [-100.0, 100.0])
def test_engine_scenario_value_matches_the_independent_reference(wb, position_id, shock):
    """The same check under a parallel shock, where prepayments are re-projected."""
    i = wb.securities.index[wb.securities["position_id"] == position_id][0]
    row = wb.securities.loc[i]
    price, _ = reference_price(row, wb.market, wb.model, wb.engine.base.spread[i], parallel_bp=shock)
    engine_value = wb.run(shock).valuation.pv[i]
    assert price * row["current_face_mm"] / 100.0 == pytest.approx(engine_value, rel=1e-9)
