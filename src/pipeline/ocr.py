"""Local RapidOCR/ONNX adapter with lazy per-thread engine ownership."""

from __future__ import annotations

import io
import math
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image

from rag_pre_ingest.models.document import Block, Observation
from rag_pre_ingest.pipeline.ocr_cards import card_regions
from rag_pre_ingest.pipeline.ocr_code import (
    code_line_crops,
    code_text,
    looks_like_code,
    preserves_code_content,
    recover_bracket,
)
from rag_pre_ingest.pipeline.ocr_icons import leading_icon_edge
from rag_pre_ingest.pipeline.ocr_lists import (
    has_left_text_fragment,
    has_visual_bullet,
    is_decorative_arrow,
    is_decorative_circle,
    is_symbol_only,
    normalize_list_prefix,
)
from rag_pre_ingest.pipeline.raster_ocr import recognize_grid
from rag_pre_ingest.pipeline.raster_tables import RasterGridConfig, detect_raster_grids

_local = threading.local()


def _get_engine(model_dir: Path | None) -> Any:
    cache: dict[str, Any] = getattr(_local, "engines", {})
    key = str(model_dir.resolve()) if model_dir is not None else ""
    if key not in cache:
        import onnxruntime

        onnxruntime.disable_telemetry_events()
        import rapidocr
        from rapidocr import RapidOCR

        params: dict[str, object] = {
            "EngineConfig.onnxruntime.intra_op_num_threads": 1,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "Global.log_level": "warning",
            # Preserve uncertain lines so the pipeline can surface their confidence.
            "Global.text_score": 0.0,
            "Global.use_det": True,
            "Global.use_rec": True,
        }
        bundled = model_dir is None
        directory = Path(rapidocr.__file__).parent / "models" if bundled else model_dir
        assert directory is not None
        filenames = (
            ("Det", "PP-OCRv6_det_small.onnx" if bundled else "det.onnx"),
            ("Cls", "ch_ppocr_mobile_v2.0_cls_mobile.onnx" if bundled else "cls.onnx"),
            ("Rec", "PP-OCRv6_rec_small.onnx" if bundled else "rec.onnx"),
        )
        for stage, filename in filenames:
            path = directory / filename
            if not path.is_file():
                raise FileNotFoundError(f"Local OCR model is missing: {filename}")
            params[f"{stage}.model_path"] = str(path.resolve())
        cache[key] = RapidOCR(params=params)
        _local.engines = cache
    return cache[key]


def recognize(
    image: bytes,
    page_number: int,
    origin: tuple[float, float] = (0, 0),
    scale: float = 1,
    model_dir: Path | None = None,
    max_table_cells: int = 1024,
    table_timeout_seconds: float = 10,
    detect_cards: bool = True,
) -> list[Block]:
    """Map OCR pixel quadrilaterals back to page coordinates; callers isolate failures.

    ``scale`` is rendered pixels per page unit, and ``origin`` is the crop's
    top-left corner in page units. No image or document is sent to a remote API.
    """
    if scale <= 0 or not math.isfinite(scale):
        raise ValueError("OCR scale must be finite and positive.")
    if page_number < 1:
        raise ValueError("Page numbers start at one.")
    result = _get_engine(model_dir)(image)
    boxes, texts, scores = result.boxes, result.txts, result.scores
    if boxes is None or texts is None or len(boxes) == 0 or len(texts) == 0:
        return []
    if scores is None or len(boxes) != len(texts) or len(scores) != len(texts):
        raise ValueError("OCR returned inconsistent result lengths.")
    raw_observations = tuple(
        Observation(
            id=f"p{page_number}_raw_{origin[0]}_{origin[1]}_{index}",
            text=str(text),
            bbox=(
                min(float(p[0]) for p in points) / scale + origin[0],
                min(float(p[1]) for p in points) / scale + origin[1],
                max(float(p[0]) for p in points) / scale + origin[0],
                max(float(p[1]) for p in points) / scale + origin[1],
            ),
            source="ocr",
            confidence=float(score),
        )
        for index, (points, text, score) in enumerate(zip(boxes, texts, scores, strict=True))
    )
    line_context = [
        (
            (
                min(float(p[0]) for p in points),
                min(float(p[1]) for p in points),
                max(float(p[0]) for p in points),
                max(float(p[1]) for p in points),
            ),
            str(content),
        )
        for points, content in zip(boxes, texts, strict=True)
        if len(points) > 0
    ]
    try:
        with Image.open(io.BytesIO(image)) as source:
            pixels: Image.Image | None = source.convert("RGB")
    except (OSError, ValueError):
        # OCR stubs and alternative decoders may return usable text without Pillow pixels.
        pixels = None
    raster_blocks: list[Block] = []
    table_deadline = time.monotonic() + table_timeout_seconds
    if pixels is not None and max_table_cells > 0:
        for index, grid in enumerate(
            detect_raster_grids(pixels, config=RasterGridConfig(max_cells=max_table_cells)), 1
        ):
            try:
                table = recognize_grid(
                    pixels,
                    grid,
                    _get_engine(model_dir),
                    page_number,
                    origin,
                    scale,
                    index,
                    deadline=table_deadline,
                )
                if table is not None:
                    raster_blocks.append(table)
            except TimeoutError:
                break
            except Exception:
                # Preserve original OCR when optional cell reconstruction fails.
                continue
    if (
        pixels is not None
        and not raster_blocks
        and looks_like_code([text for _, text in line_context])
    ):
        engine = _get_engine(model_dir)
        flags = {name: getattr(engine, name) for name in ("use_det", "use_cls", "use_rec")}
        lines = []
        confidences = []
        try:
            for box, crop in code_line_crops(pixels, line_context):
                recognized = engine(crop, use_det=False, use_cls=False, use_rec=True)
                if recognized.txts and recognized.txts[0].strip():
                    lines.append((box, recover_bracket(crop, recognized.txts[0].strip())))
                    confidences.append(float(recognized.scores[0]))
        except Exception:
            # An optional line reconstruction failure must not lose the initial OCR.
            lines = []
        finally:
            engine.update_params(**flags)
        # Decline reconstruction if it would discard existing readable lines.
        if preserves_code_content([text for _, text in line_context], [text for _, text in lines]):
            text = code_text(lines)
            bounds = (
                min(box[0] for box, _ in lines) / scale + origin[0],
                min(box[1] for box, _ in lines) / scale + origin[1],
                max(box[2] for box, _ in lines) / scale + origin[0],
                max(box[3] for box, _ in lines) / scale + origin[1],
            )
            return [
                Block(
                    id=f"p{page_number}_ocr_code",
                    type="paragraph",
                    text=text,
                    markdown="```python\n" + text + "\n```",
                    bbox=bounds,
                    source="ocr",
                    confidence=min(confidences),
                    observations=raw_observations,
                    observation_ids=tuple(o.id for o in raw_observations),
                )
            ]
    for table in raster_blocks:
        table.observations = tuple(
            o
            for o in raw_observations
            if table.bbox[0] <= (o.bbox[0] + o.bbox[2]) / 2 <= table.bbox[2]
            and table.bbox[1] <= (o.bbox[1] + o.bbox[3]) / 2 <= table.bbox[3]
        )
        table.observation_ids = tuple(o.id for o in table.observations)
    star_candidates = [
        box
        for box, _ in line_context
        if pixels is not None
        and has_visual_bullet(pixels, box, allow_stars=True)
        and not has_visual_bullet(pixels, box)
    ]
    repeated_stars = {
        box
        for box in star_candidates
        if sum(
            abs(other[0] - box[0]) < (box[3] - box[1]) * 0.25
            and abs(other[1] - box[1]) < (box[3] - box[1]) * 5
            for other in star_candidates
        )
        >= 3
    }
    blocks: list[Block] = []
    for index, (points, raw_text, raw_score) in enumerate(
        zip(boxes, texts, scores, strict=True), 1
    ):
        text = str(raw_text).strip()
        if not text:
            continue
        xs = [float(point[0]) / scale + origin[0] for point in points]
        ys = [float(point[1]) / scale + origin[1] for point in points]
        score = float(raw_score)
        if not xs or not ys or not all(math.isfinite(value) for value in (*xs, *ys, score)):
            raise ValueError("OCR returned invalid coordinates or confidence.")
        pixel_box = (
            min(float(point[0]) for point in points),
            min(float(point[1]) for point in points),
            max(float(point[0]) for point in points),
            max(float(point[1]) for point in points),
        )
        center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        if any(
            table.bbox[0] <= center[0] <= table.bbox[2]
            and table.bbox[1] <= center[1] <= table.bbox[3]
            for table in raster_blocks
        ):
            continue
        icon_only = False
        if pixels is not None:
            edge = leading_icon_edge(pixels, pixel_box)
            if edge is not None and edge >= pixel_box[2] - 4:
                icon_only = True
            elif edge is not None:
                crop = pixels.crop(
                    (int(edge + 2), int(pixel_box[1]), int(pixel_box[2]), int(pixel_box[3]))
                )
                reread = _get_engine(model_dir)(crop, use_det=False, use_cls=False, use_rec=True)
                if reread.txts and reread.txts[0].strip():
                    text = reread.txts[0].strip()
                    xs = [edge / scale + origin[0], max(xs)]
                    pixel_box = (edge, pixel_box[1], pixel_box[2], pixel_box[3])
        nontext = is_symbol_only(text)
        is_list = False
        if not nontext:
            is_list, text = normalize_list_prefix(
                text,
                has_visual_bullet(pixels, pixel_box) or pixel_box in repeated_stars
                if pixels is not None and not has_left_text_fragment(pixel_box, line_context)
                else False,
            )
        if not text:
            continue
        decorative = (
            icon_only
            or nontext
            or (
                (
                    is_decorative_circle(pixels, pixel_box, text)
                    or is_decorative_arrow(pixels, pixel_box, text)
                )
                if pixels is not None
                else False
            )
        )
        blocks.append(
            Block(
                id=f"p{page_number}_ocr{index}",
                type="other" if decorative else "list" if is_list else "paragraph",
                text=text,
                markdown="" if decorative else "- " + text if is_list else text,
                bbox=(min(xs), min(ys), max(xs), max(ys)),
                confidence=max(0.0, min(1.0, score)),
                source="ocr",
                is_decorative=decorative,
                observation_ids=(raw_observations[index - 1].id,),
                observations=(raw_observations[index - 1],),
            )
        )
    if pixels is not None and detect_cards and not raster_blocks:
        panels = card_regions(pixels)
        for number, box in enumerate(panels):
            bounds = (
                origin[0] + box[0] / scale,
                origin[1] + box[1] / scale,
                origin[0] + box[2] / scale,
                origin[1] + box[3] / scale,
            )
            # Decline replacing lines crossing a panel boundary.
            inside = [
                b
                for b in blocks
                if bounds[0] <= (b.bbox[0] + b.bbox[2]) / 2 <= bounds[2]
                and bounds[1] <= (b.bbox[1] + b.bbox[3]) / 2 <= bounds[3]
            ]
            if any(b.bbox[0] < bounds[0] or b.bbox[2] > bounds[2] for b in inside):
                continue
            if not inside:
                continue
            # The adapter proposes boundaries only. Grouping and reading order
            # belong to the shared layout preparation stage.
            for block in inside:
                block.region_id = f"p{page_number}_card{number}"
                block.region_kind = "card"
                block.region_bbox = bounds
                block.merge_locked = True
    return blocks + raster_blocks
