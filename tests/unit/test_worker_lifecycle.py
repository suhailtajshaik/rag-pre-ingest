from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rag_pre_ingest.config import Settings
from rag_pre_ingest.models.document import DocumentResult
from rag_pre_ingest.pipeline.readers import read_document
from rag_pre_ingest.services.worker import Worker
from rag_pre_ingest.storage.jobs import JobRepository


@pytest.mark.parametrize("timed_out", [True, False])
@pytest.mark.parametrize("checkpoint", [True, False])
def test_child_interruption_completes_with_recovered_content(
    tmp_path: Path, timed_out: bool, checkpoint: bool
) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    repository.initialize()
    job, _ = repository.create_job("hash", "file.pdf", "pdf", b"file", tmp_path / "uploads")
    worker = Worker(Settings(data_dir=tmp_path), repository)
    process = MagicMock()
    process.exitcode = 1
    process.is_alive.side_effect = [True, False] if timed_out else [False]

    def make_process(**kwargs: object) -> MagicMock:
        args = kwargs["args"]
        assert isinstance(args, tuple)
        if checkpoint:
            result = read_document(b"bad", "pdf", "file.pdf", "hash", job["id"])
            result.markdown = "Already completed page"
            (Path(args[2]).parent / "checkpoint.json").write_text(result.model_dump_json())
        return process

    context = MagicMock()
    context.Process.side_effect = make_process
    with patch("rag_pre_ingest.services.worker.multiprocessing.get_context", return_value=context):
        worker.process(job)
    saved = repository.get_job(job["id"])
    assert saved is not None and saved["status"] == "done"
    paths = repository.result_paths(job["id"])
    assert paths is not None
    result = DocumentResult.model_validate_json(paths[0].read_text())
    codes = {warning.code for warning in result.warnings}
    assert ("job_timeout" if timed_out else "processing_interrupted") in codes
    assert result.markdown == ("Already completed page" if checkpoint else "")
    if not checkpoint:
        assert "empty_document" in codes
    assert result.stats.warnings.total == len(result.warnings)
    assert process.terminate.call_count == int(timed_out)


def test_graceful_stop_leaves_active_job_recoverable(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    repository.initialize()
    job, _ = repository.create_job("hash", "file.pdf", "pdf", b"file", tmp_path / "uploads")
    worker = Worker(Settings(data_dir=tmp_path), repository)
    process = MagicMock()
    process.exitcode = -15
    process.is_alive.return_value = False
    process.join.side_effect = lambda _: worker.stop()
    context = MagicMock()
    context.Process.return_value = process
    with patch("rag_pre_ingest.services.worker.multiprocessing.get_context", return_value=context):
        worker.process(job)
    saved = repository.get_job(job["id"])
    assert saved is not None and saved["status"] == "running"
    repository.recover_running()
    saved = repository.get_job(job["id"])
    assert saved is not None and saved["status"] == "queued"
