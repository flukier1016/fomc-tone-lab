# Operations

How the system runs on its own after the course, what it costs, where to look, and what to do when something breaks. Setup is in [DEPLOY.md](DEPLOY.md); the research design in [DESIGN.md](DESIGN.md).

## What runs, and when

Everything below is one GitHub Actions workflow, `Refresh and deploy` (`.github/workflows/refresh.yml`), ending in a fresh deploy of https://fedtone.web.app.

**Status, 25 October 2026:** GitHub has not started this account's Actions jobs since 25 October, 03:53 UTC (each run stops within seconds with a billing notice), so neither the schedules below nor CI are running, and no new Fed document is collected. The workflows themselves are unchanged. The last scheduled refresh that ran finished on 25 October at 01:40 UTC (market data through 23 October). Hand releases with plain Cloud Build ship the committed snapshot, which stops at 20 October, so three later releases set the site back three trading days; on 26 October the site was refreshed by hand as described in “Publishing by hand” below, and that refreshed store (market data through 23 October, frozen tables unchanged) became the committed snapshot, so the slides, the code archive, fedtone.web.app and the Railway backup now show the same data. Once newer data exist, refresh before publishing again. Clearing the notice is an account decision (GitHub, Settings, Billing and plans); see the first row of “When something breaks”.

| When (New York time) | What runs |
|---|---|
| Every evening, 7:30 p.m. (6:30 p.m. in winter) | New Fed documents and market data; Claude scores what is new; this month's re-read of the anchor documents (once a month); the forward test; deploy |
| 2:25 p.m. on the day of a statement or of minutes | The same, so the reading is live within the hour. Two weekday schedules (daylight time and winter) first run `deploy/release_day.py`, which reads the decision dates in the shipped store and lets the refresh through only on a release afternoon |
| Every push to `main` that touches the app | The same |
| By hand | `gh workflow run refresh.yml` |

The research results stay as reported: the workflow stops after the audit stage, so the event study, the backtest and the next-decision test are never recomputed, and the baselines score only new documents, leaving the validity results as they were (a classifier retrained on the CI machine differs in the last digits and would otherwise rewrite them; `fomc baselines --unfreeze` recomputes them on purpose). What happens after the freeze (21 October 2026) is measured by the forward test, on rules written down once in `data/forward/rules.json`.

## What it costs, and the caps

| Item | Cap | Where it is set | A typical month |
|---|---|---|---|
| Claude: scheduled scoring and the monthly re-read | 5 USD of direct calls per calendar month, then nothing more is sent until the next month; at most 40 new jobs per run | `llm.monthly_cap_usd` in `config/settings.yaml`; `--max` in the workflow | about 1 USD: one meeting (statement, press conference, minutes), 15 to 25 speeches, 8 re-read documents |
| Google Cloud: Cloud Run, Cloud Build, Artifact Registry, Firebase Hosting, the `keep-warm` scheduler job | a 1 USD monthly budget; past it, billing is switched off for the project (`deploy/billing_cap/`) | the budget on the billing account | 0 USD: the service scales to zero and stays in the free tiers |
| GitHub Actions | the account's monthly minutes (2,000 on the free plan for this private working repository; the public copy runs only its tests) | | about 10 minutes per refresh, about 400 a month |

A backfill (weeks of new documents, a new model) goes through Message Batches at half price, started by hand after `fomc llm-estimate`, and does not count against the monthly cap.

## Where to look

| Question | Where |
|---|---|
| Is the site up, and how much does it hold? | `curl https://fedtone.web.app/api/health` |
| When did the data last change? | System › Data (“Data through …”), System › Pipeline (every stage run) |
| Did tonight's refresh work? | `gh run list --workflow refresh.yml`; a failed run also emails the repository owner. The last step, `fomc doctor --strict`, fails the run when a scheduled statement has not arrived by the next day, minutes three weeks on, market data within four business days, or a Claude reading of anything released three days ago (unless the month's cap explains it) |
| What did the Fed say today? | Home, or the feed `https://fedtone.web.app/feed.xml` in any feed reader (or forwarded by email) |
| Do the frozen findings hold on new data? | Research › Forward test |
| Has the reader changed? | Research › Validity › “Monthly re-read” |
| What did Claude cost this month? | the last lines of the “Score what is new with Claude” step |

## Publishing by hand while the schedule is paused

Plain `gcloud builds submit` ships `deploy/fomc.db.gz` as committed, which is older than what the scheduled refresh
would have served. To publish a release without setting the data back, do what the workflow does, in a separate copy
so the local store and the committed snapshot stay as they are:

```bash
W="$(mktemp -d)/refresh" && git worktree add --detach "$W" HEAD
mkdir -p "$W/data" && cp -c -R data/raw data/processed "$W/data/"     # copy-on-write clones of the download cache
gunzip -c deploy/fomc.db.gz > "$W/data/fomc.db"
PY="$PWD/.venv/bin/python"; cd "$W"; export PYTHONPATH="$W/src"          # every path now resolves inside the copy
"$PY" -m fomc run --until audit && "$PY" -m fomc forward && "$PY" -m fomc doctor
"$PY" -m fomc vacuum && gzip -c9 data/fomc.db > deploy/fomc.db.gz       # the copy's snapshot, never committed
gcloud builds submit --async --config deploy/cloudbuild.yaml --project fomc-tone-lab-2026 \
  --gcs-source-staging-dir gs://fomc-tone-lab-2026_cloudbuild/source .
cd - && git worktree remove --force "$W"
```

Before the build, compare the copy's store with the committed snapshot: `validity`, `event_study`, `event_curves`,
`backtests`, `backtest_curves`, `llm_records`, `labels`, `label_items` and `label_predictions` must be identical, and
`scores` may differ only in `updated_at`. The copy has no `.env`, so nothing is sent to Claude: a new document stays
unread until a run with the key scores it. After the build, check that `/api/system` reports the new
`yields_through` date and that the asset hash matches the code.

## When something breaks

| Symptom | Likely cause | What to do |
|---|---|---|
| Every run fails within seconds: “The job was not started because recent account payments have failed or your spending limit needs to be increased” | GitHub account billing: a failed payment, or the month's included minutes used up with a zero spending limit | Nothing in the repository to fix. The account owner clears it in GitHub's Billing and plans (included minutes reset each billing cycle); then rerun with `gh workflow run refresh.yml`. Until then publish by hand ([DEPLOY.md](DEPLOY.md)) and remember that new documents are not collected |
| The run fails at the last step, “Fail loudly …” | The site deployed, but something stopped arriving | Its log names what is missing. A statement or minutes: open the Fed's calendar page and compare with `collect.py`. Market data: FRED or Yahoo. Unread documents: the scoring step's log |
| The run fails at “New documents and market data” | The Fed changed a page layout; FRED is down | `gh run view <id> --log-failed`. FRED falls back to the Treasury's par curve on its own. For a layout change, fix the parser in `collect.py` or `textclean.py`, add the page to `tests/fixtures`, push |
| The run fails at scoring: “N new jobs, more than --max 40” | A backlog, for example after weeks without runs | Locally: `fomc llm-estimate`, then `fomc llm-submit` and `fomc llm-collect`; commit `data/llm` and push |
| The log says “reached the cap” | The month's Claude budget is spent | Nothing: the rest waits for the next month. Raise `llm.monthly_cap_usd` if the month is unusual |
| Validity shows “Drifted” | The model behind the name changed, or the cleaning or the prompt did | Do not mix readings: start a new experiment identity (a new model or `RUBRIC_VERSION`), re-score as a batch, compare on Validity; the forward test keeps its frozen reader |
| The site is down and billing is off | The 1 USD cap fired | Read the spend in the console, then `gcloud billing projects link fomc-tone-lab-2026 --billing-account <account>` and rerun the workflow |
| The run fails at Google sign-in | The workload identity pool or the deployer account changed | Check the provider and service account named in the workflow against DEPLOY.md |

## Changing the reader

A new Claude model or a changed rubric is a new experiment identity: its records go to a new path, `data/llm/<model>/<rubric>/`, and never overwrite the old ones. Estimate (`fomc llm-estimate --model …`), pilot eight documents (`fomc llm-pilot`), submit the batch, collect, sync, and compare the two readers on Validity before switching the default in `config/settings.yaml`. The frozen research and the forward test keep reading `llm:claude-opus-5-5:v1`.

## Keys

| Key | Lives in | Rotate |
|---|---|---|
| Anthropic API key | the GitHub secret `ANTHROPIC_API_KEY`; locally the git-ignored `.env` (`fomc key set`) | create a new key in the Anthropic console, `gh secret set ANTHROPIC_API_KEY` and `fomc key set`, then revoke the old one |
| Google Cloud | no key: GitHub signs in through workload identity federation as the deployer service account | |
| Hugging Face | only for FOMC-RoBERTa, in `~/.cache/huggingface` on the laptop that runs it | `hf auth logout`, then a new token |

The hosted site never holds a key (`FOMC_PUBLIC=1`).

## Running it locally

```bash
make demo-data      # the shipped store, without the 15-minute first run
make serve          # the dashboard at http://127.0.0.1:8000
make run            # everything new since the store was built, incrementally
```

After the freeze, `fomc run` leaves the event study, the backtest and the next-decision test as reported and says so (`frozen as reported, skipped`); `fomc run --unfreeze` recomputes them on the new data, which changes every number quoted in the README, the docs and the deck, so treat it as a new edition of the research, not a refresh.

`fomc slides --pdf DIR` also writes each deck as a PDF in DIR, page for page as on screen (the pages are images); the PDFs stay out of the repository.

The fine-tuned RoBERTa runs offline in its own environment (`pip install -e .[roberta]`): `fomc finetune` (hours on a laptop; resumes where it stopped), then `fomc baselines`. Its weights stay in `data/processed/roberta-tuned/`, out of git; `fomc finetune --team` labels new team sentences with them.

## Backups

- Everything that cost money, every Claude record, is in git (`data/llm/`); a lost store is rebuilt with `fomc run` without paying again.
- A copy of the site runs on Railway (https://fomc-tone-lab-production.up.railway.app) when Railway's builds work; see DEPLOY.md.
