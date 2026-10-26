"""Evaluate downloaded public documents using bounded full-pipeline subprocesses."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from rag_pre_ingest.models.document import DocumentResult
from rag_pre_ingest.pipeline.validation import ValidationConfig, ValidationError, validate_upload

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]


def evaluate() -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for entry in json.loads((ROOT / "manifest.json").read_text())["documents"]:
        path = ROOT / ".cache" / entry["file"]
        output = path.with_suffix(path.suffix + ".result.json")
        summary: dict[str, object] = {"file": entry["file"], "failures": []}
        print("Evaluating " + entry["file"], flush=True)
        try:
            validated = validate_upload(path.read_bytes(), path.name, ValidationConfig())
        except ValidationError as error:
            summary["validation"] = error.code
            summary["failures"] = ["Upload rejected: " + error.code]
            findings.append(summary)
            continue
        summary["validation"] = "accepted"
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO / "scripts/evaluate_fixtures.py"),
                    "--worker",
                    str(path),
                    "--type",
                    validated.file_type,
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if completed.returncode:
                raise RuntimeError(completed.stderr[-400:])
            result = DocumentResult.model_validate_json(output.read_text())
            summary["stats"] = result.stats.model_dump()
            summary["warning_codes"] = sorted({w.code for w in result.warnings})
            text = " ".join(result.markdown.casefold().split())
            blocks = [block for page in result.pages for block in page.blocks]
            tables = [block for block in blocks if block.type == "table"]
            failures = []
            if entry["file"].startswith("w3c-complex-table"):
                if len(tables) != 1:
                    failures.append(f"Expected one table; found {len(tables)}")
                if not any(t.columns == 6 for t in tables):
                    failures.append("Expected six table columns")
                if not any(t.rows == 6 for t in tables):
                    failures.append("Expected two header rows plus four data rows")
                if len(tables) == 1:
                    cell_map = {(cell.row, cell.col): cell.text for cell in tables[0].cells}
                    expected_cells = {
                        (2, 0): "Blind",
                        (2, 1): "5",
                        (2, 2): "1",
                        (2, 3): "4",
                        (2, 4): "34.5%, n=1",
                        (2, 5): "1199 sec, n=1",
                        (3, 0): "Low Vision",
                        (4, 0): "Dexterity",
                        (5, 0): "Mobility",
                        (5, 3): "0",
                    }
                    for position, expected in expected_cells.items():
                        if "".join(cell_map.get(position, "").casefold().split()) != "".join(
                            expected.casefold().split()
                        ):
                            failures.append(f"Cell {position} content/position mismatch")
                if not any(any(c.col_span > 1 for c in t.cells) for t in tables):
                    failures.append("Multi-column Results header span missing")
                if not any(any(c.row_span > 1 for c in t.cells) for t in tables):
                    failures.append("Multi-row header spans missing")
            if entry["file"].startswith("w3c-headings"):
                expected = ["Cooking techniques", "Cooking with oil", "Cooking with butter"]
                headings = [block.text for block in blocks if block.type == "heading"]
                for label in expected:
                    if label not in headings:
                        failures.append("Heading classification missing: " + label)
            if entry["file"] == "w3c-lists.pdf":
                for label in ["Rocky High School", "Moose Middle School", "Peabody Elementary"]:
                    if not any(block.type == "list" and label in block.text for block in blocks):
                        failures.append("List item classification missing: " + label)
            if entry["file"] == "w3c-language.pdf":
                if "sagamore bridge" not in text:
                    failures.append("Sagamore split into separate words")
                if "you better have a boat" not in text:
                    failures.append("You split into separate words")
            if entry["file"] == "w3c-two-columns.pdf":
                if "application for this and that" not in text:
                    failures.append("Document title missing")
            if entry["file"] == "census-state-population.xlsx":
                if len(tables) != 1 or tables[0].columns != 7:
                    failures.append("Expected seven logical columns, excluding styled empty tail")
                if "331515736" not in text or "340110988" not in text:
                    failures.append("US population base/2024 values missing")
                if not any(any(c.col_span == 5 for c in t.cells) for t in tables):
                    failures.append("Population year header span missing")
            if entry["file"] == "irs-w9.pdf":
                if any(
                    t.rows == 1 and t.columns == 1 and not any(c.text.strip() for c in t.cells)
                    for t in tables
                ):
                    failures.append("Blank form checkbox misclassified as one-cell table")
            if any(
                code in {"corrupted_page", "corrupted_block", "ocr_unavailable", "page_timeout"}
                for code in summary["warning_codes"]
            ):
                failures.append("A processing step raised a warning")
            summary["failures"] = failures
            summary["headings"] = [block.text for block in blocks if block.type == "heading"]
            summary["table_shapes"] = [
                {
                    "rows": t.rows,
                    "columns": t.columns,
                    "merged_cells": sum(c.row_span > 1 or c.col_span > 1 for c in t.cells),
                }
                for t in tables
            ]
            print(
                entry["file"]
                + ": "
                + ("PASS stated checks" if not failures else "; ".join(failures)),
                flush=True,
            )
        except (subprocess.TimeoutExpired, RuntimeError, ValueError) as error:
            summary["failures"] = [str(error)]
        findings.append(summary)
    (ROOT / "observations.json").write_text(json.dumps(findings, indent=2) + "\n")
    coverage = REPO / "docs/real-world-coverage.md"
    if coverage.exists():
        original = coverage.read_text()
        start = "<!-- public-run:start -->"
        end = "<!-- public-run:end -->"
        passed = sum(not finding["failures"] for finding in findings)
        lines = [
            start,
            "",
            "## Latest reproducible public-data check",
            "",
            f"{passed}/{len(findings)} documents satisfy their stated automated assertions.",
            "This includes limited smoke checks and does not establish full semantic correctness.",
            "",
            "| Document | Latest check |",
            "| --- | --- |",
        ]
        for finding in findings:
            failures = finding["failures"]
            lines.append(
                "| "
                + str(finding["file"])
                + " | "
                + ("; ".join(failures) if failures else "Stated checks pass")
                + " |"
            )
        lines += ["", end]
        block = "\n".join(lines)
        if start in original:
            begin = original.index(start)
            finish = original.index(end, begin) + len(end)
            original = original[:begin] + block + original[finish:]
        else:
            original += "\n" + block + "\n"
        coverage.write_text(original)

    return findings


if __name__ == "__main__":
    findings = evaluate()
    print(f"{sum(not item['failures'] for item in findings)}/{len(findings)} stated checks passed")
    if any(item["failures"] for item in findings):
        raise SystemExit(1)
