"""Shared extraction evidence, region ownership and explicit layout preparation."""

from __future__ import annotations

from rag_pre_ingest.models.document import Block, DocumentResult, Observation, Page, Region


def can_merge(left: Block, right: Block) -> bool:
    """A layout merge must respect both ownership and explicit boundaries."""
    return not (left.merge_locked or right.merge_locked) and left.region_id == right.region_id


def combine_provenance(target: Block, other: Block) -> None:
    """Union source references when a derived block consumes another block."""
    target.observation_ids = tuple(dict.fromkeys((*target.observation_ids, *other.observation_ids)))
    evidence = {o.id: o for o in (*target.observations, *other.observations)}
    target.observations = tuple(evidence.values())


def capture_page(page: Page) -> None:
    """Register evidence once; further layout changes cannot overwrite it."""
    evidence = {o.id: o for o in page.observations}
    for block in page.blocks:
        if not block.observations:
            block.observations = (
                Observation(
                    id=block.id,
                    text=block.text,
                    bbox=block.bbox,
                    source=block.source,
                    confidence=block.confidence,
                ),
            )
        for observation in block.observations:
            evidence.setdefault(observation.id, observation)
        block.observation_ids = tuple(o.id for o in block.observations)
    page.observations = tuple(evidence.values())


def resolve_regions(page: Page) -> Page:
    """Resolve accepted container boundaries conservatively, smallest owner first.

    Only explicit card/table/image boundaries propose regions. A crossing block is
    left unassigned and locked against merges; overlapping proposals cannot silently
    move its text into a neighboring container.
    """
    result = page.model_copy(deep=True)
    proposals: dict[str, Region] = {r.id: r for r in result.regions}
    for block in result.blocks:
        kind = block.region_kind or (block.type if block.type in {"table", "image"} else None)
        if kind in {"card", "table", "image", "text"}:
            region_id = block.region_id or f"region:{block.id}"
            previous = proposals.get(region_id)
            region = Region(
                id=region_id,
                kind=kind,
                bbox=block.region_bbox or block.bbox,
                observation_ids=tuple(
                    dict.fromkeys(
                        (*(previous.observation_ids if previous else ()), *block.observation_ids)
                    )
                ),
                confidence=block.layout_confidence,
            )
            proposals[region_id] = region
            block.region_id, block.region_kind = region.id, region.kind
            block.merge_locked = True
    regions = sorted(
        proposals.values(), key=lambda r: ((r.bbox[2] - r.bbox[0]) * (r.bbox[3] - r.bbox[1]), r.id)
    )
    for block in result.blocks:
        if block.region_id:
            continue
        x0, y0, x1, y1 = block.bbox
        for region in regions:
            a, b, c, d = region.bbox
            if a <= x0 <= x1 <= c and b <= y0 <= y1 <= d:
                block.region_id, block.region_kind = region.id, region.kind
                break
            if min(x1, c) > max(x0, a) and min(y1, d) > max(y0, b):
                block.merge_locked = True
    result.regions = tuple(regions)
    return result


def consolidate_cards(page: Page) -> Page:
    """Resolve proposed card membership centrally, preserving raw observations."""
    from rag_pre_ingest.pipeline.layout import reading_order

    result = page.model_copy(deep=True)
    groups: dict[str, list[Block]] = {}
    for block in result.blocks:
        if block.region_kind == "card" and block.region_id:
            groups.setdefault(block.region_id, []).append(block)
    consumed: set[str] = set()
    replacements: list[Block] = []
    for region_id, members in groups.items():
        # Order the observations within the region, without recursively treating
        # every line as a completed card.
        parts = [b.model_copy(deep=True) for b in members]
        for part in parts:
            part.region_kind = None
        ordered, _ = reading_order(parts, page.width, page.height)
        text = " ".join(b.text for b in ordered if not b.is_decorative)
        if not text:
            continue
        combined = members[0].model_copy(deep=True)
        for member in members[1:]:
            combine_provenance(combined, member)
        combined.id = region_id.replace("_card", "_ocr_card")
        combined.text = combined.markdown = text
        combined.type = "paragraph"
        combined.bbox = combined.region_bbox or (
            min(b.bbox[0] for b in members),
            min(b.bbox[1] for b in members),
            max(b.bbox[2] for b in members),
            max(b.bbox[3] for b in members),
        )
        scores = [b.confidence for b in members if b.confidence is not None]
        combined.confidence = min(scores) if scores else None
        combined.is_decorative = False
        consumed.update(b.id for b in members)
        replacements.append(combined)
    result.blocks = [b for b in result.blocks if b.id not in consumed] + replacements
    return result


def prepare_page(page: Page) -> Page:
    """Perform geometric joins explicitly before the final reading-order pass."""
    from rag_pre_ingest.pipeline.layout_preparation import (
        _merge_wrapped,
        merge_list_continuations,
        merge_stacked_labels,
    )

    result = page.model_copy(deep=True)
    capture_page(result)
    result = resolve_regions(result)
    result = consolidate_cards(result)
    result = merge_stacked_labels(result)
    from rag_pre_ingest.pipeline.layout import sort_page

    result, _ = sort_page(result)
    return _merge_wrapped(merge_list_continuations(result))


def prepare_document_layout(document: DocumentResult) -> DocumentResult:
    """Compatibility helper for consumers running sanitizer outside the engine."""
    result = document.model_copy(deep=True)
    from rag_pre_ingest.pipeline.sanitizer import rank_headings

    result.pages = [prepare_page(page) for page in rank_headings(result.pages)]
    return result
