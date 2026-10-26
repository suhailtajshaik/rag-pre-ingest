from copy import deepcopy

from rag_pre_ingest.models.document import Block
from rag_pre_ingest.pipeline.layout import _paired_label_order, reading_order


def paired_blocks() -> list[Block]:
    return [
        block
        for row in range(5)
        for block in (
            Block(
                id=f"label{row}",
                type="paragraph",
                text=f"Stage {row + 1}",
                bbox=(220, 168 + row * 180, 363, 213 + row * 180),
                source="ocr",
            ),
            Block(
                id=f"description{row}",
                type="paragraph",
                text=f"Description of the learning activities for stage {row + 1}.",
                bbox=(467, 151 + row * 180, 1717, 241 + row * 180),
                source="ocr",
            ),
        )
    ]


def test_numbered_labels_stay_with_descriptions_without_mutating_inputs() -> None:
    blocks = list(reversed(paired_blocks()))
    for block in blocks:
        if block.id.startswith("description"):
            x0, y0, x1, y1 = block.bbox
            block.bbox = (x0 + 300, y0, x1 + 300, y1)
    original = deepcopy(blocks)
    ordered, warnings = reading_order(blocks, 1926, 1180)
    assert [block.id for block in ordered] == [block.id for block in paired_blocks()]
    assert warnings == []
    assert blocks == original


def test_wrapped_raw_ocr_lines_follow_their_label_before_next_pair() -> None:
    blocks = paired_blocks()
    for block in list(blocks):
        if block.id.startswith("description"):
            x0, y0, x1, y1 = block.bbox
            block.bbox = (x0, y0, x1, y0 + 44)
            blocks.append(
                block.model_copy(
                    update={
                        "id": block.id + "-continued",
                        "text": "The next description line.",
                        "bbox": (x0, y0 + 45, x1 - 100, y1),
                    }
                )
            )
    ordered, warnings = reading_order(list(reversed(blocks)), 1926, 1180)
    assert [block.id for block in ordered] == [
        identifier
        for row in range(5)
        for identifier in (f"label{row}", f"description{row}", f"description{row}-continued")
    ]
    assert warnings == []


def test_fullwidth_heading_and_container_preserve_label_pairs() -> None:
    blocks = paired_blocks() + [
        Block(id="image", type="image", bbox=(0, 0, 1926, 1180)),
        Block(id="heading", type="heading", text="Roadmap", bbox=(100, 20, 1800, 80)),
    ]
    ordered, _ = reading_order(blocks, 1926, 1180)
    assert [block.id for block in ordered] == ["image", "heading"] + [
        block.id for block in paired_blocks()
    ]


def test_ordinary_article_columns_keep_column_order() -> None:
    blocks = paired_blocks()
    for block in blocks:
        if block.id.startswith("label"):
            block.text = "An ordinary article paragraph."
        else:
            x0, y0, x1, y1 = block.bbox
            block.bbox = (x0 + 300, y0, x1 + 300, y1)
    ordered, _ = reading_order(blocks, 1926, 1180)
    assert [block.id for block in ordered] == [f"label{i}" for i in range(5)] + [
        f"description{i}" for i in range(5)
    ]


def test_numbered_article_columns_of_equal_width_are_not_paired() -> None:
    blocks = paired_blocks()
    for block in blocks:
        if block.id.startswith("description"):
            x0, y0, _, y1 = block.bbox
            block.bbox = (x0, y0, x0 + 140, y1)
    assert _paired_label_order(blocks) is None


def test_ambiguous_spanning_description_does_not_force_pairs() -> None:
    blocks = paired_blocks()
    blocks[1].bbox = (467, 151, 1717, 800)
    assert _paired_label_order(blocks) is None


def test_tables_are_not_reordered_as_label_description_pairs() -> None:
    blocks = paired_blocks()
    blocks[1].type = "table"
    assert _paired_label_order(blocks) is None


def test_nonconsecutive_labels_do_not_override_column_order() -> None:
    blocks = paired_blocks()
    blocks[4].text = "Stage 9"
    assert _paired_label_order(blocks) is None
