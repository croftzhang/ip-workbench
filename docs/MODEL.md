# Model Document

**Investment Portfolio Risk Analytics, release 1**

| | |
|---|---|
| Document | Model document, version 1.0 |
| Owner | Product Owner, Investment Portfolio analytics |
| Last updated | 2026-11-10 |
| Formulas, sources, parameters | [FUNCTIONAL_SPEC.md](FUNCTIONAL_SPEC.md) |

> The desk and all figures are illustrative.

This document is the summary a model validator or a new user reads first: what
the model is for, how it works in outline, what it assumes, where it is weak,
and how it is tested. The complete formulas, their sources and every parameter
value are in the functional specification and are not repeated here.

## 1. Purpose and scope

**Intended use.** Daily risk analytics for a bank investment portfolio of
agency pass-throughs and Treasuries hedged with interest-rate swaps: valuation
against marks, interest-rate risk, scenario analysis, AOCI and net interest
income sensitivity, hedge sizing, limit monitoring, and a day-over-day explain.

**Not intended for.** Trading or relative-value decisions, pricing securities
without a mark, regulatory capital, or any use that needs option-adjusted
measures.

**Products.** 30-year and 15-year fixed-rate agency pass-throughs, Treasury
notes and bonds, plain fixed-for-floating swaps.

## 2. Method in brief

| Step | What happens | Specified in |
|---|---|---|
| Inputs | Positions, hedges, marks, Treasury par curve, mortgage rates, parameters, scenarios, limits; all validated on load | FR-0 |
| Curve | Par yields are interpolated onto a semi-annual grid and bootstrapped into discount factors; shocks are applied to par yields and the curve is rebuilt | FR-1 |
| Rate path | One path on which today's forward rates are realised; the mortgage rate follows the forward 10-year par yield at a constant spread | FR-2 |
| Prepayments | Speed is housing turnover (with seasoning, seasonality and lock-in) plus refinancing (an S-curve in the rate incentive, with seasoning, loan size and burnout) | FR-3.1 |
| Cash flows | Level-payment amortisation and prepayments for pass-throughs; coupons and principal for Treasuries; fixed and floating legs for swaps | FR-3 |
| Valuation | Cash flows are discounted on the curve plus a static spread; each mortgage position's spread is solved from its mark and held constant in scenarios | FR-4 |
| Risk | Duration, convexity, DV01 and key-rate exposures are differences of full revaluations with prepayments re-projected | FR-6 |
| Scenarios | Instantaneous shocks to curve, spreads, mortgage spread and prepayment behaviour | FR-7 |
| AOCI | Change in AFS value plus change in the swaps hedging AFS, after tax; HTM never enters | FR-8 |
| Income | Twelve months: effective-yield interest income, reinvestment, hedge carry, funding with a beta | FR-9 |
| Limits and fixes | Metrics against bounds with warning levels; the swap that restores a breached limit, found by linearity and confirmed by revaluation | FR-10, FR-11 |
| Hedging | Par swaps sized to a duration target, in one tenor or across tenors by non-negative least squares | FR-12 |
| Explain | The market is moved from the prior close to today in three steps with a revaluation after each | FR-14 |

Behaviour of the prepayment model for a seasoned, average-size, unburned loan
(`ipw prepay --s-curve`):

| Incentive (percentage points) | -3.0 | -1.0 | 0.0 | +0.5 | +1.0 | +2.0 |
|---|---|---|---|---|---|---|
| Total CPR (%) | 3.9 | 5.6 | 8.9 | 15.2 | 29.0 | 49.1 |

## 3. Assumptions and limitations

| Assumption | Consequence | Direction |
|---|---|---|
| One zero-volatility path; static spread instead of an option-adjusted spread | No value is assigned to rate volatility. Durations of coupons near the refinancing threshold are longer than option-adjusted durations, and negative convexity is understated. | Overstates duration of at-the-money coupons |
| Static spread constant across scenarios | In a rally the spread of a coupon moving into the money would widen; holding it fixed overstates the price gain. | Overstates gains in rallies |
| Stylised prepayment model, not calibrated | Speeds are plausible in shape, not in level for any specific pool. The `prepay_fast` and `prepay_slow` scenarios move market value by about +0.8% and -0.8%. | Either |
| Mortgage rate tied to the 10-year par yield at a constant spread | Changes in the mortgage basis are not anticipated along the path; they can be shocked in a scenario. | Either |
| Burnout from the pool factor, no rate history | The burnout state of seasoned pools is approximate. | Either |
| No refinancing lag, no payment delay, constant WAC, whole-month accrual | Small timing errors in cash flows. | Small |
| Swaps valued on the Treasury curve | Swap spreads and swap-spread risk are ignored; par swap rates are Treasury par yields. | Hedge sizes are approximate |
| Treasuries valued on the fitted curve | Marks of individual Treasuries are not reproduced exactly. | Small |
| Curve extended flat beyond 30 years | Affects forward 10-year rates used after year 20 of the projection. | Small |
| Income uses the prospective yield with no catch-up adjustment | The one-time adjustment required when prepayment estimates change is not shown. | Understates income volatility at the time of a rate move |
| Reinvestment at a forward par yield plus a fixed spread; funding at a blended rate with a fixed beta | Income sensitivity depends on assumed reinvestment and pass-through. | Assumption dependent |
| Designated hedges treated as fully effective | Hedge ineffectiveness and basis-adjustment mechanics are not modelled. | Understates AOCI volatility |
| Illustrative data | Portfolio, marks and limits are constructed. | Not applicable |

The main ones (no option cost, constant spread, stylised prepayments, swaps on
the Treasury curve, assumed funding beta) are printed on every daily brief.

## 4. Extension points

A product is a class with one method, `project(positions, env) -> CashFlows`.
Pricing, risk, scenarios, AOCI, income, hedging and limits work on cash flows
and never look inside a product. The products considered and left for later,
and what each needs, are listed in
[SOLUTION_DESIGN.md](SOLUTION_DESIGN.md), section 6. Simulation over many rate
paths would call the same product interface once per path.

## 5. Testing and controls

`pytest` runs about 150 tests in under 20 seconds.

| Area | What is checked |
|---|---|
| Replication | A plain-Python re-implementation of FR-1 to FR-4, importing nothing from the engine, reproduces prices and speeds of single positions to seven decimals, at today's market and under +/-100bp |
| Curve | Par bonds reprice to 100; key-rate shocks sum to parallel; shock shapes |
| Prepayment | Hand calculation at the S-curve midpoint; monotonic S-curve; lock-in, seasoning, loan size, burnout, seasonality calendar, caps |
| Cash flows | Vectorised pass-through equals a month-by-month recursion; principal returned in full; Treasury accrual; swap value equals the annuity formula |
| Valuation | Every mortgage position reprices to its mark; price-source fallback order; reconciliation of face, book and market value |
| Risk | Key-rate durations sum to effective duration; duration predicts a 10bp move within 1%; duration and convexity predict a 100bp move within 2%; Treasury effective duration equals modified duration within 2% |
| Balance sheet | HTM never reaches AOCI; income components add up; funding beta and swap carry respond as specified |
| Hedging and limits | Hedge reaches target duration; limit fix cures the breach with the smallest USD 10 million notional; utilisation rules |
| Explain | Drivers add up to the change between two independent valuations |
| Interface | Every command runs; JSON output parses; brief is complete, ASCII and deterministic; no table is truncated |
| Regression | 69 headline, scenario, limit and key-rate numbers against `tests/golden.json` |
| Documents | Every code reference, test name, command and parameter value in the specification exists and is current; requirement numbers are consistent across the documents; figures quoted in the acceptance script match the engine |

A change that moves any stored number fails the regression test. After an
intended change, regenerate the file as described in
`tests/test_regression.py`, review the difference, and update the parameter
table in the functional specification.
