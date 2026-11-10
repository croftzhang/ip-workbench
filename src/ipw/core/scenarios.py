"""Scenario definitions: instantaneous shocks to curve, spreads and prepayment behaviour."""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

import numpy as np
import yaml

from ipw.core.curve import parallel_shock, piecewise_shock


@dataclass(frozen=True)
class Scenario:
    """An instantaneous shock applied to today's market.

    Curve shocks move Treasury par yields; mortgage rates follow the 10-year
    point one for one. ``mortgage_spread_bp`` moves the primary mortgage rate
    on top of that (prepayments only). ``zv_spread_bp`` moves the discount
    spread of MBS (valuation only). The multipliers stress the prepayment model.
    """

    name: str
    description: str = ""
    parallel_bp: float = 0.0
    curve_points_bp: tuple[tuple[float, float], ...] = ()
    zv_spread_bp: float = 0.0
    mortgage_spread_bp: float = 0.0
    refi_multiplier: float = 1.0
    turnover_multiplier: float = 1.0

    def curve_shock(self) -> np.ndarray:
        shock = parallel_shock(self.parallel_bp)
        if self.curve_points_bp:
            shock = shock + piecewise_shock(self.curve_points_bp)
        return shock

    @classmethod
    def parallel(cls, bp: float) -> Scenario:
        bp = float(bp)
        if bp == 0:
            return BASE
        name = f"{'up' if bp > 0 else 'dn'}_{abs(bp):g}"
        return cls(name=name, description=f"Parallel {bp:+g}bp", parallel_bp=bp)


BASE = Scenario(name="base", description="Current market, forward curve realised")


def load_scenarios(path: Path) -> dict[str, Scenario]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    known = {f.name for f in fields(Scenario)}
    out: dict[str, Scenario] = {}
    for item in raw.get("scenarios", []):
        unknown = set(item) - known
        if unknown:
            raise ValueError(f"{path.name}: scenario {item.get('name')!r} has unknown keys {unknown}")
        item = dict(item)
        if "curve_points_bp" in item:
            item["curve_points_bp"] = tuple(sorted(item["curve_points_bp"].items()))
        scenario = Scenario(**item)
        if scenario.name in out or scenario.name == BASE.name:
            raise ValueError(f"{path.name}: duplicate or reserved scenario name {scenario.name!r}")
        out[scenario.name] = scenario
    return out
