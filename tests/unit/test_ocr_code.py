import ast
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from rag_pre_ingest.models.document import Document, DocumentResult, Page, Stats
from rag_pre_ingest.pipeline.ocr import recognize
from rag_pre_ingest.pipeline.ocr_code import (
    code_line_crops,
    code_text,
    looks_like_code,
    preserves_code_content,
    recover_bracket,
)
from rag_pre_ingest.pipeline.sanitizer import sanitize_document


@pytest.mark.parametrize(
    "texts,expected",
    [
        (["import os", "client = Client(", 'key="value",'], True),
        (["import os"], False),
        (["Import your document", "client satisfaction", "role: user"], False),
        (["BG: #FFF", "Surface: #000", "Accent: #ABC"], False),
    ],
)
def test_code_detection_requires_multiple_syntax_signals(texts: list[str], expected: bool) -> None:
    assert looks_like_code(texts) == expected


def test_code_geometry_keeps_indentation_and_blank_lines() -> None:
    assert (
        code_text(
            [
                ((0, 0, 60, 10), "call_fn("),
                ((30, 15, 90, 25), "value=42,"),
                ((0, 30, 5, 40), ")"),
                ((0, 60, 100, 70), "print(value)"),
            ]
        )
        == "call_fn(\n    value=42,\n)\n\nprint(value)"
    )
    assert code_text([]) == ""


def test_bracket_recovery_requires_visible_matching_caps() -> None:
    bracket = Image.new("RGB", (40, 60), "white")
    draw = ImageDraw.Draw(bracket)
    draw.line([(10, 10), (20, 10), (20, 50), (10, 50)], fill="black", width=3)
    assert recover_bracket(bracket, "1,") == "],"
    digit = Image.new("RGB", (40, 60), "white")
    ImageDraw.Draw(digit).line([(10, 18), (20, 10), (20, 50)], fill="black", width=3)
    assert recover_bracket(digit, "1") == "1"
    assert recover_bracket(bracket, "version1") == "version1"


def test_no_lines_without_enough_code_observations() -> None:
    assert code_line_crops(Image.new("RGB", (100, 100)), []) == []


def test_line_reconstruction_must_preserve_initial_readable_content() -> None:
    assert preserves_code_content(
        ['"content": "capitalof France"', "S"], ["{", '"content": "capital of France"']
    )
    assert not preserves_code_content(["import os", "import important_module"], ["import os"])
    assert not preserves_code_content(["import os"], [])


def test_actual_code_screenshot_preserves_source_structure_without_execution() -> None:
    path = Path("tests/fixtures/user_samples/python-code.png")
    with patch("socket.socket.connect", side_effect=AssertionError("OCR must stay offline")):
        blocks = recognize(path.read_bytes(), 1)
    assert len(blocks) == 1
    block = blocks[0]
    assert block.source == "ocr" and not block.is_decorative
    assert block.markdown.startswith("```python\nimport os\nfrom openai import OpenAI\n")
    assert '\n    messages=[\n        {\n            "role": "user",' in block.text
    assert "\n        }\n    ],\n)" in block.text
    assert "capital of France?" in block.text
    assert 'base_url="https://router.huggingface.co/v1",' in block.text
    # Parsing verifies punctuation but never executes attached source code.
    ast.parse(block.text)
    original = block.text
    result = sanitize_document(
        DocumentResult(
            document=Document(
                id="test",
                file_name=path.name,
                file_type="png",
                file_hash="test",
                page_count=1,
                processed_at=datetime.now(UTC),
            ),
            stats=Stats(),
            markdown="",
            pages=[Page(page_number=1, width=1384, height=978, blocks=blocks)],
        )
    )
    assert result.pages[0].blocks[0].text == original
    assert result.markdown == block.markdown
    # Recognition-only crops must not leave the cached engine's detector disabled.
    scan = recognize(Path("tests/fixtures/synthetic/20-scan.png").read_bytes(), 1)
    assert any("Invoice total 123.45" in b.text for b in scan)
