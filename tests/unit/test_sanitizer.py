from pathlib import Path

import pytest

from rag_pre_ingest.models.document import Block, Cell, Page
from rag_pre_ingest.pipeline.readers import read_document
from rag_pre_ingest.pipeline.sanitizer import (
    collapse_blank_lines,
    join_lines,
    normalize_lists,
    normalize_unicode,
    rank_headings,
    render_table,
    repair_hyphens,
    sanitize_document,
    strip_repeating,
)
from rag_pre_ingest.pipeline.structure import prepare_document_layout


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ﬁancée\u00a0€  café", "fiancée € café"),
        ("中文 العربية हिन्दी", "中文 العربية हिन्दी"),
        ("text\x00\r\nnext\t word", "text\nnext word"),
    ],
)
def test_normalize_unicode(value: str, expected: str) -> None:
    assert normalize_unicode(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("A broken\nline\n\nNew paragraph", "A broken line\n\nNew paragraph"),
        ("# Heading\nBody\n- first\n- second", "# Heading\nBody\n- first\n- second"),
        ("para-\ngraph", "para-\ngraph"),
    ],
)
def test_join_lines(value: str, expected: str) -> None:
    assert join_lines(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("para\u00ad\ngraph", "paragraph"),
        ("para-\ngraph", "paragraph"),
        ("well-\nknown", "well-known"),
        ("state-of-\nthe-art", "state-of-the-art"),
        ("re-\nenter", "re-enter"),
        ("a well-known phrase", "a well-known phrase"),
    ],
)
def test_repair_hyphens(value: str, expected: str) -> None:
    assert repair_hyphens(value) == expected


def test_normalize_lists() -> None:
    assert normalize_lists("• One\n◦ Two\n1) Three\n2. Four") == "- One\n- Two\n1. Three\n2. Four"


def test_table_rendering_preserves_empty_covered_slots_and_unicode() -> None:
    cells = [Cell(row=0, col=0, text="A|B", col_span=2), Cell(row=1, col=1, text="€ 中文")]
    assert render_table(cells, 2, 2) == "| A\\|B |  |\n| --- | --- |\n|  | € 中文 |"
    assert render_table([], 0, 0) == ""


def test_collapse_blank_lines() -> None:
    assert collapse_blank_lines("\nA\n\n\n\nB\n") == "A\n\nB"


def test_headerless_multiline_table_does_not_emit_html_or_promote_data() -> None:
    cells = [
        Cell(row=0, col=0, text="Data Engineer\n(ML-focused)"),
        Cell(row=0, col=1, text="SQL\nand Python"),
    ]
    assert render_table(cells, 1, 2, header=False) == (
        "|  |  |\n| --- | --- |\n| Data Engineer (ML-focused) | SQL and Python |"
    )
    assert cells[0].text == "Data Engineer\n(ML-focused)"


def text(name: str, y: float, value: str, size: float = 12) -> Block:
    return Block(
        id=name,
        type="paragraph",
        bbox=(10, y, 200, y + 15),
        text=value,
        markdown=value,
        font_size=size,
    )


def test_documentwide_heading_rank_and_existing_levels() -> None:
    page = Page(
        page_number=1,
        width=600,
        height=800,
        blocks=[
            text("title", 100, "Title", 24),
            text("subtitle", 140, "Subtitle", 18),
            text("body", 180, "Long body content " * 20),
            Block(
                id="existing",
                type="heading",
                level=3,
                text="Word heading",
                bbox=(10, 300, 200, 320),
            ),
        ],
    )
    result = rank_headings([page])[0]
    assert [(b.type, b.level) for b in result.blocks] == [
        ("heading", 1),
        ("heading", 2),
        ("paragraph", None),
        ("heading", 3),
    ]
    assert page.blocks[0].type == "paragraph"


def test_repeated_fixture_keeps_body_and_records_margin_blocks() -> None:
    name = "02-repeated.pdf"
    result = read_document(
        (Path("tests/fixtures/synthetic") / name).read_bytes(), "pdf", name, "h", "id"
    )
    cleaned = sanitize_document(prepare_document_layout(result))
    assert "ACME report" not in cleaned.markdown
    assert "Confidential" not in cleaned.markdown
    assert all(f"Unique content for section {n}" in cleaned.markdown for n in [1, 2, 3])
    assert sum(b.type == "header" for p in cleaned.pages for b in p.blocks) == 3
    assert sum(b.type == "footer" for p in cleaned.pages for b in p.blocks) == 6
    assert all(b.type == "paragraph" for p in result.pages for b in p.blocks)


def test_repeated_body_is_not_stripped() -> None:
    pages = [
        Page(page_number=i, width=600, height=800, blocks=[text(str(i), 350, "Repeated body")])
        for i in [1, 2, 3]
    ]
    assert all(p.blocks[0].type == "paragraph" for p in strip_repeating(pages))


def test_real_hyphen_wrap_fixture() -> None:
    name = "11-hyphen-wrap.pdf"
    result = read_document(
        (Path("tests/fixtures/synthetic") / name).read_bytes(), "pdf", name, "h", "id"
    )
    cleaned = sanitize_document(prepare_document_layout(result))
    assert "A broken paragraph continues here." in cleaned.markdown
    assert "A real well-known phrase." in cleaned.markdown
    assert "\u00ad" not in cleaned.markdown


def test_sanitize_keeps_images_out_and_builds_heading_path() -> None:
    result = read_document(b"bad", "pdf", "file", "h", "id")
    result.pages = [
        Page(
            page_number=1,
            width=600,
            height=800,
            blocks=[
                Block(
                    id="heading", type="heading", level=1, text="Title", bbox=(10, 100, 200, 120)
                ),
                text("list", 150, "• entry"),
                Block(
                    id="image", type="image", markdown="![placeholder]()", bbox=(10, 300, 200, 400)
                ),
            ],
        )
    ]
    cleaned = sanitize_document(prepare_document_layout(result))
    assert cleaned.markdown == "# Title\n\n- entry"
    assert cleaned.pages[0].blocks[1].type == "list"
    assert cleaned.pages[0].blocks[1].heading_path == ["Title"]


def test_captions_and_columns_do_not_merge() -> None:
    result = read_document(b"bad", "pdf", "file", "h", "id")
    first, second = text("first", 100, "Column one"), text("second", 120, "Column two")
    second.bbox = (350, 120, 550, 135)
    caption = text("caption", 140, "Caption")
    caption.source = "caption"
    result.pages = [Page(page_number=1, width=600, height=800, blocks=[first, second, caption])]
    cleaned = sanitize_document(prepare_document_layout(result))
    assert len(cleaned.pages[0].blocks) == 3


def test_ambiguous_line_hyphen_is_flagged() -> None:
    result = read_document(b"bad", "pdf", "file", "h", "id")
    result.pages = [
        Page(
            page_number=1,
            width=600,
            height=800,
            blocks=[
                text("first", 100, "a provisional para-\ngraph"),
            ],
        )
    ]
    cleaned = sanitize_document(prepare_document_layout(result))
    assert "a provisional paragraph" in cleaned.markdown
    assert any(w.code == "hyphenation_uncertain" for w in cleaned.warnings)


def test_bold_body_size_short_heading_is_ranked() -> None:
    heading = text("heading", 100, "Section")
    heading.font_weight = 700
    page = Page(
        page_number=1,
        width=600,
        height=800,
        blocks=[
            heading,
            text("body", 150, "A longer body paragraph providing the baseline size."),
        ],
    )
    ranked = rank_headings([page])[0]
    assert ranked.blocks[0].type == "heading"
    assert ranked.blocks[0].level == 1


def test_existing_ocr_list_keeps_markdown_marker() -> None:
    from datetime import UTC, datetime

    from rag_pre_ingest.models.document import Document, DocumentResult, Stats

    document = Document(
        id="id",
        file_name="a.png",
        file_type="png",
        file_hash="hash",
        page_count=1,
        processed_at=datetime.now(UTC),
    )
    page = Page(
        page_number=1,
        width=100,
        height=100,
        blocks=[
            Block(
                id="list",
                type="list",
                text="Recognized item",
                markdown="- Recognized item",
                source="ocr",
                bbox=(10, 10, 90, 20),
            )
        ],
    )
    result = sanitize_document(
        DocumentResult(document=document, stats=Stats(), markdown="", pages=[page])
    )
    assert result.markdown == "- Recognized item"
