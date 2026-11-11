# Scenario Definitions

**Investment Portfolio desk**

| | |
|---|---|
| Document | Scenario definitions, version 1.0 |
| Cited as | SCEN and the section number, for example SCEN 3 |
| Role | Knowledge base of the assistant: embedded and retrieved |
| Status | Constructed for this repository; the scenarios equal `config/scenarios.yaml` |

> The desk and every figure in this document are illustrative. They do not
> describe any institution.

## 1. Conventions

A scenario is an instantaneous shock applied to today's market. Positions do
not change, no time passes, and the whole book is revalued with prepayments
projected again on the shocked market.

A scenario is made of up to six parts.

| Part | What it moves | Affects |
|---|---|---|
| `parallel_bp` | Every Treasury par yield, by the same number of basis points | Discounting, and mortgage rates through the 10-year yield |
| `curve_points_bp` | Treasury par yields by tenor: the move is given at a few tenors, interpolated in between and held flat outside them | Discounting, and mortgage rates through the 10-year yield |
| `zv_spread_bp` | The spread at which mortgage securities are discounted | Valuation only; prepayments do not change |
| `mortgage_spread_bp` | The primary mortgage rate, on top of the move in the curve | Prepayments only; discounting does not change |
| `refi_multiplier` | The refinancing response of the prepayment model | Prepayments |
| `turnover_multiplier` | Housing turnover in the prepayment model | Prepayments |

Mortgage rates follow the 10-year Treasury par yield one for one unless a
scenario moves the mortgage spread. The spread of each mortgage position is
held constant unless a scenario moves it.

For each scenario the analytics report the change in value of all securities,
of AFS and of HTM separately, and of the swaps; the change in AOCI after tax
and net of hedges; net interest income over twelve months and its change; and
net duration after the shock.

## 2. Parallel shocks

| Scenario | Description | Parameters |
|---|---|---|
| `dn_200` | Parallel -200bp | `parallel_bp: -200` |
| `dn_100` | Parallel -100bp | `parallel_bp: -100` |
| `dn_50` | Parallel -50bp | `parallel_bp: -50` |
| `up_50` | Parallel +50bp | `parallel_bp: 50` |
| `up_100` | Parallel +100bp | `parallel_bp: 100` |
| `up_200` | Parallel +200bp | `parallel_bp: 200` |

Parallel shocks are the standard measure of exposure to the level of rates and
are the shocks the policy limits use.

## 3. Curve-shape shocks

| Scenario | Description | Parameters |
|---|---|---|
| `bear_steepener` | Long end sells off: 2y flat, 10y +50bp, 30y +75bp | `curve_points_bp: {2: 0, 10: 50, 30: 75}` |
| `bear_flattener` | Front end sells off: 2y +75bp, 10y +25bp, 30y flat | `curve_points_bp: {2: 75, 10: 25, 30: 0}` |
| `bull_steepener` | Front end rallies: 2y -75bp, 10y -25bp, 30y flat | `curve_points_bp: {2: -75, 10: -25, 30: 0}` |
| `bull_flattener` | Long end rallies: 2y flat, 10y -50bp, 30y -75bp | `curve_points_bp: {2: 0, 10: -50, 30: -75}` |

A steepener moves long yields more than short yields; a flattener does the
opposite. Bear means yields rise and bull means they fall. These scenarios
show exposure that a parallel shock hides: a book hedged to a duration target
with one swap tenor can still lose when the curve changes shape.

## 4. Spread shock

| Scenario | Description | Parameters |
|---|---|---|
| `basis_widen_25` | MBS spreads +25bp, Treasury curve unchanged | `zv_spread_bp: 25` |

The spread shock changes the value of mortgage securities and leaves
Treasuries and swaps unchanged. Swaps do not hedge it.

## 5. Prepayment behaviour stress

| Scenario | Description | Parameters |
|---|---|---|
| `prepay_fast` | Refinancing and turnover 25% faster than modelled | `refi_multiplier: 1.25, turnover_multiplier: 1.25` |
| `prepay_slow` | Refinancing and turnover 25% slower than modelled | `refi_multiplier: 0.75, turnover_multiplier: 0.75` |

Rates do not move in these scenarios. They show how much the results depend on
the prepayment model being right, which is the most uncertain input.

## 6. Combined scenarios

| Scenario | Description | Parameters |
|---|---|---|
| `refi_wave` | Rally -100bp, mortgage spread -25bp, refinancing 25% more efficient | `parallel_bp: -100, mortgage_spread_bp: -25, refi_multiplier: 1.25` |
| `sell_off_lock_in` | Sell-off +100bp with turnover 25% slower (deeper lock-in) | `parallel_bp: 100, turnover_multiplier: 0.75` |

A combined scenario moves rates and behaviour together, in the direction in
which they tend to move together: a rally with a strong refinancing response,
and a sell-off in which borrowers move home even less.

## 7. Scenarios used by policy limits

| Scenario | Limits measured under it |
|---|---|
| `dn_100` | `DUR_DRIFT_DN100`, `NII_DN100` |
| `up_100` | `DUR_DRIFT_UP100`, `NII_UP100` |
| `up_200` | `AOCI_UP200`, `EVE_UP200` |

The limits themselves are in the Investment Policy Statement, section 4.

## 8. Other shocks

The name `base` means no shock: today's market, with today's forward rates
realised. Any parallel shock can be run by its size in basis points without
being listed in this document. A new scenario is added by editing the scenario
configuration file; no development is needed.
