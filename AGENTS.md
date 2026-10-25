# Agent instructions for rag-pre-ingest

Read these first, in order:
1. docs/rag-pre-ingest-build-spec.md (single source of truth)
2. BUILD_PROMPT.md (how to work with the owner)

Rules that always apply:
- Build one milestone at a time (spec section 10). Stop after each and wait for the owner to say go.
- Python first. Every library must have a usable Rust equivalent (spec section 9).
- Read first, OCR only where a page or region needs it.
- Clean markdown is the only ingestion source. No image markers in it.
- Validate every upload at the door (spec section 5d). One bad page becomes a warning, never a failed job.
- Thresholds in spec section 5a are starting values. Keep them in config.
- Out of scope: embeddings, chunking, vector search, auth, password-protected files, URL ingestion, Rust port (spec section 11).
- Do not claim something works unless you ran it. Show test output.
- Never add yourself as a commit co-author. Never hand-edit auto-generated files.
