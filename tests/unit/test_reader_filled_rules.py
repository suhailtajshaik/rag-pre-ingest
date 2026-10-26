"""Filled PDF rectangles must become centerlines after all coordinate transforms."""

import io
import runpy
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from rag_pre_ingest.pipeline.readers import _filled_rectangle_line, read_document

ROOT = Path(__file__).parents[2]


def pdf(commands: str) -> bytes:
    return runpy.run_path(str(ROOT / "scripts/generate_fixtures.py"))["pdf"]([commands])


def test_filled_horizontal_vertical_and_fill_stroke_rules_have_one_centerline_each() -> None:
    data = pdf("100 100 200 0.5 re f\n100 200 0.5 100 re f\n300 100 100 1 re B")
    lines = read_document(data, "pdf", "", "", "").pages[0].ruling_lines
    assert lines == [
        (100, 691.75, 300, 691.75),
        (100.25, 492, 100.25, 592),
        (300, 691.5, 400, 691.5),
    ]


def test_filled_rule_transforms_then_crop_and_rotation() -> None:
    data = pdf("q 2 0 0 2 10 20 cm 10 10 100 0.5 re f Q")
    assert read_document(data, "pdf", "", "", "").pages[0].ruling_lines == [(30, 751.5, 230, 751.5)]
    output = io.BytesIO()
    with pdfium.PdfDocument(data) as document:
        page = document[0]
        page.set_cropbox(20, 30, 500, 700)
        page.set_rotation(90)
        page.close()
        document.save(output)
    assert read_document(output.getvalue(), "pdf", "", "", "").pages[0].ruling_lines == [
        (10.5, 10, 10.5, 210)
    ]


def test_large_fills_diagonals_and_triangles_are_not_table_rules() -> None:
    data = pdf(
        "100 100 20 20 re f\n100 100 m 200 100 l 100 101 l f\n"
        "100 100 m 200 105 l 200 106 l 100 101 l h f"
    )
    assert read_document(data, "pdf", "", "", "").pages[0].ruling_lines == []
    assert _filled_rectangle_line([(0, 0), (100, 0), (100, 0.5), (0, 0.5)]) == (0, 0.25, 100, 0.25)


def test_public_complex_table_uses_filled_ruling_rectangles() -> None:
    path = ROOT / "tests/fixtures/public/.cache/w3c-complex-table.pdf"
    if not path.exists():
        pytest.skip("Optional downloaded public corpus is not present.")
    result = read_document(path.read_bytes(), "pdf", path.name, "", "")
    assert len(result.pages[0].ruling_lines) == 78
    assert not result.warnings
