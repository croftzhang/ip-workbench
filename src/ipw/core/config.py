"""Typed configuration and market data loaded from ``config/`` and ``data/``.

YAML keeps market conventions (percent, basis points, $mm). Conversion to
decimals happens next to the formula that needs it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from datetime import date
from functools import cached_property
from pathlib import Path

import pandas as pd
import yaml

from ipw.core.curve import Curve

SECURITY_COLUMNS = [
    "position_id", "asset_type", "agency", "term_years", "coupon", "wac", "orig_year",
    "wala_months", "wam_months", "original_face_mm", "factor", "current_face_mm",
    "book_price", "designation", "avg_loan_size_k",
]  # fmt: skip
SWAP_COLUMNS = [
    "swap_id", "direction", "notional_mm", "fixed_rate", "remaining_years", "hedged_book",
]  # fmt: skip


# --------------------------------------------------------------------------- model
@dataclass(frozen=True)
class PrepayParams:
    """Prepayment model parameters (docs/MODEL.md section 3). Speeds in % CPR."""

    turnover_cpr_pct: float = 6.5
    turnover_ramp_months: int = 30
    lock_in_max_reduction: float = 0.40
    lock_in_full_incentive_pct: float = 2.5
    refi_max_cpr_pct: float = 45.0
    refi_midpoint_pct: float = 1.00
    refi_slope_pct: float = 0.35
    refi_ramp_months: int = 9
    loan_size_ref_k: float = 300.0
    loan_size_elasticity: float = 0.40
    loan_size_min_mult: float = 0.75
    loan_size_max_mult: float = 1.25
    burnout_exponent: float = 2.0
    burnout_floor: float = 0.20
    max_cpr_pct: float = 75.0
    seasonality: tuple[float, ...] = (
        0.75, 0.77, 0.95, 1.03, 1.11, 1.18, 1.16, 1.15, 1.04, 1.01, 0.95, 0.90,
    )  # fmt: skip


@dataclass(frozen=True)
class RiskParams:
    bump_bp: float = 25.0
    key_tenors: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 20.0, 30.0)


@dataclass(frozen=True)
class BalanceSheetParams:
    """Assumptions behind the AOCI and 12-month net interest income numbers."""

    tax_rate: float = 0.24
    funding_rate_pct: float = 2.60
    funding_beta: float = 0.40
    reinvest_tenor_years: float = 5.0
    reinvest_spread_bp: float = 60.0
    nii_horizon_months: int = 12


@dataclass(frozen=True)
class ModelConfig:
    horizon_months: int = 360
    default_zv_spread_bp: float = 60.0
    prepay: PrepayParams = field(default_factory=PrepayParams)
    risk: RiskParams = field(default_factory=RiskParams)
    balance_sheet: BalanceSheetParams = field(default_factory=BalanceSheetParams)


def _build(cls, data: dict | None, where: str):
    """Instantiate a config dataclass, rejecting keys it does not know."""
    data = dict(data or {})
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {sorted(unknown)}; allowed: {sorted(known)}")
    return cls(**{k: tuple(v) if isinstance(v, list) else v for k, v in data.items()})


def load_model(path: Path) -> ModelConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sections = {"prepay": PrepayParams, "risk": RiskParams, "balance_sheet": BalanceSheetParams}
    built = {k: _build(cls, raw.pop(k, None), f"{path.name}:{k}") for k, cls in sections.items()}
    return _build(ModelConfig, {**raw, **built}, path.name)


# --------------------------------------------------------------------------- market
@dataclass(frozen=True)
class Market:
    """One close: Treasury par curve, primary mortgage rates and MBS prices.

    ``marks`` are position-level prices (the normal case: every holding has an
    end-of-day mark). ``mbs_prices`` is a coupon stack used for anything
    without a mark, for example a hypothetical purchase in a what-if.
    """

    as_of: date
    curve: Curve
    mortgage_rate_30y_pct: float
    mortgage_rate_15y_pct: float
    mbs_prices: dict[tuple[str, float], float] = field(default_factory=dict)
    marks: dict[str, float] = field(default_factory=dict)
    quote_tenors: tuple[float, ...] = ()
    quote_yields_pct: tuple[float, ...] = ()

    @cached_property
    def mortgage_spreads(self) -> tuple[float, float]:
        """(30y mortgage rate - 10y par yield, 15y rate - 30y rate), decimal.

        Held constant along the forward path and across curve scenarios.
        """
        spread_30y = self.mortgage_rate_30y_pct / 100.0 - self.curve.par_rate(10.0)
        return spread_30y, (self.mortgage_rate_15y_pct - self.mortgage_rate_30y_pct) / 100.0

    def price(self, position_id: str, asset_type: str, coupon: float) -> float | None:
        """Clean price for a position: its own mark, else the quote for its coupon, else None."""
        if position_id in self.marks:
            return self.marks[position_id]
        return self.mbs_prices.get((asset_type, round(float(coupon), 3)))


def load_marks(path: Path, as_of: date) -> dict[str, float]:
    """Position marks for one date from a long file with columns as_of, position_id, price."""
    if not path.is_file():
        return {}
    frame = pd.read_csv(path, dtype={"as_of": str, "position_id": str})
    _check_columns(frame, ["as_of", "position_id", "price"], path.name)
    day = frame[frame["as_of"] == as_of.isoformat()]
    return dict(zip(day["position_id"], day["price"].astype(float)))


def load_market(path: Path, marks_path: Path | None = None) -> Market:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    par = raw["par_curve"]
    prices = {
        (sector, round(float(coupon), 3)): float(px)
        for sector, stack in (raw.get("mbs_prices") or {}).items()
        for coupon, px in stack.items()
    }
    as_of = raw["as_of"] if isinstance(raw["as_of"], date) else date.fromisoformat(raw["as_of"])
    return Market(
        as_of=as_of,
        curve=Curve.from_quotes(par["tenors_years"], par["yields_pct"]),
        mortgage_rate_30y_pct=float(raw["mortgage_rates_pct"]["rate_30y"]),
        mortgage_rate_15y_pct=float(raw["mortgage_rates_pct"]["rate_15y"]),
        mbs_prices=prices,
        marks=load_marks(marks_path, as_of) if marks_path else {},
        quote_tenors=tuple(float(t) for t in par["tenors_years"]),
        quote_yields_pct=tuple(float(y) for y in par["yields_pct"]),
    )


# --------------------------------------------------------------------------- positions
def _check_columns(frame: pd.DataFrame, required: list[str], name: str) -> None:
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise ValueError(f"{name}: missing column(s) {missing}")


def load_securities(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    _check_columns(frame, SECURITY_COLUMNS, path.name)
    if frame["position_id"].duplicated().any():
        raise ValueError(f"{path.name}: position_id must be unique")
    bad = set(frame["designation"]) - {"AFS", "HTM"}
    if bad:
        raise ValueError(f"{path.name}: designation must be AFS or HTM, found {sorted(bad)}")
    return prepare_securities(frame)


def prepare_securities(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the derived columns the engine and the reports rely on."""
    frame = frame.reset_index(drop=True).copy()
    frame["book_value_mm"] = frame["current_face_mm"] * frame["book_price"] / 100.0
    frame["bucket"] = [_bucket(a, c) for a, c in zip(frame["asset_type"], frame["coupon"])]
    return frame


BUCKET_ORDER = [
    f"{term} {band}" for term in ("30Y", "15Y") for band in ("low (<=3.0)", "mid (3.5-4.5)", "high (>=5.0)")
]


def _bucket(asset_type: str, coupon: float) -> str:
    """Coarse coupon bucket used as the default grouping in reports."""
    if not asset_type.startswith("MBS"):
        return asset_type
    band = "low (<=3.0)" if coupon <= 3.0 else "mid (3.5-4.5)" if coupon <= 4.5 else "high (>=5.0)"
    return f"{asset_type[4:]} {band}"


def group_order(labels, by: str | None) -> list:
    """Display order for group labels: buckets in portfolio order, everything else sorted."""
    labels = list(dict.fromkeys(labels))
    if by == "bucket":
        rank = {b: i for i, b in enumerate(BUCKET_ORDER)}
        return sorted(labels, key=lambda x: (rank.get(x, len(rank)), str(x)))
    return sorted(labels)


def load_swaps(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path) if path.is_file() else pd.DataFrame(columns=SWAP_COLUMNS)
    _check_columns(frame, SWAP_COLUMNS, path.name)
    bad = set(frame["direction"]) - {"PAY_FIXED", "RECEIVE_FIXED"}
    if bad:
        raise ValueError(f"{path.name}: direction must be PAY_FIXED or RECEIVE_FIXED")
    if ((frame["remaining_years"] * 2) % 1 != 0).any():
        raise ValueError(f"{path.name}: remaining_years must be a multiple of 0.5")
    return frame.reset_index(drop=True)


# --------------------------------------------------------------------------- root folder
def find_root(start: str | Path | None = None) -> Path:
    """Locate the folder that holds ``config/`` and ``data/``.

    Order: explicit argument, ``IPW_HOME``, the current directory and its
    parents, then the repository this package was installed from (editable).
    """

    def is_root(p: Path) -> bool:
        return (p / "config" / "market.yaml").is_file() and (p / "data" / "portfolio.csv").is_file()

    if start is not None:
        root = Path(start).expanduser().resolve()
        if not is_root(root):
            raise FileNotFoundError(f"{root} does not contain config/market.yaml and data/portfolio.csv")
        return root
    cwd = Path.cwd()
    candidates = [Path(os.environ["IPW_HOME"])] if os.environ.get("IPW_HOME") else []
    candidates += [cwd, *cwd.parents, Path(__file__).resolve().parents[3]]
    for candidate in candidates:
        if is_root(candidate):
            return candidate.resolve()
    raise FileNotFoundError(
        "Could not find config/market.yaml and data/portfolio.csv. "
        "Run from the repository folder, pass --root, or set IPW_HOME."
    )
