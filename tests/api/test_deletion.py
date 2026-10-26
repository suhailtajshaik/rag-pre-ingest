import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from rag_pre_ingest.config import Settings
from rag_pre_ingest.main import create_app


def test_delete_queued_job_removes_upload_and_releases_hash(tmp_path: Path) -> None:
    data = io.BytesIO()
    Image.new("RGB", (10, 10)).save(data, format="PNG")
    with TestClient(create_app(Settings(data_dir=tmp_path, worker_enabled=False))) as client:
        first = client.post("/v1/documents", files={"file": ("a.png", data.getvalue())}).json()
        job_id = first["job_id"]
        assert client.delete(f"/v1/jobs/{job_id}").status_code == 204
        assert client.get(f"/v1/jobs/{job_id}").status_code == 404
        assert client.get("/v1/jobs").json() == []
        assert not list((tmp_path / "uploads").iterdir())
        assert client.delete(f"/v1/jobs/{job_id}").status_code == 404
        second = client.post("/v1/documents", files={"file": ("a.png", data.getvalue())})
        assert second.status_code == 202
        assert second.json()["job_id"] != job_id
