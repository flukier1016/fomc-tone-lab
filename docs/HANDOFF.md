# Handoff: start here

FOMC Tone Lab is Final Project Group 2’s project for IEOR 4723, AI-Augmented Investment Management (Fall 2026), topic 4: a central bank communication index and duration positioning. This page takes any of us from a fresh clone to presenting, and then to changing things.

**Team:** Genie Zhang, Hong-syuan Lin, Myron Pang, Weijun Situ. Anyone can pick up any open item below, and pull requests and direct commits are both welcome: see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Frozen research (21 October 2026)

Every line of the brief is built and has been run on the full data; [ASSIGNMENT.md](ASSIGNMENT.md) maps each one to code, a dashboard page and a slide.

| Part | State | Result |
|---|---|---|
| Corpus | done | 1,509 Fed documents since 2009, each stamped with its release minute: 149 statements, 142 minutes, 95 press conferences, 1,123 Board speeches |
| Claude scoring | done | Claude Opus 5.5, rubric v1, every document plus statement-to-statement shifts, test sentences, the audit and a test-retest run: 2,049 records in 7 Message Batches and 5 direct calls, no failures, $32.44 in all as of 21 October; mean per-document evidence-match share 99.96% |
| Baselines | done | dictionary, TF-IDF classifier, sentence embeddings (all-MiniLM-L6-v2); for reference, RoBERTa-large fine-tuned on the same labels (`fomc finetune`) |
| H1, measurement | done | macro-F1 0.661 for Claude against 0.578 for the best baseline on 496 expert-labeled sentences, a lead larger than chance (p = 0.004); re-scored in a separate batch, the same stance on 95% of 152 documents. For reference, the fine-tuned RoBERTa reaches 0.737 on the same sentences (above Claude, p < 0.001): a reference outside H1; Claude received no task-specific fine-tuning by the team |
| H2, information | done | 26 of 198 release-day tests survive Benjamini-Hochberg at q < 0.10, 16 of them on Claude’s reading; Claude adds to the TF-IDF tone; statement associations weaken without the overlapping press conference; daily windows limit attribution |
| H3, tradability (pre-registered) | done | Sharpe −0.18, placebo p = 0.28: no reliable edge in the tested delayed duration tilt (re-run once after a code review, disclosed in DESIGN.md) |
| H4, contamination | done | Claude dates 99% of masked statements, yet masked and raw scores agree (r = 0.99) |
| Team labels | **human test not run** | 150 post-cutoff sentences have Claude predictions. The optional cross-model check was skipped; it supplies no evidence for the submitted results |
| Deck | local delivery | One integrated 46-slide presentation, with introduction and technical content together; Story and PowerPoint sources are in `docs/slides/` |
| Live demo | read-only | <https://fedtone.web.app> (Google Cloud Run); verify the hosted asset revision after publication |

## Submission delivery (25 October 2026)

The default deck now has 46 slides integrating the introduction, research methods, results and technical
implementation and additions beyond the brief. A generated contents page, an explicit course mapping and a local RoBERTa training walkthrough make the sequence easier to follow. All four team members are named on the cover and closing slides. H1 wording states that public
expert labels support the result and that the post-cutoff human test was not run. `docs/WRITEUP.md`
is the seven-page report source.

The delivered decks use the reviewed editorial design: rebuild them with [PRESENTATION_DESIGN.md](PRESENTATION_DESIGN.md),
whose last step writes the decks to `docs/slides` and the presentation PDF to the submission folder. Do not run
`fomc slides --out docs/slides` for a delivery: that standard exporter replaces the editorial decks with the plain
design. Then, with every change committed and the previous package moved to `05_project/archive/`:

```bash
.venv/bin/python scripts/export_writeup.py --out /absolute/path/to/submission/FOMC-Tone-Lab-writeup.pdf
.venv/bin/python scripts/package_submission.py /absolute/path/to/submission --revision "$(git rev-parse HEAD)"
```

The packager refuses uncommitted tracked changes and an older code ZIP in the folder. The active package contains
four deliverables: the unified PDF, its editable PPTX, the write-up PDF and a code ZIP, plus `SUBMISSION.md` and
checksums. Legacy technical files are historical copies, not additional upload requirements. `git archive` leaves
out the internal agent notes (`AGENTS.md` and the two handoffs to coding agents).
The unified PDF and editable PPTX contain the same presentation. CourseWorks submission is performed
by a team member. The optional cross-model comparison has not been run.

The P1 interface pass is complete: labeled theme controls, balanced Fed indicators, interval plots,
tercile response panels, a forecast-difference pane, readable wide tables, phone disclosures and
committee rows, a filter-consistent document timeline, and updated deck comparisons. The active
press-conference colors are checked by `scripts/check_chart_colors.py`. Verification includes the
offline suite, lint, JavaScript syntax, four-width headless review and interactive headless probes.
Validity's lead, tuning-search and document-agreement panels now switch independently between Chart and Table.
Each view uses the same stored values, remembers its selection and supports sortable CSV tables. Missing member
tone now distinguishes the minimum of three eligible speeches in two years from Reserve Bank speech coverage;
collected-speech totals over twelve months are labeled separately.

The delivery source is maintained on `main`. Verify the hosted asset revision and APIs after publication; a push alone does not prove deployment.

### Local duration and API audit, 25 October

The independent Duration section links document evidence and prior-only rule replay to a user-selected duration change and
dollar DV01, equal-dollar ETF legs, cost and parallel-rate stress P&L. The fixed
duration assumptions and execution limits are explicit, and the stored negative
H3 result stays visible. The calculation makes no model call or research write.
Async navigation/benchmark races, non-finite validation errors and live-tilt
history counting/units were also hardened. See [DURATION_REVIEW.md](DURATION_REVIEW.md)
and `scripts/check_duration_ui.py`. These additions preserve the frozen research and existing infrastructure and budget configuration.

## 1. Get access

The working repository, `flukier1016/fomc-tone-duration`, is private, with CI and deployment wired to it; a public copy of the submitted files is at <https://github.com/flukier1016/fomc-tone-lab>. To work on the private one, post your GitHub username in the group chat and the owner adds you as a collaborator (Settings, Collaborators); you then have write access like everyone else.

```bash
git clone https://github.com/flukier1016/fomc-tone-duration.git
cd fomc-tone-duration
```

## 2. Run it in five minutes (no key, no downloads)

```bash
make setup       # .venv and dependencies (Python 3.12; uses uv when installed)
make demo-data   # unpack deploy/fomc.db.gz: the full store, every Claude score included
make serve       # http://127.0.0.1:8000
```

Nothing to install at all: on the repository page choose Code, Codespaces, Create. The container runs `make setup` and `make demo-data`; type `make serve` and open the forwarded port 8000.

Without `make`: `python3 -m venv .venv && .venv/bin/pip install -r requirements.lock && .venv/bin/pip install -e . --no-deps`, then `gunzip -c deploy/fomc.db.gz > data/fomc.db` and `.venv/bin/fomc serve`. On Windows, use WSL.

`make run` rebuilds everything from the public sources instead (about 15 minutes the first time, mostly downloads). Every Claude response is in git under `data/llm/`, so a rebuild reuses them and costs nothing.

## 3. Present it

- **Story page.** Open local `/story` (kept apart from the dashboard, which has no Present button): one 46-slide integrated deck computed from the store. `←` and `→` move, `F` goes full screen, `N` shows the speaker notes, `Esc` leaves. Each slide links to the page behind it (“Open in the app”).
- **PowerPoint.** `docs/slides/FOMC-Tone-Lab.pptx` shows every slide exactly as on screen, with speaker notes. `docs/slides/FOMC-Tone-Lab-editable.pptx` has titles, numbers and text as native text boxes and the charts as pictures, for anyone who wants to restyle. `docs/slides/outline.md` holds every slide’s words and notes for any other template.
- **Presenter view.** Press `V` in the Story (or the presentation button under the slide): a second window with the speaker notes in large type, the next slide and a timer. Put it on your laptop and the Story on the projector; either window moves both.
- **Rebuild reviewed exports.** [PRESENTATION_DESIGN.md](PRESENTATION_DESIGN.md) describes the editorial PowerPoint authoring and validation workflow. `make slides` remains the standard content export. Technical/all are explicit legacy views, not active submission requirements.

An optional four-speaker rehearsal split is orientation, data and rubric (slides 1 to 12); measurement, recognition and the index (13 to 23); event study, trading and prospective checks (24 to 35); implementation and the close (36 to 46). This is an optional speaking order, not a division of project ownership; the work was shared.

A five-minute live demo that also works on the hosted site:

1. **Home:** the Fed pulse, the last and next decision, what the market prices, and the four findings.
2. **Fed now:** the target range, where overnight money trades, the 2-year’s lean, the Committee; open Waller to show his background in the Fed’s words, his tone turning dovish in May 2024 and hawkish again in May 2026, and his dissents.
3. **Fed now › Decisions:** open 16 September 2026, show the redline against July and Claude’s highlighted evidence.
4. **Research › Event study:** the press-conference tone shift on the 2-year, then the response curves.
5. **Duration › Historical test:** the pre-registered row, its placebo and the luck hurdle.
6. **The deck** (`/story`): jump to the answers (slide 6) and the takeaways (slide 44).

## 4. Where things are

| To change | Look in |
|---|---|
| A slide’s words or numbers | `src/fomc/story.py` assembles the integrated deck; it reuses method and implementation slides from `story_technical.py` |
| A slide’s picture | `src/fomc/web/app.js` (the `story*` functions) and `styles.css` |
| A dashboard page | `src/fomc/web/app.js` (`pages.<name>`); its data comes from `src/fomc/api.py` |
| The rubric Claude follows | `src/fomc/llm/rubric.py`; any change bumps `RUBRIC_VERSION` |
| Baselines | `src/fomc/dictionary.py`, `supervised.py`, `embeddings.py` |
| Market data and event windows | `src/fomc/market.py`, `align.py` |
| Event study and backtest | `src/fomc/evaluate/` |
| Any tunable | `config/settings.yaml` |

[ARCHITECTURE.md](ARCHITECTURE.md) has the full map; [DESIGN.md](DESIGN.md) the research design.

## 5. Open work anyone can pick up

To take something, say so in the group chat or open a draft pull request, so two people do not do the same thing.

1. **The 150 post-cutoff sentences: optional future validation** (human test not run; cross-model check skipped for this delivery).
   - Completed 25 October: the post-cutoff human test is explicitly disclosed as not run; H1 stays "supported on the public expert labels (p = 0.004)", with the caveat that those labels may be in the model's training data, partly answered by the memorization audit (masked and raw scores agree, r = 0.99). ASSIGNMENT.md, DESIGN.md, the unified deck, README and dashboard now use this boundary.
   - A future optional check can have another provider's model (OpenAI or Gemini) label the 150 sentences: a key of our own in `.env` (never the course key), every raw response and message ID kept, the labels recorded as that model's labels and reported as cross-model agreement on the sampled sentences, never as team labels or evidence about people. Verify each provider's cutoff before claiming the text is unseen.
   - If anyone changes their mind, the hand-labeling tool still works: `make serve`, Research › Team labels, initials, then `D`, `N` or `H` per sentence (`U` undoes); labels go to `data/labels/<initials>.csv`. Even 50 sentences from one person is a real human check.
   - Completed: the additions list is current in ASSIGNMENT.md and slide 42. All four members are credited on the cover and close, with no separate allocation of their overlapping work.
2. **The 28 October decision scores itself.** The evening workflow (docs/DEPLOY.md) collects it and, once the repository holds an `ANTHROPIC_API_KEY` secret, scores it. By hand: after the statement is out, `make run` collects it. Scoring new documents needs your own key: `.venv/bin/fomc key set`, then `.venv/bin/fomc llm-submit --what level` and `.venv/bin/fomc llm-submit --what shift --types statement` (only documents without a valid record are sent; a statement costs a few cents). Collect each batch with the same flags it was submitted with: `.venv/bin/fomc llm-collect --what level --batch-id <id> --wait` and `.venv/bin/fomc llm-collect --what shift --types statement --batch-id <id> --wait`. Then `make run`, `make slides` and the deployment refresh below.
3. **Rehearse the talk** with the speaker split above; the notes under each slide are a starting script, not a requirement.
4. **Stretch ideas:** intraday Treasury data around statements (our windows use the 3:30 p.m. fix), a label-efficiency curve (how many hand labels RoBERTa needs to match Claude: refit `fomc finetune` on 250, 500 and 1,000 sentences), or a rubric v2 run as a separate experiment.

## 6. Rules that keep the results honest

- **No look-ahead bias.** A document can only explain prices fixed after it became public; `tests/test_timing.py` enforces it.
- **The pre-registered test stays as written.** H3 (Claude on minutes and speeches, entry after the first eligible close, five-day hold) was fixed before results; the disclosed code-correction rerun is documented in DESIGN.md. Other variants are welcome and are reported as exploratory, charged for the search by the deflated Sharpe ratio.
- **A new model or prompt is a new experiment.** Bump `RUBRIC_VERSION` or pass a new `--run-tag`; records land in their own folder and never overwrite earlier ones.
- **Keep provenance.** Never delete or edit files in `data/llm/`, and never present Claude’s labels as human ones.
- **Keys stay out of git.** Use `fomc key set` (it writes the git-ignored `.env`); never paste a key into code, issues or chat.

## 7. Deployment

The live demo, https://fedtone.web.app, runs on Google Cloud Run and is set up to refresh itself: a GitHub Actions workflow pulls new documents and market data every evening (and at 2:25 p.m. New York time on a statement or minutes afternoon), scores what is new with Claude under a 5 USD monthly cap, runs the forward test and redeploys; every push to `main` that touches the app does the same. Since 25 October 2026 GitHub has not started the account's Actions jobs (a billing notice), so these runs are paused and the site is published by hand; see the status note in [OPERATIONS.md](OPERATIONS.md). To ship a store rebuilt locally:

```bash
make run && make deploy-snapshot   # rebuild, then write deploy/fomc.db.gz
git add deploy/fomc.db.gz && git commit -m "Refresh the demo data" && git push
```

Running it day to day, what it costs and what to do when a run fails: [OPERATIONS.md](OPERATIONS.md).

The hosted site is read-only: no key is stored there, and settings, live scoring and labeling are switched off. Details in [DEPLOY.md](DEPLOY.md).
