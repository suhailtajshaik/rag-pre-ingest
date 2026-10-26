from rag_pre_ingest.models.document import Block, Page
from rag_pre_ingest.pipeline.layout import sort_page
from rag_pre_ingest.pipeline.readers import read_document
from rag_pre_ingest.pipeline.sanitizer import sanitize_document
from rag_pre_ingest.pipeline.structure import prepare_document_layout


def fragment(identifier: str, text: str, box: tuple[float, float, float, float]) -> Block:
    return Block(id=identifier, type="paragraph", text=text, markdown=text, bbox=box, source="ocr")


def test_shuffled_jittered_headers_with_fullpage_image_stay_left_to_right() -> None:
    page = Page(
        page_number=1,
        width=780,
        height=360,
        blocks=[
            fragment("dark", "DARK", (400, 9, 450, 25)),
            Block(id="image", type="image", bbox=(0, 0, 780, 360)),
            fragment("light", "LIGHT", (40, 12, 100, 28)),
        ],
    )
    result, warnings = sort_page(page)
    assert [block.text for block in result.blocks if block.type != "image"] == ["LIGHT", "DARK"]
    assert not warnings
    assert result.blocks[0].type == "image"


def test_footer_fragments_merge_in_correct_order_without_column_merge() -> None:
    result = read_document(b"bad", "pdf", "palette", "hash", "id")
    page = Page(
        page_number=1,
        width=780,
        height=360,
        blocks=[
            fragment("tail", "trustworthy, organic", (150, 279, 310, 295)),
            fragment("cal", "Notion Cal.com", (130, 309, 270, 325)),
            Block(id="image", type="image", bbox=(0, 0, 780, 360)),
            fragment("vibe", "Vibe: Calm,", (40, 281, 138, 297)),
            fragment("like", "Like: Loom", (40, 311, 119, 327)),
        ],
    )
    result.pages = [sort_page(page)[0]]
    cleaned = sanitize_document(prepare_document_layout(result))
    assert cleaned.markdown == "Vibe: Calm, trustworthy, organic\n\nLike: Loom Notion Cal.com"
    assert len([block for block in cleaned.pages[0].blocks if block.type == "paragraph"]) == 2


def test_distinct_column_paragraphs_keep_column_order() -> None:
    page = Page(
        page_number=1,
        width=780,
        height=500,
        blocks=[
            fragment("right2", "Right second", (400, 150, 600, 170)),
            fragment("left2", "Left second", (40, 150, 240, 170)),
            fragment("right1", "Right first", (400, 100, 600, 120)),
            fragment("left1", "Left first", (40, 100, 240, 120)),
            Block(id="image", type="image", bbox=(0, 0, 780, 500)),
        ],
    )
    ordered, _ = sort_page(page)
    assert [b.text for b in ordered.blocks if b.type != "image"] == [
        "Left first",
        "Left second",
        "Right first",
        "Right second",
    ]
    result = read_document(b"bad", "pdf", "columns", "h", "id")
    result.pages = [ordered]
    clean = sanitize_document(prepare_document_layout(result))
    assert len([b for b in clean.pages[0].blocks if b.type == "paragraph"]) == 4


def test_same_row_large_gutter_does_not_merge_columns() -> None:
    result = read_document(b"bad", "pdf", "columns", "h", "id")
    page = Page(
        page_number=1,
        width=780,
        height=360,
        blocks=[
            fragment("left", "LIGHT", (40, 11, 100, 27)),
            fragment("right", "DARK", (400, 9, 450, 25)),
        ],
    )
    result.pages = [sort_page(page)[0]]
    assert sanitize_document(prepare_document_layout(result)).markdown == "LIGHT\n\nDARK"


def test_overlapping_ocr_fragments_join_without_duplicated_boundary_letter() -> None:
    from rag_pre_ingest.pipeline.sanitizer import _merge_wrapped

    page = Page(
        page_number=1,
        width=780,
        height=360,
        blocks=[
            Block(
                id="first",
                type="paragraph",
                text="Vibe: Calm, t",
                source="ocr",
                bbox=(40, 280, 215, 308),
            ),
            Block(
                id="next",
                type="paragraph",
                text="trustworthy, organic",
                source="ocr",
                bbox=(199, 280, 610, 308),
            ),
        ],
    )
    result = _merge_wrapped(page)
    assert result.blocks[0].text == "Vibe: Calm, trustworthy, organic"
    assert len(result.blocks) == 1
