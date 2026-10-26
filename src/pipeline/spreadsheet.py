"""Pure worksheet bounds: ignore formatting-only tails without shifting real cells."""


def trim_empty_tails(
    rows: list[list[str]], merged_spans: list[tuple[int, int, int, int]]
) -> list[list[str]]:
    """Keep leading/interior blanks and any span anchored by a populated cell.

    Span coordinates are zero-based inclusive (top, left, bottom, right).
    Empty styled rows/columns at the end are not logical table content.
    """
    populated = [(r, c) for r, row in enumerate(rows) for c, value in enumerate(row) if value]
    if not populated:
        return []
    bottom = max(r for r, _ in populated)
    right = max(c for _, c in populated)
    for top, left, end_row, end_col in merged_spans:
        if 0 <= top < len(rows) and 0 <= left < len(rows[top]) and rows[top][left]:
            bottom, right = max(bottom, end_row), max(right, end_col)
    return [
        ((rows[r] if r < len(rows) else []) + [""] * (right + 1))[: right + 1]
        for r in range(bottom + 1)
    ]
