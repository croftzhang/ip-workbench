# Functional Specification

**Investment Portfolio Risk Analytics, release 1**

| | |
|---|---|
| Document | Functional specification, version 1.0 |
| Status | Baseline for release 1 |
| Owner | Product Owner, Investment Portfolio analytics |
| Last updated | 2026-11-10 |
| Reads from | [BRD.md](BRD.md), [SOLUTION_DESIGN.md](SOLUTION_DESIGN.md) |
| Verified by | `tests/`, [UAT.md](UAT.md) |

> The desk and all figures are illustrative.

This document defines every function of release 1 precisely enough to build,
test and validate: inputs, calculation rules with complete formulas, outputs,
error handling and acceptance tests. Each formula states where it comes from
and where it is implemented. A test (`tests/test_spec_sync.py`) checks that
every code reference, test name, command and parameter value in this document
exists and is current.

## Contents

| Section | Function | Serves |
|---|---|---|
| [FR-0](#fr-0-data-contracts) | Data contracts | All |
| [FR-1](#fr-1-curve) | Curve | BR-1 to BR-3 |
| [FR-2](#fr-2-rate-environment) | Rate environment | BR-2 to BR-4 |
| [FR-3](#fr-3-product-valuation-models) | Product valuation models | BR-1 to BR-4 |
| [FR-4](#fr-4-pricing-calibration-and-yields) | Pricing, calibration and yields | BR-1 |
| [FR-5](#fr-5-portfolio-views) | Portfolio views | BR-1 |
| [FR-6](#fr-6-risk-measures) | Risk measures | BR-2 |
| [FR-7](#fr-7-scenarios) | Scenarios | BR-3, BR-4 |
| [FR-8](#fr-8-aoci) | AOCI | BR-3 |
| [FR-9](#fr-9-net-interest-income) | Net interest income | BR-3 |
| [FR-10](#fr-10-limits) | Limits | BR-5 |
| [FR-11](#fr-11-limit-remediation) | Limit remediation | BR-6 |
| [FR-12](#fr-12-hedge-sizing) | Hedge sizing | BR-7 |
| [FR-13](#fr-13-what-if) | What-if | BR-8 |
| [FR-14](#fr-14-explain) | Explain | BR-9 |
| [FR-15](#fr-15-prepayment-outlook) | Prepayment outlook | BR-4 |
| [FR-16](#fr-16-daily-brief) | Daily brief | BR-10 |
| [FR-17](#fr-17-interfaces) | Interfaces | NFR-8 |
| [Parameters](#model-parameters) | Every model parameter and its value | NFR-3 |
| [Qualities](#non-functional-requirements) | How each NFR is met | NFR-1 to NFR-8 |
| [Traceability](#traceability-matrix) | Requirement to function to code to test | All |
| [References](#references) | Sources cited | NFR-6 |

## Conventions

**Units.** Amounts are USD millions. Rates in input files are percent and
spreads are basis points (bp); inside formulas all rates, spreads and
prepayment speeds are decimals per year unless a formula says otherwise.
Parameters given in percent in the parameter table are divided by 100 before
use, except the incentive $x$, which stays in percentage points.

**Time.** Months are numbered $t = 1, 2, \dots, T$ with $T = 360$. A cash flow
of month $t$ is paid $t/12$ years after the valuation date. The valuation date
falls on a payment date for mortgage securities, so they carry no accrued
interest.

**Notation.**

| Symbol | Meaning |
|---|---|
| $P(m)$ | Discount factor for a payment $m$ months from today |
| $c(m;\tau)$ | Par yield of a $\tau$-year bond starting in $m$ months; $c(0;\tau)$ is today's par yield |
| $r_t$ | One-month forward rate for month $t$, simple, annualised |
| $M_{30}(j)$, $M_{15}(j)$ | Primary mortgage rates $j$ months from today |
| $B_t$ | Balance of a position at the end of month $t$; $B_0$ is the current face |
| $CF_t$ | Total cash paid to the holder in month $t$ |
| $z$ | Static spread, continuously compounded |
| $PV$ | Present value of all future cash, which is the dirty value |
| $\operatorname{clip}(x,a,b)$ | $\min(\max(x,a),b)$ |

**Origin of a formula.** *Standard* means a textbook or market-convention
result, with the reference. *Adapted* means the idea is standard and the
functional form is chosen here. *Project assumption* means a simplification
made for this product; it is repeated in the limitations table of
[MODEL.md](MODEL.md).

---

## FR-0 Data contracts

**Purpose.** Define the inputs and reject bad ones before any calculation.

### Positions: `data/portfolio.csv`

| Column | Type | Unit | Rule and use |
|---|---|---|---|
| `position_id` | text | | Required, unique |
| `asset_type` | text | | `MBS_30Y`, `MBS_15Y` or `UST`; must have a registered product |
| `agency` | text | | Reporting only |
| `term_years` | number | years | Original term; 15 or less selects the 15-year mortgage rate |
| `coupon` | number | % per year | Rate paid to the holder |
| `wac` | number | % per year | Gross loan rate; mortgage securities only |
| `orig_year` | integer | | Reporting only |
| `wala_months` | integer | months | Loan age; mortgage securities only |
| `wam_months` | integer | months | Remaining term; at least 1 |
| `original_face_mm` | number | USD mm | Reporting only |
| `factor` | number | | Current over original face; sets the burnout starting point |
| `current_face_mm` | number | USD mm | $B_0$ |
| `book_price` | number | per 100 face | Amortised cost, clean |
| `designation` | text | | `AFS` or `HTM` |
| `avg_loan_size_k` | number | USD thousands | Mortgage securities only |

Derived on load: `book_value_mm` (current face times book price over 100) and
`bucket`, a coarse coupon band used as the default grouping.

### Hedges: `data/hedges.csv`

| Column | Type | Unit | Rule |
|---|---|---|---|
| `swap_id` | text | | Required |
| `direction` | text | | `PAY_FIXED` or `RECEIVE_FIXED` |
| `notional_mm` | number | USD mm | |
| `fixed_rate` | number | % per year | |
| `remaining_years` | number | years | A multiple of 0.5 |
| `hedged_book` | text | | Swaps with `AFS` enter the AOCI calculation |

A missing hedge file means a book without hedges.

### Marks: `data/marks.csv`

One row per position and date: `as_of` (ISO date), `position_id`, `price`
(clean, per 100 face). The rows whose date equals the market file's `as_of`
are used.

### Market: `config/market.yaml`, `config/market_prev.yaml`

| Key | Content |
|---|---|
| `as_of` | Valuation date |
| `par_curve.tenors_years`, `par_curve.yields_pct` | Treasury par yields, semi-annual bond-equivalent; tenors strictly increasing |
| `mortgage_rates_pct.rate_30y`, `.rate_15y` | Primary mortgage rates |
| `mbs_prices.<sector>.<coupon>` | Clean price per 100 by sector and coupon, used where a position has no mark |

### Model, scenarios, limits

`config/model.yaml` holds the parameters listed under
[Model parameters](#model-parameters). `config/scenarios.yaml` and
`config/limits.yaml` are specified in FR-7 and FR-10. An unknown key in any of
the three is an error.

**Errors.** Missing column; duplicate `position_id`; designation other than AFS
or HTM; swap maturity not on the half-year grid; unknown key; duplicate or
reserved scenario name; duplicate limit id; limit without a bound; asset type
with no product. Each stops the load with a message naming the file and the
problem.

**Implementation.** `ipw.core.config.load_securities`,
`ipw.core.config.load_swaps`, `ipw.core.config.load_marks`,
`ipw.core.config.load_market`, `ipw.core.config.load_model`,
`ipw.core.scenarios.load_scenarios`, `ipw.core.limits.load_limits`,
`ipw.core.config.find_root`.

**Acceptance.** `test_sample_files_load`, `test_position_files_are_validated`,
`test_unknown_model_key_is_rejected`,
`test_scenario_and_limit_files_are_validated`,
`test_unknown_asset_type_is_rejected`, `test_find_root`.

---

## FR-1 Curve

**Purpose.** Turn quoted Treasury par yields into discount factors and forward
rates, and apply shocks.

**Inputs.** Par yields $y_j$ at tenors $T_j$ (years).

**Rules.**

Quotes are interpolated linearly onto a semi-annual grid $\tau_i = i/2$ years,
$i = 1,\dots,100$, flat before the first and after the last quote:

$$c_i = y_j + (y_{j+1} - y_j)\,\frac{\tau_i - T_j}{T_{j+1} - T_j} \quad \text{for } T_j \le \tau_i \le T_{j+1} \tag{1.1}$$

Discount factors at the grid nodes, $P_n = P(6n)$, follow from the condition
that a bond paying the par yield is worth par:

$$P_n = \frac{1 - \tfrac{1}{2} c_n \sum_{i=1}^{n-1} P_i}{1 + \tfrac{1}{2} c_n} \tag{1.2}$$

Between nodes the logarithm of the discount factor is linear in time, so the
forward rate is constant inside each half-year. For month $m = 6k + q$ with
$0 \le q \le 5$ and $P_0 = 1$:

$$P(6k + q) = P_k^{\,1 - q/6}\; P_{k+1}^{\,q/6} \tag{1.3}$$

The par yield of a $\tau$-year bond starting in $m$ months is

$$c(m;\tau) = \frac{2\,\bigl(P(m) - P(m + 12\tau)\bigr)}{\sum_{i=1}^{2\tau} P(m + 6i)} \tag{1.4}$$

and the one-month forward rate for month $t$ is

$$r_t = 12\left(\frac{P(t-1)}{P(t)} - 1\right) \tag{1.5}$$

A shock $\Delta_i$ in basis points is added to the par yields on the grid and
the curve is rebuilt with (1.2) and (1.3):

$$c_i' = c_i + \frac{\Delta_i}{10^4} \tag{1.6}$$

Three shock shapes exist. A parallel shock has $\Delta_i$ constant. A
piecewise shock interpolates linearly between given (tenor, bp) points and is
flat outside them. A key-rate shock for key tenor $K_k$ out of
$K_1 \lt \dots \lt K_n$ is $\Delta_i = b\,h_k(\tau_i)$, where $h_k$ is the hat
function that is linear between neighbouring key tenors, equals one at $K_k$
and zero at the other key tenors, and is flat beyond $K_1$ and $K_n$. Therefore

$$\sum_{k=1}^{n} h_k(\tau) = 1 \quad \text{for all } \tau \tag{1.7}$$

so the key-rate shocks add up to a parallel shock.

**Outputs.** $P(m)$ for $m = 0,\dots,600$; $c(m;\tau)$; $r_t$.

**Source.** (1.2), (1.4), (1.5): standard bootstrapping of discount factors
and definitions of par and forward rates [R1, ch. 1-2]. (1.3): standard, the
"raw" method, linear on the logarithm of discount factors [R2]. (1.1) and the
flat extension beyond 30 years: project assumption. (1.7): key-rate concept
from [R3]; shifts defined on par yields with linear interpolation between key
rates follow [R1, ch. 5].

**Implementation.** `ipw.core.curve.Curve`, `ipw.core.curve.Curve.from_quotes`,
`ipw.core.curve.Curve.forward_par`, `ipw.core.curve.Curve.short_rate`,
`ipw.core.curve.Curve.shifted`, `ipw.core.curve.parallel_shock`,
`ipw.core.curve.piecewise_shock`, `ipw.core.curve.key_rate_shock`.

**Acceptance.** `test_bootstrap_reprices_par_bonds`,
`test_discount_factors_are_positive_and_decreasing`,
`test_forward_rate_is_constant_within_a_half_year`,
`test_spot_and_forward_par_rates_agree_at_time_zero`,
`test_parallel_shift_moves_every_par_rate_by_the_shock`,
`test_key_rate_shocks_sum_to_a_parallel_shift`,
`test_piecewise_shock_interpolates_and_is_flat_outside`,
`test_quotes_must_be_increasing_in_tenor`.

---

## FR-2 Rate environment

**Purpose.** Define the single path of rates on which every product projects
its cash flows in a given scenario.

**Rules.** Today's forward rates are realised (zero volatility). The primary
30-year mortgage rate keeps a constant spread to the 10-year par yield. The
spread is measured once, on today's unshocked curve:

$$s_{30} = M_{30}^{\,mkt} - c(0;10) \tag{2.1}$$

On the scenario's curve, with an optional mortgage-spread shock $\Delta_m$ in
basis points, for $j = 0,\dots,T-1$:

$$M_{30}(j) = c^{\,scen}(j;10) + s_{30} + \frac{\Delta_m}{10^4} \tag{2.2}$$

$$M_{15}(j) = M_{30}(j) + \bigl(M_{15}^{\,mkt} - M_{30}^{\,mkt}\bigr) \tag{2.3}$$

The rate $M(j)$ drives the prepayments paid in month $j+1$. There is no further
lag.

**Outputs.** The scenario's curve, $M_{30}$, $M_{15}$, $r_t$, the valuation
month, and the scenario's prepayment multipliers.

**Source.** The forwards-realised path is the standard zero-volatility
(static) valuation setting for mortgage securities [R9, ch. 24]. (2.1) to
(2.3), a mortgage rate tied to the 10-year par yield at a constant spread and
no application lag: project assumption.

**Implementation.** `ipw.core.engine.Engine.environment`,
`ipw.core.products.RateEnvironment`, `ipw.core.config.Market.mortgage_spreads`.

**Acceptance.** `test_sample_files_load`,
`test_engine_price_and_speed_match_the_independent_reference`,
`test_engine_scenario_value_matches_the_independent_reference`.

---

## FR-3 Product valuation models

**Purpose.** For each product type, project the cash paid to the holder month
by month in a rate environment. Every product returns the same structure:
interest, scheduled principal, prepaid principal, balance, accrued interest
today, and projected speed.

**Extension rule.** A product is a class with one method that returns that
structure. Pricing, risk, scenarios, AOCI, income, hedging and limits use the
structure only.

**Implementation.** `ipw.core.products.Product`, `ipw.core.products.CashFlows`,
`ipw.core.products.default_products`.

### FR-3.1 Agency pass-through (30-year and 15-year fixed rate)

#### Prepayment model

For month $t$, with loan age $a_t$ and rate incentive $x_t$ in percentage
points:

$$a_t = \text{WALA} + t - 1, \qquad x_t = \text{WAC} - 100\,M(t-1) \tag{3.1}$$

where WAC is in percent and $M$ is $M_{15}$ for pools with an original term of
15 years or less and $M_{30}$ otherwise.

*Housing turnover.* With base speed $\theta$, seasoning ramp $R_T$, seasonal
multiplier $S$ and scenario multiplier $k_T$:

$$\text{turn}_t = \theta \cdot \min\!\left(1, \frac{a_t}{R_T}\right) \cdot S_{m(t)} \cdot L(x_t) \cdot k_T \tag{3.2}$$

$$L(x) = 1 - \lambda \cdot \operatorname{clip}\!\left(\frac{-x}{x_L},\, 0,\, 1\right) \tag{3.3}$$

$L$ is the lock-in multiplier: turnover falls linearly as the loan rate drops
below the market rate, by at most $\lambda$ once the gap reaches $x_L$. The
calendar month of projection month $t$, with $m_0$ the valuation month
(1 to 12), is

$$m(t) = \bigl((m_0 + t - 1) \bmod 12\bigr) + 1 \tag{3.4}$$

*Refinancing.* A logistic S-curve in the incentive, with plateau
$\rho_{max}$, midpoint $x_0$ and width $w$:

$$\rho(x) = \frac{\rho_{max}}{1 + \exp\!\bigl(-(x - x_0)/w\bigr)} \tag{3.5}$$

A loan-size multiplier, with reference size $A_0$ and elasticity $e$:

$$g = \operatorname{clip}\!\left(1 + e\left(\frac{A}{A_0} - 1\right),\, g_{min},\, g_{max}\right) \tag{3.6}$$

Refinancing speed with seasoning ramp $R_R$, burnout state $Q$, burnout
exponent $\beta$ and scenario multiplier $k_R$, capped at $\text{CPR}_{max}$:

$$\text{refi}_t = \min\!\left(\rho(x_t) \cdot \min\!\left(1, \frac{a_t}{R_R}\right) \cdot g \cdot k_R \cdot Q_{t-1}^{\,\beta},\; \text{CPR}_{max}\right) \tag{3.7}$$

*Burnout.* $Q$ is the share of rate-sensitive borrowers still in the pool. It
falls as refinancing takes place:

$$Q_t = Q_{t-1}\,\bigl(1 - \text{refi}_t\bigr)^{1/12} \tag{3.8}$$

Its starting value compares the pool factor $F$ with what scheduled
amortisation and base turnover alone would have left. With monthly loan rate
$i = \text{WAC}/1200$:

$$f^{\,sched} = \frac{1 - (1+i)^{-\text{WAM}}}{1 - (1+i)^{-(\text{WALA}+\text{WAM})}} \tag{3.9}$$

$$n^{\,eff} = \text{WALA} - \frac{R_T - 1}{2} \;\; \text{if } \text{WALA} \ge R_T, \qquad n^{\,eff} = \frac{\text{WALA}\,(\text{WALA}+1)}{2 R_T} \;\; \text{otherwise} \tag{3.10}$$

$$Q_0 = \operatorname{clip}\!\left(\frac{F}{f^{\,sched} \cdot \bigl(1 - \text{SMM}(\theta)\bigr)^{\,n^{eff}}},\; q_{min},\; 1\right) \tag{3.11}$$

where $n^{\,eff}$ is the number of months of full-speed turnover the pool has
had, allowing for the ramp.

*Total speed.* Annual speed and its monthly equivalent:

$$\text{CPR}_t = \min\bigl(\text{turn}_t + \text{refi}_t,\; \text{CPR}_{max}\bigr) \tag{3.12}$$

$$\text{SMM}_t = 1 - \bigl(1 - \text{CPR}_t\bigr)^{1/12} \tag{3.13}$$

#### Cash flows

With monthly loan rate $i = \text{WAC}/1200$, net coupon $c$ in percent and
remaining term $n = \text{WAM}$, the balance factorises into scheduled
amortisation $f$ and prepayment survival $G$:

$$f_t = \frac{1 - (1+i)^{-(n-t)}}{1 - (1+i)^{-n}} \;\; \text{for } t \le n, \qquad f_t = 0 \;\; \text{for } t \gt n \tag{3.14}$$

$$G_t = \prod_{s=1}^{t} \bigl(1 - \text{SMM}_s\bigr), \qquad B_t = B_0\, f_t\, G_t \tag{3.15}$$

Each month:

$$\text{Sched}_t = B_{t-1}\left(1 - \frac{f_t}{f_{t-1}}\right) \tag{3.16}$$

$$\text{Prepaid}_t = \bigl(B_{t-1} - \text{Sched}_t\bigr)\,\text{SMM}_t \tag{3.17}$$

$$\text{Int}_t = B_{t-1}\,\frac{c}{1200} \tag{3.18}$$

and $CF_t = \text{Int}_t + \text{Sched}_t + \text{Prepaid}_t$. The difference
between WAC and coupon is servicing and guarantee fee and is not paid to the
holder.

**Source.** (3.13), (3.15) to (3.18) and the factorisation of the pool factor
into a survival factor and an amortised balance: standard [R4; R9, ch. 3].
(3.14): standard level-payment amortisation [R4]. The four drivers of
prepayment (rate incentive, seasoning, month of the year, burnout) and the
30-month seasoning ramp: standard structure [R5; R15; R4 for the PSA ramp].
(3.2), (3.5), (3.7): adapted. The model here adds turnover and refinancing
instead of multiplying factors, uses a logistic curve in the rate difference,
and applies separate ramps to the two parts. (3.3): adapted; the existence
and rough size of the effect are documented in [R8], which reports that a one
percentage point fall in the gap between the locked-in rate and the market
rate reduced moving by 9% overall and by 16% in 2022 to 2024; the linear form
and its parameters are chosen here. (3.6): project assumption reflecting the
market convention that larger loans refinance more readily. (3.8) to (3.11):
adapted; burnout as the loss of rate-sensitive borrowers follows [R5; R7],
while tracking a surviving share $Q$ and estimating its starting value from
the pool factor are chosen here. No refinancing lag, constant WAC and no
payment delay: project assumptions. Parameter values are not calibrated to
pool data.

**Implementation.** `ipw.core.prepay.PrepayModel.project`,
`ipw.core.prepay.PrepayModel.turnover_cpr`, `ipw.core.prepay.PrepayModel.lock_in`,
`ipw.core.prepay.PrepayModel.refi_cpr`,
`ipw.core.prepay.PrepayModel.loan_size_multiplier`,
`ipw.core.prepay.PrepayModel.initial_refi_survival`, `ipw.core.prepay.cpr_to_smm`,
`ipw.core.products.passthrough_cashflows`, `ipw.core.products.AgencyPassThrough`.

**Acceptance.** `test_first_month_matches_a_hand_calculation`,
`test_s_curve_is_increasing_in_incentive`,
`test_lock_in_cuts_turnover_and_saturates`,
`test_new_loans_prepay_slower_than_seasoned_loans`,
`test_larger_loans_refinance_faster_within_bounds`,
`test_burnout_damps_refinancing_over_time_and_for_paid_down_pools`,
`test_initial_refi_survival_is_bounded`, `test_seasonality_follows_the_calendar`,
`test_scenario_multipliers_scale_each_component`,
`test_speeds_are_capped_and_convert_to_smm`, `test_seasonality_needs_twelve_months`,
`test_passthrough_matches_the_month_by_month_recursion`,
`test_passthrough_returns_all_principal_and_ends_at_zero`,
`test_without_prepayments_the_gross_payment_is_level`,
`test_engine_price_and_speed_match_the_independent_reference`.

### FR-3.2 Treasury note or bond

**Rules.** With face $F$, coupon $c$ in percent and $n$ months to maturity,
coupons are paid every six months counting back from maturity. Let $m_1$ be
the month of the next coupon, $1 \le m_1 \le 6$:

$$\text{Int}_t = \frac{F c}{200} \;\; \text{for } t \in \{n,\, n-6,\, n-12,\, \dots\},\ t \ge 1 \tag{3.19}$$

$$\text{Sched}_n = F \tag{3.20}$$

$$\text{Accrued} = \frac{F c}{200} \cdot \frac{6 - m_1}{6} \tag{3.21}$$

The balance is $F$ until maturity. Projected speed does not apply.

**Source.** Standard bond conventions with months as the day count [R1,
ch. 1]. Whole-month accrual: project assumption.

**Implementation.** `ipw.core.products.TreasuryBond`.

**Acceptance.** `test_treasury_at_the_par_yield_prices_at_par`,
`test_treasury_between_coupon_dates_accrues_interest`.

### FR-3.3 Fixed-for-floating swap

**Rules.** With notional $N$, fixed rate $K$ in percent and maturity in $n$
months (a multiple of six), the floating leg is projected at one-month
forwards and the fixed leg pays semi-annually. For a swap that pays fixed
($\sigma = +1$) or receives fixed ($\sigma = -1$):

$$\text{Float}_t = N\left(\frac{P(t-1)}{P(t)} - 1\right), \qquad t = 1,\dots,n \tag{3.22}$$

$$\text{Fixed}_t = \frac{N K}{200} \;\; \text{for } t \in \{6, 12, \dots, n\}, \qquad \text{Fixed}_t = 0 \;\; \text{otherwise} \tag{3.23}$$

$CF_t = \sigma\,(\text{Float}_t - \text{Fixed}_t)$. Discounting (3.22) on the
same curve gives the textbook value of the floating leg, so

$$PV = \sigma\, N \left[\, 1 - P(n) - \frac{K}{200} \sum_{i=1}^{n/6} P(6i) \right] \tag{3.24}$$

and a swap struck at today's par yield is worth zero.

**Source.** (3.24): standard, a swap as a fixed-rate bond against a floating
note worth par [R1, ch. 2 and 13]. Valuing swaps on the Treasury curve and
projecting the floating leg at one-month forwards: project assumption (swap
spreads are ignored).

**Implementation.** `ipw.core.products.FixedFloatSwap`.

**Acceptance.**
`test_swap_at_the_par_rate_is_worth_zero_and_off_market_matches_the_annuity_formula`,
`test_new_par_swaps_have_zero_value_and_sensible_dv01`.

---

## FR-4 Pricing, calibration and yields

**Purpose.** Value any position from its cash flows, reproduce the marks, and
report yields.

**Rules.** Present value at static spread $z$:

$$PV(z) = \sum_{t=1}^{T} CF_t \; P(t)\; e^{-z\,t/12} \tag{4.1}$$

This is the dirty value. Reported market value and price are clean:

$$\text{MV} = PV - \text{Accrued}, \qquad \text{Price} = 100\,\frac{\text{MV}}{B_0} \tag{4.2}$$

*Calibration.* For each mortgage position the spread is solved so that the
model reproduces its price $p$, taken from the first available source: the
position's own mark, then the quote for its sector and coupon, then no price,
in which case $z$ is the default spread.

$$PV(z) = \frac{p\,B_0}{100} \tag{4.3}$$

Treasuries and swaps use $z = 0$. Equation (4.3) is solved by Newton's method
from $z = 0$ until the step is below $10^{-12}$:

$$z \leftarrow z - \frac{PV(z) - \text{target}}{PV'(z)}, \qquad PV'(z) = -\sum_{t=1}^{T} \frac{t}{12}\, CF_t\, P(t)\, e^{-z\,t/12} \tag{4.4}$$

In a scenario the calibrated spread is kept, plus the scenario's spread shock
for mortgage positions.

*Yields.* The yield is the continuous rate $y_c$ that discounts the cash flows
to a given value $V$, quoted bond-equivalent:

$$\sum_{t=1}^{T} CF_t\, e^{-y_c\, t/12} = V, \qquad y = 2\left(e^{\,y_c/2} - 1\right) \tag{4.5}$$

with $V = PV$ for the market yield and $V =$ book value plus accrued for the
book yield.

*Average life and one-year speed.*

$$\text{WAL} = \frac{1}{12} \cdot \frac{\sum_t t\,(\text{Sched}_t + \text{Prepaid}_t)}{\sum_t (\text{Sched}_t + \text{Prepaid}_t)} \tag{4.6}$$

$$\text{CPR}_{1y} = 1 - \prod_{t=1}^{12} \bigl(1 - \text{SMM}_t\bigr) \tag{4.7}$$

**Errors.** Calibration that does not converge in 100 iterations stops the run
with a message to check prices and cash flows.

**Source.** (4.1), (4.3): standard, the zero-volatility (static) spread [R9,
ch. 24; R1, ch. 3]. Continuous compounding of the spread: project convention.
(4.4): Newton's method. (4.5): standard internal rate of return and
bond-equivalent quotation [R1, ch. 3]. (4.6), (4.7): standard [R4]. Order of
price sources: project design (RULE-1 in the BRD).

**Implementation.** `ipw.core.pricing.present_value`, `ipw.core.pricing.solve_rate`,
`ipw.core.pricing.bey`, `ipw.core.engine.Engine.base`, `ipw.core.engine.Engine.value`,
`ipw.core.engine.Valuation`, `ipw.core.config.Market.price`.

**Acceptance.** `test_solve_rate_round_trips_spread_and_yield`,
`test_calibration_reprices_every_mbs_to_its_mark`,
`test_price_sources_fall_back_in_order`,
`test_engine_price_and_speed_match_the_independent_reference`.

---

## FR-5 Portfolio views

**Purpose.** Show holdings, value against book and unrealized gain or loss, by
any grouping and by position (BR-1).

**Rules.** For each position: market value, price, unrealized gain or loss
(market value minus book value), spread, market yield, book yield, average
life, one-year speed, and the risk measures of FR-6. For a group $g$:

| Measure | Aggregation |
|---|---|
| Face, book value, market value, unrealized, DV01, key-rate DV01 | Sum |
| Price, book price | Market value or book value over face, times 100 |
| Coupon, average life, one-year speed | Face-weighted average |
| Market yield, spread | Market-value-weighted average |
| Book yield | Book-value-weighted average |
| Duration, convexity | From summed present values, as in FR-6 |

Groupings: coupon bucket, asset type, designation, agency, coupon, vintage,
position. A total row is always added. A position drill-down returns all
measures for one position and its projected cash flows by year. A ranking
returns the largest positions by any measure.

**Errors.** Unknown grouping, unknown position, unknown measure.

**Implementation.** `ipw.core.workbench.Workbench.positions`,
`ipw.core.workbench.Workbench.summary`, `ipw.core.workbench.Workbench.headline`,
`ipw.core.workbench.Workbench.position`, `ipw.core.workbench.Workbench.top`.

**Acceptance.** `test_market_value_reconciles_to_face_book_and_unrealized`,
`test_position_drill_down`, `test_unknown_grouping_is_rejected_everywhere`.

---

## FR-6 Risk measures

**Purpose.** Measure interest-rate exposure, its change with rates, and its
location on the curve, before and after hedges (BR-2).

**Rules.** Every measure is a difference of full revaluations (FR-2 to FR-4)
with prepayments re-projected and spreads held constant. Let $b = 25$ bp,
$\delta = b/10^4$, and let $PV_+$ and $PV_-$ be the values after parallel
shocks of $+b$ and $-b$.

$$\text{DV01} = \frac{PV_- - PV_+}{2b} \tag{6.1}$$

$$D = \frac{PV_- - PV_+}{2\,PV_0\,\delta} \tag{6.2}$$

$$C = \frac{PV_- + PV_+ - 2\,PV_0}{PV_0\,\delta^{2}} \cdot \frac{1}{100} \tag{6.3}$$

Convexity is divided by 100 by market convention, so that for a move of
$\Delta y$ percentage points the approximate percentage price change is
$-D\,\Delta y + \tfrac{1}{2}\,C\,\Delta y^{2}$.

Key-rate DV01 for key tenor $k$, with $PV_{\pm}^{(k)}$ the values after the
key-rate shocks of FR-1:

$$\text{KR01}_k = \frac{PV_-^{(k)} - PV_+^{(k)}}{2b} \tag{6.4}$$

For a group or the whole book, sums replace the single values. The net
figures add the swaps to the numerators of (6.1) to (6.4) and keep the
securities' value as the base:

$$D^{\,net} = 10^{4} \cdot \frac{\sum_{sec} \text{DV01} + \sum_{swaps} \text{DV01}}{\sum_{sec} PV_0} \tag{6.5}$$

Key-rate durations are $10^{4}\,\text{KR01}_k / \sum_{sec} PV_0$. By (1.7),

$$\sum_k \text{KR01}_k \approx \text{DV01} \tag{6.6}$$

up to second-order terms.

**Outputs.** By position and group: DV01, effective duration, effective
convexity, key-rate DV01 and key-rate duration; rows for securities, hedges
and net.

**Source.** (6.1) to (6.3): standard effective duration and convexity by
central difference [R1, ch. 4; R9, ch. 24]. (6.4), (6.6): key-rate durations
[R3], with shifts on par yields as in [R1, ch. 5]. (6.5), the choice of the
securities' value as the base for net figures: project convention.

**Implementation.** `ipw.core.risk.compute_risk`, `ipw.core.risk.RiskResult`,
`ipw.core.workbench.Workbench.risk_table`,
`ipw.core.workbench.Workbench.key_rate_table`.

**Acceptance.** `test_us2_key_rate_durations_add_up_to_effective_duration`,
`test_duration_predicts_small_moves_and_convexity_the_error`,
`test_treasury_effective_duration_matches_modified_duration`,
`test_mortgage_option_shows_up_where_it_should`.

---

## FR-7 Scenarios

**Purpose.** Revalue the book under defined instantaneous shocks and report
value, AOCI, income and post-shock duration together (BR-3, BR-4; RULE-8).

**Inputs.** A scenario has a name, a description and up to six shocks:

| Field | Effect | Enters |
|---|---|---|
| `parallel_bp` | Parallel move of the par curve | (1.6) |
| `curve_points_bp` | Piecewise curve move from (tenor, bp) points, added to the parallel move | (1.6) |
| `zv_spread_bp` | Added to the spread of mortgage positions | (4.1) |
| `mortgage_spread_bp` | $\Delta_m$: primary mortgage rate on top of the curve | (2.2) |
| `refi_multiplier` | $k_R$ | (3.7) |
| `turnover_multiplier` | $k_T$ | (3.2) |

Shocks are instantaneous. Scenarios are listed in `config/scenarios.yaml`; any
parallel shock can also be requested by its size, and the name `base` means no
shock.

**Rules.** For scenario $s$ and position $i$, $\Delta PV_i = PV_i^{(s)} - PV_i^{(0)}$.
The change is reported for securities in total, for AFS and HTM separately, and
for swaps. AOCI follows FR-8 and income FR-9. Net duration after the shock is
(6.5) measured with bumps of $\pm b$ around the scenario's curve:

$$D^{\,net,(s)} = 10^{4} \cdot \frac{\sum \text{DV01}^{(s)}}{\sum_{sec} PV^{(s)}} \tag{7.1}$$

A breakdown of one scenario by any grouping gives each group's change, its
share of the total, and its one-year speed before and after.

**Errors.** Unknown scenario name.

**Source.** Instantaneous parallel, curve-shape and basis shocks as standard
stress tests: [R16]. Composition of a scenario from six parts: project design.

**Implementation.** `ipw.core.scenarios.Scenario`, `ipw.core.scenarios.load_scenarios`,
`ipw.core.workbench.Workbench.scenario`, `ipw.core.workbench.Workbench.run`,
`ipw.core.workbench.Workbench.scenario_table`,
`ipw.core.workbench.Workbench.scenario_detail`.

**Acceptance.** `test_us1_standard_shocks_run_within_five_seconds`,
`test_us1_results_match_stored_values`, `test_base_scenario_changes_nothing`,
`test_scenario_resolution`, `test_scenario_detail_adds_up`,
`test_spread_and_prepayment_stresses_have_the_expected_sign`,
`test_engine_scenario_value_matches_the_independent_reference`.

---

## FR-8 AOCI

**Purpose.** Report the change in equity through AOCI under a scenario
(BR-3; RULE-2 to RULE-4).

**Rules.** Only AFS securities and the swaps designated as fair-value hedges
of AFS securities enter. With tax rate $\tau$:

$$\Delta\text{AOCI}^{\,pre} = \sum_{i \in AFS} \Delta PV_i \; + \sum_{j \in \text{swaps hedging AFS}} \Delta V_j \tag{8.1}$$

$$\Delta\text{AOCI}^{\,after} = (1 - \tau)\,\Delta\text{AOCI}^{\,pre} \tag{8.2}$$

The change in HTM value is reported next to it and never included.

**Source.** AFS at fair value through other comprehensive income and HTM at
amortised cost: [R11]. In a fair-value hedge of an AFS security the gain or
loss on the swap and the offsetting change on the hedged security are
recognised in earnings, so only the unhedged part of the value change reaches
AOCI: [R12]. Treating designated hedges as fully effective, which gives (8.1):
project assumption.

**Implementation.** `ipw.core.balance_sheet.aoci_impact`,
`ipw.core.balance_sheet.AociImpact`.

**Acceptance.** `test_us4_htm_positions_never_reach_aoci`,
`test_hedges_reduce_aoci_sensitivity`.

---

## FR-9 Net interest income

**Purpose.** Project income over the next $H = 12$ months under a scenario and
show where a change comes from (BR-3; RULE-5, RULE-9).

**Rules.** The balance sheet is constant: principal received is reinvested and
the funded amount does not change.

*Interest income.* Each security earns its prospective effective yield on
amortised cost. The yield $y_c$ solves (4.5) with $V = AC_0$, the book value
plus accrued, using the scenario's cash flows. With monthly growth
$\gamma = e^{\,y_c/12}$:

$$AC_t = AC_{t-1}\,\gamma - CF_t \tag{9.1}$$

$$\text{Income} = \sum_{t=1}^{H} AC_{t-1}\,(\gamma - 1) \tag{9.2}$$

It is shown as coupon income plus net premium amortisation:

$$\text{Coupon} = \sum_{t=1}^{H} B_{t-1}\,\frac{c}{1200}, \qquad \text{Amortisation} = \text{Income} - \text{Coupon} \tag{9.3}$$

*Reinvestment.* Principal received in month $t$, summed over securities,
earns the new-money yield for the rest of the horizon. With reinvestment tenor
$\tau_R$ and spread $s_R$:

$$\text{Reinvest} = \sum_{t=1}^{H} \text{Prin}_t \cdot \bigl(c(t;\tau_R) + s_R\bigr) \cdot \frac{H - t}{12} \tag{9.4}$$

*Hedge carry.* For each swap, with $\sigma$ as in FR-3.3 and $N_t = N$ while
the swap is outstanding and zero afterwards:

$$\text{Carry} = \sum_{swaps} \sum_{t=1}^{H} \sigma\,N_t\,\frac{r_t - K/100}{12} \tag{9.5}$$

*Funding cost.* Total book value $BV$ is funded at a blended rate that passes
through a share $\beta_f$ of the move in the short rate. With $r_1^{\,base}$
today's short rate in the unshocked market:

$$\phi_t = \phi_0 + \beta_f\,\bigl(r_t - r_1^{\,base}\bigr) \tag{9.6}$$

$$\text{Funding} = -\,BV \sum_{t=1}^{H} \frac{\phi_t}{12} \tag{9.7}$$

*Total.*

$$\text{NII} = \text{Income} + \text{Reinvest} + \text{Carry} + \text{Funding} \tag{9.8}$$

**Outputs.** The five components and the total, per scenario; the change
against the base case.

**Source.** (9.1) to (9.3): the interest method with prepayments anticipated
[R10]. That paragraph also requires the carrying amount to be adjusted to
what it would have been had the new yield applied since acquisition; this
catch-up is not modelled, and the yield is applied prospectively: project
assumption. (9.4), reinvestment at a forward par yield plus a spread: project
assumption. (9.5): accrual of the two swap legs. (9.6), (9.7): adapted; a
funding cost that moves by a fraction of the short-rate move is the deposit
beta of [R13], and the single blended rate and its level are assumed here.
Constant balance sheet: standard practice for income simulation.

**Implementation.** `ipw.core.balance_sheet.net_interest_income`,
`ipw.core.balance_sheet.book_yield`, `ipw.core.balance_sheet.NetInterestIncome`,
`ipw.core.workbench.Workbench.nii_table`.

**Acceptance.** `test_nii_components_add_up`,
`test_interest_income_is_close_to_book_yield_on_average_balance`,
`test_funding_beta_drives_the_rate_sensitivity_of_funding`,
`test_pay_fixed_swaps_earn_more_carry_when_rates_rise`,
`test_faster_prepayments_cut_the_yield_of_premium_bonds`.

---

## FR-10 Limits

**Purpose.** Compare policy metrics with their bounds and warn before a bound
is reached (BR-5; RULE-6).

**Inputs.** Each limit in `config/limits.yaml` has an id, a name, a metric, an
optional scenario, a floor `min`, a cap `max` or both, a warning level
`warn_at` (default 0.90), a unit and a policy reference.

| Metric | Definition | Scenario |
|---|---|---|
| `net_duration` | (6.5), or (7.1) if a scenario is given | Optional |
| `net_convexity` | (6.3) on the book including swaps | No |
| `duration_drift` | $D^{\,net,(s)} - D^{\,net}$ | Required |
| `aoci_after_tax` | (8.2) | Required |
| `nii_change` | $\text{NII}^{(s)} - \text{NII}^{(0)}$ | Required |
| `value_change_pct` | $100\,(\sum_{sec}\Delta PV + \sum_{swaps}\Delta V)/\sum_{sec} PV_0$ | Required |
| any headline number | For example `htm_share_pct`, the HTM share of book value | No |

**Rules.** Utilisation $u$ of a value $v$:

$$u = \frac{\lvert v - \tfrac{1}{2}(\text{min} + \text{max}) \rvert}{\tfrac{1}{2}(\text{max} - \text{min})} \quad \text{for a band} \tag{10.1}$$

$$u = \max\!\left(\frac{v}{\text{bound}},\, 0\right) \quad \text{for a positive cap or a negative floor} \tag{10.2}$$

$$u = \frac{\text{bound}}{v} \quad \text{for a negative cap or a positive floor, when } v \text{ has the sign of the bound} \tag{10.3}$$

In (10.3), a value of the opposite sign to the bound is outside the limit and
its utilisation is unbounded. Status is BREACH if $v$ is below the floor or
above the cap, WARN if utilisation is at or above `warn_at`, otherwise OK. Headroom is the distance to the nearest bound
in the metric's unit, negative when breached.

**Errors.** Unknown metric; a metric that needs a scenario without one; a limit
without a bound; duplicate ids.

**Source.** Board-approved limits on earnings and economic value measures
under stress: supervisory expectation [R16]. Utilisation and status rules:
project design.

**Implementation.** `ipw.core.limits.Limit`, `ipw.core.limits.evaluate`,
`ipw.core.limits.load_limits`, `ipw.core.workbench.Workbench.metric`,
`ipw.core.workbench.Workbench.limit_report`,
`ipw.core.workbench.Workbench.limit_table`.

**Acceptance.** `test_limit_utilisation_and_status`,
`test_limit_headroom_and_validation`, `test_us4_breach_is_flagged`,
`test_sample_book_starts_with_one_breach_and_one_warning`,
`test_unknown_metric_is_an_error`.

---

## FR-11 Limit remediation

**Purpose.** Size a swap that brings a breached limit back to its bound and
show what else it changes (BR-6; RULE-7).

**Inputs.** Limit id; swap tenor (default 5 years); optional target value
(default: the breached bound); rounding step (default USD 10 million).

**Rules.** Every rate-risk metric $\mu$ is linear in the notional of an added
par swap. The metric is measured with no swap and with a probe of USD 100
million pay-fixed at today's par yield for the chosen tenor:

$$\kappa = \frac{\mu(100) - \mu(0)}{100} \tag{11.1}$$

$$N^{*} = \frac{\text{target} - \mu(0)}{\kappa} \tag{11.2}$$

The trade pays fixed if $N^{*} \ge 0$ and receives fixed otherwise, with the
notional rounded up to the step $\Delta N$:

$$N = \left\lceil \frac{\lvert N^{*} \rvert}{\Delta N} \right\rceil \Delta N \tag{11.3}$$

The swap is then added to a copy of the book (FR-13) and the limit, every
other limit, net duration and base-case income are measured again.

**Outputs.** The trade; the metric before and after; utilisation after; change
in base twelve-month income; all limits after.

**Errors.** Limit not breached and no target given; metric does not respond to
swaps ($\kappa = 0$); unknown limit.

**Source.** Project design, using the linearity of swap value in notional
(3.24).

**Implementation.** `ipw.core.workbench.Workbench.fix_limit`,
`ipw.core.workbench.LimitFix`, `ipw.core.hedging.par_swaps`.

**Acceptance.** `test_fix_limit_cures_the_breach_with_the_smallest_round_notional`,
`test_fix_limit_refuses_what_it_cannot_do`.

---

## FR-12 Hedge sizing

**Purpose.** Size par swaps that bring net duration to a target, in one tenor
or along the curve (BR-7).

**Inputs.** Target net duration $D^{*}$; mode; swap tenors.

**Rules.** DV01 to remove, with $\text{MV} = \sum_{sec} PV_0$:

$$\Delta = \text{DV01}^{\,net} - \frac{D^{*}\,\text{MV}}{10^{4}} \tag{12.1}$$

Swaps pay fixed if $\Delta \ge 0$ and receive fixed otherwise. Let $d_j$ be the
DV01 and $U_{jk}$ the key-rate DV01 of USD 1 million of the par swap of tenor
$j$ in that direction, measured as in FR-6.

*Duration mode* (one tenor):

$$n = \frac{\Delta}{-d_1} \tag{12.2}$$

*Key-rate mode* (several tenors). The net key-rate profile is scaled down in
proportion, the notionals are found by non-negative least squares, and then
rescaled so that the DV01 target is met exactly:

$$w_k = \text{KR01}_k^{\,net} \cdot \frac{\Delta}{\text{DV01}^{\,net}} \tag{12.3}$$

$$\hat{n} = \arg\min_{n \ge 0} \; \sum_k \Bigl( \sum_j (-U_{jk})\, n_j - w_k \Bigr)^{2} \tag{12.4}$$

$$n = \hat{n} \cdot \frac{\Delta}{\sum_j (-d_j)\,\hat{n}_j} \tag{12.5}$$

Notionals are rounded to USD 0.1 million. The swaps are added to a copy of the
book and net duration is measured again; that measured value is reported as
the duration after the hedge.

**Outputs.** Trades; net duration, DV01 and key-rate DV01 before and after.

**Errors.** Unknown mode; duration mode with more than one tenor; key-rate
mode on a book whose net DV01 is not positive; no non-negative combination of
the tenors moves the profile.

**Source.** (12.1), (12.2): standard DV01 hedge ratio [R1, ch. 4]. Hedging a
key-rate profile with instruments at the key tenors: [R1, ch. 5; R3]. (12.3),
proportional scaling of the profile, and (12.5): project design. (12.4):
non-negative least squares, solved with the algorithm of [R14].

**Implementation.** `ipw.core.hedging.propose_hedge`,
`ipw.core.hedging.swap_sensitivities`, `ipw.core.hedging.par_swaps`,
`ipw.core.workbench.Workbench.hedge`.

**Acceptance.** `test_us3_hedge_reaches_the_duration_target`,
`test_lengthening_the_book_means_receiving_fixed`,
`test_krd_hedge_keeps_the_curve_shape_better_than_a_single_tenor`,
`test_hedge_argument_checks`.

---

## FR-13 What-if

**Purpose.** Compare the book before and after a proposed change without
changing the book (BR-8).

**Rules.** A new book is built from the current one by removing positions by
id, adding swaps, and adding securities. A security without a mark is valued
from the quote for its sector and coupon (FR-4). All functions of this
specification apply to the new book. The comparison lists market value, AFS
unrealized, net duration, net convexity, net DV01, hedge notional, base
twelve-month income and every limit metric for both books, and their
difference.

**Errors.** Unknown position id.

**Source.** Project design.

**Implementation.** `ipw.core.workbench.Workbench.what_if`,
`ipw.core.workbench.Workbench.compare`.

**Acceptance.** `test_what_if_does_not_change_the_original`,
`test_what_if_can_add_securities`, `test_compare_reports_both_books`.

---

## FR-14 Explain

**Purpose.** Attribute the change in value since the prior close to its causes
(BR-9).

**Inputs.** Today's market and the prior close (curve, mortgage rates, marks);
the same positions on both dates.

**Rules.** Four valuations of the whole book:

| Step | Curve | Mortgage spreads $s_{30}$, $M_{15} - M_{30}$ | Static spreads |
|---|---|---|---|
| $V_0$ | Prior | Prior | Calibrated to prior marks |
| $V_1$ | Today | Prior | Prior |
| $V_2$ | Today | Today | Prior |
| $V_3$ | Today | Today | Calibrated to today's marks |

$$\text{Curve} = V_1 - V_0, \qquad \text{Mortgage basis} = V_2 - V_1, \qquad \text{Spreads} = V_3 - V_2 \tag{14.1}$$

The curve effect is split into the part predicted by the prior close's
key-rate exposures and a remainder. With $\Delta c_k$ the change in the par
yield at key tenor $k$, in basis points:

$$\text{Curve}^{\,1st} = -\sum_k \text{KR01}_k^{\,prior}\,\Delta c_k \tag{14.2}$$

$$\text{Curve}^{\,rest} = (V_1 - V_0) - \text{Curve}^{\,1st} \tag{14.3}$$

By construction the four drivers add up to the total change:

$$V_3 - V_0 = \text{Curve}^{\,1st} + \text{Curve}^{\,rest} + \text{Mortgage basis} + \text{Spreads} \tag{14.4}$$

**Outputs.** Drivers by AFS, HTM, hedges and total; curve move and first-order
effect by key rate; drivers and spread change by position.

**Errors.** No prior close available.

**Source.** Attribution by successive revaluation, with a first-order term
from risk sensitivities: standard profit-and-loss attribution [R1, ch. 3].
Order of the steps: project design.

**Implementation.** `ipw.core.explain.explain`, `ipw.core.explain.ExplainResult`,
`ipw.core.workbench.Workbench.explain`.

**Acceptance.** `test_drivers_add_up_to_the_change_between_the_two_closes`,
`test_key_rate_exposure_explains_most_of_the_curve_move`,
`test_spread_driver_matches_the_constructed_widening`,
`test_explain_needs_a_prior_close`.

---

## FR-15 Prepayment outlook

**Purpose.** Show expected borrower behaviour and its sensitivity to rates
(BR-4).

**Rules.** For each group of mortgage positions, face-weighted: WAC, today's
incentive (WAC minus today's mortgage rate for the pool's term), average life,
and one-year speed (4.7) today and after parallel shocks (default $\pm 100$
bp). A second view tabulates the model itself: turnover (3.2) and refinancing
(3.5) for a loan aged 36 months of reference size with no burnout and a
seasonal multiplier of one, over a range of incentives. Faster and slower
behaviour are standard scenarios (FR-7) through $k_R$ and $k_T$.

**Source.** Project design.

**Implementation.** `ipw.core.workbench.Workbench.prepay_table`,
`ipw.core.workbench.Workbench.s_curve`, `ipw.core.prepay.PrepayModel.s_curve`.

**Acceptance.** `test_mortgage_option_shows_up_where_it_should`,
`test_s_curve_is_increasing_in_incentive`,
`test_spread_and_prepayment_stresses_have_the_expected_sign`.

---

## FR-16 Daily brief

**Purpose.** One deterministic report for sign-off and filing (BR-10; NFR-1).

**Rules.** A Markdown document with these sections, in this order: headline;
limits, with remediation options (FR-11 at 2, 5 and 10 years) for each
breached limit; composition and valuation; interest-rate risk; scenarios; net
interest income; change since prior close (omitted when there is no prior
close); prepayment outlook; largest exposures; hedge book; method and
limitations. Every figure comes from the functions above and every sentence is
a fixed template. The text is ASCII only. The file is named
`brief_<as_of>.md`.

**Source.** Project design.

**Implementation.** `ipw.classic.brief.build_brief`, `ipw.classic.brief.write_brief`.

**Acceptance.**
`test_us5_brief_has_every_section_and_the_same_numbers_as_the_workbench`,
`test_brief_is_deterministic_and_written_to_disk`,
`test_brief_without_prior_close_skips_the_explain`.

---

## FR-17 Interfaces

**Purpose.** Make every function available from the command line and from
Python (NFR-8).

**Command line.** The program is `ipw`. Global options: `--root` (folder
holding `config/` and `data/`; otherwise found from the current folder upward
or from the environment variable `IPW_HOME`) and `--format` (`table`, `md` or
`json`).

| Command | Function | Main options |
|---|---|---|
| `ipw summary` | FR-5 | `--by` |
| `ipw position` | FR-5 | position id |
| `ipw top` | FR-5 | `--metric`, `-n`, `--asc` |
| `ipw risk` | FR-6 | `--by` |
| `ipw krd` | FR-6 | `--by`, `--unit` |
| `ipw scenario` | FR-7 | `--name`, `--shock`, `--by`, `--list` |
| `ipw nii` | FR-9 | `--scenario` |
| `ipw prepay` | FR-15 | `--by`, `--s-curve` |
| `ipw limits` | FR-10 | |
| `ipw fix` | FR-11 | limit id, `--tenors`, `--target` |
| `ipw hedge` | FR-12 | `--target-duration`, `--mode`, `--tenors` |
| `ipw whatif` | FR-13 | `--drop`, `--pay-fixed`, `--receive-fixed` |
| `ipw explain` | FR-14 | `-n` |
| `ipw brief` | FR-16 | `--out`, `--stdout` |

**Rules.** Tables are never truncated. An expected error (unknown name, bad
value, missing file) prints one line beginning `Error:` and exits with status
1. The Python interface is the class `Workbench`; each method returns a table
or a small record and formats nothing.

**Implementation.** `ipw.classic.cli.main`, `ipw.classic.render.rich_table`,
`ipw.classic.render.markdown_table`, `ipw.core.workbench.Workbench.load`.

**Acceptance.** `test_every_command_runs`, `test_json_output_is_machine_readable`,
`test_markdown_output`, `test_bad_input_gives_a_clean_error`,
`test_missing_root_is_reported`.

---

## Model parameters

All values are in `config/model.yaml`. None is calibrated to pool data.

| Parameter | Symbol | Value | Used in | Meaning |
|---|---|---|---|---|
| `horizon_months` | $T$ | 360 | all | Projection horizon |
| `default_zv_spread_bp` | | 60 | (4.3) | Spread for a mortgage position with no price |
| `turnover_cpr_pct` | $\theta$ | 6.5 | (3.2) | Base turnover, % CPR |
| `turnover_ramp_months` | $R_T$ | 30 | (3.2) | Turnover seasoning ramp |
| `lock_in_max_reduction` | $\lambda$ | 0.40 | (3.3) | Largest cut in turnover from lock-in |
| `lock_in_full_incentive_pct` | $x_L$ | 2.5 | (3.3) | Rate gap at which lock-in is complete, percentage points |
| `refi_max_cpr_pct` | $\rho_{max}$ | 45.0 | (3.5) | Refinancing plateau, % CPR |
| `refi_midpoint_pct` | $x_0$ | 1.00 | (3.5) | Incentive at half the plateau |
| `refi_slope_pct` | $w$ | 0.35 | (3.5) | Width of the S-curve |
| `refi_ramp_months` | $R_R$ | 9 | (3.7) | Refinancing seasoning ramp |
| `loan_size_ref_k` | $A_0$ | 300 | (3.6) | Reference loan size, USD thousands |
| `loan_size_elasticity` | $e$ | 0.40 | (3.6) | Response of refinancing to loan size |
| `loan_size_min_mult` | $g_{min}$ | 0.75 | (3.6) | Floor of the loan-size multiplier |
| `loan_size_max_mult` | $g_{max}$ | 1.25 | (3.6) | Cap of the loan-size multiplier |
| `burnout_exponent` | $\beta$ | 2.0 | (3.7) | Strength of burnout |
| `burnout_floor` | $q_{min}$ | 0.20 | (3.11) | Lowest starting value of $Q$ |
| `max_cpr_pct` | $\text{CPR}_{max}$ | 75.0 | (3.7), (3.12) | Cap on speed, % CPR |
| `bump_bp` | $b$ | 25 | (6.1) to (6.4) | Size of the up and down bumps |
| `tax_rate` | $\tau$ | 0.24 | (8.2) | Tax rate applied to AOCI |
| `funding_rate_pct` | $\phi_0$ | 2.60 | (9.6) | Blended funding rate today, % |
| `funding_beta` | $\beta_f$ | 0.40 | (9.6) | Pass-through of short-rate moves to funding |
| `reinvest_tenor_years` | $\tau_R$ | 5 | (9.4) | Tenor of the new-money yield |
| `reinvest_spread_bp` | $s_R$ | 60 | (9.4) | Spread of the new-money yield |
| `nii_horizon_months` | $H$ | 12 | (9.2) to (9.7) | Income horizon |

Two parameters are lists. `seasonality`, the twelve monthly multipliers $S$
from January to December used in (3.2), is 0.75, 0.77, 0.95, 1.03, 1.11, 1.18,
1.16, 1.15, 1.04, 1.01, 0.95, 0.90, which averages one. `key_tenors`, the key
rates of (1.7) and (6.4), is 1, 2, 5, 10, 20 and 30 years.

---

## Non-functional requirements

| ID | How it is met | Evidence |
|---|---|---|
| NFR-1 Reproducible and auditable | No random numbers, no clock, no network in any calculation. Every figure is a function of the input files. An independent re-implementation of FR-1 to FR-4, written from this document, reproduces single-position values. | `test_engine_price_and_speed_match_the_independent_reference`, `test_engine_scenario_value_matches_the_independent_reference`, `test_brief_is_deterministic_and_written_to_disk` |
| NFR-2 Timely | One revaluation of the 88-position book takes about 5 milliseconds; the standard shocks run in well under 5 seconds from a cold start. | `test_us1_standard_shocks_run_within_five_seconds` |
| NFR-3 Configurable | Scenarios, limits and parameters are files; unknown keys and invalid values are rejected with the file and key named. | `test_scenario_and_limit_files_are_validated`, `test_unknown_model_key_is_rejected` |
| NFR-4 Extensible | Products are registered by asset type and return a common cash-flow structure; no other function refers to a product type. | `test_unknown_asset_type_is_rejected`; inspection of `ipw.core.products.Product` |
| NFR-5 Confidential | The program opens no network connection and has no telemetry. | Inspection of dependencies and code |
| NFR-6 Honest about limitations | Each project assumption in this document appears in the limitations table of [MODEL.md](MODEL.md) with the direction of its effect; the main ones are printed on the brief. | `test_us5_brief_has_every_section_and_the_same_numbers_as_the_workbench` |
| NFR-7 Controlled change | 69 results of the sample book are stored and compared on every test run; this document is checked against the code and the configuration, so a changed assumption shows up as a failed check before it is used (RULE-10). | `test_us1_results_match_stored_values`, `test_spec_references_exist`, `test_spec_parameter_values_match_the_configuration` |
| NFR-8 Usable on the desk | Windows and Linux are both tested in continuous integration; all output is English and ASCII; tables are never truncated. | `test_every_command_runs`, `test_markdown_output`, `test_json_output_is_machine_readable` |

---

## Traceability matrix

| Business requirement | Solution design | Function | Entry point | Command | Key acceptance test |
|---|---|---|---|---|---|
| BR-1 Holdings and value | SD-1, SD-2 | FR-0 to FR-5 | `ipw.core.workbench.Workbench.summary` | `ipw summary` | `test_calibration_reprices_every_mbs_to_its_mark` |
| BR-2 Rate risk and location | SD-4 | FR-6 | `ipw.core.workbench.Workbench.risk_table` | `ipw risk`, `ipw krd` | `test_us2_key_rate_durations_add_up_to_effective_duration` |
| BR-3 Effect of market moves | SD-5, SD-6, SD-7 | FR-7, FR-8, FR-9 | `ipw.core.workbench.Workbench.run` | `ipw scenario`, `ipw nii` | `test_us4_htm_positions_never_reach_aoci` |
| BR-4 Prepayment behaviour | SD-3 | FR-3.1, FR-15 | `ipw.core.workbench.Workbench.prepay_table` | `ipw prepay` | `test_mortgage_option_shows_up_where_it_should` |
| BR-5 Limit monitoring | SD-8 | FR-10 | `ipw.core.workbench.Workbench.limit_report` | `ipw limits` | `test_us4_breach_is_flagged` |
| BR-6 Remediation options | SD-9 | FR-11 | `ipw.core.workbench.Workbench.fix_limit` | `ipw fix` | `test_fix_limit_cures_the_breach_with_the_smallest_round_notional` |
| BR-7 Hedge sizing | SD-10 | FR-12 | `ipw.core.workbench.Workbench.hedge` | `ipw hedge` | `test_us3_hedge_reaches_the_duration_target` |
| BR-8 Before and after | SD-11 | FR-13 | `ipw.core.workbench.Workbench.what_if` | `ipw whatif` | `test_what_if_does_not_change_the_original` |
| BR-9 Explanation of change | SD-12 | FR-14 | `ipw.core.workbench.Workbench.explain` | `ipw explain` | `test_drivers_add_up_to_the_change_between_the_two_closes` |
| BR-10 Daily brief | SD-13 | FR-16 | `ipw.classic.brief.build_brief` | `ipw brief` | `test_us5_brief_has_every_section_and_the_same_numbers_as_the_workbench` |
| NFR-1 to NFR-8 | SD-14 | FR-0, FR-17 | `ipw.classic.cli.main` | all | See the table above |

---

## References

| | |
|---|---|
| R1 | Tuckman, B. and Serrat, A. (2022). *Fixed Income Securities: Tools for Today's Markets*, 4th edition. Wiley. Chapters 1 (Prices, Discount Factors, and Arbitrage), 2 (Swap, Spot, and Forward Rates), 3 (Returns, Yields, Spreads, and P&L Attribution), 4 (DV01, Duration, and Convexity), 5 (Key-Rate-, Partial-, and Forward-Bucket '01s and Durations), 13 (Interest Rate Swaps). |
| R2 | Hagan, P. S. and West, G. (2006). Interpolation Methods for Curve Construction. *Applied Mathematical Finance* 13(2), 89-129. |
| R3 | Ho, T. S. Y. (1992). Key Rate Durations: Measures of Interest Rate Risks. *Journal of Fixed Income* 2(2), 29-44. |
| R4 | The Bond Market Association, now SIFMA (1999). *Uniform Practices*, Chapter SF: Standard Formulas for the Analysis of Mortgage-Backed Securities and Other Related Securities. |
| R5 | Richard, S. F. and Roll, R. (1989). Prepayments on Fixed-Rate Mortgage-Backed Securities. *Journal of Portfolio Management* 15(3), 73-82. |
| R6 | Schwartz, E. S. and Torous, W. N. (1989). Prepayment and the Valuation of Mortgage-Backed Securities. *Journal of Finance* 44(2), 375-392. |
| R7 | Stanton, R. (1995). Rational Prepayment and the Valuation of Mortgage-Backed Securities. *Review of Financial Studies* 8(3), 677-708. |
| R8 | Fonseca, J. and Liu, L. (2024). Mortgage Lock-In, Mobility, and Labor Reallocation. *Journal of Finance* 79(6), 3729-3772. |
| R9 | Fabozzi, F. J., editor (2016). *The Handbook of Mortgage-Backed Securities*, 7th edition. Oxford University Press. Chapters 3 (Cash Flow Mathematics for Agency Mortgage-Backed Securities) and 24 (Valuation of Mortgage-Backed Securities). |
| R10 | FASB Accounting Standards Codification, paragraph 310-20-35-26 (interest method with anticipated prepayments). |
| R11 | FASB Accounting Standards Codification, Topic 320, Investments - Debt Securities. |
| R12 | FASB Accounting Standards Codification, paragraphs 815-25-35-1 to 35-6 (fair-value hedges). |
| R13 | Drechsler, I., Savov, A. and Schnabl, P. (2017). The Deposits Channel of Monetary Policy. *Quarterly Journal of Economics* 132(4), 1819-1876. See also the same authors, Banking on Deposits: Maturity Transformation without Interest Rate Risk, *Journal of Finance* (2021). |
| R14 | Lawson, C. L. and Hanson, R. J. (1995). *Solving Least Squares Problems*. SIAM. Implemented in `scipy.optimize.nnls`. |
| R15 | Kang, P. and Zenios, S. A. (1992). Complete Prepayment Models for Mortgage-Backed Securities. *Management Science* 38(11), 1665-1685. |
| R16 | Board of Governors of the Federal Reserve System (2010). SR 10-1, Interagency Advisory on Interest Rate Risk Management. |
| R17 | Board of Governors of the Federal Reserve System (2026). SR 26-2, Revised Guidance on Model Risk Management, issued with OCC Bulletin 2026-13 and FDIC FIL-15-2026; supersedes SR 11-7. |

R6 and R17 are background: R6 is the companion academic treatment of
prepayment in valuation, and R17 is the guidance under which a model of this
kind would be documented and validated.
