"""Reproducible synthetic OCR routing calibration; no OCR models are invoked."""

from __future__ import annotations

import itertools
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from rag_pre_ingest.models.document import Block, Page
from rag_pre_ingest.pipeline.quality import QualityConfig, evaluate_quality, select_regions
from rag_pre_ingest.pipeline.readers import read_document
from rag_pre_ingest.pipeline.validation import ValidationConfig, validate_upload

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Label:
    name: str
    family: str
    split: str
    page: Page
    needs_ocr: bool
    region_only: bool = False


def artificial_page(text: str, *, image: bool = False) -> Page:
    blocks = [Block(id="text", type="paragraph", text=text, markdown=text, bbox=(20, 20, 580, 100))]
    if image:
        blocks.append(Block(id="image", type="image", bbox=(30, 200, 300, 500)))
    return Page(page_number=1, width=612, height=792, blocks=blocks)


def labels() -> list[Label]:
    fixtures = ROOT / "tests/fixtures/synthetic"
    manifest = json.loads((fixtures / "manifest.json").read_text())["fixtures"]
    # Whole scenario families are assigned before evaluating candidates.
    files = {
        "01-clean.pdf": ("clean_pdf", "development", False, False),
        "02-repeated.pdf": ("repeating_chrome", "held_out", False, False),
        "03-two-columns.pdf": ("columns", "held_out", False, False),
        "04-ruled-table.pdf": ("ruled_table", "development", False, False),
        "05-merged-grid.pdf": ("merged_table", "held_out", False, False),
        "06-unruled-table.pdf": ("unruled_table", "held_out", False, False),
        "07-scan.pdf": ("scanned_pdf", "development", True, False),
        "08-mixed.pdf": ("mixed_pdf", "development", True, True),
        "09-caption.pdf": ("captioned_image", "held_out", True, True),
        "11-hyphen-wrap.pdf": ("hyphenation", "held_out", False, False),
        "12-blank.pdf": ("blank_pdf", "development", False, False),
        "13-wrong-extension.docx": ("wrong_extension", "held_out", False, False),
        "18-structured.docx": ("word_embedded_image", "held_out", True, True),
        "19-structured.xlsx": ("structured_excel", "held_out", False, False),
        "20-scan.png": ("standalone_png", "development", True, False),
        "21-scan.jpg": ("standalone_jpeg", "held_out", True, False),
        "22-multipage.tiff": ("multipage_image", "held_out", True, False),
    }
    examples: list[Label] = []
    for item in manifest:
        name = item["file"]
        if name not in files:
            continue
        family, split, expected, region_only = files[name]
        data = (fixtures / name).read_bytes()
        validated = validate_upload(data, name, ValidationConfig())
        result = read_document(data, validated.file_type, name, "calibration", "calibration")
        for page in result.pages:
            examples.append(
                Label(f"{name} page {page.page_number}", family, split, page, expected, region_only)
            )
    examples += [
        Label("short title", "short_title", "development", artificial_page("Title"), False),
        Label("short divider", "short_divider", "held_out", artificial_page("I"), False),
        Label(
            "broken replacement glyphs",
            "replacement_encoding",
            "development",
            artificial_page("Read " + "\ufffd" * 20),
            True,
        ),
        Label(
            "private use font",
            "private_use_encoding",
            "held_out",
            artificial_page("Text " + "\ue001" * 20),
            True,
        ),
        Label(
            "valid accented text",
            "valid_unicode",
            "held_out",
            artificial_page("café résumé £ € ¥ 中文 العربية हिन्दी"),
            False,
        ),
    ]
    return examples


def metrics(examples: list[Label], config: QualityConfig) -> dict[str, int]:
    counts = {
        "true_positive": 0,
        "true_negative": 0,
        "false_positive": 0,
        "false_negative": 0,
        "region_failures": 0,
    }
    for label in examples:
        quality = evaluate_quality(label.page, config)
        prediction = quality.needs_ocr
        key = ("true_" if prediction == label.needs_ocr else "false_") + (
            "positive" if prediction else "negative"
        )
        counts[key] += 1
        if label.region_only:
            regions = select_regions(label.page, quality, config)
            full = (0.0, 0.0, label.page.width, label.page.height)
            if not regions or full in regions:
                counts["region_failures"] += 1
    return counts


def candidates() -> list[QualityConfig]:
    return [
        QualityConfig(
            near_empty_characters=near,
            garbage_share_threshold=garbage,
            image_coverage_threshold=coverage,
            min_words_per_area=density,
        )
        for near, garbage, coverage, density in itertools.product(
            [3, 5, 10], [0.005, 0.01, 0.02], [0.5, 0.65, 0.8, 0.9], [0, 0.00001, 0.00002, 0.00005]
        )
    ]


def calibrate(examples: list[Label]) -> tuple[QualityConfig, dict[str, int], dict[str, int]]:
    default = QualityConfig()
    development = [label for label in examples if label.split == "development"]

    def score(config: QualityConfig) -> tuple[int, int, int, float]:
        result = metrics(development, config)
        distance = sum(
            abs(float(asdict(config)[key]) - float(value)) / max(abs(float(value)), 0.00001)
            for key, value in asdict(default).items()
        )
        return (
            result["false_negative"],
            result["region_failures"],
            result["false_positive"],
            distance,
        )

    selected = min(candidates(), key=score)
    return (
        selected,
        metrics(development, selected),
        metrics([label for label in examples if label.split == "held_out"], selected),
    )


def main() -> None:
    examples = labels()
    selected, development, held_out = calibrate(examples)
    lines = [
        "# Synthetic threshold calibration",
        "",
        (
            "Generated by `scripts/calibrate_thresholds.py`. This measures routing "
            "decisions, not OCR transcription accuracy."
        ),
        "",
        (
            f"Candidate settings evaluated: **{len(candidates())}**. Selection uses "
            f"development labels only, prioritizing missed OCR pages, incorrect "
            f"full-page escalation, unnecessary OCR, then distance from defaults."
        ),
        "",
        (
            "Whole scenario families are separated between development and held-out "
            "sets. Synthetic labels are explicit expectations, not statistical "
            "calibration on real documents."
        ),
        "",
        "## Recommended settings",
        "",
        "```json",
        json.dumps(asdict(selected), indent=2),
        "```",
        "",
        (
            "The defaults are retained when candidates tie; these examples provide no "
            "evidence to change them."
        ),
        "",
        (
            "| Split | True positive | True negative | False positive | False "
            "negative | Region failures |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for split, counts in [("Development", development), ("Held out", held_out)]:
        lines.append(
            f"| {split} | {counts['true_positive']} | {counts['true_negative']} | "
            f"{counts['false_positive']} | {counts['false_negative']} | "
            f"{counts['region_failures']} |"
        )
    lines += [
        "",
        "## Page expectations",
        "",
        "| Scenario | Split | Expected OCR | Predicted OCR | Routing |",
        "| --- | --- | --- | --- | --- |",
    ]
    for label in examples:
        quality = evaluate_quality(label.page, selected)
        regions = select_regions(label.page, quality, selected)
        routing = (
            "none"
            if not regions
            else (
                "full page"
                if (0.0, 0.0, label.page.width, label.page.height) in regions
                else "image regions"
            )
        )
        lines.append(
            f"| {label.name} | {label.split} | {label.needs_ocr} | {quality.needs_ocr} "
            f"| {routing} |"
        )
    lines += [
        "",
        "## Limits and excluded cases",
        "",
        (
            "- Decorative-logo fixtures are excluded from threshold selection: "
            "repetition-based decoration detection belongs to layout, and raw readers "
            "have not marked those images decorative."
        ),
        (
            "- Word embedded-image routing is now included in held-out labels: "
            "the reader exposes an actual raster asset and a synthetic region. "
            "Transcription assertions are recorded by the separate full-pipeline evaluation."
        ),
        "- Invalid upload fixtures are validated separately and never enter this routing loop.",
        (
            "- Coverage, density and near-empty thresholds cannot be independently "
            "calibrated by this corpus: any nondecorative image already triggers "
            "region OCR. Defaults remain provisional."
        ),
        (
            "- No real-world accuracy percentage is claimed. Fonts, handwriting, low "
            "contrast, damaged pages and unusual layouts need independently labelled "
            "real documents."
        ),
        "",
    ]
    output = ROOT / "docs/synthetic-calibration.md"
    output.write_text("\n".join(lines))
    print(
        json.dumps(
            {
                "candidates": len(candidates()),
                "selected": asdict(selected),
                "development": development,
                "held_out": held_out,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
