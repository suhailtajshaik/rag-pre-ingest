"""Pure grid reconstruction from page geometry; preserve empty and merged cells."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from statistics import median

from rag_pre_ingest.models.document import Block, Cell, Page, Warning
from rag_pre_ingest.pipeline.readers import render_table

Line = tuple[float, float, float, float]


def _cluster(values: list[float], epsilon: float) -> list[float]:
    groups: list[list[float]] = []
    for value in sorted(values):
        if groups and value - groups[-1][-1] <= epsilon:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [sum(group) / len(group) for group in groups]


def _center(block: Block) -> tuple[float, float]:
    a, b, c, d = block.bbox
    return (a + c) / 2, (b + d) / 2


def _inside(block: Block, box: Line) -> bool:
    x, y = _center(block)
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def _numeric(text: str) -> bool:
    return bool(re.fullmatch(r"[\s$€£¥+−\-()]*\d[\d.,%\s$€£¥+−\-()]*", text))


def _markdown(cells: list[Cell], rows: int, columns: int) -> str:
    grid = [[""] * columns for _ in range(rows)]
    for cell in cells:
        grid[cell.row][cell.col] = cell.text
    return render_table(grid, header=any(cell.is_header for cell in cells))


def _coverage(
    segments: list[tuple[float, float]], start: float, end: float, epsilon: float
) -> bool:
    edge = start
    for left, right in sorted(segments):
        if left > edge + epsilon:
            return False
        edge = max(edge, right)
        if edge >= end - epsilon:
            return True
    return False


def _cell_text(words: list[Block]) -> str:
    """Read words by baseline bands, rather than glyph-specific top coordinates."""
    bands: list[list[Block]] = []
    for word in sorted(words, key=lambda block: (_center(block)[1], block.bbox[0], block.id)):
        if bands:
            band = bands[-1]
            baseline = median(_center(block)[1] for block in band)
            height = median(block.bbox[3] - block.bbox[1] for block in band)
            tolerance = max(1, min(height, word.bbox[3] - word.bbox[1]) * 0.5)
            if abs(_center(word)[1] - baseline) <= tolerance:
                band.append(word)
                continue
        bands.append([word])
    return "\n".join(
        " ".join(block.text for block in sorted(band, key=lambda block: (block.bbox[0], block.id)))
        for band in bands
    )


def _ruled(
    page: Page, lines: list[Line], words: list[Block], epsilon: float
) -> tuple[Block | None, list[Warning]]:
    horizontal = [
        line
        for line in lines
        if abs(line[3] - line[1]) <= epsilon and abs(line[2] - line[0]) > epsilon * 2
    ]
    vertical = [
        line
        for line in lines
        if abs(line[2] - line[0]) <= epsilon and abs(line[3] - line[1]) > epsilon * 2
    ]
    xs = _cluster([(line[0] + line[2]) / 2 for line in vertical], epsilon)
    ys = _cluster([(line[1] + line[3]) / 2 for line in horizontal], epsilon)
    if len(xs) < 2 or len(ys) < 2:
        return None, []
    rows, columns = len(ys) - 1, len(xs) - 1
    if rows == columns == 1 and not any(
        word.text.strip() and _inside(word, (xs[0], ys[0], xs[-1], ys[-1])) for word in words
    ):
        # An empty isolated rectangle is often a checkbox, not a document table.
        return None, []
    if rows * columns > 10000:
        return None, [
            Warning(
                page_number=page.page_number,
                code="table_inconsistent",
                message="The inferred table grid exceeds the safe cell limit.",
            )
        ]
    parent = list(range(rows * columns))

    def find(slot: int) -> int:
        while parent[slot] != slot:
            parent[slot] = parent[parent[slot]]
            slot = parent[slot]
        return slot

    def union(a: int, b: int) -> None:
        parent[find(b)] = find(a)

    for row in range(rows):
        for col in range(columns):
            slot = row * columns + col
            if col + 1 < columns:
                segments = [
                    (min(line[1], line[3]), max(line[1], line[3]))
                    for line in vertical
                    if abs((line[0] + line[2]) / 2 - xs[col + 1]) <= epsilon
                ]
                if not _coverage(segments, ys[row], ys[row + 1], epsilon):
                    union(slot, slot + 1)
            if row + 1 < rows:
                segments = [
                    (min(line[0], line[2]), max(line[0], line[2]))
                    for line in horizontal
                    if abs((line[1] + line[3]) / 2 - ys[row + 1]) <= epsilon
                ]
                if not _coverage(segments, xs[col], xs[col + 1], epsilon):
                    union(slot, slot + columns)
    groups: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for row in range(rows):
        for col in range(columns):
            groups[find(row * columns + col)].append((row, col))
    cells: list[Cell] = []
    warnings: list[Warning] = []
    for slots in groups.values():
        r0, r1 = min(r for r, _ in slots), max(r for r, _ in slots)
        c0, c1 = min(c for _, c in slots), max(c for _, c in slots)
        if len(slots) != (r1 - r0 + 1) * (c1 - c0 + 1):
            warnings.append(
                Warning(
                    page_number=page.page_number,
                    code="table_inconsistent",
                    message="Nonrectangular merged cells were kept separate.",
                )
            )
            regions = [(r, r, c, c) for r, c in slots]
        else:
            regions = [(r0, r1, c0, c1)]
        for top, bottom, left, right in regions:
            bounds = (xs[left], ys[top], xs[right + 1], ys[bottom + 1])
            content = sorted(
                (w for w in words if _inside(w, bounds)), key=lambda w: (w.bbox[1], w.bbox[0], w.id)
            )
            cells.append(
                Cell(
                    row=top,
                    col=left,
                    text=_cell_text(content),
                    row_span=bottom - top + 1,
                    col_span=right - left + 1,
                    is_header=top == 0,
                )
            )
    cells.sort(key=lambda c: (c.row, c.col))
    # A merged first-tier heading can cover subsequent header rows. A single
    # continuation/body row is not a header merely because it occupies row zero.
    if rows > 1:
        header_rows = max((cell.row_span for cell in cells if cell.row == 0), default=1)
    else:
        visible = [
            word
            for word in words
            if _inside(word, (xs[0], ys[0], xs[-1], ys[-1])) and word.text.strip()
        ]
        header_rows = int(
            bool(visible)
            and sum((word.font_weight or 0) >= 600 for word in visible) / len(visible) >= 0.8
        )
    for cell in cells:
        cell.is_header = cell.row < header_rows
    markdown = _markdown(cells, rows, columns)
    table = Block(
        id=f"p{page.page_number}_table1",
        type="table",
        bbox=(xs[0], ys[0], xs[-1], ys[-1]),
        text=markdown,
        markdown=markdown,
        rows=rows,
        columns=columns,
        cells=cells,
    )
    return table, warnings


def _unruled(page: Page, words: list[Block], epsilon: float) -> tuple[Block | None, list[Warning]]:
    if len(words) < 6:
        return None, []
    heights = sorted(w.bbox[3] - w.bbox[1] for w in words)
    row_tolerance = max(epsilon, heights[len(heights) // 2] * 0.65)
    ys = _cluster([_center(word)[1] for word in words], row_tolerance)
    if len(ys) < 3:
        return None, []
    rows: list[list[Block]] = [[] for _ in ys]
    for word in words:
        row_index = min(range(len(ys)), key=lambda index: abs(_center(word)[1] - ys[index]))
        rows[row_index].append(word)
    anchors = _cluster([w.bbox[0] for w in words], max(epsilon, 5))
    repeated = [
        x
        for x in anchors
        if sum(any(abs(w.bbox[0] - x) <= max(epsilon, 5) for w in row) for row in rows) >= 3
    ]
    if len(repeated) < 2:
        return None, []
    # Find a contiguous run of aligned cell rows; surrounding prose is not table material.
    runs: list[list[list[Block]]] = []
    current: list[list[Block]] = []
    previous_y: float | None = None
    gaps = sorted(ys[index + 1] - ys[index] for index in range(len(ys) - 1))
    typical_gap = gaps[len(gaps) // 2] if gaps else row_tolerance
    for row in rows:
        aligned = sum(
            any(abs(word.bbox[0] - anchor) <= max(epsilon, 5) for word in row)
            for anchor in repeated
        )
        short_cells = all(len(word.text) <= 60 and len(word.text.split()) <= 4 for word in row)
        y = min(_center(word)[1] for word in row)
        if (
            aligned < 2
            or not short_cells
            or (previous_y is not None and y - previous_y > typical_gap * 1.8)
        ):
            if current:
                runs.append(current)
            current = []
        if aligned >= 2 and short_cells:
            current.append(row)
        previous_y = y
    if current:
        runs.append(current)
    if not runs or max(map(len, runs)) < 3:
        return None, [
            Warning(
                page_number=page.page_number,
                code="table_inconsistent",
                message="Aligned text lacks a clear table region; originals were preserved.",
            )
        ]
    rows = max(runs, key=len)
    words = [word for row in rows for word in row]
    grid: list[list[str]] = [[""] * len(repeated) for _ in rows]
    for row_index, row in enumerate(rows):
        for word in sorted(row, key=lambda w: w.bbox[0]):
            # A cell's first anchor owns following words until the next column begins.
            eligible = [i for i, x in enumerate(repeated) if x <= word.bbox[0] + max(epsilon, 5)]
            if not eligible:
                return None, []
            column = eligible[-1]
            grid[row_index][column] = (grid[row_index][column] + " " + word.text).strip()
    numeric = any(
        sum(_numeric(row[c]) for row in grid[1:]) >= (len(grid) - 1) * 0.6
        for c in range(len(repeated))
    )
    short = len(repeated) >= 3 and all(
        len(cell) <= 18 and len(cell.split()) <= 2 for row in grid for cell in row
    )
    if not numeric and not short:
        return None, [
            Warning(
                page_number=page.page_number,
                code="table_inconsistent",
                message="Aligned text is ambiguous; no unruled table was fabricated.",
            )
        ]
    cells = [
        Cell(row=r, col=c, text=text, is_header=r == 0)
        for r, row in enumerate(grid)
        for c, text in enumerate(row)
    ]
    markdown = render_table(grid)
    bounds = (
        min(w.bbox[0] for w in words),
        min(w.bbox[1] for w in words),
        max(w.bbox[2] for w in words),
        max(w.bbox[3] for w in words),
    )
    return Block(
        id=f"p{page.page_number}_table1",
        type="table",
        bbox=bounds,
        text=markdown,
        markdown=markdown,
        rows=len(rows),
        columns=len(repeated),
        cells=cells,
    ), []


def _source_tokens(text: str) -> list[str]:
    # PDF text rectangles may split punctuation into separate blocks while the word
    # reader preserves W&B;) as one token. Lexemes retain every nonspace character
    # without treating those harmless whitespace boundaries as missing content.
    return re.findall(r"\w+|[^\w\s]", text)


def _paired_key_tables(page: Page, table: Block, words: list[Block], epsilon: float) -> list[Block]:
    """Separate side-by-side key/value lists only when repeated colon keys prove it."""
    columns = table.columns or 0
    if columns < 4 or columns % 2 or not table.rows:
        return [table]
    grid = [[""] * columns for _ in range(table.rows)]
    for cell in table.cells:
        grid[cell.row][cell.col] = cell.text
    pattern = re.compile(
        r"^([^:#\n]{1,32}:)\s*(#[0-9A-Fa-f]{3,8}(?:\s*(?:→|->|–|-)\s*#[0-9A-Fa-f]{3,8})?)?$"
    )
    matched_rows: list[int] = []
    parsed: dict[tuple[int, int], tuple[str, str]] = {}
    for row, values in enumerate(grid):
        keys: list[str] = []
        for pair in range(columns // 2):
            match = pattern.fullmatch(values[pair * 2].strip())
            if match is None:
                break
            label, inline = match.group(1), match.group(2)
            value = values[pair * 2 + 1]
            if inline and value:
                break
            parsed[(row, pair)] = (label, inline or value)
            keys.append(label.casefold())
        if len(keys) == columns // 2 and len(set(keys)) == 1:
            matched_rows.append(row)
    if len(matched_rows) < 3:
        return [table]
    # Every source row must be understood, except an optional title row.
    first_body = matched_rows[0]
    if matched_rows != list(range(first_body, len(grid))) or first_body > 1:
        return [table]
    pair_count = columns // 2
    label_anchors: list[float] = []
    for pair in range(pair_count):
        labels = {parsed[(row, pair)][0] for row in matched_rows}
        positions = [
            word.bbox[0]
            for word in words
            if _inside(word, table.bbox)
            and any(word.text.strip().startswith(label) for label in labels)
        ]
        unique = _cluster(positions, 5)
        if len(unique) < pair_count:
            return [table]
        label_anchors = unique[:pair_count]
    boundaries = (
        [table.bbox[0]]
        + [label_anchors[pair] - epsilon for pair in range(1, pair_count)]
        + [table.bbox[2]]
    )
    tables: list[Block] = []
    for pair in range(pair_count):
        source = [
            word
            for word in words
            if boundaries[pair] <= _center(word)[0] <= boundaries[pair + 1]
            and table.bbox[1] <= _center(word)[1] <= table.bbox[3]
        ]
        if not source:
            return [table]
        x0 = min(word.bbox[0] for word in source)
        x1 = max(word.bbox[2] for word in source)
        title = grid[0][pair * 2] if first_body else ""
        title_block: Block | None = None
        if not title:
            candidates = [
                word
                for word in words
                if word.type in {"heading", "paragraph"}
                and 0 < table.bbox[1] - word.bbox[3] <= max(60, (word.bbox[3] - word.bbox[1]) * 3)
                and boundaries[pair] <= _center(word)[0] <= boundaries[pair + 1]
                and len(word.text) <= 60
                and ":" not in word.text
            ]
            if candidates:
                title_block = min(candidates, key=lambda word: table.bbox[1] - word.bbox[3])
                title = title_block.text
        cells: list[Cell] = []
        offset = 1 if title else 0
        if title:
            cells.append(Cell(row=0, col=0, text=title, col_span=2, is_header=True))
        for index, row in enumerate(matched_rows, offset):
            label, value = parsed[(row, pair)]
            cells.extend([Cell(row=index, col=0, text=label), Cell(row=index, col=1, text=value)])
        rows = len(matched_rows) + offset
        markdown = _markdown(cells, rows, 2)
        y0 = title_block.bbox[1] if title_block is not None else table.bbox[1]
        if title_block is not None:
            x0, x1 = min(x0, title_block.bbox[0]), max(x1, title_block.bbox[2])
        tables.append(
            Block(
                id=f"p{page.page_number}_table{pair + 1}",
                type="table",
                bbox=(x0, y0, x1, table.bbox[3]),
                text=markdown,
                markdown=markdown,
                rows=rows,
                columns=2,
                cells=cells,
            )
        )
    return tables


def _line_groups(lines: list[Line], epsilon: float) -> list[list[Line]]:
    """Separate disconnected ruled tables before constructing their grids."""
    groups: list[list[Line]] = []
    remaining = set(range(len(lines)))
    while remaining:
        pending = [min(remaining)]
        remaining.remove(pending[0])
        component: list[Line] = []
        while pending:
            line = lines[pending.pop()]
            component.append(line)
            x0, x1 = sorted((line[0], line[2]))
            y0, y1 = sorted((line[1], line[3]))
            touching = [
                index
                for index in remaining
                if min(x1, max(lines[index][0], lines[index][2])) + epsilon
                >= max(x0, min(lines[index][0], lines[index][2]))
                and min(y1, max(lines[index][1], lines[index][3])) + epsilon
                >= max(y0, min(lines[index][1], lines[index][3]))
            ]
            remaining.difference_update(touching)
            pending.extend(touching)
        groups.append(component)
    return groups


def _check_table(table: Block, words: list[Block], page_number: int) -> list[Warning]:
    expected = Counter(
        token for word in words if _inside(word, table.bbox) for token in _source_tokens(word.text)
    )
    actual = Counter(token for cell in table.cells for token in _source_tokens(cell.text))
    messages: list[str] = []
    if expected != actual:
        messages.append("Table cell text differs from the source region.")
    for column in range(table.columns or 0):
        values = [
            cell.text
            for cell in table.cells
            if cell.col == column and cell.row > 0 and cell.text.strip()
        ]
        numeric_count = sum(_numeric(value) for value in values)
        if values and 0.6 <= numeric_count / len(values) < 1:
            messages.append("A mostly numeric table column contains nonnumeric text.")
    return [
        Warning(page_number=page_number, code="table_inconsistent", message=message)
        for message in messages
    ]


def detect_tables(
    page: Page, lines: list[Line], words: list[Block] | None = None, *, epsilon: float = 2
) -> tuple[Page, list[Warning]]:
    """Reconstruct a geometric table, keeping originals when evidence is ambiguous.

    `words` must use the page's top-left coordinate system. Existing Office tables
    are preserved. The configurable epsilon clusters nearly coincident ruling edges.
    """
    result = page.model_copy(deep=True)
    if any(block.type == "table" for block in result.blocks):
        return result, []
    candidates = [
        w
        for w in (words if words is not None else result.blocks)
        if w.type in {"paragraph", "other", "list", "heading"}
        and not w.markdown.startswith("```")
        and not w.is_decorative
        and w.text.strip()
    ]
    if len(lines) > 4000:
        return result, [
            Warning(
                page_number=page.page_number,
                code="table_inconsistent",
                message="Too many ruling segments to reconstruct safely.",
            )
        ]
    tables: list[Block] = []
    warnings: list[Warning] = []
    for component in _line_groups(lines, epsilon):
        table, ruled_warnings = _ruled(result, component, candidates, epsilon)
        warnings.extend(ruled_warnings)
        if table is not None:
            tables.append(table)
    if not tables and not lines:
        table, inferred_warnings = _unruled(result, candidates, epsilon)
        warnings.extend(inferred_warnings)
        if table is not None:
            tables.extend(_paired_key_tables(result, table, candidates, epsilon))
    for index, table in enumerate(tables, 1):
        table.id = f"p{page.page_number}_table{index}"
        warnings.extend(_check_table(table, candidates, page.page_number))
        consumed = [
            block
            for block in result.blocks
            if block.type not in {"image", "table"}
            and not block.is_decorative
            and _inside(block, table.bbox)
            and block.text.strip()
        ]
        expected = Counter(token for block in consumed for token in _source_tokens(block.text))
        actual = Counter(token for cell in table.cells for token in _source_tokens(cell.text))
        if expected != actual:
            warnings.append(
                Warning(
                    page_number=page.page_number,
                    code="table_inconsistent",
                    message="Table conversion changed source text; original blocks were preserved.",
                )
            )
            continue
        table.source = "ocr" if consumed and all(b.source == "ocr" for b in consumed) else "read"
        result.blocks = [
            block
            for block in result.blocks
            if block.type in {"image", "table"} or not _inside(block, table.bbox)
        ] + [table]
    return result, warnings
