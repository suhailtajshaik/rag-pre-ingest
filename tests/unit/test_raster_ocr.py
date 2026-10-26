import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PIL import Image, ImageDraw

from rag_pre_ingest.config import Settings
from rag_pre_ingest.pipeline import ocr
from rag_pre_ingest.pipeline.engine import run_pipeline
from rag_pre_ingest.pipeline.raster_ocr import cell_crop, is_column_strip, recognize_grid
from rag_pre_ingest.pipeline.raster_tables import RasterGrid


@pytest.mark.parametrize(
    "values,expected",
    [
        (["A", "B", "C", "D"], True),
        (["A", "B", "C", "O", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "0"], True),
        (["Name", "Price", "Qty", "Region"], False),
        (["A", "B"], False),
        (["1", "2", "3", "4"], False),
    ],
)
def test_spreadsheet_chrome_has_strong_sequential_letter_evidence(
    values: list[str], expected: bool
) -> None:
    assert is_column_strip(values) == expected


def test_blank_cell_pixels_produce_no_recognition_crop() -> None:
    image = Image.new("RGB", (80, 40), "white")
    ImageDraw.Draw(image).rectangle((0, 0, 79, 39), outline="gray")
    assert cell_crop(image, (0, 0, 80, 40)) is None
    assert cell_crop(image, (0, 0, 2, 2)) is None


def test_cell_recognition_preserves_blank_column_and_restores_engine_flags() -> None:
    image = Image.new("RGB", (240, 80), "white")
    draw = ImageDraw.Draw(image)
    for x, y in [(10, 10), (90, 10), (170, 10), (10, 50), (170, 50)]:
        draw.text((x, y), "Ink", fill="black")
    engine = Mock(use_det=True, use_cls=True, use_rec=True)
    engine.side_effect = [
        SimpleNamespace(txts=(text,), scores=(0.95,))
        for text in ["Name", "Blank", "Value", "A", "7"]
    ]
    table = recognize_grid(
        image, RasterGrid((0, 80, 160, 240), (0, 40, 80)), engine, 2, (10, 20), 2, 1
    )
    assert table is not None
    assert table.bbox == (10, 20, 130, 60)
    assert [(c.row, c.col, c.text) for c in table.cells][-3:] == [
        (1, 0, "A"),
        (1, 1, ""),
        (1, 2, "7"),
    ]
    assert table.source == "ocr"
    assert engine.call_count == 5
    engine.update_params.assert_called_once_with(use_det=True, use_cls=True, use_rec=True)


def test_actual_spreadsheet_screenshot_keeps_numeric_cells_in_their_columns(tmp_path: Path) -> None:
    path = Path("tests/fixtures/user_samples/sales-sheet.png")
    with patch("socket.socket.connect", side_effect=AssertionError("Local OCR only")):
        result = run_pipeline(
            path.read_bytes(), "png", path.name, "hash", "test", Settings(), tmp_path
        )
    tables = [b for p in result.pages for b in p.blocks if b.type == "table"]
    assert len(tables) == 1
    table = tables[0]
    assert (table.rows, table.columns) == (31, 9)
    values = {(c.row, c.col): c.text for c in table.cells}
    assert [values[(0, c)] for c in range(9)] == [
        "Transaction ID",
        "Date",
        "Product Category",
        "Product Name",
        "Units Sold",
        "Unit Price",
        "Total Revenue",
        "Region",
        "Payment Method",
    ]
    assert [values[(r, 0)] for r in range(1, 31)] == [str(10000 + r) for r in range(1, 31)]
    assert [values[(2, c)] for c in range(9)] == [
        "10002",
        "2024-01-02",
        "Home Appliances",
        "Dyson V11 Vacuum",
        "1",
        "499.99",
        "499.99",
        "Europe",
        "PayPal",
    ]
    assert values[(8, 5)] == "599.99"
    assert values[(12, 4)] == "3"
    assert values[(20, 5)] == "99.99"
    assert values[(30, 6)] == "259.98"
    assert values[(30, 8)] == "Credit Card"
    assert any(w.code == "ocr_table_review" for w in result.warnings)


def test_expired_cell_budget_restores_detector_configuration() -> None:
    engine = Mock(use_det=True, use_cls=True, use_rec=True)
    with pytest.raises(TimeoutError):
        recognize_grid(
            Image.new("RGB", (80, 80), "white"),
            RasterGrid((0, 40, 80), (0, 40, 80)),
            engine,
            1,
            (0, 0),
            1,
            1,
            deadline=0,
        )
    engine.assert_not_called()
    engine.update_params.assert_called_once_with(use_det=True, use_cls=True, use_rec=True)


def test_optional_table_timeout_keeps_original_ocr_text() -> None:
    image = io.BytesIO()
    Image.new("RGB", (80, 80), "white").save(image, format="PNG")
    result = SimpleNamespace(
        boxes=[[[10, 10], [60, 10], [60, 30], [10, 30]]], txts=["Original value"], scores=[0.99]
    )
    with (
        patch.object(ocr, "_get_engine", return_value=Mock(return_value=result)),
        patch.object(
            ocr, "detect_raster_grids", return_value=[RasterGrid((0, 40, 80), (0, 40, 80))]
        ),
        patch.object(ocr, "recognize_grid", side_effect=TimeoutError()),
    ):
        blocks = ocr.recognize(image.getvalue(), 1)
    assert [b.text for b in blocks] == ["Original value"]
