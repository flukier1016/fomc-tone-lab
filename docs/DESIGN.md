# Research design

## 1. Question

Does a large language model's reading of Federal Reserve communication carry information about Treasury yields that simpler text measures and the policy decision itself do not, and can that information be traded once realistic timing is respected?

The brief for this project (IEOR 4723 final project, topic 4: central bank communication index and duration positioning; mapped line by line in [ASSIGNMENT.md](ASSIGNMENT.md)) already names the hard part: the market reprices a statement within minutes, so any tradable edge has to come from documents the market digests more slowly (minutes, speeches) or from the change in tone between consecutive documents.

## 2. Hypotheses

| | Hypothesis | Test | Falsified if |
|---|---|---|---|
| H1 | Measurement: Claude's rubric labels hawkish, dovish and neutral sentences closer to human annotators than dictionary, TF-IDF and sentence-embedding baselines. | Macro-F1 and Cohen's kappa on the 496-sentence public expert-labeled Trillion Dollar Words test split. A human check on 150 post-cutoff sentences was planned but not run; the saved Claude predictions are model labels. | The originally planned criterion was failure to beat the supervised baseline on the post-cutoff human labels; that criterion remains untested. |
| H2 | Information: tone level and tone shift explain the Treasury move over each release window, beyond the policy decision. | OLS of the 3m, 2y, 5y, 10y and 30y changes and the 2s10s slope on standardized tone, by document type (speeches also split into the Chair's and other members'), HC1 errors; robustness with the 3-month bill as a surprise control, the announced rate change as a control, and the 2009-2019 and 2020+ samples separately; Benjamini-Hochberg q-values across the main grid. | No main-grid test has q below 0.10, the day-before placebo is as strong as the release window, or the effect flips sign between samples. |
| H3 | Tradability, **pre-registered**: a duration tilt on Claude level scores of minutes and Board speeches, entered at the close of the trading day after release and held 5 trading days, earns a positive Sharpe after costs that beats a shuffled-score placebo. The tilt is sized so a full signal moves an aggregate-bond (AGG) or Treasury (IEI) portfolio by one year of duration. | `fomc backtest --placebo`; primary row flagged `is_primary`; its probabilistic Sharpe ratio (PSR). | Primary Sharpe is not above the 95th percentile of the placebo, its PSR is below 0.95, or its sign flips between development and holdout. |
| H4 | Contamination: the scores do not depend on recognising the document. | Masked identification accuracy; correlation of masked and raw scores; results restricted to documents after the model's knowledge cutoff. | Masked scores diverge from raw scores, or the H2/H3 results vanish after the cutoff. |

Everything other than the H3 primary specification is exploratory and reported in full (116 backtest variants across the four readers, level and shift signals, holding periods and entries), so the reader can see how many specifications were tried. Exploratory results are read after correcting for that search: q-values in the event study, the deflated Sharpe ratio in the backtest.

## 3. Sample

| Document type | Source | Count | Release time |
|---|---|---|---|
| Statements, 2009 to Sep 2026 | FOMC calendar and historical pages | 149 (143 policy decisions) | From the document ("For release at 2:00 p.m."), else 2:15 p.m. before 2013 |
| Minutes, 2009 to Sep 2026 meetings | same | 142 | 2:00 p.m. on the release date printed on the calendar |
| Press conferences, Apr 2011 onward | transcript PDFs, the Chair's words only | 95 | Information starts 2:30 p.m., complete 3:30 p.m. |
| Board speeches, 2009 onward | Fed speech feed (JSON) | 1,123 | Timestamp in the feed (Eastern) |

Markets: Treasury yields from FRED (DGS3MO, DGS2, DGS5, DGS10, DGS30), with the U.S. Treasury daily par yield curve that FRED republishes as an automatic fallback (quotes near 3:30 p.m. ET; the store records which source was used), for the event study; total-return closes of SHY, IEI, IEF, TLT and AGG (4:00 p.m. ET) for the backtest.

Splits: development 2009 to 2019; holdout January 2020 to June 2026; post-cutoff July 2026 onward (after the knowledge cutoff of the default scoring model, Claude Opus 5.5).

## 4. Timing: the no-look-ahead rules

A document can only move prices observed at a close **strictly after** the moment it became public.

- **Event window (Treasury closes):** from the last close strictly before the first information leaves the Fed to the first close strictly after the full document is public. A 2:00 p.m. statement gets a one-day window; a press conference straddles the 3:30 p.m. fix and gets two days; a speech at 7 p.m. belongs to the next day.
- **Trade entry (ETF closes):** the first 4:00 p.m. close strictly after the document is public (the aggressive variant), or one trading day later (the conservative variant used in the primary test).
- **Signal standardization:** each score is z-scored against the mean and standard deviation of *earlier* documents of the same type only.

These rules are unit-tested (`tests/test_timing.py`), including the test that changing the last document's score leaves every earlier signal unchanged.

## 5. Measurement

| Method | What it is | Why it is here |
|---|---|---|
| Dictionary | Economic nouns near direction words, signed by policy implication (Apel and Grimaldi style, our own word list) | Transparent floor; the classic approach |
| Supervised | TF-IDF unigrams and bigrams, logistic regression trained on the Trillion Dollar Words train split | A strong, cheap learned baseline |
| Fine-tuned RoBERTa (reference, added after the results) | RoBERTa-large fine-tuned on the same train split under the TF-IDF baseline's rules (its five folds, macro-F1, class-balanced loss); nine settings searched, five seeds of the best averaged (`finetune.py`) | How far a transformer trained on the same labels gets; outside H1, the event study and the backtest |
| Sentence embeddings | all-MiniLM-L6-v2 sentence vectors (run locally through ONNX by fastembed), logistic regression on the same train split; a document scores the mean of P(hawkish) minus P(dovish) over its sentences | The sentence-level embedding baseline the brief asks for; it differs from TF-IDF only in how a sentence is represented |
| Claude level | The rubric in `src/fomc/llm/rubric.py`: six dimensions, a holistic stance, a continuous score, confidence and verbatim evidence | The method under test |
| Claude shift | The current statement compared with the previous one, with the changed passages quoted | Markets read statements against each other |
| Decision and redline | The target range and the move parsed from each statement (`policy.py`), and a word-level diff against the previous decision | The decision is the control for H2; the share of wording changed is a model-free measure of news (Acosta and Meade 2015) |

Design choices that matter for validity:

- **Minimal disclosure.** The scorer sees the document type and the cleaned text, never the date, the release time or the page header.
- **Only the Fed's words.** Press conferences keep the Chair's opening statement and answers; reporters' questions and the moderator are removed. Minutes drop the attendance list wherever it sits (it moved to the end in mid-2024 and would otherwise be a sixth of the text).
- **Evidence is verified.** Every quote must appear verbatim in the source (typography-insensitive check); the share verified is stored per document and shown in the dashboard. A score whose evidence does not exist is a red flag, not a data point.
- **Versioning.** Any change to a prompt or schema bumps `RUBRIC_VERSION`, which changes the record path, so results from different wordings are never mixed.
- **Stability.** An evenly spaced 10% of the documents (152, 38 of each type) was re-scored in a separate batch (`--run-tag r2`): the same overall stance on 94.7%, never more than one step apart, scores correlated at r = 0.996 (mean absolute difference 0.023).
- **Model.** Claude Opus 5.5 by default, adaptive thinking, effort `medium`, structured outputs. The team can switch to Sonnet 5.5 or Haiku 5.5 for cost; a model change starts a separate set of records.

**Members over time (descriptive, outside the hypotheses).** The Fed now page opens each member as a line of their speeches' tone (Claude's level score, low-relevance speeches left out as everywhere else). Where the line shifts is found by circular binary segmentation (Olshen et al. 2004) on the speeches in date order: in a stretch, the run that differs most from the rest, measured against the stretch's own spread, is kept when fewer than 1 in 100 of 499 shuffles of the same speeches show as large a gap; each new stretch is searched again, with at least five speeches in each and at most five stretches. On speeches drawn at random from the corpus, where nothing changed, the rule reports a shift for about one member in a hundred (simulated at 12 to 120 speeches). The view describes; it tests nothing in H1 to H4 and changes no reported number.

## 6. Contamination audit

The default model's training data includes past FOMC documents and the market reaction to them. Three checks, adapted from the HW2 GameStop audit:

1. **Identification.** Dates, names and rate levels are masked (`audit.anonymize`); the model is asked when the document was issued. Exact-month and same-year rates bound how recognisable the documents are. Content cues (a pandemic) can identify a document legitimately, so this check bounds the risk rather than proving memorization.
2. **Invariance.** The same documents are scored masked and unmasked. High agreement partly addresses reliance on the masked identifiers; it does not rule out recognition from the remaining language or contamination of the public labels.
3. **Clean sample.** Documents released after the knowledge cutoff cannot be remembered; their results are reported separately.

After the course the index keeps running, so one more check keeps it comparable over time: every month the same eight documents are scored again through that month's model and pipeline (`fomc drift`). A mean change above 0.10 or stance agreement below 75% (test-retest: 0.023 and 95%) flags a reader that moved; readings from before and after are then kept apart as separate experiments.

## 7. Evaluation

- **Validity:** accuracy, macro-F1 and Cohen's kappa on human labels; confusion matrices; Claude against each baseline on the same sentences with a paired bootstrap of the macro-F1 difference (2,000 resamples, 95% interval and two-sided p) and McNemar's exact test on accuracy.
- **Event study:** for each group (four document types, plus the Chair's and other members' speeches), method and regressor (level, shift): coefficient in bp per SD, t (HC1), p, R-squared, across the curve (3m, 2y, 5y, 10y, 30y, 2s10s). Diagnostics: the day-before placebo and the 5- and 20-day drift. Robustness for the 2y, 10y and slope: the 3-month bill over the same window as a control for the near-term rate surprise (it over-controls if tone itself moves near-term expectations), the announced change in the target range for statements and press conferences, and the development and holdout samples on their own. Multiple testing: Benjamini-Hochberg q-values across the main grid (all groups, methods, regressors and release-window outcomes). Response curves: the average cumulative 2-year move from 5 days before to 20 days after the window, by tercile of tone.
- **Backtest:** daily overlay returns of the duration spread (IEF minus SHY), positions capped at one unit and scaled so a full signal adds or removes one year of duration on an AGG or IEI portfolio (one unit is 1 / (7.1 − 1.9) of the portfolio in the spread), with active return and tracking error against each benchmark, 1 bp per side on both legs for every change in position; annualized return, volatility, Sharpe, maximum drawdown, hit rate per signal, Newey-West t, Sharpe by split, the shuffled-score placebo p-value, the probabilistic Sharpe ratio (confidence that the true Sharpe is above zero given skew and fat tails) and the deflated Sharpe ratio (the same against the Sharpe the best of N no-skill variants would show by luck, N = every variant run).

## 8. What we found (21 October 2026)

H1 supported on the public expert labels (macro-F1 0.661 against 0.578 for the best baseline; paired bootstrap 95% interval for the lead +0.03 to +0.14, p = 0.004; McNemar p = 0.005); H2 supported (26 of 198 main-grid tests below q = 0.10, 16 of them Claude's; Claude's press-conference shift keeps t = 3.57 with the TF-IDF tone as a control; the statement shift on the 5-year, t = 3.15, falls to 1.91 at meetings without a press conference and to 0.01 with the press conference's tone as a control); H3 not supported (Sharpe −0.18, placebo p = 0.28); H4 mixed (exact-month identification 99%, masked and raw scores r = 0.99). The numbers and where to see them: [ASSIGNMENT.md](ASSIGNMENT.md) and the README.

**H1 evidence boundary.** The post-cutoff human test was not run. The 150 sampled sentences have Claude predictions, not human labels, and no optional cross-model check has been completed. The public expert labels may be in the model's training data. Masked and raw document scores agree (r = 0.99), which partly addresses the memorization concern but cannot establish independent human validation on new text.

**One re-run of the pre-registered test, disclosed.** The trade was re-run once on 21 October 2026 after a code review found two departures from the written design: speeches whose feed timestamp falls within an hour of a close now move to the next close, as the design specified, and statements are compared decision with decision. Its Sharpe moved from −0.23 to −0.18; the verdict did not change. The same review also took speech subsets and second differences out of the false-discovery family (300 tests became 198) and stopped Claude's skipped low-relevance speeches from breaking the speech shift series (269 shifts became 553).

**An exploratory test, added after the results: the next decision.** Does Claude's reading add to what the market already prices about the next decision? Each of the 142 decisions since 2009 (cut, hold or hike) is modeled on the 3-month bill and 2-year over the policy rate at the last close before it, and on the tone of the latest minutes, the speeches of the previous 60 days and the previous statement (`evaluate/forecast.py`, `fomc forecast`). The market's lean alone explains 63% of the variation; adding tone raises that to 64% (F-test of the three tone terms p = 0.04, none significant alone). Forecasting each decision from 2017 with only earlier data, adding tone does not lower the error (0.153 against 0.149, p = 0.68 over 79 decisions). The next decision is in the 3-month bill before the Fed speaks. Because it was added after the results, it is reported as exploratory and charged to no hypothesis.

**A reference added after the results: a transformer trained on the same labels.** To ask how far supervised learning gets with the same 1,984 hand-labeled sentences the TF-IDF baseline learns from, RoBERTa was fine-tuned under that baseline's rules: the same five folds, macro-F1, a class-balanced loss. Nine settings were searched (RoBERTa-base at four learning rates, RoBERTa-large at three, then layer-wise learning-rate decay and batches of 32 on the best), each scored after every one of ten epochs; the best, RoBERTa-large at a learning rate of 2e-5 stopped at epoch 9 (cross-validated macro-F1 0.724), was refit with five seeds whose probabilities are averaged, and read the test split once. It reaches macro-F1 0.737 (single seeds 0.714 to 0.737) against Claude's 0.661: Claude trails by 0.076, 95% interval 0.030 to 0.122 (paired bootstrap, p < 0.001; McNemar p = 0.003). Given labels from the same pool as the test sentences, a trained transformer reads them better than a model with no task-specific training labels. Whether that comparison holds on later sentences with independent human labels remains untested. On whole documents the two readers largely agree (Pearson r = 0.77 for statements, 0.86 for minutes, 0.79 for press conferences, 0.70 for speeches), so the index does not hinge on the reader. Because it came after the results, H1, the event study and the backtest still compare Claude with the three baselines stated in advance.

**After the freeze: a forward test.** The results above were frozen on 21 October 2026. From then on `fomc forward` runs every evening on new data only, re-fitting nothing: the pre-registered trade through the backtest's own code, with returns counted from the first close after the freeze; and, for each document type, Claude's strongest 2-year release-day relationship that survived false-discovery control, written once with its coefficient and the in-sample mean and SD of its tone measure (`data/forward/rules.json`). Each later release gets a predicted 2-year move beside its actual one; a one-sided binomial test of the direction starts at ten releases, and no verdict before a year. Research › Forward test shows it.

## 9. Reading a null result

A null is informative here. If Claude's scores explain release-window moves but nothing is left to trade afterwards, the market is efficient at the horizon a daily backtest can see, which is the expected result for statements. The interesting outcomes are (a) whether the LLM measures tone better than the baselines (H1), (b) whether minutes and speeches, digested more slowly, leave drift (H3), and (c) whether any of it survives the cutoff (H4).

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Memorization inflates results | Masked identification, invariance, post-cutoff sample |
| Specification search | One pre-registered primary test; every variant reported; placebo distribution; q-values in the event study and deflated Sharpe ratios in the backtest |
| Small samples (149 statements) | Report n and confidence intervals; treat statement results as descriptive |
| Daily data hide intraday pricing | Release windows built from 3:30 p.m. fixes; conclusions stated at the daily horizon |
| Speech times are feed timestamps | Assumed Eastern; documents within an hour of a close get two-day windows |
| Cost or key limits | Free cost estimate first; batches at 50%; pilot of 8 documents before any full run |
| Website changes break collection | Raw pages cached; parsers keyed on URL patterns; tests on fixtures |

## 11. References

- Acosta, M. and E. Meade (2015). Hanging on every word: Semantic analysis of the FOMC's postmeeting statement. FEDS Notes, Board of Governors.
- Apel, M. and M. Grimaldi (2012). The information content of central bank minutes. Sveriges Riksbank Working Paper 261.
- Bailey, D. and M. Lopez de Prado (2012). The Sharpe ratio efficient frontier. Journal of Risk.
- Bailey, D. and M. Lopez de Prado (2014). The deflated Sharpe ratio: Correcting for selection bias, backtest overfitting and non-normality. Journal of Portfolio Management.
- Benjamini, Y. and Y. Hochberg (1995). Controlling the false discovery rate. Journal of the Royal Statistical Society B.
- Gurkaynak, R., B. Sack and E. Swanson (2005). Do actions speak louder than words? The response of asset prices to monetary policy actions and statements. International Journal of Central Banking.
- Hansen, A. L. and S. Kazinnik (2023). Can ChatGPT decipher Fedspeak? Working paper.
- Harvey, C., Y. Liu and H. Zhu (2016). ... and the cross-section of expected returns. Review of Financial Studies.
- Kuttner, K. (2001). Monetary policy surprises and interest rates: Evidence from the Fed funds futures market. Journal of Monetary Economics.
- Olshen, A., E. S. Venkatraman, R. Lucito and M. Wigler (2004). Circular binary segmentation for the analysis of array-based DNA copy number data. Biostatistics.
- Shah, A., S. Paturi and S. Chava (2023). Trillion Dollar Words: A new financial dataset, task and market analysis. ACL 2023.
