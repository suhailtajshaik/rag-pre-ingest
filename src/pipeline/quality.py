"""Pure per-page OCR signals; thresholds are provisional configuration values."""

from dataclasses import dataclass

from rag_pre_ingest.models.document import Page, Quality

BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class QualityConfig:
    near_empty_characters: int = 5
    garbage_share_threshold: float = 0.01
    image_coverage_threshold: float = 0.8
    min_words_per_area: float = 0.00002


def garbage_share(text: str) -> float:
    """Count broken glyphs and common multi-character UTF-8 decoding artifacts."""
    if not text:
        return 0.0
    bad: set[int] = set()
    for index, char in enumerate(text):
        code = ord(char)
        if (
            char == "\ufffd"
            or 0xE000 <= code <= 0xF8FF
            or 0xF0000 <= code <= 0xFFFFD
            or 0x100000 <= code <= 0x10FFFD
            or 0xD800 <= code <= 0xDFFF
        ):
            bad.add(index)
        if char in {"Ã", "Â"} and index + 1 < len(text) and 0x80 <= ord(text[index + 1]) <= 0xBF:
            bad.update((index, index + 1))
        if text[index : index + 2] in {"â€", "ðŸ", "ï¿"}:
            bad.update(range(index, min(index + 3, len(text))))
    return len(bad) / len(text)


def _image_regions(page: Page) -> list[BBox]:
    regions: list[BBox] = []
    for block in page.blocks:
        if block.type != "image" or block.is_decorative:
            continue
        x0, y0, x1, y1 = block.bbox
        box = (max(0.0, x0), max(0.0, y0), min(page.width, x1), min(page.height, y1))
        if box[2] > box[0] and box[3] > box[1] and box not in regions:
            regions.append(box)
    return regions


def union_area(boxes: list[BBox]) -> float:
    """Exact axis-aligned rectangle union by a sweep; overlapping images count once."""
    valid = [box for box in boxes if box[2] > box[0] and box[3] > box[1]]
    xs = sorted({x for box in valid for x in (box[0], box[2])})
    area = 0.0
    for left, right in zip(xs, xs[1:], strict=False):
        intervals = sorted((b[1], b[3]) for b in valid if b[0] < right and b[2] > left)
        height = 0.0
        end = float("-inf")
        for low, high in intervals:
            height += max(0.0, high - max(low, end))
            end = max(end, high)
        area += (right - left) * height
    return area


def evaluate_quality(page: Page, config: QualityConfig) -> Quality:
    text = "\n".join(block.text for block in page.blocks if block.type != "image").strip()
    area = max(0.0, page.width) * max(0.0, page.height)
    regions = _image_regions(page)
    coverage = min(1.0, union_area(regions) / area) if area else 0.0
    garbage = garbage_share(text)
    density = len(text.split()) / area if area else 0.0
    reasons: list[str] = []
    if garbage > config.garbage_share_threshold:
        reasons.append("garbage_characters")
    if regions and coverage >= config.image_coverage_threshold:
        reasons.append("image_coverage")
        if len(text) <= config.near_empty_characters:
            reasons.append("near_empty_text")
    if regions and density < config.min_words_per_area:
        reasons.append("sparse_text")
    if regions:
        reasons.append("image_regions")
    return Quality(
        character_count=len(text),
        garbage_share=garbage,
        image_coverage=coverage,
        words_per_area=density,
        needs_ocr=bool(reasons),
        reasons=reasons,
    )


def select_regions(page: Page, quality: Quality, config: QualityConfig | None = None) -> list[BBox]:
    """Prefer known image and damaged-text bounds; a scan itself may span a page."""
    if not quality.needs_ocr or page.width <= 0 or page.height <= 0:
        return []
    regions = _image_regions(page)
    if "garbage_characters" in quality.reasons:
        threshold = (config or QualityConfig()).garbage_share_threshold
        damaged = [
            block.bbox
            for block in page.blocks
            if block.type != "image" and garbage_share(block.text) > threshold
        ]
        regions.extend(damaged or [(0.0, 0.0, page.width, page.height)])
    unique = list(dict.fromkeys(regions))
    return [
        box
        for box in unique
        if not any(
            other != box
            and other[0] <= box[0]
            and other[1] <= box[1]
            and other[2] >= box[2]
            and other[3] >= box[3]
            for other in unique
        )
    ]
