# Evaluation, Release 2: the Assistant

**Investment Portfolio Risk Analytics**

| | |
|---|---|
| Document | Evaluation record for release 2, version 1.0 |
| Status | One run on the reference machine, 2026-11-10, with `ipw-ai eval` |
| Owner | Product Owner, Investment Portfolio analytics |
| Last updated | 2026-11-10 |
| Traces to | [AGENT_DESIGN.md](AGENT_DESIGN.md): AD-8, which defines every measure. [PRD.md](PRD.md): US-11 and US-16 |
| Role of this document | A record of measurements. A reference only: the assistant does not retrieve it |
| Data of the run | `docs/examples/evaluation_2026-11-10.json`: every answer, draft and tool call. A reference only |

> The desk and all figures are illustrative.

This document reports what the assistant does on fixed sets of questions. The
measures are taken by code, not by a judging model, and the run is reported as
measured, with every task that was answered wrongly. The tasks are in
`evals/benchmark/tasks.yaml` and the retrieval questions in
`evals/retrieval.yaml`. Section codes such as IPS 5.4 refer to the documents of
the knowledge base, which the assistant embeds and retrieves.

## 1. Findings

1. **No invented figure.** No answer of the run was blocked. Every figure
   shown passed the check: it stands in a tool result, in a cited passage or in
   the question.
2. **A verified figure is not a correct answer.** 18 of 30 benchmark answers
   are correct. The 12 wrong ones passed the check: they give real figures for
   the wrong group, the wrong row or the wrong quantity.
3. **Routine questions: the plain command is the better tool.** Release 1
   answers all ten with one command in 0.02 seconds. The assistant answers
   seven of ten, in 3.8 seconds.
4. **Questions about the documents: the assistant adds what release 1 lacks.**
   Seven of ten are answered correctly with a citation. Retrieval returns a
   reference section for 29 of 30 questions, and all ten questions outside the
   knowledge base are refused.
5. **Composed analysis is not dependable with this model.** Four of ten.
6. **The investigation playbook runs to its end.** All six steps, the check
   passed on the first draft, 13.5 seconds. One statement in it is wrong.
7. **The most frequent mistake is a tool argument, not arithmetic.** In five of
   the fifteen wrong answers the model asked for the wrong grouping.

## 2. The run

|  |  |
|---|---|
| Date | 2026-11-10T22:53-05:00 |
| Market date | 2026-11-09 |
| Machine | Windows-11-10.0.26200-SP0; AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD |
| GPU | NVIDIA GeForce RTX 3060, 12288 MiB |
| Python | 3.14.2 |
| Chat model | qwen3:8b; temperature 0, seed 42, context 16384 tokens, replies up to 2048 tokens, reasoning off (8.2B, Q4_K_M, digest 500a1f067a9f, 100% in GPU memory) |
| Embedding model | nomic-embed-text (137M, F16, digest 0a109f422b47, 100% in GPU memory) |
| Retrieval | 4 passages from 20 candidates; refuse below 0.6; keyword fusion off; reranking off |
| Tool-call budget | 8 |
| Packages | langgraph 1.2.20, langchain-core 1.7.7, langchain-ollama 1.1.0, langchain-chroma 1.1.0, chromadb 1.5.9, ollama 0.6.3 |
| Sets | 30 retrieval questions and 10 outside the knowledge base; 40 tasks, 30 of them the benchmark |

The 51 runs of the assistant took 3.8 minutes together: ten questions outside
the knowledge base, forty tasks and one investigation. Temperature 0 and a
fixed seed make the same question give the same reply on this machine.

## 3. Measures

| Measure | Result | Set |
|---|---|---|
| Retrieval hit rate at 4 | 96.7% (29 of 30) | 30 questions with reference sections; target at least 85% |
| Refusal correctness, the assistant | 100.0% (10 of 10) | 10 questions outside the knowledge base, asked of the assistant |
| Refusal correctness, the threshold alone | 30.0% (3 of 10) | The same questions: refused by the similarity threshold, before the model is asked |
| Tool-selection accuracy | 80.0% (16 of 20) | 20 routine tasks |
| First-draft pass rate | 76.7% (23 of 30) | 30 benchmark tasks |
| Block rate | 0.0% (0 of 30) | 30 benchmark tasks |
| Answer correctness | 60.0% (18 of 30) | 30 benchmark tasks |
| Time to answer | median 3.9 s; 90th percentile 9.2 s | 30 benchmark tasks |

Targets. The roadmap sets two: a retrieval hit rate of at least 85%, which is
met, and no unverified figure shown, which holds by construction because an
answer is shown only after it passed the check. The other measures have no
target; they describe how the assistant behaves.

US-11 asks for retrieval hit rate, numeric faithfulness and tool-selection
accuracy. Numeric faithfulness is reported as two measures: the first-draft
pass rate, which says how often the model's first draft held only verified
figures, and the block rate, which says how often no verified answer could be
shown.

## 4. Retrieval

| Method | Hit rate at 4 | Refused by the threshold, outside the knowledge base |
|---|---|---|
| Vector search (the setting in use) | 96.7% (29 of 30) | 3 of 10 |
| With keyword fusion | 93.3% (28 of 30) | 3 of 10 |
| With fusion and reranking | not installed | not installed |

Vector search alone finds a reference section for 29 of 30 questions. Adding
keyword fusion finds one fewer, so it does not earn its place. Reranking is
not measured: the optional extra is not installed on the reference machine.

The one miss of vector search:

| Id | Question | Reference sections | Sections returned |
|---|---|---|---|
| R08 | Which kinds of securities is the desk allowed to buy? | IPS 3.1 | ACCT Accounting Note: AFS and HTM Securities, IPS 3.2, IPS 3.3, ACCT 2.1 |

Best similarity of a question to a passage, with vector search:

| Questions | Lowest | Median | Highest |
|---|---|---|---|
| With an answer in the knowledge base | 0.636 | 0.771 | 0.846 |
| Outside the knowledge base | 0.510 | 0.639 | 0.720 |

The two groups overlap, so no threshold separates them. The threshold in use,
0.60, lies below every answerable question; alone it refuses three of the ten
questions outside the knowledge base, and the model refuses the other seven
when it reads the passages. The threshold that separates the two groups best,
0.681, would refuse nine of the ten and with them two answerable questions,
R26 and R27.

The ten questions outside the knowledge base, asked of the assistant:

| Id | Question | Best similarity | Passages given | The assistant |
|---|---|---|---|---|
| N01 | What is the bank's common equity tier 1 capital ratio? | 0.624 | 4 | refused |
| N02 | Who is the chief executive of the bank? | 0.510 | 0 | refused |
| N03 | How is value-at-risk calculated for the trading book? | 0.681 | 4 | refused |
| N04 | What liquidity coverage ratio must the bank maintain? | 0.662 | 4 | refused |
| N05 | What is the allowance for credit losses on commercial real estate loans? | 0.655 | 4 | refused |
| N06 | Which dealers does the desk execute its swaps with? | 0.615 | 4 | refused |
| N07 | What dividend will the bank pay next quarter? | 0.663 | 4 | refused |
| N08 | What is the weather forecast for New York tomorrow? | 0.575 | 0 | refused |
| N09 | How do I reset my Windows password? | 0.526 | 0 | refused |
| N10 | What is the interest-rate risk of the bank's commercial loan book? | 0.720 | 4 | refused |

## 5. Release 1 against release 2

| Class | Tasks | Release 1: one command | Release 1: commands and work by hand | Release 1: cannot | Release 2 correct | Release 2 blocked | First draft passed | Seconds, release 2 (median) | Seconds, release 1 commands (median) |
|---|---|---|---|---|---|---|---|---|---|
| routine | 10 | 10 | 0 | 0 | 70.0% (7 of 10) | 0 | 9 | 3.8 | 0.02 |
| composed | 10 | 0 | 10 | 0 | 40.0% (4 of 10) | 0 | 4 | 7.8 | 0.04 |
| documents | 10 | 0 | 0 | 10 | 70.0% (7 of 10) | 0 | 10 | 3.3 | - |
| all | 30 | 10 | 10 | 10 | 60.0% (18 of 30) | 0 | 23 | 3.9 | 0.03 |

Release 1 answers a task when its commands show the figures of the answer. Its
seconds are those of the commands, run in the same process with the book
loaded; typing a command, starting the program and work by hand are not timed.
The seconds of release 2 run from the question to the checked answer, with the
models loaded.

| Class | Reading |
|---|---|
| Routine | Release 1 is faster by two orders of magnitude and is always right. The assistant saves knowing the command and its options, and gets three of ten wrong |
| Composed | Release 1 needs several commands and arithmetic or copying by hand. The assistant does it in one question when it succeeds, which is four times in ten |
| Documents | Release 1 cannot answer. The assistant answers seven of ten with the section cited; two of the three wrong answers leave out the figure that the question also asks for |

## 6. What the check did

* No answer was blocked: 0 of 30 benchmark tasks, and none of the other runs.
* 23 of 30 first drafts passed. Each of the seven that failed held a figure that
  is in no tool result, in most cases the model's own arithmetic.
* After the one further attempt, three of the seven are correct, each through
  the `aggregate` tool: C01, C05 and C09.
* Two give a figure from `aggregate` that is verified and wrong. In T08 the
  first draft held the shares 42.0% and 58.0%, which are right for AFS and HTM;
  the check rejected them as the model's own arithmetic, and the model then
  asked `aggregate` for the total over each part, 238.14% and 172.39%. In C03
  it asked for income after the shock over base income, not for the change.
* Two end without the figure: C02 and C07.
* The model made 48 tool calls in the forty tasks. 5 returned an error, such as
  an invalid argument or a cell that does not exist; in three of the four tasks
  concerned the model corrected the call.

The check verifies where a figure comes from. It does not verify that the
figure answers the question. Answer correctness measures that, and section 8
lists what went wrong.

## 7. Tasks

| Task | Class | Benchmark | Question | Release 1 | Release 2 | Check | Tool calls | Seconds |
|---|---|---|---|---|---|---|---|---|
| T01 | routine | yes | What is the net effective duration of the book? | one command | correct | passed on draft 1 | reference | 2.9 |
| T02 | routine | yes | What are the total market value and the total unrealized gain or loss of the securities? | one command | correct | passed on draft 1 | reference | 3.5 |
| T03 | routine | yes | What is the market value of the AFS securities and of the HTM securities? | one command | incorrect | passed on draft 1 | other | 3.8 |
| T04 | routine | yes | At which key rate is the net key-rate duration largest, and how large is it there? | one command | incorrect | passed on draft 1 | reference | 3.3 |
| T05 | routine | yes | Which five positions have the largest DV01? | one command | correct | passed on draft 1 | reference | 6.0 |
| T06 | routine | yes | For position FN30-2.5-001, what are the market value, the effective duration and the projected one-year CPR? | one command | correct | passed on draft 1 | reference | 3.8 |
| T07 | routine | yes | By how many USD millions does the value of the securities change if rates rise by 200bp? | one command | correct | passed on draft 1 | reference | 3.1 |
| T08 | routine | yes | Under the +200bp scenario, what share of the loss in value does each asset type carry? | one command | incorrect | passed on draft 2 | other | 11.4 |
| T09 | routine | yes | What is net interest income over the next 12 months in the base case and under +100bp? | one command | correct | passed on draft 1 | reference | 3.9 |
| T10 | routine | yes | Which policy limits are breached or in warning today? | one command | correct | passed on draft 1 | reference | 3.9 |
| T11 | routine | no | What is the projected one-year CPR of the 30-year high-coupon bucket today, and if rates fall by 100bp? | one command | incorrect | passed on draft 1 | other | 3.8 |
| T12 | routine | no | Why did market value change since the prior close? Give the total change and the parts due to the first-order curve effect and to MBS spreads. | one command | correct | passed on draft 1 | reference | 4.0 |
| T13 | routine | no | Which swap notionals would bring the AOCI_UP200 limit back to its bound with a 2-year, a 5-year or a 10-year swap? | one command | correct | passed on draft 1 | reference | 6.2 |
| T14 | routine | no | Size a 5-year pay-fixed swap that brings net duration to 4.5 years. | one command | correct | passed on draft 1 | reference | 4.7 |
| T15 | routine | no | What would net duration be after selling position FN30-2.5-001? | one command | correct | passed on draft 1 | reference | 3.8 |
| T16 | routine | no | What is the effective duration of the 30-year MBS and of the 15-year MBS? | one command | incorrect | passed on draft 1 | other | 3.3 |
| T17 | routine | no | What is the net key-rate DV01 at the 10-year point, in USD thousands per basis point? | one command | correct | passed on draft 1 | reference | 3.4 |
| T18 | routine | no | Which three positions have the largest unrealized losses, and how large is the largest one? | one command | incorrect | passed on draft 1 | reference | 4.0 |
| T19 | routine | no | What is the change in AOCI under the bear_steepener scenario? | one command | correct | passed on draft 1 | reference | 3.6 |
| T20 | routine | no | How is the market value of the securities split by agency? | one command | correct | passed on draft 1 | reference | 4.2 |
| C01 | composed | yes | Under the +200bp scenario, how much more value do the HTM securities lose than the AFS securities? | commands and work by hand | correct | passed on draft 2 | - | 8.0 |
| C02 | composed | yes | What share of the market value of the securities is in 30-year MBS? | commands and work by hand | incorrect | passed on draft 2 | - | 6.0 |
| C03 | composed | yes | How large is the +100bp change in 12-month net interest income as a percentage of base-case net interest income? | commands and work by hand | incorrect | passed on draft 2 | - | 9.0 |
| C04 | composed | yes | By how much is the AOCI_UP200 limit outside its bound, and what notional of a 5-year pay-fixed swap would bring it back? | commands and work by hand | correct | passed on draft 1 | - | 4.6 |
| C05 | composed | yes | What is the combined DV01 of the three positions with the largest DV01? | commands and work by hand | correct | passed on draft 2 | - | 7.6 |
| C06 | composed | yes | If the three positions with the largest unrealized losses were sold, what would net duration be, and what would the AOCI_UP200 measure be? | commands and work by hand | incorrect | passed on draft 1 | - | 8.9 |
| C07 | composed | yes | Size a 10-year pay-fixed swap that brings net duration to 5.0 years, then show what adding that swap does to 12-month NII and to the AOCI_UP200 measure. | commands and work by hand | incorrect | passed on draft 2 | - | 11.4 |
| C08 | composed | yes | How much longer is the effective duration of the HTM securities than that of the AFS securities? | commands and work by hand | incorrect | passed on draft 1 | - | 3.5 |
| C09 | composed | yes | Since the prior close, how much of the first-order curve P&L came from the 10-year and the 20-year key rates together? | commands and work by hand | correct | passed on draft 2 | - | 11.5 |
| C10 | composed | yes | Which bucket loses the most value under the bear_steepener scenario, and what are that bucket's effective duration and DV01? | commands and work by hand | incorrect | passed on draft 1 | - | 5.3 |
| D01 | documents | yes | What is the policy limit on the after-tax AOCI loss when rates rise by 200bp, and which securities does the measure cover? | no | correct | passed on draft 1 | - | 3.1 |
| D02 | documents | yes | What has to happen on the day a limit is breached? | no | correct | passed on draft 1 | - | 3.0 |
| D03 | documents | yes | At what utilisation does a limit go into warning, and which limits are in warning today? | no | correct | passed on draft 1 | - | 4.5 |
| D04 | documents | yes | Can held-to-maturity securities be hedged with swaps, and why? | no | correct | passed on draft 1 | - | 3.5 |
| D05 | documents | yes | What tax rate do the analytics apply to AOCI, and what is the after-tax change in AOCI under the +200bp scenario? | no | incorrect | passed on draft 1 | - | 3.7 |
| D06 | documents | yes | When a limit is breached, how is the restoring swap sized, and in what notional steps? | no | correct | passed on draft 1 | - | 3.9 |
| D07 | documents | yes | Do the swaps hedge a widening of MBS spreads, and what does the basis_widen_25 scenario do to the value of the securities? | no | incorrect | passed on draft 1 | - | 2.7 |
| D08 | documents | yes | What is the model not intended to be used for? | no | correct | passed on draft 1 | - | 2.6 |
| D09 | documents | yes | Why do mortgage securities get longer when rates rise? | no | correct | passed on draft 1 | - | 3.1 |
| D10 | documents | yes | The AOCI_UP200 limit is breached. What does the policy allow as a remedy, and what notional of a 5-year swap would restore the limit? | no | incorrect | passed on draft 1 | - | 5.7 |

Tool calls are compared with the reference for routine tasks only. Fourteen of
the twenty routine tasks are answered correctly, and seven of the ten that
belong to the benchmark.

## 8. Why answers were wrong

Fifteen of the forty answers are scored incorrect: twelve benchmark tasks and
three further routine tasks.

| Cause | Tasks | What the answer did |
|---|---|---|
| The wrong grouping was asked for | T03 | Grouped by asset type for a question about AFS and HTM, and gave the total, 8,909.3, as the AFS value |
| | C02 | Grouped by year of origination, then said the tool does not break the book down by mortgage type |
| | C08 | Grouped by asset type; gave the Securities row (6.01) and the Net row (5.30) as HTM and AFS, and the Hedges row (0.71) as their difference |
| | T11 | Grouped by coupon; gave the 4.5% coupon row (4.4% and 5.9%) as the 30-year high-coupon bucket |
| | T16 | Grouped by year of origination; gave the rows of 2019 and 2023 (7.08 and 6.17) as 30-year and 15-year MBS |
| The right table, the wrong row | T04 | Named the 10-year key rate (1.83); the largest is the 20-year (1.95) |
| | C10 | Named the 30Y high bucket (-69.7); the largest loss is in 30Y low (-100.6) |
| `aggregate` asked for the wrong quantity | T08 | The total over each part, and by designation where the question asks by asset type |
| | C03 | Income after the shock over base income, 79.68%; the change over base income is -20.32% |
| A call not made, or made with invented arguments | C06 | Added two swaps that nobody asked for to the what-if, so both figures are those of another trade |
| | C07 | Sized the swap and did not run the what-if; the answer says the two effects are not available |
| Two-part question: the document part answered, no tool called for the figure | D05 | Gave the limit, USD 210 million, in place of the change in AOCI |
| | D07 | Gave no figure, and described the scenario as a rise in the value of mortgage securities |
| The section was not retrieved | D10 | IPS 5.4 was not among the four passages; the answer names one remedy and cites nothing |
| The reference, not the answer | T18 | The answer is right. The reference asked for the position id in the same sentence as the figure |

T18 is reported as measured. Its reference now also accepts the figure where
it is called the largest loss. Scored again from the data file with that
reference, T18 is correct and no other task changes. T18 is not one of the
thirty benchmark tasks, so no measure moves.

Read in this way, five wrong answers come from one tool argument. The
description of that argument tells the model that it groups the rows and lists
the names of the groupings; it does not say what the rows of each grouping are,
for example that the designation is AFS or HTM.

## 9. Investigation

| | AOCI_UP200 |
|---|---|
| Playbook steps done | 6 of 6 |
| Check | Passed on the first draft |
| Headroom, a sized option and the policy section in the answer | Yes: -15.99; 260, 150 and 90 for swaps of 5, 10 and 30 years; IPS 4.3 |
| Seconds | 13.5 |

Read against the tool results, the figures of the answer are right. One
statement is not: the answer names 30Y low and 30Y mid as the buckets that
carry the exposure, and the breakdown shows 30Y low (37.8% of the change in
value) and 30Y high (26.2%) ahead of 30Y mid (14.6%). The statement carries no
figure, so the check has nothing to compare. The model asked for swaps of 5, 10
and 30 years, not the policy's default of 2, 5 and 10.

## 10. Defaults confirmed by this run

| Setting in `config/agent.yaml` | Value | Evidence |
|---|---|---|
| Chat model | `qwen3:8b`, unchanged | The one model measured. Another model is compared by changing this setting and running the same command |
| Retrieval | Vector search; keyword fusion off; reranking off | Section 4: fusion finds 28 of 30 against 29 of 30; reranking is not measured |
| Refusal threshold | 0.60, unchanged | Section 4: no answerable question lies below it, and the assistant refuses all ten questions outside the knowledge base |
| Context length | 16,384 tokens, unchanged | A prompt of this run holds about 4,100 tokens on average |
| Tool-call budget | 8, unchanged | No run made more than six tool calls |

## 11. What the results point to

These are candidates, not decisions. Each is measured by the same command.

1. **Say what each grouping is.** Add to the description of the grouping
   argument what its rows are. Five of the fifteen wrong answers have this
   cause.
2. **Questions in two parts and chained what-ifs.** D05, D07, C06 and C07 need
   a second step that the model did not take, or took with arguments of its
   own. A planning step is the deferred item of the design that addresses it; a
   larger model is the other candidate.
3. **Shares and differences.** Where a tool already reports a share, as the
   scenario breakdown does, the model should be led to it, and the result of
   `aggregate` should say what was divided by what, so that a ratio taken the
   wrong way round is visible.

A change made after reading these answers and measured on the same thirty
tasks will look better than it is. Such a result is to be reported next to this
one, not in place of it.

## 12. Limits of this evaluation

* **One run.** One model, one machine, one market date.
* **Small sets.** One task is 3.3 percentage points of answer correctness.
* **Tasks written for this repository.** The questions, the accepted tool calls
  and the references come from the same hand as the tools.
* **Scoring by presence.** An answer is correct when it holds every reference
  pair; a wrong statement next to them is not seen. D03 is scored correct and
  names HTM_SHARE as a limit in warning, which it is not: its utilisation is
  75% and its status is OK. Read strictly, 17 of 30 benchmark answers are
  right. T18, in section 8, is the opposite case.
* **Refusal.** Ten questions, all answered with the one fixed sentence.
* **Time.** The seconds of release 1 leave out starting the program and the
  work by hand.

## 13. Running it again

`ipw-ai eval` runs the same evaluation and writes the report and its data file
to `reports/`. `ipw-ai eval --mock` runs it without models, on the mock model,
and says nothing about the quality of a real model.
