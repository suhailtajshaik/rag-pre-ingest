import hashlib
from pathlib import Path

from rag_pre_ingest.config import Settings
from rag_pre_ingest.pipeline.engine import run_pipeline


def test_tech_stack_category_values_stay_together(tmp_path: Path) -> None:
    path = Path("tests/fixtures/user_samples/tech-stack.png")
    data = path.read_bytes()
    result = run_pipeline(
        data, "png", path.name, hashlib.sha256(data).hexdigest(), "tech", Settings(), tmp_path
    )
    assert "CLAUDE CODE\n\nEngineering Design:" in result.markdown
    labels = [
        "Frontend",
        "Vercel",
        "Database",
        "MongoDB",
        "Auth / Login",
        "clerk",
        "Emails",
        "Resend",
        "Cloud / VMs",
        "DigitalOcean",
        "Object storage",
        "CLOUDFLARE",
        "AI models",
        "Gemini",
    ]
    positions = [result.markdown.index(label) for label in labels]
    assert positions == sorted(positions)


def test_category_rows_preserve_pairs_and_inputs() -> None:
    from rag_pre_ingest.models.document import Block
    from rag_pre_ingest.pipeline.layout import _category_rows

    blocks = [
        b
        for i in range(5)
        for b in (
            Block(
                id=f"key{i}",
                type="paragraph",
                source="ocr",
                text=f"Category{i}",
                bbox=(100, 100 + i * 100, 250, 130 + i * 100),
            ),
            Block(
                id=f"value{i}",
                type="paragraph",
                source="ocr",
                text=f"Value{i}",
                bbox=(450, 100 + i * 100, 700, 130 + i * 100),
            ),
        )
    ]
    original = [b.model_dump() for b in blocks]
    ordered = _category_rows(list(reversed(blocks)), 1000)
    assert ordered is not None
    assert [b.id for b in ordered] == [b.id for b in blocks]
    assert [b.model_dump() for b in blocks] == original
    for b in blocks:
        b.text = "A complete sentence in an ordinary article column."
    assert _category_rows(blocks, 1000) is None


def test_category_rows_decline_spanning_values() -> None:
    from rag_pre_ingest.models.document import Block
    from rag_pre_ingest.pipeline.layout import _category_rows

    blocks = [
        b
        for i in range(5)
        for b in (
            Block(
                id=f"key{i}",
                type="paragraph",
                source="ocr",
                text=f"Category{i}",
                bbox=(100, 100 + i * 100, 250, 130 + i * 100),
            ),
            Block(
                id=f"value{i}",
                type="paragraph",
                source="ocr",
                text=f"Value{i}",
                bbox=(450, 100 + i * 100, 700, 250 + i * 100),
            ),
        )
    ]
    assert _category_rows(blocks, 1000) is None
