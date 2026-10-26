"""Cross-stage contracts rather than document-specific string exceptions."""

import pytest
from pydantic import ValidationError

from rag_pre_ingest.models.document import Block, Page, Region
from rag_pre_ingest.pipeline.engine import reconcile
from rag_pre_ingest.pipeline.layout import sort_page
from rag_pre_ingest.pipeline.readers import read_document
from rag_pre_ingest.pipeline.sanitizer import sanitize_document
from rag_pre_ingest.pipeline.structure import (
    can_merge,
    capture_page,
    prepare_document_layout,
    prepare_page,
    resolve_regions,
)


def paragraph(name: str, text: str, y: float = 10, **kwargs: object) -> Block:
    return Block(id=name, type="paragraph", text=text, bbox=(10, y, 100, y + 10), **kwargs)


def test_observations_immutable_and_not_replaced_after_cleanup() -> None:
    page = Page(page_number=1, width=200, height=200, blocks=[paragraph("a", "ﬁrst")])
    capture_page(page)
    evidence = page.observations[0]
    with pytest.raises(ValidationError):
        evidence.text = "changed"
    page.blocks[0].text = "first"
    capture_page(page)
    assert page.observations[0].text == "ﬁrst"


def test_region_boundary_is_independent_of_block_name() -> None:
    left = paragraph("ordinary-name", "left", region_id="left")
    right = paragraph("another-name", "right", region_id="right")
    assert not can_merge(left, right)
    right.region_id = left.region_id
    assert can_merge(left, right)
    left.merge_locked = True
    assert not can_merge(left, right)


def test_smallest_region_owns_text_crossing_regions_lock() -> None:
    page = Page(
        page_number=1,
        width=200,
        height=200,
        blocks=[paragraph("a", "label")],
        regions=(
            Region(id="outer", kind="image", bbox=(0, 0, 200, 200)),
            Region(id="inner", kind="card", bbox=(5, 5, 110, 40)),
        ),
    )
    result = resolve_regions(page)
    assert result.blocks[0].region_id == "inner"
    assert page.blocks[0].region_id is None
    page.blocks[0].bbox = (0, 10, 150, 20)
    page.regions = (page.regions[1],)
    assert resolve_regions(page).blocks[0].merge_locked


def test_layout_uncertainty_never_changes_recognition_score() -> None:
    page = Page(
        page_number=1,
        width=200,
        height=200,
        blocks=[paragraph("a", "one", confidence=0.99), paragraph("b", "two", confidence=0.97)],
    )
    result, warnings = sort_page(page)
    assert warnings
    assert [b.confidence for b in result.blocks] == [0.99, 0.97]
    assert all(b.layout_confidence == 0.4 for b in result.blocks)


def test_sanitizer_changes_text_without_geometry_or_membership() -> None:
    document = read_document(b"bad", "pdf", "test", "hash", "id")
    document.pages = [
        Page(
            page_number=1,
            width=200,
            height=200,
            blocks=[paragraph("a", "ﬁrst"), paragraph("b", "second", 22)],
        )
    ]
    cleaned = sanitize_document(document)
    assert [b.id for b in cleaned.pages[0].blocks] == ["a", "b"]
    assert [b.bbox for b in cleaned.pages[0].blocks] == [b.bbox for b in document.pages[0].blocks]
    assert cleaned.pages[0].blocks[0].text == "first"


def test_explicit_preparation_merges_with_complete_evidence() -> None:
    page = Page(
        page_number=1,
        width=200,
        height=200,
        blocks=[paragraph("b", "second", 22), paragraph("a", "first")],
    )
    prepared = prepare_page(page)
    assert len(prepared.blocks) == 1
    assert set(prepared.blocks[0].observation_ids) == {"a", "b"}
    assert len(prepared.observations) == 2
    assert len(page.blocks) == 2


def test_disagreeing_ocr_retained_as_evidence_when_native_wins() -> None:
    page = Page(page_number=1, width=200, height=200, blocks=[paragraph("native", "good text")])
    warnings = reconcile(page, [paragraph("ocr", "bad text", source="ocr", confidence=0.8)])
    assert warnings
    assert page.blocks[0].text == "good text"
    assert {o.text for o in page.observations} == {"good text", "bad text"}


def test_document_preparation_pure() -> None:
    document = read_document(b"bad", "pdf", "test", "hash", "id")
    document.pages = [Page(page_number=1, width=200, height=200, blocks=[paragraph("a", "first")])]
    result = prepare_document_layout(document)
    assert result.pages[0].observations
    assert not document.pages[0].observations
