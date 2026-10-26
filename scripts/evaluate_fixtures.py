"""Run upload-door and full-pipeline scenario checks against local fixtures."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

try:
    from scripts.evaluation_metrics import text_metrics
except ModuleNotFoundError:
    from evaluation_metrics import text_metrics

from rag_pre_ingest.config import Settings
from rag_pre_ingest.models.document import DocumentResult
from rag_pre_ingest.pipeline.engine import run_pipeline
from rag_pre_ingest.pipeline.validation import ValidationConfig, ValidationError, validate_upload

ROOT = Path(__file__).resolve().parents[1]


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def check_result(name: str, result: DocumentResult, expected_text: str = "") -> list[str]:
    failures: list[str] = []
    markdown = normalized(result.markdown)
    blocks = [b for page in result.pages for b in page.blocks]
    tables = [b for b in blocks if b.type == "table"]

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    def contains(value: str) -> bool:
        return normalized(value) in markdown

    if expected_text:
        require(contains(expected_text), "Expected source text missing: " + expected_text)
    require(
        not re.search(r"!\[[^\]]*\]\(", result.markdown), "Image syntax leaked into clean markdown"
    )
    require(
        "<!-- image" not in result.markdown.casefold(), "Image marker leaked into clean markdown"
    )
    require(
        not any(
            w.code
            in {
                "corrupted_page",
                "page_callback_failed",
                "ocr_failed",
                "ocr_timeout",
                "page_timeout",
                "corrupted_block",
                "preview_unavailable",
                "ocr_unavailable",
            }
            for w in result.warnings
        ),
        "A page or OCR stage failed",
    )
    if name == "02-repeated.pdf":
        require(not contains("ACME report"), "Repeated header remains")
        require(not contains("Confidential"), "Repeated footer remains")
    elif name == "03-two-columns.pdf":
        phrases = [
            "Left first paragraph",
            "Left second paragraph",
            "Right first paragraph",
            "Right second paragraph",
        ]
        positions = [markdown.find(normalized(p)) for p in phrases]
        require(
            all(p >= 0 for p in positions) and positions == sorted(positions),
            "Column reading order incorrect",
        )
    elif name == "04-ruled-table.pdf":
        require(bool(tables), "Ruled table missing")
        require(
            any(t.columns == 3 and any(c.text == "" for c in t.cells) for t in tables),
            "Blank table cells or columns missing",
        )
    elif name == "05-merged-grid.pdf":
        require(
            any(any(c.row_span > 1 or c.col_span > 1 for c in t.cells) for t in tables),
            "Merged PDF span missing",
        )
    elif name == "06-unruled-table.pdf":
        require(bool(tables), "Unruled table missing")
    elif name in {"07-scan.pdf", "20-scan.png", "21-scan.jpg", "22-multipage.tiff"}:
        require(contains("SCANNED DOCUMENT"), "Scan heading missing")
        require(contains("Invoice total 123.45"), "Scan invoice value missing")
    elif name == "08-mixed.pdf":
        require(
            contains("Digital introduction") and contains("Invoice total 123.45"),
            "Mixed direct and OCR text not preserved",
        )
        require(any(p.method == "mixed" for p in result.pages), "Mixed source method missing")
    elif name == "09-caption.pdf":
        require(
            any(b.type == "image" and b.caption and "Invoice sample" in b.caption for b in blocks),
            "Image caption attachment missing",
        )
    elif name == "10-logo.pdf":
        require(
            any(b.is_decorative for b in blocks if b.type == "image"),
            "Repeated logo not marked decorative",
        )
    elif name == "11-hyphen-wrap.pdf":
        require(contains("paragraph continues here."), "Broken hyphenated word not repaired")
        require(contains("well-known"), "Real hyphen not retained")
    elif name == "12-blank.pdf":
        require(
            any(w.code == "empty_document" for w in result.warnings),
            "Empty-document warning missing",
        )
    elif name == "18-structured.docx":
        require(contains("中文") and contains("العربية"), "Non-Latin direct text lost")
        require(
            any(any(c.col_span > 1 for c in t.cells) for t in tables), "Word merged span missing"
        )
        require(contains("Invoice total 123.45"), "Word embedded image OCR missing")
    elif name == "19-structured.xlsx":
        require(contains("中文") and contains("café"), "Spreadsheet Unicode lost")
        require(
            any(any(c.text == "" for c in t.cells) for t in tables), "Spreadsheet blanks missing"
        )
    elif name == "hackathon-guidelines.png":
        require(sum(block.type == "list" for block in blocks) == 23, "Poster bullet structure lost")
        require(
            not any(line.strip() == "O" for line in result.markdown.splitlines()),
            "Poster decorative circle leaked into clean markdown",
        )
        for phrase in [
            "AGENT",
            "STACKING",
            "Rules & Guidelines",
            "Challenge Selection",
            "Build Expectations",
            "Tools & Technology",
            "Data Usage",
            "Guardrails",
            "Demo Expectation",
            "Code of Conduct",
            "Teams may use provided datasets",
        ]:
            require(contains(phrase), "Poster text missing: " + phrase)
    elif name == "theme-palette.png":
        require(
            len(tables) == 2 and all(table.columns == 2 for table in tables),
            "Palette must contain two independent key/value tables",
        )
        for value in (
            "#F5F7F2",
            "#FFFFFF",
            "#D4DDD5",
            "#1A2E1C",
            "#16A34A",
            "#15803D",
            "#22C55E",
            "#0C120D",
            "#151E16",
            "#253026",
            "#E2EDE3",
            "#4ADE80",
            "#86EFAC",
            "trustworthy, organic",
            "Notion, Cal.com",
        ):
            require(contains(value), "Palette source content lost: " + value)
    elif name == "llm-flowchart.png":
        expected_chain = (
            "Tokenization → Embedding → Transformer Mechanism → Prediction → Response Generation"
        )
        require(contains(expected_chain), "Confirmed flowchart arrow sequence missing")
        require(
            sum(len(page.connectors) for page in result.pages) == 4,
            "Expected four confirmed flowchart links",
        )
        require(not tables, "Flowchart text was converted to a false table")
        require(
            contains("Tokens are converted into numerical vectors that represent meaning"),
            "Embedding explanation corrupted",
        )
        phrases = [
            "Tokenization",
            "Embedding",
            "Transformer Mechanism",
            "Prediction",
            "Response Generation",
        ]
        positions = [markdown.find(normalized(p)) for p in phrases]
        require(
            all(p >= 0 for p in positions) and positions == sorted(positions),
            "Flowchart step labels lost or reordered",
        )
    elif name == "automation-workshop.png":
        require(contains("Google Sheets"), "Google Sheets label split or corrupted")
        require(
            len([b for b in blocks if b.type == "list"]) == 3, "Three outcome bullets not preserved"
        )
        require(
            not any(b.text.strip().startswith("里") for b in blocks if not b.is_decorative),
            "Sheet icon became text",
        )
    elif name == "image-models.png":
        phrases = [
            "The AI Model Landscape",
            "Image Models",
            "Midjourney",
            "Google",
            "ByteDance",
            "OpenAI",
            "Qwen",
            "by Alibaba",
            "Black Forest Labs",
            "Leonardo",
            "Ideogram",
            "Reve",
        ]
        positions = [markdown.find(normalized(p)) for p in phrases]
        require(
            all(p >= 0 for p in positions) and positions == sorted(positions),
            "Image model card labels lost or reordered",
        )
        require(
            not any(line.strip() in {"K", "フ"} for line in result.markdown.splitlines()),
            "Decorative arrows became text",
        )
    elif name == "tech-stack.png":
        require(contains("CLAUDE CODE"), "Stacked logo label was split or interleaved")
        phrases = [
            "Frontend",
            "Vercel",
            "Database",
            "MongoDB",
            "Auth / Login",
            "clerk",
            "Emails",
            "Resend",
            "Cloud / VMs",
            "DigitalOcean",
            "Object storage",
            "CLOUDFLARE",
            "AI models",
            "Gemini",
        ]
        positions = [markdown.find(normalized(phrase)) for phrase in phrases]
        require(
            all(p >= 0 for p in positions) and positions == sorted(positions),
            "Tech stack categories separated from their tools",
        )
    elif name == "learning-levels.png":
        phrases = [
            "Level 1",
            "Master advanced prompting",
            "Level 2",
            "Integrate connectors",
            "Level 3",
            "Learn about Diffusion Models",
            "Level 4",
            "Build complex automations",
            "Level 5",
            "Build a real world",
        ]
        positions = [markdown.find(normalized(phrase)) for phrase in phrases]
        require(
            all(position >= 0 for position in positions) and positions == sorted(positions),
            "Level labels separated from their corresponding descriptions",
        )
    elif name == "sales-sheet.png":
        require(len(tables) == 1, "Raster spreadsheet table missing")
        if len(tables) == 1:
            table = tables[0]
            require((table.rows, table.columns) == (31, 9), "Spreadsheet cell grid shifted")
            values = {(c.row, c.col): c.text for c in table.cells}
            for position, expected in {
                (1, 0): "10001",
                (1, 5): "999.99",
                (1, 6): "1999.98",
                (2, 2): "Home Appliances",
                (8, 5): "599.99",
                (12, 4): "3",
                (20, 5): "99.99",
                (30, 6): "259.98",
                (30, 8): "Credit Card",
            }.items():
                require(values.get(position) == expected, f"Cell {position} expected {expected}")
        require(
            any(w.code == "ocr_table_review" for w in result.warnings),
            "Raster table review warning missing",
        )
    elif name == "numbered-questions.png":
        expected = [
            "1. DO I LIKE WHO I AM WHEN I'M AROUND THEM?",
            "2. DO THEY CHALLENGE ME IN WAYS THAT ELEVATE ME?",
            "3. DOES MY BEHAVIOR MOVE ME CLOSER OR FURTHER FROM MY VALUES?",
        ]
        actual = [b.text for b in blocks if b.type == "list"]
        require(actual == expected, "Numbered questions lost content, order, or wrapping")
        require(all(text in result.markdown for text in expected), "Clean list markdown differs")
    elif name == "ml-cyber-roles.pdf":
        require(len(result.pages) == 2 and len(tables) == 2, "Expected one table per PDF page")
        require(all(t.columns == 3 for t in tables), "Role table columns shifted")
        require(result.stats.pages.ocr == 0, "Readable PDF unnecessarily used OCR")
        require("<br>" not in result.markdown, "HTML break tags leaked into markdown")
        if len(tables) == 2:
            first = {(c.row, c.col): c.text for c in tables[0].cells}
            second = {(c.row, c.col): c.text for c in tables[1].cells}
            require(
                first.get((1, 0), "").replace("\n", " ")
                == "MLOps Engineer / Senior MLOps Engineer",
                "Role label reordered",
            )
            require(
                first.get((1, 1), "").startswith("Python for production ML"),
                "Skills cell misplaced",
            )
            require(
                first.get((1, 2), "").startswith("Build and maintain automated training"),
                "Responsibilities cell misplaced",
            )
            require(
                second.get((0, 0)) == "Data Engineer (ML-focused)", "Continuation row misplaced"
            )
            require(
                second.get((0, 1), "").startswith("SQL and data modeling"),
                "Continuation words reordered",
            )
    elif name == "python-code.png":
        code = next((b for b in blocks if b.markdown.startswith("```python\n")), None)
        require(code is not None, "Code fence and source lines missing")
        if code is not None:
            try:
                ast.parse(code.text)
            except SyntaxError:
                require(False, "Code punctuation or indentation is invalid")
            for value in [
                "import os\nfrom openai import OpenAI",
                '    messages=[\n        {\n            "role": "user",',
                "\n        }\n    ],\n)",
                '"content": "What is the capital of France?"',
                "print(completion.choices[0].message.content)",
            ]:
                require(value in code.text, "Code source content missing: " + value)
        require(not any(b.type == "list" for b in blocks), "Code became a bullet list")
        require(
            any(w.code == "ocr_code_review" for w in result.warnings), "Code review warning missing"
        )
    elif name == "theme-cards.png":
        descriptions = [
            "Dark·Minimal·Monochrome",
            "Dark·Teal·Electric",
            "Light·Pink·Soft",
            "Dark·Gold·Premium",
            "Light·Blue-grey·Professional",
            "Dark·Red-orange·Bold",
            "Light·Warm cream·Editorial",
            "Dark·Cyberpunk·High contrast",
            "Light·Muted green·Calm",
            "Dark·Deep blue·Trustworthy",
        ]
        positions = [markdown.find(normalized(text)) for text in descriptions]
        require(all(p >= 0 for p in positions), "Card description missing")
        require(positions == sorted(positions), "Card order incorrect")
        require(markdown.count("prompt studio") == 10, "Card branding lost or duplicated")
        require(markdown.count("try free") == 10, "Card actions lost or duplicated")
    elif name == "notebooklm-mind-map.png":
        for phrase in [
            "Joint Embedding Predictive Architecture",
            "Core Concept",
            "World Modeling",
            "System Architecture",
            "Context Encoder",
            "Target Encoder",
            "Predictor Network",
            "Implementation Variants",
            "Key Advantages",
            "Training Paradigms",
            "Challenges Addressed",
        ]:
            require(contains(phrase), "Mind-map label missing: " + phrase)
    return failures


def cases() -> list[dict[str, Any]]:
    base = ROOT / "tests/fixtures/synthetic"
    items = json.loads((base / "manifest.json").read_text())["fixtures"]
    result = [{**item, "path": str(base / item["file"])} for item in items]
    for path in sorted((ROOT / "tests/fixtures/user_samples").iterdir()):
        if path.suffix not in {".png", ".pdf"}:
            continue
        result.append(
            {
                "file": path.name,
                "path": str(path),
                "validation": "accepted",
                "config": {},
                "expected_text": "",
            }
        )
    return result


def evaluate(case: dict[str, Any], timeout: float = 300) -> dict[str, Any]:
    name = str(case["file"])
    data = Path(case["path"]).read_bytes()
    summary: dict[str, Any] = {
        "file": name,
        "expected_validation": case["validation"],
        "failures": [],
    }
    try:
        validated = validate_upload(data, name, ValidationConfig(**case["config"]))
    except ValidationError as error:
        summary["actual_validation"] = error.code
        if error.code != case["validation"]:
            summary["failures"].append("Unexpected rejection: " + error.code)
        return summary
    summary["actual_validation"] = "accepted"
    if case["validation"] != "accepted":
        summary["failures"].append("Expected rejection did not occur")
        return summary
    with tempfile.TemporaryDirectory(prefix="rag-evaluate-") as directory:
        output = Path(directory) / "result.json"
        try:
            process = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--worker",
                    case["path"],
                    "--type",
                    validated.file_type,
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if process.returncode or not output.is_file():
                summary["failures"].append("Pipeline subprocess failed: " + process.stderr[-500:])
                return summary
            result = DocumentResult.model_validate_json(output.read_text())
        except subprocess.TimeoutExpired:
            summary["failures"].append("Pipeline subprocess exceeded time limit")
            return summary
        summary["failures"] = check_result(name, result, str(case.get("expected_text", "")))
        summary["stats"] = result.stats.model_dump()
        summary["warnings"] = [w.model_dump() for w in result.warnings]
        summary["markdown_excerpt"] = result.markdown[:800]
        ground_truth = ROOT / "tests/fixtures/ground_truth"
        references = json.loads((ground_truth / "manifest.json").read_text())["cases"]
        for reference in references:
            if Path(reference["fixture"]).name != name:
                continue
            expected = (ground_truth / reference["transcription"]).read_text()
            actual = "\n".join(
                block.text
                for page in result.pages
                for block in page.blocks
                if block.type not in {"image", "header", "footer"} and not block.is_decorative
            )
            metrics = text_metrics(expected, actual)
            summary["transcription_metrics"] = {
                "cer": metrics.cer,
                "wer": metrics.wer,
                "exact": metrics.exact,
                "split": reference["split"],
                "scope": reference["scope"],
                "meets_target": metrics.cer <= reference["max_cer"]
                and metrics.wer <= reference["max_wer"],
            }
    return summary


def report(results: list[dict[str, Any]], destination: Path) -> None:
    passed = sum(not item["failures"] for item in results)
    lines = [
        "# Fixture evaluation",
        "",
        "Generated by `scripts/evaluate_fixtures.py` with actual local OCR and the full pipeline.",
        "",
        (
            f"**{passed}/{len(results)} cases passed the stated assertions.** Warnings "
            f"remain visible and are not proof of correct transcription."
        ),
        "",
        "| File | Upload expectation | Actual upload | Assertions |",
        "| --- | --- | --- | --- |",
    ]
    for item in results:
        details = (
            "PASS"
            if not item["failures"]
            else "; ".join(item["failures"]).replace("|", "\\|").replace("\n", " ")
        )
        lines.append(
            f"| {item['file']} | {item['expected_validation']} | "
            f"{item.get('actual_validation', 'unknown')} | {details} |"
        )
    lines += [
        "",
        "## Complete transcription scores",
        "",
        (
            "These scores measure all visible text, separately from scenario assertions. "
            "A passing scenario is not a perfect transcription. Existing samples are regression "
            "data; no held-out real-document accuracy is claimed."
        ),
        "",
        "| File | Character error rate | Word error rate | Exact | Meets transcription target |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in results:
        if metrics := item.get("transcription_metrics"):
            lines.append(
                f"| {item['file']} | {metrics['cer']:.4%} | {metrics['wer']:.4%} | "
                f"{metrics['exact']} | {metrics['meets_target']} |"
            )
    lines += [
        "",
        "## Source-specific OCR scale experiment",
        "",
        (
            "The hackathon poster was checked at native, doubled and tripled input "
            "scale during development. Doubling its 630-pixel width to 1260 recovered "
            "the provided-datasets phrase. The configurable minimum region width is "
            "1260 pixels. This choice is based on one source image and does not "
            "establish a general OCR accuracy optimum. The final evaluation below "
            "uses that setting. The mind map source is 4403 by 7037 pixels; its "
            "visible labels are checked without claiming diagram understanding."
        ),
        "",
        "## Warnings and limits",
        "",
        (
            "Synthetic fixtures exercise known scenarios; they cannot establish "
            "arbitrary real-document accuracy. User images are checked for visible "
            "labels and the poster datasets sentence, not diagram relationships or "
            "semantics. Word/Excel coordinates remain synthetic. Low OCR confidence "
            "warnings do not fail a case when its required text is present."
        ),
        "",
    ]
    for item in results:
        if item.get("warnings"):
            counts = {w["code"] for w in item["warnings"]}
            lines.append("- " + item["file"] + ": " + ", ".join(sorted(counts)))
    destination.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--worker")
    parser.add_argument("--type")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.worker:
        data = Path(args.worker).read_bytes()
        with tempfile.TemporaryDirectory(prefix="rag-pipeline-") as directory:
            result = run_pipeline(
                data,
                args.type,
                Path(args.worker).name,
                hashlib.sha256(data).hexdigest(),
                "evaluation",
                Settings.from_env(),
                Path(directory),
            )
            Path(args.output).write_text(result.model_dump_json())
        return
    results = []
    for case in cases():
        if args.case and case["file"] not in args.case:
            continue
        print("Evaluating " + case["file"], flush=True)
        item = evaluate(case)
        results.append(item)
        print(
            ("PASS " if not item["failures"] else "FAIL ")
            + case["file"]
            + (" — " + "; ".join(item["failures"]) if item["failures"] else ""),
            flush=True,
        )
    report(results, ROOT / "docs/fixture-evaluation.md")
    (ROOT / "docs/fixture-evaluation.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"{sum(not item['failures'] for item in results)}/{len(results)} passed", flush=True)
    if any(item["failures"] for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
