from collections import Counter
from unittest.mock import patch

from rag_pre_ingest.models.document import Block, Page
from rag_pre_ingest.pipeline.tables import detect_tables


def item(identifier: str, text: str, x: float, y: float, kind: str = "paragraph") -> Block:
    return Block(id=identifier, type=kind, text=text, markdown=text, bbox=(x, y, x + 60, y + 12))  # type: ignore[arg-type]


def content(page: Page) -> Counter[str]:
    return Counter(
        token
        for block in page.blocks
        if not block.is_decorative and block.type != "image"
        for text in ([cell.text for cell in block.cells] if block.type == "table" else [block.text])
        for token in text.split()
    )


def palette() -> Page:
    blocks = [item("light", "LIGHT", 10, 10), item("dark", "DARK", 310, 10)]
    for row, values in enumerate(
        [
            ["Surface", "#FFFFFF", "Surface", "#151E16"],
            ["Border", "#D4DDD5", "Border", "#253026"],
            ["Accent", "#16A34A", "Accent", "#4ADE80"],
        ],
        1,
    ):
        for col, value in enumerate(values):
            blocks.append(
                item(
                    f"{row}-{col}",
                    value,
                    10 + col * 150,
                    row * 25 + 10,
                    "list" if value.startswith("#") else "paragraph",
                )
            )
    blocks += [
        item("vibe", "Vibe: Calm trustworthy organic", 10, 160),
        item("like", "Like: Loom Notion Cal.com", 10, 190),
    ]
    return Page(page_number=1, width=780, height=360, blocks=blocks)


def test_palette_list_typed_hexes_and_sentence_tails_survive() -> None:
    page = palette()
    result, _ = detect_tables(page, [])
    assert content(result) == content(page)
    assert all(
        token in content(result)
        for token in [
            "#D4DDD5",
            "#151E16",
            "#253026",
            "#16A34A",
            "#4ADE80",
            "trustworthy",
            "organic",
            "Notion",
            "Cal.com",
        ]
    )
    table = next(block for block in result.blocks if block.type == "table")
    assert table.cells[0].text == "LIGHT"
    assert table.cells[1].text == ""
    assert table.cells[2].text == "DARK"
    assert any(block.id == "vibe" and block.type == "paragraph" for block in result.blocks)
    assert any(block.id == "like" and block.type == "paragraph" for block in result.blocks)


def test_incomplete_word_metadata_cannot_delete_unassigned_source_text() -> None:
    page = palette()
    words = [block for block in page.blocks if block.type != "list"]
    result, warnings = detect_tables(page, [], words)
    assert content(result) == content(page)
    assert any(w.code == "table_inconsistent" for w in warnings)
    assert not any(block.type == "table" for block in result.blocks)


def test_table_token_mismatch_falls_back_before_consuming_originals() -> None:
    page = palette()
    from rag_pre_ingest.pipeline.tables import _unruled

    table, _ = _unruled(page, page.blocks, 2)
    assert table is not None
    table.cells[0].text = "WRONG"
    with patch("rag_pre_ingest.pipeline.tables._unruled", return_value=(table, [])):
        result, warnings = detect_tables(page, [])
    assert content(result) == content(page)
    assert any("original blocks" in w.message for w in warnings)
