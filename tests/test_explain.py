"""Day-over-day explain."""

import pytest

from ipw import Workbench
from ipw.core.explain import DRIVERS


def test_drivers_add_up_to_the_change_between_the_two_closes(wb):
    ex = wb.explain()
    prior = Workbench(wb.securities, wb.swaps, wb.prior_market, wb.model)
    d_securities = wb.engine.base.pv.sum() - prior.engine.base.pv.sum()
    d_hedges = wb.engine.base.swap_pv.sum() - prior.engine.base.swap_pv.sum()

    table = ex.by_driver
    assert list(table.index) == [*DRIVERS, "Total"]
    assert table.loc["Total", "AFS"] + table.loc["Total", "HTM"] == pytest.approx(d_securities)
    assert table.loc["Total", "Hedges"] == pytest.approx(d_hedges)
    assert table.loc["Total", "Total"] == pytest.approx(d_securities + d_hedges)
    assert table.loc[DRIVERS, "Total"].sum() == pytest.approx(table.loc["Total", "Total"])
    assert ex.by_position["total_mm"].sum() == pytest.approx(d_securities)


def test_key_rate_exposure_explains_most_of_the_curve_move(wb):
    """For a move of a few bp, the linear risk report should predict the curve P&L closely."""
    table = wb.explain().by_driver["Total"]
    first_order, residual = table[DRIVERS[0]], table[DRIVERS[1]]
    assert abs(residual) < 0.05 * abs(first_order)
    by_key = wb.explain().by_key_rate
    assert by_key["pnl_mm"].sum() == pytest.approx(first_order)
    assert (by_key["move_bp"] > 0).all() and first_order < 0  # yields rose, the book lost


def test_spread_driver_matches_the_constructed_widening(wb):
    """The sample prior close was built with MBS spreads 2bp tighter."""
    ex = wb.explain()
    mbs = ex.by_position[ex.by_position["bucket"] != "UST"]
    assert mbs["spread_move_bp"].mean() == pytest.approx(2.0, abs=0.5)
    assert (ex.by_position.loc[ex.by_position["bucket"] == "UST", "spread_mm"] == 0).all()
    assert ex.by_driver.loc["MBS spreads", "Hedges"] == 0.0
    assert ex.by_driver.loc["MBS spreads", "Total"] < 0
    assert ex.mortgage_rate_move_bp == pytest.approx(4.0) and ex.mortgage_basis_move_bp == pytest.approx(-3.0)


def test_explain_needs_a_prior_close(wb):
    today_only = Workbench(wb.securities, wb.swaps, wb.market, wb.model)
    with pytest.raises(FileNotFoundError):
        today_only.explain()
