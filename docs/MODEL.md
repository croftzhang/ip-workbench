# Model documentation

Version 0.1. Covers the analytics engine in `src/ipw/core/`. Every parameter
named here lives in `config/model.yaml`; every formula has a test in `tests/`.

## 1. Purpose and scope

**Intended use.** Daily risk analytics for a bank investment portfolio of
agency pass-throughs and Treasuries hedged with interest-rate swaps: valuation
against marks, interest-rate risk, scenario analysis, AOCI and net interest
income sensitivity, hedge sizing, limit monitoring, and a day-over-day explain.

**Not intended for.** Trading or relative-value decisions, pricing securities
without a mark, regulatory capital, or any use that needs option-adjusted
measures. The prepayment model is stylised and is not calibrated to pool data.

**Products in scope.** 30-year and 15-year fixed-rate agency pass-throughs,
Treasury notes and bonds, plain fixed-for-floating swaps. Section 13 lists how
other products would be added.

## 2. Inputs

| Input | File | Content |
|---|---|---|
| Positions | `data/portfolio.csv` | One row per holding: coupon, WAC, age (WALA), remaining term (WAM), factor, face, book price, AFS/HTM, average loan size |
| Hedges | `data/hedges.csv` | Swaps: direction, notional, fixed rate, remaining years, hedged book |
| Marks | `data/marks.csv` | Clean price per position and date |
| Market | `config/market.yaml`, `config/market_prev.yaml` | Treasury par curve, primary mortgage rates, MBS coupon stack, for today and the prior close |
| Model | `config/model.yaml` | Prepayment, risk and balance-sheet parameters |
| Scenarios | `config/scenarios.yaml` | Named shocks |
| Limits | `config/limits.yaml` | Policy limits |

Amounts are $ millions. Rates in files are percent; spreads are basis points.

## 3. Curve

1. Par yields (semi-annual, bond-equivalent) are quoted at 0.5, 1, 2, 3, 5, 7,
   10, 20 and 30 years.
2. They are interpolated linearly onto a semi-annual grid out to 50 years, flat
   before the first and after the last quote.
3. Discount factors at the grid nodes are bootstrapped from the par condition
   `1 = c/2 * sum(P_i) + P_n`.
4. Monthly discount factors are log-linear between nodes, so the forward rate
   is constant inside each half-year.

Shocks are added to the par yields on the grid and the curve is bootstrapped
again. A key-rate shock is a hat function centred on one key tenor (1, 2, 5,
10, 20, 30 years by default), zero at the neighbouring key tenors and flat
beyond the first and last. The hats add up to a parallel shift, which is why
key-rate durations add up to effective duration.

## 4. Rate environment

Every valuation runs on one deterministic path: today's forward rates are
realised (zero volatility).

* **Mortgage rate.** `M30(t) = forward 10-year par yield at month t + s`, where
  `s` is today's primary 30-year mortgage rate minus today's 10-year par yield.
  The 15-year rate keeps its current distance to the 30-year rate. Both spreads
  are constant along the path and across curve scenarios. A scenario can move
  them with `mortgage_spread_bp`.
* **Short rate.** The one-month forward rate from the curve. It drives the swap
  floating leg, hedge carry and the funding rate.

With an upward-sloping curve, forward mortgage rates rise over time, so
projected speeds slow down along the path.

## 5. Prepayment model

Annual speed (CPR) is the sum of two parts, converted to a monthly rate with
`SMM = 1 - (1 - CPR)^(1/12)`. The incentive `x` is the pool's gross WAC minus
the mortgage rate for its term, in percentage points.

```
turnover(t)  = base * min(1, age / turnover_ramp) * seasonality(month) * lock_in(x)
lock_in(x)   = 1 - lock_in_max * clip(-x / lock_in_full, 0, 1)

refi(t)      = max_refi / (1 + exp(-(x - midpoint) / slope))
               * min(1, age / refi_ramp) * loan_size_mult * burnout(t)
loan_size    = clip(1 + elasticity * (avg_loan_size / ref_size - 1), min_mult, max_mult)
burnout(t)   = Q(t-1) ^ exponent,   Q(t) = Q(t-1) * (1 - refi(t))^(1/12)

CPR(t)       = min(turnover(t) + refi(t), max_cpr)
```

| Parameter | Value | Meaning |
|---|---|---|
| `turnover_cpr_pct` | 6.5 | Long-run housing turnover for a seasoned loan |
| `turnover_ramp_months` | 30 | Linear seasoning ramp |
| `lock_in_max_reduction` | 0.40 | Turnover cut when the loan rate is far below the market |
| `lock_in_full_incentive_pct` | 2.5 | Rate gap at which lock-in is complete |
| `refi_max_cpr_pct` | 45 | Refinancing plateau |
| `refi_midpoint_pct` | 1.00 | Incentive at half the plateau |
| `refi_slope_pct` | 0.35 | Width of the S-curve |
| `refi_ramp_months` | 9 | Seasoning ramp for refinancing |
| `loan_size_ref_k`, `loan_size_elasticity` | 300, 0.40 | Larger loans refinance more readily, bounded at 0.75x and 1.25x |
| `burnout_exponent`, `burnout_floor` | 2.0, 0.20 | Refinancing response falls as rate-sensitive borrowers leave |
| `max_cpr_pct` | 75 | Cap on total and on refinancing speed |
| `seasonality` | 0.75 to 1.18 | Monthly turnover multipliers, averaging 1.0, peak in June |

**Burnout starting point.** `Q(0)` compares the pool factor with what scheduled
amortisation and base turnover alone would have left:
`Q(0) = clip(factor / (scheduled_factor * turnover_survival), floor, 1)`.
A pool that has paid down faster than that has already lost refinancers. This
is a heuristic; it does not use the pool's actual rate history.

**Resulting behaviour** for a seasoned, average-size, unburned loan
(`ipw prepay --s-curve`):

| Incentive (pct points) | -3.0 | -1.0 | 0.0 | +0.5 | +1.0 | +2.0 |
|---|---|---|---|---|---|---|
| Total CPR (%) | 3.9 | 5.6 | 8.9 | 15.2 | 29.0 | 49.1 |

The model is used for every MBS in the book. It does not distinguish agencies,
and it has no lag between the rate move and the prepayment.

## 6. Cash flows

**Pass-throughs.** A level-pay pool's balance factorises into scheduled
amortisation and prepayment survival: `B(t) = B(0) * f(t) * Q(t)`, with
`f(t) = (1 - (1+r)^-(n-t)) / (1 - (1+r)^-n)`, `r = WAC/12`, `n` the remaining
term and `Q(t) = prod(1 - SMM)`. Each month:

```
scheduled principal = B(t-1) * (1 - f(t) / f(t-1))
prepaid principal   = (B(t-1) - scheduled) * SMM(t)
interest to investor = B(t-1) * coupon / 12
```

The gap between WAC and coupon is servicing and guarantee fee. Payment delay
is ignored. A test compares this with a month-by-month recursion.

**Treasuries.** Semi-annual coupons counted back from maturity, principal at
maturity, accrued interest for the part of the coupon period already elapsed.

**Swaps.** The floating leg is projected at one-month forwards, which
reproduces `N * (1 - P(T))`; the fixed leg pays semi-annually. Swaps are valued
on the Treasury curve, so a swap struck at the Treasury par yield is worth zero.

## 7. Pricing and calibration

Present value is `sum of cash(t) * P(t) * exp(-z * t)`, where `z` is a
zero-volatility (static) spread, continuously compounded. Discounting all
future cash gives the dirty value; market value is reported clean.

Calibration, in this order for each MBS position:

1. its own mark in `data/marks.csv`,
2. otherwise the quote for its sector and coupon in the market file,
3. otherwise `default_zv_spread_bp`.

`z` is solved by Newton's method so that the model reproduces the price.
Treasuries are valued on the curve (`z = 0`). In every scenario `z` stays at its
calibrated value unless the scenario moves it with `zv_spread_bp`.

Market yield and book yield are internal rates of return on the same cash
flows against market price and amortised cost, quoted bond-equivalent.

## 8. Risk measures

All measures are differences of full revaluations with prepayments
re-projected. The bump is 25bp on the par curve.

```
effective duration  = (PV- - PV+) / (2 * PV0 * dy)
effective convexity = (PV- + PV+ - 2 * PV0) / (PV0 * dy^2) / 100
DV01                = (PV- - PV+) / (2 * bump in bp)
KR01(k)             = DV01 for the hat-shaped bump at key tenor k
```

Convexity is divided by 100, so for a 100bp move the percentage price change
is roughly `-duration + 0.5 * convexity`. Portfolio duration divides the summed
DV01, including swaps for the net figure, by the market value of the securities.

## 9. Scenarios

A scenario is an instantaneous shock with up to six parts: a parallel curve
move, a curve-shape move given as (tenor, bp) points, an MBS spread move
(valuation only), a mortgage-spread move (prepayments only), and multipliers on
refinancing and turnover (prepayment-model stress). Duration after the shock
is measured by bumping around the shocked curve.

## 10. AOCI

Only AFS securities are carried at fair value through other comprehensive
income. HTM securities stay at amortised cost: their value changes are reported
but never reach AOCI. Swaps designated as fair-value hedges of AFS securities
offset the hedged item, so

```
AOCI change (pre-tax) = change in AFS market value + change in value of swaps hedging AFS
AOCI change (after tax) = pre-tax * (1 - tax_rate)          tax_rate = 0.24
```

Hedge ineffectiveness and the basis-adjustment mechanics of hedge accounting
are not modelled.

## 11. Net interest income

Twelve-month projection under a constant balance sheet.

| Component | Method |
|---|---|
| Interest income | Effective-yield method. Each security earns its prospective book yield (the IRR of the scenario's cash flows against amortised cost) on amortised cost, rolled forward monthly. Shown as coupon income plus net premium amortisation. |
| Reinvestment | Principal received in month t earns the forward 5-year par yield plus 60bp for the rest of the horizon. |
| Hedge carry | (floating - fixed) on swap notional, accrued monthly. |
| Funding cost | Book value funded at `funding_rate + beta * (short rate - today's short rate)`, with `funding_rate = 2.60%` and `beta = 0.40`. |

The funding assumption is stylised: a blended deposit-like cost that passes
through 40% of a short-rate move. It makes the portfolio's NII fall when rates
rise. Catch-up adjustments from the retrospective method are not modelled.

## 12. Hedging, limits and explain

**Hedge sizing.** Swap values are linear in notional. `duration` mode solves
one notional so that net DV01 hits the target. `krd` mode uses non-negative
least squares over several tenors to scale the key-rate profile down in
proportion, then rescales to hit the DV01 target. The proposal is verified by
adding the swaps to the book and running the normal risk calculation.

**Limits.** A limit names a metric, an optional scenario, and a floor, a cap or
both. Utilisation is value over bound for one-sided limits and distance from
the centre over half-width for bands. Status is BREACH outside the bound, WARN
at or above `warn_at`, otherwise OK.

**Limit fix.** Every rate-risk metric is linear in swap notional, so two
evaluations (no swap, and a $100mm probe) give the notional that brings a
breached metric to its bound. It is rounded up to $10mm and verified by full
revaluation.

**Explain.** Positions are held fixed and the market is moved from the prior
close to today in three steps with a full revaluation after each: Treasury
curve, mortgage-rate basis, MBS spreads. The curve step is split into the part
predicted by yesterday's key-rate exposures and a remainder. A large remainder
means the linear risk report did not describe the day well.

## 13. Assumptions and limitations

| Assumption | Consequence | Direction |
|---|---|---|
| One zero-volatility path; static spread instead of OAS | No value is assigned to rate volatility. Durations of coupons near the refinancing threshold are longer than OAS-model durations, and negative convexity is understated. | Overstates duration of at-the-money coupons |
| Static spread constant across scenarios | In a rally the spread of a coupon moving into the money would widen; holding it fixed overstates the price gain. | Overstates gains in rallies |
| Stylised prepayment model, not calibrated | Speeds are plausible in shape, not in level for any specific pool. `prepay_fast` and `prepay_slow` move market value by about +0.8% and -0.8%. | Either |
| Burnout from pool factor, no rate history | Burnout state of seasoned pools is approximate. | Either |
| No refinancing lag, no payment delay, constant WAC | Small timing errors in cash flows. | Small |
| Swaps valued on the Treasury curve | Swap spreads and swap-spread risk are ignored; par rates are Treasury par yields. | Hedge sizes are approximate |
| Treasuries on the fitted curve | Marks of individual Treasuries are not reproduced exactly. | Small |
| Funding rate with a fixed beta | NII sensitivity is driven by an assumed pass-through. | Assumption dependent |
| Hedge accounting simplified | AOCI effect assumes fully effective fair-value hedges. | Understates AOCI volatility |
| Illustrative data | Portfolio, marks and limits are constructed. | Not applicable |

**Extension points.** A product is a class with one method,
`project(positions, env) -> CashFlows`. Pricing, risk, scenarios, AOCI, NII,
hedging and limits work on cash flows and never look inside a product.

| Product | What it needs |
|---|---|
| Agency debt (bullet), other swap tenors | Nothing new |
| Mortgage servicing rights | A servicing-strip cash-flow class reusing the prepayment model |
| Adjustable-rate mortgages | Forward-rate resets |
| Agency CMO | A tranche waterfall |
| CMBS, non-agency RMBS | Default and loss models plus a waterfall |
| Callable debt, caps, swaptions | A volatility model; outside the static method |

Monte Carlo OAS would replace the single path with many paths through the
same product interface.

## 14. Testing and controls

`pytest` runs 127 tests in about 15 seconds.

| Area | What is checked |
|---|---|
| Replication | A plain-Python re-implementation of sections 3 to 7, importing nothing from the engine, reproduces prices and speeds of single positions to seven decimals, at base and under +/-100bp |
| Curve | Par bonds reprice to 100; key-rate shocks sum to parallel; shock shapes |
| Prepayment | Hand calculation at the S-curve midpoint; monotonic S-curve; lock-in, seasoning, loan size, burnout, seasonality calendar, caps |
| Cash flows | Vectorised pass-through equals a month-by-month recursion; principal returned in full; Treasury accrual; swap value equals the annuity formula |
| Valuation | Every MBS reprices to its mark; price-source fallback order; reconciliation of face, book, market value |
| Risk | Key-rate durations sum to effective duration; duration predicts a 10bp move within 1%; duration and convexity predict a 100bp move within 2%; Treasury effective duration equals modified duration within 2% |
| Balance sheet | HTM never reaches AOCI; NII components add up; funding beta and swap carry respond as specified |
| Hedging and limits | Hedge reaches target duration; limit fix cures the breach with the smallest $10mm notional; utilisation rules |
| Explain | Drivers add up to the change between two independent valuations |
| Interface | Every command runs; JSON output parses; brief is complete, ASCII and deterministic |
| Regression | 69 headline, scenario, limit and key-rate numbers against `tests/golden.json` |

A change that moves any stored number fails the regression test. After an
intended change, regenerate the file as described in
`tests/test_regression.py` and review the diff.
