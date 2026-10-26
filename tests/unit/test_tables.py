from pathlib import Path

import pytest

from rag_pre_ingest.models.document import Block, Cell, Page
from rag_pre_ingest.pipeline.readers import read_document
from rag_pre_ingest.pipeline.tables import detect_tables


def word(name: str, x: float, y: float, text: str) -> Block:
    return Block(id=name, type="paragraph", bbox=(x, y, x + 20, y + 10), text=text, markdown=text)


def grid(merged: bool = False) -> list[tuple[float, float, float, float]]:
    return [(x, 132, x, 252 if merged and x == 200 else 312) for x in [40, 200, 360, 520]] + [
        (40, y, 520, y) for y in [132, 192, 252, 312]
    ]


@pytest.mark.parametrize("merged", [False, True])
def test_real_ruled_fixture_retains_blank_and_merged_cells(merged: bool) -> None:
    name = "05-merged-grid.pdf" if merged else "04-ruled-table.pdf"
    page = read_document(
        (Path("tests/fixtures/synthetic") / name).read_bytes(), "pdf", name, "h", "id"
    ).pages[0]
    original = page.model_dump()
    result, warnings = detect_tables(page, grid(merged))
    assert page.model_dump() == original
    assert not warnings
    table = next(b for b in result.blocks if b.type == "table")
    assert (table.rows, table.columns) == (3, 3)
    assert next(c for c in table.cells if c.row == 1 and c.col == 1).text == ""
    assert next(c for c in table.cells if c.row == 2 and c.col == 0).col_span == (
        2 if merged else 1
    )
    assert "| Widget |  | 9.50 |" in table.markdown
    assert all(row.count("|") == 4 for row in table.markdown.splitlines())
    assert sum(b.type == "paragraph" for b in result.blocks) == 0


def test_real_unruled_fixture() -> None:
    name = "06-unruled-table.pdf"
    page = read_document(
        (Path("tests/fixtures/synthetic") / name).read_bytes(), "pdf", name, "h", "id"
    ).pages[0]
    result, warnings = detect_tables(page, [])
    assert not warnings
    table = next(b for b in result.blocks if b.type == "table")
    assert table.rows == 3 and table.columns == 3
    assert "| Bolts | 2 | 10.00 |" in table.markdown


@pytest.mark.parametrize("source", ["read", "ocr"])
def test_reconstructed_table_preserves_source(source: str) -> None:
    blocks = [
        word(f"{row}-{col}", col * 100, row * 30, value)
        for row, values in enumerate(
            [["Item", "Qty", "Price"], ["A", "1", "2.00"], ["B", "2", "3.00"]]
        )
        for col, value in enumerate(values)
    ]
    for block in blocks:
        block.source = source  # type: ignore[assignment]
    result, warnings = detect_tables(Page(page_number=1, width=400, height=300, blocks=blocks), [])
    assert not warnings
    assert result.blocks[0].type == "table"
    assert result.blocks[0].source == source


def test_vertical_merge_and_jittered_lines() -> None:
    lines = [
        (0, 0, 200, 0),
        (0, 100, 200, 100),
        (100, 50, 200, 50),
        (0, 0, 0, 100),
        (100.5, 0, 100.5, 100),
        (200, 0, 200, 100),
    ]
    page = Page(page_number=1, width=300, height=200, blocks=[word("a", 10, 10, "Merged")])
    result, warnings = detect_tables(page, lines)
    assert not warnings
    cell = next(c for c in result.blocks[0].cells if c.row == 0 and c.col == 0)
    assert cell.row_span == 2 and cell.col_span == 1
    assert cell.text == "Merged"


def test_two_column_prose_is_not_fabricated_as_table() -> None:
    blocks = [
        word(str(row) + str(col), col * 150, row * 30, "This is a substantial prose paragraph")
        for row in range(3)
        for col in range(2)
    ]
    page = Page(page_number=1, width=500, height=800, blocks=blocks)
    result, warnings = detect_tables(page, [])
    assert all(b.type == "paragraph" for b in result.blocks)
    assert any(w.code == "table_inconsistent" for w in warnings)


def test_unruled_blank_cells_never_shift() -> None:
    blocks = [
        word(f"{row}-{col}", col * 100, row * 30, value)
        for row, values in enumerate(
            [["Item", "Qty", "Price"], ["A", "1", "2.00"], ["B", "", "3.00"], ["C", "2", "4.00"]]
        )
        for col, value in enumerate(values)
        if value
    ]
    result, _ = detect_tables(Page(page_number=1, width=400, height=300, blocks=blocks), [])
    table = result.blocks[0]
    assert table.cells[7].text == ""
    assert table.cells[8].text == "3.00"


def test_existing_office_table_is_preserved() -> None:
    block = Block(
        id="table",
        type="table",
        bbox=(0, 0, 100, 100),
        rows=1,
        columns=2,
        cells=[Cell(row=0, col=0, text="merged", col_span=2)],
    )
    page = Page(page_number=1, width=100, height=100, blocks=[block])
    result, warnings = detect_tables(page, [])
    assert result.model_dump() == page.model_dump()
    assert not warnings


def test_disconnected_tables_do_not_merge_into_one_grid() -> None:
    lines = [(x, y, x + 100, y) for y in [0, 50, 200, 250] for x in [0]] + [
        (x, y, x, y + 50) for y in [0, 200] for x in [0, 50, 100]
    ]
    page = Page(
        page_number=1,
        width=200,
        height=300,
        blocks=[
            word("first", 10, 10, "A"),
            word("second", 10, 210, "B"),
        ],
    )
    result, _ = detect_tables(page, lines)
    assert len([b for b in result.blocks if b.type == "table"]) == 2


def test_mostly_numeric_column_mismatch_warns() -> None:
    lines = [(0, y, 100, y) for y in [0, 20, 40, 60, 80]] + [(x, 0, x, 80) for x in [0, 50, 100]]
    blocks = [
        word(str(index), 60, index * 20 + 2, value)
        for index, value in enumerate(["Total", "1.00", "bad", "3.00"])
    ]
    result, warnings = detect_tables(
        Page(page_number=1, width=100, height=100, blocks=blocks), lines
    )
    assert result.blocks[0].type == "table"
    assert any("numeric" in warning.message for warning in warnings)


@pytest.mark.parametrize(
    "name", ["04-ruled-table.pdf", "05-merged-grid.pdf", "06-unruled-table.pdf"]
)
def test_real_pdf_geometry_reconstructs_table(name: str) -> None:
    page = read_document(
        (Path("tests/fixtures/synthetic") / name).read_bytes(), "pdf", name, "h", "id"
    ).pages[0]
    result, warnings = detect_tables(page, page.ruling_lines, page.words)
    assert not warnings
    table = next(b for b in result.blocks if b.type == "table")
    assert (table.rows, table.columns) == (3, 3)
    if name == "05-merged-grid.pdf":
        assert next(c for c in table.cells if c.row == 2 and c.col == 0).col_span == 2
    if name != "06-unruled-table.pdf":
        assert "| Widget |  | 9.50 |" in table.markdown
