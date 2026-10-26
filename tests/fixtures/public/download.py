"""Fetch a bounded public evaluation corpus; no document is fetched at app runtime."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMMIT = "457cece22d8219be32d29c5c1313e71aa6b61eae"
SAMPLES = [
    (
        "w3c-complex-table.pdf",
        "pdf-complex-table/complex-table.pdf",
        ["complex_table", "multirow_headers", "merged_cells"],
    ),
    (
        "w3c-complex-table.docx",
        "pdf-complex-table/complex-table.docx",
        ["word_complex_table", "merged_cells"],
    ),
    (
        "w3c-two-columns.pdf",
        "pdf-reading-order/reading-order-2cols-word.pdf",
        ["two_columns", "tagged_pdf"],
    ),
    ("w3c-headings.pdf", "pdf-headings/cooking.pdf", ["headings", "nested_headings"]),
    ("w3c-headings.docx", "pdf-headings/cooking.docx", ["word_heading_styles"]),
    ("w3c-lists.pdf", "pdf-lists/lists.pdf", ["bullet_lists", "numbered_lists"]),
    (
        "w3c-language.pdf",
        "pdf-lang-phrase/lang-of-phrase.pdf",
        ["multilingual_text", "pdf_language_metadata"],
    ),
]


def download() -> list[dict[str, object]]:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    known = (
        json.loads((ROOT / "manifest.json").read_text())["documents"]
        if (ROOT / "manifest.json").exists()
        else []
    )
    hashes = {entry["file"]: entry["sha256"] for entry in known}
    entries = []
    for name, path, scenarios in SAMPLES:
        url = f"https://raw.githubusercontent.com/w3c/wcag/{COMMIT}/working-examples/{path}"
        entries.append(
            {
                "file": name,
                "source": url,
                "source_page": "https://www.w3.org/WAI/WCAG22/Techniques/pdf/",
                "scenarios": scenarios,
                "attribution": "W3C WCAG working examples; contributors; original bytes unchanged",
                "license": "W3C Document License",
                "license_url": "https://www.w3.org/copyright/document-license-2023/",
            }
        )
    entries.append(
        {
            "file": "irs-w9.pdf",
            "source": "https://www.irs.gov/pub/irs-pdf/fw9.pdf",
            "source_page": "https://www.irs.gov/forms-pubs/about-form-w-9",
            "scenarios": ["fillable_form", "multicolumn_instructions"],
            "attribution": "Internal Revenue Service; blank form; no submitted taxpayer data",
            "license": "US federal employee work; IRS reuse policy; no endorsement",
            "license_url": "https://www.irs.gov/about-irs/use-of-content-from-irsgov",
        }
    )
    entries.append(
        {
            "file": "census-state-population.xlsx",
            "source": "https://www2.census.gov/programs-surveys/popest/tables/2020-2024/state/totals/NST-EST2024-POP.xlsx",
            "source_page": "https://www2.census.gov/programs-surveys/popest/tables/2020-2024/state/totals/",
            "scenarios": [
                "official_numeric_spreadsheet",
                "multirow_merged_headers",
                "formatted_numbers",
                "source_notes",
            ],
            "attribution": "U.S. Census Bureau, Population Division, Vintage 2024 estimates",
            "license": "US federal government statistical data; no endorsement",
            "license_url": "https://www.copyright.gov/history/copyright-exhibit/lifecycle/",
        }
    )
    for entry in entries:
        request = urllib.request.Request(
            str(entry["source"]), headers={"User-Agent": "rag-pre-ingest-public-evaluation/1.0"}
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            raise ValueError("Public fixture exceeds 5MiB acquisition limit")
        digest = hashlib.sha256(data).hexdigest()
        if entry["file"] in hashes and digest != hashes[entry["file"]]:
            raise ValueError("Public source changed; review before updating the recorded hash.")
        (cache / str(entry["file"])).write_bytes(data)
        entry["bytes"] = len(data)
        entry["sha256"] = hashlib.sha256(data).hexdigest()
        print(f"Downloaded {entry['file']}: {len(data)} bytes", flush=True)
    (ROOT / "manifest.json").write_text(
        json.dumps(
            {"retrieved": "2026-10-25", "w3c_commit": COMMIT, "documents": entries}, indent=2
        )
        + "\n"
    )
    return entries


if __name__ == "__main__":
    download()
