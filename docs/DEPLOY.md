# Deployment

The public demo is **https://fedtone.web.app** (read-only): Google Cloud Run, setup below. The service's own address, https://fomc-tone-lab-4goy7yz73a-uk.a.run.app, works too. The same image also runs on Railway, **https://fomc-tone-lab-production.up.railway.app**, kept as a backup.

## Railway (backup)

| Piece | Where | What it does |
|---|---|---|
| Service | Railway project *FOMC Tone Lab*, service `fomc-tone-lab` | Builds from GitHub `flukier1016/fomc-tone-duration`, branch `main`; every push redeploys |
| Infrastructure as code | `.railway/railway.py` (Railway Python SDK) | Dockerfile path, health check, source repo; `railway config plan` / `railway config apply` |
| Image | `deploy/Dockerfile` | Serve-only dependencies (`requirements-serve.txt`), `uvicorn fomc.api:app` on `$PORT` |
| Data | `deploy/fomc.db.gz` | Vacuumed snapshot of the store, unpacked into the image at build time |
| Health | `GET /api/health` | Document count and mode; Railway waits for it before switching traffic |
| Story | `GET /api/story`, `/story` (opens `#/story`) | The 30-slide deck, built from the shipped store on request |

## Security model

The local app can write an API key and spend it; a public site must not. The image sets `FOMC_PUBLIC=1`, which:

- makes `POST /api/settings` and `POST /api/settings/check` return 403;
- turns off live scoring (`POST /api/score` returns 403) unless an access token is configured;
- makes the labeling endpoints (`POST /api/labels`, `POST /api/labels/undo`) return 403; the Team labels page shows the sentences and the agreement statistics read-only;
- never reports a key hint.

Optional environment variables on the service:

| Variable | Effect |
|---|---|
| `FOMC_BASIC_AUTH=user:password` | Require a login for every page and endpoint (health check excepted); use it to keep the demo to the team |
| `ANTHROPIC_API_KEY` + `FOMC_SCORE_TOKEN` | Enable live scoring with the owner's key, only for requests that send the token (the Score a text page shows a token field) |

On Cloud Run: `gcloud run services update fomc-tone-lab --region us-east4 --update-env-vars FOMC_BASIC_AUTH=team:...` (a key belongs in Secret Manager, passed with `--update-secrets`). On Railway: `railway variables set ...` or the dashboard, which stays the source of truth there.

Every response carries `X-Content-Type-Options`, `X-Frame-Options` and `Referrer-Policy` headers; responses over 1 KB are gzip-compressed.

## Refreshing the data

```bash
make run               # pull new documents and market data locally (incremental)
make deploy-snapshot   # vacuum and write deploy/fomc.db.gz
git add deploy/fomc.db.gz && git commit -m "Refresh data snapshot" && git push
```

Then `make deploy-cloudrun` rolls the new snapshot out on Cloud Run; Railway rebuilds on its own and switches over once `/api/health` answers. Claude scores, audits and team labels travel in the same snapshot, so the demo shows exactly what the deck shows; `make demo-data` unpacks the same file for a local copy.

## Operations (Railway)

```bash
railway status                    # service state and URL
railway logs                      # runtime logs (add --build for build logs)
railway deployment list           # history; redeploy or roll back from the dashboard
railway config plan               # what the IaC file would change
```

## Google Cloud Run

The same image runs on Cloud Run (project `fomc-tone-lab-2026`, region `us-east4`, service `fomc-tone-lab`). It scales to zero between visits, so a course demo stays inside the monthly free tier. A budget of 1 USD a month on the billing account (all projects, counting what would actually be charged) emails at 50%, 90% and 100%, and when the month is forecast to pass it. Past 100%, `deploy/billing_cap` (a Cloud Run function on the budget's Pub/Sub topic `billing-cap`) unlinks the project from billing, which stops every service until billing is linked again with `gcloud billing projects link fomc-tone-lab-2026 --billing-account BILLING`. Budget data trails usage by a few hours, so the cap holds the month near 1 USD rather than exactly at it.

| Piece | Setting |
|---|---|
| Build | `deploy/cloudbuild.yaml`: Cloud Build builds `deploy/Dockerfile`, pushes it to Artifact Registry (`us-east4-docker.pkg.dev/fomc-tone-lab-2026/fomc`) and deploys |
| Service | 1 vCPU, 1 GiB, 0 to 3 instances, 40 requests per instance, startup CPU boost, `FOMC_PUBLIC=1`, open to everyone |
| Upload | `.gcloudignore`: only `config/`, `src/`, `deploy/` and the requirements files leave the machine |
| Housekeeping | Artifact Registry keeps the two newest images; uploaded build sources are deleted after 7 days |
| Spending cap | `deploy/billing_cap/main.py`, deployed with `gcloud functions deploy billing-cap --gen2 --runtime python312 --region us-east4 --source deploy/billing_cap --entry-point cap --trigger-topic billing-cap --service-account billing-cap@fomc-tone-lab-2026.iam.gserviceaccount.com --set-env-vars CAP_PROJECT=fomc-tone-lab-2026`; its service account holds Project Billing Manager on the project and Cloud Run Invoker on the function (the Pub/Sub trigger runs as the same account). A message with the attribute `dry_run=true` checks it without changing anything: `gcloud pubsub topics publish billing-cap --message '{"costAmount": 1.5, "budgetAmount": 1.0}' --attribute dry_run=true` |
| Short address | `fedtone.web.app` is a Firebase Hosting site (`fedtone`) in the same project whose one rule rewrites every path to the service; it was set up once and needs no redeploy when the app changes |
| Warm instance | A Cloud Scheduler job, `keep-warm` (us-east4), requests `/api/health` every 10 minutes, so a visitor rarely meets the cold start (about 5 seconds to boot Python and the store). Idle instances cost nothing under request-based billing and one job is inside Scheduler's free tier; a minimum instance would cost about 10 USD a month and trip the cap. Remove with `gcloud scheduler jobs delete keep-warm --location us-east4` |

### Refreshed every evening, and on release afternoons

Paused since 25 October 2026: GitHub is not starting the account's Actions jobs (a billing notice). The workflow below is unchanged; see the status note in [OPERATIONS.md](OPERATIONS.md), and publish by hand meanwhile with its “Publishing by hand” steps, which refresh the data first so a release does not set it back.

`.github/workflows/refresh.yml` runs every evening after the 3:30 p.m. Treasury fix (23:30 UTC); at 2:25 p.m. New York time on a statement or minutes day (two weekday schedules, one per clock, each gated by `deploy/release_day.py`, which reads the decision dates in the shipped store with the standard library alone); on every push to `main` that touches the app; and by hand from the Actions tab. It starts from the shipped snapshot, pulls new Fed documents and market data (`fomc run --until audit`), scores what is new with Claude when the repository holds an `ANTHROPIC_API_KEY` secret (`fomc llm-update`: one request per new document or decision, never more than 40 in a run, and nothing more once a calendar month's direct calls cost `llm.monthly_cap_usd`, 5 USD), re-reads the eight anchor documents once a month (`fomc drift`), runs the forward test (`fomc forward`), commits the new Claude records, and rolls the demo out on Cloud Run. The research results stay as reported: the run stops after the audit stage, so the event study, the backtest and the next-decision test are not recomputed on new data. It signs in to Google Cloud without a stored key: workload identity federation lets only this repository's `main` branch act as `deployer@fomc-tone-lab-2026.iam.gserviceaccount.com`, which may submit builds and act as the build's service account, nothing more.

Set or replace the Claude key for scheduled runs (paste it at the prompt; it never appears in the repository):

```bash
gh secret set ANTHROPIC_API_KEY --repo flukier1016/fomc-tone-duration
```

Redeploy by hand (gcloud logged in, project `fomc-tone-lab-2026`), and look after the service:

```bash
make deploy-cloudrun                                                     # build and roll out (2 to 3 minutes)
gcloud run services logs read fomc-tone-lab --region us-east4 --limit 50  # recent logs
gcloud run revisions list --service fomc-tone-lab --region us-east4      # history; roll back with update-traffic
```

A new project needs this once (PROJECT, BILLING and the build service account are yours):

```bash
gcloud projects create PROJECT && gcloud billing projects link PROJECT --billing-account BILLING
gcloud config set project PROJECT
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
gcloud artifacts repositories create fomc --repository-format docker --location us-east4
SA=$(gcloud builds get-default-service-account --format 'value(serviceAccountEmail)' | sed 's|.*/||')
for r in run.admin iam.serviceAccountUser artifactregistry.writer logging.logWriter; do gcloud projects add-iam-policy-binding PROJECT --member serviceAccount:$SA --role roles/$r --condition None; done
```

## Running the same image elsewhere

```bash
docker build -f deploy/Dockerfile -t fomc-tone-demo .
docker run --rm -p 127.0.0.1:8000:8000 fomc-tone-demo
```
