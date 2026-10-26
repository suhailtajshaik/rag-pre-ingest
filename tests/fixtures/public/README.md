# Official public-document evaluation corpus

The manifest records nine unmodified documents, original source URLs, attribution,
license links, retrieval date, file sizes and SHA-256 hashes. W3C sources are pinned
to a repository commit; the IRS source is versioned by its recorded hash.

- W3C WCAG working examples: W3C and contributors. Their repository identifies the
  [W3C Document License](https://www.w3.org/copyright/document-license-2023/).
  Original documents are retained unchanged, with their existing notices.
- IRS blank Form W-9: Internal Revenue Service, downloaded from IRS.gov. The
  [IRS reuse policy](https://www.irs.gov/about-irs/use-of-content-from-irsgov)
  permits reuse of federal employee works. This corpus does not imply IRS approval
  or endorsement and contains no completed taxpayer forms.
- Census Vintage 2024 state-population workbook: U.S. Census Bureau, Population
  Division; aggregate official federal statistics, with no individual records.
  Source and public-domain reference are recorded in the manifest.

Downloaded originals and full extracted results stay in ignored `.cache/`. Source
and attribution records remain in Git. Do not redistribute cached originals
without retaining the applicable source attribution and copyright notices.

Run from the repository root:

```sh
.venv/bin/python tests/fixtures/public/download.py
.venv/bin/python tests/fixtures/public/evaluate.py
```

The downloader uses the standard library, limits each acquisition to 5 MiB and
checks subsequent downloads against the recorded hashes. A changed upstream file
requires deliberate review. It never disables TLS verification; environments with
a separately managed trust store can set `SSL_CERT_FILE` to their trusted bundle.
Acquisition is a developer tool, not URL ingestion in the running app.

The evaluator runs each document through the real pipeline in a separate process,
with a 180-second limit. `observations.json` records actual checks and warnings.
An official Census XLSX covers styled empty tails and merged numeric headers.
No low-quality scan or handwriting dataset is included yet;
this is a targeted regression corpus, not a general accuracy benchmark.
