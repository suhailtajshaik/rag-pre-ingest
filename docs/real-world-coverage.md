# Real-world ingestion coverage

Research and execution date: October 25, 2026. Nine official public documents were
acquired and run through the current local pipeline, including actual OCR where
its routing required it. This small corpus is deliberately independent of our
synthetic examples. It does not establish that arbitrary input will work.

## Sources and reproduction

The [public corpus manifest](../tests/fixtures/public/manifest.json) contains source
URLs, source commit, license links, byte lengths and SHA-256 hashes. W3C originals
are pinned to a commit, and the IRS form is pinned by its recorded hash. Originals
and full extraction results remain in ignored local storage; the repository keeps
attribution, acquisition instructions and compact observations.

[Corpus instructions](../tests/fixtures/public/README.md) explain acquisition and
execution. [Observed results](../tests/fixtures/public/observations.json) are
machine-readable. Each document runs in an isolated subprocess with a 180-second
limit. A completed job is distinguished from content and structure correctness.

## Initial observations from actual documents

| Public document | Actual observation | Classification and next regression |
| --- | --- | --- |
| W3C complex table PDF | Detected one 5-row, 10-column table instead of the visual six-column grid; lost the two-tier header spans, leaving header words outside the table; emitted no warning. | Supported-input defect: multi-line merged headers, thin borders and cell-level word grouping. Require six columns and both row/column spans, with all header text retained inside the table. |
| W3C complex table DOCX | Correctly retained a six-column table and merged header spans in the stated checks. | Useful paired-source control: the PDF conversion, not the information itself, exposes the layout weakness. Numeric cell correctness still needs complete ground truth. |
| W3C two-column PDF | Completed and retained the document title. | Smoke check only. Title retention does not prove every paragraph's reading order. Add paragraph-level order labels before claiming real two-column accuracy. |
| W3C headings PDF | All three expected heading labels were classified as headings. | The stated heading check passes; overall semantic fidelity is not implied. |
| W3C headings DOCX | The third visual heading was emitted as body text and joined to its following paragraph. Its paragraph style is Normal, while its run is bold, 14 pt. | Supported-input gap: manual run-level formatting must feed heading inference. The source has weaker semantic markup, so a style-name-only reader cannot infer it. |
| W3C list PDF | Numbered items survived, but two bullet symbols detached from their item text. Only the third expected school name remained a list item. | Supported-input defect: separate marker/body PDF objects need geometric grouping. Add assertions for every list item, not merely one list block. |
| W3C language PDF | Internal font/object transitions produced split words in several ordinary sentences; text remained readable but incorrect. A table warning also appeared on prose. | Supported-input defect: join glyph runs by geometry before paragraph cleanup; avoid guessing dictionary repairs or converting prose to a table. Language metadata and reading direction are separate, currently unvalidated capabilities. |
| IRS blank Form W-9 | All six pages completed, but blank checkbox outlines were interpreted as empty one-cell tables, with many heading fragments and a table warning. | Supported-input layout weakness, not a successful form-semantics test. Checkbox/field decoration should not be mistaken for a data table. Actual interactive field-value extraction is not validated by a blank form. |
| Census state-population XLSX | The source has seven populated/merged logical columns but declares 36 columns due to empty formatting. The source includes a five-column year header and population integers. | Supported-input edge case: trim trailing style-only dimensions without dropping interior blanks, and retain numeric values plus header spans. Explicit seven-column regression added. |

These observations record the first public-data run. The final rerun below
confirms fixes for the stated table, word, list, Word-heading, checkbox and
spreadsheet-dimension assertions. Remaining unlabelled semantics are not covered
by that result. Future changes must rerun the public corpus and regenerate
`observations.json`; synthetic passes alone do not close real-document findings.

## Why these cases matter

W3C describes [reading order](https://www.w3.org/WAI/WCAG22/Techniques/pdf/PDF3)
as a relationship between logical document structure and visible content. A
geometric ordering heuristic cannot be assumed equivalent to authored structure,
especially around columns, footnotes, sidebars and interactive controls.

Its [table guidance](https://www.w3.org/WAI/WCAG22/Techniques/pdf/PDF6) explicitly
covers blank cells and row/column spans. These structural requirements make a
six-column table becoming ten columns a correctness failure, even when individual
words remain present. [Heading guidance](https://www.w3.org/WAI/WCAG22/Techniques/pdf/PDF9)
also distinguishes semantic heading tags from visual appearance. The current
pipeline should expose uncertainty when only formatting supports an inference.

[Form-field guidance](https://www.w3.org/WAI/WCAG21/Techniques/pdf/PDF12) covers
control roles and values that ordinary page text extraction does not necessarily
include. Do not equate a successful blank-form text read with filled-form support.

Microsoft's [SpreadsheetML formula documentation](https://learn.microsoft.com/en-us/office/open-xml/spreadsheet/working-with-formulas)
explains that the stored value can be a cached formula result. The current
`data_only=True` path therefore needs explicit tests for missing/stale caches;
a missing cached value must not silently masquerade as a genuinely blank cell.
Missing/stale formula caches remain a researched risk rather than a tested failure;
the acquired Census workbook instead exercises merged numeric headers and
style-only empty dimensions.

## Additional coverage before a broad robustness claim

1. Pair real PDF and DOCX versions: multi-row headers, rotated headers, multi-line
   cells, blank cells, nested tables, images inside cells and footnotes.
2. Add public XLSX examples with dates, percentages, custom display formats,
   formula caches, error cells, shared strings, hidden rows/sheets, sparse distant
   cells, charts and print areas. Decide whether to represent hidden content and
   formulas; do not execute formulas or follow external links.
3. Label real multi-column order, sidebars, page-wide headings, footnotes and
   equations separately. A title-presence assertion is insufficient.
4. Cover mixed scripts, right-to-left runs, combining marks, ligatures, vertical
   text, embedded subset fonts and missing Unicode mappings. Preserve exact source
   text or warn; OCR is not a universal language recovery mechanism.
5. Add permissioned low-resolution, skewed, rotated, low-contrast and mixed
   scan/digital pages. Handwriting recognition stays out of scope.
6. Test AcroForms, annotations, signatures and attachments without executing
   scripts or opening references. Define field-value expectations before adding
   schema behavior; attachments are never recursively ingested by default.
7. Exercise clipped/rotated crop boxes, nested form objects, embedded-image masks,
   partial corruption and resource limits on real exporters. Every recoverable
   page/block failure must remain a visible warning.

## Scope boundaries

Unsupported file types, passwords/encryption, handwriting recognition, URL
ingestion, embeddings, chunking, vector search, LLM answering and authentication
remain outside the agreed build. Public fixture acquisition does not add URL
ingestion to the app. Table/word/list failures in otherwise valid PDF and DOCX
uploads are within the supported path and should be fixed or visibly warned.

Downloaded material is credited to W3C and contributors or the IRS; no affiliation
or endorsement is implied. See the manifest and corpus instructions for source
and reuse details.

<!-- public-run:start -->

## Latest reproducible public-data check

9/9 documents satisfy their stated automated assertions.
This includes limited smoke checks and does not establish full semantic correctness.

| Document | Latest check |
| --- | --- |
| w3c-complex-table.pdf | Stated checks pass |
| w3c-complex-table.docx | Stated checks pass |
| w3c-two-columns.pdf | Stated checks pass |
| w3c-headings.pdf | Stated checks pass |
| w3c-headings.docx | Stated checks pass |
| w3c-lists.pdf | Stated checks pass |
| w3c-language.pdf | Stated checks pass |
| irs-w9.pdf | Stated checks pass |
| census-state-population.xlsx | Stated checks pass |

<!-- public-run:end -->
