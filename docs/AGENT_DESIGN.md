# Solution Design, Release 2: the Assistant

**Investment Portfolio Risk Analytics**

| | |
|---|---|
| Document | Solution design for release 2, version 1.5 |
| Status | Design agreed. Scope simplified by the owner on 2026-11-10 to four things: a local language model, retrieval, tool calling and the engine's analytics. On the same day the owner named the two commands: `ipw` is classic mode and `ipw-ai` is AI mode. Built and measured: steps 1 to 5 of section 10 are done ([EVALUATION.md](EVALUATION.md)) |
| Owner | Product Owner, Investment Portfolio analytics |
| Last updated | 2026-11-11 |
| Traces to | [BRD.md](BRD.md): BR-11 to BR-13, RULE-7, NFR-1, NFR-5 to NFR-7. [PRD.md](PRD.md): US-6 to US-16, of which US-8 and US-15 are deferred |
| Previous in the chain | [SOLUTION_DESIGN.md](SOLUTION_DESIGN.md), which covers release 1 |

> The desk, its roles, its policy documents and every figure in this document
> are illustrative. They do not describe any institution.

## Contents

1. Purpose and scope
2. Requirements addressed
3. Principles
4. The solution on one page
5. Design decisions AD-1 to AD-9
6. Deferred and not adopted
7. Repository layout
8. Control position
9. Risks
10. Build plan
11. Open points
12. References

## 1. Purpose and scope

Release 1 answers the standard questions with fixed commands. Release 2 is for
the work those commands cannot do without someone writing new code:

* an ad-hoc analysis composed from several existing calculations;
* a first investigation of a limit breach or an unusual move;
* joining a number with the written rule or model document that applies to it.

Release 2 consists of four things and a way of measuring them:

| Part | In one line |
|---|---|
| Local language model | Runs on the user's machine; chooses tools and words answers |
| Retrieval | Finds the passages of the desk's own documents that bear on a question, and cites them |
| Tool calling | The model calls typed tools that wrap the release 1 engine |
| Quantitative analytics | Every figure comes from that engine and is checked before it is shown |
| Evaluation | Fixed question sets, deterministic measures, results published as measured |

Not in release 2 (section 6): a recorded approval step, persistent workflow
state, separate routing and planning steps, automatic attachment of model
limitations, a replay command, any arrangement of several agents, a graphical
interface, fine-tuning of any model, and any service outside the user's
machine.

## 2. Requirements addressed

| Requirement | What the design has to deliver | Decisions |
|---|---|---|
| BR-11 Answers outside the standard pack | A correct, sourced answer in the same conversation, composed from existing calculations | AD-1, AD-3, AD-4, AD-6 |
| BR-12 Investigation of a breach or unusual move | Contributors, the policy clause and sized options, with every step logged. Release 2 presents the options as indicative; the stop for a recorded approval is deferred | AD-4, AD-7 |
| BR-13 Explanations in terms of the bank's own book and documents | Explanations that cite the document and section and use current figures | AD-5, AD-6 |
| RULE-7 The analytics propose; people decide | Nothing is executed or booked; every proposal is labelled indicative. Recording the person's decision in the system is deferred | AD-3, AD-4 |
| NFR-1 Reproducible and auditable | Every figure comes from the deterministic engine; every run is logged with its tool calls | AD-1, AD-7 |
| NFR-5 Confidential | No position, question or document leaves the machine | AD-2 |
| NFR-6 Honest about limitations | The model summary is in the knowledge base and is cited when asked; measured failures are published | AD-5, AD-8 |
| NFR-7 Controlled change | A change of model, prompt or retrieval setting is judged by the same evaluation before it becomes the default | AD-8 |

## 3. Principles

| Principle | Consequence |
|---|---|
| The language model never computes | It chooses tools, fills their arguments and words the answer. Every figure is produced by the release 1 engine |
| Nothing is shown unchecked | Code compares every figure in a draft answer with the tool results before the answer is displayed |
| Everything runs on the user's machine | Local models only; no hosted model, no tracing service |
| Simple first | The default path has no optional part. Each optional part is a switch, and becomes a default only if it improves a measured result |
| The assistant is a separate installation | The routine tool stays small and free of language-model code |

## 4. The solution on one page

```text
question
   |
   v
 retrieve ............ code: passages from the knowledge base, with document and section
   |
   v
 model  <---->  tools  language model chooses a tool and its arguments;
   |                   the tool runs on the release 1 engine; at most 8 calls
   v
 check ............... code: every figure and citation in the draft is verified;
   |                   one redraft, otherwise the answer is blocked
   v
 answer + run log
```

Who does what:

| Step | Done by | Can it change a figure? |
|---|---|---|
| Retrieve | Code | No |
| Choose tools and arguments | Language model | Only by asking the engine a different question |
| Run tools | Engine | It is the only source of figures |
| Draft the answer | Language model | No: the check rejects any figure that is not a tool result |
| Check | Code | No |
| Log | Code | No |

Role of each document in release 2. A document is either put into the knowledge
base, where it is split, embedded and retrieved, or it is a reference the
design relies on and the assistant never reads.

| Documents | Role |
|---|---|
| Constructed policy and reference documents in `kb/`: investment policy, hedging policy, AFS and HTM accounting note, scenario definitions, MBS primer, glossary | In the knowledge base: embedded and retrieved |
| [FUNCTIONAL_SPEC.md](FUNCTIONAL_SPEC.md) and [MODEL.md](MODEL.md) | In the knowledge base: embedded and retrieved |
| [BRD.md](BRD.md), [SOLUTION_DESIGN.md](SOLUTION_DESIGN.md), [PRD.md](PRD.md), the backlog, the acceptance script, the decision log, this document and the evaluation record [EVALUATION.md](EVALUATION.md) | Project documentation only; not embedded |
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

**Decision: B** for the chat and embedding models. The optional reranker (AD-5)
is the one model run through Hugging Face and PyTorch, because that is the
established route for cross-encoders and Ollama has no standard reranking
interface.

| Role | Model | Why this one |
|---|---|---|
| Chat, default | `qwen3:8b` | Tool calling built in; 5.2 GB, so it fits a 12 GB card with room for context [T1] |
| Chat, alternatives | `qwen3:14b`, `qwen3.5:9b`, `gemma4:12b` | Same hardware class; any of them is tried by changing one setting and re-running the evaluation [T1] |
| Embeddings | `nomic-embed-text` | 274 MB, 768 dimensions, inputs up to 8,192 tokens; runs on CPU [T2] |
| Reranker, optional | `BAAI/bge-reranker-v2-m3` | Open licence (Apache 2.0), 568 million parameters, the usual self-hosted baseline [T3] |
| Tests | A scripted mock model | Lets the whole path run in continuous integration without a GPU |

Rules: every model name is a configuration value. Chat settings are
temperature 0, a fixed seed, thinking mode off, a capped context length so
the model stays on the GPU, and a capped length of one reply so that a model
that repeats itself is stopped. The reference machine is an RTX 3060 with
12 GB.

### AD-3. Tools (BR-11, US-12)

| Option | For | Against |
|---|---|---|
| A. Tools as Python functions the assistant calls in its own process | Simplest; synchronous; easy to test | Usable by this assistant only |
| B. Tools only behind a Model Context Protocol (MCP) server, with the assistant as its client | One definition for any client | A child process and asynchronous plumbing on the main path of every question |
| **C. Tools defined once as typed functions; the assistant calls them in-process; an optional thin MCP server exposes the same functions** | The main path stays simple; other MCP clients can still use the tools | Two ways in, which a test must keep identical |

**Decision: C.** A tool is a typed function over the release 1 facade. A new
analytic is added once: a method on the workbench and one tool definition,
which then appears both in the assistant and in the MCP server.

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
| `limit_status` | `ipw.core.workbench.Workbench.limit_table`, with the headroom of each limit from `ipw.core.workbench.Workbench.limit_report` | none |
| `limit_remedy` | `ipw.core.workbench.Workbench.fix_limit` | limit id, up to six swap tenors, target |
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
  the check and the run log refer to.
* **Errors are data.** The engine's one-line error is returned to the model,
  which may correct its arguments once.

### AD-4. Orchestration (BR-12, US-13, US-14)

| Option | For | Against |
|---|---|---|
| A. A hand-written loop | No framework | The loop, its budget and its retry rule become code to maintain and explain |
| **B. One small LangGraph graph: retrieve, then model and tools in a loop, then check** | The tool loop, the step budget and the single retry are edges of a graph that can be drawn and tested node by node | A dependency for a small job |
| C. A larger graph with routing, planning, approval and saved state | More control points | More to build and test than the first release needs |
| D. Several cooperating agents | Roles are separated | On one 12 GB card they are the same model taking turns: more calls, slower, more places to fail, harder to evaluate |

**Decision: B.** LangGraph is used for lightweight orchestration only: one
graph, four nodes, no checkpoints, no interrupts, no subgraphs, one model.

| Node | Done by | Produces | If it fails |
|---|---|---|---|
| Retrieve | Code (AD-5) | Passages with document and section, or none above the threshold | Recorded as "not in the knowledge base" |
| Model | Language model with the tools bound | A tool call, or a draft answer with citations | After eight tool calls it must answer with what it has |
| Tools | Code: runs the requested tool | A tool result | The error is returned to the model once for correction |
| Check | Code (AD-6) | Pass, or the list of mismatches | One redraft; then the answer is blocked and the tool tables are shown instead |

The same loop serves every kind of request; what differs is how many tools the
model calls and whether passages are used.

| Request | Example | What the loop does |
|---|---|---|
| Routine | "What is net duration?" | One tool call, answer |
| Composed analysis | "At +200bp, how much more value do the HTM securities lose than the AFS securities?" | Several tool calls, or a tool call and `aggregate`, answer |
| Knowledge | "Which limit applies to AOCI and where is it defined?" | Answer from the retrieved passages, with citations |
| Investigation | "Investigate the AOCI_UP200 breach" | The steps of the playbook below, answer |

**Investigation playbook.** A breach investigation is the same loop started
with an instruction that lists the evidence to gather, in order. It is a
prompt, not a separate workflow; the run log shows which steps were done.

1. `limit_status`: the breach, its headroom (how far the value is outside its bound) and its policy reference.
2. `scenario_breakdown` for the limit's scenario: which buckets carry the loss.
3. `top_positions`: the positions that contribute most.
4. `key_rate_report`: where on the curve the exposure sits.
5. `explain_change`: what moved since the prior close.
6. The policy clause the limit refers to, from the retrieved passages.
7. `limit_remedy` for two or three swap tenors: sized options and their cost to income.

An answer that contains a proposal says so in its first line: indicative, not
approved, no action taken. Code, not the model, decides what counts as a
proposal: a run that called `limit_remedy`, `size_hedge` or `what_if`.

### AD-5. Retrieval (BR-13, US-7)

| Option | For | Against |
|---|---|---|
| **A. Vector search** | One index, one small model, light install | Weak on exact identifiers such as `AOCI_UP200`, "IPS 4.3" or "FR-11" |
| B. Vector and keyword search, fused | Covers both kinds of question | A second index |
| C. As B, then reranked by a cross-encoder | Best ordering of the few passages the model reads | A third model and the PyTorch stack; slower |

**Decision: A is the default. B and C are optional switches, off by default.**
The keyword index is a small pure-Python addition; the reranker needs
sentence-transformers and PyTorch and is installed as a separate extra. The
knowledge base is about ten documents, so the gain from B and C may be small:
the evaluation (AD-8) reports all three, and the default changes only if the
numbers say so.

| Stage | Default | Design |
|---|---|---|
| Split | On | By Markdown heading, with a size cap; a formula stays with its section. Each passage carries document, section number and heading |
| Vector index | On | Chroma, stored locally; embeddings from `nomic-embed-text`, with the prefixes that model requires for queries and for documents [T2] |
| Keyword index and fusion | Off | BM25 over the same passages [A2]; top 20 from each index combined by reciprocal rank fusion [A1] |
| Rerank | Off | The candidates scored against the question by the cross-encoder; the best four are kept |
| Refuse | On | Two guards. First, a threshold on the best score: below it no passage is given and the answer is "the knowledge base does not cover this". The score is the vector similarity, taken before the optional stages, so the threshold means the same whichever switches are on. The threshold belongs to the embedding model and is set low, from the evaluation questions: it removes questions that have nothing to do with the documents and keeps every question that has an answer. Second, the model is told to give the same answer when the passages it receives do not hold one; this guard covers questions near the subject, whose scores overlap with those of answerable questions |
| Cite | On | Every statement taken from a passage carries its document and section |

Reciprocal rank fusion scores a passage $d$ from its rank $r(d)$ in each
ranking $r$ of the set $R$ (here the vector ranking and the keyword ranking),
with the constant $k = 60$ of the original paper [A1]:

```math
\text{RRF}(d) = \sum_{r \in R} \frac{1}{k + r(d)}
```

Fusion and reranking are implemented directly on the LangChain core interfaces
(about a hundred lines) rather than with LangChain's ready-made ensemble and
compression retrievers, which have moved to a legacy package [T6].

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
   A number that is part of a label or of a tool argument (the 200 of
   `up_200`), and a count that code takes from a result (its rows, or how many
   limits have the status BREACH), count as cells.
2. Exempt: dates, identifiers (position, limit and section numbers) and numbers
   the user typed in the question. A number taken from a document is accepted
   when it stands in a retrieved passage that the draft cites; a quotation is
   accepted when it matches a passage word for word.
3. A figure that is not a cell of a result (a total, a difference, a share) is
   allowed only if the `aggregate` tool produced it.
4. Every citation must refer to a passage that was retrieved in this run, or
   to a section that a tool result names, such as a limit's policy reference.
5. On failure the model gets the list of mismatches and one more attempt. For
   a figure that is not in a result it is told the two ways out: leave the
   figure out, or obtain it with `aggregate`. If the second attempt fails, the
   answer is blocked: the user sees the tool tables and a notice, never the
   unverified text.

What the check does not catch: a correct figure attached to the wrong label.
That is measured separately, as answer correctness against reference answers
(AD-8), and every shown answer ends with the tool tables it relied on, rendered
by code, so the labelled source figures are always on the page.

### AD-7. The run log (NFR-1, US-10)

One record per run, appended to a local file as a line of JSON: run id and
time; the question; each tool call with arguments, result id and a hash of the
result; the passages retrieved, with scores; model names and settings; each
draft and the outcome of the check; whether the run contains a proposal.

Because every figure comes from a logged tool call on the deterministic
engine, the figures of an answer can be reproduced by making the same calls
with the release 1 commands; this does not depend on the language model giving
the same words twice.

### AD-8. Evaluation (US-11, US-16, NFR-6, NFR-7)

| Option | For | Against |
|---|---|---|
| A. Demonstration by example | Quick | Shows the cases that work |
| B. Scores from a judging model | Covers free text | Not reproducible with a small local judge |
| **C. Deterministic measures on fixed question sets, published as measured** | Comparable between runs; failures visible | Question sets have to be written and maintained |

**Decision: C**, run by one command.

| Measure | Definition | Set |
|---|---|---|
| Retrieval hit rate at 4 | Share of questions for which a reference section is among the four passages passed to the model | 30 questions with reference sections |
| Refusal correctness | Share of out-of-scope questions answered "not covered". Reported twice: for the assistant, which is asked each question, and for the threshold of AD-5 alone | 10 questions with no answer in the knowledge base |
| Tool-selection accuracy | Share of tasks for which the tools called and their arguments equal the reference | 20 routine tasks |
| First-draft pass rate | Share of first drafts that pass the check of AD-6 | All benchmark tasks |
| Block rate | Share of runs whose answer was blocked after the second draft | All benchmark tasks |
| Answer correctness | Share of tasks whose answer contains every reference pair of label and value | All benchmark tasks |
| Time to answer | Seconds from the question to the checked answer, median and 90th percentile, on the reference machine with the models loaded | All benchmark tasks |

How the measures on tasks are taken:

* **Reference values.** No figure of the engine is stored with a task. A task
  names its reference path, the tool calls that answer it, and the reference
  values are read from the results of that path when the evaluation runs.
* **A pair of label and value.** An answer contains a pair when the value
  stands in it, rounded to the decimals the answer shows, with one of the
  pair's labels in the same sentence or line. A task that needs a document
  also names the sections of which the answer has to cite one.
* **Tool calls equal to the reference.** A task may list more than one accepted
  way to answer. A call matches when the tool is the same and every argument
  the reference names has the same value; an argument the reference does not
  name is free. Calls that returned an error are not counted.
* **A run that fails.** A run that ends in an error counts as not correct. A
  task that was not run is left out and reported as such.

With $Q$ the question set and $G_q$ the reference sections of question $q$:

```math
\text{Hit@}4 = \frac{1}{|Q|} \sum_{q \in Q} \mathbf{1}\left[\, G_q \cap \text{top}_4(q) \neq \varnothing \,\right]
```

The report has two tables:

| Table | Rows | Answers |
|---|---|---|
| Retrieval | Vector search; with keyword fusion; with fusion and reranking (the last only if installed) | Is the default retrieval good enough, and does an optional stage earn its place? |
| Release 1 against release 2 | Thirty tasks in three classes, ten each: routine, composed analysis, questions needing documents | Where does the assistant help, and where is the plain command the better tool? |

The task set holds forty tasks: twenty routine, ten composed and ten needing
documents. The benchmark of thirty is ten of each class; tool-selection
accuracy uses all twenty routine tasks. For each task the set records whether
release 1 answers it: with one command, with several commands and work by
hand, or not at all. The commands it names are run and timed next to the
assistant, and a test confirms that one command shows the figures of a routine
task and that a composed task needs more than that.

The report also lists every task with its outcome and, for each task that was
not answered correctly, what was missing, the tool calls made and the text of
the answer. The same content is written as a data file, so that an answer can
be scored again without running the model again.

The investigation is the fourth kind of request and is not one of the three
classes. The evaluation runs the playbook of AD-4 for every limit in breach
and reports which of its steps were done, whether the answer passed the check,
and the answer itself.

Trying another chat model is not a separate feature: change the model name and
run the same command.

Targets, from the roadmap: retrieval hit rate of at least 85%; no unverified
figure shown. A shown answer passes the check by construction, so first-draft
pass rate and block rate are reported next to it to show how often the check
had to intervene.

Where the measurements run:

| Run | Model | Purpose |
|---|---|---|
| Continuous integration, every commit | A mock model that follows the reference path of each task; fixed fake embeddings | The loop, the tools, the check, the run log and the evaluation code work, and the task set is consistent with the engine. Says nothing about model quality |
| Reference machine, by the owner | The real models | The figures that are published in `docs/EVALUATION.md`, with hardware, model tags and date. Results below target are published as measured |

### AD-9. Packaging and interfaces (NFR-5, US-12)

* **Installation.** An optional extra on top of release 1, installed with
  `pip install -e ".[agent]"`; release 1 keeps working without it. The reranker
  is a second extra, `pip install -e ".[agent,rerank]"`, which brings
  sentence-transformers and PyTorch.
* **Configuration.** One file, `config/agent.yaml`: model names, context
  length, retrieval switches and threshold, the tool-call budget, file
  locations.
* **Two commands, two modes.**

| Command | Mode |
|---|---|
| `ipw` | Classic mode: the fixed commands of release 1 on the deterministic engine |
| `ipw-ai` | AI mode: a local language model, tool calling and retrieval over the same engine |

* **Commands of AI mode.**

| Command | Purpose |
|---|---|
| `ipw-ai ask "..."` | One question, one checked answer |
| `ipw-ai investigate AOCI_UP200` | The investigation playbook for a limit |
| `ipw-ai kb build` | Split, embed and index the knowledge base. A question builds the index first when it is missing or older than its sources |
| `ipw-ai eval` | The evaluation report, written to `reports/`. `ipw-ai eval --mock` runs it without models, on the mock model |
| `ipw-ai mcp` | Optional: serve the same tools to any other MCP client |

* **Interface language.** English, command line only, as in release 1.

## 6. Deferred and not adopted

| Item | Status | What adding it later takes |
|---|---|---|
| Recorded approval of a proposal (US-8; second part of RULE-7) | Deferred | A saved workflow state, a stop after the check triggered by the proposal rule of AD-4, three typed decisions (approve, edit, reject) and a resume command. LangGraph's interrupt is the intended mechanism [T4] |
| Separate routing and planning steps | Deferred | Two more nodes before the loop. Worth adding only if the evaluation shows the single loop losing its way on composed tasks |
| Automatic attachment of model limitations to results (US-15) | Deferred | A trigger rule per limitation, evaluated on tool results. Until then the model summary is retrieved and cited when the question asks for it |
| Replay command | Deferred | Re-execute the logged tool calls and compare result hashes. The log already holds what it needs |
| Several cooperating agents | Not adopted | Nothing in the requirements needs it |

Until the approval step exists, RULE-7 is met as it is for the release 1
commands: the system creates no trade, designation or exception and labels
every proposal indicative; the portfolio manager's approval happens outside the
system and is not recorded by it.

## 7. Repository layout

```text
src/ipw/agent/
  config.py             agent configuration
  models.py             chat, embedding and optional reranker factories; the mock model
  tools.py              the typed tools over the workbench, defined once
  kb.py                 split, embed, index
  retrieval.py          vector search; optional keyword fusion and rerank; refusal
  graph.py              the four-node graph and its budgets
  verify.py             the check on figures and citations
  runlog.py             the run log
  evals.py              question sets, scoring and measures
  evalreport.py         the evaluation report and the record of the run
  mcp_server.py         optional MCP server exposing tools.py
  cli.py                the ipw-ai commands
kb/                     knowledge base sources
evals/                  question sets, reference answers, benchmark tasks
config/agent.yaml       agent configuration
tests/agent/            tests that run on the mock model
docs/EVALUATION.md      measured results from the reference machine
docs/examples/          the data file of the published run
```

Main dependencies of the `agent` extra: LangGraph; the LangChain core package
and its Chroma, Ollama and text-splitter integrations; the Chroma database; a
BM25 implementation; the MCP Python SDK for the optional server. The `rerank`
extra adds sentence-transformers with PyTorch. Exact versions are pinned when
the extras are created. Two of these packages have recently changed their
public interfaces [T5][T6], so the pins are part of the design, not a detail.

## 8. Control position

The valuation engine applies financial theory to produce quantitative estimates
and is a model in the sense of the supervisory guidance on model risk
management; its documentation, limitations and tests are in the functional
specification and the model summary. Release 2 leaves that boundary where it
is: no figure originates outside the engine.

The assistant itself is a generative use of a language model, which that
guidance places outside its scope [A3]. The design therefore does not claim
conformance for the assistant. It states its own controls:

| Risk | Control | Evidence |
|---|---|---|
| A figure is invented or misquoted | Deterministic check before display (AD-6) | First-draft pass rate, block rate |
| A correct figure is attached to the wrong label | Reference answers; tool tables appended to every answer | Answer correctness |
| The wrong tool or arguments | Typed schemas; allowed values from configuration; one corrected retry | Tool-selection accuracy |
| An answer cites a document that does not say it | Citations restricted to retrieved passages; refusal threshold | Hit rate, refusal correctness |
| A proposal is taken as a decision | No tool can write; nothing is executed or booked; every proposal is labelled indicative and marked in the run log. A recorded approval step is deferred (section 6) | Tool tests; run log |
| A result cannot be reproduced | Every figure is a logged call on the deterministic engine (AD-7) | Run log |
| Data leaves the machine | Local models only; no telemetry or tracing service (AD-2) | Dependency and configuration review |
| A change makes the assistant worse | The same evaluation before a new default (AD-8) | Evaluation report per change |

## 9. Risks

| Risk | Effect | Response |
|---|---|---|
| An 8B local model chooses tools poorly on multi-step tasks | Composed analyses fail or are blocked | Step budget; the playbook for investigations; another model is one setting away; failures published |
| A single loop is not enough structure for long tasks | Steps of the playbook skipped | The run log shows which steps were done; routing and planning nodes are the designed next step (section 6) |
| Vector search misses questions that quote an identifier | Wrong or no passage | The keyword switch; measured in the retrieval table |
| Library interfaces move again | Build breaks on a fresh install | Pinned versions; mock-model tests in continuous integration on Windows and Linux |
| The published figures depend on one machine | Not comparable elsewhere | Hardware, model tags and date recorded with every result |
| The check is read as a guarantee of correctness | Over-reliance | AD-6 states what it does not catch; answer correctness is reported beside it |
| Release 2 has no recorded approval | A proposal could be read as agreed | The label on every proposal and the mark in the run log |

## 10. Build plan

| Step | Delivers | Evidence | Status |
|---|---|---|---|
| 1. Tools | The typed tools of AD-3 and the optional MCP server | Each tool returns the same figures as the matching release 1 command; the schema rejects bad arguments; the MCP server lists the same tools | Done |
| 2. Knowledge base and retrieval | Constructed documents, the index, vector search, refusal; the optional switches; the retrieval question set | Retrieval tests on fake embeddings | Done |
| 3. The loop | Graph, check, run log; the `ipw-ai` commands | Mock-model tests for the four kinds of request, a blocked answer and the proposal label | Done |
| 4. Evaluation | Task sets, reference answers, the report | The command runs on the mock model in continuous integration | Done |
| 5. Measurement on the reference machine | `docs/EVALUATION.md`; the defaults confirmed or changed from it | Published results, including tasks that failed | Done: 2026-11-10 |
| 6. Documents | Functional specification for release 2, acceptance cases, README | Document checks extended to the new documents | Partly: the README and the status of the roadmap, backlog and business requirements are brought up to date. A separate release 2 functional specification and acceptance cases were not written; this design and the evaluation record serve in their place |

Steps 1 to 4 and 6 were done without a GPU. Step 5 ran on the reference
machine.

## 11. Open points

| Point | Default if not decided otherwise |
|---|---|
| Whether to add the public text of SR 26-2 to the knowledge base | No: the assistant answers questions about the desk's own policy and model, not about supervisory guidance |
| Which chat model is the default | `qwen3:8b`: the one model measured in [EVALUATION.md](EVALUATION.md), which is a record of results and a reference only. Another model is compared by changing one setting and running the same command |
| Whether keyword fusion or the reranker becomes a default | Neither. In the retrieval table of EVALUATION.md keyword fusion does not raise the hit rate, and the reranker is not measured; both stay optional switches |
| Which deferred item comes first | Open. EVALUATION.md, section 11, lists what the results point to |

## 12. References

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
| T4 | LangGraph, interrupts and human-in-the-loop, for the deferred approval step: an interrupt needs a checkpointer, and the interrupted node runs again from its start on resume. https://docs.langchain.com/oss/python/langgraph/interrupts |
| T5 | MCP Python SDK (`mcp`), version 2 current since 2026, with a different server class from version 1. https://github.com/modelcontextprotocol/python-sdk |
| T6 | LangChain 1.x: the ensemble and compression retriever classes are in the separate legacy package `langchain-classic`. https://docs.langchain.com/oss/python/integrations/document_transformers/cross_encoder_reranker |
| T7 | LangChain adapter for MCP tools (`langchain-mcp-adapters`), not needed while the assistant calls its tools in-process. https://github.com/langchain-ai/langchain-mcp-adapters |
