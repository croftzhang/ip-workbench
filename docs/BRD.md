# Business Requirements Document

**Investment Portfolio Risk Analytics**

| | |
|---|---|
| Document | BRD, version 1.0 |
| Status | Baseline for release 1 |
| Owner | Product Owner, Investment Portfolio analytics |
| Last updated | 2026-11-10 |
| Next in the chain | [SOLUTION_DESIGN.md](SOLUTION_DESIGN.md), then [FUNCTIONAL_SPEC.md](FUNCTIONAL_SPEC.md) |

> The desk, its roles, its policy limits and every figure in this document are
> illustrative. They do not describe any institution.

## 1. Purpose

This document states what the Investment Portfolio desk needs from its risk
analytics and why. It is written in business terms. It does not say how the
need will be met; that is the job of the solution design and the functional
specification, which trace back to the requirement numbers used here.

## 2. Business context

The Investment Portfolio holds the bank's available-for-sale (AFS) and
held-to-maturity (HTM) securities, most of them agency mortgage-backed
securities (MBS), and hedges part of the AFS book with interest-rate swaps. It
is one of the main tools the bank has for managing the interest-rate position
of its balance sheet.

Three outcomes of that position are watched by management:

1. **Economic value.** What the securities and hedges are worth, and how much
   that changes when rates, spreads or borrower behaviour change.
2. **Equity through AOCI.** Fair-value changes of AFS securities go to
   accumulated other comprehensive income (ASC 320). They change reported
   equity and, for banks that include AOCI in regulatory capital, capital
   ratios. HTM securities are carried at amortised cost, so their value changes
   do not reach equity, but they are still losses in economic terms.
3. **Earnings.** The net interest income the portfolio produces over the next
   year, after funding and hedge costs.

Mortgage securities make all three harder to manage than they are for plain
bonds. Borrowers can prepay. When rates fall, loans are refinanced and the
securities shorten just when a longer asset would be wanted; when rates rise,
prepayments slow and the securities lengthen. A borrower whose loan rate is far
below the market also moves home less often. The interest-rate risk of the book
therefore changes as rates change, and it depends on assumptions about
behaviour that are uncertain.

Supervisory guidance expects a bank to measure interest-rate risk to both
earnings and economic value, to stress it with meaningful shocks, and to hold
it inside limits approved by the board (Interagency Advisory on Interest Rate
Risk Management, SR 10-1, 2010). It also expects the models behind those
measurements to be documented, tested and understood within their limitations
(Revised Guidance on Model Risk Management, SR 26-2, April 2026, which replaced
SR 11-7).

## 3. Stakeholders

| Role | Interest in the outcome | Uses |
|---|---|---|
| Head of Investment Portfolio (sponsor) | Positions inside policy; no surprises in AOCI or earnings | Daily brief, limit status |
| Portfolio managers | Decide what to buy, sell and hedge | Risk position, scenarios, hedge sizes, what-if |
| Portfolio analysts | Produce the daily view and answer questions | All analytics; explanations of changes |
| Treasury and asset-liability management | Balance-sheet rate position, income forecast | AOCI and income sensitivities |
| Market risk oversight (second line) | Independent view of limits and stress results | Limit report, scenario results |
| Model risk management | Validates the models | Documentation, tests, limitations |
| Accounting policy | Correct treatment of AFS, HTM and hedges | Accounting rules applied to the figures |
| Technology | Runs and supports the tool | Installation, change control |

## 4. Current state and problems

The desk this document is written for produces its risk view from spreadsheets
maintained by individual analysts and from the knowledge of a few people.

| ID | Problem | Consequence |
|---|---|---|
| P1 | The morning risk view is assembled by hand | It arrives late, and scenario questions asked in the morning meeting are answered hours later |
| P2 | Different spreadsheets give different numbers | No single figure can be defended, and last month's figure cannot be re-run |
| P3 | Prepayment assumptions are understood by one or two people | Key-person risk; nobody else can say why duration moved |
| P4 | A limit breach is noticed as a red cell | The size and cost of a fix take another half day to work out |
| P5 | Day-over-day changes are explained from intuition | Management asks "why did AOCI move" and gets an opinion |
| P6 | Economic risk, AOCI and income are computed in different places | The three views do not reconcile |
| P7 | A new scenario or limit needs someone to rebuild a spreadsheet | Policy changes are slow to reach the daily view |
| P8 | Questions outside the standard pack wait for a quantitative analyst | Answers take days; some questions are not asked |

## 5. Business objectives and success measures

| ID | Objective | Measure of success |
|---|---|---|
| O1 | Timely | The standard risk view is available within minutes of the marks; a standard scenario is answered while the question is still being discussed |
| O2 | One source of truth | Every figure in any report can be reproduced from stored inputs, by anyone, on any day |
| O3 | Limits managed ahead of the breach | Warnings before limits are reached; a breach arrives with sized options and their cost |
| O4 | Explainable | Any analyst can say what moved a number and which assumption it rests on; model risk management can validate from the documentation |
| O5 | Adaptable | Risk staff add or change a scenario or a limit without software development |
| O6 | Knowledge shared | Explanations come from the system and the written policy, not from individuals (release 2) |

## 6. Business requirements

Priority: M = must have, S = should have. Release 1 is the routine daily tool.
Release 2 is the assistant for exceptions and non-standard questions.

| ID | The business needs | Because | Accepted when | Pri | Rel |
|---|---|---|---|---|---|
| BR-1 | A daily statement of what is held and what it is worth against book value, with unrealized gain or loss shown separately for AFS and HTM | The AFS part reaches equity and the HTM part does not; management must see both (P6) | Totals reconcile to the position file and to the marks, position by position | M | 1 |
| BR-2 | The interest-rate risk of the book: how much it loses per basis point, how long it is, how that changes as rates move, and where on the curve the exposure sits, before and after hedges | Hedging and limit decisions depend on the net position and its shape, and mortgage risk changes with rates (P3) | Measures reflect re-estimated prepayments; exposures by maturity add up to the total | M | 1 |
| BR-3 | The effect of defined market moves on value, on AOCI and on the next twelve months of income, in one consistent view | The three outcomes are managed together and must reconcile (P6); supervisors expect both earnings and economic value to be stressed | One run gives all three for each scenario; AOCI excludes HTM; income is decomposed into its sources | M | 1 |
| BR-4 | A clear picture of expected borrower prepayment behaviour and of what happens to value and risk if those expectations are wrong | Behavioural assumptions drive the results and are the most uncertain input (P3) | Expected speeds are shown by coupon today and under rate shocks; faster and slower behaviour are standard scenarios | M | 1 |
| BR-5 | Monitoring of every policy limit with an early warning before a limit is reached | Breaches should be anticipated, not discovered (P4) | Each limit shows value, bound, share used and status; warnings appear at a set share of the limit | M | 1 |
| BR-6 | When a limit is breached, sized options that would restore it, each with its cost to income and its effect on the other limits | The portfolio manager needs something to take to the approver the same morning (P4) | At least two options per breach, each verified to restore the limit | M | 1 |
| BR-7 | The amount of hedge needed to reach a chosen risk target, with the choice of concentrating it in one maturity or spreading it along the curve | A single-maturity hedge changes the shape of the exposure; managers need to see both (BR-2) | The proposed hedge reaches the target when the book is re-measured with it | M | 1 |
| BR-8 | A before-and-after comparison for a proposed sale or hedge, before it is executed | Decisions should be tested against every limit, not only the one being fixed | Comparison covers value, risk, income and all limits; the actual book is not changed | S | 1 |
| BR-9 | An explanation of why value changed since the previous close, split by cause | Management asks every day; an opinion is not an answer (P5) | The causes add up exactly to the change; the part not explained by the standard risk report is shown | M | 1 |
| BR-10 | One daily brief that carries all of the above, suitable for sign-off and filing | A single dated record replaces several spreadsheets (P1, P2) | The same inputs always produce the same brief | M | 1 |
| BR-11 | Answers to questions outside the standard pack without waiting for development | Such questions are frequent and time-sensitive (P8) | A portfolio manager gets a correct, sourced answer in the same conversation | S | 2 |
| BR-12 | For a breach or an unusual move, an investigation that finds the contributors, quotes the relevant policy and proposes options, stopping for approval before anything is recorded | Investigation is the slow, manual part today (P4, P5) | The investigation is traceable step by step and nothing is recorded without approval | S | 2 |
| BR-13 | Explanations of concepts and results in terms of the bank's own book and its own policy and model documents | Knowledge should not depend on individuals (P3) | Explanations cite the document and use current portfolio figures | S | 2 |

## 7. Business rules

| ID | Rule |
|---|---|
| RULE-1 | Positions are valued at the end-of-day marks supplied by price verification. The analytics must reproduce those marks and may not replace them. |
| RULE-2 | AFS securities are carried at fair value with unrealized gains and losses in AOCI; HTM securities are carried at amortised cost (ASC 320). Economic-value measures include both. |
| RULE-3 | Only AFS securities are hedged. HTM securities cannot be the hedged item for interest-rate risk under hedge accounting (ASC 815). |
| RULE-4 | AOCI sensitivity is reported after tax and net of the swaps designated as fair-value hedges of AFS securities, because the hedged part of the value change is recognised in earnings with the swap (ASC 815-25-35-1 to 35-6). |
| RULE-5 | Interest income on securities is recognised on an effective-yield basis that takes expected prepayments into account (ASC 310-20-35-26). |
| RULE-6 | Limits and their warning levels are set in the investment policy. A breach is reported the day it is measured, together with a remediation proposal. |
| RULE-7 | The analytics propose; people decide. No trade, hedge designation or limit exception is created by the system. Every proposal needs portfolio-manager approval. |
| RULE-8 | Standard scenarios are instantaneous shocks: parallel moves of 50, 100 and 200 basis points in both directions, curve-shape moves, a mortgage-spread move, and faster and slower prepayment behaviour. |
| RULE-9 | Income is measured over the next twelve months on a constant balance sheet. |
| RULE-10 | A change to a model assumption is a controlled change: documented, tested, and visible as a change in results before it is used. |

## 8. Constraints and qualities the business requires

| ID | Requirement | Why |
|---|---|---|
| NFR-1 | **Reproducible and auditable.** The same inputs always give the same outputs, and every figure can be traced to inputs and a documented calculation. | O2; model risk management |
| NFR-2 | **Timely.** The standard scenario set completes in seconds on a desk workstation. | O1 |
| NFR-3 | **Configurable by risk staff.** Scenarios, limits and model parameters are changed without software development, and invalid entries are rejected with a clear message. | O5 |
| NFR-4 | **Extensible.** A new product type can be added without changing how risk, scenarios, AOCI, income or limits are computed. | The book will not stay limited to three product types |
| NFR-5 | **Confidential.** Positions and results stay on the bank's own machines. | Position data is confidential |
| NFR-6 | **Honest about limitations.** Each simplification is documented with the direction of its effect, and the main ones appear on the daily brief. | O4; a figure used without knowing its limits is a risk |
| NFR-7 | **Controlled change.** Any change that moves a result is visible before it is released. | RULE-10 |
| NFR-8 | **Usable on the desk.** Runs on a standard Windows workstation; everything is in English; output can be read on screen, filed as a document, or passed to another program. | Desk environment |

## 9. Scope

**In scope.** Fixed-rate agency pass-through securities (30-year and 15-year),
Treasury notes and bonds, and interest-rate swaps used as hedges. Valuation
against marks, interest-rate risk, scenarios, AOCI, twelve-month income, limit
monitoring and remediation, hedge sizing, what-if comparison, day-over-day
explanation, daily brief.

**Out of scope.** Mortgage servicing rights, collateralised mortgage
obligations, commercial and non-agency mortgage securities, loans, bank-owned
life insurance and reinsurance. Credit risk and liquidity risk. Trade execution
and hedge-accounting documentation. Regulatory capital calculation and
regulatory reporting. The bank-wide income simulation owned by Treasury.

## 10. Assumptions, dependencies and risks

| Type | Item |
|---|---|
| Assumption | End-of-day marks, the Treasury curve and primary mortgage rates are available each morning |
| Assumption | The investment policy defines each limit precisely enough to be computed |
| Dependency | Price verification for marks; accounting policy for classification and hedge designations |
| Dependency | Model risk management for validation before the figures are relied on for decisions |
| Risk | Results depend on prepayment assumptions that cannot be observed directly. Mitigation: BR-4 makes the sensitivity to them a standard output |
| Risk | Users may read indicative hedge sizes as instructions. Mitigation: RULE-7 and wording on every proposal |
| Risk | A simplified method may be used beyond what it supports. Mitigation: NFR-6 |

## 11. Release plan

| Release | Content | Status |
|---|---|---|
| 1 | BR-1 to BR-10; NFR-1 to NFR-8 | Delivered |
| 2 | BR-11 to BR-13, built on the release 1 calculations without changing them | Planned |

## 12. Glossary

| Term | Meaning |
|---|---|
| AFS, HTM | Available-for-sale and held-to-maturity: the two accounting classifications of the securities |
| AOCI | Accumulated other comprehensive income: the part of equity that holds unrealized gains and losses on AFS securities |
| Basis point (bp) | One hundredth of one percent |
| Book value | Amortised cost: what the bank paid, adjusted for premium or discount recognised so far |
| Convexity | How much duration changes as rates change. Negative convexity means the security shortens when rates fall and lengthens when they rise |
| CPR | Conditional prepayment rate: the annualised share of a pool's balance prepaid |
| Duration | Percentage change in value for a one percentage point change in rates |
| DV01 | Dollar change in value for a one basis point change in rates |
| Key-rate exposure | The part of the rate exposure that belongs to one maturity point on the curve |
| Lock-in | Borrowers with loan rates far below the market move home less often |
| Mark | The end-of-day price assigned to a position |
| NII | Net interest income |
| Pass-through | A mortgage security that passes borrowers' principal and interest to investors |
| Spread | Extra yield over Treasuries at which a security is valued |
| WAC, WALA, WAM | A pool's average loan rate, average loan age, and average remaining term |

## 13. References

* FASB Accounting Standards Codification, Topic 320, Investments - Debt Securities.
* FASB Accounting Standards Codification, Topic 815, Derivatives and Hedging, paragraphs 815-25-35-1 to 35-6.
* FASB Accounting Standards Codification, Subtopic 310-20, Receivables - Nonrefundable Fees and Other Costs, paragraph 310-20-35-26.
* Board of Governors of the Federal Reserve System, SR 10-1, Interagency Advisory on Interest Rate Risk Management, January 2010.
* Board of Governors of the Federal Reserve System, SR 26-2, Revised Guidance on Model Risk Management, April 17, 2026 (issued jointly with OCC Bulletin 2026-13 and FDIC FIL-15-2026; supersedes SR 11-7).
