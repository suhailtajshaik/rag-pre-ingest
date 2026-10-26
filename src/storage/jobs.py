"""SQLite job persistence with serialized duplicate detection and safe file names."""

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast
from uuid import uuid4


class JobRecord(TypedDict):
    id: str
    status: str
    current_stage: str
    progress: float
    error: str | None
    error_code: str | None
    file_name: str
    file_type: str
    file_hash: str
    created_at: str
    warnings: list[dict[str, object]]
    stats: dict[str, object] | None


class JobRepository:
    """One connection per operation; a database transaction owns upload publication."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'queued',
                    current_stage TEXT NOT NULL DEFAULT 'queued',
                    progress REAL NOT NULL DEFAULT 0,
                    error TEXT,
                    file_name TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    file_hash TEXT NOT NULL UNIQUE,
                    upload_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    warnings TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS rejections (
                    id INTEGER PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    code TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)")}
            for name in ("stats", "result_path", "markdown_path", "error_code"):
                if name not in columns:
                    connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} TEXT")

    def create_job(
        self,
        file_hash: str,
        file_name: str,
        file_type: str,
        content: bytes,
        uploads_dir: Path,
        warnings: list[dict[str, object]] | None = None,
    ) -> tuple[JobRecord, bool]:
        """Publish one file and job, or return its existing job without writing."""
        upload_path: Path | None = None
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM jobs WHERE file_hash = ?", (file_hash,)
                ).fetchone()
                if existing is not None:
                    return self._record(existing), True

                job_id = uuid4().hex
                uploads_dir.mkdir(parents=True, exist_ok=True)
                candidate = uploads_dir / job_id
                # Assign only after exclusive creation: never remove an existing file.
                with candidate.open("xb") as stream:
                    upload_path = candidate
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                connection.execute(
                    """INSERT INTO jobs (
                        id, file_name, file_type, file_hash, upload_path, created_at, warnings
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        job_id,
                        file_name,
                        file_type,
                        file_hash,
                        str(upload_path.resolve()),
                        datetime.now(UTC).isoformat(),
                        json.dumps(warnings or []),
                    ),
                )
                row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
                assert row is not None
                result = self._record(row)
            return result, False
        except BaseException:
            if upload_path is not None:
                upload_path.unlink(missing_ok=True)
            raise

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return None if row is None else self._record(row)

    def record_rejection(self, filename: str, code: str, message: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO rejections (file_name, code, message, created_at)
                VALUES (?, ?, ?, ?)""",
                (filename, code, message, datetime.now(UTC).isoformat()),
            )

    def list_jobs(self, limit: int = 50) -> list[JobRecord]:
        if limit < 1:
            raise ValueError("limit must be positive")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._record(row) for row in rows]

    def queued_jobs(self) -> list[JobRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at, id"
            ).fetchall()
            return [self._record(row) for row in rows]

    def get_upload(self, job_id: str) -> bytes | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT upload_path FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return Path(row["upload_path"]).read_bytes()

    def upload_path(self, job_id: str) -> Path | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT upload_path FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return None if row is None else Path(row["upload_path"])

    def delete_job(self, job_id: str) -> bool:
        """Delete metadata and its unique hash so an intentional reupload is possible."""
        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            return cursor.rowcount == 1

    def mark_running(self, job_id: str) -> bool:
        """Claim a queued job once, even when two workers see the same queue."""
        with self._connection() as connection:
            cursor = connection.execute(
                """UPDATE jobs SET status = 'running', current_stage = 'read',
                progress = 0, error = NULL, error_code = NULL
                WHERE id = ? AND status = 'queued'""",
                (job_id,),
            )
            return cursor.rowcount == 1

    def update_progress(self, job_id: str, stage: str, progress: float) -> None:
        if not 0 <= progress <= 1:
            raise ValueError("progress must be between 0 and 1")
        with self._connection() as connection:
            connection.execute(
                """UPDATE jobs SET current_stage = ?, progress = ?
                WHERE id = ? AND status = 'running'""",
                (stage, progress, job_id),
            )

    def finish_job(
        self,
        job_id: str,
        result_path: Path | str,
        markdown_path: Path | str,
        stats: dict[str, object],
        warnings: list[dict[str, object]],
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """UPDATE jobs SET status = 'done', current_stage = 'done', progress = 1,
                result_path = ?, markdown_path = ?, stats = ?, warnings = ?,
                error = NULL, error_code = NULL WHERE id = ? AND status = 'running'""",
                (
                    str(Path(result_path).resolve()),
                    str(Path(markdown_path).resolve()),
                    json.dumps(stats),
                    json.dumps(warnings),
                    job_id,
                ),
            )

    def fail_job(self, job_id: str, code: str, message: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """UPDATE jobs SET status = 'failed', current_stage = 'failed',
                error_code = ?, error = ? WHERE id = ? AND status IN ('queued', 'running')""",
                (code, message, job_id),
            )

    def result_paths(self, job_id: str) -> tuple[Path, Path] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT result_path, markdown_path FROM jobs WHERE id = ? AND status = 'done'",
                (job_id,),
            ).fetchone()
        if row is None or row["result_path"] is None or row["markdown_path"] is None:
            return None
        return Path(row["result_path"]), Path(row["markdown_path"])

    def recover_running(self) -> None:
        """Requeue interrupted work during single-service startup."""
        with self._connection() as connection:
            connection.execute(
                """UPDATE jobs SET status = 'queued', current_stage = 'queued', progress = 0,
                error = NULL, error_code = NULL WHERE status = 'running'"""
            )

    @staticmethod
    def _record(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            id=row["id"],
            status=row["status"],
            current_stage=row["current_stage"],
            progress=row["progress"],
            error=row["error"],
            error_code=row["error_code"],
            file_name=row["file_name"],
            file_type=row["file_type"],
            file_hash=row["file_hash"],
            created_at=row["created_at"],
            warnings=cast(list[dict[str, object]], json.loads(row["warnings"])),
            stats=None
            if row["stats"] is None
            else cast(dict[str, object], json.loads(row["stats"])),
        )
