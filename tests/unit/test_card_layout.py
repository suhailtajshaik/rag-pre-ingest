import random
from collections import Counter

from rag_pre_ingest.models.document import Block, Page
from rag_pre_ingest.pipeline.layout import sort_page


def text(identifier: str, value: str, bounds: tuple[float, float, float, float]) -> Block:
    return Block(
        id=identifier, type="paragraph", text=value, markdown=value, bbox=bounds, source="ocr"
    )


def cards() -> Page:
    blocks = [
        Block(id="image", type="image", bbox=(0, 0, 1512, 1388)),
        text("nav1", "One Two Three", (72, 46, 483, 84)),
        text("nav2", "Four Five Six", (550, 44, 1148, 86)),
        text("nav3", "Seven Eight", (1210, 44, 1442, 93)),
        text("nav4", "Nine", (71, 127, 205, 168)),
    ]
    for row in range(5):
        for col in range(2):
            x, y = col * 731, row * 237
            blocks.extend(
                [
                    text(
                        f"brand-{row}-{col}",
                        "Repeated product",
                        (113 + x, 249 + y, 270 + x, 279 + y),
                    ),
                    text(f"action-{row}-{col}", "Open panel", (638 + x, 250 + y, 720 + x, 281 + y)),
                    text(
                        f"body-{row}-{col}",
                        f"Unique panel {row}-{col} description",
                        (67 + x, 293 + y, 349 + x, 355 + y),
                    ),
                ]
            )
    random.Random(19).shuffle(blocks)
    return Page(page_number=1, width=1512, height=1388, blocks=blocks)


def test_repeated_card_grid_orders_each_card_before_next_card() -> None:
    source = cards()
    result, warnings = sort_page(source)
    assert not warnings
    assert [b.id for b in result.blocks] == ["image", "nav1", "nav2", "nav3", "nav4"] + [
        identifier
        for row in range(5)
        for col in range(2)
        for identifier in [f"brand-{row}-{col}", f"action-{row}-{col}", f"body-{row}-{col}"]
    ]
    assert Counter(b.id for b in source.blocks) == Counter(b.id for b in result.blocks)
    assert source.blocks != result.blocks


def test_card_detection_is_label_independent_and_tolerates_baseline_jitter() -> None:
    page = cards()
    for block in page.blocks:
        if block.id.startswith("brand"):
            block.text = "Different reusable label"
        if block.id.startswith("action"):
            block.text = "Different action"
            a, b, c, d = block.bbox
            block.bbox = (a, b + 2, c, d + 2)
    result, _ = sort_page(page)
    bodies = [b.id for b in result.blocks if b.id.startswith("body")]
    assert bodies == [f"body-{row}-{col}" for row in range(5) for col in range(2)]


def test_unrepeated_document_columns_still_read_column_by_column() -> None:
    blocks = [
        text(
            f"{row}-{col}",
            f"Unique prose {row}-{col}",
            (40 + col * 350, 100 + row * 50, 240 + col * 350, 120 + row * 50),
        )
        for row in range(3)
        for col in range(2)
    ]
    result, _ = sort_page(Page(page_number=1, width=800, height=900, blocks=blocks))
    assert [b.id for b in result.blocks] == [f"{row}-{col}" for col in range(2) for row in range(3)]


def test_one_repeated_label_does_not_change_prose_column_rule() -> None:
    blocks = [
        text(
            f"{row}-{col}",
            "Repeated prose" if row % 2 == 0 else f"Unique {row}-{col}",
            (40 + col * 350, 100 + row * 80, 240 + col * 350, 120 + row * 80),
        )
        for row in range(5)
        for col in range(2)
    ]
    result, _ = sort_page(Page(page_number=1, width=800, height=900, blocks=blocks))
    assert [b.id for b in result.blocks] == [f"{row}-{col}" for col in range(2) for row in range(5)]
