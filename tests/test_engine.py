"""Valuation, calibration, risk and scenarios on the sample portfolio."""

import time

import numpy as np
import pytest

from ipw.core.curve import parallel_shock
from ipw.core.scenarios import BASE, Scenario


def test_calibration_reprices_every_mbs_to_its_mark(wb):
    pos = wb.positions
    mbs = pos["asset_type"].str.startswith("MBS")
    marks = pos.loc[mbs, "position_id"].map(wb.market.marks)
    assert marks.notna().all()
    assert np.allclose(pos.loc[mbs, "price"], marks, atol=1e-8)
    assert pos.loc[mbs, "zv_spread_bp"].between(20, 200).all()  # implied spreads stay in a sane range
    assert (pos.loc[~mbs, "zv_spread_bp"] == 0).all()  # Treasuries sit on the curve


def test_price_sources_fall_back_in_order(wb):
    """Own mark, then the coupon-stack quote, then the default spread."""
    from dataclasses import replace

    from ipw import Workbench

    pid, sector, coupon = "FN30-6.5-029", "MBS_30Y", 6.5
    row = wb.positions.set_index("position_id").loc[pid]
    assert row["price"] == pytest.approx(wb.market.marks[pid])

    no_marks = Workbench(wb.securities, wb.swaps, replace(wb.market, marks={}), wb.model)
    row = no_marks.positions.set_index("position_id").loc[pid]
    assert row["price"] == pytest.approx(wb.market.mbs_prices[(sector, coupon)])

    no_prices = Workbench(wb.securities, wb.swaps, replace(wb.market, marks={}, mbs_prices={}), wb.model)
    spreads = no_prices.positions.loc[no_prices.positions["asset_type"].str.startswith("MBS"), "zv_spread_bp"]
    assert np.allclose(spreads, wb.model.default_zv_spread_bp)


def test_market_value_reconciles_to_face_book_and_unrealized(wb):
    total = wb.summary(None).loc["Total"]
    pos = wb.positions
    assert total["current_face_mm"] == pytest.approx(10_000.0)
    assert total["market_value_mm"] == pytest.approx((pos["price"] * pos["current_face_mm"]).sum() / 100.0)
    assert total["unrealized_mm"] == pytest.approx(total["market_value_mm"] - total["book_value_mm"])
    by_designation = wb.summary("designation")
    assert by_designation.loc[["AFS", "HTM"], "market_value_mm"].sum() == pytest.approx(
        total["market_value_mm"]
    )


def test_base_scenario_changes_nothing(wb):
    again = wb.engine.value(BASE)
    assert np.allclose(again.pv, wb.engine.base.pv, rtol=0, atol=1e-9)
    run = wb.run("base")
    assert run.d_securities == 0.0 and run.d_hedges == 0.0 and run.aoci.pre_tax == 0.0


def test_us1_standard_shocks_run_within_five_seconds(root):
    """US-1: results for the standard parallel shocks in under 5 seconds, from a cold start."""
    from ipw import Workbench

    start = time.perf_counter()
    table = Workbench.load(root).scenario_table([-200, -100, -50, -25, 25, 50, 100, 200])
    assert time.perf_counter() - start < 5.0
    assert (table.loc[["up_25", "up_50", "up_100", "up_200"], "d_value_mm"] < 0).all()
    assert (table.loc[["dn_25", "dn_50", "dn_100", "dn_200"], "d_value_mm"] > 0).all()
    assert table["d_value_mm"].is_monotonic_decreasing


def test_us2_key_rate_durations_add_up_to_effective_duration(wb):
    """US-2: key-rate durations sum to effective duration within 5% (in practice far closer)."""
    krd = wb.key_rate_table("designation")
    headline = wb.headline()
    assert krd.loc["Securities", "Sum"] == pytest.approx(headline["securities_duration"], rel=0.05)
    assert krd.loc["Net", "Sum"] == pytest.approx(headline["net_duration"], rel=0.05)
    assert krd.loc["Securities", "Sum"] == pytest.approx(headline["securities_duration"], rel=0.005)
    per_position = wb.positions.filter(like="kr01_").sum(axis=1)
    assert np.allclose(per_position, wb.positions["dv01_k"], rtol=0.02)


def test_duration_predicts_small_moves_and_convexity_the_error(wb):
    risk, base = wb.risk, wb.engine.base
    up10 = wb.engine.value(BASE, parallel_shock(10.0))
    predicted = -risk.dv01.sum() * 10.0
    assert (up10.pv - base.pv).sum() == pytest.approx(predicted, rel=0.01)

    up100 = wb.run(100)
    duration, convexity = risk.duration(), risk.convexity()
    second_order = (-duration + 0.5 * convexity) / 100.0 * base.pv.sum()
    assert up100.d_securities == pytest.approx(second_order, rel=0.02)


def test_treasury_effective_duration_matches_modified_duration(wb):
    """For option-free bonds, effective duration is close to yield-based modified duration."""
    pos = wb.positions
    ust = pos[pos["asset_type"] == "UST"]
    cash = wb.engine.base.cash.total[ust.index]
    years = np.arange(1, cash.shape[1] + 1) / 12.0
    y = ust["yield_pct"].to_numpy()[:, None] / 100.0
    pv = cash / (1 + y / 2) ** (2 * years)
    modified = (pv * years).sum(axis=1) / pv.sum(axis=1) / (1 + y[:, 0] / 2)
    assert np.allclose(ust["eff_duration"], modified, rtol=0.02)


def test_mortgage_option_shows_up_where_it_should(wb):
    """Coupons near the refinancing threshold are negatively convex; deep discounts are not."""
    risk = wb.risk_table("bucket")
    assert risk.loc["30Y high (>=5.0)", "eff_convexity"] < 0
    assert risk.loc["30Y low (<=3.0)", "eff_convexity"] > 0
    prepay = wb.prepay_table()
    high, low = prepay.loc["30Y high (>=5.0)"], prepay.loc["30Y low (<=3.0)"]
    assert high["cpr_-100bp"] > 2 * high["cpr_base"]  # a rally pulls them into the money
    assert low["cpr_-100bp"] == pytest.approx(low["cpr_base"], abs=0.1)  # still locked in
    assert wb.run(-100).net_duration < wb.run("base").net_duration  # the book shortens in a rally


def test_spread_and_prepayment_stresses_have_the_expected_sign(wb):
    widen = wb.run("basis_widen_25")
    assert widen.d_securities < 0 and widen.d_hedges == 0.0
    ust = (wb.positions["asset_type"] == "UST").to_numpy()
    assert np.allclose((widen.valuation.pv - wb.engine.base.pv)[ust], 0.0)  # Treasuries have no MBS spread
    # A book that trades below par gains when principal comes back sooner.
    assert wb.run("prepay_fast").d_securities > 0 > wb.run("prepay_slow").d_securities


def test_scenario_resolution(wb):
    assert wb.scenario("base") is BASE and wb.scenario(0) is BASE
    assert wb.scenario("up_100") == wb.scenarios["up_100"]
    assert wb.scenario("-75").parallel_bp == -75 and wb.scenario("dn_75").parallel_bp == -75
    assert wb.scenario(Scenario.parallel(30)).name == "up_30"
    with pytest.raises(KeyError):
        wb.scenario("no_such_scenario")


def test_scenario_detail_adds_up(wb):
    detail = wb.scenario_detail("up_200", "bucket")
    assert detail.loc["Total", "d_value_mm"] == pytest.approx(wb.run("up_200").d_securities)
    assert detail.drop(index="Total")["d_value_mm"].sum() == pytest.approx(detail.loc["Total", "d_value_mm"])
    assert detail.drop(index="Total")["share_pct"].sum() == pytest.approx(100.0)


def test_position_drill_down(wb):
    details, flows = wb.position("FN30-2.5-001")
    assert details["position_id"] == "FN30-2.5-001" and details["designation"] == "HTM"
    assert flows[["scheduled_mm", "prepaid_mm"]].to_numpy().sum() == pytest.approx(details["current_face_mm"])
    with pytest.raises(KeyError):
        wb.position("NOPE")


def test_unknown_asset_type_is_rejected(wb):
    from ipw.core.engine import Engine

    bad = wb.securities.copy()
    bad.loc[0, "asset_type"] = "CMBS"
    with pytest.raises(ValueError, match="No product registered"):
        Engine(bad, wb.swaps, wb.market, wb.model)


def test_unknown_grouping_is_rejected_everywhere(wb):
    for call in (wb.summary, wb.risk_table, wb.key_rate_table, wb.prepay_table):
        with pytest.raises(ValueError, match="cannot group by"):
            call(by="colour")
    with pytest.raises(ValueError, match="cannot group by"):
        wb.scenario_detail("up_100", by="colour")
