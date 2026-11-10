"""Loading and validating configuration and position files."""

import pandas as pd
import pytest

from ipw.core import config as cfg
from ipw.core.limits import load_limits
from ipw.core.scenarios import load_scenarios


def test_sample_files_load(root, wb):
    assert len(wb.securities) == 88 and len(wb.swaps) == 5
    assert wb.market.as_of.isoformat() == "2026-11-09" and wb.prior_market.as_of.isoformat() == "2026-11-06"
    assert {"base", *wb.scenarios} >= {"base", "up_100", "dn_100", "bear_steepener", "refi_wave"}
    assert wb.securities["bucket"].nunique() == 7
    spread_30y, spread_15y = wb.market.mortgage_spreads
    assert spread_30y == pytest.approx((7.18 - 4.88) / 100) and spread_15y == pytest.approx(-0.0068)


def test_find_root(root, tmp_path, monkeypatch):
    assert cfg.find_root(root) == root
    monkeypatch.chdir(root / "tests")
    assert cfg.find_root() == root  # found from a sub-folder
    with pytest.raises(FileNotFoundError):
        cfg.find_root(tmp_path)


def test_unknown_model_key_is_rejected(tmp_path):
    path = tmp_path / "model.yaml"
    path.write_text("prepay:\n  turnover_cpr: 6.5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown key"):
        cfg.load_model(path)
    path.write_text("prepay:\n  turnover_cpr_pct: 8.0\nrisk:\n  key_tenors: [2, 10]\n", encoding="utf-8")
    model = cfg.load_model(path)
    assert model.prepay.turnover_cpr_pct == 8.0 and model.risk.key_tenors == (2, 10)
    assert model.prepay.refi_max_cpr_pct == cfg.PrepayParams().refi_max_cpr_pct  # defaults fill the rest


def test_position_files_are_validated(root, tmp_path):
    good = pd.read_csv(root / "data" / "portfolio.csv")
    path = tmp_path / "portfolio.csv"

    good.drop(columns="book_price").to_csv(path, index=False)
    with pytest.raises(ValueError, match="missing column"):
        cfg.load_securities(path)

    good.assign(designation="TRADING").to_csv(path, index=False)
    with pytest.raises(ValueError, match="AFS or HTM"):
        cfg.load_securities(path)

    pd.concat([good, good.head(1)]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="unique"):
        cfg.load_securities(path)

    swaps = pd.read_csv(root / "data" / "hedges.csv")
    swaps.assign(remaining_years=2.3).to_csv(tmp_path / "hedges.csv", index=False)
    with pytest.raises(ValueError, match="multiple of 0.5"):
        cfg.load_swaps(tmp_path / "hedges.csv")
    assert len(cfg.load_swaps(tmp_path / "no_hedges.csv")) == 0  # a book without hedges is fine


def test_scenario_and_limit_files_are_validated(tmp_path):
    path = tmp_path / "scenarios.yaml"
    path.write_text("scenarios:\n  - {name: a, parallel: 100}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown keys"):
        load_scenarios(path)
    path.write_text("scenarios:\n  - {name: base, parallel_bp: 100}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="reserved"):
        load_scenarios(path)
    path.write_text("scenarios:\n  - {name: twist, curve_points_bp: {10: 50, 2: 0}}\n", encoding="utf-8")
    assert load_scenarios(path)["twist"].curve_points_bp == ((2, 0), (10, 50))

    path = tmp_path / "limits.yaml"
    path.write_text("limits:\n  - {id: A, name: a, metric: net_duration}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="needs min, max or both"):
        load_limits(path)
    path.write_text(
        "limits:\n  - {id: A, name: a, metric: net_duration, max: 5}\n"
        "  - {id: A, name: b, metric: net_duration, max: 6}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unique"):
        load_limits(path)
