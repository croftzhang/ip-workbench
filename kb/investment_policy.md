# Investment Policy Statement

**Investment Portfolio desk**

| | |
|---|---|
| Document | Investment Policy Statement (IPS), version 1.0 |
| Cited as | IPS and the section number, for example IPS 4.3 |
| Role | Knowledge base of the assistant: embedded and retrieved |
| Status | Constructed for this repository; the limits equal `config/limits.yaml` |

> The desk, its roles, its limits and every figure in this document are
> illustrative. They do not describe any institution.

## 1. Purpose and scope

This policy states what the Investment Portfolio may hold, how its holdings
are classified, the limits on its interest-rate risk, and what happens when a
limit is approached or breached.

It covers the securities portfolio, both available-for-sale (AFS) and
held-to-maturity (HTM), and the interest-rate swaps that hedge it. Credit
risk, liquidity risk and regulatory capital are governed by other policies.

## 2. Roles and responsibilities

| Role | Responsibility under this policy |
|---|---|
| Board | Approves the policy and every limit in it |
| Head of Investment Portfolio | Keeps the portfolio inside the limits; receives every breach report |
| Portfolio managers | Decide what to buy, sell and hedge; approve every proposal before it is acted on |
| Portfolio analysts | Produce the daily risk view and the limit report |
| Market risk oversight (second line) | Reviews limits and stress results independently; receives every breach report |
| Model risk management | Validates the models that produce the measures |
| Accounting policy | Decides the classification of securities and the designation of hedges |

## 3. Eligible investments and classification

### 3.1 Eligible securities

The portfolio may hold fixed-rate agency mortgage pass-through securities with
original terms of 30 and 15 years, and US Treasury notes and bonds. Mortgage
servicing rights, collateralised mortgage obligations, commercial and
non-agency mortgage securities are not eligible under this policy.

### 3.2 Held-to-maturity share

The book value of HTM securities may not exceed 80% of the book value of all
securities (limit `HTM_SHARE`).

HTM securities are carried at amortised cost, cannot be sold without calling
the classification into question, and cannot be the hedged item in a hedge of
interest-rate risk. The cap keeps enough of the portfolio in AFS, where it can
be sold or hedged, to manage the limits of section 4.

### 3.3 Classification at purchase

A security is classified as AFS or HTM when it is bought. Classification is a
decision of accounting policy and is described in the accounting note on AFS
and HTM securities. The analytics take the classification from the position
file and do not change it.

## 4. Interest-rate risk limits

Every limit is measured each business day on closing marks. Measures are
effective measures: prepayments are re-projected when rates are shocked.
Unless a limit says otherwise, measures are net of hedges. Shocks are the
instantaneous shocks of the scenario definitions.

| Section | Limit id | Measure | Bound |
|---|---|---|---|
| 3.2 | `HTM_SHARE` | HTM share of book value | At most 80% |
| 4.1 | `DUR_BAND` | Net effective duration | 3.0 to 5.5 years |
| 4.2 | `DUR_DRIFT_DN100` | Change in net duration, rates down 100bp | No lower than -0.80 years |
| 4.2 | `DUR_DRIFT_UP100` | Change in net duration, rates up 100bp | No higher than 0.50 years |
| 4.2 | `CONVEXITY` | Net effective convexity | No lower than -0.50 |
| 4.3 | `AOCI_UP200` | After-tax AOCI change, rates up 200bp | No lower than USD -210 million |
| 4.4 | `EVE_UP200` | Economic value change, rates up 200bp | No lower than -13.0% |
| 4.5 | `NII_UP100` | 12-month NII change, rates up 100bp | No lower than USD -30 million |
| 4.5 | `NII_DN100` | 12-month NII change, rates down 100bp | No lower than USD -30 million |

### 4.1 Net effective duration

The effective duration of the securities net of hedges must stay between 3.0
and 5.5 years (limit `DUR_BAND`).

The floor keeps the portfolio earning a term premium; the cap bounds the loss
of economic value and of AOCI when rates rise. A band is used, not only a cap,
because mortgage securities shorten when rates fall.

### 4.2 Duration drift and convexity

Mortgage securities change duration as rates move. Three limits bound that
change.

* In an instantaneous parallel fall of 100bp, net duration may not shorten by
  more than 0.80 years (limit `DUR_DRIFT_DN100`, a floor of -0.80 years on the
  change).
* In an instantaneous parallel rise of 100bp, net duration may not lengthen by
  more than 0.50 years (limit `DUR_DRIFT_UP100`, a cap of 0.50 years on the
  change).
* Net effective convexity may not be lower than -0.50 (limit `CONVEXITY`).

A portfolio that breaches these limits needs larger and more frequent hedge
adjustments than the desk is prepared to make.

### 4.3 AOCI sensitivity

In an instantaneous parallel rise of 200bp, the after-tax change in AOCI may
not be a loss of more than USD 210 million (limit `AOCI_UP200`, a floor of
USD -210 million).

The measure covers AFS securities only, net of the swaps designated as
fair-value hedges of AFS securities, and is stated after tax. HTM securities
never enter it. This is the limit that protects reported equity.

### 4.4 Economic value

In an instantaneous parallel rise of 200bp, the market value of all securities
and hedges, AFS and HTM together, may not fall by more than 13.0% of the
market value of the securities (limit `EVE_UP200`, a floor of -13.0%).

HTM securities are included because a loss of value on them is an economic
loss even though it does not reach equity.

### 4.5 Earnings at risk

Net interest income over the next twelve months, on a constant balance sheet,
may not fall by more than USD 30 million in an instantaneous parallel rise of
100bp (limit `NII_UP100`) or in an instantaneous parallel fall of 100bp (limit
`NII_DN100`). Each is a floor of USD -30 million on the change from the base
case.

## 5. Monitoring, warnings and breaches

### 5.1 Daily measurement

Each limit is measured every business day and shown in the daily brief with
its value, its bound, the share of the allowance used (utilisation) and its
status: OK, WARN or BREACH.

### 5.2 Warning level

A limit is in warning when its utilisation reaches 80%. A warning is reported
in the daily brief. It calls for attention, not for action: its purpose is
that a breach is anticipated and not discovered.

### 5.3 Breach

A limit is breached when its value is outside its bound. A breach is reported
on the day it is measured, to the Head of Investment Portfolio and to market
risk oversight, together with a remediation proposal. The proposal holds at
least two sized options, each with its cost to income and its effect on every
other limit.

### 5.4 Remediation and approval

A breach of a limit in section 4 is remedied by hedging AFS securities with
swaps under the hedging policy, or by selling or repositioning AFS securities.
HTM securities are not sold and not hedged to cure a breach.

The analytics propose and people decide. Every proposal is indicative until a
portfolio manager approves it. The analytics create no trade, no hedge
designation and no limit exception.

### 5.5 Exceptions

An exception to a limit is a decision of the body that approved the limit. It
is made and recorded outside the analytics.

## 6. Scenarios the limits use

| Limit | Scenario | Shock |
|---|---|---|
| `DUR_DRIFT_DN100`, `NII_DN100` | `dn_100` | Parallel fall of 100bp |
| `DUR_DRIFT_UP100`, `NII_UP100` | `up_100` | Parallel rise of 100bp |
| `AOCI_UP200`, `EVE_UP200` | `up_200` | Parallel rise of 200bp |
| `DUR_BAND`, `CONVEXITY`, `HTM_SHARE` | None | Measured on today's market |

The scenarios are defined in the scenario definitions document.
