from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from rag_pre_ingest.pipeline.ocr_lists import is_decorative_arrow


def test_colored_arrow_shape():
    image = Image.new("RGB", (80, 80), "white")
    draw = ImageDraw.Draw(image)
    draw.polygon(
        [(20, 10), (60, 10), (60, 50), (50, 50), (50, 28), (18, 60), (10, 52), (42, 20), (20, 20)],
        fill="#00bb88",
    )
    assert is_decorative_arrow(image, (0, 0, 80, 80), "K")
    assert not is_decorative_arrow(image, (0, 0, 80, 80), "OK")


@pytest.mark.parametrize("character", ["K", "O", "フ", "A", "1"])
def test_legitimate_colored_letters_retained(character):
    image = Image.new("RGB", (80, 80), "white")
    ImageDraw.Draw(image).text((10, 10), character, fill="#00bb88", font_size=50)
    assert not is_decorative_arrow(image, (0, 0, 80, 80), character)


def test_uploaded_arrows():
    path = Path("tests/fixtures/user_samples/image-models.png")
    with Image.open(path) as image:
        assert is_decorative_arrow(image, (13, 790, 166, 858), "フ")
        assert is_decorative_arrow(image, (1492, 798, 1551, 856), "K")
