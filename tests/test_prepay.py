import numpy as np
import pytest

from ipw.core.config import PrepayParams
from ipw.core.prepay import PrepayAdjustments, PrepayModel, cpr_to_smm

P = PrepayParams()
MODEL = PrepayModel(P)


def project(wac=7.0, wala=40, wam=318, factor=0.90, size=300.0, rate=0.06, months=24, as_of=11, adj=None):
    """One pool on a flat mortgage-rate path; returns (cpr, turnover, refi) vectors."""
    one = lambda x: np.array([float(x)])  # noqa: E731
    smm, turnover, refi = MODEL.project(
        one(wac), one(wala), one(wam), one(factor), one(size), np.full((1, months), rate), as_of,
        adj or PrepayAdjustments(),
    )  # fmt: skip
    return 1.0 - (1.0 - smm[0]) ** 12, turnover[0], refi[0]


def test_first_month_matches_a_hand_calculation():
    """WAC 7.0 vs 6.0 market: incentive +1.00 sits at the S-curve midpoint."""
    _, turnover, refi = project(wac=7.0, rate=0.06, wala=40, size=300.0, factor=1.0, as_of=11)
    december = P.seasonality[11]
    assert turnover[0] == pytest.approx(0.065 * december)  # seasoned, no lock-in
    assert refi[0] == pytest.approx(0.45 * 0.5)  # half the plateau; unburned, average loan size


def test_s_curve_is_increasing_in_incentive():
    speeds = MODEL.s_curve(np.linspace(-3, 3, 25))
    total = speeds["turnover_cpr"] + speeds["refi_cpr"]
    assert np.all(np.diff(total) >= 0)
    assert speeds["refi_cpr"][0] < 0.001 and speeds["refi_cpr"][-1] > 0.44


def test_lock_in_cuts_turnover_and_saturates():
    assert MODEL.lock_in(np.array([0.5, 0.0])).tolist() == [1.0, 1.0]
    assert MODEL.lock_in(np.array([-1.25]))[0] == pytest.approx(1.0 - 0.5 * P.lock_in_max_reduction)
    assert MODEL.lock_in(np.array([-2.5, -4.0])).tolist() == pytest.approx([0.6, 0.6])


def test_new_loans_prepay_slower_than_seasoned_loans():
    new, _, _ = project(wala=2)
    seasoned, _, _ = project(wala=40)
    assert new[0] < seasoned[0]


def test_larger_loans_refinance_faster_within_bounds():
    tiny, small, large = MODEL.loan_size_multiplier(np.array([60.0, 150.0, 600.0]))
    assert tiny == P.loan_size_min_mult and large == P.loan_size_max_mult
    assert small == pytest.approx(1.0 + P.loan_size_elasticity * (150.0 / P.loan_size_ref_k - 1.0))
    assert MODEL.loan_size_multiplier(np.array([P.loan_size_ref_k]))[0] == 1.0


def test_burnout_damps_refinancing_over_time_and_for_paid_down_pools():
    _, _, refi = project(months=36)
    assert refi[35] < refi[0]  # same incentive, fewer rate-sensitive borrowers left
    _, _, fresh = project(factor=0.95)
    _, _, burned = project(factor=0.40)
    assert burned[0] < fresh[0]


def test_initial_refi_survival_is_bounded():
    one = lambda x: np.array([float(x)])  # noqa: E731
    survival = MODEL.initial_refi_survival(one(4.5), one(88), one(272), np.array([0.05, 0.45, 0.99]))
    assert survival.min() >= P.burnout_floor and survival.max() <= 1.0
    assert survival[0] == P.burnout_floor and survival[2] == 1.0


def test_seasonality_follows_the_calendar():
    """Valuation in November: month 1 is December, month 7 is June (the seasonal peak)."""
    _, turnover, _ = project(wac=6.0, rate=0.06, wala=60, months=12, as_of=11)
    assert turnover[0] / turnover[6] == pytest.approx(P.seasonality[11] / P.seasonality[5])


def test_scenario_multipliers_scale_each_component():
    _, t0, r0 = project()
    _, t1, r1 = project(adj=PrepayAdjustments(refi=1.25, turnover=0.75))
    assert t1[0] == pytest.approx(0.75 * t0[0]) and r1[0] == pytest.approx(1.25 * r0[0])


def test_speeds_are_capped_and_convert_to_smm():
    cpr, _, _ = project(wac=12.0, rate=0.03, adj=PrepayAdjustments(refi=3.0))
    assert cpr.max() == pytest.approx(P.max_cpr_pct / 100.0)
    assert 1.0 - (1.0 - cpr_to_smm(np.array([0.06]))[0]) ** 12 == pytest.approx(0.06)


def test_seasonality_needs_twelve_months():
    with pytest.raises(ValueError):
        PrepayModel(PrepayParams(seasonality=(1.0, 1.0)))
