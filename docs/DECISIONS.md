# Design decisions

Short records of the choices that shaped the code, with the alternative that
was not taken and what the choice costs.

### D1. One engine, two front ends
**Decision.** All numbers come from `ipw.core`. The classic CLI (version 1) and
the agent (version 2) are thin layers that call the same `Workbench` methods.
**Instead of** separate analytics for the AI version.
**Cost and benefit.** The agent can be removed without changing a single
result, and model validation only has to cover `ipw.core`. The agent cannot do
anything the engine does not expose as a method.

### D2. Products return cash flows; nothing else knows the product
**Decision.** A product implements `project(positions, env) -> CashFlows`.
Pricing, risk, scenarios, AOCI, NII, hedging and limits work on cash flows.
**Instead of** product-specific pricing and risk functions.
**Cost and benefit.** A new product is one class. Products that cannot be
written as cash flows on a single path (options) do not fit.

### D3. Static spread on one path, not Monte Carlo OAS
**Decision.** Zero-volatility valuation: forwards are realised, MBS are
discounted at a calibrated static spread.
**Instead of** a short-rate model with simulated paths.
**Cost and benefit.** The whole book revalues in about 5 milliseconds, every
number is reproducible to the last digit, and the code is short enough to
read. Option cost is not measured; `docs/MODEL.md` section 3 says where that
biases the results. The product interface is the same one a path-based pricer
would call.

### D4. Bump and revalue for all sensitivities
**Decision.** Duration, convexity, DV01 and key-rate exposures are differences
of full revaluations with prepayments re-projected.
**Instead of** closed-form or cash-flow-fixed durations.
**Cost and benefit.** The mortgage option shows up in the numbers. Fourteen
revaluations per risk run, which D3 makes cheap.

### D5. Key rates on the par curve
**Decision.** Key-rate shocks are hat functions on par yields.
**Instead of** shocks to zero rates.
**Cost and benefit.** A par swap loads almost entirely on its own key rate, so
the key-rate report maps directly to hedge instruments. Long zero-coupon cash
flows can show small negative exposures at shorter key rates.

### D6. Positions are calibrated to marks
**Decision.** Each MBS position's spread is solved from its own price. A
coupon stack is the fallback for positions without a mark.
**Instead of** assuming a spread and computing a price.
**Cost and benefit.** Base valuation agrees with the marks by construction and
the explain can attribute what is left to spread moves. The engine cannot
price a security it has no price for, other than at a default spread.

### D7. Scenarios, limits and model parameters are data
**Decision.** YAML files, validated on load; unknown keys are errors.
**Instead of** constants in code.
**Cost and benefit.** A risk manager can add a scenario or a limit on any
scenario without touching Python. A limit can only use metrics the workbench
knows.

### D8. The workbench returns tables, not text
**Decision.** `Workbench` methods return pandas tables and small dataclasses.
Labels and number formats live in `ipw.classic.render`.
**Instead of** methods that print.
**Cost and benefit.** The CLI, the Markdown brief, JSON output and the agent
tools all read the same objects.

### D9. A what-if is a new workbench
**Decision.** `what_if()` returns a new `Workbench` with positions removed or
added. The original is never changed.
**Instead of** editing the book in place and undoing it.
**Cost and benefit.** Before and after can be compared side by side and
nothing can be left half-applied. Each what-if recomputes the book, which
takes a fraction of a second.

### D10. Limit fixes use linearity, then verify
**Decision.** Size a swap from two evaluations of the limit metric, round up,
and confirm with a full revaluation.
**Instead of** a numerical search.
**Cost and benefit.** Exact for every rate-risk limit and fast. Limits that
swaps cannot move (portfolio composition) are refused with a clear message.

### D11. Hedges are swaps only
**Decision.** Hedge instruments are par swaps valued on the Treasury curve.
**Instead of** adding Treasury futures and a separate swap curve.
**Cost and benefit.** No cheapest-to-deliver or swap-spread modelling. Hedge
sizes are indicative.

### D12. Illustrative data anchored to public levels
**Decision.** The curve and the 30-year mortgage rate are rounded from public
early-November-2026 levels; the portfolio, marks and limits are constructed.
`scripts/` holds the generators.
**Instead of** real pool data or arbitrary numbers.
**Cost and benefit.** The repository can be published and the numbers look
like a real book in the current rate environment. Nothing in it is evidence
about any institution.

### D13. Plain ASCII output
**Decision.** Reports and the brief use only ASCII characters.
**Instead of** symbols such as the delta sign.
**Cost and benefit.** Works on any Windows console and code page. Column
headers say "Chg" instead of a symbol.

### D14. A stored regression baseline
**Decision.** About seventy headline numbers are stored in `tests/golden.json`
and compared on every test run.
**Instead of** only property-style tests.
**Cost and benefit.** A change in results is always visible in a diff. The
file has to be regenerated, and the diff reviewed, after intended changes.

### D15. Documents are checked by the build
**Decision.** `tests/test_spec_sync.py` reads the requirement documents and
fails if a function, test, command, file or parameter value they name does not
exist, if a requirement number is not carried from the business requirements
through to an acceptance case, or if a figure in the acceptance script is not
what the command prints.
**Instead of** reviewing the documents by hand at each release.
**Cost and benefit.** A formula in the specification can still be wrong in a
way no script detects, which is what the independent replication is for. What
the check removes is the common failure: a document that describes last
quarter's code. Writing a reference now means writing it in a form the check
can read.

### D16. Formulas written for GitHub's renderer
**Decision.** Display formulas sit in fenced `math` blocks and carry their
number as text at the end of the line; inline formulas avoid asterisks and
backslashes before punctuation. A test enforces both.
**Instead of** dollar-sign display blocks with LaTeX equation tags.
**Cost and benefit.** GitHub lays out a tagged equation as a column one
character wide, and Markdown can read characters inside dollar signs as
formatting. The fenced form is not touched by Markdown and renders the same in
every browser. A viewer that does not know math fences shows the LaTeX source
in a code box instead of a typeset formula.
