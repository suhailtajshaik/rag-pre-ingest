"""OCR adapter tests isolate model inference with realistic RapidOCR result fields."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from rag_pre_ingest.pipeline import ocr


def output(text: str = " recognized text ") -> SimpleNamespace:
    return SimpleNamespace(
        boxes=[[[2, 4], [22, 4], [22, 14], [2, 14]]],
        txts=[text],
        scores=[0.87],
    )


def test_ocr_maps_crop_and_render_scale_to_page_coordinates() -> None:
    engine = Mock(return_value=output())
    with patch.object(ocr, "_get_engine", return_value=engine):
        blocks = ocr.recognize(b"encoded-image", 3, origin=(100, 200), scale=2)
    assert len(blocks) == 1
    block = blocks[0]
    assert block.id == "p3_ocr1"
    assert block.source == "ocr"
    assert block.confidence == 0.87
    assert block.text == block.markdown == "recognized text"
    assert block.bbox == (101, 202, 111, 207)
    engine.assert_called_once_with(b"encoded-image")


@pytest.mark.parametrize(
    "result", [SimpleNamespace(boxes=None, txts=None, scores=None), output(" ")]
)
def test_no_text_produces_no_blocks(result: SimpleNamespace) -> None:
    with patch.object(ocr, "_get_engine", return_value=Mock(return_value=result)):
        assert ocr.recognize(b"image", 1) == []


@pytest.mark.parametrize("scale", [0, -1, float("inf"), float("nan")])
def test_invalid_scale_is_rejected_before_inference(scale: float) -> None:
    with patch.object(ocr, "_get_engine") as engine:
        with pytest.raises(ValueError, match="scale"):
            ocr.recognize(b"image", 1, scale=scale)
        engine.assert_not_called()


def test_bad_output_is_reported_for_caller_to_warn() -> None:
    result = output()
    result.scores = []
    with patch.object(ocr, "_get_engine", return_value=Mock(return_value=result)):
        with pytest.raises(ValueError, match="inconsistent"):
            ocr.recognize(b"image", 1)


def test_engine_failure_is_not_silently_swallowed() -> None:
    with patch.object(ocr, "_get_engine", side_effect=RuntimeError("model unavailable")):
        with pytest.raises(RuntimeError, match="model unavailable"):
            ocr.recognize(b"image", 1)


def test_model_directory_requires_explicit_local_model_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="det.onnx"):
        ocr._get_engine(tmp_path)


def test_engine_is_cached_per_model_configuration(tmp_path: Path) -> None:
    for name in ("det.onnx", "cls.onnx", "rec.onnx"):
        (tmp_path / name).write_bytes(b"model")
    with patch("rapidocr.RapidOCR") as factory:
        first = ocr._get_engine(tmp_path)
        assert ocr._get_engine(tmp_path) is first
        factory.assert_called_once()
        assert factory.call_args.kwargs["params"]["Det.model_path"] == str(tmp_path / "det.onnx")


def test_bundled_models_recognize_fixture_without_network() -> None:
    import time

    fixture = Path(__file__).parents[1] / "fixtures" / "synthetic" / "20-scan.png"
    if not fixture.exists():
        pytest.skip("Generate synthetic fixtures before running local model inference.")
    started = time.monotonic()
    with patch("socket.socket.connect", side_effect=AssertionError("OCR must stay offline")):
        blocks = ocr.recognize(fixture.read_bytes(), page_number=1)
    text = "\n".join(block.text for block in blocks)
    assert "Invoice total 123.45" in text
    assert all(block.source == "ocr" for block in blocks)
    assert all(block.confidence is not None for block in blocks)
    print(f"Offline OCR fixture recognized in {time.monotonic() - started:.2f}s: {text}")
