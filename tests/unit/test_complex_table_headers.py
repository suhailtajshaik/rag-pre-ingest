from pathlib import Path

import pytest

from rag_pre_ingest.models.document import Block, Page
from rag_pre_ingest.pipeline.readers import read_document
from rag_pre_ingest.pipeline.tables import detect_tables


def text(name: str, value: str, x: float, y: float, bold: bool = False) -> Block:
    return Block(
        id=name,
        type="paragraph",
        text=value,
        bbox=(x, y, x + 30, y + 10),
        font_weight=700 if bold else 400,
    )


def test_two_tier_merged_headers_mark_all_source_header_cells() -> None:
    # Column zero spans both header tiers; columns one/two have a shared top label.
    lines = (
        [(0, y, 300, y) for y in [0, 40, 60]]
        + [(100, 20, 300, 20)]
        + [
            (0, 0, 0, 60),
            (100, 0, 100, 60),
            (200, 20, 200, 60),
            (300, 0, 300, 60),
        ]
    )
    words = [
        text("category", "Category", 10, 10),
        text("results", "Results", 120, 5),
        text("accuracy", "Accuracy", 110, 25),
        text("time", "Time", 210, 25),
        text("blind", "Blind", 10, 45),
        text("num", "1", 110, 45),
        text("secs", "2", 210, 45),
    ]
    result, warnings = detect_tables(
        Page(page_number=1, width=300, height=100, blocks=words), lines
    )
    assert not warnings
    cells = result.blocks[0].cells
    assert cells[0].row_span == 2
    assert cells[1].col_span == 2
    assert all(cell.is_header for cell in cells if cell.row < 2)
    assert all(not cell.is_header for cell in cells if cell.row == 2)


@pytest.mark.parametrize("bold", [False, True])
def test_single_row_body_requires_typographic_header_evidence(bold: bool) -> None:
    words = [
        text("first", "Actual content", 10, 10, bold),
        text("second", "Other content", 110, 10, bold),
    ]
    lines = [(0, 0, 200, 0), (0, 30, 200, 30)] + [(x, 0, x, 30) for x in [0, 100, 200]]
    result, warnings = detect_tables(
        Page(page_number=1, width=200, height=100, blocks=words), lines
    )
    assert not warnings
    table = result.blocks[0]
    assert all(cell.is_header is bold for cell in table.cells)
    if not bold:
        assert table.markdown.splitlines()[0] == "|  |  |"
        assert table.markdown.splitlines()[2] == "| Actual content | Other content |"


def test_cached_public_pdf_retains_six_columns_and_two_header_tiers() -> None:
    path = Path("tests/fixtures/public/.cache/w3c-complex-table.pdf")
    if not path.is_file():
        pytest.skip("Download the attributed public corpus to run its original-byte regression.")
    document = read_document(path.read_bytes(), "pdf", path.name, "hash", "id")
    page = document.pages[0]
    assert page.ruling_lines
    result, warnings = detect_tables(page, page.ruling_lines, page.words)
    assert not warnings
    tables = [block for block in result.blocks if block.type == "table"]
    assert len(tables) == 1
    table = tables[0]
    assert (table.rows, table.columns) == (6, 6)
    assert [(cell.row_span, cell.col_span) for cell in table.cells[:5]] == [(2, 1)] * 4 + [(1, 2)]
    assert all(cell.is_header for cell in table.cells if cell.row < 2)
    assert next(cell for cell in table.cells if cell.row == 1 and cell.col == 4).text == "Accuracy"
    assert (
        next(cell for cell in table.cells if cell.row == 1 and cell.col == 5).text
        == "Time to\ncomplete"
    )
    assert (
        next(cell for cell in table.cells if cell.row == 3 and cell.col == 4).text
        == "98.3% n=2\n(97.7%, n=3)"
    )


def test_empty_isolated_checkbox_is_not_a_table() -> None:
    lines = [(0, 0, 10, 0), (0, 10, 10, 10), (0, 0, 0, 10), (10, 0, 10, 10)]
    page = Page(
        page_number=1, width=300, height=300, blocks=[text("label", "Checkbox label", 20, 0)]
    )
    result, warnings = detect_tables(page, lines)
    assert not warnings
    assert all(block.type != "table" for block in result.blocks)


def test_text_bearing_single_cell_is_retained() -> None:
    lines = [(0, 0, 100, 0), (0, 30, 100, 30), (0, 0, 0, 30), (100, 0, 100, 30)]
    page = Page(page_number=1, width=300, height=300, blocks=[text("content", "Content", 10, 10)])
    result, warnings = detect_tables(page, lines)
    assert not warnings
    assert result.blocks[0].type == "table"
    assert result.blocks[0].cells[0].text == "Content"
