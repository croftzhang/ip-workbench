# Accounting Note: AFS and HTM Securities

**Investment Portfolio desk**

| | |
|---|---|
| Document | Accounting note on available-for-sale and held-to-maturity securities, version 1.0 |
| Cited as | ACCT and the section number, for example ACCT 3.2 |
| Role | Knowledge base of the assistant: embedded and retrieved |
| Status | Constructed for this repository, consistent with the engine's AOCI and income calculations |

> The desk and every figure in this document are illustrative. The note
> explains how the analytics treat the two classifications. It is not
> accounting advice.

## 1. Purpose

The same change in market value has a different effect on reported equity
depending on how a security is classified. This note explains the two
classifications the portfolio uses and what each means for the figures the
analytics report.

## 2. The two classifications

### 2.1 Available for sale

An available-for-sale (AFS) security is carried on the balance sheet at fair
value. Its unrealized gain or loss, the difference between fair value and
amortised cost, is not part of earnings. It is held in accumulated other
comprehensive income (AOCI), a component of equity.

### 2.2 Held to maturity

A held-to-maturity (HTM) security is carried at amortised cost. A change in
its market value changes neither earnings nor equity. The security is still
worth less when rates rise: the loss is an economic loss that the balance
sheet does not show.

## 3. AOCI

### 3.1 What enters

Only AFS securities enter AOCI. HTM securities never do. The analytics report
the change in HTM value next to the change in AOCI so that both are seen, and
never add the two.

### 3.2 After tax

AOCI is reported after tax. The analytics apply a tax rate of 24% to the
pre-tax change, so the after-tax change is 76% of the pre-tax change.

### 3.3 Net of hedges

The swaps designated as fair-value hedges of AFS securities offset part of the
change in AFS value. In a fair-value hedge the gain or loss on the swap and
the offsetting change on the hedged security are recognised in earnings, so
only the unhedged part of the change reaches AOCI. The AOCI sensitivity the
analytics report is the change in AFS value plus the change in the value of
those swaps, after tax.

## 4. Hedge accounting

Only AFS securities are hedged. An HTM security cannot be the hedged item in a
hedge of interest-rate risk. The analytics treat every designated hedge as
fully effective; hedge ineffectiveness and the mechanics of basis adjustments
are not modelled.

## 5. Interest income

Interest income on a security is recognised on an effective-yield basis that
takes expected prepayments into account. A security bought above par carries a
premium that is amortised against income over its life. When prepayments speed
up, the premium is amortised faster and income falls; when they slow, the
premium lasts longer.

The analytics show interest income as coupon income plus net premium
amortisation. They use the prospective effective yield and do not show the
one-time catch-up adjustment that is required when prepayment estimates
change. This understates the volatility of income at the time of a rate move.

## 6. Why two views of a rate shock are reported

| View | Covers | Answers |
|---|---|---|
| Economic value | AFS and HTM securities and all hedges | How much is the portfolio worth after the shock? |
| AOCI | AFS securities net of designated hedges, after tax | How much does reported equity change? |

A portfolio with a large HTM share shows a small AOCI sensitivity and a large
economic sensitivity. The Investment Policy Statement limits both, in sections
4.3 and 4.4, and caps the HTM share in section 3.2.

## 7. Standards the note relies on

| Topic | Standard |
|---|---|
| Classification of debt securities as AFS or HTM | FASB Accounting Standards Codification, Topic 320 |
| Fair-value hedges | FASB Accounting Standards Codification, Topic 815, paragraphs 815-25-35-1 to 35-6 |
| Effective-yield income with expected prepayments | FASB Accounting Standards Codification, Subtopic 310-20, paragraph 310-20-35-26 |

The standards themselves are not in the knowledge base.
