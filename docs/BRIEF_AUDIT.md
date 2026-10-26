# Topic 4 coverage audit

Read-only inspection of the frozen store on 25 October 2026. Functional coverage and positive research results are different questions.

| Requirement | Coverage | Evidence | Boundary |
|---|---|---|---|
| Fed corpus: four document types | Covered | {'minutes': 142, 'presser': 95, 'speech': 1123, 'statement': 149} | The speech corpus covers Board governors, not all Reserve Bank presidents. |
| Claude rubric with evidence spans | Covered | 1509 frozen-reader scores; 1669 verified level records | Evidence matching does not prove the absence of model memory. |
| Dictionary and embedding baselines | Covered | {'dictionary': 496, 'supervised': 496, 'embedding': 496} | Public expert labels may have been seen in training; post-cutoff human validation was not run. |
| Treasury yields across the curve | Covered | 4700 complete five-tenor dates; actual source: U.S. Treasury par yield curve | The official Treasury fallback replaces unavailable FRED downloads. Badges disclose the active provider. |
| Treasury / aggregate-bond duration tilt | Covered | 116 stored variants; AGG and IEI portfolio views | Fixed ETF durations are assumptions. The negative primary result remains part of the answer. |
| Public-release timing and executable delay | Covered | 1509 aligned delayed-entry windows | Daily closes respect release timing but do not measure minute-by-minute price discovery. |
| Minutes, speeches and statement tone shifts | Covered | 36 shift-signal variants; minutes+speech primary | No reliable delayed trading edge was found under the frozen rules. |

The primary Sharpe is -0.1849 and the placebo p-value 0.284. The tested trading rule is not supported. The test and negative result are implemented and reported.

The Duration section links document evidence and prior-only rule replay to exposure sizing, the frozen historical test and forward evaluation. Its custom scenario is a what-if illustration. No research stage was rerun.
