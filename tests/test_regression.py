"""Regression test: headline numbers of the sample book against stored values.

Any change to the engine, the model parameters or the sample data that moves
these numbers fails this test, so a change in results is always a decision
and never an accident. After an intended change, refresh the stored values:

    bash:        IPW_UPDATE_GOLDEN=1 pytest tests/test_regression.py
    PowerShell:  $env:IPW_UPDATE_GOLDEN=1; pytest tests/test_regression.py; Remove-Item Env:IPW_UPDATE_GOLDEN

and review the diff of tests/golden.json before committing it.
"""

import json
import os
from pathlib import Path

import pytest

GOLDEN = Path(__file__).with_name("golden.json")


def snapshot(wb) -> dict[str, float]:
    headline = wb.headline()
    values = {f"headline.{k}": v for k, v in headline.items()}
    for name in ("dn_200", "dn_100", "up_100", "up_200", "bear_steepener", "basis_widen_25", "refi_wave"):
        run = wb.run(name)
        values[f"{name}.d_securities_mm"] = run.d_securities
        values[f"{name}.d_hedges_mm"] = run.d_hedges
        values[f"{name}.aoci_after_tax_mm"] = run.aoci.after_tax
        values[f"{name}.nii_mm"] = run.nii.total
        values[f"{name}.net_duration"] = run.net_duration
    for result in wb.limit_report():
        values[f"limit.{result.limit.id}"] = result.value
    for tenor, value in wb.key_rate_table(None, unit="k").loc["Net"].items():
        values[f"net_kr01_k.{tenor}"] = value
    values["explain.total_mm"] = wb.explain().by_driver.loc["Total", "Total"]
    return {k: round(float(v), 6) for k, v in values.items()}


def test_us1_results_match_stored_values(wb):
    """US-1: scenario results match the regression values."""
    actual = snapshot(wb)
    if os.environ.get("IPW_UPDATE_GOLDEN"):
        GOLDEN.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")
        pytest.skip("golden values rewritten")
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert actual.keys() == expected.keys()
    drift = {
        k: (expected[k], actual[k])
        for k in expected
        if actual[k] != pytest.approx(expected[k], rel=1e-6, abs=1e-6)
    }
    assert not drift, f"results moved (expected, actual): {drift}"
