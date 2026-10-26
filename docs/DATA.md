# Data

## Sources

| Data | Source | Access | License |
|---|---|---|---|
| FOMC meeting calendar, statements, minutes | federalreserve.gov `fomccalendars.htm` (2021 onward) and `fomchistorical<year>.htm` | HTML | U.S. government work, public domain |
| Press conference transcripts | `federalreserve.gov/mediacenter/files/FOMCpresconf<date>.pdf` | PDF | public domain |
| Board speeches | `federalreserve.gov/json/ne-speeches.json`, then each speech page | JSON + HTML | public domain |
| Treasury yields, 3 months to 30 years | FRED `fredgraph.csv` (DGS3MO, DGS2, DGS5, DGS10, DGS30), the primary source | CSV | public data (Board of Governors H.15 via the St. Louis Fed) |
| Treasury par yields (fallback) | `home.treasury.gov` daily par yield curve CSV, by year: the series FRED republishes, used automatically when FRED is down | CSV | public domain |
| Bond ETFs (SHY, IEI, IEF, TLT, AGG) | Yahoo Finance via yfinance, dividend-adjusted closes | API | Yahoo terms; research use |
| Effective fed funds rate, SOFR | New York Fed reference-rate API (`markets.newyorkfed.org/api/rates`) | JSON | public |
| Human sentence labels | Hugging Face `gtfintechlab/fomc_communication` (Trillion Dollar Words) | CSV | CC BY-NC 4.0; evaluation only |
| Sentence-embedding model | `sentence-transformers/all-MiniLM-L6-v2` through fastembed (ONNX), cached under `data/raw/models/` | model files | Apache-2.0 |

## Counts (store built 2026-10-21)

| Type | Documents | First | Median words |
|---|---|---|---|
| Statements | 149 | Jan 2009 | 438 |
| Minutes | 142 | Jan 2009 meeting | 6,810 |
| Press conferences (Chair's words) | 95 | Apr 2011 | 6,350 |
| Board speeches | 1,123 | Jan 2009 | 2,517 |

In all 4.48 million words. Of the 149 statements, 143 announce a policy decision (21 hikes, 11 cuts, 111 holds); the other six are notices (swap lines, balance-sheet implementation, framework reviews).

Three speeches under 300 words are excluded (`note = 'under 300 words'`); speech-feed entries with no link (repeat deliveries of an earlier speech) are skipped.

## Release-time conventions (Eastern time)

| Type | Rule | Source of the time |
|---|---|---|
| Statement | Time printed in the document ("For release at 2:00 p.m. EST"); otherwise 2:15 p.m. before 2013 and 2:00 p.m. after | `document_text` for 93 statements, `default` for 56 older ones |
| Minutes | 2:00 p.m. on the release date printed on the calendar ("Released February 18, 2026") | calendar |
| Press conference | Information begins 2:30 p.m.; complete 3:30 p.m. | convention |
| Speech | Timestamp in the speech feed (from 2009); entries without a time are treated as 11:59 p.m. | `speech_json` |

Market closes: Treasury yields (FRED or the Treasury par curve, the same series) use quotes near 3:30 p.m.; ETFs close at 4:00 p.m. The store records which yield source the last run used (`meta.yield_source`, shown on the System › Data page); on 21 October 2026 FRED was down for maintenance, so the current store uses the Treasury par curve, and the next run tries FRED again.

## Cleaning

- Statements: the date line, release line and page header are removed; the text ends at the vote, dropping related links.
- Minutes: the attendance list is removed wherever it sits. Until mid-2024 it opened the minutes (the text starts at "Developments in Financial Markets" or "Staff Review of the Economic..."); since July 2024 it closes them, after the notation vote, and the text stops at "Attendance". The one-line notation vote approving the previous minutes is dropped; reports of intermeeting calls that follow it are kept, since they discuss policy.
- Speeches: header lines (date, title, speaker, venue) and the footnotes and references are removed.
- Transcripts: running headers, footers and page numbers are removed; only the Chair's turns are kept (the opening statement and the answers), one paragraph per turn. A speaker label is a name in capitals ("CHAIR POWELL.", "MICHELLE SMITH.") or the early transcripts' "QUESTION."; a lone capitalized word before a period ("CBS.", "PCE.") stays inside the running turn.
- Decisions: `policy.py` reads the target range quoted next to "target range" (quoted directives to the Desk are skipped) and derives the move from the change in the upper bound against the previous decision. Typography is normalized first: the Board's pages write "1‑1/4" with a non-breaking hyphen.

## Known quirks

- 2009 and 2010 statement links use `/newsevents/press/monetary/<date>a.htm`; 2005 and earlier use `/boarddocs/press/monetary/<year>/<date>/`. Both are parsed.
- The calendar page uses both `fomcpresconf` and `fomcpressconf` in links.
- The speech feed's titles contain HTML entities (`&#39;`); they are decoded at collection.
- From June 2026 the statement opens with the vote ("approved the following statement for release by a 12 - 0 vote") and was rewritten in a shorter format; the redline against the previous decision therefore shows a large change that month.

## Team labels

`fomc label-sample --n 150` draws sentences from documents released on or after the post-cutoff date (2026-07-01): stratified by document type in round robin, at most 40 sentences per statement, 15 per set of minutes or press conference and 4 per speech, 8 to 70 words, mentioning policy, the economy or prices, procedural lines (votes, staff titles) excluded. Each sentence is stored with the sentences before and after it as context. Labels are -1 dovish, 0 neutral, +1 hawkish, one row per sentence and annotator. Each label or undo also rewrites `data/labels/<annotator>.csv` (sentence hash, document, label, time, sentence); `fomc run`, `fomc serve` and `fomc label-report` load every file in that folder, matching sentences by their text, so labels made on four laptops meet in one store through git.

## Where data lives

| Path | Content | In git |
|---|---|---|
| `data/raw/<host>/<path>` | exact downloaded bytes | no |
| `data/interim/documents.csv`, `texts/` | document index and clean texts | no |
| `data/processed/` | market CSVs, event table | no |
| `data/fomc.db` | the SQLite store everything reads | no (share with `make snapshot`) |
| `data/llm/<model>/<rubric>/<mode>/*.json` | every Claude response with IDs and usage (2,049 records, plus `batches/` manifests; `shift_superseded/` keeps the eleven readings replaced when statements were re-paired) | **yes** |
| `data/labels/<annotator>.csv` | each teammate's labels on the post-cutoff sentences | **yes** |
| `data/baselines/roberta-tuned.json` | the RoBERTa fine-tuned here (`fomc finetune`): every setting tried on the five folds, the one chosen, the backbones' revisions, its labels for the test split and the team's sentences, and its document scores | **yes** |
| `data/baselines/fomc-roberta.json` | FOMC-RoBERTa's labels and document scores (`fomc roberta`), once its authors grant access | **yes** |
| `data/processed/roberta-tuned/` | the five fine-tuned models, half precision (about 3.5 GB) | no |
| `data/forward/rules.json` | the forward test as frozen on 21 October 2026: the trade with its reader, and per document type the 2-year rule with its coefficient and the in-sample mean and SD of its tone measure; written once | **yes** |
| `data/drift/anchors.json` | the eight anchor documents re-read every month; their readings sit under `data/llm/<model>/<rubric>/level_dYYYYMM/` | **yes** |
| `deploy/fomc.db.gz` | the vacuumed store shipped to the live demo; `make demo-data` unpacks it locally | **yes** |
| `docs/slides/` | the deck as PowerPoint, outline and contact sheet (`make slides`) | **yes** |

## The Committee

`fed.committee` reads the attendance list of the latest minutes (voting members, alternates, other presidents), the Reserve Bank of each president from the minutes' own "President of the Federal Reserve Bank of ..." lines over the past year, and Board titles from the speech feed. `fed.dissents` reads the "Voting against" sentence of every statement, each group of dissenters in it ("A, who preferred X; and B and C, who preferred Y"), and classifies what each preferred (hike, cut, no change, other), keeping the statement's own words. Nothing is entered by hand.

Each member's background is quoted, not written: `fed.bios` opens the page the Fed's FOMC page links for the member (a Board biography, or the Reserve Bank's page, followed to the Bank's own biography where the Board's stops at "Read more") and keeps up to four sentences verbatim: when the member took office or joined the Board, a later title such as Vice Chair, what came before, and the degrees. They are stored in `meta` (`bios`) with their pages and the date read; a page that fails keeps the last copy. `members.py` builds the member view from these and the store: the titles under the member's speeches, their dissents, and the stretches of steady tone in their speeches (see DESIGN.md, Measurement).
