"""OCR lists require an explicit glyph or an actual nearby pixel component."""

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from rag_pre_ingest.pipeline.ocr import recognize
from rag_pre_ingest.pipeline.ocr_lists import has_visual_bullet, normalize_list_prefix


@pytest.mark.parametrize("glyph", ["•", "▪", "◦", "●", "·", "\uf0a7", "-", "*", "+"])
def test_explicit_list_glyphs_become_plain_text_and_list_flag(glyph: str) -> None:
    assert normalize_list_prefix(glyph + " An item") == (True, "An item")


@pytest.mark.parametrize(
    "text", ["A short heading", "O ring components", "-standing", "No marker", "The word • here"]
)
def test_shortness_or_internal_punctuation_does_not_invent_a_list(text: str) -> None:
    assert normalize_list_prefix(text) == (False, text)


def test_ocr_marker_artifact_requires_visual_bullet_evidence() -> None:
    assert normalize_list_prefix("o An item", True) == (True, "An item")
    assert normalize_list_prefix("o An item", False) == (False, "o An item")
    assert normalize_list_prefix("An item", True) == (True, "An item")


@pytest.mark.parametrize("background,foreground", [("white", "black"), ("#0d1451", "white")])
def test_square_bullet_is_detected_for_both_contrast_polarities(
    background: str, foreground: str
) -> None:
    image = Image.new("RGB", (200, 100), background)
    ImageDraw.Draw(image).rectangle((22, 28, 26, 32), fill=foreground)
    assert has_visual_bullet(image, (40, 20, 160, 40))


def test_small_round_bullet_and_bullet_inside_ocr_box_are_detected() -> None:
    image = Image.new("L", (200, 100), 255)
    ImageDraw.Draw(image).ellipse((40, 28, 45, 33), fill=0)
    assert has_visual_bullet(image, (39, 20, 160, 40))


@pytest.mark.parametrize("kind", ["none", "rule", "vertical", "box", "far", "clipped"])
def test_rules_boxes_and_unrelated_components_are_not_bullets(kind: str) -> None:
    image = Image.new("L", (200, 100), 255)
    draw = ImageDraw.Draw(image)
    if kind == "rule":
        draw.line((5, 30, 35, 30), fill=0, width=2)
    elif kind == "vertical":
        draw.line((24, 18, 24, 42), fill=0, width=2)
    elif kind == "box":
        draw.rectangle((15, 22, 31, 38), outline=0, width=2)
    elif kind == "far":
        draw.rectangle((22, 60, 26, 64), fill=0)
    elif kind == "clipped":
        draw.rectangle((0, 28, 4, 32), fill=0)
    assert not has_visual_bullet(image, (40, 20, 160, 40))


def test_continuation_line_without_its_own_bullet_is_not_a_new_item() -> None:
    image = Image.new("L", (200, 100), 255)
    ImageDraw.Draw(image).rectangle((22, 28, 26, 32), fill=0)
    assert has_visual_bullet(image, (40, 20, 160, 40))
    assert not has_visual_bullet(image, (40, 45, 160, 65))


def test_invalid_or_degenerate_boxes_are_not_bullets() -> None:
    image = Image.new("L", (200, 100), 255)
    assert not has_visual_bullet(image, (40, 20, 160, 20))
    assert not has_visual_bullet(image, (float("nan"), 20, 160, 40))


def test_actual_poster_recovers_all_visible_list_items() -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "user_samples" / "hackathon-guidelines.png"
    if not fixture.is_file():
        pytest.skip("Local user poster is not included in the repository.")
    with Image.open(fixture) as original:
        image = original.convert("RGB").resize((original.width * 2, original.height * 2))
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    blocks = recognize(encoded.getvalue(), 1, scale=2)
    lists = [block for block in blocks if block.type == "list"]
    assert len(lists) == 23
    for expected in (
        "Teams should collaborate",
        "Each team must select",
        "The problem and selected use case",
    ):
        block = next(block for block in lists if block.text.startswith(expected))
        assert block.markdown == "- " + block.text
        assert block.source == "ocr"
        assert block.confidence is not None
    assert next(block for block in blocks if block.text == "Build Sprint").type == "paragraph"
    assert (
        next(block for block in blocks if block.text.startswith("Each team will present")).type
        == "paragraph"
    )
    for block in blocks:
        if block.text == "O":
            assert block.is_decorative
            assert block.type == "other"
            assert block.markdown == ""
            print(
                f"Decorative circle recognized as O: bbox={block.bbox}, "
                f"confidence={block.confidence}"
            )


def test_attached_colored_circle_is_decorative_but_isolated_glyph_is_kept() -> None:
    from rag_pre_ingest.pipeline.ocr_lists import is_decorative_circle

    image = Image.new("RGB", (1000, 1000), "#0d1451")
    draw = ImageDraw.Draw(image)
    draw.ellipse((200, 200, 212, 212), outline="#41abd5", width=2)
    assert not is_decorative_circle(image, (199, 199, 213, 213), "O")
    draw.line((150, 206, 200, 206), fill="#41abd5", width=2)
    assert is_decorative_circle(image, (199, 199, 213, 213), "O")
    assert not is_decorative_circle(image, (199, 199, 213, 213), "0")


def test_printed_o_and_separate_node_label_are_kept() -> None:
    from rag_pre_ingest.pipeline.ocr_lists import is_decorative_circle

    image = Image.new("RGB", (1000, 1000), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((200, 200, 212, 212), outline="black", width=2)
    assert not is_decorative_circle(image, (199, 199, 213, 213), "O")
    draw.rectangle((190, 190, 225, 225), outline="#2385ba", width=2)
    draw.line((150, 206, 190, 206), fill="#2385ba", width=2)
    assert not is_decorative_circle(image, (199, 199, 213, 213), "O")


def test_inline_comma_and_label_colon_are_not_inferred_bullets() -> None:
    from rag_pre_ingest.pipeline.ocr_lists import has_left_text_fragment

    target = (140.0, 20.0, 300.0, 40.0)
    assert has_left_text_fragment(target, [((20, 20, 130, 40), "calm,")])
    assert has_left_text_fragment(target, [((20, 20, 152, 40), "calm, t")])
    assert has_left_text_fragment(target, [((20, 20, 130, 40), "Primary:")])
    assert not has_left_text_fragment(target, [((20, 45, 130, 65), "Different baseline,")])
    assert not has_left_text_fragment(target, [((20, 20, 70, 40), "Far away,")])
    assert not has_left_text_fragment(target, [((120, 25, 130, 35), "•")])
    assert normalize_list_prefix("• Explicit bullet", False) == (True, "Explicit bullet")


def test_adapter_does_not_turn_left_fragment_comma_into_a_bullet() -> None:
    from types import SimpleNamespace
    from unittest.mock import Mock, patch

    image = Image.new("L", (400, 100), 255)
    ImageDraw.Draw(image).rectangle((126, 28, 130, 32), fill=0)
    data = io.BytesIO()
    image.save(data, format="PNG")
    output = SimpleNamespace(
        boxes=[
            [[20, 20], [132, 20], [132, 40], [20, 40]],
            [[140, 20], [300, 20], [300, 40], [140, 40]],
        ],
        txts=["calm,", "trustworthy, organic"],
        scores=[0.9, 0.9],
    )
    with patch("rag_pre_ingest.pipeline.ocr._get_engine", return_value=Mock(return_value=output)):
        blocks = recognize(data.getvalue(), 1)
    assert blocks[1].type == "paragraph"
    assert blocks[1].markdown == "trustworthy, organic"


def test_actual_theme_fragments_are_not_false_lists() -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "user_samples" / "theme-palette.png"
    if not fixture.is_file():
        pytest.skip("Local user theme image is not included in repository.")
    with Image.open(fixture) as original:
        image = original.convert("RGB").resize((original.width * 2, original.height * 2))
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    blocks = recognize(encoded.getvalue(), 1, scale=2)
    assert not [block.text for block in blocks if block.type == "list"]
    assert any("trustworthy" in block.text for block in blocks)
    assert any("Notion" in block.text for block in blocks)
