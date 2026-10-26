# rag-pre-ingest architecture

[Editable Excalidraw scene](architecture.excalidraw) · [SVG preview](architecture.svg)

Open the `.excalidraw` file in Excalidraw using **Open** or drag it onto the canvas. Every box,
arrow and text label is editable. The SVG is a matching static preview.

The FastAPI service serves the React viewer and Swagger documentation. Upload validation
precedes hashing and deduplication. SQLite WAL stores the durable queue, job progress, hashes,
rejected-upload audit and output paths; generated filenames protect local uploads.

The background worker runs each job in an isolated child with time limits, temporary workspaces
and checkpoints. Direct reading always runs. Per-page quality checks overlap reading, and only
flagged image regions or broken pages enter concurrent local OCR. Source reconciliation retains
readable direct text and flags disagreement.

Source observations and explicit region boundaries make layout transformations inspectable.
Boundary-aware geometric grouping precedes final reading order; the final sanitizer cleans text.
Recognition and layout confidence are tracked separately. Layout, captions, tables and ordered
sanitizer steps produce clean markdown and structured JSON.
Blank and merged cells, image assets, provenance and warnings remain inspectable. Office
previews use synthetic page coordinates. Result, image, status and event endpoints power the
viewer; deletion cancels work under a shared lock before removing artifacts.

Clean markdown contains no image placeholders. Downstream embeddings, chunking and RAG are
outside this service, as are authentication, URL ingestion and LLM answering.

Regenerate both views with `python scripts/generate_architecture.py`. The generator uses only
the standard library. The native scene follows the [official Excalidraw JSON
schema](https://docs.excalidraw.com/docs/codebase/json-schema/).
