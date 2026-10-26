from __future__ import annotations

import io
import runpy
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from rag_pre_ingest.pipeline.readers import read_document

ROOT = Path(__file__).resolve().parents[2]


def read_fixture(name: str):
    return read_document(
        (ROOT / "tests/fixtures/synthetic" / name).read_bytes(), "pdf", name, "", ""
    )


@pytest.mark.parametrize(
    ("name", "expected_lines"),
    [("04-ruled-table.pdf", 8), ("05-merged-grid.pdf", 8), ("06-unruled-table.pdf", 0)],
)
def test_real_table_geometry(name: str, expected_lines: int) -> None:
    result = read_fixture(name)
    page = result.pages[0]
    assert len(page.ruling_lines) == expected_lines
    assert len(page.words) >= 7
    assert not any(w.code == "corrupted_block" for w in result.warnings)
    assert all(word.font_size == 14 for word in page.words)
    assert all(0 <= word.bbox[0] < word.bbox[2] <= page.width for word in page.words)
    assert all(0 <= word.bbox[1] < word.bbox[3] <= page.height for word in page.words)
    assert all(line[0] == line[2] or line[1] == line[3] for line in page.ruling_lines)


def test_numeric_punctuation_is_one_word() -> None:
    page = read_fixture("04-ruled-table.pdf").pages[0]
    assert "9.50" in [word.text for word in page.words]
    assert "9" not in [word.text for word in page.words]


def test_blocks_keep_dominant_font_attributes() -> None:
    page = read_fixture("01-clean.pdf").pages[0]
    assert page.blocks[0].font_size == 22
    assert page.blocks[1].font_size == 14
    assert page.blocks[0].font_weight is None or page.blocks[0].font_weight > 0
    assert "Clean document title" in page.blocks[0].text


def create_pdf(commands: str) -> bytes:
    helper = runpy.run_path(str(ROOT / "scripts/generate_fixtures.py"))["pdf"]
    return helper([commands])


def test_path_matrix_is_applied_before_page_rotation() -> None:
    data = create_pdf("q 2 0 0 2 10 20 cm 10 10 m 100 10 l S Q")
    result = read_document(data, "pdf", "", "", "")
    assert result.pages[0].ruling_lines == [(30, 752, 210, 752)]
    output = io.BytesIO()
    with pdfium.PdfDocument(data) as source:
        page = source[0]
        page.set_rotation(90)
        page.close()
        source.save(output)
    rotated = read_document(output.getvalue(), "pdf", "", "", "").pages[0]
    assert rotated.width == 792
    assert rotated.height == 612
    assert rotated.ruling_lines == [(40, 30, 40, 210)]


def test_curves_diagonals_and_fill_only_paths_are_not_rulings() -> None:
    data = create_pdf("10 10 m 50 50 l S\n10 10 m 20 30 40 50 60 70 c S\n100 100 20 20 re f")
    result = read_document(data, "pdf", "", "", "")
    assert not result.pages[0].ruling_lines
    assert not any(w.code == "corrupted_block" for w in result.warnings)


def test_stroked_rectangle_has_all_four_edges() -> None:
    data = create_pdf("100 100 200 100 re S")
    page = read_document(data, "pdf", "", "", "").pages[0]
    assert len(page.ruling_lines) == 4
    assert (100, 692, 300, 692) in page.ruling_lines
