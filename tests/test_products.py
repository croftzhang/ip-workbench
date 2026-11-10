"""Cash-flow construction, checked against independent textbook calculations."""

import numpy as np
import pandas as pd
import pytest

from ipw.core.curve import Curve
from ipw.core.pricing import bey, present_value, solve_rate
from ipw.core.products import FixedFloatSwap, RateEnvironment, TreasuryBond, passthrough_cashflows

HORIZON = 360
CURVE = Curve.from_quotes(
    [0.5, 1, 2, 3, 5, 7, 10, 20, 30], [4.26, 4.33, 4.56, 4.61, 4.69, 4.79, 4.88, 5.30, 5.26]
)
ENV = RateEnvironment(
    curve=CURVE,
    mortgage_30y=np.full(HORIZON, 0.07),
    mortgage_15y=np.full(HORIZON, 0.065),
    short_rate=CURVE.short_rate(HORIZON),
    as_of_month=11,
)


def reference_passthrough(balance, coupon_pct, wac_pct, wam, smm):
    """Month-by-month recursion from first principles (level payment recomputed each month)."""
    r = wac_pct / 1200.0
    rows = []
    for t in range(len(smm)):
        remaining = wam - t
        if remaining <= 0:
            rows.append((0.0, 0.0, 0.0))
            continue
        payment = balance * r / (1.0 - (1.0 + r) ** (-remaining))
        scheduled = payment - balance * r
        prepaid = (balance - scheduled) * smm[t]
        rows.append((balance * coupon_pct / 1200.0, scheduled, prepaid))
        balance -= scheduled + prepaid
    return np.array(rows).T


def test_passthrough_matches_the_month_by_month_recursion():
    rng = np.random.default_rng(7)
    smm = rng.uniform(0.0, 0.03, size=(3, HORIZON))
    balance = np.array([100.0, 55.5, 240.0])
    coupon, wac, wam = np.array([2.5, 6.0, 4.0]), np.array([3.3, 6.8, 4.7]), np.array([295, 340, 110])
    cf = passthrough_cashflows(balance, coupon, wac, wam, smm)
    for i in range(3):
        interest, scheduled, prepaid = reference_passthrough(balance[i], coupon[i], wac[i], wam[i], smm[i])
        assert np.allclose(cf.interest[i], interest, atol=1e-10)
        assert np.allclose(cf.scheduled[i], scheduled, atol=1e-10)
        assert np.allclose(cf.prepaid[i], prepaid, atol=1e-10)


def test_passthrough_returns_all_principal_and_ends_at_zero():
    smm = np.full((1, HORIZON), 0.005)
    cf = passthrough_cashflows(np.array([100.0]), np.array([3.0]), np.array([3.7]), np.array([300]), smm)
    assert cf.principal.sum() == pytest.approx(100.0)
    assert cf.balance[0, 300] == pytest.approx(0.0, abs=1e-10)
    assert np.all(cf.total[0, 300:] == 0.0)
    assert np.allclose(np.diff(cf.balance[0]), -cf.principal[0])


def test_without_prepayments_the_gross_payment_is_level():
    cf = passthrough_cashflows(
        np.array([100.0]), np.array([5.0]), np.array([5.0]), np.array([360]), np.zeros((1, HORIZON))
    )
    payment = cf.interest[0] + cf.scheduled[0]  # coupon equals WAC here, so this is the borrower payment
    assert np.allclose(payment, payment[0])
    assert payment[0] == pytest.approx(100.0 * (0.05 / 12) / (1 - (1 + 0.05 / 12) ** -360))


def _bond(coupon, months, face=100.0):
    return pd.DataFrame({"current_face_mm": [face], "coupon": [coupon], "wam_months": [months]})


def test_treasury_at_the_par_yield_prices_at_par():
    for tenor in (2, 5, 10):
        cf = TreasuryBond(HORIZON).project(_bond(CURVE.par_rate(tenor) * 100.0, tenor * 12), ENV)
        assert present_value(cf.total, CURVE.df, np.zeros(1))[0] == pytest.approx(100.0, abs=1e-9)
        assert cf.accrued[0] == 0.0


def test_treasury_between_coupon_dates_accrues_interest():
    """Maturity in 28 months: next coupon in 4 months, so 2 of 6 months have accrued."""
    cf = TreasuryBond(HORIZON).project(_bond(4.5, 28), ENV)
    assert np.flatnonzero(cf.interest[0]).tolist() == [3, 9, 15, 21, 27]
    assert cf.accrued[0] == pytest.approx(100.0 * 0.045 / 2 * 2 / 6)
    assert cf.scheduled[0, 27] == 100.0 and cf.balance[0, 27] == 100.0 and cf.balance[0, 28] == 0.0


def _swap(direction, rate, years, notional=100.0):
    return pd.DataFrame(
        {
            "direction": [direction],
            "notional_mm": [notional],
            "fixed_rate": [rate],
            "remaining_years": [years],
        }
    )


def test_swap_at_the_par_rate_is_worth_zero_and_off_market_matches_the_annuity_formula():
    product = FixedFloatSwap(HORIZON)
    value = lambda swap: present_value(product.project(swap, ENV).total, CURVE.df, np.zeros(1))[0]  # noqa: E731
    par = CURVE.par_rate(5.0) * 100.0
    assert value(_swap("PAY_FIXED", par, 5.0)) == pytest.approx(0.0, abs=1e-9)

    annuity = 0.5 * CURVE.df[np.arange(6, 61, 6)].sum()
    expected = 100.0 * (par - 3.80) / 100.0 * annuity  # paying 3.80% when the market is at par
    assert value(_swap("PAY_FIXED", 3.80, 5.0)) == pytest.approx(expected, rel=1e-10)
    assert value(_swap("RECEIVE_FIXED", 3.80, 5.0)) == pytest.approx(-expected, rel=1e-10)


def test_solve_rate_round_trips_spread_and_yield():
    cf = passthrough_cashflows(np.array([100.0, 80.0]), np.array([3.0, 6.0]), np.array([3.6, 6.7]),
                               np.array([300, 340]), np.full((2, HORIZON), 0.006))  # fmt: skip
    spread = np.array([0.0055, 0.0130])
    pv = present_value(cf.total, CURVE.df, spread)
    assert np.allclose(solve_rate(cf.total, pv, CURVE.df), spread, atol=1e-10)

    # A level annuity of 1 per month for 10 years at 6% compounded monthly.
    annuity = np.zeros((1, HORIZON))
    annuity[0, :120] = 1.0
    price = (1 - (1 + 0.06 / 12) ** -120) / (0.06 / 12)
    z = solve_rate(annuity, np.array([price]))
    assert np.exp(z[0] / 12) - 1 == pytest.approx(0.06 / 12, rel=1e-9)
    assert bey(z)[0] == pytest.approx(2 * ((1 + 0.06 / 12) ** 6 - 1), rel=1e-9)
