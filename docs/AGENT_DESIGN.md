# Solution Design, Release 2: the Assistant

**Investment Portfolio Risk Analytics**

| | |
|---|---|
| Document | Solution design for release 2, version 0.9 |
| Status | Design agreed in principle. Nothing in this document is built yet |
| Owner | Product Owner, Investment Portfolio analytics |
| Last updated | 2026-11-10 |
| Traces to | [BRD.md](BRD.md): BR-11 to BR-13, RULE-7, NFR-1, NFR-5 to NFR-7. [PRD.md](PRD.md): US-6 to US-16 |
| Previous in the chain | [SOLUTION_DESIGN.md](SOLUTION_DESIGN.md), which covers release 1 |

> The desk, its roles, its policy documents and every figure in this document
> are illustrative. They do not describe any institution.

## Contents

1. Purpose
2. Requirements addressed
3. Principles
4. The solution on one page
5. Design decisions AD-1 to AD-10
6. Planned repository layout
7. Control position
8. Risks
9. Build plan
10. Open points
11. References

## 1. Purpose

Release 1 answers the standard questions with fixed commands. Release 2 is for
the work those commands cannot do without someone writing new code:

* investigating an exception, where the path depends on what is found;
* an ad-hoc analysis composed from several existing calculations;
* joining a number with the written rule or model limitation that applies to it.

This document says how that will be built: which parts are done by a language
model, which by ordinary code and which by a person; which tools and models are
used and why; and how the result will be measured. Section 9 gives the order of
build and the evidence expected at each step.

Out of scope for release 2: a graphical interface, execution or booking of any
trade, fine-tuning of any model, and any service outside the user's machine.

## 2. Requirements addressed

| Requirement | What the design has to deliver | Decisions |
|---|---|---|
| BR-11 Answers outside the standard pack | A correct, sourced answer in the same conversation, composed from existing calculations | AD-1, AD-3, AD-4, AD-6 |
| BR-12 Investigation of a breach or unusual move | Contributors, the policy clause, sized options; traceable step by step; stops for approval | AD-4, AD-7, AD-8 |
| BR-13 Explanations in terms of the bank's own book and documents | Explanations that cite the document and section and use current figures | AD-5, AD-6 |
| RULE-7 The analytics propose; people decide | No proposal is recorded without a person's decision; nothing is executed | AD-7 |
| NFR-1 Reproducible and auditable | Every figure comes from the deterministic engine; every run can be replayed | AD-1, AD-8 |
| NFR-5 Confidential | No position, question or document leaves the machine | AD-2 |
| NFR-6 Honest about limitations | The relevant model limitation is shown next to a result that depends on it; measured failures are published | AD-5, AD-9 |
| NFR-7 Controlled change | A change of model, prompt or retrieval setting is judged by the same evaluation before it becomes the default | AD-9 |

## 3. Principles

| Principle | Consequence |
|---|---|
| The language model never computes | It chooses tools, fills their arguments and words the answer. Every figure is produced by the release 1 engine |
| Nothing is shown unchecked | Code compares every figure in a draft answer with the tool results before the answer is displayed |
| The engine is reached through a tool server | The assistant does not import the engine. The same tools serve any other client the desk adopts |
| Everything runs on the user's machine | Local models only; no hosted model, no tracing service |
| Every stage can be switched off, and is measured | A stage that does not improve a measured result is not part of the default |
| The assistant is a separate installation | The routine tool stays small and free of language-model code |

## 4. The solution on one page

```text
question
   |
   v
 route + plan ........ language model: class of request, ordered steps
   |
   v
 retrieve ............ code: vector index + keyword index -> fuse -> rerank
   |                         (knowledge base: policies, specification, model summary)
   v
 call tools .......... language model selects tools and arguments;
   |                   tool server (MCP) runs them on the release 1 engine
   v
 draft ............... language model: wording only
   |
   v
 verify .............. code: every figure and every citation checked; else blocked
   |
   v
 approve ............. person: approve, edit or reject (only when the answer proposes something)
   |
   v
 record .............. code: audit record of the whole run
```

Who does what:

| Step | Done by | Can it change a figure? |
|---|---|---|
| Route and plan | Language model | No |
| Retrieve | Code | No |
| Choose tools and arguments | Language model | Only by asking the engine a different question |
| Run tools | Engine, through the tool server | It is the only source of figures |
| Draft | Language model | No: the next step rejects any figure that is not a tool result |
| Verify | Code | No |
| Approve | Person | Only by editing parameters, which re-runs the tools |
| Record | Code | No |

Role of each document in release 2. A document is either put into the knowledge
base, where it is split, embedded and retrieved, or it is a reference the
design relies on and the assistant never reads.

| Documents | Role |
|---|---|
| Constructed policy and reference documents in `kb/`: investment policy, hedging policy, AFS and HTM accounting note, scenario definitions, MBS primer, glossary | In the knowledge base: embedded and retrieved |
| [FUNCTIONAL_SPEC.md](FUNCTIONAL_SPEC.md) and [MODEL.md](MODEL.md) | In the knowledge base: embedded and retrieved |
| [BRD.md](BRD.md), [SOLUTION_DESIGN.md](SOLUTION_DESIGN.md), [PRD.md](PRD.md), the backlog, the acceptance script, the decision log, this document | Project documentation only; not embedded |
| Supervisory guidance (SR 10-1, SR 26-2) and accounting standards | Design references only; not embedded, not retrieved |

## 5. Design decisions

### AD-1. Division of labour between the language model and code (BR-11, NFR-1)

| Option | For | Against |
|---|---|---|
| A. The model answers from the figures placed in its context | Simplest | Small local models misquote and miscalculate; nothing can be audited |
| B. The model writes analysis code that is then executed | Flexible | Unreviewed code produces the desk's numbers; not reproducible; a security surface |
| **C. The model selects typed tools and words the answer; code computes and checks** | Figures stay deterministic and validated once; every step is inspectable | The assistant can only do what a tool exposes |

**Decision: C.** The limitation is accepted and made explicit: when no tool can
produce a figure, the assistant says so and names the nearest thing it can do.
Arithmetic across tool results (a sum of five positions, a difference between
two scenarios) is done by a deterministic helper tool, not by the model.

### AD-2. Where the models run, and which models (NFR-5)

| Option | For | Against |
|---|---|---|
| A. Hosted model through an API | Strongest models | Positions and questions leave the machine; a cost and a key for anyone reproducing |
| **B. Local models served by Ollama** | Nothing leaves the machine; one install on Windows; free to reproduce | Smaller models; quality has to be measured, not assumed |
| C. Local models run directly with Hugging Face transformers | Full control | A second runtime for the job Ollama already does; harder set-up on Windows |

**Decision: B** for the chat and embedding models. The reranker (AD-5) is the
one model run through Hugging Face and PyTorch, because that is the established
route for cross-encoders and Ollama has no standard reranking interface.

| Role | Model | Why this one |
|---|---|---|
| Chat, default | `qwen3:8b` | Tool calling built in; 5.2 GB, so it fits a 12 GB card with room for context [T1] |
| Chat, candidates | `qwen3:14b`, `qwen3.5:9b`, `gemma4:12b` | Same hardware class; compared with the default in the benchmark rather than assumed better or worse [T1] |
| Embeddings | `nomic-embed-text` | 274 MB, 768 dimensions, inputs up to 8,192 tokens; runs on CPU [T2] |
| Reranker | `BAAI/bge-reranker-v2-m3` | Open licence (Apache 2.0), 568 million parameters, the usual self-hosted baseline [T3] |
| Tests | A scripted mock model | Lets the whole workflow run in continuous integration without a GPU |

Rules:

* Every model name is a configuration value.
* The default chat model is the candidate with the best tool-selection accuracy
  on the benchmark (AD-9) among those that fit in graphics memory on the
  reference machine (RTX 3060, 12 GB); ties go to the smaller model.
* Chat settings: temperature 0, a fixed seed, thinking mode off for tool
  selection, a capped context length so the model stays on the GPU.
* Memory budget on 12 GB, to be measured during the build: chat model about
  5 to 7 GB with context, reranker 1 to 2.5 GB depending on precision,
  embeddings under 0.5 GB.

### AD-3. How the assistant reaches the engine (BR-11, US-12)

| Option | For | Against |
|---|---|---|
| A. Import the engine and wrap its methods as Python functions | Least code | The assistant and the engine become one program; tools serve this assistant only |
| B. A web service in front of the engine | Familiar | A server to run and secure; more than a single-user tool needs |
| **C. A Model Context Protocol (MCP) server over standard input and output** | One typed definition per tool, usable by any MCP client; a process boundary between engine and language-model code; no network port | A child process and asynchronous plumbing |

**Decision: C.** The server is a thin layer over the release 1 facade. A new
analytic is added once: a method on the workbench and one tool registration.

| Tool | Wraps | Main arguments |
|---|---|---|
| `portfolio_summary` | `ipw.core.workbench.Workbench.summary` | grouping |
| `risk_report` | `ipw.core.workbench.Workbench.risk_table` | grouping |
| `key_rate_report` | `ipw.core.workbench.Workbench.key_rate_table` | grouping, unit |
| `top_positions` | `ipw.core.workbench.Workbench.top` | metric, count, direction |
| `position_detail` | `ipw.core.workbench.Workbench.position` | position id |
| `run_scenarios` | `ipw.core.workbench.Workbench.scenario_table` | scenario names or parallel shocks |
| `scenario_breakdown` | `ipw.core.workbench.Workbench.scenario_detail` | scenario, grouping |
| `income_report` | `ipw.core.workbench.Workbench.nii_table` | scenarios |
| `prepayment_outlook` | `ipw.core.workbench.Workbench.prepay_table` | shocks, grouping |
| `explain_change` | `ipw.core.workbench.Workbench.explain` | none |
| `limit_status` | `ipw.core.workbench.Workbench.limit_table` | none |
| `limit_remedy` | `ipw.core.workbench.Workbench.fix_limit` | limit id, swap tenor, target |
| `size_hedge` | `ipw.core.workbench.Workbench.hedge` | target duration, mode, tenors |
| `what_if` | `ipw.core.workbench.Workbench.what_if`, `ipw.core.workbench.Workbench.compare` | positions to drop, swaps to add |
| `aggregate` | New helper | sum, difference or ratio over cells of earlier results |

Conventions for every tool:

* **Read-only.** A tool calculates and returns. None writes a file, changes the
  book or keeps state; `what_if` returns a comparison and discards the copy.
* **Typed.** Arguments have a schema with allowed values taken from the
  configuration (scenario names, limit ids, groupings), so a wrong argument is
  rejected before the engine runs.
* **Self-describing results.** Each result carries an id, the market date, the
  tool and arguments, the unit of every column, and the rows. The id is what
  the verifier and the audit record refer to.
* **Errors are data.** The engine's one-line error is returned to the model,
  which may correct its arguments once.

### AD-4. The workflow (BR-12, US-13, US-14)

| Option | For | Against |
|---|---|---|
| A. One loop in which the model decides every next step | Least design | A small model loses the thread on long chains; no fixed point for checks or approval |
| B. A fixed pipeline | Predictable | Cannot follow an investigation whose path depends on what is found |
| **C. A graph with fixed control points and model-chosen steps between them** | Checks and approval always happen; the model has freedom only where it is useful | More design work |

**Decision: C**, built as a LangGraph state graph with a checkpoint after every
step.

| Node | Done by | Produces | If it fails |
|---|---|---|---|
| Route | Language model, structured output | Class of request and the question restated | Unclear request: ask one clarifying question |
| Plan | Language model | At most six ordered steps | Empty plan: treated as a knowledge question |
| Retrieve | Code (AD-5) | Passages with document and section | Nothing above threshold: recorded as "not in the knowledge base" |
| Act | Language model chooses; tool server executes | Tool results | Tool error returned once for correction; then a clarifying question. At most eight tool calls per run |
| Draft | Language model | Answer text with citations | See Verify |
| Verify | Code (AD-6) | Pass, or the list of mismatches | One redraft; then the answer is blocked and the tool tables are shown instead |
| Approve | Person (AD-7) | Approve, edit or reject | Edit re-runs the affected tools and Verify |
| Record | Code (AD-8) | Audit record | Failure to write stops the run |

Four classes of request and the path each takes:

| Class | Example | Path |
|---|---|---|
| Routine | "What is net duration?" | Route, Act (one tool), Draft, Verify, Record |
| Composed analysis | "The five largest contributors to the +200bp AOCI loss, and their share of the total" | Route, Plan, Act (several tools and `aggregate`), Draft, Verify, Record |
| Knowledge | "Which limit applies to AOCI and where is it defined?" | Route, Retrieve, Draft, Verify, Record |
| Investigation | "Investigate the AOCI_UP200 breach" | Fixed skeleton below, then Approve and Record |

The two other uses named in the roadmap map onto these classes: drafting the
commentary on the day's change is a composed analysis that starts from
`explain_change`, and explaining a concept with the book's own figures is a
knowledge question with one or two tool calls added.

The investigation follows a fixed skeleton so that every investigation contains
the same evidence. The model decides which further drill-downs to add and how
to word the findings.

1. `limit_status`: the breach, its size and its policy reference.
2. `scenario_breakdown` for the limit's scenario: which buckets carry the loss.
3. `top_positions`: the positions that contribute most.
4. `key_rate_report`: where on the curve the exposure sits.
5. `explain_change`: what moved since the prior close.
6. Retrieve the policy clause the limit refers to.
7. `limit_remedy` for two or three swap tenors: sized options and their cost to income.
8. Draft, Verify, Approve, Record.

State is checkpointed to a local SQLite file under a thread id, so a run that is
waiting for approval survives closing the terminal and is resumed by id.

### AD-5. Retrieval (BR-13, US-7, US-15)

| Option | For | Against |
|---|---|---|
| A. Vector search only | Finds paraphrases | Weak on exact identifiers such as `AOCI_UP200`, "IPS 4.3" or "FR-11" |
| B. Keyword search only | Exact terms | Misses a question worded differently from the document |
| C. Both, fused | Covers both kinds of question | Two indexes |
| **D. Both, fused, then reranked by a cross-encoder** | Best ordering of the few passages the model reads | A third model; slower |

**Decision: D as the design, with each stage switchable and the default set by
measurement** (AD-9). The knowledge base is about ten documents, so the gain
from fusion and reranking may be small; if it is, the default is the simpler
configuration and the evaluation report says so.

| Stage | Design |
|---|---|
| Split | By Markdown heading, with a size cap; a formula stays with its section. Each passage carries document, section number and heading |
| Vector index | Chroma, stored locally; embeddings from `nomic-embed-text`, with the prefixes that model requires for queries and for documents [T2] |
| Keyword index | BM25 over the same passages [A2] |
| Fuse | Top 20 from each index, combined by reciprocal rank fusion [A1] |
| Rerank | The fused candidates scored against the question by the cross-encoder; the best four are kept |
| Refuse | If the best score is below a threshold set on the evaluation questions, the answer is "the knowledge base does not cover this" |
| Cite | Every statement taken from a passage carries its document and section |

Reciprocal rank fusion scores a passage $d$ from its rank $r(d)$ in each
ranking $r$ of the set $R$ (here the vector ranking and the keyword ranking),
with the constant $k = 60$ of the original paper [A1]:

$$\text{RRF}(d) = \sum_{r \in R} \frac{1}{k + r(d)}$$

Fusion and reranking are implemented directly on the LangChain core interfaces
(about a hundred lines) rather than with LangChain's ready-made ensemble and
compression retrievers, which have moved to a legacy package [T6].

**Limitations shown with results (US-15).** Each row of the limitations table
in the model summary becomes a passage with a trigger written as a rule over
tool results, for example "the result includes 30-year coupons within one point
of the current mortgage rate" for the missing option cost. When a tool result
meets a trigger, code attaches the limitation to the answer. This is a rule,
not a judgement left to the model.

### AD-6. Checking an answer before it is shown (US-6, US-7)

| Option | For | Against |
|---|---|---|
| A. Trust the draft | Nothing to build | A local model will sometimes misquote a figure |
| B. Ask a second model to judge the draft | Flexible | A small local judge is unreliable, and its verdict cannot be reproduced |
| **C. A deterministic check in code** | Reproducible; failures are countable | Checks presence of a figure, not every aspect of meaning |

**Decision: C.** Rules:

1. Every number in the draft must equal a cell of a tool result from the same
   run, after rounding to the number of decimals the draft shows. Sign, unit
   words (bp, %, years, USD millions) and thousands separators are normalised.
2. Exempt: dates, identifiers (position, limit and section numbers), numbers
   the user typed in the question, and numbers inside a quoted passage, which
   must match the passage exactly.
3. A figure that is not a cell of a result (a total, a difference, a share) is
   allowed only if the `aggregate` tool produced it.
4. Every citation must refer to a passage that was retrieved in this run.
5. On failure the model gets the list of mismatches and one more attempt. If
   that fails, the answer is blocked: the user sees the tool tables and a
   notice, never the unverified text.

What the check does not catch: a correct figure attached to the wrong label.
That is measured separately, as answer correctness against reference answers
(AD-9), and every shown answer ends with the tool tables it relied on, rendered
by code, so the labelled source figures are always on the page.

### AD-7. Approval by a person (RULE-7, BR-12, US-8)

| Option | For | Against |
|---|---|---|
| A. No pause; proposals are labelled "indicative" | Simplest | Does not meet RULE-7 |
| B. The model asks "shall I proceed?" and interprets the reply | Conversational | The decision would rest on a model reading free text |
| **C. The workflow stops at a defined step and resumes with a typed decision** | The stop cannot be skipped; the decision is data | Needs persistent state |

**Decision: C**, using the graph's interrupt and the SQLite checkpoint.

* **When.** Code, not the model, decides: a run that called `limit_remedy`,
  `size_hedge` or `what_if` contains a proposal and must stop.
* **What the person sees.** The verified answer, the proposal with its effect on
  the limit, on every other limit, on duration and on income, and the cited
  policy clause.
* **Decisions.** Approve; edit (change tenor, notional or target, which re-runs
  the tools and the check before stopping again); reject with a reason.
* **What approval does.** It records the decision. The system executes nothing
  and books nothing.
* **Resuming.** On resume the approval step runs again from its start, so it
  contains no action with a side effect; writing the record is a separate step
  after it [T4].

### AD-8. The audit record (NFR-1, US-10)

One record per run, appended to a local file as a line of JSON: thread id and
time; the question; class and plan; each tool call with arguments, result id
and a hash of the result; the passages retrieved, with scores at each stage;
model names and settings; each draft and the verifier's outcome; the decision
and who made it.

A replay command re-executes the recorded tool calls against the same input
files and compares the hashes. Reproducing the figures of an answer therefore
does not depend on the language model giving the same words twice.

### AD-9. Evaluation and benchmark (US-11, US-16, NFR-6, NFR-7)

| Option | For | Against |
|---|---|---|
| A. Demonstration by example | Quick | Shows the cases that work |
| B. Scores from a judging model | Covers free text | Not reproducible with a small local judge |
| **C. Deterministic measures on fixed question sets, published as measured** | Comparable between runs; failures visible | Question sets have to be written and maintained |

**Decision: C.**

| Measure | Definition | Set |
|---|---|---|
| Retrieval hit rate at 4 | Share of questions for which a reference section is among the four passages passed to the model | 30 questions with reference sections |
| Mean reciprocal rank | Mean of one over the rank of the first reference section, zero if absent | Same |
| Refusal correctness | Share of out-of-scope questions answered "not covered" | 10 questions with no answer in the knowledge base |
| Tool-selection accuracy | Share of tasks for which the tools called and their arguments equal the reference | 20 routine tasks |
| First-draft pass rate | Share of first drafts that pass the check of AD-6 | All benchmark tasks |
| Block rate | Share of runs whose answer was blocked after the second draft | All benchmark tasks |
| Answer correctness | Share of tasks whose answer contains every reference pair of label and value | All benchmark tasks |
| Time to answer | Seconds, median and 90th percentile, on the reference machine | All benchmark tasks |

With $Q$ the question set, $G_q$ the reference sections of question $q$ and
$\text{rank}_q$ the rank of the first reference section retrieved:

$$\text{Hit@}4 = \frac{1}{|Q|} \sum_{q \in Q} \mathbf{1}\left[\, G_q \cap \text{top}_4(q) \neq \varnothing \,\right] \qquad \text{MRR} = \frac{1}{|Q|} \sum_{q \in Q} \frac{1}{\text{rank}_q}$$

Three comparisons are produced by one command each:

| Comparison | Rows | Answers |
|---|---|---|
| Retrieval ablation | Vector only; keyword only; fused; fused and reranked | Does each retrieval stage earn its place? |
| Model comparison | The default and the three candidate chat models | Which model is the default on this hardware? |
| Release 1 against release 2 | Thirty tasks in three classes: routine, composed analysis, questions needing documents | Where does the assistant help, and where is the plain command the better tool? |

Targets, from the roadmap: retrieval hit rate of at least 85%; no unverified
figure shown. A shown answer passes the check by construction, so first-draft
pass rate and block rate are reported next to it to show how often the check
had to intervene.

Where the measurements run:

| Run | Model | Purpose |
|---|---|---|
| Continuous integration, every commit | Scripted mock model; fixed fake embeddings | The workflow, the tool server, the check, approval, the audit record and the evaluation code work. Says nothing about model quality |
| Reference machine, by the owner | The real models | The figures that are published in `docs/EVALUATION.md`, with hardware, model tags and date. Results below target are published as measured |

### AD-10. Packaging and interfaces (NFR-5, US-12)

* **Installation.** An optional extra, installed with `pip install -e ".[agent]"`,
  on top of release 1. Release 1 keeps working without it.
* **Configuration.** One file, `config/agent.yaml`: model names, context
  length, retrieval switches and thresholds, budgets, file locations.
* **Commands.**

| Command | Purpose |
|---|---|
| `ipw-mcp` | Start the tool server (also usable from any other MCP client) |
| `ipw-agent ask "..."` | One question, one verified answer |
| `ipw-agent investigate AOCI_UP200` | Run the investigation for a limit |
| `ipw-agent resume <thread>` | Continue a run that is waiting for approval |
| `ipw-agent kb build` | Split, embed and index the knowledge base |
| `ipw-agent replay <thread>` | Re-execute a recorded run's tool calls and compare |
| `ipw-agent eval` | Retrieval ablation and model comparison |
| `ipw-agent benchmark` | Release 1 against release 2 |

* **Interface language.** English, command line only, as in release 1.

## 6. Planned repository layout

```text
src/ipw/mcp/            tool server: one registration per tool, no language-model code
src/ipw/agent/
  config.py             agent configuration
  models.py             chat, embedding and reranker factories; the mock model
  kb.py                 split, embed, index
  retrieval.py          vector + keyword search, fusion, rerank, refusal
  graph.py              the workflow: nodes, routing, budgets
  verify.py             the check on figures and citations
  approval.py           the stop, the three decisions, resume
  audit.py              the record and replay
  evals.py              measures, ablation, model comparison, benchmark
  cli.py                the ipw-agent commands
kb/                     knowledge base sources and limitation triggers
evals/                  question sets, reference answers, benchmark tasks
config/agent.yaml       agent configuration
tests/agent/            tests that run on the mock model
docs/EVALUATION.md      measured results from the reference machine
```

Main dependencies of the extra: LangGraph; the LangChain core package and its
Chroma, Ollama and text-splitter integrations; the LangChain adapter for MCP
tools; the MCP Python SDK; the Chroma database; a BM25 implementation;
sentence-transformers with PyTorch. Exact versions are pinned when the extra is
created. Two of these packages have recently changed their public interfaces
[T5][T6], so the pins are part of the design, not a detail.

## 7. Control position

The valuation engine applies financial theory to produce quantitative estimates
and is a model in the sense of the supervisory guidance on model risk
management; its documentation, limitations and tests are in the functional
specification and the model summary. Release 2 leaves that boundary where it
is: no figure originates outside the engine.

The assistant itself is a generative, agentic use of a language model, which
that guidance places outside its scope [A3]. The design therefore does not
claim conformance for the assistant. It states its own controls:

| Risk | Control | Evidence |
|---|---|---|
| A figure is invented or misquoted | Deterministic check before display (AD-6) | First-draft pass rate, block rate |
| A correct figure is attached to the wrong label | Reference answers; tool tables appended to every answer | Answer correctness |
| The wrong tool or arguments | Typed schemas; allowed values from configuration; one corrected retry | Tool-selection accuracy |
| An answer cites a document that does not say it | Citations restricted to retrieved passages; refusal threshold | Hit rate, refusal correctness |
| A proposal is acted on without a decision | Fixed stop decided by code; typed decision; nothing executed (AD-7) | Workflow tests; audit record |
| A result cannot be reproduced | Audit record and replay of tool calls (AD-8) | Replay test |
| Data leaves the machine | Local models only; no telemetry or tracing service (AD-2) | Dependency and configuration review |
| A change makes the assistant worse | The same evaluation before a new default (AD-9) | Evaluation report per change |

## 8. Risks

| Risk | Effect | Response |
|---|---|---|
| An 8B local model chooses tools poorly on multi-step tasks | Composed analyses fail or are blocked | Fixed skeleton for investigations; step budget; candidates compared; failures published |
| The knowledge base is too small for fusion and reranking to matter | Added complexity without benefit | Each stage is a switch; the default follows the ablation |
| Graphics memory is short with chat model, reranker and context together | Slow answers | Reranker can run on CPU; context length is capped; sizes measured at build |
| Library interfaces move again | Build breaks on a fresh install | Pinned versions; mock-model tests in continuous integration on Windows and Linux |
| The published figures depend on one machine | Not comparable elsewhere | Hardware, model tags and date recorded with every result |
| The check is read as a guarantee of correctness | Over-reliance | Section AD-6 states what it does not catch; answer correctness is reported beside it |

## 9. Build plan

| Step | Delivers | Evidence |
|---|---|---|
| 1. Tool server | `ipw-mcp` with all tools of AD-3 | Each tool returns the same figures as the matching release 1 command; schema rejects bad arguments |
| 2. Knowledge base and retrieval | Constructed documents, indexes, fusion, rerank, refusal; retrieval question set | Retrieval tests on fake embeddings; ablation command runs |
| 3. Workflow | Graph, check, approval, audit record, replay; `ipw-agent` commands | Mock-model tests for all four request classes, a blocked answer, approve, edit, reject, resume after restart, replay |
| 4. Evaluation and benchmark | Task sets, reference answers, the three comparisons | Commands run on the mock model in continuous integration |
| 5. Measurement on the reference machine | `docs/EVALUATION.md`; default model and retrieval configuration chosen from it | Published results, including tasks that failed |
| 6. Documents | Functional specification for release 2, acceptance cases, README | Document checks extended to the new documents |

Steps 1 to 4 and 6 can be completed and tested without a GPU. Step 5 needs the
reference machine.

## 10. Open points

| Point | Default if not decided otherwise |
|---|---|
| Whether to add the public text of SR 26-2 to the knowledge base | No: the assistant answers questions about the desk's own policy and model, not about supervisory guidance |
| Which chat model is the default | `qwen3:8b` until step 5 gives a measured answer |
| Whether the reranker stays in the default configuration | Decided by the retrieval ablation in step 5 |

## 11. References

Literature and guidance:

| | |
|---|---|
| A1 | Cormack, G. V., Clarke, C. L. A. and Büttcher, S. (2009). Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods. *Proceedings of the 32nd International ACM SIGIR Conference*, 758-759. |
| A2 | Robertson, S. and Zaragoza, H. (2009). The Probabilistic Relevance Framework: BM25 and Beyond. *Foundations and Trends in Information Retrieval* 3(4), 333-389. |
| A3 | Board of Governors of the Federal Reserve System (2026). SR 26-2, Revised Guidance on Model Risk Management, April 17, 2026: definition of a model in section II; generative and agentic AI stated to be outside its scope in footnote 3. |

Tools, as checked on 2026-11-10. Sizes and versions change; they are confirmed
again when the versions are pinned.

| | |
|---|---|
| T1 | Ollama model library: `qwen3:8b` 5.2 GB with tool calling; `qwen3.5:9b` 6.6 GB; `gemma4:12b` about 8 GB; `qwen3:14b` 8 to 9 GB. https://ollama.com/library |
| T2 | `nomic-embed-text` on Ollama: 274 MB, 768 dimensions, 8,192-token input, separate prefixes for queries and documents. https://ollama.com/library/nomic-embed-text |
| T3 | `BAAI/bge-reranker-v2-m3` on Hugging Face: Apache 2.0, about 568 million parameters. https://huggingface.co/BAAI/bge-reranker-v2-m3 |
| T4 | LangGraph, interrupts and human-in-the-loop: an interrupt needs a checkpointer, and the interrupted node runs again from its start on resume. https://docs.langchain.com/oss/python/langgraph/interrupts |
| T5 | MCP Python SDK (`mcp`), version 2 current since 2026, with a different server class from version 1. https://github.com/modelcontextprotocol/python-sdk |
| T6 | LangChain 1.x: the ensemble and compression retriever classes are in the separate legacy package `langchain-classic`. https://docs.langchain.com/oss/python/integrations/document_transformers/cross_encoder_reranker |
| T7 | LangChain adapter for MCP tools (`langchain-mcp-adapters`). https://github.com/langchain-ai/langchain-mcp-adapters |
