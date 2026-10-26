from pathlib import Path
from unittest.mock import patch

from rag_pre_ingest.config import Settings
from rag_pre_ingest.pipeline.readers import read_document
from rag_pre_ingest.services.worker import process_document
from rag_pre_ingest.storage.jobs import JobRepository


def test_spawned_job_refreshes_missing_settings_defaults(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    repository.initialize()
    job, _ = repository.create_job("hash", "a.pdf", "pdf", b"pdf", tmp_path / "uploads")
    older = Settings()
    del older.__dict__["ocr_min_region_width"]
    result = read_document(b"bad", "pdf", "a.pdf", "hash", job["id"])
    with patch("rag_pre_ingest.pipeline.engine.run_pipeline", return_value=result) as run:
        with patch("rag_pre_ingest.services.worker.os._exit"):
            process_document(job, b"pdf", str(tmp_path / "result.json"), older)
    assert run.call_args.args[-2].ocr_min_region_width == 1260
    assert (tmp_path / "result.json").is_file()
