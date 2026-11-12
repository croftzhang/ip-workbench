# IP Workbench

Risk analytics for a bank investment portfolio of agency MBS, Treasuries and
swap hedges. One deterministic engine answers the questions a portfolio
manager asks every day, in two modes:

| Command | Mode | What it is |
|---|---|---|
| `ipw` | Classic | Fixed commands and a daily brief. No language model: the same inputs give the same outputs |
| `ipw-ai` | AI | A local language model answers questions in plain English by calling the same engine through typed tools, cites the desk's own documents, and shows an answer only after code has checked every figure in it |

**Status.** Both releases are built. Release 1 is classic mode. Release 2 is AI
mode: a local model through Ollama, retrieval over a Chroma index, tool calling
orchestrated with LangGraph, and an optional MCP server. AI mode was measured
on fixed question sets and the results are published as measured, including
where it is worse than the plain command
([docs/EVALUATION.md](docs/EVALUATION.md)).

> The portfolio, marks and limits in this repository are illustrative. They do
> not describe any institution. See [What the data is](#what-the-data-is).

## What it answers

| Question | Command |
|---|---|
| What do we own and what is it worth against book? | `ipw summary` |
| How much rate risk do we carry, and where on the curve? | `ipw risk`, `ipw krd` |
| What happens if rates, spreads or prepayments move? | `ipw scenario` |
| What does that do to AOCI and to next year's income? | `ipw scenario`, `ipw nii` |
| Are we inside policy limits? If not, what brings us back? | `ipw limits`, `ipw fix` |
| How much hedge reaches a duration target? | `ipw hedge` |
| What if we sell these positions and add that swap? | `ipw whatif` |
| Why did value change since yesterday? | `ipw explain` |
| What are borrowers expected to do? | `ipw prepay` |
| Give me the daily report. | `ipw brief` |
| A question no command covers, in plain English | `ipw-ai ask "..."` |
| What does our policy say about this, and where? | `ipw-ai ask "..."` |
| Why is this limit breached, and what could fix it? | `ipw-ai investigate AOCI_UP200` |
| How good is the assistant, measured? | `ipw-ai eval` |

## Quick start

Python 3.10 or newer. Classic mode needs nothing else; AI mode is an optional
install on top of it ([below](#ai-mode)).

**Windows (PowerShell)**

```powershell
git clone <your-repository-url> ip-workbench
cd ip-workbench
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

ipw limits
ipw brief
pytest
```

If PowerShell refuses to run the activation script, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

**macOS / Linux**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ipw limits && ipw brief && pytest
```

`ipw` finds `config/` and `data/` from the repository folder or any folder
below it. From elsewhere, pass `--root <folder>` or set `IPW_HOME`.

## A five-minute tour

```text
ipw summary                       composition, book value, market value, unrealized
ipw risk                          duration, convexity, DV01 by coupon bucket, with hedges
ipw krd                           key-rate durations on the par curve
ipw scenario                      every scenario in config/scenarios.yaml
ipw scenario -s 200 --by bucket   where the +200bp loss comes from
ipw limits                        policy limits with utilisation and status
ipw fix AOCI_UP200                swap sizes that cure the breached limit
ipw whatif --pay-fixed 5:260      the book before and after that trade
ipw explain                       change since the prior close, by driver
ipw brief                         writes reports/brief_<date>.md
```

Add `-f md` or `-f json` before the command for Markdown or JSON output, for
example `ipw -f json limits`. `ipw <command> --help` lists the options. Tables
are never truncated; the widest (`ipw scenario`) needs about 165 columns, so
widen the window if lines wrap.

`ipw limits` on the sample book:

| ID | Limit | Value | Min | Max | Unit | Used % | Status | Policy |
| :--- | :--- | ---: | ---: | ---: | :--- | ---: | :--- | :--- |
| DUR_BAND | Net effective duration | 5.30 | 3.00 | 5.50 | years | 84 | WARN | IPS 4.1 |
| DUR_DRIFT_DN100 | Duration contraction, -100bp | -0.56 | -0.80 | - | years | 70 | OK | IPS 4.2 |
| DUR_DRIFT_UP100 | Duration extension, +100bp | -0.08 | - | 0.50 | years | 0 | OK | IPS 4.2 |
| CONVEXITY | Net effective convexity | 0.21 | -0.50 | - |  | 0 | OK | IPS 4.2 |
| AOCI_UP200 | AOCI change, +200bp (after tax) | -225.99 | -210.00 | - | $mm | 108 | BREACH | IPS 4.3 |
| EVE_UP200 | Economic value change, +200bp | -9.78 | -13.00 | - | % | 75 | OK | IPS 4.4 |
| NII_UP100 | 12-month NII change, +100bp | -21.06 | -30.00 | - | $mm | 70 | OK | IPS 4.5 |
| NII_DN100 | 12-month NII change, -100bp | 18.45 | -30.00 | - | $mm | 0 | OK | IPS 4.5 |
| HTM_SHARE | HTM share of book value | 59.93 | - | 80.00 | % | 75 | OK | IPS 3.2 |

`ipw fix AOCI_UP200` then sizes three ways to cure the breach:

```text
 Option          Notional   Fixed %    Before     After   Used %   Net dur   Chg NII   Breaches after
 PAY_FIXED 2Y       570.0     4.560   -225.99   -209.98      100      5.18      -1.5                0
 PAY_FIXED 5Y       260.0     4.690   -225.99   -209.40      100      5.17      -1.0                0
 PAY_FIXED 10Y      150.0     4.880   -225.99   -209.62      100      5.17      -0.9                0
```

A full sample report is in
[docs/examples/brief_2026-11-09.md](docs/examples/brief_2026-11-09.md).

## AI mode

AI mode adds three things to the install: the `agent` extra (LangGraph, the
LangChain core and its Ollama and Chroma integrations, Chroma, and the MCP SDK,
at pinned versions), [Ollama](https://ollama.com), and two local models.
Nothing leaves the machine. It was measured on a Windows PC with an NVIDIA RTX
3060 with 12 GB of memory; on a smaller card, or on the processor alone, it is
slower.

```powershell
pip install -e ".[dev,agent]"
ollama pull qwen3:8b               # the chat model, about 5 GB
ollama pull nomic-embed-text       # the embedding model
ipw-ai kb build                    # Indexed 130 passages from 8 documents ...
ipw-ai ask "What is the net effective duration of the book?"
ipw-ai investigate AOCI_UP200
```

Start Ollama before the first `ipw-ai` command. A question builds the index
itself when it is missing or older than the documents, so `ipw-ai kb build` is
optional.

### What an answer looks like

```text
> ipw-ai ask "What has to happen on the day a limit is breached?"

On the day a limit is breached, a breach is reported to the Head of Investment
Portfolio and to market risk oversight, together with a remediation proposal.
The proposal holds at least two sized options, each with its cost to income and
its effect on every other limit. This is outlined in [IPS 5.3].

Sources
[IPS 5.3] Investment Policy Statement > 5. Monitoring, warnings and breaches > 5.3 Breach

Run ...: 0 tool calls; check passed on draft 1. Logged to logs/agent_runs.jsonl.
```

A question about the book is answered from tool results, and the tables those
results hold are printed under the answer:

```text
> ipw-ai ask "What is the net effective duration of the book?"

The net effective duration of the book is 5.30 years.

r1  Interest-rate risk (bump and revalue, prepayments re-projected)
 ... the risk table, whose Net row shows eff_duration 5.30 ...

Run ...: 1 tool calls; check passed on draft 1. Logged to logs/agent_runs.jsonl.
```

Both answers are those of the measured run. A question the documents do not
cover gets "The knowledge base does not cover this."

### How it answers

```text
 question
    |
    v
 retrieve ............ code: the 4 passages nearest the question, or none
    |
    v
 model  <---->  tools  the language model chooses a tool and its arguments;
    |                  the tool runs on the release 1 engine; at most 8 calls
    v
 check ............... code: every figure and citation of the draft is verified;
    |                  one redraft, otherwise the answer is blocked
    v
 answer, the tables it rests on, and one line in the run log
```

* **The model never computes.** It chooses tools and words the answer. A sum,
  a difference or a share comes from the `aggregate` tool.
* **Nothing is shown unchecked.** Every number in a draft must be a figure of a
  tool result, of a cited passage or of the question. A draft that fails gets
  one more attempt; then the answer is blocked and only the tables are shown.
* **Proposals are labelled by code.** An answer that sized a trade starts with
  "Indicative only: not approved, no action taken." Nothing is traded or
  booked.
* **Every run is logged** with its tool calls, a hash of each result, the
  passages and each draft, so its figures can be reproduced with the classic
  commands.

What the check does not catch: a correct figure attached to the wrong label or
the wrong meaning. Answer correctness is measured separately for that reason.

### Commands

| Command | Purpose |
|---|---|
| `ipw-ai ask "..."` | One question, one checked answer |
| `ipw-ai investigate AOCI_UP200` | The investigation playbook for a limit: where it stands, why, what the policy says, sized options |
| `ipw-ai kb build` | Split, embed and index the knowledge base |
| `ipw-ai eval` | The evaluation report, written to `reports/`; `ipw-ai eval --mock` runs it without models |
| `ipw-ai mcp` | Optional: the same fifteen tools for any other MCP client |

Every setting (models, retrieval, budgets) is in `config/agent.yaml`. The
design, with the options considered for each choice, is in
[docs/AGENT_DESIGN.md](docs/AGENT_DESIGN.md).

### What was measured

One run on the reference machine on 2026-11-10, with `qwen3:8b`: thirty
benchmark tasks in three classes, thirty retrieval questions and ten questions
outside the knowledge base.

| Measure | Result |
|---|---|
| Retrieval hit rate at 4 | 96.7% (29 of 30) |
| Refusal correctness, the assistant | 100.0% (10 of 10) |
| Tool-selection accuracy | 80.0% (16 of 20) |
| First-draft pass rate | 76.7% (23 of 30) |
| Block rate | 0.0% (0 of 30) |
| Answer correctness | 60.0% (18 of 30) |
| Time to answer | median 3.9 s; 90th percentile 9.2 s |

| Class of task | Classic mode | AI mode, correct |
|---|---|---|
| Routine query | One command, about 0.02 seconds, always right | 7 of 10, median 3.8 seconds |
| Composed analysis | Several commands and arithmetic by hand | 4 of 10 |
| Question needing the documents | Cannot answer | 7 of 10, with the section cited |

For a routine question the classic command is the better tool. AI mode adds
answers from the desk's documents, which classic mode cannot give, and a first
investigation of a breach, which ran all six of its steps. Composed analysis is
not dependable with this model. No shown answer held an unchecked figure, but a
checked figure is not a correct answer: the wrong answers use real figures for
the wrong group, row or quantity. [docs/EVALUATION.md](docs/EVALUATION.md)
lists every task, every wrong answer and why it was wrong.

## What the sample book shows

* **Most of the loss is outside equity.** Market value is USD 8,909mm against
  book value USD 10,149mm. Of the USD 1,240mm unrealized loss, USD 1,175mm sits in
  held-to-maturity securities bought at a premium in 2020-21; only USD 65mm is in
  available-for-sale securities and reaches AOCI.
* **The book shortens in a rally.** Net duration is 5.30 years today and 4.74
  after a 100bp rally. The 2.0-3.0 coupons are locked in and do not react. The
  5.5-6.5 coupons sit just below the refinancing threshold: the rally takes
  their projected speed from about 7 to about 16 CPR, and to 21 for the 6.5s.
* **One limit is breached.** A 200bp sell-off would take USD 226mm after tax out
  of AOCI against a floor of USD 210mm. USD 260mm of 5-year pay-fixed swaps cures
  it, costs about USD 1mm of income a year, and also brings duration back from
  its warning level.
* **Income falls when rates rise.** Twelve-month NII is USD 104mm and drops by
  USD 21mm in a 100bp sell-off. Funding cost rises by USD 40mm; hedge carry gives
  USD 15mm back.

## From Python

```python
from ipw import Workbench

wb = Workbench.load()  # reads config/ and data/
wb.headline()["net_duration"]  # 5.30
wb.run("up_200").aoci.after_tax  # -225.99
wb.scenario_table(["dn_100", 100, "refi_wave"])
wb.risk_table(by="coupon")

fix = wb.fix_limit("AOCI_UP200", tenor=5)  # size the swap, verify by revaluation
fix.trades  # the proposed trade
fix.result.limit_table()  # every limit with the trade added

after = wb.what_if(drop=["FN30-6.5-029"], add_swaps=fix.trades)
wb.compare(after)  # before and after, side by side
```

Every method returns a pandas table or a small dataclass. The command line,
the brief and the tools of AI mode all read the same objects. The tools can be
called from Python too:

```python
from ipw.agent.tools import Toolbox

tools = Toolbox(wb)
status = tools.call("limit_status")  # result r1: the limit table, headroom included
status.table().rows["AOCI_UP200"]["headroom"]  # -15.99
```

## Documentation

The documents follow one chain, from the business need to the test that proves
it. Every requirement has a number, and the same numbers appear at each step.

| Step | Document | Answers |
|---|---|---|
| 1 | [Business requirements](docs/BRD.md) | What does the desk need, under which rules, and why? No solution in it. |
| 2 | [Solution design](docs/SOLUTION_DESIGN.md) | Which analytical approach meets each need, what else was considered, and what was deferred? |
| 3 | [Functional specification](docs/FUNCTIONAL_SPEC.md) | What exactly is computed? Every formula in full, with its source and its place in the code. |
| 4 | [Roadmap and user stories](docs/PRD.md), [backlog](docs/BACKLOG.md) | What is built in which release, and in what order? |
| 5 | [Acceptance script](docs/UAT.md) | How does a user confirm it does what was asked? |

Alongside: [model summary](docs/MODEL.md) (method in brief, limitations,
controls), [design decisions](docs/DECISIONS.md) (engineering choices), the
[release 2 design](docs/AGENT_DESIGN.md) (the assistant: options considered,
decisions, controls) and the [evaluation record](docs/EVALUATION.md) (what the
assistant did on the reference machine).

The assistant embeds and cites some of these documents and never reads the
others. In its knowledge base: the six policy and reference documents in
`kb/`, the functional specification and the model summary. Not in it:
everything else, this README included.

One requirement followed through:

| Step | Reference | Content |
|---|---|---|
| Need | BR-6 | When a limit is breached, show the smallest actions that bring the book back inside it. |
| Design | SD-9 | Size a pay-fixed swap by using the fact that the limit metric is linear in swap notional. |
| Function | FR-11 | Equations 11.1 to 11.3: notional per tenor, rounded up, then checked by full revaluation. |
| Code | `ipw.core.workbench.Workbench.fix_limit` | Command `ipw fix AOCI_UP200` |
| Test | `test_fix_limit_cures_the_breach_with_the_smallest_round_notional` | Runs on every commit |
| Acceptance | UAT-06 | The user runs the command and confirms the breach clears. |

The same table for every requirement is the traceability matrix at the end of
the functional specification. `tests/test_spec_sync.py` fails the build if a
document names a function, test, command or parameter value that no longer
exists, or if the requirement numbers stop matching between documents.

## How the numbers are built

```text
 market.yaml + marks.csv        portfolio.csv + hedges.csv        model.yaml
          |                                 |                          |
          v                                 v                          v
   par curve -> discount factors       positions                parameters
          |                                 |                          |
          +------------> rate environment (forward curve, mortgage rate path)
                                   |
                                   v
              products project cash flows (prepayment model inside the MBS product)
                                   |
                                   v
                 pricer: discount on curve + calibrated spread
                                   |
                 one revaluation of the book (about 5 milliseconds)
                                   |
        +-----------+-------------+-------------+--------------+-----------+
        v           v             v             v              v           v
   duration,    scenarios      AOCI and      hedge sizing    limits     explain
   convexity,                  12-month NII  and what-if     and fix
   key rates
```

Everything after the revaluation is a difference between revaluations. Every
formula, with its source, is in
[docs/FUNCTIONAL_SPEC.md](docs/FUNCTIONAL_SPEC.md); the limitations are in
[docs/MODEL.md](docs/MODEL.md).

## What the data is

| File | Content | Real or constructed |
|---|---|---|
| `config/market.yaml` | Treasury par curve and mortgage rates for 2026-11-09 | 10-year yield and 30-year mortgage rate rounded from public levels; other points filled in by hand |
| `config/market_prev.yaml` | Prior close | Constructed: yields 1 to 8bp lower, spreads 2bp tighter |
| `data/portfolio.csv` | 88 positions, USD 10bn face | Constructed by `scripts/generate_portfolio.py` (fixed seed) |
| `data/marks.csv` | Position prices for both closes | Model prices at an assumed spread per coupon, rounded to 1/32 (`scripts/build_market.py`) |
| `data/hedges.csv` | Five pay-fixed swaps, USD 1.5bn | Constructed |
| `config/limits.yaml` | Nine policy limits | Constructed, set so the book starts with one breach and one warning |
| `kb/` | Investment policy, hedging policy, AFS and HTM accounting note, scenario definitions, MBS primer, glossary | Constructed; tests check that they state the limits, scenarios and parameters of the configuration |
| `evals/` | Retrieval questions and benchmark tasks | Written for this repository; no figure is stored, the reference values are read from the engine when the evaluation runs |

To run on real data, replace these files; nothing else depends on the scripts.

## Repository layout

```text
config/            market closes, model parameters, scenarios, limits (YAML)
data/              positions, hedges, marks (CSV)
src/ipw/core/      the engine; no presentation, no LLM
  curve.py           par curve, bootstrap, shocks
  prepay.py          prepayment model
  products.py        pass-through, Treasury and swap cash flows
  pricing.py         discounting, spread and yield solver
  engine.py          rate environment, calibration, revaluation
  risk.py            duration, convexity, key rates
  balance_sheet.py   AOCI and net interest income
  hedging.py         swap sizing
  limits.py          limit definitions and status
  explain.py         day-over-day attribution
  workbench.py       the facade everything else calls
src/ipw/classic/   command line, table rendering, daily brief
src/ipw/agent/     AI mode; imports the engine, never the other way round
  tools.py           the fifteen typed tools over the workbench
  kb.py              split, embed and index the knowledge base
  retrieval.py       vector search, optional keyword fusion and rerank, refusal
  graph.py           the four-node loop and the investigation playbook
  verify.py          the check on figures and citations
  runlog.py          the run log
  evals.py           question sets, scoring and measures
  evalreport.py      the evaluation report
  mcp_server.py      the optional MCP server
  cli.py             the ipw-ai commands
config/agent.yaml  models, retrieval settings and budgets of AI mode
kb/                the documents the assistant cites
evals/             retrieval questions and benchmark tasks
scripts/           generators for the sample data
tests/             unit, independent replication, stored regression baseline,
                   documents checked against the code
tests/agent/       AI mode, on a mock model: no language model or GPU needed
docs/              requirements, designs, functional specification, roadmap,
                   backlog, acceptance script, model summary, evaluation record
```

To read the code, follow the order of the files under `src/ipw/core/` above.
Each one is 50 to 250 lines except the workbench.

## Changing things without code

* **A scenario.** Add an entry to `config/scenarios.yaml`: curve points,
  spread move, mortgage-spread move, prepayment multipliers. Any parallel
  shock also runs ad hoc: `ipw scenario -s -75`.
* **A limit.** Add an entry to `config/limits.yaml` with a metric, an optional
  scenario and a floor or cap. `ipw limits` and the brief pick it up.
* **A model parameter.** Edit `config/model.yaml`. The regression test will
  fail until the stored values are refreshed, by design.
* **The chat model of AI mode.** Change `chat.model` in `config/agent.yaml`,
  pull the model with Ollama and run `ipw-ai eval`. The report records the
  model and the machine, so the run can be compared with the published one.

## Adding a product

A product is one class with one method, `project(positions, env) -> CashFlows`.
Pricing, risk, scenarios, AOCI, NII, hedging and limits work on cash flows and
need no change.

| Product | What it needs | Effort |
|---|---|---|
| Agency bullets, other swap tenors | Nothing new | Low |
| Mortgage servicing rights | Servicing-strip cash flows on the existing prepayment model | Low to medium |
| Adjustable-rate mortgages | Forward-rate resets | Medium |
| Agency CMO | A tranche waterfall | Medium |
| CMBS, non-agency RMBS | Default and loss models, waterfall | High |
| Callable debt, caps, swaptions | A volatility model | Outside the static method |

## Adding an analytic to AI mode

A new analytic is a method on the workbench and one tool definition in
`src/ipw/agent/tools.py`. It then appears in the assistant and in the MCP
server, with a schema whose allowed values come from the configuration.

## Tests

```text
pytest                    more than 400 tests, about two minutes; no language model needed
ruff check .              lint
ipw-ai eval --mock        the whole evaluation on the mock model
```

AI mode is tested on a mock model and fixed word-hash embeddings, so the tests
need no model, no Ollama and no GPU. Without the `agent` extra its tests are
skipped and the rest run. Continuous integration runs lint, the tests, a smoke
test of the commands and the mock evaluation on Windows and Linux, with
Python 3.10 and 3.12.

Every release 1 user story has tests named after it; the full list is in
section 4.1 of [docs/PRD.md](docs/PRD.md). Five of them:

| Story | Criterion | Test |
|---|---|---|
| US-1 | Standard shocks in under 5 seconds; results match stored values | `test_us1_standard_shocks_run_within_five_seconds`, `test_us1_results_match_stored_values` |
| US-2 | Key-rate durations add up to effective duration | `test_us2_key_rate_durations_add_up_to_effective_duration` |
| US-3 | Hedge reaches the duration target within 0.05 years | `test_us3_hedge_reaches_the_duration_target` |
| US-4 | HTM excluded from AOCI; breaches flagged | `test_us4_htm_positions_never_reach_aoci`, `test_us4_breach_is_flagged` |
| US-5 | Brief complete, with the workbench's numbers | `test_us5_brief_has_every_section_and_the_same_numbers_as_the_workbench` |

`tests/test_replication.py` re-implements the whole valuation chain for single
positions in plain Python, written from the functional specification and importing
nothing from the engine; its prices match the engine's to seven decimals, at
today's market and under +/-100bp shocks. Swap values are also checked against
the annuity formula and Treasury durations against modified duration. See
section 5 of the [model summary](docs/MODEL.md).

## Known limitations

* Valuation is on one zero-volatility path with a static spread. There is no
  option-adjusted spread, so durations of coupons near the refinancing
  threshold are longer than OAS-model durations.
* The prepayment model is stylised and not calibrated to pool data.
* Swaps are valued on the Treasury curve; swap spreads are ignored.
* The funding side of NII is a blended rate with an assumed beta.
* Hedge accounting is simplified to fully effective fair-value hedges.

The full table, with the direction of each bias, is in
[docs/MODEL.md](docs/MODEL.md#3-assumptions-and-limitations).

AI mode:

* The check verifies where each figure comes from, not what it means. In the
  measured investigation every figure was right, and one statement named the
  wrong bucket as the second source of the exposure.
* With `qwen3:8b`, 18 of 30 benchmark answers are correct; composed analysis
  is 4 of 10. The most frequent mistake is asking a tool for the wrong
  grouping. No other model has been measured.
* The investigation is a prompt, not a fixed procedure: the model can change
  the arguments of a step or skip it. The run log shows what it did.
* There is no recorded approval. Proposals are labelled indicative and the
  system creates nothing.
* The evaluation is one run on one machine, with small task sets written for
  this repository.

## Not built

Deferred from release 2: a stop for a recorded approval of a proposal (US-8),
and an automatic warning when a result rests on a weak part of the model
(US-15). The design records what each would take
([docs/AGENT_DESIGN.md](docs/AGENT_DESIGN.md), section 6). The evaluation
points to three further candidates
([docs/EVALUATION.md](docs/EVALUATION.md), section 11), listed with the
not-scheduled items of release 1 in [docs/BACKLOG.md](docs/BACKLOG.md).
