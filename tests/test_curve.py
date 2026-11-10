import numpy as np
import pytest

from ipw.core.curve import GRID_YEARS, Curve, key_rate_shock, parallel_shock, piecewise_shock

TENORS = [0.5, 1, 2, 3, 5, 7, 10, 20, 30]
YIELDS = [4.26, 4.33, 4.56, 4.61, 4.69, 4.79, 4.88, 5.30, 5.26]


@pytest.fixture(scope="module")
def curve() -> Curve:
    return Curve.from_quotes(TENORS, YIELDS)


def test_bootstrap_reprices_par_bonds(curve):
    """A bond paying the quoted par yield must price at exactly 100."""
    for tenor, quote in zip(TENORS, YIELDS):
        months = np.arange(6, int(tenor * 12) + 1, 6)
        price = (quote / 2.0 * curve.df[months]).sum() + 100.0 * curve.df[months[-1]]
        assert price == pytest.approx(100.0, abs=1e-10)
        assert curve.par_rate(tenor) * 100.0 == pytest.approx(quote, abs=1e-10)


def test_discount_factors_are_positive_and_decreasing(curve):
    assert curve.df[0] == 1.0
    assert np.all(np.diff(curve.df) < 0)
    assert np.all(curve.df > 0)


def test_forward_rate_is_constant_within_a_half_year(curve):
    short = curve.short_rate(12)
    assert np.allclose(short[:6], short[0]) and np.allclose(short[6:], short[6])


def test_spot_and_forward_par_rates_agree_at_time_zero(curve):
    assert curve.forward_par(10.0, 24)[0] == pytest.approx(curve.par_rate(10.0))


def test_parallel_shift_moves_every_par_rate_by_the_shock(curve):
    shifted = curve.shifted(parallel_shock(50))
    for tenor in (1, 2, 5, 10, 30):
        assert (shifted.par_rate(tenor) - curve.par_rate(tenor)) * 1e4 == pytest.approx(50.0, abs=1e-9)
    assert np.all(shifted.df[1:] < curve.df[1:])


def test_key_rate_shocks_sum_to_a_parallel_shift():
    keys = (1.0, 2.0, 5.0, 10.0, 20.0, 30.0)
    total = sum(key_rate_shock(keys, k, 25.0) for k in range(len(keys)))
    assert np.allclose(total, 25.0)
    assert np.all(key_rate_shock(keys, 2, 25.0)[GRID_YEARS <= 2.0] == 0.0)  # 5y hat is zero at and below 2y


def test_piecewise_shock_interpolates_and_is_flat_outside():
    shock = piecewise_shock([(2, 0), (10, 50), (30, 75)])
    at = lambda years: shock[np.isclose(GRID_YEARS, years)][0]  # noqa: E731
    assert at(1.0) == 0.0 and at(6.0) == pytest.approx(25.0) and at(10.0) == 50.0 and at(40.0) == 75.0


def test_quotes_must_be_increasing_in_tenor():
    with pytest.raises(ValueError):
        Curve.from_quotes([1, 1, 2], [4.0, 4.1, 4.2])
