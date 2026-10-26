"""Every generated upload scenario has an independently checked door outcome."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from rag_pre_ingest.pipeline.readers import read_document
from rag_pre_ingest.pipeline.validation import ValidationConfig, ValidationError, validate_upload

ROOT = Path(__file__).resolve().parents[1] / "fixtures/synthetic"
MANIFEST = json.loads((ROOT / "manifest.json").read_text())["fixtures"]


@pytest.mark.parametrize("fixture", MANIFEST, ids=[item["file"] for item in MANIFEST])
def test_fixture_validation(fixture: dict[str, object]) -> None:
    name = str(fixture["file"])
    config = ValidationConfig(**fixture["config"])  # type: ignore[arg-type]
    data = (ROOT / name).read_bytes()
    if fixture["validation"] == "accepted":
        result = validate_upload(data, name, config)
        assert result.file_type
        if name == "13-wrong-extension.docx":
            assert result.file_type == "pdf"
            assert result.extension_mismatch
    else:
        with pytest.raises(ValidationError) as error:
            validate_upload(data, name, config)
        assert error.value.code == fixture["validation"]


def test_fixture_coverage() -> None:
    assert len(MANIFEST) >= 25
    scenarios = {scenario for fixture in MANIFEST for scenario in fixture["scenarios"]}
    assert {
        "two_columns",
        "zip_expansion_limit",
        "ocr_required",
        "special_characters",
        "non_latin",
        "merged_cells",
        "blank_cells",
        "page_numbers",
    } <= scenarios


def test_unicode_direct_read_preserves_content() -> None:
    for name, kind in [("18-structured.docx", "docx"), ("19-structured.xlsx", "xlsx")]:
        result = read_document((ROOT / name).read_bytes(), kind, name, "test", "test")
        assert "café" in result.markdown
        assert "中文" in result.markdown
        assert "العربية" in result.markdown
    result = read_document(
        (ROOT / "18-structured.docx").read_bytes(), "docx", "unicode.docx", "test", "test"
    )
    assert "Ligatures fi fl; nonbreaking space; café résumé." in result.markdown


def test_generator_is_reproducible(tmp_path: Path) -> None:
    path = Path(__file__).resolve().parents[2] / "scripts/generate_fixtures.py"
    spec = importlib.util.spec_from_file_location("fixture_generator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.generate(tmp_path / "first")
    module.generate(tmp_path / "second")
    for entry in (tmp_path / "first").iterdir():
        assert entry.read_bytes() == (tmp_path / "second" / entry.name).read_bytes()
