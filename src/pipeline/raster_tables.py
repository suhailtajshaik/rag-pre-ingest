"""PIL-only detection of thin raster ruling grids for cell-bounded OCR.

No text or values are inferred. Coordinates map back to the original page;
spreadsheet row/column chrome remains geometry for the caller to classify.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import median

from PIL import Image, ImageChops

BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class RasterGridConfig:
    lightest_line: int = 245
    max_channel_difference: int = 24
    min_line_length: int = 60
    min_line_fraction: float = 0.12
    max_line_thickness: int = 4
    intersection_tolerance: float = 3
    min_rows: int = 2
    min_columns: int = 2
    min_cell_size: float = 8
    max_cells: int = 4096
    max_scan_pixels: int = 4_000_000
    fragment_support: float = 0.5
    fragment_darkest: int = 160
    partial_row_fraction: float = 0.7
    min_rule_support: float = 0.5


@dataclass(frozen=True)
class RasterCell:
    row: int
    col: int
    bbox: BBox


@dataclass(frozen=True)
class RasterGrid:
    xs: tuple[float, ...]
    ys: tuple[float, ...]
    clipped_bottom: bool = False

    @property
    def rows(self) -> int:
        return len(self.ys) - 1

    @property
    def columns(self) -> int:
        return len(self.xs) - 1

    @property
    def bbox(self) -> BBox:
        return self.xs[0], self.ys[0], self.xs[-1], self.ys[-1]

    @property
    def lines(self) -> tuple[BBox, ...]:
        return tuple((x, self.ys[0], x, self.ys[-1]) for x in self.xs) + tuple(
            (self.xs[0], y, self.xs[-1], y) for y in self.ys
        )

    @property
    def cells(self) -> tuple[RasterCell, ...]:
        return tuple(
            RasterCell(row, col, (self.xs[col], self.ys[row], self.xs[col + 1], self.ys[row + 1]))
            for row in range(self.rows)
            for col in range(self.columns)
        )


def _runs(data: bytes, minimum: int) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(data):
        start = data.find(b"\xff", cursor)
        if start < 0:
            break
        end = data.find(b"\x00", start)
        if end < 0:
            end = len(data)
        if end - start >= minimum:
            runs.append((start, end - 1))
        cursor = end + 1
    return runs


def _thin_segments(
    raw: list[tuple[int, int, int]], thickness: int
) -> list[tuple[float, float, float]]:
    """Collapse antialiased multi-pixel lines, rejecting filled area bands."""
    groups: list[list[tuple[int, int, int]]] = []
    for segment in raw:
        if groups and segment[0] <= groups[-1][-1][0] + 1:
            groups[-1].append(segment)
        else:
            groups.append([segment])
    segments = []
    for group in groups:
        low, high = group[0][0], group[-1][0]
        if high - low + 1 > thickness:
            continue
        spans: list[list[tuple[int, int, int]]] = []
        for item in sorted(group, key=lambda entry: (entry[1], entry[2])):
            if spans and item[1] <= max(entry[2] for entry in spans[-1]) + thickness:
                spans[-1].append(item)
            else:
                spans.append([item])
        for span in spans:
            segments.append(
                (
                    (min(item[0] for item in span) + max(item[0] for item in span)) / 2,
                    float(min(item[1] for item in span)),
                    float(max(item[2] for item in span)),
                )
            )
    return segments


def _coordinates(values: list[float], minimum_gap: float) -> tuple[float, ...]:
    groups: list[list[float]] = []
    for value in sorted(values):
        if groups and value - groups[-1][-1] < minimum_gap:
            groups[-1].append(value)
        else:
            groups.append([value])
    return tuple(sum(group) / len(group) for group in groups)


def _supported_rules(
    coordinates: tuple[float, ...],
    segments: list[tuple[float, float, float]],
    start: float,
    end: float,
    tolerance: float,
    minimum_support: float,
) -> bool:
    """Require real ruling along every inferred divider, not just intersections.

    Connected glyph strokes and diagram connectors can intersect without forming
    table cells. Measure the union of their lengths, never overlapping pixels twice.
    """
    if end <= start:
        return False
    for coordinate in coordinates:
        intervals = sorted(
            (max(start, low), min(end, high))
            for position, low, high in segments
            if abs(position - coordinate) <= tolerance and high > start and low < end
        )
        covered = 0.0
        cursor = start
        for low, high in intervals:
            covered += max(0, high - max(cursor, low))
            cursor = max(cursor, high)
        if covered / (end - start) < minimum_support:
            return False
    return True


def detect_raster_grids(
    image: Image.Image,
    page_width: float | None = None,
    page_height: float | None = None,
    *,
    config: RasterGridConfig | None = None,
) -> list[RasterGrid]:
    """Find connected, repeated thin-line grids; blank cells need no OCR evidence.

    Pass page dimensions for scaled PDF renders; standalone images use pixel units.
    Native image bytes and pixels are never modified. Long filled regions and
    isolated boxes/icons are rejected instead of interpreted as tables.
    """
    settings = config or RasterGridConfig()
    if image.width <= 0 or image.height <= 0:
        return []
    scale = min(1.0, sqrt(settings.max_scan_pixels / (image.width * image.height)))
    width, height = max(1, round(image.width * scale)), max(1, round(image.height * scale))
    rgb = image.convert("RGB")
    if rgb.size != (width, height):
        rgb = rgb.resize((width, height), Image.Resampling.BILINEAR)
    red, green, blue = rgb.split()
    neutral = ImageChops.lighter(
        ImageChops.difference(red, green), ImageChops.difference(red, blue)
    )
    neutral = neutral.point(lambda value: 255 if value <= settings.max_channel_difference else 0)
    dark = rgb.convert("L").point(lambda value: 255 if value <= settings.lightest_line else 0)
    mask = ImageChops.multiply(neutral, dark).tobytes()
    minimum = max(
        round(settings.min_line_length * scale),
        round(min(width, height) * settings.min_line_fraction),
        8,
    )
    horizontal = _thin_segments(
        [
            (y, start, end)
            for y in range(height)
            for start, end in _runs(mask[y * width : (y + 1) * width], minimum)
        ],
        settings.max_line_thickness,
    )
    vertical_raw = [
        (x, start, end) for x in range(width) for start, end in _runs(mask[x::width], minimum)
    ]
    long_vertical = [segment for segment in vertical_raw if segment[2] - segment[1] >= minimum * 2]
    if len(horizontal) >= settings.min_rows + 1 and len(long_vertical) >= settings.min_columns + 1:
        # Spreadsheet overflow can paint over a vertical ruling on every text row.
        # Accumulate light neutral support across the established horizontal grid,
        # rather than requiring an uninterrupted run through the glyphs.
        top = max(0, int(median(segment[1] for segment in long_vertical)))
        bottom = min(height, int(median(segment[2] for segment in long_vertical)) + 1)
        grey = rgb.convert("L").point(
            lambda value: 255 if settings.fragment_darkest <= value <= settings.lightest_line else 0
        )
        fragment_mask = ImageChops.multiply(neutral, grey).tobytes()
        if bottom > top:
            for pixel_x in range(width):
                column = fragment_mask[top * width + pixel_x : bottom * width + pixel_x : width]
                if column.count(255) / len(column) >= settings.fragment_support:
                    vertical_raw.append((pixel_x, top, bottom - 1))
    vertical = _thin_segments(sorted(vertical_raw), settings.max_line_thickness)
    if len(horizontal) < settings.min_rows + 1 or len(vertical) < settings.min_columns + 1:
        return []
    # Build a bipartite intersection graph: disconnected shapes cannot form one grid.
    count = len(horizontal) + len(vertical)
    parent = list(range(count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> None:
        parent[find(b)] = find(a)

    tolerance = settings.intersection_tolerance
    for hi, (y, x0, x1) in enumerate(horizontal):
        for vi, (x, y0, y1) in enumerate(vertical):
            if x0 - tolerance <= x <= x1 + tolerance and y0 - tolerance <= y <= y1 + tolerance:
                union(hi, len(horizontal) + vi)
    components: dict[int, tuple[list[float], list[float]]] = {}
    for hi, (y, _, _) in enumerate(horizontal):
        components.setdefault(find(hi), ([], []))[1].append(y)
    for vi, (x, _, _) in enumerate(vertical):
        components.setdefault(find(len(horizontal) + vi), ([], []))[0].append(x)
    x_scale = (page_width if page_width is not None else image.width) / width
    y_scale = (page_height if page_height is not None else image.height) / height
    grids = []
    for x_values, y_values in components.values():
        xs = _coordinates(x_values, settings.min_cell_size * scale)
        ys = _coordinates(y_values, settings.min_cell_size * scale)
        clipped_bottom = False
        if len(ys) >= 4:
            gaps = [ys[index + 1] - ys[index] for index in range(len(ys) - 1)]
            if (
                ys[-1] >= height * 0.94
                and gaps[-1] < median(gaps[:-1]) * settings.partial_row_fraction
            ):
                ys = ys[:-1]
                clipped_bottom = True
        rows, columns = len(ys) - 1, len(xs) - 1
        if (
            rows >= settings.min_rows
            and columns >= settings.min_columns
            and rows * columns <= settings.max_cells
            and _supported_rules(xs, vertical, ys[0], ys[-1], tolerance, settings.min_rule_support)
            and _supported_rules(
                ys, horizontal, xs[0], xs[-1], tolerance, settings.min_rule_support
            )
        ):
            grids.append(
                RasterGrid(
                    tuple(x * x_scale for x in xs), tuple(y * y_scale for y in ys), clipped_bottom
                )
            )
    return sorted(grids, key=lambda grid: (grid.ys[0], grid.xs[0]))
