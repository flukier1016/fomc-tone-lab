# Presentation design and rebuild

The 46-slide presentation uses the same frozen Story content in the browser, editable PowerPoint and PDF.
The redesign changes presentation, not research estimates, model records or labels.

## Visual system

- A fixed 1600 by 900 design grid, exported at the source PowerPoint's 13.333 by 7.5 inch dimensions.
- Two typefaces, each with one job. Georgia, regular weight, sets the slide titles and nothing else. Arial sets
  everything else: numbers (lining figures, bold for the headline statistic), text, tables, chart labels and the code
  and formula panels, whose columns are measured instead of relying on a monospace face. The browser presentation and
  its exported exhibits use the same two faces, and so does the dashboard, which marks the current tab, section and step
  with the same vermilion.
- Ink on warm paper with one accent: the vermilion of the logo's dot, `#C8401F`, marks the chapter number, the
  current progress segment, step numerals and the For the desk rule. Sources, kickers and page numbers use a darker
  gray than before so the small text stays legible. Data keep the application's reader, document-type and
  hawkish/dovish colors, which were checked for color-vision separation and contrast.
- The write-up PDF (`scripts/export_writeup.py`) reads the same theme: Georgia section headings, Arial for text,
  tables, code and paths, the section number in vermilion in its running header, and source lines styled like
  the slides' citation line.
- `scripts/deck_theme.json` holds the typefaces and colors; the export and finalize scripts read it, and
  `DECK_THEME=/path/to/candidate.json` renders a candidate theme for comparison without editing it.
- One shared title, subtitle, exhibit and citation grid. Large figures receive most of the page;
  supporting statistics use flat rules and text rather than repeated rounded cards.
- The five sections appear in the header and the bottom progress rule. Their first slides have a stronger header rule.
- The contents, course mapping, methods, evidence and limitations stay at their existing page positions.
  No divider slides were added.

PowerPoint tables, code, method steps, summary blocks and headlines are native editable objects.
Scientific plots and the more complex source exhibits are rendered from the application and kept as pictures.
Their values, axes, units, legends and limitations are preserved. Speaker notes retain the fuller methods and sources.

## Sources to edit

| Change | Source |
|---|---|
| Words, data or slide sequence | `src/fomc/story.py`, `story_technical.py`; numbers read the frozen store |
| Browser presentation grid and flat exhibit styles | The scoped `.editorial` block in `src/fomc/web/styles.css` |
| Browser cover, chapter header and progress rule | `slideHtml`, `storyChapter` and `storyRail` in `src/fomc/web/app.js` |
| Deck typefaces and colors | `scripts/deck_theme.json` (charts follow `html.presenting` in `styles.css`) |
| Editable PowerPoint geometry and tables | `scripts/export_presentation.mjs` |
| Source exhibits and Story JSON | `scripts/render_presentation.py` |
| Validated PowerPoint and page renders | `scripts/finalize_presentation.mjs` |

The dashboard styles outside Story are unchanged. The standard `fomc slides` exporter remains available
for content reproduction; use the workflow below to rebuild the reviewed editorial PowerPoint treatment.

## Rebuild the reviewed design

The editorial PowerPoint treatment needs a presentation runtime that is not part of this repository: the
`@oai/artifact-tool` package and validators bundled with the Codex desktop app. Set `RUNTIME_NODE_MODULES`,
`RUNTIME_NODE`, `RUNTIME_PYTHON` and `PRESENTATION_SKILL_DIR` to that runtime's Node, its modules, its Python and its
presentation skill folder. These are tool paths, not credentials. Without the runtime the same Story content is still
available: `make serve` shows it at `/story`, and `make slides` exports it in the standard design.

Use a new, empty ignored folder under `qa/` for each revision; the scripts take it as a required argument, and
finalization refuses to overwrite a validated deck. From the repository root:

```bash
.venv/bin/python scripts/render_presentation.py qa/presentation_export
"$RUNTIME_NODE" scripts/export_presentation.mjs qa/presentation_export
"$RUNTIME_NODE" scripts/finalize_presentation.mjs qa/presentation_export
# review every page in qa/presentation_export/rendered, then:
.venv/bin/python scripts/assemble_presentation.py qa/presentation_export --pdf /path/to/submission/FOMC-Tone-Lab.pdf
```

The renderer starts a temporary local server, reads the Story and captures exhibits headlessly.
The authorer makes a native editable draft. The finalizer checks slide count, dimensions, fonts and tables,
imports the draft again, renders every page, and creates the matching image PowerPoint.
No data pipeline, training job or model API is called.

The assembler writes both PowerPoints to `docs/slides/` with the deck's own title, authors and slide count in their
document properties, regenerates `outline.md` and `contact-sheet.jpg` there, and writes the page-image PDF, with a
bookmark for every slide, to the given path outside the repository. Keep PDFs and private QA captures out of tracked
source. Preserve the previous submission directory in its archive. Commit substantive source and PowerPoint changes
before running `scripts/package_submission.py`, so the submitted code ZIP is an exact committed revision.

Validation is structural plus rendered visual review. It does not claim that the file was opened in native PowerPoint.
Headlines are editable text boxes rather than PowerPoint title placeholders, so PowerPoint's outline view lists the
slides without titles; `docs/slides/outline.md` holds every title, number and speaker note as text.
