# IP Workbench

Risk analytics for a bank investment portfolio of agency MBS, Treasuries and
swap hedges. One deterministic engine answers the questions a portfolio
manager asks every day, from the command line or from Python.

**Status.** This is version 1, the classic tool: no LLM, same inputs give the
same outputs. Version 2 puts a local-LLM agent (LangGraph, MCP, RAG) on top of
the same engine for exception investigation and ad-hoc analysis; it is in
progress and nothing here depends on it.

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

## Quick start

Python 3.10 or newer.

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
the brief and the agent tools of version 2 all read the same objects.

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
controls), [design decisions](docs/DECISIONS.md) (engineering choices) and the
[release 2 design](docs/AGENT_DESIGN.md) (the assistant: not built yet).

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
scripts/           generators for the sample data
tests/             about 150 tests: unit, independent replication, stored regression
                   baseline, documents checked against the code
docs/              business requirements, solution design, functional specification,
                   roadmap, backlog, acceptance script, model summary, sample brief
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

## Tests

```text
pytest                    about 150 tests, under 20 seconds
ruff check .              lint
```

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

## Roadmap

Version 2 adds, on the same engine: the workbench methods as MCP tools, a
LangGraph workflow that investigates limit breaches and unusual moves and
stops for approval, retrieval over policy and model documents, and a benchmark
that records where the agent helps and where the classic tool is the better
choice. The business requirements for it are BR-11 to BR-13 in
[docs/BRD.md](docs/BRD.md); the design is in
[docs/AGENT_DESIGN.md](docs/AGENT_DESIGN.md); the stories and their order are
in [docs/PRD.md](docs/PRD.md) and [docs/BACKLOG.md](docs/BACKLOG.md).
