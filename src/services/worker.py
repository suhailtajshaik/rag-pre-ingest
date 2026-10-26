"""Durable single-worker queue with an isolated, bounded processing subprocess."""

import asyncio
import json
import logging
import multiprocessing
import os
import shutil
import tempfile
import threading
import time
from datetime import UTC, datetime
from multiprocessing.process import BaseProcess
from pathlib import Path

from rag_pre_ingest.config import Settings
from rag_pre_ingest.models.document import DocumentResult
from rag_pre_ingest.storage.jobs import JobRecord, JobRepository

logger = logging.getLogger(__name__)


def process_document(job: JobRecord, data: bytes, output: str, settings: Settings) -> None:
    from rag_pre_ingest.pipeline.engine import run_pipeline

    settings = Settings.model_validate(settings.model_dump())
    result = run_pipeline(
        data,
        job["file_type"],
        job["file_name"],
        job["file_hash"],
        job["id"],
        settings,
        Path(output).parent,
    )
    Path(output).write_text(result.model_dump_json(), encoding="utf-8")
    # This target only runs in an isolated child. Retire any timed-out OCR threads.
    os._exit(0)


def interrupted_result(
    job: JobRecord, directory: Path, code: str, duration: float
) -> "DocumentResult":
    """Recover the last durable page checkpoint after a bounded child exits."""
    from rag_pre_ingest.models.document import Document, DocumentResult, Stats, Warning

    result = None
    for name in ("result.json", "checkpoint.json"):
        checkpoint = directory / name
        if checkpoint.is_file():
            try:
                result = DocumentResult.model_validate_json(checkpoint.read_text(encoding="utf-8"))
                break
            except ValueError:
                logger.warning("Ignoring incomplete processing checkpoint")
    if result is None:
        result = DocumentResult(
            document=Document(
                id=job["id"],
                file_name=job["file_name"],
                file_type=job["file_type"],
                file_hash=job["file_hash"],
                page_count=0,
                processed_at=datetime.now(UTC),
            ),
            stats=Stats(),
            markdown="",
            pages=[],
        )
    result.warnings.append(
        Warning(
            code=code,
            message=(
                "The job time limit was reached; completed content has been preserved."
                if code == "job_timeout"
                else "Processing was interrupted; completed content has been preserved."
            ),
        )
    )
    if not result.markdown.strip() and not any(w.code == "empty_document" for w in result.warnings):
        result.warnings.append(
            Warning(code="empty_document", message="No readable text was recovered.")
        )
    result.stats.duration_seconds = duration
    return result


class Worker:
    def __init__(self, settings: Settings, repository: JobRepository) -> None:
        self.settings = settings
        self.repository = repository
        self.stopping = False
        self.active_process: BaseProcess | None = None
        self.progress_path: Path | None = None
        self.lock = threading.RLock()
        self.active_job_id: str | None = None

    async def run(self) -> None:
        self.repository.recover_running()
        while not self.stopping:
            jobs = await asyncio.to_thread(self.repository.queued_jobs)
            if not jobs:
                await asyncio.sleep(0.2)
                continue
            for job in jobs:
                if self.stopping:
                    break
                task = asyncio.create_task(asyncio.to_thread(self.process, job))
                while not task.done():
                    await asyncio.sleep(0.2)
                    if self.progress_path is not None:
                        try:
                            update = json.loads(self.progress_path.read_text())
                            await asyncio.to_thread(
                                self.repository.update_progress,
                                job["id"],
                                update["stage"],
                                update["progress"],
                            )
                        except (OSError, ValueError, KeyError):
                            pass
                await task

    def process(self, job: JobRecord) -> None:
        with self.lock:
            if not self.repository.mark_running(job["id"]):
                return
        started = time.monotonic()
        try:
            with self.lock:
                if self.repository.get_job(job["id"]) is None:
                    return
                data = self.repository.get_upload(job["id"])
                if data is None:
                    raise FileNotFoundError("Upload is missing.")
            self.repository.update_progress(job["id"], "direct_read", 0.1)
            with tempfile.TemporaryDirectory(prefix="rag-job-") as directory:
                output = Path(directory) / "result.json"
                self.progress_path = Path(directory) / "progress.json"
                context = multiprocessing.get_context("spawn")
                process = context.Process(
                    target=process_document,
                    args=(job, data, str(output), self.settings),
                    daemon=True,
                )
                with self.lock:
                    if self.repository.get_job(job["id"]) is None or self.stopping:
                        return
                    self.active_job_id = job["id"]
                    self.active_process = process
                    process.start()
                process.join(self.settings.per_job_timeout_seconds)
                timed_out = process.is_alive()
                if timed_out:
                    process.terminate()
                    process.join(5)
                    if process.is_alive():
                        process.kill()
                        process.join()
                if self.stopping:
                    return
                from rag_pre_ingest.models.document import DocumentResult, Warning

                if timed_out or process.exitcode != 0 or not output.exists():
                    result = interrupted_result(
                        job,
                        Path(directory),
                        "job_timeout" if timed_out else "processing_interrupted",
                        time.monotonic() - started,
                    )
                else:
                    result = DocumentResult.model_validate_json(output.read_text(encoding="utf-8"))
                result.warnings.extend(Warning.model_validate(item) for item in job["warnings"])
                from collections import Counter

                result.stats.warnings.total = len(result.warnings)
                result.stats.warnings.by_code = dict(Counter(w.code for w in result.warnings))
                with self.lock:
                    if self.repository.get_job(job["id"]) is None:
                        return
                    destination = self.settings.data_dir / "results" / job["id"]
                    destination.mkdir(parents=True, exist_ok=True)
                    for preview in Path(directory).glob("*.png"):
                        shutil.copy2(preview, destination / preview.name)
                    result_path = destination / "result.json"
                    markdown_path = destination / "document.md"
                    result_path.write_text(result.model_dump_json(), encoding="utf-8")
                    markdown_path.write_text(result.markdown, encoding="utf-8")
                    self.repository.finish_job(
                        job["id"],
                        result_path,
                        markdown_path,
                        result.stats.model_dump(),
                        [warning.model_dump() for warning in result.warnings],
                    )
        except Exception:
            if self.stopping:
                return
            logger.exception("Job processing failed")
            self.repository.fail_job(
                job["id"], "processing_failed", "Processing could not complete."
            )
        finally:
            with self.lock:
                self.active_process = None
                self.active_job_id = None
                self.progress_path = None

    def stop(self) -> None:
        with self.lock:
            self.stopping = True
            if self.active_process is not None and self.active_process.is_alive():
                self.active_process.terminate()
