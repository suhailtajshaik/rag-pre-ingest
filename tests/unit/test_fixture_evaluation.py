from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from rag_pre_ingest.models.document import Warning
from rag_pre_ingest.pipeline.readers import read_document


def evaluator() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts/evaluate_fixtures.py"
    spec = importlib.util.spec_from_file_location("fixture_evaluation", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_and_user_cases_present() -> None:
    module = evaluator()
    cases = module.cases()
    assert len(cases) == 42
    assert len({item["file"] for item in cases}) == 42
    assert any(item["file"] == "learning-levels.png" for item in cases)
    assert any(item["file"] == "hackathon-guidelines.png" for item in cases)
    assert any(item["file"] == "notebooklm-mind-map.png" for item in cases)
    assert any(item["file"] == "theme-palette.png" for item in cases)
    assert any(item["file"] == "theme-cards.png" for item in cases)
    assert any(item["file"] == "python-code.png" for item in cases)
    assert any(item["file"] == "ml-cyber-roles.pdf" for item in cases)
    assert any(item["file"] == "numbered-questions.png" for item in cases)
    assert any(item["file"] == "sales-sheet.png" for item in cases)


def test_rejection_cases_run_without_pipeline() -> None:
    module = evaluator()
    cases = [item for item in module.cases() if item["validation"] != "accepted"]
    assert len(cases) >= 10
    for case in cases:
        summary = module.evaluate(case)
        assert summary["failures"] == []
        assert summary["actual_validation"] == case["validation"]


def test_scan_assertion_detects_missing_text() -> None:
    module = evaluator()
    result = read_document(b"broken", "pdf", "test", "", "")
    result.warnings = []
    result.markdown = "SCANNED DOCUMENT"
    failures = module.check_result("07-scan.pdf", result)
    assert "Scan invoice value missing" in failures
    result.markdown += "\nInvoice total 123.45"
    assert module.check_result("07-scan.pdf", result) == []


def test_markers_and_processing_warnings_fail_evaluation() -> None:
    module = evaluator()
    result = read_document(b"broken", "pdf", "test", "", "")
    result.markdown = "![placeholder](image.png)"
    result.warnings = [Warning(code="ocr_unavailable", message="Missing models")]
    failures = module.check_result("test", result)
    assert "Image syntax leaked into clean markdown" in failures
    assert "A page or OCR stage failed" in failures


def test_mindmap_assertions_require_labels() -> None:
    module = evaluator()
    result = read_document(b"broken", "pdf", "test", "", "")
    result.warnings = []
    result.markdown = "World Modeling"
    failures = module.check_result("notebooklm-mind-map.png", result)
    assert any("Context Encoder" in failure for failure in failures)
    assert not any("World Modeling" in failure for failure in failures)


def test_report_preserves_actual_failure(tmp_path: Path) -> None:
    module = evaluator()
    destination = tmp_path / "report.md"
    module.report(
        [
            {
                "file": "bad.pdf",
                "expected_validation": "accepted",
                "actual_validation": "accepted",
                "failures": ["Source text missing"],
                "warnings": [],
            }
        ],
        destination,
    )
    text = destination.read_text()
    assert "0/1" in text
    assert "Source text missing" in text
