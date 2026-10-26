import tempfile
from pathlib import Path
from unittest.mock import patch

from rag_pre_ingest.config import Settings
from rag_pre_ingest.models.document import Block, Page
from rag_pre_ingest.pipeline.engine import run_pipeline
from rag_pre_ingest.pipeline.sanitizer import merge_list_continuations


def block(identifier: str, text: str, kind: str, box: tuple[float, float, float, float]) -> Block:
    return Block(id=identifier, type=kind, text=text, markdown=text, bbox=box, source="ocr")  # type: ignore[arg-type]


def test_centered_ocr_list_wraps_into_existing_item_without_renumbering() -> None:
    page = Page(
        page_number=1,
        width=600,
        height=800,
        blocks=[
            block("a", "2. DO THEY CHALLENGE", "list", (60, 100, 540, 170)),
            block("b", "ME IN WAYS THAT", "paragraph", (120, 165, 480, 205)),
            block("c", "ELEVATE ME?", "paragraph", (170, 210, 430, 250)),
            block("d", "3. NEXT QUESTION", "list", (60, 350, 540, 420)),
        ],
    )
    result = merge_list_continuations(page)
    assert [b.text for b in result.blocks] == [
        "2. DO THEY CHALLENGE ME IN WAYS THAT ELEVATE ME?",
        "3. NEXT QUESTION",
    ]
    assert result.blocks[0].bbox == (60, 100, 540, 250)
    assert len(page.blocks) == 4


def test_list_completion_gaps_and_columns_prevent_unrelated_attachment() -> None:
    page = Page(
        page_number=1,
        width=600,
        height=800,
        blocks=[
            block("a", "1. Complete.", "list", (20, 20, 260, 60)),
            block("b", "A new paragraph", "paragraph", (20, 65, 260, 105)),
            block("c", "2. Incomplete", "list", (20, 200, 260, 240)),
            block("d", "Other column", "paragraph", (320, 245, 560, 285)),
            block("e", "3. Separate", "list", (20, 400, 260, 440)),
            block("f", "Footer", "paragraph", (20, 550, 260, 590)),
        ],
    )
    assert merge_list_continuations(page) == page


def test_real_numbered_poster_retains_three_complete_questions() -> None:
    path = Path("tests/fixtures/user_samples/numbered-questions.png")
    with (
        tempfile.TemporaryDirectory() as folder,
        patch("socket.socket.connect", side_effect=AssertionError("Offline OCR required")),
    ):
        result = run_pipeline(
            path.read_bytes(), "png", path.name, "hash", "test", Settings(), Path(folder)
        )
    lists = [b for p in result.pages for b in p.blocks if b.type == "list"]
    assert [b.text for b in lists] == [
        "1. DO I LIKE WHO I AM WHEN I'M AROUND THEM?",
        "2. DO THEY CHALLENGE ME IN WAYS THAT ELEVATE ME?",
        "3. DOES MY BEHAVIOR MOVE ME CLOSER OR FURTHER FROM MY VALUES?",
    ]
    assert all(item.text in result.markdown for item in lists)
    assert len([b for p in result.pages for b in p.blocks if b.type == "paragraph"]) == 1
