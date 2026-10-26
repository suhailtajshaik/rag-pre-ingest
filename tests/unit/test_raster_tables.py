from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from rag_pre_ingest.pipeline.raster_tables import RasterGridConfig, detect_raster_grids


def draw_grid(image: Image.Image, xs: list[int], ys: list[int], colour: str | int = "gray") -> None:
    draw = ImageDraw.Draw(image)
    for x in xs:
        draw.line((x, ys[0], x, ys[-1]), fill=colour)
    for y in ys:
        draw.line((xs[0], y, xs[-1], y), fill=colour)


@pytest.mark.parametrize("colour", ["black", "#e5e4e5"])
def test_empty_raster_cells_retain_full_grid_without_text(colour: str) -> None:
    image = Image.new("RGB", (500, 350), "white")
    draw_grid(image, [40, 140, 260, 400], [80, 140, 200, 260], colour)
    original = image.tobytes()
    grids = detect_raster_grids(image)
    assert len(grids) == 1
    grid = grids[0]
    assert grid.xs == (40, 140, 260, 400)
    assert grid.ys == (80, 140, 200, 260)
    assert len(grid.cells) == 9
    assert grid.cells[4].bbox == (140, 140, 260, 200)
    assert grid.cells[4].row == 1 and grid.cells[4].col == 1
    assert len(grid.lines) == 8
    assert image.tobytes() == original


def test_raster_coordinates_map_to_source_page_units() -> None:
    image = Image.new("RGB", (500, 350), "white")
    draw_grid(image, [40, 140, 260, 400], [80, 140, 200, 260])
    grid = detect_raster_grids(image, page_width=1000, page_height=700)[0]
    assert grid.bbox == (80, 160, 800, 520)
    assert grid.cells[0].bbox == (80, 160, 280, 280)


def test_disconnected_grids_do_not_invent_cells_in_the_gap() -> None:
    image = Image.new("RGB", (700, 350), "white")
    draw_grid(image, [40, 140, 240], [80, 160, 240])
    draw_grid(image, [400, 500, 600], [80, 160, 240])
    grids = detect_raster_grids(image)
    assert len(grids) == 2
    assert [grid.bbox for grid in grids] == [(40, 80, 240, 240), (400, 80, 600, 240)]


def test_filled_background_and_isolated_ui_boxes_are_not_tables() -> None:
    image = Image.new("RGB", (700, 500), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 650, 150), fill="#e0e0e0")
    for x in [50, 250, 450]:
        draw.rectangle((x, 250, x + 120, 280), outline="gray")
    assert detect_raster_grids(image) == []


def test_broken_gray_vertical_recovers_using_consistent_column_support() -> None:
    image = Image.new("RGB", (550, 500), "white")
    xs, ys = [40, 160, 280, 400, 500], list(range(80, 441, 30))
    draw_grid(image, xs, ys, "#e0e0e0")
    draw = ImageDraw.Draw(image)
    for y in ys[:-1]:
        draw.line((280, y + 10, 280, y + 18), fill="white")
    grid = detect_raster_grids(image)[0]
    assert 280 in grid.xs
    assert grid.columns == 4


def test_safe_cell_budget_rejects_overlarge_grids() -> None:
    image = Image.new("RGB", (500, 350), "white")
    draw_grid(image, [40, 140, 260, 400], [80, 140, 200, 260])
    assert detect_raster_grids(image, config=RasterGridConfig(max_cells=8)) == []


def test_actual_sales_sheet_retains_all_nine_content_column_boundaries() -> None:
    path = Path("tests/fixtures/user_samples/sales-sheet.png")
    with Image.open(path) as image:
        grids = detect_raster_grids(image)
    assert len(grids) == 1
    grid = grids[0]
    assert grid.columns == 15 and grid.rows == 32
    for actual, expected in zip(
        grid.xs[:10], [40, 136, 231, 363, 503, 598, 693, 788, 884, 1003], strict=True
    ):
        assert abs(actual - expected) <= 1
    assert grid.ys[0] == 131.5
    assert grid.ys[1] == 153
    assert grid.ys[-1] == 766.5
    assert grid.clipped_bottom


@pytest.mark.parametrize(
    "name",
    [
        "notebooklm-mind-map.png",
        "theme-cards.png",
        "theme-palette.png",
        "numbered-questions.png",
        "python-code.png",
        "hackathon-guidelines.png",
        "llm-flowchart.png",
    ],
)
def test_other_user_samples_do_not_form_false_raster_grids(name: str) -> None:
    with Image.open(Path("tests/fixtures/user_samples") / name) as image:
        assert detect_raster_grids(image) == []


def test_connected_diagram_lines_do_not_invent_full_dividers() -> None:
    image = Image.new("RGB", (600, 600), "white")
    draw = ImageDraw.Draw(image)
    # A connected ladder with short branches is not a rectangular cell grid.
    draw.line((80, 80, 80, 500), fill="gray")
    draw.line((500, 80, 500, 500), fill="gray")
    for y in (80, 280, 500):
        draw.line((80, y, 500, y), fill="gray")
    draw.line((280, 80, 280, 180), fill="gray")
    assert detect_raster_grids(image) == []
