# rag-pre-ingest

A read-first document preparation service that sits in front of a RAG or search system. It takes PDF, Word, Excel, or image files and returns clean markdown plus structured JSON (pages, typed blocks, bounding boxes, heading paths, confidence, source tags). It reads files directly and uses OCR only on pages or regions that need it. No embeddings, no vector database, no LLM by default.

This folder is the planning package. The code does not exist yet.

## What is in here

- docs/rag-pre-ingest-build-spec.md : the full build spec (12 sections)
- BUILD_PROMPT.md : the prompt to give a coding agent
- AGENTS.md : short standing instructions the agent reads first

## How to use

1. Put this folder in a new git repo called rag-pre-ingest.
2. Open it in your coding agent (for example Claude Code).
3. Paste the contents of BUILD_PROMPT.md as the first message.
4. The agent proposes a repo layout and dependency list. Approve or adjust.
5. It then builds one milestone at a time. Say go after each one.

## Milestones

1. Upload endpoint, job table, file type sniffing, hash dedup, input validation
2. Direct reading for PDF, Word, Excel, plus markdown output
3. Viewer app (page image, boxes, block list, markdown tab)
4. Per-page quality check and OCR fallback
5. XY-cut reading order and caption attachment
6. Table detection with blank and merged cell handling
7. Header and footer stripping, sanitizer polish, warnings
8. Test on about twenty real documents and tune the thresholds

## Ship checklist

A project counts as shipped only with all three: a live demo, a public repo with a clear README, and a short write-up.
