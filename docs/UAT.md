# User Acceptance Test Script

**Investment Portfolio Risk Analytics, release 1**

| | |
|---|---|
| Document | UAT script, version 1.0 |
| Owner | Product Owner, Investment Portfolio analytics |
| Last updated | 2026-11-10 |
| Tests against | [BRD.md](BRD.md) business requirements and qualities |

> The desk and all figures are illustrative.

## How to use this script

A business user runs each case on the sample book and marks it Pass or Fail.
The automated tests in `tests/` prove the calculations; this script proves that
a user can get each business answer and that it reads the way the business
expects.

**Before starting.** Install as described in the README, open a terminal in the
repository folder, and widen the window to at least 165 columns. Expected
figures are for the sample book as delivered (market date 2026-11-09). Amounts
are USD millions.

## Cases

### UAT-01 Holdings and value against book (BR-1)

| Step | Action | Expected |
|---|---|---|
| 1 | `ipw summary` | Total row: 88 positions, face 10,000.0, book value 10,149.3, market value 8,909.3, unrealized -1,240.1 |
| 2 | `ipw summary --by designation` | AFS unrealized -65.2; HTM unrealized -1,174.9; the two add up to the total |
| 3 | `ipw position FN30-2.5-001`, then open `data/marks.csv` | Price shown is 79.19, the mark for that position on 2026-11-09 (79.1875) |

Result: [ ] Pass [ ] Fail. Notes:

### UAT-02 Interest-rate risk and where it sits (BR-2)

| Step | Action | Expected |
|---|---|---|
| 1 | `ipw risk` | Securities duration 6.01; hedges -0.71; net 5.30. The 30Y high bucket has negative convexity; the 30Y low bucket has positive convexity |
| 2 | `ipw krd` | The Sum column equals the durations in step 1 (securities 6.01, net 5.30). Hedges reduce the 2Y, 5Y and 10Y points only |

Result: [ ] Pass [ ] Fail. Notes:

### UAT-03 Effect of market moves on value, AOCI and income (BR-3)

| Step | Action | Expected |
|---|---|---|
| 1 | `ipw scenario -n up_200` | Change in AFS -416.6, HTM -575.6, hedges +119.3, AOCI after tax -226.0, net duration after the shock 4.93 |
| 2 | Recompute AOCI by hand: (AFS + hedges) x (1 - 0.24) | (-416.6 + 119.3) x 0.76 = -226.0. HTM is not included |
| 3 | `ipw nii` | Base case 103.6; -100bp 122.1; +100bp 82.6. In each column the components add up to the total |
| 4 | `ipw scenario` | Every scenario in `config/scenarios.yaml` appears with value, AOCI, income and duration on one row |

Result: [ ] Pass [ ] Fail. Notes:

### UAT-04 Prepayment behaviour and its uncertainty (BR-4)

| Step | Action | Expected |
|---|---|---|
| 1 | `ipw prepay` | 30Y low coupons: 3.9 CPR today and after both shocks (locked in). 30Y high coupons: 6.6 today, 16.1 after -100bp |
| 2 | `ipw prepay --s-curve` | Speed rises with the incentive: 3.9 at -3 points, 8.9 at zero, 29.0 at +1 point |
| 3 | `ipw scenario -n prepay_fast -n prepay_slow` | Faster behaviour +67.3 on value, slower -74.5: the book trades below par, so earlier principal is worth more |

Result: [ ] Pass [ ] Fail. Notes:

### UAT-05 Limit monitoring with early warning (BR-5)

| Step | Action | Expected |
|---|---|---|
| 1 | `ipw limits` | Nine limits. AOCI_UP200 is BREACH: -225.99 against a floor of -210.00, 108% used. DUR_BAND is WARN at 84% used. The other seven are OK. Each row shows its policy reference |

Result: [ ] Pass [ ] Fail. Notes:

### UAT-06 Remediation options for a breach (BR-6)

| Step | Action | Expected |
|---|---|---|
| 1 | `ipw fix AOCI_UP200` | Three pay-fixed options: 2Y 570.0, 5Y 260.0, 10Y 150.0. Each brings the metric from -225.99 to -210 or better (-209.98, -209.40, -209.62), shows the cost to income (-1.5, -1.0, -0.9) and leaves no limit breached |
| 2 | `ipw fix NII_UP100` | Refused with a one-line message: the limit is not breached |
| 3 | `ipw fix HTM_SHARE --target 50` | Refused with a one-line message: this limit does not respond to swaps |

Result: [ ] Pass [ ] Fail. Notes:

### UAT-07 Hedge sizing to a target (BR-7)

| Step | Action | Expected |
|---|---|---|
| 1 | `ipw hedge -t 4.5` | One 5Y pay-fixed swap of 1,614.0; net duration 5.30 to 4.50. The 5Y key-rate exposure is almost removed; other points are unchanged |
| 2 | `ipw hedge -t 4.5 --mode krd --tenors 2,5,10` | Three swaps (318.2, 486.7, 555.8); net duration 5.30 to 4.50; the 2Y, 5Y and 10Y exposures fall by the same proportion |
| 3 | `ipw hedge -t 6.0` | A receive-fixed swap, because the target is longer than the book |

Result: [ ] Pass [ ] Fail. Notes:

### UAT-08 Before and after a proposed trade (BR-8)

| Step | Action | Expected |
|---|---|---|
| 1 | `ipw whatif --pay-fixed 5:260` | AOCI_UP200 moves from -225.99 to -209.40; net duration from 5.30 to 5.17; income from 103.64 to 102.61. In the limit table after the change, AOCI_UP200 is no longer BREACH and DUR_BAND is OK |
| 2 | `ipw limits` | Unchanged from UAT-05: the actual book was not altered |
| 3 | `ipw whatif --drop FN30-2.5-001` | Market value moves from 8,909.27 to 8,838.79, a change of -70.48, which is that position's value; limits are re-evaluated |

Result: [ ] Pass [ ] Fail. Notes:

### UAT-09 Explanation of the change since the prior close (BR-9)

| Step | Action | Expected |
|---|---|---|
| 1 | `ipw explain` | Total change -38.80. Drivers: curve first order -29.29, curve remainder -0.24, mortgage rate basis +0.22, MBS spreads -9.49. They add up to the total |
| 2 | Same output, key-rate table | Yields rose 3 to 8bp at every key rate; the first-order effect by key rate adds up to -29.29 |
| 3 | Same output | The remainder is under 1% of the curve effect, so the risk report described the day well |

Result: [ ] Pass [ ] Fail. Notes:

### UAT-10 Daily brief (BR-10, NFR-1)

| Step | Action | Expected |
|---|---|---|
| 1 | `ipw brief` | A file `reports/brief_2026-11-09.md` with ten numbered sections and a method section |
| 2 | Read section 1 | Headline states value, risk, income, limit counts (7 OK, 1 WARN, 1 BREACH) and the change since the prior close |
| 3 | Read section 2 | Remediation options for AOCI_UP200 are listed under the limit table and marked as indicative |
| 4 | Rename the file, run `ipw brief` again, compare the two files | Identical |

Result: [ ] Pass [ ] Fail. Notes:

### UAT-11 Changing scenarios and limits without development (NFR-3)

| Step | Action | Expected |
|---|---|---|
| 1 | Add to the list in `config/scenarios.yaml`: `- {name: twist_test, description: "2y +50bp, 10y -25bp", curve_points_bp: {2: 50, 10: -25}}` and run `ipw scenario -n twist_test` | The new scenario runs and shows value, AOCI, income and duration |
| 2 | Change `curve_points_bp` to `curve_points` in that entry and run again | One-line error naming the file, the scenario and the unknown key |
| 3 | Correct the entry. Add to the list in `config/limits.yaml`: `- {id: TEST, name: Test limit, metric: aoci_after_tax, scenario: twist_test, unit: $mm, min: -50}` and run `ipw limits` | The new limit appears with value, utilisation and status |
| 4 | Remove the additions | `ipw limits` matches UAT-05 again |

Result: [ ] Pass [ ] Fail. Notes:

### UAT-12 Reproducibility and controlled change (NFR-1, NFR-7)

| Step | Action | Expected |
|---|---|---|
| 1 | `pytest` | All tests pass |
| 2 | In `config/model.yaml` change `turnover_cpr_pct` from 6.5 to 7.0 and run `pytest` | The regression test fails and lists the results that moved; the specification check fails because the documented value no longer matches |
| 3 | Restore 6.5 and run `pytest` | All tests pass |

Result: [ ] Pass [ ] Fail. Notes:

### UAT-13 Output for people and for programs (NFR-8)

| Step | Action | Expected |
|---|---|---|
| 1 | `ipw -f md summary` | A Markdown table that can be pasted into a document |
| 2 | `ipw -f json limits` | Valid JSON with one record per limit |
| 3 | `ipw position NOPE` | One line: `Error: unknown position_id 'NOPE'`; no stack trace |

Result: [ ] Pass [ ] Fail. Notes:

## Coverage

| Requirement | Cases |
|---|---|
| BR-1 | UAT-01 |
| BR-2 | UAT-02 |
| BR-3 | UAT-03 |
| BR-4 | UAT-04 |
| BR-5 | UAT-05 |
| BR-6 | UAT-06 |
| BR-7 | UAT-07 |
| BR-8 | UAT-08 |
| BR-9 | UAT-09 |
| BR-10 | UAT-10 |
| NFR-1, NFR-7 | UAT-10, UAT-12 |
| NFR-3 | UAT-11 |
| NFR-8 | UAT-13 |
| NFR-2, NFR-4, NFR-5, NFR-6 | Covered by automated tests and inspection; see the functional specification |

## Sign-off

| Role | Name | Date | Result |
|---|---|---|---|
| Portfolio manager | | | |
| Portfolio analyst | | | |
| Market risk oversight | | | |
| Product owner | | | |
