"""Pure conservative decoration marking from size and identical repeated crops."""

from collections import defaultdict

from rag_pre_ingest.models.document import Page


def mark_decorative(
    pages: list[Page], fingerprints: dict[str, str], max_area_fraction: float = 0.02
) -> list[Page]:
    copies = [page.model_copy(deep=True) for page in pages]
    repeated: dict[str, set[int]] = defaultdict(set)
    for page in copies:
        for block in page.blocks:
            if block.type == "image" and block.id in fingerprints:
                area = max(0, block.bbox[2] - block.bbox[0]) * max(0, block.bbox[3] - block.bbox[1])
                if area / max(1, page.width * page.height) <= max_area_fraction:
                    repeated[fingerprints[block.id]].add(page.page_number)
    for page in copies:
        decorative = []
        for block in page.blocks:
            if (
                block.type == "image"
                and len(repeated.get(fingerprints.get(block.id, ""), set())) >= 2
            ):
                block.is_decorative = True
                block.ocr_text = None
                decorative.append(block)
        page.blocks = [
            block
            for block in page.blocks
            if not (
                block.source == "ocr"
                and any(
                    image.bbox[0] <= block.bbox[0] <= block.bbox[2] <= image.bbox[2]
                    and image.bbox[1] <= block.bbox[1] <= block.bbox[3] <= image.bbox[3]
                    for image in decorative
                )
            )
        ]
    return copies
