"""Cell-bounded local OCR for visible raster grids; source values are never inferred."""

from __future__ import annotations

import time
from statistics import median
from typing import Any, cast

from PIL import Image, ImageChops, ImageOps

from rag_pre_ingest.models.document import Block, Cell
from rag_pre_ingest.pipeline.raster_tables import RasterGrid
from rag_pre_ingest.pipeline.readers import render_table
from rag_pre_ingest.pipeline.spreadsheet import trim_empty_tails


def is_column_strip(values: list[str]) -> bool:
    """Recognize a contiguous spreadsheet letter strip without dropping its text."""
    populated = [value.strip() for value in values]
    return (
        len(populated) >= 4
        and all(len(value) == 1 for value in populated)
        and sum(value == chr(65 + i) for i, value in enumerate(populated)) >= len(populated) * 0.8
    )


def cell_crop(image: Image.Image, box: tuple[float, float, float, float]) -> Image.Image | None:
    """Exclude ruling pixels, skip blank cells, and enlarge small visible glyphs."""
    x0, y0, x1, y1 = box
    inset = max(2, round(min(x1 - x0, y1 - y0) * 0.1))
    if min(x1 - x0, y1 - y0) <= inset * 2:
        return None
    crop = image.crop(
        (round(x0) + inset, round(y0) + inset, round(x1) - inset, round(y1) - inset)
    ).convert("RGB")
    corners = [
        cast(tuple[int, int, int], crop.getpixel(point))
        for point in [
            (0, 0),
            (crop.width - 1, 0),
            (0, crop.height - 1),
            (crop.width - 1, crop.height - 1),
        ]
    ]
    background = tuple(int(median(color[i] for color in corners)) for i in range(3))
    difference = ImageChops.difference(crop, Image.new("RGB", crop.size, background)).convert("L")
    if cast(tuple[int, int], difference.getextrema())[1] < 35:
        return None
    factor = max(1, 48 / crop.height)
    crop = crop.resize(
        (max(1, round(crop.width * factor)), max(1, round(crop.height * factor))),
        Image.Resampling.LANCZOS,
    )
    return ImageOps.expand(crop, border=4, fill=background)


def recognize_grid(
    image: Image.Image,
    grid: RasterGrid,
    engine: Any,
    page_number: int,
    origin: tuple[float, float],
    scale: float,
    identifier: int,
    deadline: float | None = None,
) -> Block | None:
    """Recognize each nonempty cell separately, preserving blank column positions."""
    values = [[""] * grid.columns for _ in range(grid.rows)]
    scores: list[float] = []
    flags = {name: getattr(engine, name) for name in ("use_det", "use_cls", "use_rec")}
    try:
        for cell in grid.cells:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Cell OCR budget exhausted; retain original observations.")
            crop = cell_crop(image, cell.bbox)
            if crop is None:
                continue
            recognition = engine(crop, use_det=False, use_cls=False, use_rec=True)
            if recognition.txts and recognition.txts[0].strip():
                values[cell.row][cell.col] = recognition.txts[0].strip()
                scores.append(float(recognition.scores[0]))
            else:
                scores.append(0)
    finally:
        engine.update_params(**flags)
    start = 1 if values and is_column_strip(values[0]) else 0
    if start and len(values) > 1:
        # Spreadsheet grids extend beyond the logical table. A populated header
        # bounds sparse UI overlays in otherwise empty trailing columns; their
        # original OCR observations remain outside the resulting table bounds.
        header_columns = [i for i, value in enumerate(values[1]) if value]
        if len(header_columns) >= 2:
            header_end = max(header_columns) + 1
            if all(
                sum(bool(row[col]) for row in values[2:]) <= max(1, len(values) * 0.1)
                for col in range(header_end, grid.columns)
            ):
                values = [row[:header_end] for row in values]
    rows = trim_empty_tails(values[start:], [])
    if len(rows) < 2 or not rows[0] or not any(any(row) for row in rows):
        return None
    columns = len(rows[0])
    cells = [
        Cell(row=r, col=c, text=text, is_header=r == 0)
        for r, row in enumerate(rows)
        for c, text in enumerate(row)
    ]
    markdown = render_table(rows)
    bounds = (grid.xs[0], grid.ys[start], grid.xs[columns], grid.ys[start + len(rows)])
    return Block(
        id=f"p{page_number}_raster_table{identifier}",
        type="table",
        text=markdown,
        markdown=markdown,
        bbox=(
            bounds[0] / scale + origin[0],
            bounds[1] / scale + origin[1],
            bounds[2] / scale + origin[0],
            bounds[3] / scale + origin[1],
        ),
        rows=len(rows),
        columns=columns,
        cells=cells,
        source="ocr",
        confidence=min(scores) if scores else 0,
    )
