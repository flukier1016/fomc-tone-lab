PY ?= .venv/bin/python
FOMC ?= .venv/bin/fomc

.DEFAULT_GOAL := help
help:  ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup:  ## create .venv with the locked versions (uses uv if present)
	@command -v uv >/dev/null && (uv venv -q -p 3.12 .venv && uv pip install -q -p $(PY) -r requirements.lock && uv pip install -q -p $(PY) -e . --no-deps) \
	 || (python3 -m venv .venv && $(PY) -m pip install -q -r requirements.lock && $(PY) -m pip install -q -e . --no-deps)

lock:  ## re-pin requirements.lock after editing requirements.txt (needs uv), then run make test
	@{ echo "# Exact versions of requirements.txt for every platform: what CI tests and make setup installs. Regenerate with make lock."; \
	  uv pip compile -q requirements.txt --universal --python-version 3.12 --no-header --no-annotate; } > requirements.lock

run:  ## free pipeline end to end (incremental: unchanged stages are skipped)
	$(FOMC) run

rerun:  ## force every stage to run again
	$(FOMC) run --force

serve:  ## dashboard at http://127.0.0.1:8000
	$(FOMC) serve

doctor:  ## check data, scores and API key
	$(FOMC) doctor --online

estimate:  ## Claude cost estimate (free)
	$(FOMC) llm-estimate

pilot:  ## score 8 documents with Claude (your key)
	$(FOMC) llm-pilot --n 8

test:  ## offline test suite
	$(PY) -m pytest -q

inventory:  ## record the test counts the deck shows (src/fomc/test_inventory.json); rerun after adding tests
	$(PY) scripts/test_inventory.py

lint:  ## ruff lint + format check
	.venv/bin/ruff check src tests scripts && .venv/bin/ruff format --check src tests scripts

snapshot:  ## compress the store for sharing (data/fomc.db.gz)
	$(FOMC) vacuum && gzip -kf9 data/fomc.db && ls -lh data/fomc.db.gz

deploy-snapshot:  ## refresh deploy/fomc.db.gz, the store shipped to the hosted dashboard
	$(FOMC) vacuum && gzip -c9 data/fomc.db > deploy/fomc.db.gz && ls -lh deploy/fomc.db.gz

deploy-cloudrun:  ## build and roll out the read-only dashboard on Google Cloud Run (setup: docs/DEPLOY.md)
	gcloud builds submit --config deploy/cloudbuild.yaml .

screenshots:  ## README images and the product slide (needs make serve running and Chrome)
	$(PY) scripts/screenshots.py

review:  ## headless captures of every page at four widths into qa/review, with overflow checks (needs Chrome)
	$(PY) scripts/review_pages.py

slides:  ## the Story as an editable PowerPoint in docs/slides (needs Chrome)
	$(FOMC) slides --out docs/slides

demo-data:  ## skip the 15-minute first run: unpack the shipped snapshot into data/fomc.db
	gunzip -c deploy/fomc.db.gz > data/fomc.db && $(FOMC) doctor

docker:  ## build the container image
	docker build -t fomc-tone .
