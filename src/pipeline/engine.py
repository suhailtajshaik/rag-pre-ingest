"""Read first; schedule quality checks and only necessary OCR as pages arrive."""

from __future__ import annotations

import hashlib
import io
import json
import time
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from rag_pre_ingest.config import Settings
from rag_pre_ingest.models.document import Block, Document, DocumentResult, Page, Stats, Warning
from rag_pre_ingest.pipeline.connectors import detect_connectors
from rag_pre_ingest.pipeline.images import mark_decorative
from rag_pre_ingest.pipeline.layout import attach_captions, sort_page
from rag_pre_ingest.pipeline.ocr import recognize
from rag_pre_ingest.pipeline.quality import (
    QualityConfig,
    evaluate_quality,
    garbage_share,
    select_regions,
)
from rag_pre_ingest.pipeline.readers import page_deadline, read_document, render_page
from rag_pre_ingest.pipeline.sanitizer import rank_headings, sanitize_document
from rag_pre_ingest.pipeline.structure import capture_page, prepare_page
from rag_pre_ingest.pipeline.tables import detect_tables

BBox = tuple[float, float, float, float]


def rebuild_result(result: DocumentResult) -> DocumentResult:
    """Derive output and counts from the retained ordered blocks."""
    blocks = [block for page in result.pages for block in page.blocks]
    result.markdown = "\n\n".join(
        block.markdown
        for block in blocks
        if block.type not in {"image", "header", "footer"} and block.markdown.strip()
    )
    result.warnings = [warning for warning in result.warnings if warning.code != "empty_document"]
    if not result.markdown.strip():
        result.warnings.append(
            Warning(code="empty_document", message="No readable text was found.")
        )
    stats = result.stats
    stats.pages.total = len(result.pages)
    stats.pages.read = sum(page.method == "read" for page in result.pages)
    stats.pages.ocr = sum(page.method == "ocr" for page in result.pages)
    stats.pages.mixed = sum(page.method == "mixed" for page in result.pages)
    stats.images.total = sum(block.type == "image" for block in blocks)
    stats.images.decorative = sum(block.type == "image" and block.is_decorative for block in blocks)
    stats.images.with_ocr_text = sum(
        block.type == "image" and bool(block.ocr_text) for block in blocks
    )
    stats.tables.total = sum(block.type == "table" for block in blocks)
    stats.tables.with_merged_cells = sum(
        block.type == "table"
        and any(cell.row_span > 1 or cell.col_span > 1 for cell in block.cells)
        for block in blocks
    )
    stats.headings = sum(block.type == "heading" for block in blocks)
    stats.paragraphs = sum(block.type == "paragraph" for block in blocks)
    stats.lists = sum(block.type == "list" for block in blocks)
    stats.warnings.total = len(result.warnings)
    stats.warnings.by_code = dict(Counter(warning.code for warning in result.warnings))
    scores = [block.confidence for block in blocks if block.confidence is not None]
    result.document.confidence.average = sum(scores) / len(scores) if scores else None
    result.document.confidence.lowest_block = min(scores) if scores else None
    return result


def overlap(first: BBox, second: BBox) -> float:
    area = max(0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0, min(first[3], second[3]) - max(first[1], second[1])
    )
    return area / max(1, (first[2] - first[0]) * (first[3] - first[1]))


def reconcile(page: Page, blocks: list[Block], garbage_threshold: float = 0.01) -> list[Warning]:
    """Prefer readable direct text on overlap, with explicit disagreement warnings."""
    warnings: list[Warning] = []
    capture_page(page)
    incoming = page.model_copy(update={"blocks": blocks}, deep=True)
    capture_page(incoming)
    page.observations = tuple(
        {o.id: o for o in (*page.observations, *incoming.observations)}.values()
    )
    for block in blocks:
        direct = [
            item
            for item in page.blocks
            if item.source == "read"
            and item.type != "image"
            and overlap(block.bbox, item.bbox) > 0.5
        ]
        if direct:
            agrees = (
                " ".join(block.text.split()).casefold()
                == " ".join(item.text for item in direct).casefold()
            )
            if not agrees:
                warnings.append(
                    Warning(
                        page_number=page.page_number,
                        code="source_disagreement",
                        message="Direct reading and OCR differ in this region.",
                    )
                )
            if all(garbage_share(item.text) <= garbage_threshold for item in direct):
                continue
            page.blocks = [item for item in page.blocks if item not in direct]
        page.blocks.append(block)
        for image in page.blocks:
            if image.type == "image" and overlap(block.bbox, image.bbox) > 0.5:
                image.ocr_text = "\n".join(filter(None, [image.ocr_text, block.text]))
    capture_page(page)
    sources = {block.source for block in page.blocks if block.type != "image" and block.text}
    page.method = (
        "mixed"
        if "ocr" in sources and "read" in sources
        else ("ocr" if "ocr" in sources else "read")
    )
    return warnings


def run_pipeline(
    data: bytes,
    file_type: str,
    file_name: str,
    file_hash: str,
    document_id: str,
    settings: Settings,
    working_dir: Path,
) -> DocumentResult:
    started = time.monotonic()
    warnings: list[Warning] = []
    image_assets: dict[str, bytes] = {}
    fingerprints: dict[str, str] = {}
    pending: list[tuple[Page, Future[list[Block]]]] = []
    config = QualityConfig(
        near_empty_characters=settings.near_empty_characters,
        garbage_share_threshold=settings.garbage_share_threshold,
        image_coverage_threshold=settings.image_coverage_threshold,
        min_words_per_area=settings.min_words_per_area,
    )
    seen: list[Page] = []
    ocr = ThreadPoolExecutor(max_workers=settings.ocr_workers)

    def checkpoint(result: DocumentResult | None = None) -> None:
        snapshot = result or DocumentResult(
            document=Document(
                id=document_id,
                file_name=file_name,
                file_type=file_type,
                file_hash=file_hash,
                page_count=len(seen),
                processed_at=datetime.now(UTC),
            ),
            stats=Stats(),
            markdown="",
            pages=list(seen),
            warnings=list(warnings),
        )
        temporary = working_dir / "checkpoint.tmp"
        temporary.write_text(rebuild_result(snapshot).model_dump_json(), encoding="utf-8")
        temporary.replace(working_dir / "checkpoint.json")
        progress = {
            "stage": f"reading_page_{len(seen)}" if result is None else "ocr",
            "progress": 0.1 if result is None else 0.65,
        }
        progress_temp = working_dir / "progress.tmp"
        progress_temp.write_text(json.dumps(progress))
        progress_temp.replace(working_dir / "progress.json")

    with ThreadPoolExecutor(max_workers=2) as checks:

        def on_page(page: Page) -> None:
            capture_page(page)
            seen.append(page)
            quality = checks.submit(evaluate_quality, page, config)
            try:
                with page_deadline(settings.per_page_timeout_seconds):
                    preview = render_page(
                        data,
                        file_type,
                        page.page_number,
                        max_pixels=settings.max_image_pixels,
                        result_page=page,
                        image_assets=image_assets,
                    )
                (working_dir / f"page-{page.page_number}.png").write_bytes(preview)
                page.quality = quality.result()
                with Image.open(io.BytesIO(preview)) as image:
                    sx, sy = image.width / max(page.width, 1), image.height / max(page.height, 1)
                    for block in page.blocks:
                        if block.type == "image":
                            crop = image.crop(
                                (
                                    block.bbox[0] * sx,
                                    block.bbox[1] * sy,
                                    block.bbox[2] * sx,
                                    block.bbox[3] * sy,
                                )
                            )
                            if block.id in image_assets:
                                with Image.open(io.BytesIO(image_assets[block.id])) as original:
                                    crop = original.convert("RGB").copy()
                            fingerprints[block.id] = hashlib.sha256(crop.tobytes()).hexdigest()
                            crop_name = f"{block.id}.png"
                            crop.save(working_dir / crop_name)
                            block.image_ref = f"/v1/jobs/{document_id}/images/{block.id}"
                    regions = select_regions(page, page.quality, config)
                    if regions and settings.ocr_enabled:
                        page.method = (
                            "mixed"
                            if any(b.type != "image" and b.text for b in page.blocks)
                            else "ocr"
                        )
                    for region in regions:
                        if not settings.ocr_enabled:
                            warnings.append(
                                Warning(
                                    page_number=page.page_number,
                                    code="ocr_disabled",
                                    message="This region needs OCR, which is disabled.",
                                )
                            )
                            continue
                        crop = image.crop(
                            (region[0] * sx, region[1] * sy, region[2] * sx, region[3] * sy)
                        )
                        matching_image = next(
                            (
                                b
                                for b in page.blocks
                                if b.type == "image" and b.bbox == region and b.id in image_assets
                            ),
                            None,
                        )
                        region_scale = sx
                        if matching_image is not None:
                            with Image.open(
                                io.BytesIO(image_assets[matching_image.id])
                            ) as original:
                                crop = original.convert("RGB").copy()
                            region_scale = crop.width / max(region[2] - region[0], 1)
                        enlargement = min(
                            max(1, settings.ocr_min_region_width / crop.width),
                            (settings.max_image_pixels / (crop.width * crop.height)) ** 0.5,
                        )
                        if enlargement != 1:
                            crop = crop.resize(
                                (
                                    max(1, round(crop.width * enlargement)),
                                    max(1, round(crop.height * enlargement)),
                                ),
                                Image.Resampling.LANCZOS,
                            )
                            region_scale *= enlargement
                        encoded = io.BytesIO()
                        crop.save(encoded, format="PNG")
                        future = ocr.submit(
                            recognize,
                            encoded.getvalue(),
                            page.page_number,
                            origin=(region[0], region[1]),
                            scale=region_scale,
                            model_dir=settings.ocr_model_dir,
                            max_table_cells=settings.ocr_table_max_cells,
                            table_timeout_seconds=min(
                                settings.ocr_table_timeout_seconds,
                                settings.per_page_timeout_seconds / 2,
                            ),
                        )
                        pending.append((page, future))
            except Exception as error:
                page.quality = quality.result()
                warnings.append(
                    Warning(
                        page_number=page.page_number,
                        code="page_timeout"
                        if isinstance(error, TimeoutError)
                        else "preview_unavailable",
                        message="This page could not be prepared for OCR or preview.",
                    )
                )

            checkpoint()

        result = read_document(
            data,
            file_type,
            file_name,
            file_hash,
            document_id,
            per_page_timeout_seconds=settings.per_page_timeout_seconds,
            max_pages=settings.max_pages,
            on_page=on_page,
            image_assets=image_assets,
            max_image_pixels=settings.max_image_pixels,
        )
        for index, (page, future) in enumerate(pending):
            try:
                blocks = future.result(timeout=settings.per_page_timeout_seconds)
                visible = [block for block in blocks if not block.is_decorative]
                if visible and all(len(block.text.strip()) <= 1 for block in visible):
                    warnings.append(
                        Warning(
                            page_number=page.page_number,
                            code="ambiguous_ocr_text",
                            message="Isolated OCR characters may be graphics; review the image.",
                        )
                    )
                for block in blocks:
                    if block.type == "table" and block.source == "ocr":
                        warnings.append(
                            Warning(
                                page_number=page.page_number,
                                code="ocr_table_review",
                                message="Table cells were read from visible image boundaries; "
                                "review clipped text and uncertain values.",
                            )
                        )
                    if block.markdown.startswith("```"):
                        warnings.append(
                            Warning(
                                page_number=page.page_number,
                                code="ocr_code_review",
                                message="Code was read from an image; review punctuation "
                                "before reuse.",
                            )
                        )
                    block.id = f"p{page.page_number}_ocr{index}_{block.id}"
                    if block.is_decorative:
                        warnings.append(
                            Warning(
                                page_number=page.page_number,
                                code="decorative_ocr_ignored",
                                message="A detected graphic mark was omitted from clean text.",
                            )
                        )
                    if (
                        block.confidence is not None
                        and block.confidence < settings.low_ocr_confidence
                    ):
                        warnings.append(
                            Warning(
                                page_number=page.page_number,
                                code="low_ocr_confidence",
                                message="OCR text has provisional low confidence.",
                            )
                        )
                if blocks:
                    warnings.extend(reconcile(page, blocks, settings.garbage_share_threshold))
                if not blocks:
                    warnings.append(
                        Warning(
                            page_number=page.page_number,
                            code="no_ocr_text",
                            message="OCR found no text in this flagged region.",
                        )
                    )
            except Exception as error:
                warnings.append(
                    Warning(
                        page_number=page.page_number,
                        code="page_timeout"
                        if isinstance(error, TimeoutError)
                        else "ocr_unavailable",
                        message="OCR could not finish this region; direct text was retained.",
                    )
                )
            checkpoint(result)
        result.warnings.extend(warnings)
    ocr.shutdown(wait=False, cancel_futures=True)
    result.pages = mark_decorative(
        result.pages, fingerprints, settings.decorative_max_area_fraction
    )
    result.pages = rank_headings(result.pages)
    for index, page in enumerate(result.pages):
        capture_page(page)
        page, table_warnings = detect_tables(page, page.ruling_lines, page.words or None)
        result.warnings.extend(table_warnings)
        ordered, layout_warnings = sort_page(attach_captions(prepare_page(page)))
        preview_path = working_dir / f"page-{page.page_number}.png"
        if file_type not in {"docx", "xlsx"} and preview_path.is_file():
            try:
                with Image.open(preview_path) as source_image:
                    ordered = detect_connectors(source_image, ordered)
            except (OSError, ValueError):
                result.warnings.append(
                    Warning(
                        page_number=page.page_number,
                        code="connectors_unavailable",
                        message="Arrow relationships could not be inspected; text was retained.",
                    )
                )
        result.pages[index] = ordered
        result.warnings.extend(layout_warnings)
    result = sanitize_document(result)
    result.stats.duration_seconds = time.monotonic() - started
    return rebuild_result(result)
