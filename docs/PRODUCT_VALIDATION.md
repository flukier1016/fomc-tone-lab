# Product validation: who it serves and what is not yet shown

The research results answer whether tone can be measured and whether it relates to Treasury yields. They do not show
that the dashboard helps anyone do a job faster or better. No user study has been run; this page states the intended
users and tasks, the evidence that exists, and a small study ready to run. Nothing below is a measured user outcome.

## Intended users and tasks

| User | Task | Done correctly when |
|---|---|---|
| A rates analyst or portfolio manager | T1. After a Fed release, see whether it reads more hawkish or dovish than that type's history, and check the wording behind the reading | States the percentile and direction for the right document type and opens at least one quoted evidence span that supports it |
| The same user | T2. Decide whether tone is a tradable signal for a delayed duration tilt | Finds the pre-registered result (Sharpe about -0.18, placebo p = 0.28) and concludes there is no reliable delayed edge, rather than picking a positive exploratory variant |
| The same user | T3. Turn one document's frozen rule into a duration change and dollar risk for their own portfolio | Enters capital, duration and budget, reads the DV01 change and round-trip cost, and can say why the one-document rule differs from the historical backtest |
| A course reviewer | T4. Reproduce the reported numbers from the submitted files | Runs `make setup`, `make test`, `make demo-data` and `make serve` from the code ZIP and sees the same H1 to H4 figures as the slides |

Out of scope: intraday trading, live order placement, scoring new text on the public site (it is read-only), and
any claim that the tone index predicts returns.

## Evidence that exists

| Evidence | What it shows | What it cannot show |
|---|---|---|
| 132 offline tests (developer-written regression suite) | Coded rules hold: timing without look-ahead, sizing identities, search syntax, public read-only mode | That users complete T1 to T4 |
| Headless interaction checks (`scripts/check_duration_ui.py`, `make review`) | Pages load at four widths, the Duration flow behaves under edits, failures and races | Comprehension or speed |
| Frozen research results (H1 to H4) | Measurement quality on public expert labels; release-window associations; no delayed trading edge | Usefulness of the interface |
| Live checks of the deployed site | The deployed revision matches the code and serves the frozen results in read-only mode | User value |

## A small study, ready to run (not yet run)

Five participants who read Fed communication (classmates in the course or desk colleagues), one session of about
20 minutes each, on the public site. Give each task card below in turn, without help, and record the table.

Task cards:

1. "The latest FOMC minutes came out. Is their tone unusual compared with past minutes? Show the sentence that
   supports your answer."
2. "Should a desk tilt duration on the day after hawkish Fed documents? Use the site to decide."
3. "Your bond portfolio is USD 50 million with a duration of 6 years and a 1-year budget. What would the most recent
   speech's rule do to your dollar DV01, and what would it cost?"
4. (Reviewer) "Starting from the code ZIP, reproduce H1's macro-F1 figures."

Record for each participant and task:

| Field | Meaning |
|---|---|
| Completed correctly | Against the "done correctly" column above, judged by a second person |
| Minutes to first correct answer | From reading the card to a correct answer |
| Wrong turns | Pages visited that did not help, and answers given then corrected |
| Help requests | Times the participant asked how to do something |
| Misreadings | For example a model reading taken as a human label, a range taken as a confidence interval, or a stale date missed |
| Recovered after an error | Whether the participant got back on track without help |

Report completion rate, median time and the misreadings with their pages. Treat five participants as a check for
obvious problems, not as evidence of value in general. Fix what the misreadings point to and record the revision.

## Status

Not validated with users. The study above is a plan; it has not been run and no participant data exist.
