# rag-pre-ingest: Build Spec (Python first)

## 1. Goal

An API-only, Document AI style service. Input: PDF, Word, Excel, or image. Output: clean markdown plus structured JSON with pages, typed blocks, bounding boxes, heading paths, confidence, and a source tag. No embeddings, no vector database, no LLM by default. A small Vite web app is included purely as a developer viewer.

## 2. Principles

- Read first. Extract text directly from the file by default. OCR only where a page or region needs it.
- Deterministic. Same file in, same output out. No randomness in the core path.
- Flag, don't lie. Wrong or uncertain output must be marked with warnings and confidence, never passed silently.
- Library rule: every Python library must have a usable Rust equivalent so a later port is a swap, not a redesign.
- Confidence scores are provisional until calibrated on real files. Do not build hard gates on them before that.
- Simple first. Build the read-only path end to end before adding any escalation layer.

## 3. Architecture

- FastAPI app: upload, job status, result endpoints, and static file serving for the viewer.
- Background worker: runs the pipeline off the request thread (start with FastAPI background tasks or a small queue like RQ).
- SQLite (built-in sqlite3, WAL mode): job state, file hashes, results metadata.
- File storage: local folder for uploads, extracted images, and result JSON.
- Viewer: Vite + React app, built to static files and served by FastAPI.

## 4. API

- POST /v1/documents: multipart upload. Returns 202 Accepted with job_id and status queued.
- GET /v1/jobs/{job_id}: status (queued, running, done, failed), current stage, progress, error reason.
- GET /v1/jobs/{job_id}/result: full result JSON.
- GET /v1/jobs/{job_id}/markdown: markdown only.
- GET /v1/jobs/{job_id}/pages/{n}/image: rendered page image for the viewer.
- GET /v1/jobs/{job_id}/events: server-sent events for live stage updates.
- Optional later: webhook_url on upload, called when the job finishes.
- Duplicate handling: if the exact file hash already exists, respond that the file already exists and do not ingest again.

## 5. Pipeline stages

1. Identify file type by sniffing bytes (filetype or python-magic), not the extension.
2. Hash the file (SHA-256). Exact match with an existing file means stop and report already exists.
3. Direct read, always runs on every page because it is nearly free: pypdfium2 for PDF (text plus coordinates and vector lines), python-docx for Word, openpyxl for Excel. Standalone images have no text layer, so they go straight to OCR.
4. Per-page quality checks, run in parallel with the direct read (details in 5a). Flag a page or region for OCR when any one check fires: near-empty text, garbage characters, image coverage, or text far below what the page area suggests. Pages with embedded images get the text read directly and only the image regions flagged.
5. Parallel OCR, only for flagged pages or regions, started as soon as the checks flag them and run concurrently with the direct read of other pages: RapidOCR (PaddleOCR models via ONNX). Render the page image with pypdfium2. Clean pages never touch OCR.
6. Layout and reading order: collect all blocks with bounding boxes. Single-column pages read top to bottom. Multi-column pages use XY-cut: full-width blocks act as dividers, then split by the widest vertical and horizontal gaps, read column by column. Attach small text under or beside an image as its caption. If no clean gaps are found, add a warning and mark the page low confidence.
7. Tables: use drawn ruling lines to build a grid where they exist; otherwise cluster words into rows and infer column edges from alignment. Keep blank cells as empty cells so columns never shift. Detect merged cells and record spans.
8. Strip repeating headers, footers, and page numbers (text repeated across pages in the same position).
9. Markdown sanitizer: heading levels from font size and weight, join broken line wraps, repair hyphenated words, normalize whitespace, render tables as markdown with every row having the same cell count.
10. Reconcile sources, then merge. Where the direct read and OCR cover the same region and agree, confidence is high. Where they disagree, keep the direct read if it passes the quality checks, otherwise keep OCR, and in both cases flag the region with a warning. Agreement raises confidence but does not prove correctness, so thresholds are validated on real files before being trusted. Then merge all blocks in page and reading order, compute confidence roll-ups, collect warnings, write markdown and JSON.

### 5a. Messy-page check: signals and starting thresholds

Measure these per page and decide whether the page goes to OCR. Starting cutoffs are guesses; tune them on about twenty real files by labelling each page fine or needs OCR and picking cutoffs that separate the groups. Principle: avoid the OCR route wherever reasonably possible, so cutoffs start strict and only clearly broken pages go to OCR. Tuning on real files then checks that no bad page slips through silently.

- Extracted character count: 5 characters or fewer means the page is effectively empty. A nearly empty page with no image is probably just short (title page, divider), so only treat it as OCR-needed when the image coverage signal also fires.
- Garbage character share: more than 1 percent replacement symbols, private-use glyphs, or broken-encoding characters means bad font encoding. Even a little garbage usually means the whole font mapping is broken.
- Image coverage: an image covering most of the page area means the text is likely in the picture.
- Words per page area: far below what a normal page holds means text is missing.
- Output per page: the measured values, the decision, and the reason, so the viewer can show why a page went to OCR.

### 5b. Markdown sanitizer: steps in order

Build each step as a small, separate, pure function with example inputs and outputs as tests, so changes never silently break other steps and the code ports to Rust cleanly.

1. Normalize text: fix odd Unicode, expand ligatures such as the fi symbol, replace non-breaking spaces.
2. Join broken lines inside paragraphs, keeping real breaks after headings and list items.
3. Repair words hyphenated across line breaks, without gluing together real hyphenated words.
4. Rebuild heading levels from font size and weight, ranked per document.
5. Normalize bullets and numbering into proper markdown lists.
6. Render tables with the same cell count in every row, blank cells kept.
7. Strip repeated headers, footers, and page numbers.
8. Collapse extra blank lines.

### 5c. Image handling: placeholders, accessibility, ingestion

The clean markdown is the source of truth for chunking and embedding, so it contains only real content: no markers, no placeholder text, no empty image syntax. Images are tracked in the JSON and in an optional annotated copy, never in the clean text.

- Every image gets a stable image block: id, page number, bbox, saved crop file, OCR text if any, caption if found nearby, and an empty description field.
- Clean markdown (default, used for ingestion and screen readers): image regions are omitted. If the image contains text, the OCR text appears as a normal paragraph tagged source ocr in the JSON. If the image has a nearby caption, the caption text appears as a plain paragraph.
- Annotated markdown (optional, separate output): each image is an HTML comment carrying its id, for example a comment reading image id img_p3_01. Comments render as nothing and screen readers skip them. This copy is for the viewer and debugging, never for ingestion.
- Later description step (opt-in, off by default): an optional vision model reads the saved crop and fills the block's description field. When enabled, the description is exported as alt text in the JSON and in annotated markdown, and is only added to the clean text if the user turns that on, so ingestion never silently gets model-written content.
- Chunking and embedding use only the clean markdown, plus the description field if the user opted in. Each chunk keeps source tags and heading_path, so a retrieved chunk can point back to its page and image.
- Decorative images (logos, rules, backgrounds) are detected by size and repetition across pages and marked as decorative, so they never get described and never appear in the clean text.
- Core service stays LLM-free: the vision step is a separate optional job that only touches image blocks.

### 5d. Input validation: checks before any processing

Every file passes these checks at upload, before a job starts. A failed check rejects the file immediately with a clear reason and a stable error code, so a bad file never reaches the pipeline. Anything that passes the door but fails mid-pipeline fails only that page or block, with a warning, never the whole job.

- Size limits: reject empty files (0 bytes) and files over a configured maximum size. Cap page count per document and image pixel dimensions to prevent decompression bombs.
- Type allowlist: only supported types (PDF, DOCX, XLSX, common image formats) are accepted. Type comes from sniffing bytes, and a mismatch with the extension is logged but the sniffed type wins.
- Structural integrity: PDF must have a valid header and open cleanly with pypdfium2. DOCX and XLSX are zip files, so test the archive opens, has the expected internal parts, and passes a compression-ratio check against zip bombs. Images must decode.
- Truncated or corrupted files: if the file opens but some pages fail to render or parse, keep the good pages, mark the failed ones with a corrupted_page warning, and set the job status to completed with warnings rather than failed.
- Unreadable results: if a file opens but yields no text and no OCR text on any page, finish the job with an empty_document warning instead of returning silent empty output.
- Unsafe content: ignore and never execute macros, embedded scripts, external links, or embedded files. Do not follow external references in DOCX or XLSX.
- Safe handling: save uploads under generated names, never the client-supplied file name, and reject path-like names. Process in a temporary working folder and clean it up when the job ends.
- Resource limits: a per-job time limit and per-page time limit. A page that exceeds it is skipped with a page_timeout warning and the job continues.
- Duplicate check order: validation runs first, then hashing, so a corrupted duplicate is rejected as corrupted rather than reported as already existing.
- Every rejection and warning is recorded on the job and visible in the viewer's warnings panel.

## 6. Output schema

Top level: document, stats, markdown, pages, warnings.

- document: id, file_name, file_type, file_hash, page_count, processed_at, confidence (average and lowest_block).
- stats: job summary counts, also returned by the job status endpoint. pages (total, read, ocr, mixed), images (total, decorative, with_ocr_text), tables (total, with_merged_cells), headings, paragraphs, lists, warnings (total and by code), duration_seconds.
- markdown: the full document as markdown.
- pages: page_number, width, height, method (read, ocr, or mixed), blocks in reading order.
- block: id, type (heading, paragraph, list, table, image, header, footer, other), level (headings), text, markdown, bbox [x0, y0, x1, y1] in page coordinates, heading_path (list of strings), confidence (nullable), source (read, ocr, caption).
- table block adds: rows, columns, cells (row, col, text, is_header, row_span, col_span).
- image block adds: image_ref (saved crop file path), ocr_text (nullable), caption (nullable), description (nullable, filled later by the optional vision step), is_decorative (boolean). Image blocks are excluded from the clean markdown.
- warnings: page_number, code (for example reading_order_uncertain, table_inconsistent, low_ocr_confidence), message.

## 7. Quality checks

- Word-count comparison between extracted text and the source page region. Large gaps raise a warning.
- Tables: every row has the same cell count; numeric columns mostly contain numbers; words inside the table match the source region.
- Where two methods read the same block and disagree, warn.
- Handwriting and other low-trust content are marked low confidence by default.

## 8. Viewer web app (Vite + React)

Served as static files by the same FastAPI server, calling the API directly.

- Top section: drag-and-drop upload, a list of recent jobs, live stage progress through server-sent events, and a clear message when a file already exists.
- Summary strip at the top of the results: the job stats as counts (pages, images, tables, headings, paragraphs, warnings) and how many pages were read directly versus sent to OCR.
- Bottom section, results, three panes:
  - Left: the original page image with colored boxes drawn over every block, colored by type and with a distinct style for OCR blocks and low-confidence blocks. Page navigation.
  - Middle: the block list in reading order with number badges. Hovering a block highlights its box on the page, and clicking a box scrolls to the block.
  - Right: tabs for rendered markdown, raw markdown, and raw JSON.
- Warnings panel listing flagged pages, clicking jumps to that page.
- Table view that shows the detected grid so blank and merged cells are visible.
- Debug toggles: show reading-order arrows, show only OCR blocks, show confidence heat.
- No database console needed; everything inspectable here.

## 9. Python to Rust library map

- File type sniffing: filetype or python-magic to the infer crate.
- PDF reading and page rendering: pypdfium2 to pdfium-render.
- Word: python-docx to docx-rs (least polished in Rust, expect extra work).
- Excel: openpyxl to calamine.
- OCR and layout models: RapidOCR with PaddleOCR ONNX models to oar-ocr, same models carry over.
- Layout, XY-cut, table grid, sanitizer: own code, port by rewriting.
- API: FastAPI to Axum.
- Job state: sqlite3 to rusqlite.

## 10. Milestones

1. Upload endpoint, job table, file type sniffing, hash dedup.
2. Direct reading for PDF, Word, Excel to raw blocks, plus markdown output.
3. Viewer app with page image, boxes, block list, markdown tab.
4. Per-page quality check and OCR fallback.
5. XY-cut reading order and caption attachment.
6. Table detection with blank and merged cell handling.
7. Header and footer stripping, sanitizer polish, warnings.
8. Test on about twenty real documents: clean PDFs, a two-column page, tables with blanks, a scan. Record where it fails.

## 11. Out of scope for now

- Embeddings, chunking, vector search, and any RAG answering.
- Web page URL ingestion (stretch goal later; fetched HTML would follow the same read-first path).
- Handwriting recognition and image captioning (optional vision model plug-in, off by default, only after calibration on real files).
- Confidence-gated multi-layer cascade: hold until confidence scores are shown to be reliable.
- Rust port: only after the Python version proves out on real files.
- Authentication, user accounts, and password-protected or encrypted file handling (encrypted files are rejected with a clear message). Detailed logging and metrics are optional for now.
- MCP wrapper over the OpenAPI spec so agents can call the service (possible later add-on).

## 12. Open decisions

- Score thresholds for the messy-page check (section 5a): starting values only, to be tuned on about twenty real files.
- Decided: Python first, then a Rust twin built from the same design.
