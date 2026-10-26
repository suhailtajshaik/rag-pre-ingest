from collections import Counter

from rag_pre_ingest.models.document import Block, Page
from rag_pre_ingest.pipeline.tables import detect_tables


def fragment(name: str, text: str, x: float, y: float, width: float = 70) -> Block:
    return Block(
        id=name,
        type="paragraph",
        text=text,
        markdown=text,
        bbox=(x, y, x + width, y + 16),
        source="ocr",
    )


def test_repeated_colon_keys_form_two_named_tables_with_every_value() -> None:
    blocks = [fragment("light", "LIGHT", 35, 22), fragment("dark", "DARK", 385, 21)]
    data = [
        ("BG:", "#F5F7F2", "#0C120D"),
        ("Surface:", "#FFFFFF", "#151E16"),
        ("Border:", "#D4DDD5", "#253026"),
        ("Text:", "#1A2E1C", "#E2EDE3"),
        ("Accent:", "#16A34A", "#4ADE80"),
        ("Grad:", "#15803D→#22C55E", "#4ADE80→#86EFAC"),
    ]
    for row, (key, light, dark) in enumerate(data):
        y = 80 + row * 28
        blocks.append(
            fragment(
                f"left-label{row}", key + light if row == 1 else key, 35, y, 170 if row == 1 else 70
            )
        )
        if row != 1:
            blocks.append(fragment(f"left-value{row}", light, 155, y, 180 if row == 5 else 90))
        blocks.extend(
            [
                fragment(f"right-label{row}", key, 385, y),
                fragment(f"right-value{row}", dark, 535, y, 200 if row == 5 else 90),
            ]
        )
    blocks += [
        fragment("vibe", "Vibe: Calm, trustworthy, organic", 35, 280, 450),
        fragment("like", "Like: Loom, Notion, Cal.com", 35, 315, 400),
    ]
    page = Page(page_number=1, width=780, height=360, blocks=list(reversed(blocks)))
    result, warnings = detect_tables(page, [])
    assert not warnings
    tables = sorted(
        (block for block in result.blocks if block.type == "table"), key=lambda b: b.bbox[0]
    )
    assert len(tables) == 2
    for index, table in enumerate(tables):
        assert table.columns == 2 and table.rows == 7
        assert table.cells[0].text == ("LIGHT" if index == 0 else "DARK")
        assert table.cells[0].col_span == 2
        assert table.cells[0].is_header
        assert all(not cell.is_header for cell in table.cells[1:])
        assert [(cell.row, cell.col, cell.text) for cell in table.cells[1:]] == [
            entry
            for row, (key, light, dark) in enumerate(data, 1)
            for entry in [(row, 0, key), (row, 1, light if index == 0 else dark)]
        ]
        assert all(len(line.split("|")) == 4 for line in table.markdown.splitlines())
    assert {b.id for b in result.blocks if b.type == "paragraph"} == {"vibe", "like"}
    tokens = Counter(
        token for table in tables for cell in table.cells for token in cell.text.split()
    )
    assert tokens["#FFFFFF"] == 1
    assert tokens["#4ADE80"] == 1


def test_arbitrary_four_column_table_is_not_split() -> None:
    blocks = [
        fragment(f"{r}-{c}", value, 35 + c * 150, 60 + r * 30)
        for r, values in enumerate(
            [
                ["Name", "Qty", "Unit", "Price"],
                ["Widget", "2", "each", "5.00"],
                ["Bolt", "4", "each", "1.00"],
            ]
        )
        for c, value in enumerate(values)
    ]
    result, warnings = detect_tables(Page(page_number=1, width=780, height=360, blocks=blocks), [])
    tables = [block for block in result.blocks if block.type == "table"]
    assert len(tables) == 1 and tables[0].columns == 4
    assert not warnings
