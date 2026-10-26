# FOMC Tone Lab

Central bank communication and Treasury duration positioning  
IEOR 4723, AI-Augmented Investment Management, Fall 2026  
Final Project Group 2: Genie Zhang, Hong-syuan Lin, Myron Pang, Weijun Situ  
Research frozen on 21 October 2026

## 1. Question and main findings

Can a language model measure Federal Reserve policy tone, and can a bond portfolio trade on it after release? A model can read language accurately even when the market has already absorbed its information.

FOMC Tone Lab collects statements, minutes, press-conference transcripts and Board speeches; scores them with a Claude rubric and three simpler readers; aligns releases with Treasury observations; and tests a duration overlay after costs. A public dashboard links readings to source evidence. The unified presentation reads the same store.

H1 compares labels with public expert annotations. H2 tests associations with release-window Treasury moves. H3 specifies a trade entering later. H4 examines recognition of historical documents.

| Hypothesis | Frozen result | Interpretation |
|---|---|---|
| H1: measurement | Claude macro-F1 0.661 versus 0.578 for the strongest stated baseline; paired-bootstrap p = 0.004 | Supported on public expert labels; an independent post-cutoff human test was not run. |
| H2: information | 26 of 198 main-grid tests have q < 0.10; 16 use Claude readings | Tone is associated with release-window yield changes. |
| H3: tradability | Primary Sharpe -0.18; shuffled-score placebo p = 0.28 | The pre-registered next-day duration trade does not beat chance. |
| H4: contamination | 99% exact-month identification of masked statements; masked/raw score correlation 0.99 | Recognition risk remains, although removing identifying details barely changes the readings. |

Only the H3 primary specification is pre-registered. The other analyses, robustness checks and strategy variants are exploratory. A fine-tuned RoBERTa reference, added after the original results, reaches macro-F1 0.737 and exceeds Claude on the same sentence test. Claude's advantage is relative to the three stated baselines, not every possible reader.

The practical finding is useful but limited: Claude supplies an auditable description of policy language without task-specific training labels supplied by the team. The daily data do not establish a profitable delayed trade or identify a causal effect of communication.

Source: [ASSIGNMENT.md](ASSIGNMENT.md), requirements table and hypotheses; [DESIGN.md](DESIGN.md), sections 2 and 8.

<!-- pagebreak -->

## 2. Data, release times and information sets

The frozen corpus contains 1,509 usable documents and approximately 4.48 million words from the Federal Reserve website: meeting calendars and historical pages, press-conference PDFs, and the speech feed and linked pages.

| Type | Documents | Release-time convention, Eastern |
|---|---:|---|
| Statements | 149 | Printed release time; otherwise 2:15 p.m. before 2013 and 2:00 p.m. thereafter |
| Minutes | 142 | 2:00 p.m. on the calendar's release date |
| Press conferences | 95 | First information at 2:30 p.m.; complete at 3:30 p.m. |
| Board speeches | 1,123 | Timestamp in the speech feed |

The sample begins in 2009, except for press conferences, which begin in April 2011. Of the statements, 143 announce policy decisions; the remainder are notices. The decision parser reads the target range and compares successive policy decisions. Cleaning removes headers, date lines and unrelated material. Minutes exclude attendance lists. Transcripts retain the Chair's opening statement and answers, excluding reporters' questions and the moderator. Speeches under 300 words are excluded.

Treasury yields cover the 3-month bill and 2-, 5-, 10- and 30-year maturities, plus the 2s10s slope. FRED is the intended source; the U.S. Treasury daily par curve provides the automatic fallback used in the frozen store. Treasury quotes are near 3:30 p.m. ETF backtests use Yahoo Finance dividend-adjusted closes for SHY, IEI, IEF, TLT and AGG at 4:00 p.m.

Timing defines what the tests can mean. An event window starts with the last yield observation strictly before the first information is public and ends with the first observation strictly after the complete document is available. A statement released at 2:00 p.m. can enter that afternoon's window. A press conference straddles the Treasury fix and therefore requires a longer window. An evening speech moves to the next available close. Speech-feed timestamps within one hour of a close receive a conservative later window.

Trading uses ETF closes after release, and the primary strategy delays entry by one additional trading day. Its returns start after entry. Standardization uses only earlier documents of the same type, so later scores cannot change an earlier position.

The development period is 2009-2019, the holdout is January 2020-June 2026, and the configured post-cutoff period starts on 1 July 2026. The model cutoff is an assumption recorded in settings. The 34 post-cutoff documents available in the frozen sample provide a small additional check, not conclusive evidence of generalization.

Source: [DATA.md](DATA.md), counts, release conventions and cleaning; [DESIGN.md](DESIGN.md), sections 3-4; `align.py` and `tests/test_timing.py`.

<!-- pagebreak -->

## 3. Measuring tone and testing H1

Claude Opus 5.5 follows rubric v1 and returns structured JSON. Six dimensions describe policy action, forward guidance, inflation, activity and labor, the balance of risks, and the balance sheet. Each dimension runs from -2 to +2 or is null when absent. The overall stance is a holistic judgment, not an arithmetic mean. Its continuous score runs from -1, dovish, to +1, hawkish. Confidence and policy relevance are separate. Low-relevance speeches remain searchable but do not enter the market tests.

Each document reading includes two to six short evidence quotations. A typography-insensitive match locates them in the cleaned source. Across the 1,509 primary document readings, the mean per-document evidence-match share is 99.96%. This checks quotation fidelity; it does not establish that the economic interpretation is correct. A separate run re-scored 152 documents: stance agreement was 94.7%, score correlation 0.996 and mean absolute difference 0.023.

Three baselines form the original H1 comparison. The dictionary signs economic nouns near direction words. A TF-IDF logistic classifier learns from word and phrase frequencies. A sentence-embedding logistic classifier uses all-MiniLM-L6-v2 representations. The learned baselines use the same 1,984 training sentences and five-fold tuning. All readers are evaluated on the same 496 expert-labeled Trillion Dollar Words test sentences.

| Reader | Macro-F1 | Cohen's kappa | Role |
|---|---:|---:|---|
| Claude | 0.661 | 0.485 | Method under study |
| TF-IDF classifier | 0.578 | 0.361 | Stated baseline |
| Sentence embeddings | 0.576 | 0.374 | Stated baseline |
| Dictionary | 0.511 | 0.264 | Stated baseline |
| Fine-tuned RoBERTa | 0.737 | 0.602 | Reference added after the results |

Macro-F1 gives each of the three classes equal weight. Paired bootstrap resampling compares readers on identical sentences. Claude's lead over TF-IDF is 0.083, with a 95% interval of 0.027 to 0.139 and p = 0.004. McNemar's accuracy comparison gives p = 0.005. These results support H1 on the public expert labels.

The boundary matters. These annotations have been public since 2023 and could be in the model's training data. The planned human check on 150 sampled post-cutoff sentences was not run. Model-produced labels on those sentences are not human annotations. Masking historical documents partly addresses recognition, as discussed in section 6, but cannot replace independent human evaluation.

RoBERTa was fine-tuned after the original results on the same 1,984 labels. Nine settings were searched by five-fold validation; the chosen setting was refit with five seeds and their probabilities averaged. It exceeds Claude by 0.076 macro-F1, with a 95% interval of 0.030 to 0.122 and p < 0.001. It is outside the original H1 comparison, event study and backtest.

Source: [RUBRIC.md](RUBRIC.md); [ASSIGNMENT.md](ASSIGNMENT.md), requirements 2-3; [DESIGN.md](DESIGN.md), sections 5, 7 and 8; store tables `validity` and `llm_records`, and `meta.validity_tests`.

<!-- pagebreak -->

## 4. Release-window associations and H2

The event study asks whether more hawkish language accompanies higher Treasury yields over the window in which the document becomes public. For each document group, reader, tone measure and maturity, an OLS regression relates the yield change to standardized tone. Coefficients are reported in basis points per standard deviation, with HC1 standard errors. Results include the 2s10s slope, not only individual maturities.

Two meanings of change are kept separate. A reader's level score can be differenced against the previous scored document of the same type. Claude also has a paired-document rubric that compares successive statements directly and quotes changed passages. Both are retained as distinct measures; a coefficient from one is not presented as a result from the other.

The 198-test release-window family receives Benjamini-Hochberg adjustment. Diagnostics and controlled regressions are reported separately. In the frozen results, 26 tests survive at q < 0.10; 16 use Claude readings, seven use TF-IDF and three use embeddings.

A prominent association is the change in Claude's level reading of press conferences. A one-standard-deviation hawkish change accompanies a 3.9 bp rise in the 2-year yield, with t = 3.90 and q = 0.007 across 94 events. Including the TF-IDF tone change as a control leaves t = 3.57. The relationship is also examined with the 3-month bill move as a surprise control, the announced policy decision, and separate development and holdout periods.

The change in Claude's statement level score is most associated with the 5-year yield: approximately +1.8 bp per standard deviation, t = 3.15. It weakens at meetings without a press conference, to t = 1.91, and is close to zero after controlling for the conference's tone. With daily observations, statement and conference information are difficult to separate. This result is consistent with conference communication carrying much of the measured association.

Diagnostics include a day-before placebo and five- and twenty-day drift. Response curves show cumulative 2-year changes by tone tercile, describing response timing.

H2 is supported as an association within the measured release windows. It is not a causal estimate of an exogenous communication shock. Tone can reflect the same economic information that moves markets; several releases can share a window; daily fixes cannot isolate minute-by-minute reactions. False-discovery control addresses the number of tests, not these identification limitations. The absence of a delayed profitable trade must be assessed separately.

Source: [ASSIGNMENT.md](ASSIGNMENT.md), requirement 4; [DESIGN.md](DESIGN.md), sections 7-8; `evaluate/event_study.py` and store table `event_study`.

<!-- pagebreak -->

## 5. A duration overlay and H3

The trading question is deliberately harder than the release-window question. H3 specifies Claude's level scores for minutes and Board speeches, entry one trading day after the first eligible post-release ETF close, and a five-trading-day holding period. This is the pre-registered primary specification. The strategy cannot trade at a price observed before the complete document becomes public.

For each type, the score is standardized against the expanding mean and standard deviation of earlier documents. At least 12 earlier observations are required. The document position is `-clip(z, -2, 2) / 2`: hawkish tone shorts the duration spread and dovish tone buys it. Overlapping positions add and are capped between -1 and +1.

The spread is long IEF and short SHY. Its approximate duration difference is 7.1 minus 1.9 years. Scaling the spread by `1 / (7.1 - 1.9)` makes a full signal add or remove one year of portfolio duration. The overlay can be applied to an aggregate-bond benchmark, AGG, or a Treasury benchmark, IEI. Returns use the position held at the preceding close. Every position change pays 1 bp per side on both spread legs. Constant duration approximations and stylized costs are explicit modeling assumptions.

| Primary result | Frozen value |
|---|---:|
| Signals | 672 |
| Annualized Sharpe after costs | -0.18 |
| Shuffled-score placebo p-value | 0.28 |
| Probabilistic Sharpe ratio | 22% |
| Annual active return on the AGG portfolio | Approximately -10 bp |

The placebo shuffles scores within type and reruns the trade. The primary strategy does not beat this chance benchmark. Its probabilistic Sharpe ratio measures confidence that true Sharpe exceeds zero while allowing non-normal returns; 22% misses the 95% criterion. H3 is not supported.

The project also reports all 116 variants across readers, level and change signals, holding periods and entry rules. These are exploratory. A deflated Sharpe calculation accounts for specification search by comparing performance with what the best of many no-skill variants might show. No variant exceeds the resulting annualized Sharpe hurdle of 0.48. Selecting a positive row from the table would therefore not establish an edge.

The primary test was rerun once on 21 October after code review found two departures from the written design. Speech timestamps near a close were moved to the later window, and statements were compared policy decision with policy decision. The primary Sharpe changed from -0.23 to -0.18; its verdict did not change. The review and correction are disclosed rather than treated as an untouched one-shot experiment.

The findings concern this daily strategy and its costs, leaving intraday opportunities and other instruments open. Better measurement does not automatically imply investable alpha.

Source: [ASSIGNMENT.md](ASSIGNMENT.md), requirements 5-7; [DESIGN.md](DESIGN.md), sections 2, 4, 7-8; `evaluate/backtest.py` and store table `backtests`.

<!-- pagebreak -->

The Duration workspace connects this research to an inspectable risk example. A document link selects its frozen-reader score and replays its rule using earlier eligible peers only, with entry date and hold shown. The user supplies capital and duration assumptions to see dollar DV01, equal-dollar ETF legs, costs and parallel-shock P&L. The page links the source evidence to the stored primary test and forward evaluation. An isolated document rule differs from the backtest's combined overlapping position. Manual overrides and non-primary document types remain explicit. This interface adds no new profitability evidence.

## 6. Recognition, robustness and remaining limits

A model may recognize historical documents and have encountered their market reactions. H4 examines recognition and score stability after masking dates, names and rate levels.

Claude identifies the exact month for 99% of 149 masked statements. This makes recognition risk substantial, although a distinctive event can also reveal a document's date through legitimate content clues. The identification task alone cannot establish what was memorized or whether market outcomes influenced a score.

For the 60-document invariance sample, masked and raw continuous scores correlate at 0.99; mean absolute difference is 0.038 and stance agreement is 93%. The reading changes little when obvious identity clues disappear. This partially addresses the concern that explicit dates and names drive the score. It does not prove independence from training data: the remaining economic language can still identify an event, and two similar scores can share the same bias. H4 is therefore mixed.

A separate limitation applies to H1. Public expert labels may be familiar to the model, and no post-cutoff human test was completed. The 150 sampled sentences and other models' predictions cannot provide the missing independent human reference. Any later cross-provider comparison must be labeled model agreement, with the provider, model, prompt and responses retained as a separate experiment.

Other limits affect the financial interpretation. Daily Treasury fixes combine information arriving within a window. The smaller statement and conference samples provide less precision than the overall corpus size suggests. The 34 documents after the configured cutoff are too few for a strong generalization claim. ETF duration is held approximately constant, costs are simplified, and many specifications are explored. Robustness checks reduce some concerns but do not turn observational associations into causal estimates.

One additional analysis asks whether tone forecasts the next policy decision beyond what the 3-month bill and 2-year already price. Market variables explain 63% of the in-sample variation; adding tone raises this to 64%. Across 79 expanding-window forecasts from 2017, however, mean squared error is 0.153 with tone versus 0.149 without, with bootstrap p = 0.68. This test was added after the results and supports no claim of improved real-time forecasting.

The frozen design now runs prospectively. Stored release-day rules and the primary trade are applied to new data without refitting. Directional p-values wait for ten releases, and no verdict is issued before a year. Monthly re-readings of eight fixed documents monitor model drift: a mean score change above 0.10 or stance agreement below 75% flags a changed reader. Neither mechanism changes the frozen H1-H4 results.

Source: [DESIGN.md](DESIGN.md), sections 6, 8 and 10; store `meta.audit` and `meta.forecast`; `evaluate/forward.py` and `audit.py`.

<!-- pagebreak -->

## 7. Reproduction, implementation and use

The submission includes code and a compressed SQLite snapshot, so a reader can inspect the project without an API key, model training or fresh market downloads. From a fresh checkout or the extracted code archive, run:

```bash
make setup
make demo-data
make serve
```

`make setup` creates the Python environment and installs pinned dependencies. `make demo-data` unpacks the supplied store; it replaces the local database, so it belongs in a fresh project copy. `make serve` starts the dashboard at `http://127.0.0.1:8000`. The hosted read-only version is [fedtone.web.app](https://fedtone.web.app), with a backup at [fomc-tone-lab-production.up.railway.app](https://fomc-tone-lab-production.up.railway.app). The live site can accumulate later operational information; the submitted files and frozen research tables define the reported results.

A five-minute inspection starts at Home for the four hypotheses, continues to Validity for public-label comparisons and the audit, then Event study for release-window coefficients and Backtest for the pre-registered row. Fed now and Decisions connect the readings to policy decisions and source evidence. The Story shows one integrated presentation of the introduction, methods, results and implementation. The submitted PDF slides and write-up are self-contained; speaker notes and a live demonstration are not required to interpret them.

Stages communicate through one SQLite store. `collect.py` and `textclean.py` collect and clean text; `align.py` constructs availability windows; `llm/rubric.py` defines the rubric; `evaluate/validity.py`, `event_study.py` and `backtest.py` implement the tests. `findings.py` supplies shared verdicts, and `story.py` assembles the unified deck from stored results and the method and implementation components in `story_technical.py`. Offline checks are:

```bash
make test
make lint
node --check src/fomc/web/app.js
```

The research freeze prevents routine refreshes from retraining baselines or replacing reported estimates. New scoring identities retain separate model, prompt and data provenance. Raw model responses and message identifiers are preserved; keys stay in the ignored local environment file. The public service is read-only and contains no scoring key.

Beyond the brief, the system adds the trained RoBERTa reference, masking and repeatability audits, the prospective frozen-rule test, monthly drift monitoring, statement redlines, member biographies and descriptive tone timelines with turning points and dissents, a subscription feed, and automatic refresh with spending caps. These features support inspection, not confirmatory evidence of profitability.

Selected references and implementation documentation: Shah, Paturi and Chava (2023), *Trillion Dollar Words*, for the expert labels; Apel and Grimaldi (2012), for dictionary motivation; Benjamini and Hochberg (1995), for false-discovery control; Bailey and Lopez de Prado (2012, 2014), for probabilistic and deflated Sharpe ratios. Full design and references are in [DESIGN.md](DESIGN.md); provenance is in [DATA.md](DATA.md), rubric definitions in [RUBRIC.md](RUBRIC.md), and operational instructions in [OPERATIONS.md](OPERATIONS.md).
