from pathlib import Path

from rag_pre_ingest.models.document import Block, Page
from rag_pre_ingest.pipeline.layout import attach_captions, reading_order, sort_page
from rag_pre_ingest.pipeline.readers import read_document


def block(name: str, box: tuple[float, float, float, float], kind: str = "paragraph") -> Block:
    return Block(id=name, type=kind, text=name, markdown=name, bbox=box)  # type: ignore[arg-type]


def test_column_order_with_top_and_middle_fullwidth_dividers() -> None:
    blocks = [
        block("title", (0, 0, 600, 30)),
        block("left1", (0, 60, 200, 80)),
        block("left2", (0, 100, 200, 120)),
        block("right1", (350, 60, 550, 80)),
        block("right2", (350, 100, 550, 120)),
        block("middle", (0, 150, 600, 180)),
        block("lower-left", (0, 220, 200, 240)),
        block("lower-right", (350, 220, 550, 240)),
    ]
    ordered, warnings = reading_order(list(reversed(blocks)), 600, 800)
    assert [b.id for b in ordered] == [b.id for b in blocks]
    assert warnings == []


def test_single_column_top_to_bottom() -> None:
    blocks = [block("second", (10, 60, 200, 80)), block("first", (10, 10, 200, 30))]
    ordered, warnings = reading_order(blocks, 600, 800)
    assert [b.id for b in ordered] == ["first", "second"]
    assert not warnings


def test_overlap_is_stable_warns_and_does_not_mutate_input() -> None:
    page = Page(
        page_number=3,
        width=600,
        height=800,
        blocks=[
            block("z", (10, 10, 100, 100)),
            block("a", (10, 10, 100, 100)),
        ],
    )
    result, warnings = sort_page(page)
    assert [b.id for b in result.blocks] == ["a", "z"]
    assert all(b.layout_confidence == 0.4 for b in result.blocks)
    assert [b.confidence for b in result.blocks] == [b.confidence for b in page.blocks]
    assert warnings[0].code == "reading_order_uncertain"
    assert warnings[0].page_number == 3
    assert all(b.confidence is None for b in page.blocks)


def test_real_two_column_fixture() -> None:
    data = Path("tests/fixtures/synthetic/03-two-columns.pdf").read_bytes()
    page = read_document(data, "pdf", "columns.pdf", "h", "id").pages[0]
    page.blocks.reverse()
    result, _ = sort_page(page)
    assert [b.text for b in result.blocks] == [
        "Full width heading",
        "Left first paragraph",
        "Left second paragraph",
        "Right first paragraph",
        "Right second paragraph",
    ]


def test_caption_fixture_keeps_plain_caption_and_pure_input() -> None:
    data = Path("tests/fixtures/synthetic/09-caption.pdf").read_bytes()
    page = read_document(data, "pdf", "caption.pdf", "h", "id").pages[0]
    result = attach_captions(page)
    image = next(b for b in result.blocks if b.type == "image")
    caption = next(b for b in result.blocks if b.type == "paragraph")
    assert image.caption == "Figure 1: Invoice sample"
    assert caption.source == "caption"
    assert caption.markdown == caption.text
    assert all(b.source == "read" for b in page.blocks)


def test_inside_image_ocr_and_distant_text_are_not_captions() -> None:
    image = block("image", (100, 100, 400, 300), "image")
    inside = block("inside", (120, 130, 350, 170))
    inside.source = "ocr"
    distant = block("distant", (100, 400, 350, 420))
    page = Page(page_number=1, width=600, height=800, blocks=[image, inside, distant])
    result = attach_captions(page)
    assert result.blocks[0].caption is None


def test_beside_caption() -> None:
    page = Page(
        page_number=1,
        width=600,
        height=800,
        blocks=[
            block("image", (100, 100, 300, 300), "image"),
            block("caption", (310, 110, 500, 130)),
        ],
    )
    assert attach_captions(page).blocks[0].caption == "caption"


def test_image_containing_ocr_is_not_uncertain_overlap() -> None:
    image = block("image", (10, 10, 400, 400), "image")
    text = block("ocr", (30, 30, 300, 60))
    text.source = "ocr"
    ordered, warnings = reading_order([text, image], 600, 800)
    assert {b.id for b in ordered} == {"image", "ocr"}
    assert not warnings
    assert all(b.confidence is None for b in ordered)
