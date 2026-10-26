from collections import Counter
from pathlib import Path

from rag_pre_ingest.models.document import Block, Page
from rag_pre_ingest.pipeline.readers import read_document
from rag_pre_ingest.pipeline.tables import _source_tokens, detect_tables


def test_real_multiline_pdf_cells_retain_alignment_and_reading_order() -> None:
    path = Path("tests/fixtures/user_samples/ml-cyber-roles.pdf")
    result = read_document(path.read_bytes(), "pdf", path.name, "hash", "id")
    assert len(result.pages) == 2
    detected = []
    for page in result.pages:
        reconstructed, warnings = detect_tables(page, page.ruling_lines, page.words)
        assert not warnings
        tables = [block for block in reconstructed.blocks if block.type == "table"]
        assert len(tables) == 1
        table = tables[0]
        detected.append(table)
        source = [
            block
            for block in page.blocks
            if table.bbox[0] <= (block.bbox[0] + block.bbox[2]) / 2 <= table.bbox[2]
            and table.bbox[1] <= (block.bbox[1] + block.bbox[3]) / 2 <= table.bbox[3]
        ]
        assert Counter(
            token for block in source for token in _source_tokens(block.text)
        ) == Counter(token for cell in table.cells for token in _source_tokens(cell.text))
        assert table.columns == 3
    assert detected[0].rows == 4
    assert detected[0].cells[3].text == "MLOps Engineer / Senior\nMLOps Engineer"
    assert (
        detected[0]
        .cells[4]
        .text.startswith("Python for production ML (APIs, testing,\npackaging) CI/CD for ML")
    )
    assert "experiment tracking (MLflow, W&B;)" in detected[0].cells[4].text
    assert detected[1].rows == 1
    assert detected[1].cells[0].text == "Data Engineer (ML-focused)"
    assert (
        detected[1]
        .cells[1]
        .text.startswith("SQL and data modeling for analytical and\nML use cases Python/Scala")
    )
    assert "<br>" not in detected[1].markdown
    assert "Data Engineer (ML-focused)" in detected[1].markdown


def test_glyph_top_jitter_does_not_reorder_words_on_same_line() -> None:
    words = [
        Block(id=str(index), type="paragraph", text=value, bbox=box)
        for index, (value, box) in enumerate(
            [
                ("Python", (10, 10.1, 45, 19.3)),
                ("for", (50, 10.0, 65, 19.8)),
                ("production", (70, 10.3, 110, 19.2)),
                ("ML", (115, 10.0, 130, 19.8)),
                ("Second", (10, 22.1, 45, 31.3)),
                ("line", (50, 22.0, 65, 31.8)),
            ]
        )
    ]
    page = Page(page_number=1, width=200, height=100, blocks=words)
    lines = [(0, 0, 150, 0), (0, 40, 150, 40), (0, 0, 0, 40), (150, 0, 150, 40)]
    detected, warnings = detect_tables(page, lines, list(reversed(words)))
    assert not warnings
    assert detected.blocks[0].cells[0].text == "Python for production ML\nSecond line"


def test_punctuation_segmentation_is_equivalent_without_relaxing_word_loss() -> None:
    assert Counter(_source_tokens("W &B; )")) == Counter(_source_tokens("W&B;)"))
    assert Counter(_source_tokens("W&B;) critical")) != Counter(_source_tokens("W&B;)"))
    assert Counter(_source_tokens("Surface:#FFFFFF")) == Counter(_source_tokens("Surface: #FFFFFF"))
