# Duration utility and engineering review

Reviewed locally on 25 October 2026. Research remains frozen on 21 October. No
research stage was rerun, no model was retrained and the existing infrastructure and budget configuration are retained.

## What is useful today

The product supports an auditable reading of Fed communication, comparisons with
Treasury moves and an honest record of the duration strategy. It does not establish
a profitable trading rule: the stored pre-registered H3 result has Sharpe -0.1849
and shuffled-score placebo p = 0.284. This result stays visible on the new tool.

Duration > Signal to exposure fills a different need: translating a user-selected
exposure into money and sensitivity. It accepts portfolio market value, modified
duration, desired duration change, an active-duration limit, a parallel yield shock
and trading cost. It reports capped exposure, dollar DV01, equal-dollar ETF legs,
gross traded notional, cost, cost break-even and stress P&L. It generates no signal
and writes nothing to the research store.

## Calculation and units

Let V be USD market value, D the starting duration and B the user's duration budget.
A document's rule gives dD = theta * B, as in the backtest, where one unit of signal
moves duration by the budget (|theta| <= 1, so B also bounds it); a manual change is
capped at +/- B. Let DL and DS be the assumed durations of the long and short instruments. In the shipped research assumptions, IEF is
7.1 years and SHY 1.9 years. These are fixed assumptions, not live estimates.

```text
before DV01      = V * D / 10,000                  USD per bp
active DV01      = V * dD / 10,000                 signed USD per bp
overlay weight  = dD / (DL - DS)
long leg        = V * overlay weight              signed USD
short leg       = -long leg                       signed USD
round-trip cost = 4 * abs(long leg) * cost_bp / 10,000   both legs, in and out
before P&L      = -before DV01 * yield_shock_bp
active net P&L  = -active DV01 * yield_shock_bp - round-trip cost
after net P&L   = before P&L + active net P&L
```

The relation between duration and basis-point value is described by
[CME's Treasury risk explanation](https://www.cmegroup.com/education/courses/introduction-to-treasuries/how-can-you-measure-risk-in-treasuries).
The shock axis uses numeric distances, so nonuniform shock steps do not make a
linear approximation appear curved.

For the default illustration, V = USD 1 million, D = 6, dD = -1 and cost = 1 bp per
leg. Duration becomes 5 years; DV01 falls from USD 600 to USD 500 per bp. The
illustrative legs sell USD 192,307.69 IEF and buy the same amount of SHY; entering
and leaving both legs costs USD 76.92, the charge the backtest makes for every change
of position. A +50 bp parallel move gives first-order portfolio P&L of USD -25,076.92
after that cost. This is a what-if example, not an executable portfolio allocation.

## Findings addressed

| Priority | Finding and correction | Location |
|---|---|---|
| P1 | A late curve response could overwrite a newer benchmark selection. Responses now carry a per-plot generation and require a connected chart node. Failures remove the obsolete curve and show an error. | `web/app.js`, `pages.backtest` |
| P1 | The router checked its generation after rendering, but an old renderer could already have overwritten the shared DOM. Each navigation now owns a separate render node, so obsolete renderers write to detached nodes. | `web/app.js`, `route` |
| P2 | Live tilt counted missing historical scores and hardcoded the 12-document minimum. It now drops missing values, reads the configured minimum and returns explicit active-duration years. | `api.py`, `live_score` |
| P2 | Reporting a non-finite input can itself fail JSON serialization. Validation errors now serialize safely and return 422. The new calculator rejects non-finite values, booleans, unexpected fields and out-of-range inputs. | `api.py`, `invalid_request`; `duration.py`, `ScenarioIn` |
| P2 | A curve bookmark with an invalid benchmark left the control state inconsistent. It now normalizes to Overlay. | `web/app.js`, `pages.backtest` |
| P2 | Second review: the user's budget only capped a document's rule, while the backtest sizes the rule by it (theta times the budget). The rule now scales with the budget, sent as `signal_theta`; a manual change is still capped. | `duration.py`, `scenario`; `web/app.js`, `pages.duration` |
| P2 | Second review: the new tests missed the same-type filter, same-day timestamps, the default document, the stored fallback string and the HTTP context and source endpoints; mutations of each passed. Tests now cover them, and each of 13 mutations fails the suite. | `tests/test_duration.py` |
| P3 | Costs covered entry only; the backtest charges every change of position. Costs are now a round trip, both legs in and out, which doubles the default cost and break-even. | `duration.py`, `scenario` |
| P3 | Same-minute releases of the same type are not history here, while the backtest's sort order may count one (6 of 672 primary signals, z within 0.032). The page now says so; history also requires an entry close, as in the backtest. | `duration.py`, `document_context` |
| P3 | Both yield badges showed the store date, and the Treasury link returned 404. Only the provider the stored yields came from is dated; the link opens the daily par yield curve. | `provenance.py` |

Positive controls retained: point-in-time timing tests, the frozen research guard,
public-mode write restrictions, provenance of model outputs, local key isolation,
cost-aware backtests and the existing light/dark visual system.

| Review dimension | Assessment |
|---|---|
| Correctness | Sizing identities, sign flips, costs, budget caps, zero exposure and valid-history minimums have offline regressions. Frozen research is compared before/after. |
| Security | Pure scenario POST needs no key or database; inputs are finite and bounded. Existing settings/scoring/label guards remain covered. No change to authentication or cloud settings. |
| Performance | Scenarios are constant-size arithmetic. Calculating a scenario does not clear the dashboard's GET cache or invoke an LLM. |
| Maintainability | Financial arithmetic is isolated in `duration.py`; the frontend consumes API calculations instead of duplicating formulas. |

## Verification

- `make test`, `make lint`, `node --check src/fomc/web/app.js`.
- `make review`: all pages at 390, 820, 1366 and 1920 pixels plus document/member drawers.
- `python scripts/check_duration_ui.py`: real local HTTP responses with deliberately
  delayed replies, edited-input invalidation, limit handling, zero exposure,
  invalid form inputs, failure recovery, navigation and benchmark races.
- Evidence and screenshots stay in ignored `qa/duration_audit/` and `qa/review/`.

## What to add next

1. **Timestamped instrument risk data.** Real ETF effective durations, convexity and
   their sources, with stale-data flags. Fixed research assumptions should not
   silently become live desk estimates.
2. **Holdings-aware feasibility.** Actual holdings, cash, permission to short and
   borrowing/financing assumptions. An equal-dollar spread has a negative leg;
   users need holdings to sell or shorting capacity. The current tool labels this
   execution limit beside the legs.
3. **Key-rate risk.** Instrument key-rate DV01 to evaluate curve twists. Do not
   invent key-rate exposures from a single aggregate duration or maturity label.
4. **Prospective evidence.** Accumulate the already-frozen forward test rather than
   optimize the historical rule after seeing the failed H3 result. Intraday data
   would be a separate, explicitly identified research extension.

Convexity, carry, credit-spread moves, FX, financing, margin and borrow availability
are outside the current linear scenario. The calculator is useful for sensitivity
and cost interpretation; it does not turn an unsupported signal into alpha.

## Document linkage and presentation update

A stored document now links directly to its prior-only replay under the frozen primary reader. The workspace exposes the earlier sample, standardized score, duration change, delayed entry and hold. Low-relevance readings, unsupported document types and insufficient history receive an explicit unavailable signal instead of an invented position. Manual overrides remain labeled. The single-document replay is not presented as the backtest's overlapping aggregate position.

The source badges distinguish FRED-series provenance from an active Treasury fallback. The committee uses compact rows, document timelines split by type with quarterly summaries, and pipeline phases expose details on demand. The presentation contains 46 slides, including this linkage and a seven-part assignment-coverage audit.
