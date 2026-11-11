# Hedging Policy

**Investment Portfolio desk**

| | |
|---|---|
| Document | Hedging Policy, version 1.0 |
| Cited as | HEDGE and the section number, for example HEDGE 3.1 |
| Role | Knowledge base of the assistant: embedded and retrieved |
| Status | Constructed for this repository, consistent with the engine's hedge sizing |

> The desk, its roles and every figure in this document are illustrative. They
> do not describe any institution.

## 1. Purpose and scope

This policy states which instruments the Investment Portfolio may use to hedge
interest-rate risk, what may be hedged, how a hedge is sized, and who approves
it. It supports the limits of the Investment Policy Statement, section 4.

## 2. Permitted instruments

The desk hedges with plain fixed-for-floating interest-rate swaps in US
dollars, entered at the par rate so that the swap has no value at inception.

* A pay-fixed swap gains value when rates rise. It shortens the net duration
  of the portfolio and reduces the loss of AOCI in a sell-off.
* A receive-fixed swap gains value when rates fall. It lengthens net duration.

Options, swaptions and futures are not covered by this policy and are not
sized by the analytics.

## 3. What may be hedged

### 3.1 Available-for-sale securities only

Only AFS securities are hedged. Every swap is designated against AFS
securities.

### 3.2 Held-to-maturity securities

HTM securities are not hedged. Under hedge accounting an HTM security cannot
be the hedged item in a hedge of interest-rate risk. Their rate risk is
managed through the HTM share cap of the Investment Policy Statement, section
3.2, and through the economic value limit, section 4.4, which includes them.

## 4. Designation and accounting effect

Swaps are designated as fair-value hedges of AFS securities. In a fair-value
hedge the gain or loss on the swap and the offsetting change in the value of
the hedged security are both recognised in earnings, so only the unhedged part
of the change in AFS value reaches AOCI.

For this reason AOCI sensitivity is measured net of the designated swaps. The
analytics treat a designated hedge as fully effective. Hedge documentation and
effectiveness testing are the responsibility of accounting policy and are
outside the analytics.

## 5. Sizing a hedge

### 5.1 To a duration target

A hedge can be sized to bring net effective duration to a chosen target. With
one swap tenor, the notional is chosen so that the net DV01 of the portfolio
equals the DV01 implied by the target duration. The swap pays fixed when
duration has to come down and receives fixed when it has to go up. The result
is confirmed by adding the swap to a copy of the book and measuring duration
again.

### 5.2 Along the curve

A hedge in one tenor removes exposure at one point of the curve and leaves the
rest, which changes the shape of the key-rate profile. A hedge can instead be
spread over several tenors so that the whole key-rate profile is scaled down
in proportion. The portfolio manager sees both and chooses.

### 5.3 To restore a limit

When a limit is breached, the hedge is the smallest swap notional, in steps of
USD 10 million, that brings the limit back to its bound. It is sized for
several tenors, by default 2, 5 and 10 years, and each option is shown with
the limit after the trade, net duration, the change in twelve-month income and
the number of limits still breached.

A limit that does not respond to swaps, such as the HTM share, cannot be
restored by a hedge and needs a change in positions.

## 6. Choosing among options

Options that restore the same limit differ in three ways the portfolio manager
weighs.

* **Notional.** A shorter swap has less DV01 per dollar of notional, so more
  notional is needed.
* **Cost to income.** A pay-fixed swap pays the fixed rate and receives the
  floating rate. Its carry over the next twelve months is the difference
  between the two and is part of net interest income.
* **Curve shape.** Each tenor changes a different part of the key-rate
  profile.

## 7. Approval and execution

Every hedge size produced by the analytics is indicative. A portfolio manager
approves a hedge before it is executed. Execution, designation and
documentation happen outside the analytics, which create no trade and no hedge
designation.

## 8. Limits of the hedge analytics

* Swaps are valued on the Treasury curve. Swap spreads and swap-spread risk
  are ignored, and the par swap rate is the Treasury par yield of the same
  tenor. Hedge sizes are therefore approximate.
* Designated hedges are treated as fully effective. Hedge ineffectiveness is
  not modelled, which understates the volatility of AOCI.
