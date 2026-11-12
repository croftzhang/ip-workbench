# Product Backlog

**Investment Portfolio Risk Analytics**

Owner: Product Owner, Investment Portfolio analytics. Last updated 2026-11-11.

Items are ordered by priority within each release. Each story names the
business requirement it serves ([BRD.md](BRD.md)); the full story text and
acceptance criteria are in [PRD.md](PRD.md), and the functions are specified in
[FUNCTIONAL_SPEC.md](FUNCTIONAL_SPEC.md). The design of release 2 is in
[AGENT_DESIGN.md](AGENT_DESIGN.md).

Priority: M must have, S should have, C could have.

## Definition of done

A story is done when its functions are specified with formulas and sources, its
acceptance tests pass, the stored regression baseline has been reviewed if any
result changed, lint and tests pass on Windows and Linux, the user-facing
documents are updated, and the matching acceptance case in [UAT.md](UAT.md)
passes.

## Release 1: the routine daily tool (delivered)

| # | Story | Serves | Pri | Function | Status |
|---|---|---|---|---|---|
| 1 | US-17 Holdings and value against book, by accounting class | BR-1 | M | FR-0 to FR-5 | Done |
| 2 | US-1 Rate shock: value, duration, convexity | BR-2, BR-3 | M | FR-6, FR-7 | Done |
| 3 | US-2 Key-rate profile | BR-2 | M | FR-6 | Done |
| 4 | US-4 AOCI and income per scenario, against limits | BR-3, BR-5 | M | FR-8, FR-9, FR-10 | Done |
| 5 | US-21 Prepayment outlook and model stress | BR-4 | M | FR-3.1, FR-15 | Done |
| 6 | US-18 Swap that cures a breached limit | BR-6 | M | FR-11 | Done |
| 7 | US-3 Hedge sized to a duration target | BR-7 | M | FR-12 | Done |
| 8 | US-20 Change since the prior close, by cause | BR-9 | M | FR-14 | Done |
| 9 | US-5 Daily brief | BR-10 | M | FR-16 | Done |
| 10 | US-19 What-if before trading | BR-8 | S | FR-13 | Done |
| 11 | US-22 Scenarios, limits and parameters changed without development | NFR-3 | M | FR-0, FR-7, FR-10 | Done |

## Release 2: the assistant for exceptions and non-standard questions (delivered)

| # | Story | Serves | Pri | Design | Status |
|---|---|---|---|---|---|
| 1 | US-12 Engine functions exposed as typed tools; a new analytic is added once | BR-11 | M | AD-3, AD-9 | Done |
| 2 | US-13 Investigation of a breach or unusual move, with policy citation and options | BR-12 | M | AD-4 | Done, without the pause for approval |
| 3 | US-8 Approve, edit or reject before anything is recorded | BR-12 | M | | Deferred by the owner on 2026-11-10 |
| 4 | US-6 Plain-language question answered only with figures from the engine | BR-11 | M | AD-1, AD-6 | Done |
| 5 | US-10 Every answer reproducible from an audit record | BR-11, BR-12 | M | AD-7 | Done |
| 6 | US-14 Multi-step what-if that no command covers | BR-11 | M | AD-1, AD-4 | Done |
| 7 | US-16 Measured comparison of the assistant with the routine tool | BR-11 | M | AD-8 | Done |
| 8 | US-7 Policy and model questions answered with citations | BR-13 | S | AD-5, AD-6 | Done |
| 9 | US-15 Warning when a result rests on a weak part of the model | BR-13 | S | | Deferred |
| 10 | US-9 Concepts explained with the book's own figures | BR-13 | S | AD-4, AD-5 | Done |
| 11 | US-11 Evaluation scores for retrieval, numeric faithfulness and tool choice | BR-11 | S | AD-8 | Done |

Candidates the evaluation points to, not scheduled. Each would be measured with
`ipw-ai eval` and reported next to the published run, not in place of it
([EVALUATION.md](EVALUATION.md), section 11).

| Candidate | Expected effect |
|---|---|
| Say in each tool what its groupings are and which rows they give | Fewer answers built on the wrong grouping, the cause of five of the fifteen wrong answers |
| A planning step before the loop, or a larger chat model | Fewer two-part questions and chained what-ifs answered by halves |
| Lead the model to shares a tool already reports, and say in an `aggregate` result what was divided by what | Fewer ratios taken the wrong way round |

## Not scheduled

Each item names what it would remove from the limitations table in
[MODEL.md](MODEL.md).

| Item | Removes | Depends on |
|---|---|---|
| Option-adjusted valuation by simulation | No option cost; long durations for at-the-money coupons | A calibrated rate model and volatility data |
| Separate swap curve | Swaps valued on the Treasury curve | Swap quotes |
| Treasury futures as hedge instruments | Swaps as the only hedge | Deliverable-basket data |
| Prepayment model calibrated to pool data | Stylised speeds | Pool-level history |
| Payment delay and refinancing lag | Small timing errors | None |
| Mortgage servicing rights | Product not covered | A servicing-strip cash-flow definition |
| Agency CMO | Product not covered | Deal structures |
| Graphical interface | Command line only | None |
| Sales as remediation options | Remediation by swaps only | None |
