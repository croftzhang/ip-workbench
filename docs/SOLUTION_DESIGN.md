# Solution Design

**Investment Portfolio Risk Analytics**

| | |
|---|---|
| Document | Solution design, version 1.0 |
| Status | Baseline for release 1 |
| Owner | Product Owner, Investment Portfolio analytics |
| Last updated | 2026-11-10 |
| Reads from | [BRD.md](BRD.md) |
| Feeds | [FUNCTIONAL_SPEC.md](FUNCTIONAL_SPEC.md) |

> The desk and all figures are illustrative.

## 1. Purpose

The business requirements say what the desk needs. This document turns each
need into an analytical question, sets out the ways it could be answered, and
records which one was chosen and what that choice costs. The functional
specification then defines the chosen solution precisely enough to build and
test.

Each section below follows the same pattern: the business need, the analytical
question behind it, the options considered, the decision, and what is left for
later.

## 2. The solution in one page

One calculation engine holds every formula. Everything a user sees is produced
by revaluing the whole book under some change to the market and comparing the
result with today.

```text
 marks, curve, mortgage rates        positions and hedges        parameters, scenarios, limits
            |                                 |                              |
            +---------------> rate environment (one path: forwards realised)
                                      |
                 each product projects its cash flows on that path
                                      |
                 discount on the curve plus a spread calibrated to the mark
                                      |
                        one revaluation of the whole book
                                      |
     risk measures | scenarios | AOCI | income | limits | hedge sizes | what-if | explain | brief
```

Design principles that follow from the business requirements:

| Principle | Comes from |
|---|---|
| One engine is the only source of numbers; every interface is a thin layer on it | O2, NFR-1 |
| Marks are reproduced, never replaced | RULE-1 |
| Every sensitivity is a difference of full revaluations, so borrower behaviour is always re-estimated | BR-2, BR-4 |
| Scenarios, limits and parameters are data, checked when loaded | NFR-3 |
| A product only has to say what it pays; nothing else knows which product it is | NFR-4 |
| The system proposes and verifies; it never executes | RULE-7 |
| A change in any stored result fails a test | NFR-7 |

## 3. From business need to function

| Business requirement | Analytical question | Functions (functional specification) |
|---|---|---|
| BR-1 Holdings and value against book | What is each position worth at its mark, and what is the gain or loss by accounting class? | FR-1 to FR-5 |
| BR-2 Rate risk and its location | How does value change for a small parallel move and for a move at each maturity point, with prepayments re-estimated? | FR-6 |
| BR-3 Effect of market moves | What are value, AOCI and twelve-month income after a defined shock? | FR-7, FR-8, FR-9 |
| BR-4 Prepayment behaviour and its uncertainty | What speeds does the model expect by coupon, and what if behaviour is faster or slower? | FR-3.1, FR-7, FR-15 |
| BR-5 Limit monitoring | Where is each policy metric relative to its bound and its warning level? | FR-10 |
| BR-6 Remediation options | What trade brings the breached metric back, and what else does it change? | FR-11 |
| BR-7 Hedge sizing | What swap notionals reach a duration target, in one maturity or along the curve? | FR-12 |
| BR-8 Before-and-after comparison | What do value, risk, income and limits look like with the proposed change? | FR-13 |
| BR-9 Explanation of change | How much of the change since the prior close is due to the curve, to mortgage rates, to spreads? | FR-14 |
| BR-10 Daily brief | One deterministic report of all the above | FR-16 |
| BR-11 to BR-13 | Release 2 | See the product roadmap in [PRD.md](PRD.md) |

## 4. Options and decisions

### SD-1. How to value mortgage securities (BR-1, BR-2, BR-3)

**Question.** A pass-through's cash flows depend on future rates through
prepayments. What valuation method gives value and risk that respond to rates
the way the security does?

| Option | For | Against |
|---|---|---|
| A. Cash-flow yield at a fixed prepayment speed | Simple; widely understood | Speed does not respond to rates, so duration ignores the prepayment option. Fails BR-2 |
| B. One path on which today's forward rates are realised, speeds from a prepayment model, discounting at a spread calibrated to the price (zero-volatility spread) | Speeds respond to every shock; fast; exactly reproducible; small enough to read and validate | Rate volatility has no value, so there is no option cost. Durations of coupons near the refinancing threshold come out longer than option-adjusted durations |
| C. Monte Carlo over rate paths with an option-adjusted spread | Market standard for mortgage risk; prices the option | Needs a calibrated rate model and volatility data; slower; much more to validate |

**Decision: B.** It meets BR-2 through re-estimated prepayments and meets
NFR-1 and NFR-2 comfortably. The bias is known in direction and documented
(NFR-6). The product interface is the one a path-based pricer would call, so C
can be added without changing products or reports.

**Deferred.** Option-adjusted valuation.

### SD-2. Where today's value comes from (BR-1, RULE-1)

**Question.** Should the engine compute a price, or start from one?

| Option | For | Against |
|---|---|---|
| A. Assume a spread per sector and compute the price | No price data needed | The engine's value differs from the official mark. Breaks RULE-1 |
| B. Calibrate to a quote per coupon | Matches the coupon stack | All pools of one coupon get one price; older pools then show implausible spreads |
| C. Calibrate each position's spread to its own mark; use the coupon quote only where there is no mark | Reproduces the marks exactly; a change in spread becomes a measurable driver for BR-9 | The engine cannot value a position that has no price, except at a default spread |

**Decision: C.** Option B was tried first and rejected when positions of the
same coupon showed spreads from 7 to 61 basis points.

### SD-3. How to represent borrower behaviour (BR-4)

**Question.** What prepayment model is transparent enough to explain and rich
enough to show the behaviours that matter today?

| Option | For | Against |
|---|---|---|
| A. Constant speed or a multiple of the PSA benchmark | Trivial | No response to rates |
| B. A vendor prepayment model | Calibrated to pool data; industry acceptance | Licence required; a black box to the desk; cannot be published or read |
| C. A small in-house model: housing turnover plus a refinancing S-curve, with seasoning, seasonality, lock-in, loan size and burnout, every parameter in a file | Every term is one line; the behaviours in BR-4 are all present; stress multipliers come for free | Not calibrated to pool data; levels are plausible, not fitted |

**Decision: C,** with faster and slower behaviour as standard scenarios so the
exposure to model error is always on the report. In a production setting the
model would be benchmarked against a vendor model before use.

### SD-4. Which risk measures, and on which curve (BR-2)

**Question.** How should exposure along the curve be measured so that it maps
to the instruments used to hedge?

| Option | For | Against |
|---|---|---|
| A. Modified duration from yield | Simple | Assumes fixed cash flows |
| B. Bump and revalue; key rates on zero rates | Standard textbook form | A par hedge instrument spreads over several key rates |
| C. Bump and revalue; key rates on par yields | A par swap loads on its own key rate, so the report reads directly as a hedge | Long single cash flows can show small negative exposures at shorter key rates |

**Decision: C.** Six key tenors: 1, 2, 5, 10, 20 and 30 years.

### SD-5. How scenarios are defined (BR-3, BR-4, RULE-8, NFR-3)

| Option | For | Against |
|---|---|---|
| A. A fixed list of shocks in code | Quick | Every new scenario is a development request. Fails NFR-3 |
| B. A scenario is data with six optional parts: parallel move, curve-shape points, MBS spread move, mortgage-spread move, refinancing multiplier, turnover multiplier | Risk staff compose scenarios; combined scenarios need no code | Only shocks expressible in those six parts |

**Decision: B.** Any parallel shock can also be run ad hoc without being listed.

### SD-6. The equity view (BR-3, RULE-2, RULE-3, RULE-4)

| Option | For | Against |
|---|---|---|
| A. Report total value change only | Simple | Mixes what reaches equity with what does not |
| B. Split by accounting class; AOCI from AFS only, net of designated swaps, after tax | Matches how the figure is reported and limited | Assumes hedges are fully effective |

**Decision: B.**

### SD-7. The earnings view (BR-3, RULE-5, RULE-9)

| Option | For | Against |
|---|---|---|
| A. Coupon income only | Trivial | Ignores premium amortisation, funding and hedges |
| B. Effective-yield income, reinvestment of principal, hedge carry, and funding at a blended rate that follows short rates with a beta | Shows each source of the change separately; consistent with the scenario's prepayments | The funding side is a stylised assumption |
| C. The bank-wide income simulation | Complete | Owned by Treasury; out of scope |

**Decision: B.** The decomposition is always shown so a reader can remove the
funding assumption.

### SD-8. Limits (BR-5, RULE-6, NFR-3)

| Option | For | Against |
|---|---|---|
| A. Checks written in code | Quick | Every policy change is a development request |
| B. A limit is data: a metric, an optional scenario, a floor or cap or both, a warning level, a policy reference | Policy changes are edits to a file; any metric can be limited under any scenario | A limit can only use metrics the engine exposes |

**Decision: B.**

### SD-9. Remediation of a breach (BR-6, RULE-7)

**Question.** How should the size of a curing trade be found?

| Option | For | Against |
|---|---|---|
| A. Flag the breach; leave sizing to the user | Nothing to build | This is problem P4 |
| B. Numerical search over hedge size | General | Slow; needs tolerances; hard to explain |
| C. Use the fact that swap value is linear in notional: two evaluations give the size; round up; confirm by full revaluation | Exact for every rate-risk limit; fast; the verification is the acceptance test | Limits that swaps cannot move (composition) need a different remedy |

**Decision: C,** offered at several maturities so the manager sees alternatives
and their cost. Limits that do not respond to swaps are refused with a message.

**Deferred.** Choosing among sales as remedies; the what-if (SD-11) supports a
manual trial.

### SD-10. Hedge sizing and instruments (BR-7)

| Option | For | Against |
|---|---|---|
| A. One swap sized to the DV01 gap | Simple; one trade | Removes exposure at one maturity only |
| B. Several swaps chosen by non-negative least squares to scale the key-rate profile down in proportion | Keeps the shape of the exposure | Several trades |
| Instruments: swaps only | Linear, no delivery options | Valued on the Treasury curve; swap spreads ignored |
| Instruments: add Treasury futures | Used in practice | Needs cheapest-to-deliver modelling |

**Decision.** Offer A and B and show the key-rate profile before and after.
Swaps only.

**Deferred.** Treasury futures; a separate swap curve.

### SD-11. What-if (BR-8)

| Option | For | Against |
|---|---|---|
| A. Edit the book, measure, undo | Cheap | A failed undo corrupts the book |
| B. Build a second book and compare | The actual book cannot be changed; both pictures are available | Recomputes the book, which takes a fraction of a second |

**Decision: B.**

### SD-12. Explaining a change (BR-9)

| Option | For | Against |
|---|---|---|
| A. Risk-report attribution only: exposure times move | One calculation | Leaves an unexplained remainder with no way to size it |
| B. Move the market in steps with a full revaluation after each; split the curve step into the part predicted by the key-rate report and a remainder | Causes add up exactly; the remainder measures how well the risk report described the day | Result depends on the order of steps for cross effects, which are small for daily moves |

**Decision: B,** in the order curve, mortgage-rate basis, spreads.

### SD-13. The daily brief (BR-10, NFR-1)

| Option | For | Against |
|---|---|---|
| A. Written by an analyst | Flexible | This is problem P1 |
| B. A fixed template filled from the engine | Deterministic; identical inputs give an identical document | Commentary is formulaic |

**Decision: B** for release 1. Narrative commentary is a release 2 item and
will annotate this brief, not replace its numbers.

### SD-14. Form of delivery (RULE-10, NFR-1, NFR-3, NFR-5, NFR-7, NFR-8)

| Choice | Decision | Reason |
|---|---|---|
| Interface | Command line and a programming interface; table, Markdown and JSON output | Scriptable, auditable, no server; a graphical interface can be added on the same functions |
| Configuration | Text files for market, model, scenarios, limits; unknown entries rejected | NFR-3 |
| Where it runs | Entirely on the user's machine | NFR-5 |
| Change control | A stored baseline of about seventy results compared on every test run; parameter values in the specification checked against the configuration | RULE-10, NFR-7 |
| Verification | An independent re-implementation of the valuation chain, written from the specification | NFR-1; supports validation |

## 5. Valuation approach by product

| Product | Cash flows | Discounting | Calibration | Main simplifications | Specification |
|---|---|---|---|---|---|
| Agency pass-through, 30- and 15-year fixed | Level-payment amortisation; prepayments from the model in SD-3; investor receives the net coupon | Treasury curve plus a static spread | Spread solved from the position's mark | No option cost; no payment delay; constant WAC | FR-3.1, FR-4 |
| Treasury note or bond | Semi-annual coupons and principal; accrued interest | Treasury curve | None; valued on the fitted curve | Individual marks are not reproduced exactly | FR-3.2, FR-4 |
| Fixed-for-floating swap | Floating leg at one-month forwards; fixed leg semi-annual | Treasury curve | None; a swap at the par yield is worth zero | Swap spreads ignored | FR-3.3, FR-4 |

## 6. Products considered and left for later

| Product | What is missing | Why it waits |
|---|---|---|
| Mortgage servicing rights | A servicing-strip cash-flow definition; it can reuse the prepayment model | Not held in the investment portfolio book in scope; highly option-like, so the static method is weakest here |
| Adjustable-rate mortgage securities | Coupon resets from forward rates, caps and floors | Not in the book |
| Agency CMO | A tranche waterfall on top of the pass-through cash flows | Not in the book; the waterfall is the work |
| Commercial and non-agency mortgage securities | Default and loss models, prepayment penalties, waterfalls | Credit risk is out of scope |
| Callable agency debt, caps, swaptions | A volatility model | Cannot be valued on one path |

## 7. Risks of this design

| Risk | Effect | Mitigation |
|---|---|---|
| No option cost | Duration of at-the-money coupons overstated; negative convexity understated | Stated on the brief and in the model document; option-adjusted valuation is the first item on the deferred list |
| Uncalibrated prepayment model | Speeds right in shape, uncertain in level | Faster and slower behaviour are standard scenarios; parameters are in one file |
| Swaps on the Treasury curve | Hedge sizes approximate | Proposals are labelled indicative and need approval (RULE-7) |
| Stylised funding assumption | Income sensitivity depends on an assumed pass-through | Decomposition shown; the beta is one parameter |

Engineering decisions that do not change what the business sees (vectorised
calculation, facade, immutability, output conventions) are recorded in
[DECISIONS.md](DECISIONS.md).
