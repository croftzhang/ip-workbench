# Product Roadmap and User Stories

**Investment Portfolio Risk Analytics (IP Workbench)**

| | |
|---|---|
| Document | Product requirements, version 1.1 |
| Owner | Product Owner, Investment Portfolio analytics |
| Last updated | 2026-11-11 |
| Status | Releases 1 and 2 delivered; US-8 and US-15 deferred |

> The desk and all figures are illustrative.

## 1. Where this document sits

| Document | Question it answers |
|---|---|
| [BRD.md](BRD.md) | What does the business need, and why? |
| [SOLUTION_DESIGN.md](SOLUTION_DESIGN.md) | Which ways of meeting each need were considered, and which was chosen? |
| [FUNCTIONAL_SPEC.md](FUNCTIONAL_SPEC.md) | What exactly does each function compute, from what, and how is it accepted? |
| **This document** | What does each user get, in which release? |
| [BACKLOG.md](BACKLOG.md) | In what order is it built, and what is the status? |
| [UAT.md](UAT.md) | How does a business user confirm it? |
| [MODEL.md](MODEL.md) | What are the model's assumptions, limitations and tests? |
| [DECISIONS.md](DECISIONS.md) | Which engineering choices shaped the code? |
| [AGENT_DESIGN.md](AGENT_DESIGN.md) | How does the release 2 assistant work, and how is it measured? |
| [EVALUATION.md](EVALUATION.md) | What did the measurement of the assistant show? |

## 2. Product goals

1. One analytics engine is the single source of every number.
2. Two releases on that engine: a routine tool for the daily view, and an
   assistant for exceptions and non-standard questions. Release 2 adds no
   calculation of its own.
3. Everything runs on the user's machine. Release 2 uses a local language
   model: no keys, and no data leaves the machine.
4. Every answer from the assistant is traceable: tools called, documents
   retrieved, approvals given.
5. Claims about the assistant are measured, including where it is worse than
   the routine tool.

**Not goals.** Option-adjusted valuation, real pool-level data, trade
execution, multi-user access, a graphical interface, and products outside the
scope in the BRD. The product interface allows the listed products to be added
later ([SOLUTION_DESIGN.md](SOLUTION_DESIGN.md), section 6).

## 3. Releases

### 3.1 Release 1: the routine daily tool (delivered)

A deterministic command-line tool and Python interface on the core engine
(`src/ipw/core/`, `src/ipw/classic/`). Fixed scenarios, fixed report format,
no language model.

| Command | Purpose |
|---|---|
| `ipw summary`, `ipw position`, `ipw top` | Composition, valuation, drill-down |
| `ipw risk`, `ipw krd` | Duration, convexity, DV01, key-rate profile |
| `ipw scenario`, `ipw nii`, `ipw prepay` | Scenarios, income, prepayment outlook |
| `ipw limits`, `ipw fix` | Limit status and the swap that cures a breach |
| `ipw hedge`, `ipw whatif` | Hedge sizing and before/after comparison |
| `ipw explain` | Change since the prior close, by cause |
| `ipw brief` | Daily risk brief in Markdown |

Sample data: 88 positions with USD 10 billion face (30-year agency MBS 70%,
15-year 15%, Treasuries 15%; HTM 59.5%, AFS 40.5%), five pay-fixed swaps, marks
for two closes, nine policy limits, fifteen scenarios. Market levels are
anchored to public early-November-2026 levels.

### 3.2 Release 2: the assistant (delivered)

Release 2 is not a chat front end for release 1. Its job is the work release 1
cannot do without someone writing new code, on the same engine and with no
calculation of its own (`src/ipw/agent/`). The command is `ipw-ai`. The design,
with the options considered for each choice, is in
[AGENT_DESIGN.md](AGENT_DESIGN.md); the measured results are in
[EVALUATION.md](EVALUATION.md). On 2026-11-10 the owner narrowed the scope to
four things: a local language model, retrieval, tool calling and the engine's
analytics.

| Use | What release 2 does |
|---|---|
| Exception investigation | `ipw-ai investigate` gathers the evidence for a limit by a fixed playbook (the limit and its headroom, which buckets and positions carry it, where on the curve, what moved since the prior close, the policy clause) and sizes swap options. The answer is labelled indicative. It does not stop for an approval |
| Ad-hoc analysis | `ipw-ai ask` answers a question in plain English by calling several tools; sums, differences and shares come from a tool, not from the model |
| Numbers joined with written rules | Answers cite the section of the policy, accounting, scenario or model document they rely on; a question the documents do not cover is refused |
| Control | Every figure is checked against the tool results before an answer is shown, and every run is logged |

Building blocks, as built:

* **Tools.** Fifteen typed, read-only tools over the engine, called in the
  assistant's own process. An optional MCP server offers the same tools to any
  other client.
* **The loop.** One LangGraph graph of four nodes: retrieve, model, tools,
  check. No saved state, no approval step.
* **Retrieval.** A local Chroma vector index over the knowledge base, with
  `nomic-embed-text`. Keyword fusion and a cross-encoder reranker are switches,
  off by default; fusion was measured and does not raise the hit rate.
* **Local models.** Chat `qwen3:8b` and embeddings `nomic-embed-text`, through
  Ollama. Both are configuration values; no other chat model has been measured.
* **Mock model** for tests and continuous integration.

Knowledge base (constructed, consistent with the engine's parameters):
investment policy with the limits referenced as IPS sections, hedging policy,
AFS and HTM accounting note, scenario definitions, an MBS primer, a glossary,
and the functional specification and model document of this repository.

Benchmark (`evals/benchmark/`): forty tasks, thirty of which form the benchmark
of ten routine queries, ten composed analyses and ten questions needing the
documents. For each task: can release 1 do it without new code; is release 2
correct; elapsed time; was the answer blocked by the check. The run on the
reference machine is published as measured, including failures.

Not in release 2: the stop for a recorded approval (US-8); the automatic
warning when a result rests on a weak part of the model (US-15); separate
planning steps; commentary drafting and a learning mode as features of their
own (a question may still ask for an explanation); a container image; a
comparison of several chat models.

## 4. User stories and acceptance criteria

| ID | Story | Serves | Acceptance criteria | Rel |
|---|---|---|---|---|
| US-1 | As a portfolio manager, I run a rate shock and see value, duration and convexity change | BR-2, BR-3 | Results for +/-25, 50, 100 and 200bp in under 5 seconds; results match the stored regression values | 1 |
| US-2 | As a portfolio manager, I see key-rate durations so I know where on the curve my risk sits | BR-2 | Key-rate durations sum to effective duration within 5% | 1 |
| US-3 | As a portfolio manager, I size a hedge to a duration target | BR-7 | Duration after the hedge within 0.05 years of target when the book is re-measured; notional by instrument shown | 1 |
| US-4 | As a portfolio manager, I see AOCI and income impact per scenario against policy limits | BR-3, BR-5 | Breaches flagged; HTM positions excluded from AOCI | 1 |
| US-5 | As a portfolio manager, I export a daily risk brief | BR-10 | Markdown brief with every section; its figures are the engine's figures; same inputs give the same file | 1 |
| US-17 | As a portfolio manager, I see what we hold and what it is worth against book, split AFS and HTM | BR-1 | Totals reconcile to the positions; every mortgage position reprices to its mark | 1 |
| US-18 | As a portfolio manager, when a limit is breached I get the swap that cures it, at several maturities, with its cost | BR-6 | The smallest USD 10 million notional that removes the breach; confirmed by revaluation; every other limit shown after the trade | 1 |
| US-19 | As a portfolio manager, I compare the book before and after a sale or a hedge | BR-8 | The actual book is unchanged; the comparison covers value, risk, income and all limits | 1 |
| US-20 | As an analyst, I explain the change since the prior close by cause | BR-9 | Causes add up exactly to the change; the part not predicted by the risk report is shown | 1 |
| US-21 | As an analyst, I see expected prepayment speeds and what faster or slower behaviour does | BR-4 | Speeds by coupon today and after +/-100bp; faster and slower behaviour are standard scenarios | 1 |
| US-22 | As a risk manager, I add a scenario or a limit by editing a file | NFR-3 | Picked up without development; invalid entries rejected with the file and key named | 1 |
| US-6 | As a portfolio manager, I ask in plain language and get an answer with numbers | BR-11 | Every number in the answer appears in a tool result; otherwise the answer is blocked | 2 |
| US-7 | As an analyst, I ask a policy or model question and get a cited answer | BR-13 | Answer lists the source document and section; says so when the knowledge base has no answer | 2 |
| US-8 | As a portfolio manager, I approve, edit or reject a recommendation before it is recorded | BR-12 | Workflow pauses, resumes from its checkpoint, and logs the decision | 2 |
| US-9 | As an analyst, I ask "why" and get an explanation tied to this book | BR-13 | Explanation quotes portfolio figures from tools and a cited concept | 2 |
| US-10 | As a validator, I reproduce any answer | BR-11, BR-12 | Audit record holds the question, tool calls with arguments, retrieved passages, model and approval | 2 |
| US-11 | As a product owner, I see whether a change improved the assistant | BR-11 | Evaluation reports retrieval hit rate, numeric faithfulness and tool-selection accuracy | 2 |
| US-12 | As a quant, I add a new analytic once | BR-11 | A new engine function plus one tool registration appears in the tool server and the assistant | 2 |
| US-13 | As a portfolio manager, when a limit is breached I get an investigation, not just a red flag | BR-12 | Report names the contributing positions and curve points, the day-over-day driver, the cited policy clause and two or three remediation options; pauses for approval | 2 |
| US-14 | As a portfolio manager, I ask a multi-step what-if that no command covers | BR-11 | The assistant composes at least three tool calls; final figures pass the verifier; plan and calls are logged | 2 |
| US-15 | As a portfolio manager, I am warned when a result relies on a weak part of the model | BR-13 | The relevant limitation is cited whenever its triggering condition holds | 2 |
| US-16 | As a product owner, I can show where the assistant helps and where it does not | BR-11 | Benchmark table produced by one command | 1, 2 |

### 4.1 Tests that prove the release 1 stories

| Story | Test (in `tests/`) |
|---|---|
| US-1 | `test_us1_standard_shocks_run_within_five_seconds`, `test_us1_results_match_stored_values` |
| US-2 | `test_us2_key_rate_durations_add_up_to_effective_duration` |
| US-3 | `test_us3_hedge_reaches_the_duration_target` |
| US-4 | `test_us4_htm_positions_never_reach_aoci`, `test_us4_breach_is_flagged` |
| US-5 | `test_us5_brief_has_every_section_and_the_same_numbers_as_the_workbench`, `test_brief_is_deterministic_and_written_to_disk` |
| US-17 | `test_market_value_reconciles_to_face_book_and_unrealized`, `test_calibration_reprices_every_mbs_to_its_mark` |
| US-18 | `test_fix_limit_cures_the_breach_with_the_smallest_round_notional` |
| US-19 | `test_what_if_does_not_change_the_original`, `test_compare_reports_both_books` |
| US-20 | `test_drivers_add_up_to_the_change_between_the_two_closes` |
| US-21 | `test_mortgage_option_shows_up_where_it_should`, `test_spread_and_prepayment_stresses_have_the_expected_sign` |
| US-22 | `test_scenario_and_limit_files_are_validated`, `test_unknown_model_key_is_rejected` |

The full requirement-to-test matrix is in
[FUNCTIONAL_SPEC.md](FUNCTIONAL_SPEC.md#traceability-matrix).

### 4.2 Where the release 2 stories are tested

The tests run on the mock model. What the real model does is measured
separately ([EVALUATION.md](EVALUATION.md)).

| Story | Status | Tests | Note |
|---|---|---|---|
| US-6 | Done | `tests/agent/test_agent_loop.py`, `tests/agent/test_agent_verify.py` | |
| US-7 | Done | `tests/agent/test_agent_retrieval.py`, `tests/agent/test_agent_loop.py` | |
| US-8 | Deferred | | No stop for approval; every proposal is labelled indicative ([AGENT_DESIGN.md](AGENT_DESIGN.md), section 6) |
| US-9 | Done | `tests/agent/test_agent_loop.py` | Through the same loop: tools for the book's figures, passages for the concept |
| US-10 | Done | `tests/agent/test_agent_loop.py` | The run log holds no approval, because there is none to record |
| US-11 | Done | `tests/agent/test_agent_evals.py` | Numeric faithfulness is reported as first-draft pass rate and block rate |
| US-12 | Done | `tests/agent/test_agent_tools.py`, `tests/agent/test_agent_mcp.py` | |
| US-13 | Done, without the pause | `tests/agent/test_agent_loop.py` | The pause for approval is US-8 |
| US-14 | Done | `tests/agent/test_agent_loop.py` | The calls are logged; there is no separate plan to log |
| US-15 | Deferred | | The model summary is retrieved and cited when a question asks for it |
| US-16 | Done | `tests/agent/test_agent_evals.py` | One command: `ipw-ai eval` |

## 5. Release 2 design principles

| Principle | Why |
|---|---|
| The language model never computes; it selects tools and words the answer | Numbers stay auditable and validation covers the engine only |
| A verifier checks every figure before an answer is shown | Small local models misquote figures; this turns that into a caught error |
| Tools are defined once over the engine; the assistant calls them in its own process, and an optional MCP server offers the same tools | The main path stays simple, and any client the desk adopts can use the same tools |
| Local model only | Positions are confidential; reproduction costs nothing |
| Separate installation for the assistant's dependencies | The routine tool stays light and free of language-model code |
| Constructed data and documents | Publishable; no proprietary content |

## 6. Success measures for release 2

| Measure | Result |
|---|---|
| The routine brief and the assistant agree on every figure | Met by construction: every figure of the assistant is a figure of the engine |
| Numeric faithfulness of shown answers is 100%: unfaithful answers are blocked | Met: no shown figure failed the check; no benchmark answer had to be blocked |
| Retrieval hit rate of at least 85% on the evaluation questions | Met: 96.7% (29 of 30) |
| Set-up on a fresh Windows machine with a 12 GB graphics card in under 30 minutes from the README | Not measured |

Answer correctness, which these measures do not cover, was 18 of 30 benchmark
tasks ([EVALUATION.md](EVALUATION.md)).

## 7. Risks

| Risk | Mitigation |
|---|---|
| A small local model loses the thread on chains longer than about four tool calls | The investigation playbook; failures published; a larger model is one setting away. Measured: composed analysis 4 of 10 correct |
| The model picks the wrong tool or malformed arguments | Schema validation; the error goes back to the model, which may correct the call. Measured: tool-selection accuracy 16 of 20 |
| The prepayment model is stylised | Stated in the model document and on the brief; the assistant cites the model document when asked. The automatic warning (US-15) is deferred |
| Tool-calling quality varies by model | The model is a configuration value; evaluation is re-scored on change |

## 8. Delivery plan

| Step | Content | Status |
|---|---|---|
| 1 | Business requirements, solution design | Done |
| 2 | Core engine, functional specification, regression baseline | Done |
| 3 | Routine tool and daily brief; acceptance script | Done |
| 4 | Tools, knowledge base, retrieval, the loop, mock-model tests | Done |
| 5 | Evaluation, benchmark, run log | Done. A container image was not built |
| 6 | Measurement on the reference machine with the real local model | Done: published in [EVALUATION.md](EVALUATION.md) |
