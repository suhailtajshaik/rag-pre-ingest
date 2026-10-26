from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from rag_pre_ingest.models.document import Block, Page
from rag_pre_ingest.pipeline.connectors import arrow_direction, detect_connectors


def arrow_image() -> Image.Image:
    image = Image.new("RGB", (40, 40), "white")
    ImageDraw.Draw(image).polygon(
        [(17, 2), (23, 2), (23, 17), (36, 17), (20, 36), (4, 17), (17, 17)], fill="black"
    )
    return image


@pytest.mark.parametrize(
    ("rotation", "expected"), [(0, "down"), (90, "right"), (180, "up"), (270, "left")]
)
def test_arrow_direction(rotation: int, expected: str) -> None:
    image = arrow_image().rotate(rotation)
    points = {(x, y) for x in range(40) for y in range(40) if image.getpixel((x, y)) == (0, 0, 0)}
    assert arrow_direction(points) == expected


def test_rectangles_and_unclear_shapes_have_no_direction() -> None:
    assert arrow_direction({(x, y) for x in range(15) for y in range(20)}) is None
    assert (
        arrow_direction(
            {(x, y) for x in range(20) for y in range(20) if (x - 10) ** 2 + (y - 10) ** 2 < 80}
        )
        is None
    )
    assert arrow_direction(set()) is None


def test_real_flowchart_arrows_keep_text_and_omit_corner_decorations() -> None:
    path = Path(__file__).parent / "fixtures/user_samples/llm-flowchart.png"
    image = Image.open(path)
    labels = [
        "Tokenization",
        "Embedding",
        "Transformer Mechanism",
        "Prediction",
        "Response Generation",
    ]
    # Manually annotated source label bounds; geometry is in the image's native units.
    sx, sy = image.width / 800, image.height / 452
    blocks = [
        Block(
            id=f"label{i}",
            type="paragraph",
            text=text,
            source="ocr",
            bbox=(320 * sx, y * sy, 478 * sx, (y + 15) * sy),
        )
        for i, (text, y) in enumerate(zip(labels, [28, 111, 195, 278, 361], strict=True))
    ]
    blocks.append(
        Block(
            id="description",
            type="paragraph",
            text="Preserve this description",
            bbox=(320 * sx, 57 * sy, 478 * sx, 80 * sy),
        )
    )
    page = Page(page_number=1, width=image.width, height=image.height, blocks=blocks)
    result = detect_connectors(image, page)
    assert [edge.direction for edge in result.connectors] == ["down"] * 4
    assert {(edge.source_block_id, edge.target_block_id) for edge in result.connectors} == {
        (f"label{i}", f"label{i + 1}") for i in range(4)
    }
    assert result.blocks[-1].text == " → ".join(labels)
    assert result.blocks[:-1] == page.blocks
    assert page.connectors == ()
    assert detect_connectors(image, result) == result


def test_no_links_without_visible_arrows() -> None:
    image = Image.new("RGB", (500, 500), "white")
    draw = ImageDraw.Draw(image)
    blocks = []
    for i in range(3):
        y = 20 + i * 150
        draw.rectangle((100, y, 400, y + 50), fill="lightgreen")
        blocks.append(
            Block(id=str(i), type="paragraph", text=f"Step {i}", bbox=(120, y + 10, 380, y + 40))
        )
    result = detect_connectors(image, Page(page_number=1, width=500, height=500, blocks=blocks))
    assert not result.connectors
    assert len(result.blocks) == 3
