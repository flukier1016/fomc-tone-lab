# FOMC Tone Lab: the story (2026-10-26)

Team: Genie Zhang, Hong-syuan Lin, Myron Pang, Weijun Situ

## 1. FOMC Tone Lab

*Final Project Group 2 · IEOR 4723 · Fall 2026*
Measuring Fed Communication and Testing Duration Signals

> We are Group 2. Our topic is the central bank communication index: read everything the Fed publishes, score its tone with Claude, see whether Treasuries react, and ask whether a duration trade can use it. Everything on these slides is computed live from our system.

## 2. Contents

*Roadmap*
| Section | What it covers | Slides |
|---|---|---|
| Question and data | The task, course lessons, the data and release times | 3-8 |
| Readers and validation | How each reader scores tone and how accurate it is | 9-21 |
| Index, yields and duration | Tone over time, Treasury reactions and the duration trade | 22-31 |
| Forward checks and system | Tests on new data, the system and the dashboard | 32-41 |
| Conclusions and limits | What we found and what remains open | 42-46 |
Five sections, from the question to the conclusions

> First define the investment question and the information available at each release. Then explain the readers, including the model fine-tuned locally, before judging their accuracy and recognition risk. Only then move to Treasury responses and the delayed duration trade. Forward evaluation and implementation follow the research results, and the close separates delivered functionality from evidence of profitability.

## 3. The Fed moves Treasuries with words

*Topic 4 in one picture*
1. **The Fed speaks** Eight decisions a year: a statement at 2:00 p.m., the Chair’s press conference at 2:30, minutes three weeks later, and speeches in between. 1,509 documents since 2009
2. **Its tone: hawkish or dovish**
   - Hawkish: “…anticipates that ongoing increases in the target range will be appropriate” (21 September 2022 statement, Claude +0.90)
   - Dovish: “…the Committee decided to lower the target range for the federal funds rate to 0 to 1/4 percent” (15 March 2020 statement, Claude -0.95)
3. **Yields move** Hawkish news raises the expected path of the policy rate, so yields rise, most at two to five years; dovish news pulls them down. Bond prices move the other way
4. **Duration sets the gain or loss** ΔP / P ≈ −D × Δy If yields rise 10 bp, IEF (D ≈ 7.1) loses about 0.7% and SHY (D ≈ 1.9) about 0.2%. Hawkish: shorten. Dovish: lengthen. Within ±1 year.
So its tone might tell a bond portfolio how much duration to hold
Source: FOMC statements of 21 Sep 2022 (+0.90) and 15 Mar 2020 (−0.95), scored by Claude; IEF and SHY durations from the backtest.

> Before the results, the idea. The Fed sets short-term interest rates, and it signals where they are going through what it says: statements, minutes, press conferences and speeches. When it sounds hawkish, ready to raise rates to cool inflation, yields rise and bond prices fall; when it sounds dovish, they move the other way. How much a bond portfolio gains or loses depends on its duration: seven years of duration loses about seven percent if yields rise one point. So the topic asks: can we read the tone of the Fed’s words, turn it into an index, and use it to decide how much duration to hold?

## 4. What the brief asks, and what we built

*The assignment · Topic 4*
- A hawkish-dovish index from statements, minutes, press-conference transcripts and governor speeches → 1,509 documents from the Fed’s website since 2009, each stamped with its release minute
- Claude scores each document on a defined rubric with evidence spans → Rubric v1: six policy dimensions and a stance from −1 to +1; mean document evidence-match share 99.96%
- Compared with simpler baselines: dictionary methods and sentence-level embeddings → Dictionary, TF-IDF classifier and MiniLM sentence embeddings, judged on the same human labels
- Tested against subsequent Treasury yield changes from FRED across the curve → 3-month to 30-year yields and the 2s10s slope over each release window; FRED first, the Treasury par curve it republishes as fallback (used this run)
- A duration tilt in a Treasury or aggregate-bond portfolio, respecting that statements are priced within minutes → IEF against SHY, applied to AGG and IEI; entry the day after release; minutes, speeches and statement-to-statement shifts
Topic 4: a central bank communication index and duration positioning
Source: IEOR 4723 final project brief, Topic 4.

> Our topic is number four: build a hawkish-dovish index from everything the Fed publishes, score it with Claude against a defined rubric with evidence, compare it with simpler baselines, test it on Treasury yields across the curve, and use it to tilt duration in a bond portfolio. The left column is what the brief asks for; the right column is what we built for each line. Why it matters: The brief’s key insight shapes every test: the market reprices a statement within minutes, so any tradable edge has to sit in slower documents or in the change of tone.

## 5. What we learned in the course, and how we used it

*From the course*
| What we learned | How we applied it |
|---|---|
| A prompt has a ceiling; training on labeled data can go further | Fine-tuned RoBERTa on the expert labels as a reference reader, and report that it beats Claude |
| Treat the prompt as a specification: version it and check the output | One rubric enforced as a JSON schema; every quote is checked against the Fed's text |
| A model may remember history; test for it before trusting a score | Masked dates and names, asked Claude to date statements, re-scored to check stability |
| Use only what was public at the time | Timestamped every release; trades enter at the first close after publication |
| Count every variant you try, and charge for costs | Reported 116 strategy variants with costs and placebos, including the negative result |
| Ground answers in sources | Every score links to the Fed's own words; the full archive is searchable |
Six lessons from the lectures, each put to work in this project
Source: IEOR 4723 Sessions 1 to 4 and the Topic 4 brief; page references in docs/COURSE_ALIGNMENT.md.

> Six things from the lectures shaped how we built this. From Session One: prompting a general model has a ceiling, and training on labeled data can go past it, so we fine-tuned RoBERTa on the expert labels and report that it beats Claude. From Session Two: treat the prompt as a specification you version and check, and test whether a model is simply remembering history; hence the JSON rubric, the quote checks, the masked dates and the re-scoring. From Session Three: use only information that was public at the time, and count every variant you try; hence the release clocks, the next-close entry, and every strategy reported with costs and a placebo, including the one that failed. From Session Four: ground answers in sources; every score links back to the Fed's own words, and the archive is searchable by full text.

## 6. Four hypotheses, four answers

*The answers first*
- H1 · Measurement: Claude matches public expert labels better than the baselines (Supported on public expert labels; Macro-F1 0.66 against 0.58 (p = 0.004))
- H2 · Information: Tone is associated with release-window Treasury moves (Supported; 26 of 198 tests survive false-discovery control)
- H3 · Tradability: A pre-registered next-day duration tilt beats chance (Not supported; Sharpe −0.18, placebo p = 0.28)
- H4 · Contamination: Masked scores are stable; recognition risk remains (Mixed; Dates 99% of masked statements, yet masked scores track raw ones (r = 0.99))
Public-label accuracy and release-window associations; no delayed trading edge detected
Source: Project results, frozen 21 October 2026; design and pre-registration in docs/DESIGN.md.

> Here are the answers before the evidence, one card per hypothesis. H1: supported. H2: supported. H3: not supported. H4: mixed. For the desk: Use Claude to read the Fed faster and with evidence; do not expect a daily duration tilt on tone alone to pay.

## 7. Every Fed document since 2009

*Data*
**1,509**: statements, minutes, press conferences and Board speeches; 4.5M words
- 149 statements; time from text or recorded convention
- 142 minutes; attendance removed
- 95 press conferences; Chair's words only
- 1,123 speeches; time from the Fed's feed
Fed source text, recorded release times, and consistent cleaning
Source: Federal Reserve Board website: FOMC calendar, statements, minutes, press conferences and speeches.

> The corpus is collected from the Federal Reserve Board's own calendar, statements, minutes, transcripts and speech feed. Each release minute retains its source: text, the speech feed or a recorded convention. Press conferences keep the Chair's words, minutes omit attendance lists, and speeches under 300 words are excluded. The counts and annual bars use documents without an exclusion note. For the desk: One searchable store keeps source text, time provenance and every score, so a reading can be checked against its source.

## 8. Release windows and trade entry

*Timing*
**+1 day**: primary entry lag after the first eligible ETF close
- Event window: last pre-release Treasury fix to the first eligible later fix
- Speech-feed buffer: 60 minutes before either market close counts as after it
- Entry clock: first eligible ETF close, then one more trading day for the primary
- Return clock: first return after entry, never the return ending at that close
Event windows measure repricing; returns begin only after entry
Source: Fed release times; Treasury par yields (about 3:30 p.m.) and ETF closes (4:00 p.m.); align.py.

> A document's event window begins at the last Treasury fix before the first information is public, and ends at the first eligible fix after the full text is available. A statement has one fix-to-fix window; a press conference that straddles the Treasury fix spans two. A feed-timestamped speech's availability is delayed by 60 minutes for both the Treasury-window end and ETF-entry calculation. The exploratory entry is the first eligible ETF close; the primary waits one more trading day. A position earns only close-to-close returns after its entry. Weekends and holidays follow the observed trading calendar. For the desk: The event study asks when yields adjust; the backtest asks whether a later executable position can use the signal.

## 9. One rubric, enforced as a JSON schema

*Rubric v1*
**6**: policy dimensions, each from −2 to +2, then an overall stance and a continuous score
- Structured outputs: the schema is the contract, no free text to parse
- The scorer sees the document type and the text, never the date
- Any change to the prompt or schema bumps v1 and starts new records
```text
{
  "policy_relevance": "high | medium | low",
  "policy_action":                -2 … +2 | null,
  "forward_guidance":             -2 … +2 | null,
  "inflation_assessment":         -2 … +2 | null,
  "activity_labor_assessment":    -2 … +2 | null,
  "risk_balance":                 -2 … +2 | null,
  "balance_sheet":                -2 … +2 | null,
  "overall_stance":               -2 … +2,      # holistic, not an average
  "stance_score":                 -1.0 … +1.0,  # the index
  "confidence":                   0 … 1,
  "evidence": [{"dimension": …, "quote": "verbatim"}]
}
```
Positive is hawkish; negative is dovish; stance_score is the index
Source: llm/rubric.py and llm/scorer.py.

> Each level reading returns this object. Six dimensions on an integer scale from minus two to plus two, null when a document does not address one; an overall stance that weighs forward guidance and the balance of risks most; a continuous score for finer ranking between documents with the same stance; a confidence; and evidence quotes tied to a dimension. The schema is enforced by structured outputs, so nothing is parsed from prose. For the desk: The stance_score is the index; dimensions explain it and quotes locate supporting language.

## 10. Every score comes with its evidence

*Scoring and evidence verification*
**99.96%**: mean document evidence-match share (1,509 documents)
- Rubric v1: structured JSON and character-span evidence
- 1,506 of 1,509 documents: every quote matched
- 3 documents contain an unmatched quote
- Lowest document match share: 67%
Claude supplies quoted spans; we verify each quote against the source
Source: Claude Opus 5.5 readings in the project store; quote checks in llm/scorer.py.

> Each document is scored against six policy dimensions with a holistic stance, a continuous score, confidence and quoted evidence. Every returned quote is checked against the cleaned source with typography normalized; matched spans are located as character offsets. The mean document evidence-match share is 99.96% over 1,509 level records. Unmatched quotes are disclosed, not treated as verified evidence. Finding the quoted language proves its location, not the correctness of the model's economic judgment. Request provenance and spending are detailed on the next page. For the desk: Matched spans make scores inspectable; quote matching alone does not establish that an economic interpretation is correct.

## 11. Cached requests and auditable spending

*Scoring engine*
**$32.75**: for 2,057 stored Claude records; operations continue after the research freeze
- A record's key changes with the prompt, schema or text, never otherwise
- Records live in git: a rebuilt store costs nothing
- Refusals, truncation and schema misses are recorded, not retried silently
| Piece | Setting |
|---|---|
| Model | claude-opus-5-5, adaptive thinking, effort medium |
| Output | structured JSON against the rubric's schema; quotes located in the source |
| Batching | 7 Message Batches at half price; 21 direct calls |
| Prompt cache | 3.7M input tokens read from the cache |
| Tokens | 10.6M in, 0.96M out |
| Records | 2,057, each keyed by a hash of prompt, schema and text |
| Failures | 0 failed requests |
| Caps | at most 40 new jobs a run; 5 USD a month of scheduled scoring |
Operational snapshot through 2026-10-22, including monthly re-reads
Source: Anthropic Message Batches records in data/llm/; llm/scorer.py.

> All Claude traffic goes through one module. The full corpus ran as 7 Message Batches at half price, with the system prompt cached. Each record is keyed by a hash of prompt, schema and text, so a rerun never pays twice, and the 2,057 records are committed. 21 direct calls are the scheduled scoring of new documents and the monthly re-read. For the desk: Every reading is reproducible from its record: request and message IDs, tokens, cost and raw text.

## 12. Claude reads the 16 September statement as hawkish

*One reading, end to end*
And shows, word for word, where the statement says so
Source: FOMC statement of 16 September 2026; Claude Opus 5.5, rubric v1.

> Here is one real reading: the statement of 16 September. Claude scores it +0.75, hawkish, with confidence 0.85. The highlights are its evidence: the rate decision, the inflation language, the commitment to price stability. Each quote was found in the source text. For the desk: An analyst can check any score in seconds: the highlighted words are the evidence, located in the source.

## 13. Same 1,984 sentences, same five folds

*Readers*
| Reader | Representation | Classifier | Tuned | CV macro-F1 | Test macro-F1 |
|---|---|---|---|---|---|
| Dictionary | policy nouns near direction words | signed rules | none | – | 0.511 |
| TF-IDF | unigrams and bigrams, min_df 2, sublinear tf | logistic regression, balanced | C = 2 of 0.5 to 8 | 0.575 | 0.578 |
| Sentence embeddings | all-MiniLM-L6-v2, 384 dimensions, ONNX | logistic regression, balanced | C = 4 of 0.25 to 16 | 0.592 | 0.576 |
| Fine-tuned RoBERTa | RoBERTa-large, 355M parameters | fine-tuned end to end | 9 settings × 5 folds | 0.724 | 0.737 |
| Claude Opus 5.5 | sentences (H1); documents (index) | zero-shot rubric | none | – | 0.661 |
H1 uses the same test sentences; corpus scoring uses full documents
Source: Trillion Dollar Words (Shah, Paturi and Chava, 2023): 1,984 training and 496 test sentences.

> Five readers. The dictionary needs no training. TF-IDF and sentence embeddings each fit a balanced logistic regression, with the penalty chosen by five-fold cross-validated macro-F1 on the train split. The RoBERTa reference uses the same folds and score. Claude reads the same test sentences for H1, and whole documents for the index, without task-specific training. A document's score for the sentence readers is the mean of P(hawkish) minus P(dovish) over its sentences. Why it matters: Same data, same folds, same score: the readers differ only in how they represent a sentence.

## 14. How we fine-tuned RoBERTa locally

*The model we trained locally*
1. **Keep the split fixed** 1,984 public expert training sentences; 496 held out. Three classes: dovish, neutral and hawkish.
2. **Select on validation folds** 9 settings across 5 stratified folds. Mean validation macro-F1 selects the setting and epoch.
3. **Fit the chosen model locally** Full-parameter RoBERTa fine-tuning on Apple MPS; 5 seeds. Chosen learning rate 2e-5, stopping at epoch 9.
4. **Evaluate the fixed ensemble** Average the seeds' class probabilities. Test once; then average P(hawkish) minus P(dovish) over each document's sentences.
A supervised reference added after the original study, using public expert labels
Source: RoBERTa (Liu et al., 2019); Trillion Dollar Words training labels; finetune.py.

> The model is a pretrained RoBERTa encoder with a three-class classification head. We update all its parameters locally on an Apple GPU through PyTorch MPS. The saved record identifies the backbone revision, train/test sentence hashes, device, software versions, every search run and the final seeds. The 1,984 training sentences and the 496-sentence held-out test are the same split used by the supervised baselines. Five-fold stratified validation selects architecture, learning rate and stopping epoch without consulting test performance. Training uses class-balanced cross-entropy, AdamW, 10% warmup, linear decay and gradient clipping. The final chosen configuration is fit on all training sentences with five seeds; their class probabilities are averaged before the fixed ensemble is evaluated. Document tone is the mean of P(hawkish) minus P(dovish) across sentences. This reference was added after the original results and does not replace the frozen Claude H1 comparison, event study or duration strategy. The next slide shows the complete parameter search; the following slides compare held-out performance.

## 15. Nine settings, five folds, five seeds

*Fine-tuning RoBERTa*
**0.724**: cross-validated macro-F1 of RoBERTa-large at 2e-5, epoch 9 of ten
- AdamW, betas 0.9 and 0.98, eps 1e-6, weight decay 0.01
- 10% warmup, linear decay; class-balanced loss; gradients clipped at 1
- Validation macro-F1 after every epoch: the epoch is chosen too
Axis: Cross-validated macro-F1. Mean ±1 fold SD; purple is the chosen setting.
| Variant | Estimate | Interval | Details |
|---|---:|---|---|
| base; 1e-5 | 0.668 | 0.642 to 0.694 | best epoch 9; batch 16; fold SD 0.026 |
| base; 2e-5 | 0.681 | 0.666 to 0.697 | best epoch 9; batch 16; fold SD 0.015 |
| base; 3e-5 | 0.686 | 0.665 to 0.706 | best epoch 9; batch 16; fold SD 0.021 |
| base; 5e-5 | 0.675 | 0.643 to 0.707 | best epoch 6; batch 16; fold SD 0.032 |
| large; 5e-6 | 0.702 | 0.679 to 0.724 | best epoch 10; batch 16; fold SD 0.022 |
| large; 1e-5 | 0.716 | 0.696 to 0.736 | best epoch 5; batch 16; fold SD 0.020 |
| large; 2e-5 (chosen) | 0.724 | 0.708 to 0.740 | best epoch 9; batch 16; fold SD 0.016 |
| large; 2e-5; decay 0.9 | 0.713 | 0.696 to 0.730 | best epoch 10; batch 16; fold SD 0.017 |
| large; 2e-5; b32 | 0.720 | 0.697 to 0.742 | best epoch 8; batch 32; fold SD 0.023 |
The best setting is refit on all 1,984 sentences with five seeds, then averaged
Source: finetune.py; data/baselines/roberta-tuned.json.

> The search ran RoBERTa-base at four learning rates and RoBERTa-large at three, then two refinements of the best: layer-wise learning-rate decay and batches of 32. Each setting ran on the TF-IDF baseline's five folds for ten epochs, scored after each, so the epoch with the best average was chosen with the rest. The winner was refit on all 1,984 sentences with five seeds, stopped at that epoch, and their probabilities averaged. For the desk: The test split was read once, by the chosen setting; every setting tried is in the record.

## 16. Higher agreement on public expert labels

*Claude against three baselines*
**0.66**: macro-F1 on 496 sentences labeled by finance experts; the best baseline reaches 0.58
- TF-IDF 0.58 · Embeddings 0.58 · Dictionary 0.51
- Kappa 0.49; best baseline 0.37 (Sentence embeddings)
- Lead +0.08, 95% interval +0.03 to +0.14
- Fine-tuned RoBERTa 0.74, for reference
Public expert labels support H1; the post-cutoff human test was not run
Source: Trillion Dollar Words test split, 496 expert-labeled sentences (Shah, Paturi and Chava, 2023).

> Four readers on the same 496 sentences that finance experts labeled hawkish, dovish or neutral. A dictionary of policy words reaches 0.51; two learned baselines, TF-IDF and sentence embeddings, reach about 0.58. Claude reaches 0.66, the highest agreement beyond chance of the four. For reference, added after the results: a RoBERTa we fine-tuned on the same 1,984 labeled sentences reaches 0.74. Trained on the labels, a transformer does better still; Claude needed none. For the desk: The baselines see words; Claude sees policy. The gap is largest on sentences that hedge, qualify or look ahead.

## 17. Ahead of the baselines, behind a trained model

*Validity statistics*
| Reader | Accuracy | Macro-F1 | Kappa | Claude − reader F1 | 95% interval | p | McNemar p |
|---|---|---|---|---|---|---|---|
| Fine-tuned RoBERTa | 0.746 | 0.737 | 0.602 | −0.076 | −0.122 to −0.030 | < 0.001 | 0.003 |
| Claude Opus 5.5 | 0.677 | 0.661 | 0.485 | – | – | – | – |
| TF-IDF classifier | 0.601 | 0.578 | 0.361 | +0.083 | +0.027 to +0.139 | 0.004 | 0.005 |
| Sentence embeddings | 0.599 | 0.576 | 0.374 | +0.085 | +0.030 to +0.136 | 0.002 | 0.002 |
| Dictionary | 0.569 | 0.511 | 0.264 | +0.150 | +0.094 to +0.205 | < 0.001 | < 0.001 |
Paired macro-F1 gaps on public expert labels; positive favors Claude
Source: Trillion Dollar Words test split (496 sentences); evaluate/validity.py.

> Claude's macro-F1 is 0.661. Against each reader, the gap is bootstrapped by resampling the same sentences 2,000 times; the interval and two-sided p come from that distribution. McNemar's test uses only the sentences the two readers label differently. These labels have been public since 2023 and may be in training. The post-cutoff human test was not run; masked/raw agreement partly addresses contamination risk. How to read it: A paired test on the same sentences: each reader's gap to Claude, its interval, and the sentences only one of them gets right.

## 18. Commonest miss: neutral read as dovish

*Where the readers miss*
**41**: of 247 neutral test sentences Claude read as dovish
- Dovish recall: Claude 66% · RoBERTa 73%
- Hawkish recall: Claude 61% · RoBERTa 77%
- Neutral recall: Claude 72% · RoBERTa 74%
**Claude Opus 5.5**

| expert \ reader | Dovish | Hawkish | Neutral |
|---|---|---|---|
| Dovish | 89 | 11 | 35 |
| Hawkish | 16 | 69 | 29 |
| Neutral | 41 | 28 | 178 |

**Fine-tuned RoBERTa**

| expert \ reader | Dovish | Hawkish | Neutral |
|---|---|---|---|
| Dovish | 99 | 12 | 24 |
| Hawkish | 10 | 88 | 16 |
| Neutral | 29 | 35 | 183 |

**TF-IDF classifier**

| expert \ reader | Dovish | Hawkish | Neutral |
|---|---|---|---|
| Dovish | 78 | 13 | 44 |
| Hawkish | 18 | 56 | 40 |
| Neutral | 40 | 43 | 164 |

Each reader's labels against the experts' on the 496 test sentences
Source: Trillion Dollar Words test split; rows are the experts’ labels, columns the reader’s.

> The matrices count the 496 test sentences by the experts' label in rows and the reader's label in columns. Claude's largest error is reading neutral sentences as dovish: it leans where the annotators saw none, which fits a reader of whole documents applied to single sentences. For the desk: Shading is each row's share: a dark diagonal is a reader that agrees with the experts.

## 19. Trained on the labels, RoBERTa beats Claude

*For reference: a transformer trained on the same labels*
**0.74**: macro-F1 on the same 496 test sentences; Claude, with no labels, reaches 0.66 and TF-IDF on the same labels 0.58
- Best of 9 settings on the same five folds: RoBERTa-large, learning rate 2e-5, 9 epochs; added after the results
- Five seeds averaged; alone 0.71 to 0.74
- Agreement with Claude on documents, r: statements 0.77 · minutes 0.86 · press conferences 0.79 · speeches 0.70
The same 1,984 hand-labeled sentences improve accuracy; Claude needs no task-specific training
Source: RoBERTa (Liu et al., 2019); Trillion Dollar Words (Shah, Paturi and Chava, 2023).

> The obvious question after the last slide: what if, instead of an LLM, we train a transformer on the same 1,984 hand-labeled sentences the TF-IDF classifier learns from? We fine-tuned RoBERTa, tried 9 settings on the same five folds, refit the best with five seeds and read the test sentences once. It reaches 0.74, above Claude's 0.66. On whole documents the two readers mostly agree: r = statements 0.77 · minutes 0.86 · press conferences 0.79 · speeches 0.70. Because it came after the results, it is a reference, not part of H1. For the desk: Labels buy accuracy on sentences like these; Claude needs none, reads whole documents and quotes its evidence.

## 20. Recognition and score stability

*Memorization check*
**r = 0.99**: correlation of Claude’s scores with and without dates, names and rate levels (60 documents)
- Dates 99% of masked statements to the exact month
- Same overall stance on 93% of masked documents
- 34 documents released after the model’s knowledge cutoff so far
Masked scores track raw scores, a partial reassurance rather than proof against memorization
Source: audit.py: masked and raw readings, month identification.

> An honest worry: Claude has read history, including what markets did. With every date, name and rate level masked, it still dates 99% of statements to the exact month, so it recognizes them. But its scores barely move when those details are removed: correlation 0.99. The check partly addresses recognition risk; it cannot rule out contamination. For the desk: The model knows Fed history, so trust rests on two checks: masked scores match, and the post-cutoff sample keeps growing.

## 21. Stable scores under masking and re-reading

*Reliability and memorization*
**0.996**: correlation between two separate batches on 152 documents
- Same stance on 94.7% of 152 repeated documents
- Mean change 0.023 on a scale of −1 to +1
- Drift flag: mean change above 0.10 or stance agreement below 75%
- **100%** 152 repeated documents: stance within one step on the five-point scale
- **99%** of 149 masked statements dated to the exact month
- **r = 0.99** masked against raw scores on 60 documents
- **100%** same stance on the 8 anchors re-read in 2026-10; mean change 0.025
Masking dates and names barely moves scores; it cannot rule out contamination
Source: audit.py.

> Four checks. A separate batch of 152 documents re-scored gives r of 0.996. Masked statements are dated to the exact month almost every time, consistent with recognition but not proof of memorization. Scores with dates, names and rate levels masked track the raw ones at r of 0.99. Every month eight anchor documents are read again through the current model and pipeline; a change past the limits starts a new experiment. For the desk: Masking dates and names barely changes scores; recognition risk and possible shared bias remain.

## 22. Fed language is running hawkish

*The index today*
**96th**: percentile: the latest minutes against every set since 2009
- Statement 95th
- Press conference 95th
- Last 25 speeches 90th
Into the 28 October decision; the latest minutes against every set since 2009
For the desk: Words lean hawkish and the 2-year sits +81 bp over the overnight rate: language and pricing point the same way.
Source: FOMC minutes since 2009, scored by Claude Opus 5.5.

> Each dot is a set of minutes scored by Claude Opus 5.5; the line is a rolling median. The latest minutes, released 7 October, rank in the 96th percentile of all minutes since 2009.

## 23. The September hike rewrote 35% of the statement

*Decisions and wording*
**35%**: of the wording changed against the previous decision (median since 2009: 14%)
- +25 bp to 3.75–4.00%
- Vote 12–0
- 3 dissents at the previous meeting wanted a hike
A word-level redline of every decision against the one before
Source: FOMC statements since 2009 (21 hikes, 11 cuts, 111 holds).

> Every statement is parsed for the decision and compared word by word with the previous one. The September hike rewrote 35 percent of the statement against a median of 14 percent. At the previous meeting 3 members had dissented for a hike. For the desk: Read the redline, not only the decision: new phrases and vanished dissents show how much conviction is behind a move.

## 24. 1,213 regressions, one FDR family

*Event study*
**26 / 198**: main tests survive q < 0.10, 16 of them on Claude's reading
- β in basis points per standard deviation of tone
- Statements are compared decision with decision
- Controls and split samples are exploratory diagnostics outside the main family
```text
Δy = α + β · tone_z + γ' · controls + ε          # OLS, HC1 errors

tone_z    a reader's score (level) or its change since the
          previous document of the type (shift), standardized
groups    statements, minutes, press conferences, speeches
          (and the Chair's against other members')
y         3m, 2y, 5y, 10y, 30y and 2s10s over the window;
          the day before (placebo); 5 and 20 days after (drift)
controls  3-month bill (the surprise), the announced move,
          TF-IDF tone of the same document; split samples
family    Benjamini-Hochberg q over the 198 main tests
```
Exploratory main-grid tests share one BH adjustment; diagnostics are separate
Source: evaluate/event_study.py.

> One specification across the grid: the yield change over the release window on standardized tone, with HC1 errors. The main grid crosses four document groups, the readers, level and shift, and six outcomes: 198 tests, with Benjamini-Hochberg q-values across all of them. 26 survive at q below 0.10. Controls, split samples, the day-before placebo and the drift outcomes are reported beside each test, outside the family. For the desk: BH adjustment addresses the main-grid search; it does not identify an exogenous communication shock.

## 25. Tone and 2-year release-window yield changes

*H2 · Exploratory association*
**+3.9 bp**: Associated 2-year move per SD of score change (t = 3.90, q = 0.007; Claude Opus 5.5)
- Day before: t = 1.71 (placebo)
- 3-month bill as a surprise control: t = 3.20
- TF-IDF tone as a control: t = 3.57
Press conferences: change in the level score between releases
For the desk: No detectable five-day drift (t = 0.37); this does not establish full pricing.
Source: Treasury par yields; 94 release windows; evaluate/event_study.py.

> The lines show the average path of the 2-year around release days for the most dovish, middle and most hawkish thirds of tone shift in press conferences. One SD more hawkish accompanies a 2-year move of +3.9 basis points over the release window, t of 3.90. The day before: t of 1.71. With the 3-month bill as a control: t of 3.20. With the TF-IDF classifier's tone of the same documents as a control, Claude's tone still has a t of 3.57; it adds an association beyond the TF-IDF score.

## 26. Statement tone shifts across the curve

*Across the curve*
**+1.8 bp**: 5-year move per standard deviation of the statement-to-statement shift in Claude’s score (t = 3.15)
- 2-year: t = 2.94
- 10-year: t = 2.22
- Meetings without a press conference: t = 1.91 (n = 46)
- Press conference’s tone as a control: t = 0.01
Level-score changes between policy decisions; statement and conference windows overlap
Source: FOMC statements and Treasury par yields; evaluate/event_study.py.

> This is the brief’s tone shift between consecutive statements. We regress each yield’s move over the statement window on the change in level score since the previous decision. The strongest association is at the 5-year; the result is descriptive, not a causal estimate. The yields are the Treasury’s daily par curve, the same series FRED republishes; FRED was unavailable when we last ran the pipeline, and the next run tries it first again. For the desk: Daily fixes cannot isolate statement information from an overlapping press conference.

## 27. The press-conference association across checks

*The headline, stress-tested*
**t = 3.90**: +3.87 bp on the 2-year per standard deviation of Claude Opus 5.5's shift
- 3-month bill control: t = 3.20
- Announced move control: t = 3.88
- TF-IDF tone control: t = 3.57
Axis: 2-year move, bp per SD of tone. 95% HC1 intervals; hollow dots cross zero.
| Variant | Estimate | Interval | Details |
|---|---:|---|---|
| Headline | 3.87 | 1.93 to 5.81 | n = 94; t = 3.90; q = 0.007 |
| 3-month bill control | 3.21 | 1.24 to 5.18 | n = 94; t = 3.20; near-term surprise |
| Announced move control | 3.87 | 1.92 to 5.82 | n = 94; t = 3.88 |
| TF-IDF tone control | 3.81 | 1.72 to 5.91 | n = 94; t = 3.57; word-count tone |
| 2009 to 2019 | 2.53 | 0.99 to 4.07 | n = 39; t = 3.23 |
| Jan 2020 to Jun 2026 | 5.22 | 1.78 to 8.65 | n = 53; t = 2.97 |
| Day-before placebo | 0.70 | -0.10 to 1.50 | n = 94; t = 1.71 |
| 5-day drift | 0.30 | -1.30 to 1.91 | n = 94; t = 0.37 |
| 20-day drift | 0.82 | -3.13 to 4.77 | n = 94; t = 0.41 |
The association survives controls and sample splits; no significant later drift
Source: Stored event-study estimates; evaluate/event_study.py.

> The strongest 2-year relationship, read across every robustness row. The near-term surprise, the announced move and the TF-IDF tone of the same transcript each leave it significant, so Claude reads something the decision and word counts do not. It holds in both halves of the sample. The day-before placebo is weaker and later drift is not statistically detectable; full market pricing is not established. For the desk: Control and split-sample checks do not separate an exogenous language shock from shared news.

## 28. Claude accounts for 16 of 26 surviving tests

*Robustness*
**26 / 198**: main release-window tests with Benjamini-Hochberg q below 0.10
- Claude: 16 of 54 tests
- Dictionary, TF-IDF and embeddings: 10 of 144
- Placebo, drift, controls and split samples are separate diagnostics
Exploratory release-window associations; BH adjustment across 198 tests
Source: Benjamini and Hochberg (1995); evaluate/event_study.py.

> We ran 198 exploratory release-window regressions and corrected for that family. 26 survive at a 10 percent false-discovery rate, and 16 of them use Claude’s reading. The chart shows the 2-year coefficients by document group for the three strongest readers. For the desk: False-discovery control addresses specification search, not shared news or causal identification.

## 29. A trade fixed in advance

*The pre-registered trade*
**−0.18**: Sharpe of the pre-registered tilt: Claude on minutes and speeches, next-day entry
- Newey-West t = −0.79; hit rate 51%
- Shuffled-score placebo p = 0.28 (500 draws)
- Probabilistic Sharpe 22%; −10 bp a year on AGG
```text
z_i  = (s_i − mean_earlier) / sd_earlier    # same type, ≥ 12 earlier
θ_i  = −clip(z_i, −2, 2) / 2              # hawkish → shorter
pos_t = clip(Σ θ_i over open trades, −1, 1)  # each held 5 days
r_t  = pos_(t−1) · (r_IEF − r_SHY) − 2 × 1 bp × |Δpos_t|
tilt = 0.192 of the portfolio per unit    # ± 1 year of duration

PSR (probabilistic Sharpe) =
  Φ((SR − 0) · √(T−1) / √(1 − γ3·SR + (γ4−1)/4 · SR²))
DSR (deflated Sharpe): benchmark = E[max SR of N no-skill variants]
SR: daily Sharpe; T: days; γ3: skewness; γ4: kurtosis; Φ: normal CDF
```
Standardize, cap, hold five days, pay costs: the code is the pre-registration
For the desk: Every parameter was written down before the first run; the code is the pre-registration.
Source: Bailey and López de Prado (2012, 2014); evaluate/backtest.py.

> Signals are standardized against earlier documents of the same type only. A hawkish document sets a negative position, capped so one signal moves at most half a unit and all open trades at most one. Returns are the IEF-minus-SHY spread with costs on both legs for every change. The probabilistic Sharpe ratio allows for skew and fat tails; the deflated one raises the bar to what the best of all variants would show by luck.

## 30. No reliable delayed trading edge

*Duration trading and selection bias*
**−0.18**: Sharpe after costs: Claude on minutes and speeches, next-day entry, 5-day hold
- Placebo p = 0.28; probabilistic Sharpe 22%
- 116 variants; expected-best no-skill Sharpe 0.48
- 0 pass DSR 95%; active AGG −10 bp/year
- 21 Oct correction: Sharpe −0.23 → −0.18; verdict unchanged
One primary specification; every exploratory variant is counted in the search
For the desk: PSR tests Sharpe against zero; DSR raises the benchmark for the search across all variants.
Source: Yahoo Finance ETF closes; Bailey and López de Prado (2014); evaluate/backtest.py; docs/DESIGN.md.

> The primary tilt was specified before results: Claude's level scores on minutes and speeches, next-day ETF entry, five-day hold, after costs. Its Sharpe is -0.18. All 116 tested variants are reported; 0 pass the 95% deflated-Sharpe criterion, against an expected-best no-skill Sharpe of 0.48. PSR compares the primary Sharpe with zero; DSR adjusts the comparison for the search. The primary test was rerun once on 21 October 2026 after code review restored the speech-availability buffer and decision-with-decision comparisons in the written design. Sharpe changed from −0.23 to -0.18; the verdict did not change. This daily-horizon result does not establish that every possible trading edge has disappeared.

## 31. From a Fed document to duration exposure

*The duration workflow*
1. **Read the evidence** A scored Fed document, its source and policy-relevant evidence spans
2. **Replay the fixed rule** Earlier same-type peers, a standardized score and explicit delayed entry
3. **Translate to money** User capital and duration budget, dollar DV01, ETF legs and round-trip cost
4. **Challenge the result** Parallel shocks, the stored historical test and prospective evaluation
A traceable rule replay connects evidence with sizing and its historical test
Source: duration.py; frozen reader and entry rules from the backtest.

> Open a document and choose Explore duration. The workspace reads its score from the frozen primary model. It standardizes only against earlier eligible documents of the same type. The fixed rule maps that z-score to a share of the duration budget, as in the historical test. The user supplies capital, portfolio duration and the budget; an equal-dollar ETF overlay then gives dollar DV01, round-trip trading cost and parallel-shock P&L. Non-primary types, insufficient history and low policy relevance receive no rule-sized trade. Manual overrides remain labeled. Historical and forward tests stay one click away, including the negative H3 result. This tool does not add evidence of profitability.

## 32. The market leans to more hikes

*The Fed now*
**+81 bp**: 2-year Treasury minus the effective fed funds rate
- Target 3.75–4.00%
- EFFR 3.88%
- Next decision 28 October
- Latest vote 12–0
The 2-year sits 81 bp above the overnight rate
For the desk: Into the next decision, the curve prices more tightening than the overnight rate shows.
Source: New York Fed (EFFR, SOFR); FRED or U.S. Treasury (2-year); FOMC minutes (roster).

> This is the live Fed-now page. The band is the target range, the blue line is where overnight money trades, and the orange line is the 2-year. The gap between the last two is a rough read of where the market thinks policy is going.

## 33. No forecast gain from tone detected

*The next decision*
**0.63**: market-only in-sample R² across 142 decisions; pre-meeting 3-month and 2-year spreads over policy
- With Claude's tone: R² 0.64 (F-test p = 0.04)
- Forecasts from 2017: MSE 0.153 with tone, 0.149 without (p = 0.68)
- 79 forecasts, 30 of them moves
- Exploratory: added after the results
Exploratory expanding-window forecasts use only earlier decisions
For the desk: Adding tone does not reduce real-time forecast error in this sample; the test is exploratory.
Source: FOMC decisions and pre-meeting Treasury yields; evaluate/forecast.py.

> Does Claude's reading add to what the market already prices about the next decision? For each of the 142 decisions since 2009 we model the decision (cut, hold or hike) on the 3-month bill and 2-year over the policy rate at the last close before it, and on the tone of the latest minutes, the speeches of the previous 60 days and the previous statement. The market's lean alone explains 63%; tone adds a little in sample. In real time, forecasting every decision from 2017 with only earlier data, adding tone does not lower the error. We added this test after the results, so treat it as exploratory.

## 34. Market predictors and the next decision

*Next decision, exploratory*
**R² 0.63**: from the 3-month bill and 2-year over the policy rate alone, 142 decisions
- Decision coded −1, 0, +1; linear model, HC1 errors
- Inputs per standard deviation; all strictly before the decision day
- Expanding window: each of 79 forecasts uses only earlier decisions
| Input | Per SD | t | p |
|---|---|---|---|
| 3-month bill over the policy rate | +0.303 | 6.70 | < 0.001 |
| 2-year over the policy rate | +0.077 | 2.24 | 0.025 |
| Tone of the latest minutes | +0.061 | 1.19 | 0.234 |
| Tone of speeches, last 60 days | −0.078 | −1.41 | 0.160 |
| Tone of the previous statement | +0.063 | 1.35 | 0.176 |
| R², market alone → with tone | 0.625 → 0.644 |  |  |
| F-test of the three tone terms | F = 2.82 |  | 0.041 |
| Real-time MSE from 2017: tone + market vs market | 0.153 vs 0.149 |  | 0.68 |
No reduction in real-time forecast error from tone
Source: evaluate/forecast.py.

> Each decision since 2009 is modeled on the market's lean the evening before and on the tone of the latest minutes, recent speeches and the previous statement. In sample the tone terms are jointly significant at the 5% level; R² is 0.625 for the market and 0.644 with tone. Forecasting each decision from 2017 with only earlier data, adding tone does not lower the error. For the desk: Adding tone does not lower real-time forecast error in this sample; this result is exploratory.

## 35. After the freeze, nothing is re-fit

*Forward test*
**4**: frozen 2-year rules, one per document type, written on 2026-10-21
- No release scored since the 2026-10-21 freeze yet
- The pre-registered trade: +0.0 bp over 2 trading days
- A one-sided binomial test from 10 releases; no verdict before a year
| Type | Reads | bp per SD | t | q |
|---|---|---|---|---|
| Minutes | change in tone | +0.93 | 2.98 | 0.036 |
| Press conferences | change in tone | +3.87 | 3.90 | 0.007 |
| Speeches | tone | +0.85 | 3.25 | 0.029 |
| Statements | Claude's comparison with the last decision | +1.96 | 2.97 | 0.036 |
The same rules run on new data only, as it is collected
For the desk: Rules and coefficients were frozen before these releases; no post-freeze refitting.
Source: evaluate/forward.py; data/forward/rules.json.

> On 21 October 2026 the research was frozen. For each document type the strongest surviving 2-year relationship was written to a file with its coefficient and the in-sample mean and SD of its tone measure. Every evening each new release gets a predicted move beside its actual one, and the pre-registered trade runs through the backtest's own code, counted from the first close after the freeze.

## 36. Ten stages, one store, three ways in

*Architecture*
- Sources: Federal Reserve; FRED and U.S. Treasury; New York Fed; Yahoo Finance; Trillion Dollar Words
- Pipeline: collect (1,509 documents) → market (4,707 yield days) → events (1,509 windows) → baselines (3 simpler readers) → Claude (1,509 documents scored) → audit (masking and invariance) → evaluate (1,213 regressions) → backtest (116 variants) → forecast (the next decision, exploratory) → forward (the frozen rules on new data)
- Store: 20 tables, schema v4; FTS5 search over 4.5M words; 6,178 scores
- Ways in: Command line (fomc run, llm-*, slides); REST API (36 endpoints, ETags on reads); Dashboard (live demo, no build step)
Five public sources feed a pipeline that writes a single SQLite store
Source: Project code in src/fomc/ (Python 3.12, SQLite, FastAPI, ECharts), deployed on Cloud Run.

> The architecture in one picture. Five public sources feed ten pipeline stages. Every stage writes to a single SQLite store, and three front doors read it: the command line that runs the research, a REST API, and the dashboard, deployed as a read-only demo. Why it matters: Stages talk only through the store, so each can be rerun, tested or replaced on its own.

## 37. Ten stages, one SQLite store

*Store and pipeline*
| Stage | Reads | Writes | Skipped when |
|---|---|---|---|
| collect | Fed calendar and pages, cached by URL | documents, full-text index, committee | never: always runs |
| market | FRED (Treasury fallback), Yahoo, New York Fed | yields, etf_prices, policy_rates | once a day |
| events | documents, yields, ETF closes | events, decisions | inputs unchanged |
| baselines | texts, labels, saved readers | scores, validity | texts, code, records unchanged |
| llm-sync | data/llm/*.json | llm_records, scores | records unchanged |
| audit | masked, repeated and re-read records | meta.audit | records unchanged |
| evaluate | scores, events, yields | event_study, event_curves | frozen since the freeze |
| backtest | scores, events, ETF closes | backtests, backtest_curves | frozen |
| forecast | scores, decisions, yields | meta.forecast | frozen |
| forward | the same, after the freeze | meta.forward | inputs unchanged |
Stages talk only through the store and rerun only when their inputs change
Source: db.py, store.py and cli.py.

> fomc run walks ten stages in order. Each stage's inputs are hashed, files, code and the parts of the settings it reads, and the stage is skipped when the hash matches the last run. Since the freeze the research stages are skipped regardless, unless asked to unfreeze. Full-text search is an FTS5 index over the documents table without duplicating text. The store: 20 tables, schema v4 with automatic migrations; every stage run is logged in pipeline_runs.

## 38. One read-only API serves everything

*Serving*
- **36** JSON endpoints; reads revalidate by ETag, a 304 when unchanged
- **/feed.xml** Atom feed: lean, percentile and the Fed's words for each new document
- **0** build steps: vanilla JavaScript, ECharts, self-hosted fonts and icons
- **Reproduce** make setup, make demo-data, then make serve. The supplied snapshot needs no API key.
- **One story** Introduction and technical detail; PDF and editable PowerPoint exports
- **1,601** source files cached by URL, so nothing is downloaded twice
Read-only and keyless: dashboard, unified story, feed and exports
Source: api.py and web/app.js.

> FastAPI serves 36 JSON endpoints; every read carries a validator, so an unchanged response costs a 304. The front end has no build step. The deck is rendered by parallel headless Chrome into one unified story with PDF and editable PowerPoint exports. An Atom feed gives each new document with its reading. Security: The hosted app holds no key: settings, scoring and labeling are locked by FOMC_PUBLIC=1.

## 39. Automated refresh and spending guards

*Deployment and operations*
1. **Trigger** Configured: 7:30 p.m. ET daily; 2:25 p.m. ET on release afternoons; every main push
2. **Refresh** documents and prices; Claude on what is new, at most 40 jobs and 5 USD a month
3. **Build** keyless sign-in (workload identity federation); Cloud Build to Artifact Registry
4. **Serve** Cloud Run, 1 vCPU, 1 GiB, 0 to 3 instances, warm by a free ping; fedtone.web.app
5. **Guard** fomc doctor --strict: statements, minutes, prices and readings must keep arriving
6. **Cap** a 1 USD budget unlinks billing through Pub/Sub and a function
Configured schedules, spending caps and checks for missing data
Source: .github/workflows/refresh.yml; docs/OPERATIONS.md.

> A workflow is configured for every evening and the afternoon of a statement or minutes, after a fifteen-second check. It refreshes data, scores what is new under the caps, runs the forward test, then signs in to Google Cloud without a key and rolls out a new revision. A strict check fails the run if a scheduled release never arrives. The service scales to zero, kept warm by a free scheduler ping. These are configured controls; verify the workflow and cloud build's terminal state before treating a refresh as successful. Operations: A refresh that stops bringing things in fails loudly: GitHub emails the owner.

## 40. 132 offline tests, no model calls

*Tests*
**132**: tests that pytest collects in this revision; none needs a key or calls a model
- Locked versions in requirements.lock, one file for every OS
- A guard keeps the research stack out of the hosted image
- Lint and a front-end check run beside the tests
| Suite | Tests | Guards |
|---|---|---|
| duration | 37 | duration sizing, prior-only signals, source badges, input checks |
| store_api | 32 | store, migrations, API, public mode, feed, the decks |
| research | 16 | decisions, false discovery, PSR and DSR, event panels |
| ops | 8 | release days, the monthly cap, drift, the strict check |
| submission | 8 | the code archive, the four deliverables, this test count |
| timing | 8 | release windows, holidays, entries that earn only later |
| text_and_scoring | 7 | cleaning, sentences, dictionary signs, quote checks |
| finetune | 4 | fine-tuning bookkeeping, without PyTorch |
| members | 4 | quoted biographies, shifts in tone, what changed |
| scorer_offline | 4 | the scoring engine against a stub client, no key |
| forward | 3 | the freeze: returns after it only, rules that cannot move |
| forecast | 1 | the next-decision inputs never look ahead |
Checks cover timing, scoring, statistics, the API, operations and delivery
Source: pytest collection of this revision (src/fomc/test_inventory.json).

> 132 tests run offline on this revision. The duration tests check the sizing identities, prior-only signals and input validation. The timing suite holds the no-look-ahead rules. The scoring engine is tested against a stub client, so the suite never spends money. The research tests check Benjamini-Hochberg against statsmodels and the Sharpe statistics. The operations tests cover the release-day check, the cap, drift and the strict freshness check. For the desk: The rules that make a result trustworthy, like no look-ahead, are tests, not intentions.

## 41. A dashboard a rates desk could open every morning

*The product*
Source documents, clearer comparisons and a linked duration workspace
Source: fedtone.web.app (read-only demo).

> This is the product: a home page with the Fed pulse and the four findings, the Fed-now pages with rates, the Committee (click a member for their background, the tone of every speech and their dissents) and every decision redlined, and the research pages. It is live; we can switch to it now. Try it: Everything in this deck is one click away in the live app, with the source documents behind every number.

## 42. What we added beyond the brief

*Beyond topic 4*
- **RoBERTa** Fine-tuned on the same labels; a reference added after the results, outside H1
- **Forward test** Frozen coefficients and trading rules applied only to releases after the freeze
- **Monthly re-reads** The same anchor documents reveal changes in the model or scoring pipeline
- **Member timelines** Fed biographies, speech-tone turning points, titles and dissent histories
- **Atom feed** Subscribe to new releases, their tone and links to the Fed's source documents
- **Freeze guards** Research and baseline results stay fixed while new documents receive scores
- **Refresh and caps** Automatic collection and refresh, with spending limits and freshness checks
- **Shared store** The unified story and read-only dashboard read the same versioned store
Measurement checks, a forward test, and a system that keeps the evidence auditable
Source: Project code; docs/ASSIGNMENT.md.

> These additions extend the brief without changing the frozen H1 to H4 results. The trained transformer and forecast are exploratory references. The forward test uses new releases under fixed rules.

## 43. Topic 4 coverage and its limits

*Assignment coverage*
| Requirement | Delivered evidence | Boundary |
|---|---|---|
| Four Fed text types | 1,509 documents | Board speeches only |
| Claude rubric and evidence | 1,509 main readings | Recognition remains possible |
| Simpler text baselines | Dictionary, TF-IDF, embeddings | Public expert labels |
| Treasury curve test | 3m, 2y, 5y, 10y and 30y | Treasury fallback disclosed |
| Bond portfolio duration tilt | 116 variants, AGG / IEI | Fixed risk assumptions |
| Release-time backtest | Delayed entry, costs, placebos | Daily data, not ticks |
| Minutes, speeches and shifts | Primary and exploratory tests | No reliable H3 edge |
Seven functional requirements have evidence, with profitability reported honestly
Source: docs/ASSIGNMENT.md and docs/BRIEF_AUDIT.md.

> The seven components in the brief are implemented. A negative trading result does not mean the backtest is missing. The corpus covers the four requested document types. Claude scores have a defined rubric and evidence spans. Dictionary and sentence-embedding baselines share an expert-labeled test. Five Treasury tenors use the FRED series with an official Treasury fallback. AGG and IEI views expose the delayed duration tilt, including costs and multiple-testing controls. Daily windows respect public-release times but cannot identify minute-by-minute pricing. Minutes, speeches and statement shifts are all tested. Optional post-cutoff human annotation was not run and is not presented as completed.

## 44. Three things a rates desk can use

*Takeaways*
- **Higher agreement on public expert labels** Public-label macro-F1 0.66 against 0.58 for the best baseline without task-specific training (trained RoBERTa: 0.74); no post-cutoff human validation was run.
- **Tone accompanies release-window repricing** 26 of 198 exploratory release-window tests survive adjustment, 16 on Claude’s reading. Shared news and overlapping releases prevent a causal interpretation.
- **No delayed trading edge detected** The pre-registered trade has a Sharpe of −0.18 (placebo p = 0.28); no variant clears the luck hurdle.
What the evidence supports, and how to use it
Source: Project results, frozen 21 October 2026.

> Three takeaways. Claude outperforms the stated baselines on public expert sentences, with no task-specific training, but public-label exposure remains possible. Tone is associated with release-window yield changes. The tested delayed duration tilt does not beat chance; this does not prove full market pricing. For the desk: Use the evidence-linked index for inspection; the tested daily tilt does not establish an investable edge.

## 45. What would change our minds, and what we do next

*Limits and next steps*
- **Daily closes, not ticks** Release windows use the 3:30 p.m. Treasury fix; intraday data would sharpen the statement tests.
- **Small post-cutoff sample** 34 documents since the configured post-cutoff date, 2026-07-01; no independent human reference.
- **No post-cutoff human test** 150 sentences have model predictions. No post-cutoff human or cross-model validation was performed.
- **Public labels may be familiar** Expert labels may be in the model's training data. Masking dates and names partly addresses this risk.
H1 is supported on public expert labels; independent human validation remains absent
Next: Independent labels, intraday yields, and more frozen-rule releases would strengthen the evidence.
Source: docs/DESIGN.md (limitations); docs/PRODUCT_VALIDATION.md.

> Limits, stated plainly. We use daily closes; intraday data would sharpen the statement tests. The sample after the configured cutoff is still small. The post-cutoff human test was not run. H1 is supported on the public expert labels, which may have appeared in training. The masking audit only partly addresses that risk.

## 46. Thank you

*Final Project Group 2 · IEOR 4723, AI-Augmented Investment Management, Fall 2026*
Questions and discussion

> Thank you. Happy to take questions, or to open any page of the dashboard live. The code is public at github.com/flukier1016/fomc-tone-lab, with the same files as the submitted code ZIP.
