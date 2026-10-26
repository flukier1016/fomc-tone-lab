# Contributing

This is a four-person team project and everyone’s improvements are welcome: a fixed typo, a sharper slide title, a new chart, a better baseline, a bug report. Pull requests and direct commits are both fine; the only gate is that CI stays green.

New here? Start with [docs/HANDOFF.md](docs/HANDOFF.md): it gets you from a fresh clone to a running dashboard in five minutes.

## The short version

```bash
git switch -c your-topic          # e.g. labels-gz, slide-titles, fix-tracker-dates
# change things
make test lint                    # about 10 seconds, offline, no key needed
git commit -am "Sharpen the backtest slide title"
git push -u origin your-topic     # then open a pull request on GitHub
```

- **Small, safe changes** (docs, copy, styling, your own label file) can go straight to `main` if you prefer. CI runs on every push, and Railway redeploys the live demo from `main`, so check it builds first.
- **Anything that changes results** (rubric, data cleaning, event windows, backtest rules) goes through a pull request so the others can see it before it lands. Merge it yourself once CI is green; nobody needs to sign off, but say in the chat that it is there.
- **Not sure how?** Open an issue or a draft pull request with a question. Half-finished work is welcome as a draft.

## What CI checks

GitHub Actions (`.github/workflows/ci.yml`) runs on every push and pull request:

| Check | Locally |
|---|---|
| Ruff lint and format | `make lint` (fix with `.venv/bin/ruff format src tests`) |
| 51 offline tests: look-ahead rules, scoring engine with a stub client, research layer, store, API, hosted mode | `make test` |
| Front-end syntax and the icon sprite | `node --check src/fomc/web/app.js` |

The tests never call Claude and never need a key (`tests/conftest.py` removes any key for the run).

## Conventions

- **Numbers come from the store.** Slides, insights and README tables read the database; never type a result into a slide by hand. If a number changes, `make run` then `make slides` updates everything.
- **Every slide is a function** in `src/fomc/story.py` returning a title (a full sentence that says why), at most one big number, a takeaway line, a source line and speaker notes. Its picture is a `story*` function in `src/fomc/web/app.js`. Check it in the Story page and in both themes (`?theme=light` and `?theme=dark`).
- **The front end has no build step:** plain ES module, vendored ECharts, Lucide icons in one sprite (`scripts/build_icons.py` adds an icon).
- **The hosted image is small on purpose.** Anything `fomc.api` imports must run with `requirements-serve.txt` only; a test fails if the research stack, the embedding model or python-pptx is imported.
- **Python:** type hints where they help, functions over classes, a test for anything with a rule in it. Line length 120.
- **Dependencies:** add the package to `requirements.txt`, run `make lock` and `make test`, and commit both files; everyone then installs the same versions. A package the hosted API needs also goes in `requirements-serve.txt`.
- **Commits:** one topic per commit, an imperative subject line (“Add FinBERT baseline”), the reason in the body when it is not obvious.

## Research rules

These keep the results defensible; please follow them even for experiments.

1. **No look-ahead bias.** A document can only explain prices fixed after it became public. Use the windows in `events`; do not compute your own from release dates.
2. **The pre-registered test is fixed.** Do not change the H3 primary specification. Add variants instead; they are reported as exploratory and charged for the search (deflated Sharpe ratio).
3. **New model, prompt or data means a new experiment.** Bump `RUBRIC_VERSION` in `src/fomc/llm/rubric.py` or pass `--run-tag`; records go to a new folder under `data/llm/` and never overwrite earlier ones.
4. **Preserve provenance.** Do not edit or delete Claude records in `data/llm/` or anyone’s labels in `data/labels/`. Never relabel Claude’s output as human labels.
5. **Label independently.** Do your own labels before looking at anyone else’s file.
6. **Keys stay private.** Keys live in `.env` (git-ignored) or the environment. Never commit, print or paste one; review `git diff --cached` before committing.

## Where to add things

| You want to add | Do this |
|---|---|
| A baseline | A module with `score_documents` and sentence labels like `embeddings.py`; register it in `cmd_baselines` in `cli.py`; it then appears in the validity table, the event study and the backtest |
| An event-study outcome | `markets.fred_series` in `config/settings.yaml` and the outcome lists in `evaluate/event_study.py` |
| A backtest variant | `cmd_backtest` in `cli.py`; never flag it `is_primary` |
| A dashboard page | `pages.<name>` in `app.js` and a tab in its section in `NAV` (a new section also needs a link in `index.html`), an endpoint in `api.py` with a test |
| A slide | A builder in `story.py`, listed in `build()`; a `story*` renderer in `app.js` if it needs a new picture; rerun `make slides` |

## Data you should not commit

`.env`, `config/local.yaml`, `data/raw/`, `data/interim/`, `data/processed/` and `data/fomc.db` are git-ignored; `make demo-data` or `make run` recreates them. Do commit `data/llm/` (paid Claude responses), `data/labels/` (team labels), and `deploy/fomc.db.gz` when you refresh the live demo.
