"""Policy limits: definitions, utilisation and status.

A limit names a metric (computed by the workbench) and a floor, a cap or
both. Utilisation is how much of the allowance is used:

* cap only      value / max
* floor only    value / min   (for negative floors such as "loss no worse than -150")
* band          distance from the centre of the band / half its width

Status is BREACH outside the limit, WARN at or above ``warn_at`` utilisation,
otherwise OK.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Limit:
    id: str
    name: str
    metric: str
    scenario: str | None = None  # scenario the metric is measured under, if any
    unit: str = ""
    min: float | None = None
    max: float | None = None
    warn_at: float = 0.90
    policy_ref: str = ""
    description: str = ""

    def __post_init__(self):
        if self.min is None and self.max is None:
            raise ValueError(f"limit {self.id}: needs min, max or both")


@dataclass(frozen=True)
class LimitResult:
    limit: Limit
    value: float
    utilisation: float
    status: str  # OK | WARN | BREACH

    @property
    def headroom(self) -> float:
        """Distance to the nearest bound in the metric's own unit (negative when breached)."""
        gaps = []
        if self.limit.max is not None:
            gaps.append(self.limit.max - self.value)
        if self.limit.min is not None:
            gaps.append(self.value - self.limit.min)
        return min(gaps)


def _one_sided(value: float, bound: float, is_cap: bool) -> float:
    if bound == 0:
        return 0.0 if (value <= 0 if is_cap else value >= 0) else float("inf")
    if (bound > 0) == is_cap:  # positive cap or negative floor: the allowance runs from zero to the bound
        return max(value / bound, 0.0)
    return bound / value if value * bound > 0 else float("inf")  # negative cap or positive floor


def evaluate(limit: Limit, value: float) -> LimitResult:
    lo, hi = limit.min, limit.max
    if lo is not None and hi is not None:
        utilisation = abs(value - (lo + hi) / 2.0) / ((hi - lo) / 2.0)
    elif hi is not None:
        utilisation = _one_sided(value, hi, is_cap=True)
    else:
        utilisation = _one_sided(value, lo, is_cap=False)
    breached = (lo is not None and value < lo) or (hi is not None and value > hi)
    status = "BREACH" if breached else "WARN" if utilisation >= limit.warn_at else "OK"
    return LimitResult(limit, float(value), float(utilisation), status)


def load_limits(path: Path) -> list[Limit]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    known = {f.name for f in fields(Limit)}
    limits = []
    for item in raw.get("limits", []):
        unknown = set(item) - known
        if unknown:
            raise ValueError(f"{path.name}: limit {item.get('id')!r} has unknown keys {sorted(unknown)}")
        limits.append(Limit(**item))
    ids = [limit.id for limit in limits]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: limit ids must be unique")
    return limits
