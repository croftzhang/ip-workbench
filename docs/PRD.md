# IP Workbench - Product Requirements

Document version 0.3. **Delivery status:** version 1 (core engine, classic
command line, daily brief) is built and tested; stories US-1 to US-5 are met
and the tests that prove it are listed in section 5.1. Version 2 (agent) is
next.

## 1. Problem

Portfolio managers and analysts on a bank investment portfolio desk ask the same
questions every day about an agency MBS book held as AFS/HTM:

- What happens to duration, convexity and market value if rates move?
- How much AOCI and net interest income is at risk, and are we inside policy limits?
- How much hedge do we need, and in which tenors?
- Why did the number change since yesterday?

Today these are answered by ad-hoc spreadsheets and by asking the one person who
knows the prepayment model. Answers are slow, hard to reproduce, and the business
knowledge stays in a few heads.

## 2. Users

| Persona | Needs |
|---|---|
| Portfolio manager (PM) | Fast scenario answers, hedge sizing, limit status, a daily brief to sign |
| Junior analyst | Run standard analytics correctly; learn why MBS behave as they do |
| Model validator | One auditable source of numbers; documentation; reproducible tests |
| Quant / product owner | Add a new analytic once and have it appear in every interface |

## 3. Goals and non-goals

**Goals**
1. One analytics engine as the single source of every number.
2. Two versions on that engine: a classic (no-LLM) tool for routine work and an
   agent for exception investigation and ad-hoc analysis. All interfaces and
   documentation are in English.
3. The agent app runs fully locally: no API keys, no data leaves the machine.
4. Every AI answer is traceable: tool calls, retrieved documents, human approvals.
5. Measured, not asserted: an evaluation suite scores retrieval, numeric
   faithfulness and tool selection.

**Non-goals (v0.1)**
- Monte Carlo OAS, real pool-level data, real trade execution, multi-user auth.
- Web UI (command line only in v0.1).
- MSR, agency CMO, non-agency products (CMBS, CLO), loans, BOLI, reinsurance.
  The engine's product interface is designed so these can be added later
  (see the extension table in the README).

## 4. Scope

### 4.1 Core engine (`src/ipw/core/`, no LLM dependency)
- Synthetic portfolio (`data/portfolio.csv`, seeded generator): 88 positions,
  $10bn current face: 30-year agency MBS 70%, 15-year agency MBS 15%,
  US Treasuries 15%; HTM 59.5% / AFS 40.5%. Barbell coupon stack: 2020-21
  low coupons (2.0-3.0) bought at a premium and held HTM, 2023-25 production
  coupons (5.5-6.5) held AFS. Supporting files: hedge swaps, position marks
  for two closes, policy limits, market closes.
- Market data anchored to public early-November-2026 levels (10-year about
  4.88%, 30-year mortgage rate 7.18%), so the production coupons sit at or
  just below the refinancing threshold and the low coupons are locked in.
- Product interface: each product returns cash flows for a given rate path;
  behaviour models (prepayment) and the pricer are separate components.
- Prepayment model: refinance S-curve, turnover with lock-in, seasoning,
  seasonality, loan size, burnout.
- Cash flow engine; static-spread pricing calibrated to each position's mark.
- Scenarios: parallel shocks, curve shape, MBS spread, mortgage spread,
  prepayment-model stress.
- Risk: effective duration, convexity, key-rate durations (KRD).
- Hedging: par swaps sized to a duration target or to a key-rate profile.
  Treasury futures and a separate swap curve are left for later.
- Limit fix: the swap notional that brings a breached limit back to its bound.
- What-if: the book with positions removed or swaps and securities added.
- Day-over-day explain: curve, mortgage-rate basis, MBS spreads.
- Balance sheet: AOCI change (AFS only), 12-month NII, policy limit checks.

### 4.2 Version 1 — Classic app (`src/ipw/classic/`)
Command-line tool and Python API (English only; no web UI in v0.1). Fixed
scenarios, fixed report format, fully deterministic. This remains the right tool
for routine reporting.

| Command | Purpose |
|---|---|
| `ipw summary`, `ipw position`, `ipw top` | Composition, valuation, drill-down |
| `ipw risk`, `ipw krd` | Duration, convexity, DV01, key-rate profile |
| `ipw scenario`, `ipw nii`, `ipw prepay` | Scenarios, income, prepayment outlook |
| `ipw limits`, `ipw fix` | Limit status and the swap that cures a breach |
| `ipw hedge`, `ipw whatif` | Hedge sizing and before/after comparison |
| `ipw explain` | Change since the prior close, by driver |
| `ipw brief` | Daily risk brief in Markdown |

Every command prints a table, Markdown (`-f md`) or JSON (`-f json`).

### 4.3 Version 2 — Agent app (`src/ipw/agent/`)
Version 2 is not a chat front end for Version 1. Its job is the work Version 1
cannot do without someone writing new code:

- **Exception investigation (primary use case).** When the daily run finds a
  limit breach or an unusual day-over-day move, the agent drills down (which
  pools, which curve tenors, what changed since yesterday), retrieves the policy
  requirement for that breach, computes two or three remediation options, then
  stops for human approval. The path differs per exception.
- **Ad-hoc analysis.** Multi-step what-if questions composed from existing tools
  (e.g. "top five extension contributors under +100bp; AOCI exposure if swapped
  into 15-year").
- **Numbers joined with written rules.** Checks proposals against hedging and
  investment policy text, and surfaces relevant model limitations alongside any
  result that falls in a weakly supported region of the prepayment model.
- **Commentary drafting.** First draft of the "why it changed" text, with every
  figure verified against tool output.
- **Learn mode.** Explains a concept using the live portfolio's own numbers.

Building blocks:
- **MCP server** exposing the core engine as typed tools.
- **LangGraph** workflow with checkpoints: plan → retrieve → call tools →
  verify numbers → answer; long chains split into checked sub-steps.
- **RAG**: Chroma vector store over the knowledge base (`kb/`), LangChain for
  loading, splitting, embedding and retrieval; answers cite sources.
- **Human-in-the-loop** in the terminal: graph pauses on any hedge recommendation
  or breach remediation; approve / edit / reject; decision is logged.
- Interface: `ipw investigate`, `ipw ask`, `ipw chat` (English only).
- **Local LLM** via Ollama. Default chat model `qwen3:8b` (optional `qwen3:14b`),
  embeddings `nomic-embed-text`; both set in `config.yaml`.
- **Mock LLM** mode for tests and CI (deterministic, no model required).

### 4.4 Knowledge base (`kb/`, synthetic, consistent with engine parameters)
Prepayment model description, hedging policy, investment policy limits,
AFS/HTM accounting note, scenario definitions, MBS primer, glossary, model
limitations.

### 4.5 Classic-vs-agent benchmark (`evals/benchmark/`)
Thirty realistic tasks in three classes: routine queries, ad-hoc composed
analysis, and questions needing policy or model documentation. For each task:
can Version 1 do it without new code; is Version 2 correct; elapsed time; was
the answer blocked by the verifier. Results are published in the README as
measured, including failures. Expected shape: Version 1 wins on routine tasks;
Version 2 covers most of the other two classes at an accuracy below 100%.

## 5. User stories and acceptance criteria

| ID | Story | Acceptance criteria | Ver. |
|---|---|---|---|
| US-1 | As a PM, I run a rate shock and see market value, duration and convexity change | Results for ±25/50/100/200bp in < 5 s; matches regression test values | 1, 2 |
| US-2 | As a PM, I see KRDs so I know where on the curve my risk sits | KRDs sum to effective duration within 5% | 1, 2 |
| US-3 | As a PM, I size a hedge to a duration target | Post-hedge duration within 0.05y of target; notional by instrument shown | 1, 2 |
| US-4 | As a PM, I see AOCI and NII impact per scenario against policy limits | Breaches flagged red; HTM pools excluded from AOCI | 1, 2 |
| US-5 | As a PM, I export a daily risk brief | Markdown brief with all tables; identical numbers in both versions | 1, 2 |
| US-6 | As a PM, I ask in plain language and get an answer with numbers | Every number in the answer appears in a tool result; else answer is blocked | 2 |
| US-7 | As an analyst, I ask a policy/model question and get a cited answer | Answer lists source document and section; "not in knowledge base" when absent | 2 |
| US-8 | As a PM, I approve, edit or reject a hedge recommendation before it is recorded | Graph pauses; resumes from checkpoint; decision in audit log | 2 |
| US-9 | As an analyst, I ask "why" and get an explanation tied to this portfolio | Explanation quotes portfolio numbers from tools plus a cited concept | 2 |
| US-10 | As a validator, I reproduce any answer | Audit log holds question, tool calls with args, retrieved chunks, model, approval | 2 |
| US-11 | As a product owner, I see whether a change improved the assistant | `evals/` reports retrieval hit rate, numeric faithfulness, tool-selection accuracy | 2 |
| US-12 | As a quant, I add a new analytic once | New core function + one tool registration appears in MCP and the agent | 2 |
| US-13 | As a PM, when a limit is breached I get an investigation, not just a red flag | Report names the contributing pools and tenors, the day-over-day driver, the cited policy clause and 2–3 remediation options; pauses for approval | 2 |
| US-14 | As a PM, I ask a multi-step what-if that no command covers | Agent composes ≥ 3 tool calls; final figures pass the verifier; plan and calls are logged | 2 |
| US-15 | As a PM, I am warned when a result relies on a weak part of the model | Relevant model-limitation passage is cited whenever the triggering condition holds | 2 |
| US-16 | As a product owner, I can show where the agent helps and where it does not | Benchmark table (4.5) generated by one command | 1, 2 |

### 5.1 Traceability for version 1

| Story | Test (in `tests/`) |
|---|---|
| US-1 | `test_us1_standard_shocks_run_within_five_seconds`, `test_us1_results_match_stored_values` |
| US-2 | `test_us2_key_rate_durations_add_up_to_effective_duration` |
| US-3 | `test_us3_hedge_reaches_the_duration_target` |
| US-4 | `test_us4_htm_positions_never_reach_aoci`, `test_us4_breach_is_flagged` |
| US-5 | `test_us5_brief_has_every_section_and_the_same_numbers_as_the_workbench` |

The version 1 half of US-13 (name the contributors, size the remediation) is
already served by `ipw scenario --by`, `ipw top` and `ipw fix`; version 2 adds
the investigation that chooses among them and the policy citation.

## 6. Priorities (MoSCoW)

- **Must**: US-1 to US-8, US-10, US-13, US-14, US-16, mock-LLM tests, CI.
- **Should**: US-9, US-11, US-15, Docker.
- **Could**: US-12 walkthrough, chunking/retrieval experiment report, web UI.
- **Won't (v0.1)**: see non-goals.

## 7. Key design decisions

| Decision | Why |
|---|---|
| LLM never computes; it only selects tools and words the answer | Numbers stay auditable and validation scope is `core/` only |
| Numeric verifier node before any answer is shown | Small local models misquote figures; this makes it a caught error |
| Engine exposed through MCP, not imported directly by the agent | Same tools reusable by any MCP client the team adopts |
| Local model only | Portfolio positions are confidential; also zero cost to reproduce |
| Separate dependency sets (`pip install -e .` vs `.[agent]`) | Classic app stays light and LLM-free |
| Synthetic data and documents | Publishable on GitHub; no proprietary content |

## 8. Success measures

- Classic and agent briefs agree to the cent on every figure.
- Numeric faithfulness 100% on shown answers (unfaithful ones are blocked).
- Retrieval hit rate ≥ 85% on the evaluation questions.
- Fresh-machine setup (Windows, 12 GB GPU) in under 30 minutes from README.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Small local model loses the thread on chains longer than ~4 tool calls | Sub-steps with checkpoints; benchmark re-run on `qwen3:14b` and the difference reported |
| Local model picks wrong tool or malformed arguments | Schema validation, one retry with the error, fall back to clarifying question |
| Prepayment model is stylised, not calibrated | Stated in model limitations document and in the UI |
| Tool-calling quality varies by model | Model is a config value; eval suite re-scored on change |

## 10. Delivery plan

1. PRD and stories (this document). Done.
2. Core engine + regression tests. Done.
3. Classic CLI and daily brief. Done.
4. MCP server, knowledge base, RAG, LangGraph workflow, mock-LLM tests.
5. Evals, classic-vs-agent benchmark, audit log, Docker, CI, README with
   Windows + Ollama setup.
6. Smoke test on the target machine with the real local model.
