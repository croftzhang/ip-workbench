"""AOCI and net interest income."""

from dataclasses import replace

import pytest

from ipw import Workbench


def test_us4_htm_positions_never_reach_aoci(wb):
    """US-4: AOCI moves only with AFS securities and their hedges."""
    run = wb.run("up_200")
    assert run.aoci.afs_securities == pytest.approx(run.d_afs)
    assert run.aoci.hedges == pytest.approx(run.d_hedges)  # every swap in the sample book hedges AFS
    assert run.aoci.pre_tax == pytest.approx(run.d_afs + run.d_hedges)
    assert run.aoci.after_tax == pytest.approx(run.aoci.pre_tax * (1 - wb.model.balance_sheet.tax_rate))

    htm = wb.securities.loc[wb.securities["designation"] == "HTM", "position_id"]
    without_htm = wb.what_if(drop=htm)
    assert without_htm.run("up_200").aoci.pre_tax == pytest.approx(run.aoci.pre_tax)
    assert abs(run.d_htm) > abs(run.d_afs)  # the larger loss is the one equity does not see


def test_us4_breach_is_flagged(wb):
    table = wb.limit_table()
    assert table.loc["AOCI_UP200", "status"] == "BREACH"
    assert table.loc["AOCI_UP200", "value"] == pytest.approx(wb.run("up_200").aoci.after_tax)


def test_hedges_reduce_aoci_sensitivity(wb):
    unhedged = Workbench(wb.securities, wb.swaps.iloc[:0], wb.market, wb.model)
    assert unhedged.run(200).aoci.pre_tax < wb.run(200).aoci.pre_tax < 0


def test_nii_components_add_up(wb):
    nii = wb.run("base").nii
    assert nii.interest_income == pytest.approx(nii.coupon_income + nii.amortization)
    assert nii.total == pytest.approx(
        nii.interest_income + nii.reinvestment + nii.hedge_carry + nii.funding_cost
    )
    table = wb.nii_table()
    assert table.loc["total", "base"] == pytest.approx(nii.total)
    assert nii.funding_cost < 0 < nii.coupon_income
    assert nii.amortization < 0  # the book is carried at a net premium


def test_interest_income_is_close_to_book_yield_on_average_balance(wb):
    """Sanity check of the effective-yield roll: income ~ book yield x average amortised cost."""
    headline, nii = wb.headline(), wb.run("base").nii
    principal_12m = wb.engine.base.cash.principal[:, :12].sum()
    average_balance = headline["book_value_mm"] - 0.5 * principal_12m
    assert nii.interest_income == pytest.approx(headline["book_yield_pct"] / 100 * average_balance, rel=0.03)


def test_funding_beta_drives_the_rate_sensitivity_of_funding(wb):
    base, up = wb.run("base").nii, wb.run(100).nii
    bs = wb.model.balance_sheet
    expected = -bs.funding_beta * 0.01 * wb.headline()["book_value_mm"]
    # A 100bp move in semi-annual par yields is 100bp in the monthly forward rate to within compounding.
    assert up.funding_cost - base.funding_cost == pytest.approx(expected, rel=0.02)

    no_beta = replace(wb.model, balance_sheet=replace(bs, funding_beta=0.0))
    flat = Workbench(wb.securities, wb.swaps, wb.market, no_beta)
    assert flat.run(100).nii.funding_cost == pytest.approx(flat.run("base").nii.funding_cost)
    assert (
        flat.run(100).nii.total > flat.run("base").nii.total
    )  # without funding pass-through, higher rates help


def test_pay_fixed_swaps_earn_more_carry_when_rates_rise(wb):
    base, up = wb.run("base").nii, wb.run(100).nii
    assert up.hedge_carry - base.hedge_carry == pytest.approx(0.01 * wb.swaps["notional_mm"].sum(), rel=0.02)


def test_faster_prepayments_cut_the_yield_of_premium_bonds(wb):
    """Book yield of a bond carried above par falls when principal comes back sooner."""
    from ipw.core.balance_sheet import book_yield

    premium = (wb.securities["book_price"] > 101).to_numpy() & wb.engine._is_mbs
    slow = book_yield(wb.run("prepay_slow").valuation, wb.securities)[premium]
    fast = book_yield(wb.run("prepay_fast").valuation, wb.securities)[premium]
    assert (fast < slow).all()
