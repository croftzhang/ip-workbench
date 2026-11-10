"""Hedge sizing, what-if analysis and policy limits."""

import numpy as np
import pandas as pd
import pytest

from ipw.core.hedging import par_swaps, swap_sensitivities
from ipw.core.limits import Limit, evaluate


# --------------------------------------------------------------------------- hedging
@pytest.mark.parametrize(
    "target, mode, tenors",
    [
        (4.5, "duration", (5,)),
        (4.0, "duration", (10,)),
        (4.5, "krd", (2, 5, 10)),
        (3.5, "krd", (2, 5, 10, 20)),
    ],
)
def test_us3_hedge_reaches_the_duration_target(wb, target, mode, tenors):
    """US-3: after adding the proposed swaps, full revaluation gives the target within 0.05 years."""
    proposal = wb.hedge(target, mode, tenors)
    hedged = wb.what_if(add_swaps=proposal.trades)
    assert hedged.headline()["net_duration"] == pytest.approx(target, abs=0.05)
    assert hedged.headline()["net_duration"] == pytest.approx(target, abs=0.001)  # in practice exact
    assert proposal.duration_after == pytest.approx(target, abs=0.001)
    assert (proposal.trades["direction"] == "PAY_FIXED").all() and (proposal.trades["notional_mm"] > 0).all()
    assert proposal.dv01_after_k < proposal.dv01_before_k


def test_lengthening_the_book_means_receiving_fixed(wb):
    proposal = wb.hedge(6.0)
    assert proposal.trades["direction"].tolist() == ["RECEIVE_FIXED"]
    assert proposal.duration_after == pytest.approx(6.0, abs=0.001)


def test_krd_hedge_keeps_the_curve_shape_better_than_a_single_tenor(wb):
    """The key-rate hedge spreads the reduction; the one-tenor hedge piles it into one bucket."""
    single, spread = wb.hedge(4.5, "duration", (5,)), wb.hedge(4.5, "krd", (2, 5, 10))
    cut = lambda h: (h.kr01_before_k - h.kr01_after_k) / h.kr01_before_k  # noqa: E731
    assert cut(single)["5Y"] > 0.8 and cut(single)["10Y"] == pytest.approx(0.0, abs=1e-9)
    assert cut(spread)[["2Y", "5Y", "10Y"]].std() < 0.02


def test_new_par_swaps_have_zero_value_and_sensible_dv01(wb):
    swaps = par_swaps(wb.engine, (2.0, 5.0, 10.0)).assign(notional_mm=100.0)
    hedged = wb.what_if(add_swaps=swaps)
    assert np.allclose(hedged.engine.base.swap_pv[-3:], 0.0, atol=1e-9)
    dv01, kr01 = swap_sensitivities(wb.engine, swaps)
    df = wb.market.curve.df
    annuity = [0.5 * df[np.arange(6, int(t * 12) + 1, 6)].sum() for t in (2, 5, 10)]
    assert np.allclose(-dv01, 100.0 * np.array(annuity) / 1e4, rtol=0.02)  # pay fixed: DV01 = -annuity
    assert np.allclose(kr01.sum(axis=1), dv01, rtol=0.01)
    own_bucket = kr01[[0, 1, 2], [1, 2, 3]]  # 2y, 5y, 10y key rates
    assert np.allclose(own_bucket, dv01, rtol=0.02)  # a par swap loads on its own key rate


def test_hedge_argument_checks(wb):
    with pytest.raises(ValueError):
        wb.hedge(4.5, "duration", (2, 5))
    with pytest.raises(ValueError):
        wb.hedge(4.5, "magic")


# --------------------------------------------------------------------------- what-if
def test_what_if_does_not_change_the_original(wb):
    before = wb.headline()["market_value_mm"]
    dropped = wb.what_if(drop=["FN30-2.5-001"])
    assert len(dropped.securities) == len(wb.securities) - 1
    assert wb.headline()["market_value_mm"] == before
    with pytest.raises(KeyError):
        wb.what_if(drop=["NOPE"])


def test_what_if_can_add_securities(wb):
    """A hypothetical purchase has no mark, so it is priced off the coupon stack."""
    new = wb.securities[wb.securities["position_id"] == "FN30-6.5-029"].assign(position_id="NEW-6.5")
    bigger = wb.what_if(add_securities=new)
    added = bigger.positions.set_index("position_id").loc["NEW-6.5"]
    original = wb.positions.set_index("position_id").loc["FN30-6.5-029"]
    assert added["price"] == pytest.approx(wb.market.mbs_prices[("MBS_30Y", 6.5)])
    assert added["eff_duration"] == pytest.approx(original["eff_duration"], rel=0.01)
    assert bigger.headline()["face_mm"] == pytest.approx(
        wb.headline()["face_mm"] + original["current_face_mm"]
    )


def test_compare_reports_both_books(wb):
    swaps = par_swaps(wb.engine, (5.0,)).assign(notional_mm=260.0)
    table = wb.compare(wb.what_if(add_swaps=swaps))
    assert table.loc["Hedge notional ($mm)", "change"] == pytest.approx(260.0)
    assert table.loc["Net duration (years)", "change"] < 0
    assert table.loc["Limit AOCI_UP200 ($mm)", "after"] > table.loc["Limit AOCI_UP200 ($mm)", "before"]


# --------------------------------------------------------------------------- limits
def L(**kw) -> Limit:
    return Limit(id="X", name="x", metric="m", **kw)


@pytest.mark.parametrize(
    "limit, value, utilisation, status",
    [
        (L(min=3.0, max=5.0), 4.0, 0.0, "OK"),
        (L(min=3.0, max=5.0), 4.95, 0.95, "WARN"),
        (L(min=3.0, max=5.0), 5.2, 1.2, "BREACH"),
        (L(min=3.0, max=5.0), 2.8, 1.2, "BREACH"),
        (L(max=0.5), 0.25, 0.5, "OK"),
        (L(max=0.5), -0.1, 0.0, "OK"),
        (L(max=0.5), 0.6, 1.2, "BREACH"),
        (L(min=-200.0), -150.0, 0.75, "OK"),
        (L(min=-200.0), 40.0, 0.0, "OK"),
        (L(min=-200.0, warn_at=0.7), -150.0, 0.75, "WARN"),
        (L(min=-200.0), -230.0, 1.15, "BREACH"),
        (L(min=10.0), 20.0, 0.5, "OK"),
        (L(min=10.0), 8.0, 1.25, "BREACH"),
    ],
)
def test_limit_utilisation_and_status(limit, value, utilisation, status):
    result = evaluate(limit, value)
    assert result.utilisation == pytest.approx(utilisation)
    assert result.status == status


def test_limit_headroom_and_validation():
    assert evaluate(L(min=3.0, max=5.0), 4.8).headroom == pytest.approx(0.2)
    assert evaluate(L(min=-200.0), -230.0).headroom == pytest.approx(-30.0)
    with pytest.raises(ValueError):
        L()


def test_sample_book_starts_with_one_breach_and_one_warning(wb):
    """The illustrative limits are set so the limit workflow has something to do."""
    status = wb.limit_table()["status"]
    assert status["AOCI_UP200"] == "BREACH" and status["DUR_BAND"] == "WARN"
    assert (status.drop(["AOCI_UP200", "DUR_BAND"]) == "OK").all()


@pytest.mark.parametrize("tenor", [2.0, 5.0, 10.0])
def test_fix_limit_cures_the_breach_with_the_smallest_round_notional(wb, tenor):
    fix = wb.fix_limit("AOCI_UP200", tenor)
    assert fix.before.status == "BREACH" and fix.after.status != "BREACH"
    assert fix.after.value >= fix.limit.min
    notional = fix.trades["notional_mm"].iloc[0]
    assert notional % 10 == 0
    smaller = fix.trades.assign(notional_mm=notional - 10)
    assert wb.what_if(add_swaps=smaller).metric("aoci_after_tax", "up_200") < fix.limit.min
    assert all(r.status != "BREACH" for r in fix.result.limit_report())
    assert fix.carry_12m_mm < 0  # paying fixed above the short rate costs carry today


def test_fix_limit_refuses_what_it_cannot_do(wb):
    with pytest.raises(ValueError, match="not breached"):
        wb.fix_limit("NII_UP100")
    with pytest.raises(ValueError, match="does not respond to swaps"):
        wb.fix_limit("HTM_SHARE", target=50.0)
    with pytest.raises(KeyError):
        wb.fix_limit("NO_SUCH_LIMIT")
    eased = wb.fix_limit("NII_UP100", target=-15.0)  # an explicit target works on any limit
    assert eased.after.value >= -15.0


def test_unknown_metric_is_an_error(wb):
    with pytest.raises(KeyError):
        wb.metric("no_such_metric")
    with pytest.raises(ValueError):
        wb.metric("aoci_after_tax")  # needs a scenario


def test_limits_table_is_a_dataframe(wb):
    assert isinstance(wb.limit_table(), pd.DataFrame) and len(wb.limit_table()) == len(wb.limits)
