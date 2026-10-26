## What and why

<!-- One or two sentences. Screenshots for anything visible. -->

## How I checked it

- [ ] `make test lint` passes
- [ ] Looked at the change in the dashboard or the Story page (light and dark), if it is visible

## Research rules (tick what applies)

- [ ] Does not change results, or the changed numbers are explained above
- [ ] Respects the release windows (no look-ahead)
- [ ] Leaves the pre-registered H3 test as it was; new variants are exploratory
- [ ] A new model, prompt or data source has a new `RUBRIC_VERSION` or `--run-tag`
- [ ] No keys, `.env`, raw downloads or `data/fomc.db` in the diff
