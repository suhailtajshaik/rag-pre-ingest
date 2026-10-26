# rag-pre-ingest

A single-service, read-first document preparation app. Upload PDF, DOCX, XLSX, or supported images and inspect clean markdown plus structured JSON. Direct reading always runs; local OCR runs only on flagged pages or image regions. FastAPI serves the React viewer and automatic API documentation. No LLM, embeddings, chunking, vector search, authentication, or URL ingestion.

## Run locally with uv

Requires Python 3.12, Node.js 22.12+ and npm. From the repository root:

```sh
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements-dev.lock
uv pip install --no-deps -e .
cd viewer
npm ci
npm run build
cd ..
uv run --no-project uvicorn rag_pre_ingest.main:app --host 127.0.0.1 --port 8001
```

Open [the viewer](http://127.0.0.1:8001/), [Swagger](http://127.0.0.1:8001/docs), or [ReDoc](http://127.0.0.1:8001/redoc). Port 8001 avoids the existing service on port 8000 in the development workspace. Any free port works.

Stop with Ctrl+C. Leave the environment with `deactivate`. After changing backend code or configuration, restart the server. Add `--reload` for backend development, but expect reloads to interrupt and then recover active jobs. Rebuild the viewer after frontend changes. Use one server process; the local queue is designed for a single service instance.

## Standard Python virtual environment

Use this instead of the uv setup if preferred:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
cd viewer
npm ci
npm run build
cd ..
uvicorn rag_pre_ingest.main:app --host 127.0.0.1 --port 8001
```

For viewer development, `npm run dev` inside `viewer/` starts Vite; its development proxy forwards API calls to the backend. Production serves the built files from FastAPI.

## Docker

```sh
docker build -t suhailtaj/rag-pre-ingest .
docker run --rm -p 127.0.0.1:8001:8000 -v rag-pre-ingest-data:/data suhailtaj/rag-pre-ingest
```

The multi-stage build compiles the viewer, installs pinned Python dependencies and packages the backend. The final container runs as a non-root user. Uploads, SQLite WAL state, results, page previews, and crops live in the persistent data volume. Bundled RapidOCR ONNX models run locally without runtime model downloads or a remote OCR service.

## Use the viewer

Choose or drop a document. Upload feedback appears immediately, followed by live processing stage updates; polling provides a fallback if the event stream disconnects. The document list stays ordered by upload date when selection changes.

The result has three panes: continuously scrollable original pages with selectable block boxes, the active page's block list in reading order, and rendered markdown/raw markdown/JSON tabs. Scrolling the originals updates the active page; the page selector and navigation buttons scroll to that page. Inspect page-quality measurements, warnings, table grids, reading-order arrows, OCR blocks, and confidence shading. A confirmation dialog protects the delete action. Deletion cancels active processing and removes the document's upload, job, results, previews, and crops.

Duplicate uploads return the original job without processing again. Refreshing a completed job shows its saved result. To run the same document through a changed pipeline, delete its old job and upload it again.

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/documents` | Multipart `file`; 202 for a new job, 200 with `already_exists: true` for an exact duplicate |
| `GET /v1/jobs` | Recent jobs, newest uploads first |
| `GET /v1/jobs/{job_id}` | Status, current stage, progress, stats, warnings, and error |
| `GET /v1/jobs/{job_id}/events` | Server-sent progress events |
| `GET /v1/jobs/{job_id}/result` | Full document JSON |
| `GET /v1/jobs/{job_id}/markdown` | Clean ingestion markdown |
| `GET /v1/jobs/{job_id}/pages/{n}/image` | Cached rendered page preview |
| `GET /v1/jobs/{job_id}/images/{image_id}` | Extracted image crop |
| `DELETE /v1/jobs/{job_id}` | Cancel and remove the document; 204 on success |

```sh
curl -F 'file=@tests/fixtures/synthetic/01-clean.pdf' http://127.0.0.1:8001/v1/documents
curl http://127.0.0.1:8001/v1/jobs/JOB_ID
curl http://127.0.0.1:8001/v1/jobs/JOB_ID/result
curl http://127.0.0.1:8001/v1/jobs/JOB_ID/markdown
curl -N http://127.0.0.1:8001/v1/jobs/JOB_ID/events
curl -X DELETE http://127.0.0.1:8001/v1/jobs/JOB_ID
```

Jobs use `queued`, `running`, `done`, and `failed`. A completed job may contain warnings. Results not yet ready return 409. Errors consistently use `{"error":{"code":"empty_file","message":"..."}}`. Rejected uploads are recorded in a separate rejection audit table because they never become processing jobs.

## Configuration and safeguards

Configuration uses typed `RAG_...` environment variables with safe defaults. See `.env.example`; export the variables explicitly, because the app does not auto-load `.env` files.

Defaults: 50 MiB uploads, 500 PDF pages/image frames/Excel worksheets, 40 million image pixels, 100:1 ZIP expansion ratio, 200 MiB uncompressed archive content, 30 seconds per page/region, 300 seconds per job, and two concurrent OCR workers. Multipart request bodies are capped at the upload limit plus 64 KiB overhead before parsing.

OCR starting thresholds are configurable: at most five characters for near-empty text, garbage share above 1%, image coverage of 80%, and fewer than two words per 100,000 page-area units when images are present. Embedded images are considered as regions independently. Damaged text uses its own block bounds; high image coverage does not send good text outside that image to OCR. OCR inputs narrower than 1260 pixels are enlarged within the pixel cap; that setting improved small text in the supplied poster. Confidence is provisional and does not gate a cascade.

Validation precedes hashing: byte signatures determine type; mismatched extensions produce warnings. The service checks empty/oversized files, plain safe names, PDF opening/encryption/page count, Office ZIP integrity/required parts/expansion, and image decoding/dimensions/frame counts. Macros and embedded scripts are never executed; external Office relationships are not followed. Encrypted and legacy Office containers are rejected.

Per-page/block processing failures become warnings. Checkpoints preserve completed content if processing is interrupted or reaches its job limit. Missing OCR models/inference errors retain direct text and report warnings. Temporary request/job folders are cleaned on completion. Keep the data directory and temporary storage on suitably sized local disks.

## Architecture

Application folders live directly in `src/`: `api`, `services`, `pipeline`, `models`, and `storage`. Packaging maps `src/` to the required Python import name `rag_pre_ingest`.

Routes delegate to services. SQLite in WAL mode stores jobs and unique hashes. A background worker claims queued jobs and runs each in an isolated subprocess. Direct reads dispatch per-page quality checks and concurrent regional OCR. Pure layout, table, reconciliation, and sanitizer functions build the final output. The parent persists results and progress; shared publication/deletion locking prevents removed jobs from reappearing.

Python libraries follow the spec's Rust map: filetype/infer, pypdfium2/pdfium-render, python-docx/docx-rs, openpyxl/calamine, RapidOCR/oar-ocr, FastAPI/Axum, sqlite3/rusqlite. Supporting Uvicorn, multipart, and Pillow correspond to Tokio/Hyper, Axum multipart, and `image`. Runtime dependencies are pinned in generated lock files; setuptools supplies the packaging backend.

## Verification and fixtures

```sh
uv run --no-project pytest -q
uv run --no-project ruff check src tests scripts
uv run --no-project ruff format --check src tests scripts
uv run --no-project python scripts/check_types.py
cd viewer
npm test
npm run typecheck
npm run build
cd ..
uv run --no-project python scripts/calibrate_thresholds.py
uv run --no-project python scripts/evaluate_fixtures.py
uv run --no-project pre-commit install
```

With the virtual environment activated, each command can also run without `uv run --no-project`. The type-check helper exposes the flat source-to-package mapping to mypy through a temporary symlink; it does not duplicate source files.

- `tests/fixtures/synthetic/`: 29 generated files, including invalid uploads, plus a scenario manifest.
- `tests/fixtures/user_samples/`: supplied poster, mind map, palette, card grid, code screenshot, numbered questions, and multiline roles table PDF.
- `tests/fixtures/public/`: nine official public PDF, DOCX, and XLSX cases with pinned source hashes and attribution. Follow its README to download and evaluate; originals remain in an ignored cache.
- `scripts/generate_fixtures.py`: reproducible synthetic fixture generator.
- `docs/synthetic-calibration.md`: 144-setting threshold sweep with labeled development and held-out cases.
- `docs/fixture-evaluation.md`: actual full-pipeline corpus checks and remaining warnings.
- `docs/real-world-coverage.md`: public-document checks, initial defects, fixes, and researched but untested scenarios.

The installed Starlette emits a test-client HTTPX deprecation warning; the tests still run. No replacement HTTP library was added.

## Practical limits

Recognized Python-style code screenshots use local line crops to preserve indentation and punctuation in fenced markdown. They carry an `ocr_code_review` warning; parsing in regression tests never executes the extracted code. Uniform editor backgrounds are supported by this path, while other backgrounds retain the original OCR observations. Repeated card grids use corroborating header and action positions to keep each card's content together.

Visible neutral raster grids use cell-bounded OCR to keep adjacent values in their source columns. `RAG_OCR_TABLE_MAX_CELLS` caps this work (default 1024; zero disables it); `RAG_OCR_TABLE_TIMEOUT_SECONDS` limits optional cell reconstruction (default 10 seconds, also bounded by half the page timeout). If that budget expires, original OCR observations remain. Raster tables carry an `ocr_table_review` warning: text clipped by the original screenshot, overlays, faint rules, and merged raster cells remain review cases. Hidden or cropped content is never reconstructed from expected totals or product names.

The corpus tests establish the listed scenarios, not general real-document accuracy. Pure shapes may produce no OCR text. An arrowhead can resemble a letter such as X; isolated-character OCR is explicitly flagged for review rather than silently deleting possible real text. The owner requested synthetic documents in place of the original real-document calibration milestone; tuning on representative real files remains necessary.

Word pages and Excel worksheets use explicitly labeled synthetic previews and coordinates, not original print pagination. Tables, columns, captions, repeated margins, and decoration use deterministic geometry heuristics and report uncertainty. OCR extracts mind-map labels; it does not reconstruct semantic graph relationships. Complex layouts, scanned table boundaries, handwriting, and unseen scripts may need additional work; handwriting recognition remains out of scope. Confidence is uncalibrated.

An abrupt host failure between file publication and database commit can leave an unreferenced upload. Persistent storage should be backed up as a unit. Authentication and production hosting are outside this project's current scope; the default listener is local.

## Architecture diagram

Open `docs/architecture.excalidraw` in Excalidraw for the editable scene. `docs/architecture.svg` is the matching preview, with an explanation in `docs/architecture.md`. Regenerate with `python scripts/generate_architecture.py`.

### Layout evidence and accuracy evaluation

Each page retains frozen source observations and accepted regions. Derived blocks reference
those observations and carry explicit region ownership and merge locks. Geometry preparation
runs before final reading order; the final sanitizer cleans text without changing block geometry.
Recognition confidence remains separate from layout confidence. Existing result fields remain
available; these inspection fields are additive.

The fixture evaluator reports complete-transcription character and word error rates where a
reference exists, separately from scenario checks. The numbered-question and automation-workshop posters currently have
full references; other fixtures still use structural and selected-content checks. Pure scoring
helpers also cover reading order, grouping and exact cell assignments. The split manifest in
`tests/fixtures/ground_truth` explicitly records that no unseen real-document benchmark is
available yet. A passing scenario does not establish perfect OCR. New libraries and learned
layout models have not been added.

Clear arrows between repeated, filled flowchart step boxes are retained as a text sequence
and as `page.connectors` with pixel bounds, direction and source/target block references.
Detection requires shaft/head evidence and matching aligned boxes; decorative corners and
ambiguous shapes are excluded. This is conservative connector recovery, not general diagram
understanding. Original text and descriptions remain. Synthetic Office previews are excluded.
