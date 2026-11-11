# Agency MBS Primer

**Investment Portfolio desk**

| | |
|---|---|
| Document | Primer on agency mortgage-backed securities, version 1.0 |
| Cited as | MBS and the section number, for example MBS 2.3 |
| Role | Knowledge base of the assistant: embedded and retrieved |
| Status | Constructed for this repository, consistent with the engine's prepayment model |

> The desk and every figure in this document are illustrative. Parameter
> values of the prepayment model are in the functional specification, not
> here.

## 1. What a pass-through is

An agency mortgage pass-through is a share in a pool of home loans. Each month
borrowers pay interest and principal, and the pool passes both through to
investors after a servicing and guarantee fee. Timely payment is guaranteed by
the agency (FNMA, FHLMC or GNMA), so the investor's risks are interest rates
and the timing of principal, not credit.

Terms used for a pool:

| Term | Meaning |
|---|---|
| Coupon | The rate paid to investors |
| WAC | Weighted-average coupon: the average rate borrowers pay. It is higher than the coupon by the fees |
| WALA | Weighted-average loan age, in months |
| WAM | Weighted-average remaining term, in months |
| Factor | The share of the original balance still outstanding |
| Current face | Original face multiplied by the factor |

The portfolio holds 30-year and 15-year fixed-rate pools.

## 2. Prepayments

A borrower may repay a loan early at any time and without penalty. Principal
arrives earlier or later than scheduled depending on what borrowers do, and
what they do depends on rates.

### 2.1 Measuring speed

Speed is quoted as CPR, the conditional prepayment rate: the share of the
balance at the start of a year that would be prepaid over the year at the
current monthly pace. The monthly rate is SMM, the single monthly mortality.
A CPR of 6% means that about 6% of the pool is prepaid over a year.

### 2.2 Housing turnover

People sell their homes for reasons that have little to do with rates, and the
loan is repaid when they do. Turnover gives every pool a base speed. Three
things shape it.

* **Seasoning.** New loans prepay slowly; turnover rises over the first years
  of a loan's life.
* **Seasonality.** Homes are sold more in summer than in winter.
* **Lock-in.** A borrower whose loan rate is far below the market rate would
  give up a cheap loan by moving, and so moves less often. Turnover falls as
  the gap grows.

### 2.3 Refinancing

A borrower whose loan rate is above the market rate can save by refinancing.
The rate incentive is the pool's WAC less the current mortgage rate, in
percentage points. The response to it has the shape of an S-curve: close to
nothing when the incentive is negative, rising steeply once the incentive
passes a threshold, and levelling off at a plateau when almost every borrower
who can refinance has reason to.

Two further effects are modelled. Larger loans refinance faster, because the
saving in dollars is larger against a fixed cost. New loans do not refinance
immediately.

### 2.4 Burnout

A pool that has been through a period of high incentive has already lost its
most rate-sensitive borrowers. Those who remain respond less to the same
incentive. This is burnout: the refinancing response of a seasoned pool that
has had the chance to refinance is weaker than that of a new pool.

## 3. Negative convexity

A plain bond gains more when rates fall than it loses when rates rise by the
same amount. A mortgage security often does the opposite.

* **Contraction.** When rates fall, refinancing speeds up, principal comes
  back early and has to be reinvested at lower yields. The security shortens
  and its price rises less than a bond's would.
* **Extension.** When rates rise, refinancing stops and lock-in slows
  turnover. Principal comes back later, the security lengthens, and its price
  falls more.

The duration of a mortgage portfolio therefore drifts as rates move: shorter
in a rally, longer in a sell-off. The Investment Policy Statement limits that
drift in section 4.2.

## 4. How coupons differ

| Coupon against the market | Incentive | Behaviour |
|---|---|---|
| Far below | Strongly negative | Locked in: slow, stable speeds, long duration, little refinancing risk; the price is well below par |
| Near the refinancing threshold | Around zero to slightly positive | Most sensitive: speeds change quickly with rates, and convexity is most negative |
| Well above | Strongly positive | Fast speeds until burnout sets in; short duration |

The portfolio groups its 30-year and 15-year pools into low, mid and high
coupon buckets for this reason.

## 5. Risk measures for mortgage securities

Because cash flows change with rates, the measures have to be effective
measures: the security is revalued after a shock with prepayments projected
again, not with the cash flows held fixed.

| Measure | Meaning |
|---|---|
| Effective duration | Percentage change in value for a one percentage point parallel move in rates |
| Effective convexity | How much duration changes as rates change; negative for most mortgage securities |
| DV01 | Dollar change in value for a one basis point move |
| Key-rate duration | The part of duration that belongs to one maturity point of the curve |
| WAL | Weighted-average life: the average time until principal is returned, in years |

## 6. Value and spread

Each position is valued at its end-of-day mark. The analytics find the spread
over the Treasury curve at which the projected cash flows discount to that
mark, and hold the spread constant when rates are shocked.

That spread is a zero-volatility (static) spread on one rate path. It is not
an option-adjusted spread: no value is given to the volatility of rates, so
the durations of coupons near the refinancing threshold are longer than
option-adjusted durations and their negative convexity is understated.

## 7. Reading the prepayment outlook

The prepayment outlook shows, for each coupon bucket, the rate incentive and
the projected one-year CPR today and after parallel shocks. A bucket whose
speed barely changes across shocks is locked in. A bucket whose speed rises
sharply when rates fall is near the refinancing threshold and is where
contraction risk sits.

The scenarios `prepay_fast` and `prepay_slow` show what happens to value and
risk if borrowers behave differently from the model.
