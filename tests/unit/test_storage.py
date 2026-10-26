"""Persistence, rollback, and concurrent duplicate behavior."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from rag_pre_ingest.storage import JobRepository


@pytest.fixture
def repository(tmp_path: Path) -> JobRepository:
    repository = JobRepository(tmp_path / "state" / "jobs.sqlite3")
    repository.initialize()
    return repository


def test_initialize_is_repeatable_and_enables_wal(repository: JobRepository) -> None:
    repository.initialize()
    with sqlite3.connect(repository.db_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)


def test_create_persists_job_and_generated_upload_name(
    repository: JobRepository, tmp_path: Path
) -> None:
    uploads = tmp_path / "uploads"
    warning: dict[str, object] = {"code": "extension_mismatch", "message": "Mismatch"}
    job, existing = repository.create_job(
        "abc", "client.pdf", "pdf", b"content", uploads, [warning]
    )
    assert existing is False
    assert job["status"] == "queued"
    assert job["current_stage"] == "queued"
    assert job["progress"] == 0
    assert job["error"] is None
    assert job["warnings"] == [warning]
    assert job["file_hash"] == "abc"
    assert job["file_name"] == "client.pdf"
    assert (uploads / job["id"]).read_bytes() == b"content"
    reopened = JobRepository(repository.db_path)
    assert reopened.get_job(job["id"]) == job
    assert "upload_path" not in job


def test_missing_job_returns_none(repository: JobRepository) -> None:
    assert repository.get_job("missing") is None
    assert repository.get_job("' OR 1=1 --") is None


def test_duplicate_preserves_original_job_and_file(
    repository: JobRepository, tmp_path: Path
) -> None:
    uploads = tmp_path / "uploads"
    original, _ = repository.create_job("same", "a.pdf", "pdf", b"one", uploads)
    duplicate, existing = repository.create_job("same", "b.pdf", "pdf", b"two", uploads)
    assert existing is True
    assert duplicate == original
    assert len(list(uploads.iterdir())) == 1
    assert (uploads / original["id"]).read_bytes() == b"one"


def test_concurrent_identical_uploads_create_one_job(
    repository: JobRepository, tmp_path: Path
) -> None:
    def upload(_: int) -> tuple[str, bool]:
        job, existing = repository.create_job(
            "same", "doc.pdf", "pdf", b"bytes", tmp_path / "uploads"
        )
        return job["id"], existing

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(upload, range(16)))
    assert len({job_id for job_id, _ in results}) == 1
    assert sum(not existing for _, existing in results) == 1
    assert len(list((tmp_path / "uploads").iterdir())) == 1


def test_failed_write_leaves_no_job_or_upload(repository: JobRepository, tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    with patch("rag_pre_ingest.storage.jobs.os.fsync", side_effect=OSError("disk")):
        with pytest.raises(OSError, match="disk"):
            repository.create_job("abc", "a.pdf", "pdf", b"bytes", uploads)
    assert list(uploads.iterdir()) == []
    with sqlite3.connect(repository.db_path) as connection:
        assert connection.execute("SELECT count(*) FROM jobs").fetchone() == (0,)


def test_failed_insert_removes_upload(repository: JobRepository, tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_insert BEFORE INSERT ON jobs
            BEGIN SELECT RAISE(ABORT, 'test failure'); END"""
        )
    with pytest.raises(sqlite3.IntegrityError, match="test failure"):
        repository.create_job("abc", "a.pdf", "pdf", b"bytes", uploads)
    assert list(uploads.iterdir()) == []


def test_rejection_audit_has_no_job(repository: JobRepository) -> None:
    repository.record_rejection("empty.pdf", "empty_file", "Upload is empty")
    with sqlite3.connect(repository.db_path) as connection:
        assert connection.execute("SELECT count(*) FROM jobs").fetchone() == (0,)
        assert connection.execute("SELECT file_name, code, message FROM rejections").fetchone() == (
            "empty.pdf",
            "empty_file",
            "Upload is empty",
        )


def test_worker_lifecycle_and_result_metadata(repository: JobRepository, tmp_path: Path) -> None:
    job, _ = repository.create_job("life", "a.pdf", "pdf", b"doc", tmp_path / "uploads")
    job_id = job["id"]
    assert repository.result_paths(job_id) is None
    assert repository.get_upload(job_id) == b"doc"
    assert repository.mark_running(job_id)
    assert not repository.mark_running(job_id)
    repository.update_progress(job_id, "markdown", 0.75)
    running = repository.get_job(job_id)
    assert running is not None
    assert (running["status"], running["current_stage"], running["progress"]) == (
        "running",
        "markdown",
        0.75,
    )
    warning: dict[str, object] = {"code": "empty_document", "message": "Empty"}
    stats: dict[str, object] = {"pages": {"total": 1}, "duration_seconds": 0.1}
    repository.finish_job(
        job_id, tmp_path / "result.json", tmp_path / "result.md", stats, [warning]
    )
    done = repository.get_job(job_id)
    assert done is not None
    assert (done["status"], done["progress"], done["stats"], done["warnings"]) == (
        "done",
        1,
        stats,
        [warning],
    )
    assert repository.result_paths(job_id) == (tmp_path / "result.json", tmp_path / "result.md")
    repository.update_progress(job_id, "late", 0.5)
    repository.fail_job(job_id, "late_error", "Late callback")
    assert repository.get_job(job_id) == done


def test_failed_job_retains_stable_code(repository: JobRepository, tmp_path: Path) -> None:
    job, _ = repository.create_job("failure", "a.pdf", "pdf", b"doc", tmp_path / "uploads")
    repository.fail_job(job["id"], "storage_error", "Unable to read upload")
    failed = repository.get_job(job["id"])
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["error_code"] == "storage_error"
    assert failed["error"] == "Unable to read upload"
    assert repository.result_paths(job["id"]) is None


def test_restart_recovers_only_running_jobs(repository: JobRepository, tmp_path: Path) -> None:
    first, _ = repository.create_job("first", "a.pdf", "pdf", b"a", tmp_path / "uploads")
    second, _ = repository.create_job("second", "b.pdf", "pdf", b"b", tmp_path / "uploads")
    repository.mark_running(first["id"])
    repository.update_progress(first["id"], "read", 0.5)
    repository.fail_job(second["id"], "error", "Failed")
    repository.recover_running()
    queued = repository.queued_jobs()
    assert len(queued) == 1
    assert queued[0]["id"] == first["id"]
    assert queued[0]["status"] == queued[0]["current_stage"] == "queued"
    assert queued[0]["progress"] == 0
    failed = repository.get_job(second["id"])
    assert failed is not None
    assert failed["status"] == "failed"


def test_recent_jobs_limit_and_missing_upload(repository: JobRepository, tmp_path: Path) -> None:
    repository.create_job("first", "a.pdf", "pdf", b"a", tmp_path / "uploads")
    newest, _ = repository.create_job("second", "b.pdf", "pdf", b"b", tmp_path / "uploads")
    assert repository.list_jobs(1) == [newest]
    assert repository.get_upload("missing") is None
    assert not repository.mark_running("missing")
    assert repository.result_paths("missing") is None
    with pytest.raises(ValueError):
        repository.list_jobs(0)
    with pytest.raises(ValueError):
        repository.update_progress(newest["id"], "read", float("nan"))


def test_concurrent_claims_run_job_once(repository: JobRepository, tmp_path: Path) -> None:
    job, _ = repository.create_job("claim", "a.pdf", "pdf", b"a", tmp_path / "uploads")
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: repository.mark_running(job["id"]), range(16)))
    assert sum(claims) == 1


def test_milestone_one_database_migration_preserves_existing_job(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'queued',
                current_stage TEXT NOT NULL DEFAULT 'queued', progress REAL NOT NULL DEFAULT 0,
                error TEXT, file_name TEXT NOT NULL, file_type TEXT NOT NULL,
                file_hash TEXT NOT NULL UNIQUE, upload_path TEXT NOT NULL,
                created_at TEXT NOT NULL, warnings TEXT NOT NULL DEFAULT '[]'
            );
            INSERT INTO jobs(id,file_name,file_type,file_hash,upload_path,created_at)
            VALUES ('old','old.pdf','pdf','old_hash','/missing','2026-10-24');
        """)
    migrated = JobRepository(path)
    migrated.initialize()
    migrated.initialize()
    old = migrated.get_job("old")
    assert old is not None
    assert old["id"] == "old"
    assert old["stats"] is None
    assert old["error_code"] is None
    assert old["warnings"] == []
