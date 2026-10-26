from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rag_pre_ingest.config import Settings
from rag_pre_ingest.services.deletion import DeletionService
from rag_pre_ingest.services.results import ResultUnavailable
from rag_pre_ingest.services.worker import Worker
from rag_pre_ingest.storage.jobs import JobRepository


def setup(tmp_path: Path) -> tuple[JobRepository, Worker, DeletionService]:
    settings = Settings(data_dir=tmp_path)
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    repository.initialize()
    worker = Worker(settings, repository)
    return repository, worker, DeletionService(repository, worker, settings)


def test_delete_queued_and_reupload_releases_hash(tmp_path: Path) -> None:
    repository, _, service = setup(tmp_path)
    job, _ = repository.create_job("hash", "file.pdf", "pdf", b"file", tmp_path / "uploads")
    service.delete(job["id"])
    assert repository.get_job(job["id"]) is None
    assert not (tmp_path / "uploads" / job["id"]).exists()
    replacement, duplicate = repository.create_job(
        "hash", "file.pdf", "pdf", b"file", tmp_path / "uploads"
    )
    assert not duplicate and replacement["id"] != job["id"]
    with pytest.raises(ResultUnavailable) as error:
        service.delete(job["id"])
    assert error.value.status == 404


def test_delete_completed_removes_previews_crops_and_results(tmp_path: Path) -> None:
    repository, _, service = setup(tmp_path)
    job, _ = repository.create_job("hash", "file.pdf", "pdf", b"file", tmp_path / "uploads")
    folder = tmp_path / "results" / job["id"]
    folder.mkdir(parents=True)
    for name in ["result.json", "document.md", "page-1.png", "crop-1.png"]:
        (folder / name).write_text("content")
    repository.mark_running(job["id"])
    repository.finish_job(job["id"], folder / "result.json", folder / "document.md", {}, [])
    service.delete(job["id"])
    assert not folder.exists()
    assert repository.result_paths(job["id"]) is None


def test_delete_active_job_terminates_without_resurrection(tmp_path: Path) -> None:
    repository, worker, service = setup(tmp_path)
    job, _ = repository.create_job("hash", "file.pdf", "pdf", b"file", tmp_path / "uploads")
    process = MagicMock()
    process.exitcode = -15
    process.is_alive.return_value = False

    def deleted_during_join(timeout: float) -> None:
        process.is_alive.return_value = True
        service.delete(job["id"])
        process.is_alive.return_value = False

    process.join.side_effect = deleted_during_join
    context = MagicMock()
    context.Process.return_value = process
    with patch("rag_pre_ingest.services.worker.multiprocessing.get_context", return_value=context):
        worker.process(job)
    process.terminate.assert_called_once()
    assert repository.get_job(job["id"]) is None
    assert not (tmp_path / "results" / job["id"]).exists()


def test_symlink_cannot_delete_outside_storage(tmp_path: Path) -> None:
    repository, _, service = setup(tmp_path)
    job, _ = repository.create_job("hash", "file.pdf", "pdf", b"file", tmp_path / "uploads")
    victim = tmp_path / "outside"
    victim.write_text("keep")
    upload = tmp_path / "uploads" / job["id"]
    upload.unlink()
    upload.symlink_to(victim)
    with pytest.raises(ResultUnavailable) as error:
        service.delete(job["id"])
    assert error.value.code == "unsafe_storage_path"
    assert victim.read_text() == "keep"
    assert repository.get_job(job["id"]) is not None
