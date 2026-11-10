"""Workbench: the one object the CLI, the daily brief and the agent tools talk to.

It loads positions, market data and configuration, owns the engine, caches
revaluations, and returns plain pandas tables and small dataclasses. Nothing
here formats output; presentation lives in ``ipw.classic``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np
import pandas as pd

from ipw.core import config as cfg
from ipw.core.balance_sheet import (
    AociImpact,
    NetInterestIncome,
    aoci_impact,
    book_yield,
    net_interest_income,
)
from ipw.core.engine import Engine, Valuation
from ipw.core.explain import ExplainResult, explain
from ipw.core.hedging import HedgeProposal, par_swaps, propose_hedge
from ipw.core.limits import Limit, LimitResult, evaluate, load_limits
from ipw.core.pricing import bey, solve_rate
from ipw.core.risk import RiskResult, compute_risk
from ipw.core.scenarios import BASE, Scenario, load_scenarios

GROUPINGS = ("bucket", "asset_type", "designation", "agency", "coupon", "orig_year", "position_id")

_ADDITIVE = ["current_face_mm", "book_value_mm", "market_value_mm", "unrealized_mm", "dv01_k",
             "_pv", "_pv_up", "_pv_dn"]  # fmt: skip
_WEIGHTED = {  # column -> weight used when averaging it over a group
    "coupon": "current_face_mm",
    "wal_years": "current_face_mm",
    "cpr_1y_pct": "current_face_mm",
    "yield_pct": "market_value_mm",
    "book_yield_pct": "book_value_mm",
    "zv_spread_bp": "market_value_mm",
}


@dataclass
class ScenarioResult:
    scenario: Scenario
    valuation: Valuation
    d_afs: float  # change in AFS securities value, $mm
    d_htm: float  # change in HTM securities value, $mm (not recognised in equity)
    d_hedges: float  # change in swap value, $mm
    aoci: AociImpact
    nii: NetInterestIncome
    net_duration: float  # effective duration after the shock, net of hedges

    @property
    def d_securities(self) -> float:
        return self.d_afs + self.d_htm


@dataclass
class LimitFix:
    """A swap trade sized to bring one limit to its bound, with the before/after picture."""

    limit: Limit
    trades: pd.DataFrame
    before: LimitResult
    after: LimitResult
    carry_12m_mm: float  # change in base 12-month NII from adding the swap
    result: Workbench  # the book with the trade added, for any further question


class Workbench:
    def __init__(
        self,
        securities: pd.DataFrame,
        swaps: pd.DataFrame,
        market: cfg.Market,
        model: cfg.ModelConfig,
        scenarios: dict[str, Scenario] | None = None,
        limits: list[Limit] | None = None,
        prior_market: cfg.Market | None = None,
    ):
        self.securities = securities
        self.swaps = swaps
        self.market = market
        self.model = model
        self.scenarios = scenarios or {}
        self.limits = limits or []
        self.prior_market = prior_market
        self.engine = Engine(securities, swaps, market, model)
        self._runs: dict[Scenario, ScenarioResult] = {}

    @classmethod
    def load(cls, root: str | Path | None = None) -> Workbench:
        """Load everything from ``<root>/config`` and ``<root>/data``."""
        root = cfg.find_root(root)
        conf, data = root / "config", root / "data"
        prior, marks = conf / "market_prev.yaml", data / "marks.csv"
        return cls(
            securities=cfg.load_securities(data / "portfolio.csv"),
            swaps=cfg.load_swaps(data / "hedges.csv"),
            market=cfg.load_market(conf / "market.yaml", marks),
            model=cfg.load_model(conf / "model.yaml"),
            scenarios=load_scenarios(conf / "scenarios.yaml"),
            limits=load_limits(conf / "limits.yaml"),
            prior_market=cfg.load_market(prior, marks) if prior.is_file() else None,
        )

    # ================================================================== valuation and risk
    @cached_property
    def risk(self) -> RiskResult:
        return compute_risk(self.engine)

    @cached_property
    def positions(self) -> pd.DataFrame:
        """One row per security: valuation, yields, prepayment and risk measures."""
        sec, val, risk = self.securities, self.engine.base, self.risk
        face = sec["current_face_mm"].to_numpy()
        principal = val.cash.principal
        months = np.arange(1, principal.shape[1] + 1)
        dy = risk.bump_bp / 1e4

        out = sec[["position_id", "bucket", "asset_type", "agency", "designation", "coupon", "wac",
                   "orig_year", "current_face_mm", "book_price", "book_value_mm"]].copy()  # fmt: skip
        out["market_value_mm"] = val.clean
        out["price"] = val.clean / face * 100.0
        out["unrealized_mm"] = val.clean - sec["book_value_mm"].to_numpy()
        out["zv_spread_bp"] = val.spread * 1e4
        out["yield_pct"] = bey(solve_rate(val.cash.total, val.pv)) * 100.0
        out["book_yield_pct"] = bey(book_yield(val, sec)) * 100.0
        out["wal_years"] = (principal * months).sum(axis=1) / principal.sum(axis=1) / 12.0
        out["cpr_1y_pct"] = _cpr_1y(val)
        out["dv01_k"] = risk.dv01 * 1e3
        out["eff_duration"] = risk.dv01 * 1e4 / val.pv
        out["eff_convexity"] = (risk.pv_up + risk.pv_dn - 2.0 * val.pv) / (val.pv * dy * dy) / 100.0
        for k, tenor in enumerate(risk.key_tenors):
            out[f"kr01_{tenor:g}y_k"] = risk.kr01[:, k] * 1e3
        out["_pv"], out["_pv_up"], out["_pv_dn"] = val.pv, risk.pv_up, risk.pv_dn
        return out

    def summary(self, by: str | None = "bucket") -> pd.DataFrame:
        """Positions aggregated by ``by`` with a Total row (see GROUPINGS)."""
        return _aggregate(self.positions, by, self.risk.bump_bp)

    def risk_table(self, by: str | None = "bucket") -> pd.DataFrame:
        """Risk by group, followed by Securities, Hedges and Net rows."""
        cols = ["market_value_mm", "wal_years", "cpr_1y_pct", "zv_spread_bp", "eff_duration",
                "eff_convexity", "dv01_k"]  # fmt: skip
        table = self.summary(by)[cols].rename(index={"Total": "Securities"})
        mv = self.engine.base.pv.sum()
        risk = self.risk
        hedge_dv01 = risk.swap_dv01.sum()
        table.loc["Hedges"] = {
            "market_value_mm": self.engine.base.swap_pv.sum(),
            "eff_duration": hedge_dv01 * 1e4 / mv,
            "eff_convexity": risk.convexity(with_swaps=True) - risk.convexity(),
            "dv01_k": hedge_dv01 * 1e3,
        }
        table.loc["Net"] = {
            "market_value_mm": table.loc[["Securities", "Hedges"], "market_value_mm"].sum(),
            "eff_duration": risk.duration(with_swaps=True),
            "eff_convexity": risk.convexity(with_swaps=True),
            "dv01_k": (risk.dv01.sum() + hedge_dv01) * 1e3,
        }
        return table

    def key_rate_table(self, by: str | None = "designation", unit: str = "years") -> pd.DataFrame:
        """Key-rate profile by group plus Securities, Hedges and Net rows.

        ``unit="years"`` gives contributions to portfolio duration (they add up
        to the net effective duration); ``unit="k"`` gives $ thousands per bp.
        """
        if unit not in ("years", "k"):
            raise ValueError("unit must be 'years' or 'k'")
        _check_grouping(by)
        risk = self.risk
        labels = [f"{t:g}Y" for t in risk.key_tenors]
        frame = pd.DataFrame(risk.kr01 * 1e3, columns=labels)
        parts = []
        if by:
            grouped = frame.groupby(self.securities[by].to_numpy()).sum()
            parts.append(grouped.loc[cfg.group_order(grouped.index, by)])
        table = pd.concat(parts + [frame.sum().to_frame("Securities").T])
        table.loc["Hedges"] = risk.swap_kr01.sum(axis=0) * 1e3
        table.loc["Net"] = table.loc["Securities"] + table.loc["Hedges"]
        if unit == "years":
            table = table * 10.0 / self.engine.base.pv.sum()
        table["Sum"] = table.sum(axis=1)
        return table

    def headline(self) -> dict[str, float]:
        """The handful of numbers that describe the book today."""
        pos, val, risk = self.positions, self.engine.base, self.risk
        afs = pos["designation"] == "AFS"
        tax = self.model.balance_sheet.tax_rate
        numbers = {
            "positions": float(len(pos)),
            "face_mm": pos["current_face_mm"].sum(),
            "book_value_mm": pos["book_value_mm"].sum(),
            "market_value_mm": pos["market_value_mm"].sum(),
            "unrealized_mm": pos["unrealized_mm"].sum(),
            "unrealized_afs_mm": pos.loc[afs, "unrealized_mm"].sum(),
            "unrealized_htm_mm": pos.loc[~afs, "unrealized_mm"].sum(),
            "afs_unrealized_after_tax_mm": pos.loc[afs, "unrealized_mm"].sum() * (1.0 - tax),
            "htm_share_pct": pos.loc[~afs, "book_value_mm"].sum() / pos["book_value_mm"].sum() * 100.0,
            "securities_duration": risk.duration(),
            "net_duration": risk.duration(with_swaps=True),
            "net_convexity": risk.convexity(with_swaps=True),
            "net_dv01_k": (risk.dv01.sum() + risk.swap_dv01.sum()) * 1e3,
            "hedge_notional_mm": float(self.swaps["notional_mm"].sum()),
            "hedge_value_mm": float(val.swap_pv.sum()),
            "book_yield_pct": float(np.average(pos["book_yield_pct"], weights=pos["book_value_mm"])),
            "nii_12m_mm": self.run(BASE).nii.total,
        }
        return {key: float(value) for key, value in numbers.items()}

    # ================================================================== scenarios
    def scenario(self, which: Scenario | str | float) -> Scenario:
        """Resolve a scenario object, a configured name, 'base', or a parallel shock in bp."""
        if isinstance(which, Scenario):
            return which
        if isinstance(which, str):
            key = which.strip().lower()
            if key == BASE.name:
                return BASE
            if key in self.scenarios:
                return self.scenarios[key]
            sign = {"up_": 1.0, "dn_": -1.0}.get(key[:3])
            try:
                return Scenario.parallel(sign * float(key[3:]) if sign else float(key))
            except ValueError:
                known = ", ".join(["base", *self.scenarios])
                raise KeyError(f"unknown scenario {which!r}; configured: {known}") from None
        return Scenario.parallel(float(which))

    def run(self, which: Scenario | str | float) -> ScenarioResult:
        """Full revaluation under a scenario, with AOCI, NII and post-shock duration (cached)."""
        scenario = self.scenario(which)
        if scenario not in self._runs:
            base = self.engine.base
            risk = self.risk if scenario == BASE else compute_risk(self.engine, scenario, key_rates=False)
            val = risk.base
            afs = (self.securities["designation"] == "AFS").to_numpy()
            delta = val.pv - base.pv
            bs = self.model.balance_sheet
            self._runs[scenario] = ScenarioResult(
                scenario=scenario,
                valuation=val,
                d_afs=float(delta[afs].sum()),
                d_htm=float(delta[~afs].sum()),
                d_hedges=float((val.swap_pv - base.swap_pv).sum()),
                aoci=aoci_impact(base, val, self.securities, self.swaps, bs.tax_rate),
                nii=net_interest_income(val, self.securities, self.swaps, bs, float(base.env.short_rate[0])),
                net_duration=risk.duration(with_swaps=True),
            )
        return self._runs[scenario]

    def scenario_table(self, names: Iterable[Scenario | str | float] | None = None) -> pd.DataFrame:
        """One row per scenario; default is every scenario in config/scenarios.yaml."""
        base = self.run(BASE)
        market_value = self.engine.base.pv.sum()
        rows = []
        for which in names if names is not None else self.scenarios.values():
            r = self.run(which)
            rows.append(
                {
                    "scenario": r.scenario.name,
                    "description": r.scenario.description,
                    "d_value_mm": r.d_securities,
                    "d_value_pct": r.d_securities / market_value * 100.0,
                    "d_afs_mm": r.d_afs,
                    "d_htm_mm": r.d_htm,
                    "d_hedges_mm": r.d_hedges,
                    "d_aoci_mm": r.aoci.after_tax,
                    "nii_mm": r.nii.total,
                    "d_nii_mm": r.nii.total - base.nii.total,
                    "net_duration": r.net_duration,
                }
            )
        return pd.DataFrame(rows).set_index("scenario")

    def scenario_detail(self, which: Scenario | str | float, by: str = "bucket") -> pd.DataFrame:
        """Where a scenario's value change comes from, by group."""
        _check_grouping(by)
        r = self.run(which)
        pos = self.positions
        frame = pd.DataFrame(
            {
                "market_value_mm": pos["market_value_mm"].to_numpy(),
                "d_value_mm": r.valuation.pv - self.engine.base.pv,
                "cpr_1y_pct": pos["cpr_1y_pct"].to_numpy(),
                "cpr_1y_shocked_pct": _cpr_1y(r.valuation),
                "_face": pos["current_face_mm"].to_numpy(),
            }
        )
        keys = [pos[by].to_numpy(), np.full(len(pos), "Total")]
        parts = []
        for key in keys:
            g = frame.groupby(key)
            part = g[["market_value_mm", "d_value_mm"]].sum()
            for col in ("cpr_1y_pct", "cpr_1y_shocked_pct"):
                ok = frame[col].notna()
                den = frame["_face"].where(ok, 0.0).groupby(key).sum()
                part[col] = (frame[col].where(ok, 0.0) * frame["_face"]).groupby(key).sum() / den.where(
                    den > 0
                )
            parts.append(part)
        table = pd.concat([parts[0].loc[cfg.group_order(parts[0].index, by)], parts[1]])
        table["d_value_pct"] = table["d_value_mm"] / table["market_value_mm"] * 100.0
        table["share_pct"] = table["d_value_mm"] / table.loc["Total", "d_value_mm"] * 100.0
        return table[
            ["market_value_mm", "d_value_mm", "d_value_pct", "share_pct", "cpr_1y_pct", "cpr_1y_shocked_pct"]
        ]

    def nii_table(self, names: Iterable[Scenario | str | float] = (-100, "base", 100)) -> pd.DataFrame:
        """12-month NII decomposition, one column per scenario."""
        runs = [self.run(n) for n in names]
        return pd.DataFrame({r.scenario.name: r.nii.as_dict() for r in runs}).loc[
            ["coupon_income", "amortization", "interest_income", "reinvestment", "hedge_carry",
             "funding_cost", "total"]
        ]  # fmt: skip

    # ================================================================== prepayments
    def prepay_table(self, shocks_bp: Iterable[float] = (-100, 0, 100), by: str = "bucket") -> pd.DataFrame:
        """Rate incentive and projected 1-year CPR by group, today and under parallel shocks."""
        _check_grouping(by)
        pos = self.positions
        mbs = pos["asset_type"].str.startswith("MBS")
        rate = np.where(pos["asset_type"] == "MBS_15Y", self.market.mortgage_rate_15y_pct,
                        self.market.mortgage_rate_30y_pct)  # fmt: skip
        frame = pd.DataFrame(
            {"face": pos["current_face_mm"], "wac": pos["wac"], "incentive_pct": pos["wac"] - rate}
        )
        frame["wal_years"] = pos["wal_years"]
        for bp in shocks_bp:
            frame[f"cpr_{'base' if bp == 0 else f'{bp:+g}bp'}"] = _cpr_1y(self.run(float(bp)).valuation)
        frame, keys = frame[mbs], pos.loc[mbs, by]
        weighted = frame.drop(columns="face").multiply(frame["face"], axis=0)
        table = weighted.groupby(keys).sum().div(frame["face"].groupby(keys).sum(), axis=0)
        table.insert(0, "face_mm", frame["face"].groupby(keys).sum())
        return table.loc[cfg.group_order(table.index, by)]

    def s_curve(
        self, incentives_pct: Iterable[float] = (-3, -2, -1, -0.5, 0, 0.5, 1, 1.5, 2, 3)
    ) -> pd.DataFrame:
        """The model's speeds for a seasoned, unburned, average-size loan."""
        curve = self.engine.product("MBS_30Y").prepay.s_curve(list(incentives_pct))
        table = pd.DataFrame(curve).set_index("incentive_pct") * 100.0
        table["total_cpr"] = table["turnover_cpr"] + table["refi_cpr"]
        return table

    # ================================================================== hedging and what-if
    def hedge(
        self, target_duration: float, mode: str = "duration", tenors: Iterable[float] = (5.0,)
    ) -> HedgeProposal:
        """Size par swaps to reach ``target_duration`` and verify by full revaluation."""
        proposal = propose_hedge(
            self.engine, self.risk, target_duration, mode, tuple(float(t) for t in tenors)
        )
        proposal.duration_after = self.what_if(add_swaps=proposal.trades).risk.duration(with_swaps=True)
        return proposal

    def what_if(
        self,
        drop: Iterable[str] = (),
        add_swaps: pd.DataFrame | None = None,
        add_securities: pd.DataFrame | None = None,
    ) -> Workbench:
        """A new workbench with positions removed and/or swaps and securities added."""
        drop = list(drop)
        unknown = set(drop) - set(self.securities["position_id"])
        if unknown:
            raise KeyError(f"unknown position_id(s): {sorted(unknown)}")
        securities = self.securities[~self.securities["position_id"].isin(drop)]
        if add_securities is not None and len(add_securities):
            securities = pd.concat([securities[cfg.SECURITY_COLUMNS], add_securities[cfg.SECURITY_COLUMNS]])
        swaps = self.swaps
        if add_swaps is not None and len(add_swaps):
            swaps = pd.concat([swaps, add_swaps[cfg.SWAP_COLUMNS]], ignore_index=True)
        return Workbench(cfg.prepare_securities(securities[cfg.SECURITY_COLUMNS]), swaps, self.market,
                         self.model, self.scenarios, self.limits, self.prior_market)  # fmt: skip

    def compare(self, other: Workbench, labels: tuple[str, str] = ("before", "after")) -> pd.DataFrame:
        """Headline numbers and limit metrics of two workbenches side by side."""
        names = {
            "market_value_mm": "Market value ($mm)",
            "unrealized_afs_mm": "AFS unrealized ($mm)",
            "net_duration": "Net duration (years)",
            "net_convexity": "Net convexity",
            "net_dv01_k": "Net DV01 ($k per bp)",
            "hedge_notional_mm": "Hedge notional ($mm)",
            "nii_12m_mm": "NII, 12 months ($mm)",
        }
        rows = {}
        for label, wb in zip(labels, (self, other)):
            headline = wb.headline()
            col = {name: headline[key] for key, name in names.items()}
            for r in wb.limit_report():
                unit = f" ({r.limit.unit})" if r.limit.unit else ""
                col[f"Limit {r.limit.id}{unit}"] = r.value
            rows[label] = col
        table = pd.DataFrame(rows)
        table["change"] = table[labels[1]] - table[labels[0]]
        return table

    def hedge_table(self) -> pd.DataFrame:
        """The swap book with today's value and DV01 of each swap."""
        table = self.swaps.set_index("swap_id").copy()
        table["value_mm"] = self.engine.base.swap_pv
        table["dv01_k"] = self.risk.swap_dv01 * 1e3
        return table

    # ================================================================== limits
    def metric(self, name: str, scenario: str | None = None) -> float:
        """Value of a limit metric, optionally under a scenario."""
        run = self.run(scenario) if scenario else None
        base = self.run(BASE)

        def need() -> ScenarioResult:
            if run is None:
                raise ValueError(f"metric {name!r} needs a scenario")
            return run

        if name == "net_duration":
            return run.net_duration if run else base.net_duration
        if name == "net_convexity":
            return self.risk.convexity(with_swaps=True)
        if name == "duration_drift":
            return need().net_duration - base.net_duration
        if name == "aoci_after_tax":
            return need().aoci.after_tax
        if name == "nii_change":
            return need().nii.total - base.nii.total
        if name == "value_change_pct":
            r = need()
            return (r.d_securities + r.d_hedges) / self.engine.base.pv.sum() * 100.0
        headline = self.headline()
        if name in headline:
            return headline[name]
        raise KeyError(f"unknown metric {name!r}")

    def limit_report(self) -> list[LimitResult]:
        return [evaluate(limit, self.metric(limit.metric, limit.scenario)) for limit in self.limits]

    def limit_table(self) -> pd.DataFrame:
        rows = [
            {
                "limit": r.limit.id,
                "name": r.limit.name,
                "value": r.value,
                "min": r.limit.min,
                "max": r.limit.max,
                "unit": r.limit.unit,
                "utilisation_pct": r.utilisation * 100.0,
                "status": r.status,
                "policy_ref": r.limit.policy_ref,
            }
            for r in self.limit_report()
        ]
        return pd.DataFrame(rows).set_index("limit")

    def fix_limit(
        self, limit_id: str, tenor: float = 5.0, target: float | None = None, round_to_mm: float = 10.0
    ) -> LimitFix:
        """Size a par swap that brings one limit metric to ``target`` (default: its breached bound).

        Every limit metric is linear in swap notional, so two evaluations (no
        swap and a $100mm probe) give the answer. The notional is rounded up
        and the result is verified by full revaluation.
        """
        limit = next((x for x in self.limits if x.id == limit_id), None)
        if limit is None:
            raise KeyError(f"unknown limit {limit_id!r}; configured: {[x.id for x in self.limits]}")
        before = evaluate(limit, self.metric(limit.metric, limit.scenario))
        if target is None:
            if before.status != "BREACH":
                raise ValueError(
                    f"limit {limit_id} is not breached; pass a target value to size a hedge anyway"
                )
            bounds = [b for b in (limit.min, limit.max) if b is not None]
            target = min(bounds, key=lambda b: abs(before.value - b))

        probe = par_swaps(self.engine, (float(tenor),)).assign(notional_mm=100.0)
        probed = self.what_if(add_swaps=probe).metric(limit.metric, limit.scenario)
        slope = (probed - before.value) / 100.0
        if abs(slope) < 1e-12:
            raise ValueError(f"limit {limit_id} does not respond to swaps; it needs a position change")
        notional = (target - before.value) / slope
        direction = "PAY_FIXED" if notional >= 0 else "RECEIVE_FIXED"
        notional = math.ceil(abs(notional) / round_to_mm) * round_to_mm
        trades = par_swaps(self.engine, (float(tenor),), direction).assign(notional_mm=notional)

        result = self.what_if(add_swaps=trades)
        return LimitFix(
            limit=limit,
            trades=trades,
            before=before,
            after=evaluate(limit, result.metric(limit.metric, limit.scenario)),
            carry_12m_mm=result.run(BASE).nii.total - self.run(BASE).nii.total,
            result=result,
        )

    # ================================================================== explain and drill-down
    def explain(self) -> ExplainResult:
        if self.prior_market is None:
            raise FileNotFoundError("no prior close found (config/market_prev.yaml)")
        return explain(self.engine, self.prior_market)

    def top(self, metric: str = "dv01_k", n: int = 10, ascending: bool = False) -> pd.DataFrame:
        """Largest positions by any column of ``positions``."""
        if metric not in self.positions.columns:
            raise KeyError(f"unknown column {metric!r}")
        cols = ["position_id", "bucket", "designation", "current_face_mm", "market_value_mm",
                "unrealized_mm", "eff_duration", "dv01_k"]  # fmt: skip
        cols += [metric] if metric not in cols else []
        return self.positions.sort_values(metric, ascending=ascending).head(n)[cols].set_index("position_id")

    def position(self, position_id: str) -> tuple[pd.Series, pd.DataFrame]:
        """(all measures for one position, its projected cash flows by year)."""
        match = np.flatnonzero(self.securities["position_id"] == position_id)
        if match.size == 0:
            raise KeyError(f"unknown position_id {position_id!r}")
        i = int(match[0])
        cash = self.engine.base.cash
        years = np.arange(cash.interest.shape[1]) // 12 + 1
        flows = (
            pd.DataFrame(
                {
                    "interest_mm": cash.interest[i],
                    "scheduled_mm": cash.scheduled[i],
                    "prepaid_mm": cash.prepaid[i],
                    "smm_log": np.log1p(-np.nan_to_num(cash.cpr[i])) / 12.0,
                }
            )
            .groupby(years)
            .sum()
        )
        flows["cpr_pct"] = (1.0 - np.exp(flows.pop("smm_log"))) * 100.0
        flows["end_balance_mm"] = cash.balance[i, 12::12][: len(flows)]
        flows.index.name = "year"
        details = self.positions.iloc[i].drop(labels=["_pv", "_pv_up", "_pv_dn"])
        return details, flows[flows[["interest_mm", "scheduled_mm", "prepaid_mm"]].sum(axis=1) > 0]


# ====================================================================== helpers
def _cpr_1y(val: Valuation) -> np.ndarray:
    """Projected 12-month CPR in percent (NaN for products without prepayments)."""
    survival = np.prod((1.0 - val.cash.cpr[:, :12]) ** (1.0 / 12.0), axis=1)
    return (1.0 - survival) * 100.0


def _check_grouping(by: str | None) -> None:
    if by is not None and by not in GROUPINGS:
        raise ValueError(f"cannot group by {by!r}; choose from: {', '.join(GROUPINGS)}")


def _aggregate(frame: pd.DataFrame, by: str | None, bump_bp: float) -> pd.DataFrame:
    """Sum additive columns, weight-average the others, and append a Total row."""
    _check_grouping(by)
    key_rate_cols = [c for c in frame.columns if c.startswith("kr01_")]
    dy = bump_bp / 1e4

    def agg(keys) -> pd.DataFrame:
        groups = frame.groupby(keys, sort=True)
        out = groups[_ADDITIVE + key_rate_cols].sum()
        out.insert(0, "positions", groups.size())
        for col, weight in _WEIGHTED.items():
            ok = frame[col].notna()
            den = frame[weight].where(ok, 0.0).groupby(keys).sum()
            out[col] = (frame[col].where(ok, 0.0) * frame[weight]).groupby(keys).sum() / den.where(den != 0)
        out["price"] = out["market_value_mm"] / out["current_face_mm"] * 100.0
        out["book_price"] = out["book_value_mm"] / out["current_face_mm"] * 100.0
        out["eff_duration"] = out["dv01_k"] * 10.0 / out["_pv"]
        out["eff_convexity"] = (
            (out["_pv_up"] + out["_pv_dn"] - 2.0 * out["_pv"]) / (out["_pv"] * dy * dy) / 100.0
        )
        return out.drop(columns=["_pv", "_pv_up", "_pv_dn"])

    parts = []
    if by:
        grouped = agg(frame[by].to_numpy())
        parts.append(grouped.loc[cfg.group_order(grouped.index, by)])
    table = pd.concat(parts + [agg(np.full(len(frame), "Total"))])
    table.index.name = by or "portfolio"
    return table
